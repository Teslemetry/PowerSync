"""Device-scoped Envoy DPEL transactions, ownership, and restart recovery."""
import asyncio
import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/power_sync"


@pytest.fixture
def module(monkeypatch):
    for name, path in (("power_sync", ROOT), ("power_sync.inverters", ROOT / "inverters")):
        package = types.ModuleType(name)
        package.__path__ = [str(path)]
        monkeypatch.setitem(sys.modules, name, package)
    name = "power_sync.inverters.enphase_envoy"
    monkeypatch.delitem(sys.modules, name, raising=False)
    # Constructor imports storage lazily; tests use an in-memory durable store.
    storage = types.ModuleType("homeassistant.helpers.storage")
    class Store:
        def __init__(self, hass, version, key):
            self.hass, self.key = hass, key
        async def async_load(self):
            return self.hass.disk.get(self.key)
        async def async_save(self, data):
            if self.hass.fail_save:
                raise RuntimeError("storage failure")
            from copy import deepcopy
            self.hass.disk[self.key] = deepcopy(data)
    storage.Store = Store
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.storage", storage)
    result = importlib.import_module(name)
    # Keep bounded readback failures quick without changing the service timing.
    monkeypatch.setattr(result, "_READBACK_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(result, "_READBACK_POLL_SECONDS", 0.001)
    yield result
    sys.modules.pop(name, None)


class Hass:
    def __init__(self, enabled="off", mode="Production", limit=4200):
        self.data, self.disk, self.calls = {}, {}, []
        self.fail_save = False
        self.fail_call = None
        self.ignore_call = None
        self.values = {
            "switch.envoy_123_dpel_enabled": SimpleNamespace(state=enabled, attributes={}),
            "select.envoy_123_dpel_mode": SimpleNamespace(state=mode, attributes={"options": ["Export", "Production"]}),
            "number.envoy_123_dpel_limit": SimpleNamespace(state=str(limit), attributes={"unit_of_measurement": "W", "min": 0, "max": 1000000, "step": 1}),
        }
        self.states = SimpleNamespace(get=self.values.get)
        self.services = SimpleNamespace(async_call=self.call)
    async def call(self, domain, service, data, *, blocking):
        assert blocking
        self.calls.append((domain, service, data))
        if self.fail_call == len(self.calls):
            raise RuntimeError("write failed")
        if self.ignore_call == len(self.calls):
            return
        state = self.values[data["entity_id"]]
        state.state = str(data["value"]) if domain == "number" else data.get("option", "on" if service == "turn_on" else "off")


def controller(module, hass, model="export"):
    result = module.EnphaseEnvoyController(hass, "envoy_123", "entry", model)
    result._gateway = ["device-envoy-123", "config-envoy-123"]
    result._valid_identity = lambda: True
    return result


def test_native_zero_export_and_exact_baseline_restore(module):
    h = Hass()
    c = controller(module, h)
    async def run():
        assert await c.curtail(home_load_w=900)
        assert c._read() == {"enabled": True, "mode": "Export", "limit": 0}
        assert (await c.get_status()).is_curtailed
        count = len(h.calls)
        assert await c.curtail(home_load_w=2000)
        assert len(h.calls) == count  # Native load following needs no target rewrites.
        assert await c.restore()
        assert c._read() == {"enabled": False, "mode": "Production", "limit": 4200}
    asyncio.run(run())
    assert all(call[2]["entity_id"].startswith(("select.envoy_123_", "number.envoy_123_", "switch.envoy_123_")) for call in h.calls)
    assert all(call[0] != "enphase_envoy" for call in h.calls)


@pytest.mark.parametrize("enabled", ["on", "off"])
def test_restart_restores_previous_mode_limit_and_enable(module, enabled):
    h = Hass(enabled=enabled, mode="Export", limit=2800)
    async def run():
        assert await controller(module, h).curtail()
        h.data = {}  # A new controller must recover from durable storage.
        c = controller(module, h)
        assert await c.restore()
        assert c._read() == {"enabled": enabled == "on", "mode": "Export", "limit": 2800}
    asyncio.run(run())


def test_production_following_and_manual_shutdown_are_not_export_limits(module):
    h = Hass()
    c = controller(module, h, "production")
    async def run():
        assert not await c.curtail()
        assert h.calls == []
        assert await c.curtail(home_load_w=1650)
        assert c._read() == {"enabled": True, "mode": "Production", "limit": 1650}
        assert await c.curtail(home_load_w=0)
        assert c._read()["limit"] == 0
        assert await c.restore()
    asyncio.run(run())


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 1000001])
def test_invalid_production_target_cannot_write(module, value):
    h = Hass()
    assert not asyncio.run(controller(module, h, "production").curtail(home_load_w=value))
    assert h.calls == []


@pytest.mark.parametrize("key", ["enabled", "mode", "limit"])
def test_unavailable_controls_cannot_write(module, key):
    h = Hass()
    c = controller(module, h)
    h.values[c.entities[key]].state = "unavailable"
    assert not asyncio.run(c.curtail())
    assert h.calls == []


def test_wrong_units_and_gateway_identity_cannot_write(module):
    h = Hass()
    c = controller(module, h)
    h.values[c.entities["limit"]].attributes["unit_of_measurement"] = "%"
    assert not asyncio.run(c.curtail())
    h.values[c.entities["limit"]].attributes["unit_of_measurement"] = "W"
    c._valid_identity = lambda: False
    assert not asyncio.run(c.curtail())
    assert h.calls == []


def test_external_change_prevents_curtail_and_restore(module):
    h = Hass()
    c = controller(module, h)
    async def run():
        assert await c.curtail()
        h.values[c.entities["limit"]].state = "123"
        count = len(h.calls)
        assert not await c.restore()
        assert not await c.curtail()
        assert len(h.calls) == count
    asyncio.run(run())


@pytest.mark.parametrize("fail_at", [1, 2, 3])
def test_partial_write_retains_durable_baseline_for_retry(module, fail_at):
    h = Hass()
    h.fail_call = fail_at
    c = controller(module, h)
    async def run():
        assert not await c.curtail()
        h.fail_call = None
        h.data = {}
        c2 = controller(module, h)
        assert await c2.restore()
        assert c2._read() == {"enabled": False, "mode": "Production", "limit": 4200}
    asyncio.run(run())


def test_acknowledgement_without_readback_is_failure(module):
    h = Hass()
    h.ignore_call = 1
    c = controller(module, h)
    assert not asyncio.run(c.curtail())
    assert len(h.calls) == 1


def test_storage_failure_prevents_command(module):
    h = Hass()
    h.fail_save = True
    assert not asyncio.run(controller(module, h).curtail())
    assert h.calls == []


def test_concurrent_controller_instances_share_transaction_lock(module):
    h = Hass()
    a, b = controller(module, h), controller(module, h)
    async def run():
        assert await asyncio.gather(a.curtail(), b.curtail()) == [True, True]
        assert len(h.calls) == 3
        assert await b.restore()
        assert a._read() == {"enabled": False, "mode": "Production", "limit": 4200}
    asyncio.run(run())


def test_pending_unacknowledged_command_is_explicitly_restored(module):
    h = Hass()
    h.ignore_call = 1
    c = controller(module, h)
    async def run():
        assert not await c.curtail()
        assert c._shared["record"]["pending"] is not None
        count = len(h.calls)
        h.ignore_call = None
        assert await c.restore()
        assert len(h.calls) > count  # Must write the baseline despite old HA values.
        assert c._shared["record"] is None
    asyncio.run(run())


def test_replaced_gateway_cannot_inherit_restore_journal(module):
    h = Hass()
    c = controller(module, h)
    async def run():
        assert await c.curtail()
        count = len(h.calls)
        c._gateway = ["different-device", "different-config"]
        assert not await c.restore()
        assert not await c.curtail()
        assert len(h.calls) == count
    asyncio.run(run())


def test_adjusting_an_enabled_production_cap_never_disables_dpel(module):
    h = Hass(enabled="on", mode="Production", limit=4200)
    c = controller(module, h, "production")
    async def run():
        assert await c.curtail(home_load_w=900)
        assert await c.curtail(home_load_w=1800)
        assert not any(service == "turn_off" for _, service, _ in h.calls)
        assert await c.restore()
        assert c._read() == {"enabled": True, "mode": "Production", "limit": 4200}
    asyncio.run(run())


def test_registry_requires_all_controls_on_the_same_envoy(module, monkeypatch):
    h = Hass()
    c = module.EnphaseEnvoyController(h, "envoy_123", "entry")
    entries = {eid: SimpleNamespace(platform="enphase_envoy", device_id="device123", config_entry_id="envoy-config", unique_id=f"123_{eid.split('_123_', 1)[1]}") for eid in c.entities.values()}
    def lookup(domain, platform, unique_id):
        return next((eid for eid, e in entries.items() if eid.startswith(domain + ".") and e.platform == platform and e.unique_id == unique_id), None)
    registry = SimpleNamespace(async_get=entries.get, async_get_entity_id=lookup)
    helpers = types.ModuleType("homeassistant.helpers")
    helpers.entity_registry = SimpleNamespace(async_get=lambda hass: registry)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers)
    assert c._read() is not None
    assert c._gateway == ["device123", "envoy-config"]
    entries[c.entities["mode"]].device_id = "other-envoy"
    assert c._read() is None
    entries[c.entities["mode"]].device_id = "device123"
    entries[c.entities["mode"]].platform = "template"
    assert c._read() is None


def test_another_powersync_entry_cannot_take_over_the_same_gateway(module):
    h = Hass()
    first = controller(module, h)
    other = module.EnphaseEnvoyController(h, "envoy_123", "other-entry", "production")
    other._gateway = first._gateway
    other._valid_identity = lambda: True
    async def run():
        assert await first.curtail()
        count = len(h.calls)
        assert not await other.curtail(home_load_w=2000)
        assert not await other.restore()
        assert len(h.calls) == count
        assert await first.restore()
        assert await other.curtail(home_load_w=2000)
    asyncio.run(run())


def test_zero_demand_preserves_native_export_and_shutdown_is_explicit(module):
    h = Hass()
    c = controller(module, h)
    async def run():
        assert await c.curtail(home_load_w=0)
        assert c._read() == {"enabled": True, "mode": "Export", "limit": 0}
        assert await c.curtail(shutdown=True)
        assert c._read() == {"enabled": True, "mode": "Production", "limit": 0}
        assert await c.restore()
    asyncio.run(run())


def test_factory_selects_envoy_bridge_without_host_or_credentials(module):
    import ast
    from typing import Optional
    tree = ast.parse((ROOT / "inverters/__init__.py").read_text())
    factory = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "get_inverter_controller")
    ns = {"__package__": "power_sync.inverters", "Optional": Optional,
          "InverterController": object}
    exec(compile(ast.Module(body=[factory], type_ignores=[]), "factory", "exec"), ns)
    h = Hass()
    result = ns["get_inverter_controller"](brand="enphase_envoy", host="", entity_prefix="envoy_123", hass=h, entry_id="entry")
    assert isinstance(result, module.EnphaseEnvoyController)
    assert result.model == "export"
    assert result.host == ""
    assert ns["get_inverter_controller"](brand="enphase_envoy", host="") is None


def test_registry_resolves_actual_dpel_switch_slug_and_renamed_select(module, monkeypatch):
    h = Hass()
    h.values["switch.envoy_123_dpel"] = h.values.pop("switch.envoy_123_dpel_enabled")
    h.values["select.solar_export_mode"] = h.values.pop("select.envoy_123_dpel_mode")
    c = module.EnphaseEnvoyController(h, "envoy_123", "entry")
    entries = {
        "switch.envoy_123_dpel": SimpleNamespace(platform="enphase_envoy", device_id="d", config_entry_id="e", unique_id="123_dpel_enabled"),
        "select.solar_export_mode": SimpleNamespace(platform="enphase_envoy", device_id="d", config_entry_id="e", unique_id="123_dpel_mode"),
        "number.envoy_123_dpel_limit": SimpleNamespace(platform="enphase_envoy", device_id="d", config_entry_id="e", unique_id="123_dpel_limit"),
    }
    def lookup(domain, platform, unique_id):
        return next((eid for eid, e in entries.items() if eid.startswith(domain + ".") and e.platform == platform and e.unique_id == unique_id), None)
    helpers = types.ModuleType("homeassistant.helpers")
    helpers.entity_registry = SimpleNamespace(async_get=lambda hass: SimpleNamespace(async_get=entries.get, async_get_entity_id=lookup))
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers)
    async def run():
        assert await c.curtail()
        assert c.entities["enabled"] == "switch.envoy_123_dpel"
        assert c.entities["mode"] == "select.solar_export_mode"
        assert await c.restore()
    asyncio.run(run())


class DeferredReadbackHass(Hass):
    """Envoy setters can return while HA's debounced refresh is queued.

    The upstream number/select/switch setters await async_request_refresh(),
    which returns immediately during DataUpdateCoordinator's 10s cooldown.
    Keep device acceptance and eventual entity publication separate here.
    """

    def __init__(self, *, first_refresh_immediate=False):
        super().__init__()
        self.first_refresh_immediate = first_refresh_immediate
        self.published = 0

    async def call(self, domain, service, data, *, blocking):
        assert blocking
        self.calls.append((domain, service, data))
        state = self.values[data["entity_id"]]
        value = (str(data["value"]) if domain == "number"
                 else data.get("option", "on" if service == "turn_on" else "off"))

        def publish():
            state.state = value
            self.published += 1

        if self.first_refresh_immediate and len(self.calls) == 1:
            publish()
        else:
            asyncio.get_running_loop().call_later(0.01, publish)


@pytest.mark.parametrize("first_refresh_immediate", [False, True])
def test_deferred_refresh_confirms_each_write_and_restore(module, first_refresh_immediate):
    h = DeferredReadbackHass(first_refresh_immediate=first_refresh_immediate)
    c = controller(module, h)

    async def run():
        assert await c.curtail()
        assert h.published == len(h.calls) == 3
        assert c._read() == {"enabled": True, "mode": "Export", "limit": 0}
        assert c._shared["record"]["pending"] is None
        h.data = {}  # Reload recovers the durable baseline before delayed restore.
        restored = controller(module, h)
        assert await restored.restore()
        assert h.published == len(h.calls)
        assert c._read() == {"enabled": False, "mode": "Production", "limit": 4200}
        assert restored._shared["record"] is None

    asyncio.run(run())


def test_deferred_restore_timeout_preserves_journal_for_reload(module):
    h = Hass()
    c = controller(module, h)

    async def run():
        assert await c.curtail()
        h.ignore_call = len(h.calls) + 1
        assert not await c.restore()
        assert c._shared["record"]["pending"] is not None
        h.ignore_call = None
        h.data = {}
        restored = controller(module, h)
        assert await restored.restore()
        assert restored._read() == {"enabled": False, "mode": "Production", "limit": 4200}
        assert restored._shared["record"] is None

    asyncio.run(run())


@pytest.mark.parametrize("conflict", ["external_write", "unavailable"])
def test_readback_wait_stops_before_next_write_on_conflict(module, conflict):
    h = Hass()
    h.ignore_call = 1
    c = controller(module, h)

    async def run():
        def conflict_during_wait():
            key = "mode" if conflict == "external_write" else "limit"
            h.values[c.entities[key]].state = "Export" if key == "mode" else "unavailable"

        asyncio.get_running_loop().call_later(0.01, conflict_during_wait)
        assert not await c.curtail()
        assert len(h.calls) == 1
        assert c._shared["record"]["pending"] is not None

    asyncio.run(run())


def test_cancelled_readback_wait_keeps_pending_for_reload_restore(module):
    h = Hass()
    h.ignore_call = 1
    c = controller(module, h)

    async def run():
        task = asyncio.create_task(c.curtail())
        while not h.calls:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert c._shared["record"]["pending"] is not None
        assert not c._shared["lock"].locked()
        h.ignore_call = None
        h.data = {}
        restored = controller(module, h)
        assert await restored.restore()
        assert restored._read() == {"enabled": False, "mode": "Production", "limit": 4200}
        assert restored._shared["record"] is None

    asyncio.run(run())
