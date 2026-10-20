"""Run Amber mode dispatch through the actual PowerSync optimiser coordinator."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest

from test_amber_smartshift import modules, native, automatic
from test_battery_export_allowed_slots import _execution_coordinator
from test_battery_export_allowed_slots import opt_module


@pytest.fixture
def stack(native, opt_module, monkeypatch):
    automatic(native)
    adapter = native.modules.controls.AmberOptimizerController(native.coordinator)
    opt = _execution_coordinator(opt_module, adapter, soc=.60)
    opt.battery_system = "amber_smartshift"
    opt.energy_coordinator = native.coordinator
    opt.hass = native.hass
    opt.entry_id = native.entry.entry_id
    opt._entry = native.entry
    opt._last_update_time = native.modules.clock
    native.coordinator.entry_data()["optimization_coordinator"] = opt
    monkeypatch.setattr(opt_module.dt_util, "now", lambda *args: native.modules.clock)
    monkeypatch.setattr(opt_module.dt_util, "utcnow", lambda *args: native.modules.clock)
    opt._grid_charge_blackout_active_now = lambda: False
    opt._amber_spike_protected_slots = lambda *args: [False]
    opt._scheduled_ev_preserve_active = lambda: False
    opt._should_block_export_for_demand = lambda: False
    opt._config.allow_grid_charge = True
    return native, opt


@pytest.mark.asyncio
@pytest.mark.parametrize("action,mode", [("charge", "charge"), ("export", "discharge"), ("idle", "preserve-charge"), ("self_consumption", "self-consume")])
async def test_optimizer_action_reaches_amber_and_records_only_reported_mode(stack, action, mode):
    native, opt = stack
    opt._last_executed_action = None
    request = SimpleNamespace(action=action, power_w=5000 if action in ("charge", "export") else 0, timestamp=native.modules.clock)
    await opt._execute_optimizer_action(request)
    assert native.client.override is not None
    assert native.client.override["value"] == mode
    assert opt._last_executed_action == action
    assert not any(call[0] == "reserve" for call in native.client.calls)


@pytest.mark.asyncio
async def test_rejected_amber_command_does_not_advance_optimizer_marker(stack):
    native, opt = stack
    native.client.drop_readback = True
    opt._last_executed_action = "idle"
    await opt._execute_optimizer_action(SimpleNamespace(action="self_consumption", power_w=0, timestamp=native.modules.clock))
    assert opt._last_executed_action == "idle"
    assert native.coordinator.command_state == "unconfirmed"


@pytest.mark.asyncio
async def test_owned_consume_renews_only_when_lease_nears_expiry(stack):
    native, opt = stack
    opt._last_executed_action = None
    request = SimpleNamespace(action="self_consumption", power_w=0, timestamp=native.modules.clock)
    await opt._execute_optimizer_action(request)
    await opt._execute_optimizer_action(request)
    assert len([c for c in native.client.calls if c[0] == "add"]) == 1
    native.client.override["validTo"] = (native.modules.clock + timedelta(minutes=4)).isoformat()
    await native.coordinator._async_update_data()
    await opt._execute_optimizer_action(request)
    assert len([c for c in native.client.calls if c[0] == "add"]) == 2


@pytest.mark.asyncio
async def test_optimizer_cannot_replace_app_override(stack):
    native, opt = stack
    native.client.override = {"overrideId": "app", "value": "preserve-charge", "validTo": (native.modules.clock + timedelta(minutes=30)).isoformat()}
    await native.coordinator._async_update_data()
    await opt._execute_optimizer_action(SimpleNamespace(action="charge", power_w=5000, timestamp=native.modules.clock))
    assert not native.client.calls


@pytest.mark.asyncio
async def test_cached_path_renews_through_the_actual_safety_gates(stack):
    native, opt = stack
    opt._enabled = True
    opt._last_executed_action = None
    request = SimpleNamespace(action="self_consumption", power_w=0, timestamp=native.modules.clock)
    await opt._execute_optimizer_action(request)
    native.client.override["validTo"] = (native.modules.clock + timedelta(minutes=4)).isoformat()
    await native.coordinator._async_update_data()
    opt._execute_lock = asyncio.Lock()
    opt._optimization_lock = asyncio.Lock()
    opt._get_current_action = lambda: request
    opt._cached_solar_export_has_settled_feed_in_price = lambda *args: True
    opt.get_api_data = lambda: {}
    opt.async_set_updated_data = lambda data: None
    await opt._execute_cached_current_action_if_changed()
    assert len([c for c in native.client.calls if c[0] == "add"]) == 2


@pytest.mark.asyncio
async def test_shorter_safe_duration_replaces_a_longer_automatic_lease(stack):
    native, opt = stack
    await native.coordinator.command("charge", duration=10, source="optimizer")
    await native.coordinator.command("charge", duration=1, source="optimizer")
    interval = native.client.calls[-1]
    assert interval[0] == "add"
    start, end = map(native.modules.runtime.timestamp, interval[-2:])
    assert end - start == timedelta(minutes=1)
