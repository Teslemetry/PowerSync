"""Explicit native Tesla Charge on Solar control, with persistent EV ownership.

No background polling: both the Teslemetry read and write can spend credits and
wake a vehicle. The hold is intentionally retained after an uncertain command.
"""
from __future__ import annotations

import asyncio
from functools import wraps
from inspect import signature
import re
import time


class SolarError(ValueError):
    """A user-safe native solar failure."""


def validate_settings(value):
    if not isinstance(value, dict) or type(value.get("enabled")) is not bool:
        raise SolarError("enabled must be a boolean")
    for key in ("lowerChargeLimit", "upperChargeLimit"):
        if type(value.get(key)) is not int or not 0 <= value[key] <= 100:
            raise SolarError("Charge limits must be whole percentages from 0 to 100")
    if value["lowerChargeLimit"] > value["upperChargeLimit"]:
        raise SolarError("The lower charge limit must not exceed the upper limit")
    return {key: value[key] for key in ("enabled", "lowerChargeLimit", "upperChargeLimit")}


async def request_settings(session, token, vin, settings=None):
    if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", vin):
        raise SolarError("A valid vehicle VIN is required")
    url = f"https://api.teslemetry.com/api/1/vehicles/{vin}/custom_command/charge_on_solar"
    try:
        async with session.request(
            "POST" if settings is not None else "GET", url,
            headers={"Authorization": f"Bearer {token}"},
            **({"json": validate_settings(settings)} if settings is not None else {}),
            timeout=45, allow_redirects=False,
        ) as response:
            if response.status != 200:
                raise SolarError(f"Teslemetry request failed (HTTP {response.status}); check connection, credits and vehicle compatibility")
            body = await response.json()
        result = body.get("response") if isinstance(body, dict) else None
        if not isinstance(result, dict) or result.get("result") is False:
            raise SolarError("Teslemetry did not accept the request")
        if settings is not None:
            if result.get("result") is not True:
                raise SolarError("Teslemetry did not acknowledge the command")
            return None
        return validate_settings(result)
    except SolarError:
        raise
    except Exception as err:
        raise SolarError("Teslemetry request could not be confirmed; refresh before changing controller ownership") from err


class SolarOwnership:
    def __init__(self, store):
        self.store = store
        self.lock = asyncio.Lock()
        self.owner = None
        self.holds = None
        self.requests = {}

    async def load(self):
        if self.holds is None:
            data = await self.store.async_load()
            self.holds = dict((data or {}).get("vehicles", {}))
            self.requests = dict((data or {}).get("requests", {}))

    async def hold(self, vin, value):
        self.holds[vin] = value
        await self.store.async_save({"vehicles": self.holds, "requests": self.requests})

    async def release(self, vin):
        # Persist before releasing the in-memory interlock.
        remaining = {key: val for key, val in self.holds.items() if key != vin}
        await self.store.async_save({"vehicles": remaining, "requests": self.requests})
        self.holds = remaining

    def blocked(self, vin):
        return bool(self.holds) if not vin or vin == "_default" else vin.upper() in self.holds


async def ownership(hass, entry_id):
    from homeassistant.helpers.storage import Store
    runtime = hass.data.setdefault("power_sync_native_solar", {})
    if entry_id not in runtime:
        runtime[entry_id] = SolarOwnership(Store(hass, 1, f"power_sync.native_solar.{entry_id}"))
    return runtime[entry_id]


def guard_ev_control(func):
    """Serialize Tesla writes and ownership changes, including nested actions."""
    sig = signature(func)

    @wraps(func)
    async def guarded(*args, **kwargs):
        bound = sig.bind(*args, **kwargs).arguments
        hass = bound["hass"]
        entry = bound.get("config_entry")
        if entry is None:
            return await func(*args, **kwargs)
        gate = await ownership(hass, entry.entry_id)
        if gate.owner is asyncio.current_task():
            params = bound.get("params") or {}
            vin = params.get("vehicle_vin") or params.get("vehicle_id") or bound.get("vehicle_id")
            cleanup_only = params.get("stop_charging") is False and func.__name__ == "_action_stop_ev_charging_dynamic"
            if gate.blocked(vin) and not cleanup_only:
                return False
            return await func(*args, **kwargs)
        async with gate.lock:
            await gate.load()
            params = bound.get("params") or {}
            vin = params.get("vehicle_vin") or params.get("vehicle_id") or bound.get("vehicle_id")
            cleanup_only = params.get("stop_charging") is False and func.__name__ == "_action_stop_ev_charging_dynamic"
            if gate.blocked(vin) and not cleanup_only:
                return False
            gate.owner = asyncio.current_task()
            try:
                return await func(*args, **kwargs)
            finally:
                gate.owner = None
    return guarded


def register_services(hass):
    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from .const import DOMAIN, CONF_MONITORING_MODE

    async def handle(call):
        from . import get_tesla_vehicle_api_token
        from .automations.actions import _dynamic_ev_state
        entries = [e for e in hass.config_entries.async_entries(DOMAIN)
                   if e.entry_id == call.data["entry_id"] and e.entry_id in hass.data.get(DOMAIN, {})]
        if len(entries) != 1:
            raise HomeAssistantError("Select a loaded PowerSync entry")
        entry = entries[0]
        token, provider = get_tesla_vehicle_api_token(hass, entry)
        if provider != "teslemetry" or not token:
            raise HomeAssistantError("Select Teslemetry as the vehicle API provider in PowerSync settings")
        vin = call.data["vin"].upper()
        if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", vin):
            raise HomeAssistantError("A valid vehicle VIN is required")
        gate = await ownership(hass, entry.entry_id)
        try:
            async with gate.lock:
                await gate.load()
                if any(state.get("active") for state in _dynamic_ev_state.get(entry.entry_id, {}).values()):
                    raise SolarError("Turn off PowerSync EV charging sessions before reading or changing native Charge on Solar")
                settings = None
                if call.service == "set_teslemetry_charge_on_solar":
                    if entry.options.get(CONF_MONITORING_MODE, entry.data.get(CONF_MONITORING_MODE, False)):
                        raise SolarError("Vehicle commands are blocked in monitoring mode")
                    if call.data["enabled"] and entry.options.get(
                        "no_solar_installed", entry.data.get("no_solar_installed", False)
                    ):
                        raise SolarError("Charge on Solar cannot be enabled while No solar installed is selected")
                    if call.data["enabled"] and not call.data.get("confirm_eligible"):
                        raise SolarError("Confirm Tesla setup at a Powerwall site without export/site limits; turn off all other charging controllers first")
                    settings = validate_settings({"enabled": call.data["enabled"],
                        "lowerChargeLimit": call.data["lower_charge_limit"],
                        "upperChargeLimit": call.data["upper_charge_limit"]})
                if time.time() - gate.requests.get(vin, 0) < 15:
                    raise SolarError("Wait 15 seconds before another native solar request")
                gate.requests[vin] = time.time()
                await gate.hold(vin, {"status": "unconfirmed"})
                if settings is not None:
                    await request_settings(async_get_clientsession(hass), token, vin, settings)
                observed = await request_settings(async_get_clientsession(hass), token, vin)
                if observed["enabled"]:
                    await gate.hold(vin, observed)
                else:
                    await gate.release(vin)
                matches = settings is None or settings == observed
                return {"settings": observed, "readback_confirmed": matches,
                        "powersync_control_blocked": gate.blocked(vin)}
        except SolarError as err:
            raise HomeAssistantError(str(err)) from err

    schema = {vol.Required("entry_id"): str, vol.Required("vin"): str}
    hass.services.async_register("power_sync", "get_teslemetry_charge_on_solar", handle,
        schema=vol.Schema(schema), supports_response=SupportsResponse.ONLY)
    hass.services.async_register("power_sync", "set_teslemetry_charge_on_solar", handle,
        schema=vol.Schema({**schema, vol.Required("enabled"): bool,
            vol.Optional("confirm_eligible", default=False): bool,
            vol.Required("lower_charge_limit"): vol.All(int, vol.Range(min=0, max=100)),
            vol.Required("upper_charge_limit"): vol.All(int, vol.Range(min=0, max=100))}),
        supports_response=SupportsResponse.OPTIONAL)
