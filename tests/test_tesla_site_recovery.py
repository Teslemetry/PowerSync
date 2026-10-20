"""Tesla site recovery after changing the battery backend (no HA or network)."""
from __future__ import annotations

import ast
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components/power_sync"


def flow_namespace():
    tree = ast.parse((COMPONENT / "config_flow.py").read_text())
    flow = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PowerSyncOptionsFlow")
    wanted = {
        "_save_battery_system_selection", "_async_route_to_provider_options",
        "async_step_tesla_site", "_save_connection_and_reload", "_get_option",
        "_effective_battery_system",
        "async_step_tesla_connection", "async_step_powersync_token", "async_step_teslemetry_token",
    }
    nodes = [n for n in tree.body if isinstance(n, ast.AnnAssign)
             and isinstance(n.target, ast.Name) and n.target.id == "BATTERY_SYSTEM_CONNECTION_KEYS"]
    nodes += [n for n in flow.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in wanted]
    module = ast.Module(body=nodes, type_ignores=[])
    namespace = {n.id: n.id.removeprefix("CONF_").removeprefix("BATTERY_SYSTEM_").lower()
                 for n in ast.walk(module) if isinstance(n, ast.Name) and n.id.isupper()}
    namespace.update(Any=object, FlowResult=object, __name__="tesla_recovery_test", __package__="tesla_recovery_test")
    namespace.update(
        TESLA_PROVIDER_POWERSYNC="powersync", TESLA_PROVIDER_TESLEMETRY="teslemetry",
        TESLA_PROVIDER_FLEET_API="fleet_api", TESLA_EV_API_PROVIDER_NONE="none",
        TESLA_EV_API_PROVIDER_FLEET_API="fleet_api", TESLA_EV_API_PROVIDER_TESLEMETRY="teslemetry",
        validate_force_discharge_prices=lambda *args: (0.55, 25),
        normalize_powerwall_gateway_host=lambda value: value,
        _detect_tesla_ev_integrations=lambda hass: {"tesla_fleet": True, "teslemetry": True},
    )
    exec(compile(module, "config_flow.py", "exec"), namespace)
    return namespace


def make_flow(namespace, data):
    entry = SimpleNamespace(entry_id="entry-a", data=dict(data), options={})
    def update(entry, **changes):
        entry.__dict__.update(changes)
    class Flow:
        def __init__(self):
            self.config_entry = entry
            self.reloads = 0
            self.hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update))
        async def async_step_amber_options(self):
            return {"step_id": "amber_options"}
        async def async_step_tesla_site(self):
            return {"step_id": "tesla_site"}
        def _schedule_entry_reload(self):
            self.reloads += 1
        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}
        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}
    for name in ("_save_battery_system_selection", "_async_route_to_provider_options", "_save_connection_and_reload", "_get_option", "_effective_battery_system"):
        setattr(Flow, name, namespace[name])
    return Flow()


@pytest.mark.asyncio
async def test_return_from_smartshift_requires_tesla_site_before_completion():
    ns = flow_namespace()
    flow = make_flow(ns, {"battery_system": "tesla", "tesla_energy_site_id": "123", "electricity_provider": "amber"})
    flow._save_battery_system_selection("amber_smartshift")
    assert "tesla_energy_site_id" not in flow.config_entry.data
    flow._save_battery_system_selection("tesla")
    result = await flow._async_route_to_provider_options()
    assert result["step_id"] == "tesla_site"
    assert flow.reloads == 0


@pytest.mark.asyncio
async def test_existing_tesla_site_keeps_existing_options_route():
    flow = make_flow(flow_namespace(), {"battery_system": "tesla", "tesla_energy_site_id": "123", "electricity_provider": "amber"})
    assert (await flow._async_route_to_provider_options())["step_id"] == "amber_options"


@pytest.mark.asyncio
async def test_smartshift_options_do_not_request_a_tesla_site():
    flow = make_flow(flow_namespace(), {"battery_system": "amber_smartshift", "electricity_provider": "amber"})
    assert (await flow._async_route_to_provider_options())["step_id"] == "amber_options"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["fleet_api", "powersync", "teslemetry"])
async def test_all_tesla_provider_options_reach_site_recovery(provider):
    ns = flow_namespace()
    flow = make_flow(ns, {"battery_system": "tesla", "teslemetry_api_token": "psync_test" if provider == "powersync" else "test"})
    if provider == "fleet_api":
        result = await ns["async_step_tesla_connection"](flow, {"tesla_api_provider": provider})
    else:
        result = await ns[f"async_step_{provider}_token"](flow, {})
    assert result["step_id"] == "tesla_site"
    assert flow.reloads == 0


@pytest.fixture
def recovery(monkeypatch):
    ns = flow_namespace()
    calls = []
    response = {"success": True, "sites": [
        {"energy_site_id": 123, "site_name": "Home"},
        {"energy_site_id": 456, "site_name": "Other"},
    ], "base_url": "https://fleet-api.prd.ap.vn.cloud.tesla.com"}
    async def validate(hass, token):
        calls.append(token)
        return response
    ns.update(
        vol=SimpleNamespace(Schema=lambda value: value, Required=lambda value: value),
        SelectSelector=lambda value: value, SelectSelectorConfig=dict, SelectOptionDict=dict,
        SelectSelectorMode=SimpleNamespace(DROPDOWN="dropdown"),
        validate_powersync_token=validate, validate_teslemetry_token=validate,
        validate_fleet_api_token=validate,
    )
    package = ModuleType("tesla_recovery_test")
    package.get_tesla_api_token = lambda hass, entry: (entry.data.get("teslemetry_api_token"), entry.data["tesla_api_provider"])
    monkeypatch.setitem(sys.modules, "tesla_recovery_test", package)
    flow = make_flow(ns, {"battery_system": "tesla", "tesla_api_provider": "fleet_api", "teslemetry_api_token": "test"})
    flow.async_step_tesla_site = ns["async_step_tesla_site"].__get__(flow)
    return SimpleNamespace(flow=flow, calls=calls, response=response)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["fleet_api", "powersync", "teslemetry"])
async def test_recovery_validates_account_and_saves_selected_site_before_reload(recovery, provider):
    flow = recovery.flow
    flow.config_entry.data["tesla_api_provider"] = provider
    # Cover an upgraded entry that has already lost its site, including stale options.
    flow.config_entry.options["tesla_energy_site_id"] = "old-site"
    form = await flow.async_step_tesla_site()
    choices = form["data_schema"]["tesla_energy_site_id"]["options"]
    assert {item["value"] for item in choices} == {"123", "456"}
    assert flow.reloads == 0
    bad = await flow.async_step_tesla_site({"tesla_energy_site_id": "amber-site"})
    assert bad["errors"]["tesla_energy_site_id"] == "invalid_tesla_site"
    assert "tesla_energy_site_id" not in flow.config_entry.data
    assert flow.reloads == 0
    result = await flow.async_step_tesla_site({"tesla_energy_site_id": "456"})
    assert result["type"] == "create_entry"
    assert flow.config_entry.data["tesla_energy_site_id"] == "456"
    assert flow.config_entry.options["tesla_energy_site_id"] == "456"
    assert flow.config_entry.data["fleet_api_base_url"] == recovery.response["base_url"]
    assert flow.reloads == 1
    assert recovery.calls == ["test"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["invalid_auth", "cannot_connect", "no_energy_sites", "missing_token", "empty_sites"])
async def test_recovery_does_not_reload_without_valid_site(recovery, failure):
    if failure == "missing_token":
        recovery.flow.config_entry.data.pop("teslemetry_api_token")
    else:
        recovery.response.clear()
        recovery.response.update({"success": failure == "empty_sites", "sites": []})
        if failure != "empty_sites":
            recovery.response["error"] = failure
    form = await recovery.flow.async_step_tesla_site({"tesla_energy_site_id": "123"})
    assert form["errors"]["base"] == ("invalid_auth" if failure == "missing_token" else "no_energy_sites" if failure == "empty_sites" else failure)
    assert recovery.flow.reloads == 0
    assert "tesla_energy_site_id" not in recovery.flow.config_entry.data


@pytest.mark.asyncio
async def test_account_change_invalidates_previously_discovered_sites(recovery):
    await recovery.flow.async_step_tesla_site()
    recovery.flow.config_entry.data["teslemetry_api_token"] = "replacement"
    recovery.response["sites"] = [{"energy_site_id": 789}]
    form = await recovery.flow.async_step_tesla_site({"tesla_energy_site_id": "123"})
    assert form["errors"]["tesla_energy_site_id"] == "invalid_tesla_site"
    assert recovery.flow.reloads == 0
    assert recovery.calls == ["test", "replacement"]


def test_startup_with_missing_site_fails_before_token_or_coordinator_access():
    tree = ast.parse((COMPONENT / "__init__.py").read_text())
    setup = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_setup_entry")
    branch = next(n.orelse for n in ast.walk(setup) if isinstance(n, ast.If) and any(
        isinstance(item, ast.Assign) and isinstance(item.value, ast.Call)
        and isinstance(item.value.func, ast.Name) and item.value.func.id == "get_tesla_api_token"
        for item in n.orelse))
    class NotReady(Exception):
        pass
    def unexpected(*args, **kwargs):
        pytest.fail("Missing site must fail before credentials or coordinator access")
    ns = {"entry": SimpleNamespace(data={}), "CONF_TESLA_ENERGY_SITE_ID": "tesla_energy_site_id",
          "ConfigEntryNotReady": NotReady, "get_tesla_api_token": unexpected, "hass": object()}
    with pytest.raises(NotReady, match="Tesla API connection"):
        exec(compile(ast.Module(body=branch, type_ignores=[]), "__init__.py", "exec"), ns)
