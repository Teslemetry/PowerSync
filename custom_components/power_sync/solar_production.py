"""Price-driven PV production suppression, separate from site export limits.

Only a current retail import interval authorizes a new stop. Every mutation has
an exact, durable restore record first; acknowledgements never prove generation.
No battery dispatch, grid contactor or export-limit commands belong here.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import logging
import math
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)
ENABLED = "negative_import_solar_enabled"
ENTITIES = "solar_production_control_entities"
ALL_PV = "negative_import_solar_controls_all_pv"


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _datetime(value: Any) -> datetime | None:
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.tzinfo is not None else None
    except (TypeError, ValueError, AttributeError):
        return None


def current_import_price(coordinators: tuple, now: datetime) -> float | None:
    """Read only a timestamped, unexpired current retail interval (c/kWh).

    Callers supply retail coordinators, never raw AEMO/Flow Power wholesale
    feeds. No feed-in price, forecast, cached scalar or default-price fallback.
    """
    for coordinator in coordinators:
        if coordinator is None or not getattr(coordinator, "last_update_success", True):
            continue
        data = getattr(coordinator, "data", None)
        if not isinstance(data, dict):
            continue
        prices = data.get("current")
        if not isinstance(prices, list):
            continue
        matches = []
        for item in prices:
            if not isinstance(item, dict) or item.get("channelType") != "general":
                continue
            if item.get("type") != "CurrentInterval":
                continue
            start = _datetime(item.get("startTime"))
            end = _datetime(item.get("endTime"))
            duration = finite_number(item.get("duration"))
            if end is None and start and duration and 0 < duration <= 60:
                end = start + timedelta(minutes=duration)
            price = finite_number(item.get("perKwh"))
            if start and end and start <= now < end and price is not None:
                matches.append(price)
        # Conflicting current prices must not pick a favourable value by order.
        if matches:
            return matches[0] if len(set(matches)) == 1 else None
    return None


def planned_solar(solar: list[float], imports: list[float], *, enabled: bool) -> list[float]:
    """Adjust only explicitly covered whole-site PV; prices here are $/kWh."""
    return [
        0.0 if enabled and index < len(imports) and (price := finite_number(imports[index])) is not None and price < 0 else value
        for index, value in enumerate(solar)
    ]


class EntityProductionTarget:
    """Explicit PV-only HA control: on/off production or an output limit.

    The installer selects the entity; discovery must never guess that an
    export-limit, grid switch, battery dispatch or general relay means PV-only.
    """
    refresh = False

    def __init__(self, hass, entity_id: str):
        self.hass = hass
        self.entity_id = entity_id
        self.identity = {"entity_id": entity_id}

    async def read(self):
        await self.hass.services.async_call(
            "homeassistant", "update_entity", {"entity_id": self.entity_id}, blocking=True
        )
        state = self.hass.states.get(self.entity_id)
        if state is None:
            return None
        domain = self.entity_id.split(".")[0]
        if domain == "switch":
            return {"value": state.state} if state.state in ("on", "off") else None
        if domain == "number":
            value = finite_number(state.state)
            minimum = finite_number(state.attributes.get("min"))
            maximum = finite_number(state.attributes.get("max"))
            if value is not None and minimum is not None and maximum is not None and minimum <= 0 <= maximum and minimum <= value <= maximum:
                return {"value": value}
        return None

    def stopped(self, original):
        return {"value": "off" if self.entity_id.startswith("switch.") else 0.0}

    async def write(self, value):
        domain = self.entity_id.split(".")[0]
        if domain == "switch" and value.get("value") in ("on", "off"):
            service = "turn_on" if value["value"] == "on" else "turn_off"
            data = {"entity_id": self.entity_id}
        elif domain == "number" and finite_number(value.get("value")) is not None:
            state = self.hass.states.get(self.entity_id)
            if state is None:
                return False
            minimum = finite_number(state.attributes.get("min"))
            maximum = finite_number(state.attributes.get("max"))
            if minimum is None or maximum is None or not minimum <= value["value"] <= maximum:
                return False
            service = "set_value"
            data = {"entity_id": self.entity_id, "value": value["value"]}
        else:
            return False
        await self.hass.services.async_call(domain, service, data, blocking=True)
        return True


class ProductionStopManager:
    """Serialize one entry's PV controls and retain all unfinished restores."""

    def __init__(self, store, target_factory, permitted, lock=None, *, stop_permitted=None):
        self.store = store
        self.target_factory = target_factory
        self.permitted = permitted
        self.stop_permitted = stop_permitted or permitted
        self.lock = lock or asyncio.Lock()
        self.records: list[dict] = []
        self.loaded = False
        self.status = "normal"
        self.device_confirmed = False
        self.command_attempted = False
        self.acknowledged = False
        self.physical_converged: bool | None = None
        self.last_command_at: datetime | None = None
        self.stopping = False
        self.suspended = False
        self._failures = {}
        self._retry_at = {}
        self._last_goal = None
        self._latest_power = None
        self._latest_power_at = None
        self._pre_stop_power = None

    @property
    def owns_control(self):
        return bool(self.records)

    async def _load(self):
        if not self.loaded:
            data = await self.store.async_load() or {}
            self.records = data.get("records", [])
            self.suspended = bool(data.get("suspended", False))
            if not isinstance(self.records, list) or any(
                not isinstance(record, dict) or not all(key in record for key in ("identity", "original", "stopped"))
                for record in self.records
            ):
                raise ValueError("Invalid PV production restore journal")
            self.loaded = True

    async def _save(self):
        await self.store.async_save({"records": deepcopy(self.records), "suspended": self.suspended})

    async def _read(self, target):
        try:
            return await target.read()
        except Exception:
            _LOGGER.exception("PV production readback unavailable; restore intent retained")
            return None

    @staticmethod
    def _matches(target, observed, expected):
        return getattr(target, "matches", lambda actual, wanted: actual == wanted)(observed, expected)

    async def _write(self, target, state, *, stop=False):
        # Re-evaluate after every await and immediately before every mutation.
        if not self.permitted() or (stop and (self.stopping or not self.stop_permitted())):
            return False
        key = repr(getattr(target, "identity", id(target)))
        if time.monotonic() < self._retry_at.get(key, 0):
            return False
        self.command_attempted = True
        self.device_confirmed = False
        self.physical_converged = None
        now = datetime.now(timezone.utc)
        if self._last_goal != stop or self.last_command_at is None:
            self.last_command_at = now
            self._pre_stop_power = (
                self._latest_power if stop and self._latest_power_at
                and timedelta(0) <= now - self._latest_power_at <= timedelta(seconds=60)
                else None
            )
        self._last_goal = stop
        target.allowed = lambda: self.permitted() and (not stop or (not self.stopping and self.stop_permitted()))
        try:
            self.acknowledged = bool(await target.write(state))
        except Exception:
            self.acknowledged = False
            _LOGGER.exception("PV production command failed; exact restore retained")
        if self.acknowledged:
            self._failures.pop(key, None)
            self._retry_at.pop(key, None)
        else:
            count = min(6, self._failures.get(key, 0) + 1)
            self._failures[key] = count
            self._retry_at[key] = time.monotonic() + min(300, 15 * 2 ** (count - 1))
        return self.acknowledged

    async def _restore(self):
        if self.status != "restore_pending":
            self._retry_at.clear()
            self._failures.clear()
        self.status = "restore_pending"
        self.device_confirmed = False
        self.physical_converged = None
        for record in list(self.records):
            target = self.target_factory(record["identity"])
            if target is None:
                continue
            observed = await self._read(target)
            if self._matches(target, observed, record["original"]):
                pass  # Includes a crash before the stop write reached hardware.
            elif self._matches(target, observed, record["stopped"]) or getattr(target, "owns_partial", lambda *args: False)(observed, record["original"], record["stopped"]):
                if not await self._write(target, record["original"]):
                    continue
                if not self._matches(target, await self._read(target), record["original"]):
                    continue
            elif observed is None:
                continue
            else:
                # A different controller changed the control. Keep its value;
                # require explicit user resume before any new stop.
                self.suspended = True
                self.status = "external_control"
            self.records.remove(record)
            await self._save()
        if not self.records:
            self._last_goal = None
            self.last_command_at = None
            self._pre_stop_power = None
            if self.status != "external_control":
                self.status = "normal"

    async def update(self, price, identities, *, enabled=True):
        async with self.lock:
            await self._load()
            if self.stopping:
                return
            price = finite_number(price)
            active = enabled and price is not None and price < 0
            if not active:
                if self.records:
                    await self._restore()
                if self.suspended and price is not None and price >= 0:
                    self.suspended = False
                    await self._save()
                return
            if not self.permitted():
                self.status = "blocked"
                self.device_confirmed = False
                self.physical_converged = None
                return
            if self.suspended:
                self.status = "external_control"
                return
            # Configuration changes settle old devices before acquiring new ones.
            if any(record["identity"] not in identities for record in self.records):
                await self._restore()
                if self.records or self.suspended:
                    return
            self.status = "stop_pending" if identities else "unsupported"
            confirmed = bool(identities)
            for identity in identities:
                target = self.target_factory(identity)
                if target is None:
                    confirmed = False
                    continue
                record = next((r for r in self.records if r["identity"] == identity), None)
                observed = await self._read(target)
                if observed is None:
                    confirmed = False
                    continue
                if record is None:
                    stopped = target.stopped(observed)
                    if stopped is None:
                        confirmed = False
                        continue
                    if self._matches(target, observed, stopped):
                        # Already stopped by somebody else: never acquire/restore it.
                        self.status = "external_control"
                        confirmed = False
                        continue
                    record = {"identity": identity, "original": observed, "stopped": stopped}
                    self.records.append(record)
                    try:
                        await self._save()  # Must succeed before the first write.
                    except BaseException:
                        self.records.remove(record)
                        raise
                elif not any(self._matches(target, observed, state) for state in (record["original"], record["stopped"])) and not getattr(target, "owns_partial", lambda *args: False)(observed, record["original"], record["stopped"]):
                    self.suspended = True
                    self.status = "external_control"
                    await self._save()
                    self.device_confirmed = False
                    return
                if not self._matches(target, observed, record["stopped"]) or target.refresh:
                    if not await self._write(target, record["stopped"], stop=True):
                        confirmed = False
                        continue
                    observed = await self._read(target)
                if not self._matches(target, observed, record["stopped"]) or not getattr(target, "effective", True):
                    confirmed = False
            self.device_confirmed = confirmed
            if confirmed:
                self.status = "limit_confirmed"

    async def release(self, *, suspend=False):
        async with self.lock:
            await self._load()
            if suspend:
                self.suspended = True
                await self._save()
            if self.records:
                await self._restore()
            return not self.records

    async def shutdown(self):
        async with self.lock:
            self.stopping = True
            await self._load()
            if self.records:
                await self._restore()

    def observe_power(self, value_w, sampled_at):
        """Only a fresh PV-only sample after a command proves physical effect."""
        power = finite_number(value_w)
        sample = _datetime(sampled_at)
        now = datetime.now(timezone.utc)
        self._latest_power = power
        self._latest_power_at = sample
        self.physical_converged = (
            abs(power) <= 100
            if self.device_confirmed and self._pre_stop_power is not None
            and self._pre_stop_power > 100 and power is not None and sample
            and self.last_command_at and self.last_command_at < sample <= now
            and now - sample <= timedelta(seconds=60) else None
        )

    def as_dict(self):
        return {
            "state": self.status,
            "command_attempted": self.command_attempted,
            "acknowledged": self.acknowledged,
            "device_limit_confirmed": self.device_confirmed,
            "physical_converged": self.physical_converged,
            "restore_required": self.owns_control,
            "restore_pending": self.owns_control and self.status == "restore_pending",
            "target_power_w": 0 if self.owns_control else None,
        }


def validate_production_entities(hass, entities):
    """Validate legacy/runtime inputs as well as the options form."""
    if not isinstance(entities, list):
        return "invalid_solar_production_entity"
    for entity in entities:
        if not isinstance(entity, str):
            return "invalid_solar_production_entity"
        state = hass.states.get(entity)
        if state is None:
            return "invalid_solar_production_entity"
        if entity.startswith("switch."):
            if state.state not in ("on", "off"):
                return "invalid_solar_production_entity"
        elif entity.startswith("number."):
            minimum = finite_number(state.attributes.get("min"))
            maximum = finite_number(state.attributes.get("max"))
            if minimum is None or maximum is None or not minimum <= 0 <= maximum:
                return "invalid_solar_production_entity"
        else:
            return "invalid_solar_production_entity"
    return None
