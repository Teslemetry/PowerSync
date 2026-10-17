"""Behavioral proof for PV-only stopping and durable exact restoration."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "custom_components/power_sync"
pkg = ModuleType("_pvfeature")
pkg.__path__ = [str(PACKAGE)]
sys.modules[pkg.__name__] = pkg

def load(name):
    spec = importlib.util.spec_from_file_location(f"_pvfeature.{name}", PACKAGE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

pv = load("solar_production")
native = load("solar_production_native")

class Store:
    def __init__(self):
        self.data = None
        self.fail = False
        self.saves = []
    async def async_load(self):
        return deepcopy(self.data)
    async def async_save(self, value):
        if self.fail:
            raise OSError("storage unavailable")
        self.data = deepcopy(value)
        self.saves.append(deepcopy(value))

class Target:
    refresh = False
    def __init__(self, store, value=80):
        self.store = store
        self.value = value
        self.calls = []
        self.fail = False
        self.accept_without_apply = False
        self.unavailable = False
        self.after_read = None
    async def read(self):
        result = None if self.unavailable else {"value": self.value}
        if self.after_read:
            self.after_read()
        return result
    def stopped(self, original):
        return {"value": 0}
    async def write(self, state):
        assert self.store.data["records"], "snapshot must be durable before mutation"
        self.calls.append(deepcopy(state))
        if not self.fail and not self.accept_without_apply:
            self.value = state["value"]
        return not self.fail


def rig():
    store = Store()
    targets = {"a": Target(store), "b": Target(store, 65)}
    allowed = {"yes": True}
    manager = pv.ProductionStopManager(store, lambda identity: targets[identity["id"]], lambda: allowed["yes"])
    return manager, store, targets, allowed


def run(coro):
    return asyncio.run(coro)

@pytest.mark.parametrize("price", [0, 0.001, 20, None, "unknown", float("nan"), float("inf"), -float("inf"), True])
def test_only_finite_strict_negative_price_authorizes_new_stop(price):
    manager, store, targets, _ = rig()
    run(manager.update(price, [{"id": "a"}]))
    assert targets["a"].calls == []
    assert not store.saves

@pytest.mark.parametrize("restore_price", [0, 25, None, float("nan")])
def test_negative_import_independent_of_export_and_soc_restores_exact_prior_limit(restore_price):
    manager, store, targets, _ = rig()
    async def scenario():
        await manager.update(-0.01, [{"id": "a"}])
        assert manager.status == "limit_confirmed"
        assert manager.device_confirmed
        assert manager.physical_converged is None
        await manager.update(-10, [{"id": "a"}])
        assert len(targets["a"].calls) == 1
        assert store.data["records"][0]["original"] == {"value": 80}
        await manager.update(restore_price, [{"id": "a"}])
        assert targets["a"].value == 80
        assert not manager.owns_control
        assert manager.status == "normal"
    run(scenario())


def test_storage_failure_prevents_first_stop_and_followup_write():
    manager, store, targets, _ = rig()
    async def scenario():
        store.fail = True
        with pytest.raises(OSError):
            await manager.update(-5, [{"id": "a"}])
        assert targets["a"].calls == []
        # A failed save must not let the next tick use an in-memory-only record.
        with pytest.raises(OSError):
            await manager.update(-5, [{"id": "a"}])
        assert targets["a"].calls == []
    run(scenario())


def test_failed_restore_is_retained_and_retried_across_restart():
    manager, store, targets, allowed = rig()
    async def scenario():
        await manager.update(-5, [{"id": "a"}])
        targets["a"].fail = True
        await manager.update(0, [{"id": "a"}])
        assert manager.status == "restore_pending"
        assert manager.owns_control and store.data["records"]
        targets["a"].fail = False
        restarted = pv.ProductionStopManager(store, lambda identity: targets[identity["id"]], lambda: allowed["yes"])
        await restarted.update(None, [])
        assert not restarted.owns_control
        assert targets["a"].value == 80
    run(scenario())


def test_acknowledgement_without_readback_never_reports_confirmed():
    manager, _, targets, _ = rig()
    targets["a"].accept_without_apply = True
    run(manager.update(-5, [{"id": "a"}]))
    assert manager.acknowledged and manager.command_attempted
    assert not manager.device_confirmed
    assert manager.status == "stop_pending"
    assert manager.physical_converged is None


def test_monitoring_denial_and_permission_change_during_read_send_no_commands():
    manager, _, targets, allowed = rig()
    async def scenario():
        allowed["yes"] = False
        await manager.update(-5, [{"id": "a"}])
        assert not targets["a"].calls
        allowed["yes"] = True
        targets["a"].after_read = lambda: allowed.update(yes=False)
        await manager.update(-5, [{"id": "a"}])
        assert not targets["a"].calls
    run(scenario())


def test_price_expiry_during_snapshot_prevents_stop():
    manager, _, targets, _ = rig()
    current = {"negative": True}
    manager.stop_permitted = lambda: current["negative"]
    targets["a"].after_read = lambda: current.update(negative=False)
    run(manager.update(-5, [{"id": "a"}]))
    assert not targets["a"].calls


def test_external_change_is_preserved_and_not_recaptured_as_new_baseline():
    manager, store, targets, _ = rig()
    async def scenario():
        await manager.update(-5, [{"id": "a"}])
        targets["a"].value = 40
        await manager.update(-5, [{"id": "a"}])
        assert manager.status == "external_control"
        assert manager.suspended
        await manager.update(0, [])
        assert targets["a"].value == 40
        assert not manager.owns_control
        assert store.data["records"] == []
    run(scenario())


def test_manual_takeover_restores_owned_state_and_suppresses_reentry_until_price_recovers():
    manager, _, targets, _ = rig()
    async def scenario():
        await manager.update(-5, [{"id": "a"}])
        assert await manager.release(suspend=True)
        targets["a"].value = 60  # manual limit
        await manager.update(-5, [{"id": "a"}])
        assert targets["a"].value == 60
        await manager.update(0, [{"id": "a"}])
        await manager.update(-5, [{"id": "a"}])
        assert targets["a"].value == 0
        await manager.release()
        assert targets["a"].value == 60
    run(scenario())


def test_multiple_devices_keep_independent_baselines_and_failed_stop_does_not_restore_other_owner():
    manager, _, targets, _ = rig()
    targets["b"].value = 0  # somebody else already stopped B
    async def scenario():
        await manager.update(-5, [{"id": "a"}, {"id": "b"}])
        assert not manager.device_confirmed
        await manager.update(10, [])
        assert targets["a"].value == 80
        assert targets["b"].value == 0
        assert not targets["b"].calls
    run(scenario())


def test_device_configuration_change_restores_old_before_stopping_new():
    manager, _, targets, _ = rig()
    async def scenario():
        await manager.update(-5, [{"id": "a"}])
        await manager.update(-5, [{"id": "b"}])
        assert targets["a"].value == 80
        assert targets["b"].value == 0
        await manager.shutdown()
        assert targets["b"].value == 65
        await manager.update(-5, [{"id": "a"}])
        assert targets["a"].value == 80
    run(scenario())


def test_physical_proof_requires_fresh_post_command_pv_not_zero_grid_export():
    manager, _, _, _ = rig()
    manager.observe_power(2500, datetime.now(timezone.utc))
    run(manager.update(-5, [{"id": "a"}]))
    before = manager.last_command_at - timedelta(seconds=1)
    manager.observe_power(0, before)
    assert manager.physical_converged is None
    after = datetime.now(timezone.utc)
    manager.observe_power(2500, after)
    assert manager.physical_converged is False
    manager.observe_power(25, after)
    assert manager.physical_converged is True
    manager.observe_power(float("nan"), after)
    assert manager.physical_converged is None


def interval(price=-5, **changes):
    item = {"type": "CurrentInterval", "channelType": "general", "perKwh": price,
            "startTime": "2026-10-17T05:00:00+00:00", "endTime": "2026-10-17T05:30:00+00:00"}
    item.update(changes)
    return item

NOW = datetime(2026, 10, 17, 5, 10, tzinfo=timezone.utc)

@pytest.mark.parametrize("item", [
    interval(type="ForecastInterval"), interval(channelType="feedIn"),
    interval(startTime="2026-10-17T05:15:00Z"), interval(endTime="2026-10-17T05:10:00Z"),
    interval(startTime="2026-10-17T05:00:00"), interval(endTime=None), interval(float("nan")),
])
def test_invalid_expired_future_or_feed_in_prices_cannot_authorize_production_stop(item):
    assert pv.current_import_price((SimpleNamespace(data={"current": [item]}),), NOW) is None


def test_current_retail_interval_without_feed_in_is_sufficient_and_localvolts_duration_supported():
    for item in (interval(), interval(endTime=None, duration=30)):
        assert pv.current_import_price((SimpleNamespace(data={"current": [item]}),), NOW) == -5
    assert pv.current_import_price((SimpleNamespace(data={"current": [interval(-5), interval(5)]}),), NOW) is None
    assert pv.current_import_price((SimpleNamespace(last_update_success=False, data={"current": [interval()]}),), NOW) is None


def test_planner_zeros_only_explicitly_covered_pv_at_strict_negative_import():
    solar = [5, 6, 7, 8]
    assert pv.planned_solar(solar, [-0.1, 0, 1], enabled=True) == [0, 6, 7, 8]
    assert pv.planned_solar(solar, [-0.1] * 4, enabled=False) == solar
    assert solar == [5, 6, 7, 8]


def test_enphase_zero_production_never_uses_zero_export_or_firmware_fallbacks():
    settings = {"enable": False, "export_limit": True, "limit_value_W": 5000.0,
                "enable_dynamic_limiting": True, "relay_config": {"default_pct_limit": 100, "limit_levels": []},
                "slew_rate": 100, "installed_capacity": 10000, "installer_setting": 27}
    original = deepcopy(settings)
    posts = []
    async def connect(): return True
    async def get(): return {"dynamic_pel_settings": deepcopy(settings)}
    async def post(endpoint, payload):
        posts.append((endpoint, deepcopy(payload)))
        settings.update(payload["dynamic_pel_settings"])
        return True, 200
    c = SimpleNamespace(connect=connect, _get_dpel_settings=get, _post=post, ENDPOINT_DPEL="/ivp/ss/dpel",
                        _dpel_relay_config=lambda pct: {"default_pct_limit": pct, "limit_levels": []})
    target = native.NativeProductionTarget(c, {"brand": "enphase"})
    store = Store()
    manager = pv.ProductionStopManager(store, lambda identity: target, lambda: True)
    async def scenario():
        await manager.update(-5, [{"brand": "enphase"}])
        assert manager.device_confirmed and target.refresh
        payload = posts[-1][1]["dynamic_pel_settings"]
        assert payload["enable"] is True
        assert payload["export_limit"] is False
        assert payload["limit_value_W"] == 0
        assert payload["enable_dynamic_limiting"] is True
        assert payload["installed_capacity"] == 10000
        # Installer metadata changed while curtailed; restore only our controls.
        settings["installed_capacity"] = 12000
        await manager.update(0, [])
        for key, value in original.items():
            assert settings[key] == (12000 if key == "installed_capacity" else value)
        assert all(endpoint == "/ivp/ss/dpel" for endpoint, _ in posts)
    run(scenario())


def test_enphase_unsupported_or_rejected_production_surface_sends_no_export_substitute():
    posts = []
    async def connect(): return True
    async def get(): return {"dynamic_pel_settings": {"enable": True, "export_limit": 3000}}
    async def post(*args): posts.append(args); return False, 400
    target = native.NativeProductionTarget(SimpleNamespace(connect=connect, _get_dpel_settings=get, _post=post), {"brand": "enphase"})
    store = Store()
    manager = pv.ProductionStopManager(store, lambda identity: target, lambda: True)
    run(manager.update(-5, [{"brand": "enphase"}]))
    assert not posts and not manager.owns_control and not manager.device_confirmed


def test_fronius_simple_mode_uses_real_zero_production_and_recovers_partial_write():
    registers = {10: 0, 11: 7500, 12: 25}
    writes = []
    fail = {"once": True}
    async def connect(): return True
    async def read(address, count=1): return [registers[address]]
    async def write(address, value):
        writes.append((address, value))
        if address == 12 and fail["once"]:
            fail["once"] = False
            return False
        registers[address] = value
        return True
    c = SimpleNamespace(connect=connect, _read_register=read, _write_register=write,
                        REG_WMAXLIM_ENA=10, REG_WMAXLIMPCT=11, REG_WMAXLIMPCT_RVRT=12)
    target = native.NativeProductionTarget(c, {"brand": "fronius"})
    store = Store()
    manager = pv.ProductionStopManager(store, lambda identity: target, lambda: True)
    async def scenario():
        await manager.update(-5, [{"brand": "fronius"}])
        assert not manager.device_confirmed and manager.owns_control
        assert registers[11] == 0
        # Recover even if stop failed halfway, without assuming restore-to-100%.
        await manager.update(0, [])
        assert registers == {10: 0, 11: 7500, 12: 25}
        assert not manager.owns_control
        await manager.update(-5, [{"brand": "fronius"}])
        assert manager.device_confirmed
        assert registers == {10: 1, 11: 0, 12: 0}
        assert (10, 0) not in writes[-3:]  # no transient unthrottling
    run(scenario())


@pytest.mark.parametrize("model, mode, expected", [("sg5.0rs",207,True),("sh10rs",207,False),(None,207,False),("sg5.0rs",65535,False)])
def test_sungrow_generation_stop_is_scoped_to_readable_standalone_sg(model, mode, expected):
    registers = {5005: mode}
    writes = []
    async def connect(): return True
    async def read(address, count=1): return [registers[address]]
    async def write(address, value): writes.append((address,value)); registers[address]=value; return True
    c = SimpleNamespace(model=model,production_stop_model_supported=model == "sg5.0rs",connect=connect,_read_register=read,_write_register=write,
                        REGISTER_RUN_MODE=5005,RUN_MODE_ENABLED=207,RUN_MODE_SHUTDOWN=206)
    target = native.NativeProductionTarget(c, {"brand":"sungrow"})
    store=Store();manager=pv.ProductionStopManager(store,lambda _:target,lambda:True)
    async def scenario():
        await manager.update(-5,[{"brand":"sungrow"}])
        assert manager.device_confirmed is expected
        if expected:
            assert writes == [(5005,206)]
            await manager.update(0,[])
            assert writes == [(5005,206),(5005,207)]
        else:
            assert not writes
    run(scenario())


def test_solaredge_restores_previous_active_limit_and_requires_restart_readback():
    limit={"value":67};calls=[]
    async def connect():return True
    async def read():return limit["value"]
    async def write(value):calls.append(value);limit["value"]=value;return True
    target=native.NativeProductionTarget(SimpleNamespace(connect=connect,_get_active_power_limit=read,_set_active_power_limit=write),{"brand":"solaredge"})
    manager=pv.ProductionStopManager(Store(),lambda _:target,lambda:True)
    async def scenario():
        await manager.update(-5,[{"brand":"solaredge"}])
        await manager.update(0,[])
        assert calls==[0,67]
    run(scenario())


def test_unimplemented_native_brands_never_issue_export_or_battery_commands():
    async def connect(): raise AssertionError("unsupported must not connect")
    for brand in ("goodwe","goodwe_entity","huawei","foxess","alphaess","solax"):
        assert brand not in native.NATIVE_BRANDS


@pytest.mark.parametrize("brand", ["enphase","sungrow","fronius","solaredge","zeversolar","sigenergy","foxess","huawei","goodwe","solax","alphaess","other"])
def test_explicit_pv_entity_supports_every_brand_without_touching_export_or_battery(brand):
    states={f"switch.{brand}_pv_enable":SimpleNamespace(state="on",attributes={})}
    calls=[]
    async def call(domain, service, data, blocking):
        calls.append((domain,service,data))
        if domain=="switch":states[data["entity_id"]].state="off" if service=="turn_off" else "on"
    hass=SimpleNamespace(states=SimpleNamespace(get=states.get),services=SimpleNamespace(async_call=call))
    identity={"entity_id":next(iter(states))}
    target=pv.EntityProductionTarget(hass,identity["entity_id"])
    manager=pv.ProductionStopManager(Store(),lambda _:target,lambda:True)
    async def scenario():
        await manager.update(-5,[identity])
        assert manager.device_confirmed
        await manager.update(0,[])
        assert states[identity["entity_id"]].state=="on"
        mutations=[(domain,service) for domain,service,_ in calls if domain!="homeassistant"]
        assert mutations==[("switch","turn_off"),("switch","turn_on")]
    run(scenario())


def test_number_production_control_requires_zero_and_restores_exact_nondefault_value():
    states={"number.pv_limit":SimpleNamespace(state="43",attributes={"min":0,"max":100})}
    async def call(domain,service,data,blocking):
        if domain=="number":states[data["entity_id"]].state=str(data["value"])
    hass=SimpleNamespace(states=SimpleNamespace(get=states.get),services=SimpleNamespace(async_call=call))
    target=pv.EntityProductionTarget(hass,"number.pv_limit")
    identity={"entity_id":"number.pv_limit"}
    manager=pv.ProductionStopManager(Store(),lambda _:target,lambda:True)
    async def scenario():
        await manager.update(-5,[identity])
        assert states[identity["entity_id"]].state=="0.0"
        await manager.update(0,[])
        assert states[identity["entity_id"]].state=="43.0"
        states[identity["entity_id"]].attributes["min"]=1
        assert pv.validate_production_entities(hass,[identity["entity_id"]])
        await manager.update(-5,[identity])
        assert not manager.device_confirmed
    run(scenario())


def test_sigenergy_pv_only_limit_preserves_ems_and_export_and_recovers_when_mode_changes():
    from contextlib import asynccontextmanager
    registers = {40029:[1],40031:[3],40036:[0,7500],40038:[0,5000]}
    writes=[]
    @asynccontextmanager
    async def transaction():yield
    async def connect():return True
    async def read(address,count=1):return registers[address]
    async def read_pv():return registers[40036][0]*65536+registers[40036][1]
    async def write(address,value):writes.append((address,value));registers[address]=value;return True
    c=SimpleNamespace(connect=connect,_modbus_transaction=transaction,_read_holding_registers=read,
                      _get_current_pv_limit=read_pv,_write_holding_registers=write,
                      _from_unsigned32=lambda n:[n>>16,n&65535],REG_REMOTE_EMS_ENABLE=40029,
                      REG_REMOTE_EMS_CONTROL_MODE=40031,REG_PV_MAX_POWER_LIMIT=40036)
    identity={"brand":"sigenergy"};store=Store()
    manager=pv.ProductionStopManager(store,lambda _:native.NativeProductionTarget(c,identity),lambda:True)
    async def scenario():
        await manager.update(-5,[identity])
        assert manager.device_confirmed and registers[40036]==[0,0]
        assert registers[40029]==[1] and registers[40031]==[3] and registers[40038]==[0,5000]
        registers[40031]=[2]  # optimiser returns to self-consumption
        await manager.update(-5,[identity])
        assert not manager.device_confirmed  # PV register is inactive in mode 2
        await manager.update(0,[])
        assert registers[40036]==[0,7500]
        assert all(address==40036 for address,_ in writes)
        assert not manager.owns_control
    run(scenario())


def test_zeversolar_reads_and_restores_disabled_limit_exactly():
    from contextlib import asynccontextmanager
    fields={"enlim":"off","drm_sp":"16.67","ac_sys":"5000","ac_value1":"62","ac_value2":"0","ac_value3":"0","ac_mode":"1","em_ml":"0"}
    original=deepcopy(fields);posts=[]
    class Response:
        status=200
        async def text(self):
            lines=["0"]*16
            lines[8]="1" if fields["enlim"]=="on" else "0"
            for i,k in ((9,"drm_sp"),(10,"ac_sys"),(11,"ac_value1"),(12,"ac_value2"),(13,"ac_value3"),(14,"ac_mode"),(15,"em_ml")):
                lines[i]=fields[k]
            return "\n".join(lines)
    class Session:
        @asynccontextmanager
        async def get(self,url):yield Response()
        @asynccontextmanager
        async def post(self,url,data,headers):
            posts.append((url,deepcopy(data)));fields.update(data);yield Response()
    async def connect():return True
    target=native.NativeProductionTarget(SimpleNamespace(connect=connect,_session=Session(),base_url="http://pv"),{"brand":"zeversolar"})
    manager=pv.ProductionStopManager(Store(),lambda _:target,lambda:True)
    async def scenario():
        await manager.update(-5,[{"brand":"zeversolar"}])
        assert manager.device_confirmed and fields["ac_value1"]=="0"
        await manager.update(0,[])
        assert fields==original
        assert len(posts)==2
    run(scenario())


def test_one_unavailable_device_does_not_suppress_other_solar_controls():
    manager,_,targets,_=rig()
    async def broken_read():raise TimeoutError("offline inverter A")
    targets["a"].read=broken_read
    async def scenario():
        await manager.update(-5,[{"id":"a"},{"id":"b"}])
        assert targets["b"].value==0
        assert not manager.device_confirmed
        await manager.update(0,[])
        assert targets["b"].value==65
    run(scenario())


def test_zero_pv_at_night_and_precommand_samples_never_prove_a_physical_transition():
    manager,_,_,_=rig()
    manager.observe_power(0,datetime.now(timezone.utc))
    run(manager.update(-5,[{"id":"a"}]))
    manager.observe_power(0,datetime.now(timezone.utc))
    assert manager.device_confirmed and manager.physical_converged is None


@pytest.fixture
def runtime_rig(monkeypatch):
    storage = ModuleType("homeassistant.helpers.storage")
    store = Store()
    storage.Store = lambda *args: store
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.storage", storage)
    runtime_module = load("solar_production_runtime")
    now = datetime.now(timezone.utc)
    states = {
        "switch.pv_enable": SimpleNamespace(state="on", attributes={}),
        "binary_sensor.grid_connected": SimpleNamespace(state="on", attributes={}, last_updated=now),
        "sensor.import_price": SimpleNamespace(state="-5", attributes={"unit_of_measurement":"c/kWh", "valid_from":(now-timedelta(minutes=1)).isoformat(), "valid_to":(now+timedelta(minutes=1)).isoformat()}),
        "sensor.pv": SimpleNamespace(state="2500", attributes={"unit_of_measurement":"W"}, last_updated=now),
    }
    calls=[]
    async def call(domain,service,data,blocking):
        calls.append((domain,service,data))
        if domain=="switch":
            states[data["entity_id"]].state="on" if service=="turn_on" else "off"
    hass=SimpleNamespace(states=SimpleNamespace(get=states.get),services=SimpleNamespace(async_call=call))
    entry=SimpleNamespace(entry_id="entry",data={},options={pv.ENABLED:True,pv.ENTITIES:["switch.pv_enable"],pv.ALL_PV:True,
        "solar_production_import_price_entity":"sensor.import_price","solar_production_power_entity":"sensor.pv",
        "solar_production_grid_connected_entity":"binary_sensor.grid_connected"})
    data={};permission={"allowed":True}
    runtime=runtime_module.SolarProductionRuntime(hass,entry,data,lambda:permission["allowed"],(None,)*4,lambda:False)
    return runtime,store,states,calls,permission,data


def test_runtime_current_retail_stop_expiry_outage_and_disabled_option_recovery(runtime_rig):
    runtime,store,states,calls,permission,data=runtime_rig
    async def scenario():
        await runtime.tick()
        assert states["switch.pv_enable"].state=="off"
        assert data["solar_production_stop"]["device_limit_confirmed"]
        assert runtime.can_project()
        assert runtime.blocks_export_control
        # An outage withdraws the stop even while the price remains negative.
        states["binary_sensor.grid_connected"].state="off"
        await runtime.tick()
        assert states["switch.pv_enable"].state=="on"
        assert not runtime.blocks_export_control
        assert data["solar_production_stop"]["state"]=="grid_unavailable"
        states["binary_sensor.grid_connected"].state="on"
        await runtime.tick()
        assert states["switch.pv_enable"].state=="off"
        # Expired retail quote withdraws the stop without a new price callback.
        states["sensor.import_price"].attributes["valid_to"]=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        await runtime.tick()
        assert states["switch.pv_enable"].state=="on"
        states["sensor.import_price"].attributes["valid_to"]=(datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat()
        await runtime.tick()
        runtime.entry.options[pv.ENABLED]=False
        await runtime.tick()
        assert states["switch.pv_enable"].state=="on"
        assert store.data["records"]==[]
    run(scenario())


def test_runtime_never_stops_without_fresh_grid_connection_proof(runtime_rig):
    runtime,_,states,calls,_,data=runtime_rig
    states["binary_sensor.grid_connected"].last_updated=datetime.now(timezone.utc)-timedelta(minutes=2)
    run(runtime.tick())
    assert not [c for c in calls if c[0]=="switch"]
    assert data["solar_production_stop"]["state"]=="grid_unavailable"


def test_runtime_only_uses_selected_retail_provider_and_explicit_units(runtime_rig):
    runtime,_,states,_,_,_=runtime_rig
    assert runtime.price()==-5
    states["sensor.import_price"].attributes["unit_of_measurement"]="$/kWh"
    states["sensor.import_price"].state="-0.05"
    assert runtime.price()==-5
    states["sensor.import_price"].attributes["unit_of_measurement"]="AUD/MWh"
    assert runtime.price() is None
    runtime.entry.options["solar_production_import_price_entity"]=""
    runtime.entry.options["electricity_provider"]="flow_power"
    now=datetime.now(timezone.utc)
    quote=interval(-50,startTime=(now-timedelta(minutes=1)).isoformat(),endTime=(now+timedelta(minutes=1)).isoformat())
    runtime.coordinators=(SimpleNamespace(data={"current":[quote]}),)*4
    # The Amber-shaped wholesale observation must not replace Flow Power retail.
    assert runtime.price() is None
    runtime.entry.options["electricity_provider"]="amber"
    assert runtime.price()==-50


def test_runtime_restore_reconciles_export_and_shutdown_blocks_queued_legacy_callbacks(runtime_rig):
    runtime,_,states,_,_,_=runtime_rig
    reconciled=[]
    async def reconcile():reconciled.append(states["switch.pv_enable"].state)
    runtime.after_restore=reconcile
    async def scenario():
        await runtime.tick()
        states["sensor.import_price"].state="0"
        await runtime.tick()
        assert reconciled==["on"]
        states["sensor.import_price"].state="-5"
        await runtime.tick()
        assert await runtime.shutdown()
        assert states["switch.pv_enable"].state=="on"
        assert runtime.blocks_export_control
        await runtime.tick()
        assert states["switch.pv_enable"].state=="on"
    run(scenario())


def test_runtime_default_unsupported_hybrid_guard_and_invalid_entities(runtime_rig):
    runtime,_,_,_,_,_=runtime_rig
    runtime.entry.options[pv.ENTITIES]=["switch.pv_enable","light.not_pv"]
    assert runtime.identities()==[]
    runtime.entry.options[pv.ENTITIES]=[]
    runtime.entry.options.update(ac_inverter_curtailment_enabled=True,inverter_brand="fronius",battery_system="fronius_reserva")
    assert runtime.identities()==[]
    runtime.entry.options.update(inverter_brand="huawei",battery_system="tesla")
    assert runtime.identities()==[]
    runtime.entry.options.update(inverter_brand="solaredge")
    runtime.same_hybrid=lambda:True
    assert runtime.identities()==[]


def extracted(path, name, namespace):
    import ast
    import textwrap
    source=path.read_text()
    node=next(node for node in ast.walk(ast.parse(source)) if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name==name)
    exec(textwrap.dedent(ast.get_source_segment(source,node)),namespace)
    return namespace[name]


def test_actual_fast_loop_cannot_overwrite_owned_production_stop():
    ticks=[]
    async def tick():ticks.append(True)
    runtime=SimpleNamespace(tick=tick,blocks_export_control=True)
    data={"solar_production_runtime":runtime}
    def forbidden(*args,**kwargs):raise AssertionError("legacy controller must not run while PV stop is owned")
    namespace={"_aemo_dispatch_entry_data":lambda:data,"ac_inverter_is_same_hybrid":forbidden,
               "_LOGGER":SimpleNamespace(error=forbidden)}
    callback=extracted(PACKAGE/"__init__.py","fast_load_following_update",namespace)
    run(callback(SimpleNamespace(second=0)))
    assert ticks==[True]


def test_offgrid_projection_excludes_negative_and_unknown_import_slots(monkeypatch):
    # Execute the real post-solve overlay against a minimal schedule.
    schedule_reader=ModuleType("_pvfeature.optimization.schedule_reader")
    schedule_reader.ScheduleAction=lambda **kw:SimpleNamespace(**kw)
    monkeypatch.setitem(sys.modules,schedule_reader.__name__,schedule_reader)
    namespace={"__package__":"_pvfeature.optimization", "_LOGGER":SimpleNamespace(info=lambda *a:None)}
    overlay=extracted(PACKAGE/"optimization/coordinator.py","_apply_offgrid_overlay",namespace)
    owner=SimpleNamespace(_OFFGRID_FULL_SOC_THRESHOLD=98,_OFFGRID_EXPORT_THRESHOLD=.01,_OFFGRID_MIN_CONSECUTIVE=3)
    actions=[SimpleNamespace(timestamp=NOW+timedelta(minutes=5*i),action="idle",power_w=0,soc=1,battery_charge_w=0,battery_discharge_w=0) for i in range(6)]
    schedule=SimpleNamespace(actions=actions)
    result=overlay(owner,schedule,[-.1]*6,import_prices=[-.1,-.1,-.1,.1,.1,.1])
    assert [s.action for s in result.actions]==["idle"]*3+["off_grid"]*3
    schedule=SimpleNamespace(actions=actions)
    assert all(s.action=="idle" for s in overlay(owner,schedule,[-.1]*6).actions)


def test_confirmed_stop_replans_and_observed_ineffective_stop_withdraws_projection(runtime_rig):
    runtime,_,states,_,_,data=runtime_rig
    replans=[]
    data["optimization_coordinator"]=SimpleNamespace(_schedule_settings_reoptimization=lambda:replans.append(True))
    async def scenario():
        await runtime.tick()
        assert replans and runtime.can_project()
        # Fresh post-command PV that remains high is evidence the stop has not
        # physically converged. Do not keep a zero-PV planning assumption.
        states["sensor.pv"].last_updated=datetime.now(timezone.utc)
        await runtime.tick()
        assert runtime.manager.physical_converged is False
        assert not runtime.can_project()
    run(scenario())


@pytest.mark.parametrize("physical,expected",[(None,"curtailment_pending"),(False,"curtailment_pending"),(True,"curtailed")])
def test_existing_inverter_api_separates_native_stop_intent_from_physical_result(physical,expected):
    production={"native_ac_owned":True,"physical_converged":physical,"device_limit_confirmed":True}
    state={"status":"online","is_curtailed":False}
    namespace={"Any":object,"INVERTER_CONTROL_MODE_SHUTDOWN":"shutdown"}
    apply=extracted(PACKAGE/"__init__.py","_apply_inverter_physical_convergence_status",namespace)
    apply(state,{"solar_production_stop":production})
    assert state["status"]==expected
    assert state["is_curtailed"] is (physical is True)
    assert state["control_mode"]=="shutdown" and state["target_power_w"]==0
    assert state["production_control"]==production


@pytest.mark.parametrize("physical,restore,expected",[(None,False,"Shutdown Pending"),(False,False,"Shutdown Pending"),(True,False,"Shutdown"),(None,True,"Restore Pending")])
def test_existing_inverter_sensor_uses_production_proof_and_restore_state(physical,restore,expected):
    import ast
    source=(PACKAGE/"sensor.py").read_text()
    cls=next(node for node in ast.parse(source).body if isinstance(node,ast.ClassDef) and node.name=="InverterStatusSensor")
    method=next(node for node in cls.body if isinstance(node,ast.FunctionDef) and node.name=="native_value")
    method.decorator_list=[]
    ns={}
    exec(compile(ast.Module(body=[method],type_ignores=[]),"sensor.py","exec"),ns)
    sensor=SimpleNamespace(_cached_state="running",_entry_data=lambda:{"solar_production_stop":{
        "native_ac_owned":True,"physical_converged":physical,"restore_pending":restore}})
    assert ns["native_value"](sensor)==expected
