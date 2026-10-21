"""Mobile requests use the native service, and status never contacts Tesla."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1] / 'custom_components/power_sync'
VIN = '5YJ3E1EA7KF000001'
SETTINGS = dict(enabled=True, lowerChargeLimit=50, upperChargeLimit=80)


@pytest.fixture
def view(monkeypatch):
    package = ModuleType('native_solar_api_probe')
    package.__path__ = [str(ROOT)]
    package.get_tesla_ev_api_token = lambda *args: ('secret', 'teslemetry')
    monkeypatch.setitem(sys.modules, package.__name__, package)
    modules = {}
    for name in ('teslemetry_solar', 'teslemetry_solar_api'):
        spec = importlib.util.spec_from_file_location(f'{package.__name__}.{name}', ROOT / f'{name}.py')
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, module)
        spec.loader.exec_module(module)
        modules[name] = module
    native = modules['teslemetry_solar']
    class Store:
        async def async_load(self): return None
        async def async_save(self, value): pass
    gate = native.SolarOwnership(Store())
    async def ownership(*args): return gate
    monkeypatch.setattr(modules['teslemetry_solar_api'], 'ownership', ownership)
    http = ModuleType('homeassistant.components.http')
    class Base:
        def json(self, data, status_code=200): return status_code, data
    http.HomeAssistantView = Base
    monkeypatch.setitem(sys.modules, http.__name__, http)
    exceptions = ModuleType('homeassistant.exceptions')
    exceptions.HomeAssistantError = type('HomeAssistantError', (Exception,), {})
    monkeypatch.setitem(sys.modules, exceptions.__name__, exceptions)
    entry = SimpleNamespace(entry_id='one', title='Home', data={}, options={})
    calls, views = [], []
    async def service(*args, **kwargs):
        calls.append((args, kwargs))
        return {'settings': SETTINGS, 'readback_confirmed': True, 'powersync_control_blocked': True}
    hass = SimpleNamespace(data={'power_sync': {'one': {}}},
        config_entries=SimpleNamespace(async_entries=lambda _: [entry]),
        services=SimpleNamespace(async_call=service),
        http=SimpleNamespace(register_view=views.append))
    modules['teslemetry_solar_api'].register_http_view(hass)
    return views[0], gate, entry, calls


def request(body=None):
    async def json(): return body
    return SimpleNamespace(query={'vin': VIN}, json=json)


@pytest.mark.asyncio
async def test_get_returns_uncertain_hold_without_any_vehicle_or_service_request(view):
    api, gate, entry, calls = view
    await gate.load()
    await gate.hold(VIN, {'status': 'unconfirmed'})
    entry.options['no_solar_installed'] = True
    status, result = await api.get(request())
    assert api.requires_auth and status == 200
    assert calls == []
    assert result['entries'][0]['status'] == 'unconfirmed'
    assert result['entries'][0]['powersync_control_blocked']
    assert result['entries'][0]['no_solar_installed']
    assert result['entries'][0]['cached_settings'] is None
    assert 'secret' not in str(result)


@pytest.mark.asyncio
async def test_post_read_and_write_delegate_to_existing_interlocked_services(view):
    api, _, _, calls = view
    status, result = await api.post(request({'action': 'read', 'entry_id': 'one', 'vin': VIN.lower()}))
    assert status == 200 and result['readback_confirmed']
    assert calls[0] == (('power_sync', 'get_teslemetry_charge_on_solar', {'entry_id': 'one', 'vin': VIN}),
                        {'blocking': True, 'return_response': True})
    await api.post(request({'action': 'write', 'entry_id': 'one', 'vin': VIN,
                            'settings': SETTINGS, 'confirm_eligible': 'true'}))
    assert calls[1][0][1] == 'set_teslemetry_charge_on_solar'
    assert calls[1][0][2]['confirm_eligible'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [None, [], {},
    {'action': 'read', 'entry_id': 'missing', 'vin': VIN},
    {'action': 'wake', 'entry_id': 'one', 'vin': VIN},
    {'action': 'write', 'entry_id': 'one', 'vin': VIN, 'settings': {**SETTINGS, 'lowerChargeLimit': 81}},
])
async def test_invalid_requests_never_reach_a_service(view, body):
    api, _, _, calls = view
    status, result = await api.post(request(body))
    assert status == 400 and not result['success'] and calls == []
