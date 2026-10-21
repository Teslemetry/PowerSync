"""Persistent, per-vehicle inclusion of Tesla schedules in the home forecast.

These preferences never change vehicle schedules or charging ownership.
"""
from __future__ import annotations

import asyncio
import re

VIN_PATTERN = r"[A-HJ-NPR-Z0-9]{17}"
RUNTIME_KEY = "power_sync_tesla_schedule_planning"


def normalize_vin(value):
    vin = str(value or "").upper()
    if not re.fullmatch(VIN_PATTERN, vin):
        raise ValueError("A valid vehicle VIN is required")
    return vin


class TeslaSchedulePlanning:
    def __init__(self, store):
        self.store = store
        self.lock = asyncio.Lock()
        self.vehicles = None

    async def load(self):
        if self.vehicles is None:
            data = await self.store.async_load()
            raw = data.get("vehicles", {}) if isinstance(data, dict) else {}
            self.vehicles = {vin.upper(): False for vin, enabled in raw.items()
                             if isinstance(vin, str) and re.fullmatch(VIN_PATTERN, vin.upper())
                             and enabled is False} if isinstance(raw, dict) else {}

    def enabled(self, vin):
        return (self.vehicles or {}).get(vin.upper()) is not False

    @property
    def excluded_vins(self):
        return frozenset(self.vehicles or {})

    async def save(self, vin, enabled):
        """Caller holds the preference lock; persist before publishing changes."""
        vin = normalize_vin(vin)
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        updated = dict(self.vehicles or {})
        if enabled:
            updated.pop(vin, None)
        else:
            updated[vin] = False
        await self.store.async_save({"vehicles": updated})
        self.vehicles = updated


async def preferences(hass, entry_id):
    from homeassistant.helpers.storage import Store
    runtime = hass.data.setdefault(RUNTIME_KEY, {})
    if entry_id not in runtime:
        runtime[entry_id] = TeslaSchedulePlanning(Store(hass, 1, f"power_sync.tesla_schedule_planning.{entry_id}"))
    return runtime[entry_id]


def excluded_vins(hass, entry_id):
    value = hass.data.get(RUNTIME_KEY, {}).get(entry_id)
    return value.excluded_vins if value is not None else frozenset()


def register_http_view(hass):
    from homeassistant.components.http import HomeAssistantView

    class TeslaSchedulePlanningView(HomeAssistantView):
        url = "/api/power_sync/ev/tesla_schedule_planning"
        name = "api:power_sync:ev:tesla_schedule_planning"
        requires_auth = True

        def entries(self):
            return [entry for entry in hass.config_entries.async_entries("power_sync")
                    if entry.entry_id in hass.data.get("power_sync", {})]

        async def get(self, request):
            try:
                vin = normalize_vin(request.query.get("vin"))
                entries = []
                for entry in self.entries():
                    setting = await preferences(hass, entry.entry_id)
                    async with setting.lock:
                        await setting.load()
                        entries.append({"entry_id": entry.entry_id, "name": entry.title,
                                        "enabled": setting.enabled(vin)})
                return self.json({"success": True, "entries": entries})
            except ValueError as err:
                return self.json({"success": False, "error": str(err)}, status_code=400)

        async def post(self, request):
            try:
                body = await request.json()
                if not isinstance(body, dict) or type(body.get("enabled")) is not bool:
                    raise ValueError("enabled must be a boolean")
                vin = normalize_vin(body.get("vin"))
                entries = [entry for entry in self.entries() if entry.entry_id == body.get("entry_id")]
                if len(entries) != 1:
                    raise ValueError("Select a loaded PowerSync entry")
                entry = entries[0]
                setting = await preferences(hass, entry.entry_id)
                async with setting.lock:
                    await setting.load()
                    await setting.save(vin, body["enabled"])
                coordinator = hass.data["power_sync"][entry.entry_id].get("optimization_coordinator")
                refresh = getattr(coordinator, "_schedule_settings_reoptimization", None)
                if refresh:
                    refresh()
                return self.json({"success": True, "entry_id": entry.entry_id,
                                  "vin": vin, "enabled": setting.enabled(vin)})
            except (ValueError, TypeError) as err:
                return self.json({"success": False, "error": str(err)}, status_code=400)

    hass.http.register_view(TeslaSchedulePlanningView())
