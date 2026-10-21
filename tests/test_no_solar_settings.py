"""Exercise no-solar settings persistence through the actual HA HTTP handlers."""
from __future__ import annotations

import ast
import asyncio
import copy
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/power_sync"


def _namespace():
    values = {"Any": object, "_LOGGER": logging.getLogger(__name__)}
    for node in ast.parse((COMPONENT / "const.py").read_text()).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    try:
                        values[target.id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        if isinstance(node.value, ast.Name) and node.value.id in values:
                            values[target.id] = values[node.value.id]
    values["SOLAR_FORECAST_PROVIDERS"] = {"solcast": "Solcast", "open_meteo": "Open-Meteo", "volcast": "Volcast"}
    return values


def _load_methods(path, class_name, names, namespace):
    tree = ast.parse(path.read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    methods = [copy.deepcopy(node) for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    class RemoveLocalImports(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            return None if node.level else node
    body = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *methods]
    module = RemoveLocalImports().visit(ast.Module(body=body, type_ignores=[]))
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return SimpleNamespace(**{name: namespace[name] for name in names})


def _view():
    namespace = _namespace()
    namespace.update({
        "_normalize_solar_forecast_provider": lambda value: value if value in ("solcast", "open_meteo", "volcast") else "solcast",
        "_has_external_solcast_integration": lambda hass: True,
        "_has_external_volcast_integration": lambda hass: False,
        "web": SimpleNamespace(json_response=lambda data, status=200: SimpleNamespace(data=data, status=status)),
    })
    # Execute the actual config predicate alongside the request handlers.
    tree = ast.parse((COMPONENT / "__init__.py").read_text())
    predicate = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_solcast_builtin_configured")
    exec(compile(ast.Module(body=[predicate], type_ignores=[]), "predicate", "exec"), namespace)
    methods = _load_methods(COMPONENT / "__init__.py", "WeatherSolcastSettingsView", ("get", "post"), namespace)
    namespace["_SOLCAST_SETTINGS_KEYS"] = tuple(namespace[n] for n in (
        "CONF_NO_SOLAR_INSTALLED", "CONF_SOLCAST_ENABLED", "CONF_SOLCAST_API_KEY", "CONF_SOLCAST_RESOURCE_ID", "CONF_SOLCAST_ESTIMATE_TYPE", "CONF_SOLAR_FORECAST_PROVIDER"
    ))
    entry = SimpleNamespace(entry_id="battery-only", data={"no_solar_installed": False}, options={
        "solar_forecast_provider": "volcast", "solcast_enabled": True,
        "solcast_api_key": "saved-key", "solcast_resource_id": "saved-resource",
        "unrelated_option": 123,
    })
    reloads = []
    def update(item, **kwargs):
        for key, val in kwargs.items():
            setattr(item, key, val)
    async def reload(entry_id):
        reloads.append(entry_id)
    tasks = []
    def schedule(coro):
        tasks.append(asyncio.create_task(coro))
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_entries=lambda domain: [entry], async_update_entry=update, async_reload=reload),
        config=SimpleNamespace(components=set()),
        data={"power_sync": {entry.entry_id: {}}}, async_create_task=schedule,
    )
    return methods, SimpleNamespace(_hass=hass), entry, reloads, tasks


async def _post(methods, view, payload):
    async def json():
        return payload
    result = await methods.post(view, SimpleNamespace(json=json))
    await asyncio.sleep(0)
    return result


def test_no_solar_roundtrip_keeps_forecast_credentials_and_reloads():
    methods, view, entry, reloads, _ = _view()
    async def scenario():
        before = await methods.get(view, None)
        assert before.data["no_solar_installed"] is False
        assert before.data["no_solar_installed_supported"] is True
        response = await _post(methods, view, {"no_solar_installed": True})
        assert response.status == 200
        assert entry.options["no_solar_installed"] is True
        assert "no_solar_installed" not in entry.data
        assert entry.options["solcast_api_key"] == "saved-key"
        assert entry.options["solcast_resource_id"] == "saved-resource"
        assert entry.options["solar_forecast_provider"] == "volcast"
        assert entry.options["unrelated_option"] == 123
        confirmed = await methods.get(view, None)
        assert confirmed.data["no_solar_installed"] is True
        assert confirmed.data["solar_forecast_source"] == "no_solar_installed"
        assert confirmed.data["solar_forecast_active"] is False
        assert confirmed.data["solcast_enabled"] is True  # saved enablement survives
        assert reloads == [entry.entry_id]
        assert (await _post(methods, view, {"no_solar_installed": False})).status == 200
        restored = await methods.get(view, None)
        assert restored.data["solar_forecast_active"] is True
        assert restored.data["solar_forecast_source"] == "integration"
        assert reloads == [entry.entry_id, entry.entry_id]
    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", ["false", "true", 0, 1, None, [], {}])
def test_no_solar_http_requires_explicit_boolean_without_mutation(invalid):
    methods, view, entry, reloads, _ = _view()
    before = copy.deepcopy(entry)
    result = asyncio.run(_post(methods, view, {"no_solar_installed": invalid}))
    assert result.status == 400
    assert entry == before
    assert reloads == []


def test_legacy_mobile_weather_save_does_not_clear_no_solar_confirmation():
    methods, view, entry, reloads, _ = _view()
    entry.options["no_solar_installed"] = True
    response = asyncio.run(_post(methods, view, {"weather_location": "Brisbane"}))
    assert response.status == 200
    assert entry.options["no_solar_installed"] is True
    assert entry.options["weather_location"] == "Brisbane"
    assert reloads == []


@pytest.mark.parametrize("confirmed", [True, False])
def test_ha_options_save_no_solar_with_credentials(confirmed):
    namespace = _namespace()
    namespace["_normalize_optional_entity"] = lambda entity: entity or None
    methods = _load_methods(COMPONENT / "config_flow.py", "PowerSyncOptionsFlow", ("async_step_weather_options",), namespace)
    removed = []
    view = SimpleNamespace(_from_menu=True, _remove_legacy_data_keys=lambda keys: removed.extend(keys), _save_and_finish=lambda opts: opts)
    saved = asyncio.run(methods.async_step_weather_options(view, {
        "no_solar_installed": confirmed, "solcast_enabled": True,
        "solcast_api_key": " saved-key ", "solcast_resource_id": " saved-resource ",
    }))
    assert saved["no_solar_installed"] is confirmed
    assert saved["solcast_enabled"] is True
    assert saved["solcast_api_key"] == "saved-key"
    assert saved["solcast_resource_id"] == "saved-resource"
    assert "no_solar_installed" in removed
