"""Loopback-only mobile contract harness: real coordinator, no hardware executor."""
import ast
import asyncio
import importlib
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import runpy
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
fixture = runpy.run_path(str(ROOT / 'tests/test_optimization_price_source.py'))
fixture['_install_ha_stubs']()
fixture['_install_power_sync_stubs']()
module = importlib.import_module('power_sync.optimization.coordinator')
entry = SimpleNamespace(entry_id='mobile-test', data={}, options={})

def persist(target, data=None, options=None):
    if data is not None:
        target.data = data
    if options is not None:
        target.options = options

hass = SimpleNamespace(data={}, config_entries=SimpleNamespace(async_update_entry=persist))
# The dispatch side is a fake and optimisation is deliberately disabled.
import sys
import types
dispatcher = types.ModuleType('homeassistant.helpers.dispatcher')
dispatcher.async_dispatcher_send = lambda *args: None
sys.modules[dispatcher.__name__] = dispatcher

restore = next(n for n in ast.walk(ast.parse((ROOT / 'custom_components/power_sync/optimization/coordinator.py').read_text()))
               if isinstance(n, ast.Assign) and any(ast.unparse(t) == 'self._config.amber_forecast_confidence_enabled' for t in n.targets)
               and isinstance(n.value, ast.Compare))

def recreate():
    coordinator = module.OptimizationCoordinator(hass=hass, entry_id=entry.entry_id, battery_system='tesla', battery_controller=SimpleNamespace(), entry=entry)
    exec(compile(ast.Module(body=[restore], type_ignores=[]), '<real-config-restore>', 'exec'), {
        'self': coordinator, 'CONF_AMBER_FORECAST_CONFIDENCE_ENABLED': 'amber_forecast_confidence_enabled',
    })
    coordinator._config.profit_max_enabled = True
    coordinator.async_set_updated_data = lambda data: None
    coordinator.get_api_data = lambda: {
        'success': True, 'enabled': False, 'optimizer_available': True,
        'cost_function': 'cost', 'profit_max_enabled': coordinator.profit_max_mode,
        'amber_forecast_confidence_enabled': coordinator.amber_forecast_confidence_enabled,
        'settings_schema': module.optimizer_settings_schema(),
        'config': {'backup_reserve': 0.2, 'hardware_backup_reserve': 0.2,
                   'interval_minutes': 5, 'horizon_hours': 48},
    }
    return coordinator

coordinator = recreate()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def reply(self, value, status=200):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        self.reply(coordinator.get_api_data())
    def do_POST(self):
        global coordinator
        if self.path == '/restart':
            coordinator = recreate()
            return self.reply({'success': True})
        settings = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        result = asyncio.run(coordinator.set_settings(settings))
        self.reply(result, 200 if result['success'] else 400)

server = HTTPServer(('127.0.0.1', 0), Handler)
print(server.server_address[1], flush=True)
server.serve_forever()
