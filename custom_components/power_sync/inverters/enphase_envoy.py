"""Device-scoped DPEL control through Enphase Envoy Installer HA entities.

Never use enphase_envoy.enable_dpel: that upstream service is not device-scoped.
Entity writes refresh the upstream coordinator; their states provide readback,
not proof of physical solar output. The journal survives integration reloads.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
from copy import deepcopy

from .base import InverterController, InverterState, InverterStatus

_LOGGER = logging.getLogger(__name__)

# HA batches coordinator refresh requests during a 10-second cooldown. A
# completed entity service can therefore precede its published readback.
_READBACK_TIMEOUT_SECONDS = 15
_READBACK_POLL_SECONDS = 0.1


class EnphaseEnvoyController(InverterController):
    def __init__(self, hass, entity_prefix, entry_id="", model="export"):
        super().__init__(host="", port=0, model=model)
        self.hass = hass
        self._gateway = None
        self.entry_id = entry_id
        self.prefix = entity_prefix.strip()
        self.entities = {
            "enabled": f"switch.{self.prefix}_dpel_enabled",
            "limit": f"number.{self.prefix}_dpel_limit",
            "mode": f"select.{self.prefix}_dpel_mode",
        }
        # One gateway has one writer, even across PowerSync config entries.
        key = self.prefix
        self._shared = hass.data.setdefault("_power_sync_envoy_dpel", {}).setdefault(
            key, {"lock": asyncio.Lock(), "loaded": False, "record": None}
        )
        from homeassistant.helpers.storage import Store
        self._store = Store(hass, 1, f"power_sync_envoy_dpel_{self.prefix}")

    def _valid_identity(self):
        from homeassistant.helpers import entity_registry as er
        registry = er.async_get(self.hass)
        anchor = registry.async_get(self.entities["limit"])
        if (anchor is None or anchor.platform != "enphase_envoy"
                or not anchor.unique_id.endswith("_dpel_limit")):
            return False
        serial = anchor.unique_id.removesuffix("_dpel_limit")
        resolved = {}
        for key, domain, suffix in (("enabled", "switch", "dpel_enabled"),
                                    ("mode", "select", "dpel_mode"),
                                    ("limit", "number", "dpel_limit")):
            entity_id = registry.async_get_entity_id(domain, "enphase_envoy", f"{serial}_{suffix}")
            entity = registry.async_get(entity_id) if entity_id else None
            if (entity is None or not entity.device_id or not entity.config_entry_id
                    or entity.device_id != anchor.device_id
                    or entity.config_entry_id != anchor.config_entry_id):
                return False
            resolved[key] = entity_id
        # The switch's display name is DPEL, while its unique key is
        # dpel_enabled. Resolve registry IDs so renames and default slugs work.
        self.entities = resolved
        self._gateway = [anchor.device_id, anchor.config_entry_id]
        return True

    def _read(self):
        if not re.fullmatch(r"[a-z0-9_]+", self.prefix) or not self._valid_identity():
            return None
        states = {key: self.hass.states.get(eid) for key, eid in self.entities.items()}
        if any(s is None or s.state in ("unknown", "unavailable") for s in states.values()):
            return None
        if states["enabled"].state not in ("on", "off") or states["mode"].state not in ("Export", "Production"):
            return None
        if not {"Export", "Production"}.issubset(states["mode"].attributes.get("options", [])):
            return None
        try:
            limit = float(states["limit"].state)
        except (ValueError, TypeError):
            return None
        if not math.isfinite(limit) or states["limit"].attributes.get("unit_of_measurement") != "W":
            return None
        return {"enabled": states["enabled"].state == "on", "mode": states["mode"].state, "limit": limit}

    async def connect(self):
        self._connected = self._read() is not None
        return self._connected

    async def disconnect(self):
        self._connected = False

    async def _load(self):
        if not self._shared["loaded"]:
            self._shared["record"] = await self._store.async_load()
            self._shared["loaded"] = True
        return self._shared["record"]

    async def _save(self, record):
        # Persist before writing hardware. Failed storage must prevent the write.
        await self._store.async_save(record)
        self._shared["record"] = deepcopy(record)

    async def _wait_for_readback(self, current, pending):
        try:
            async with asyncio.timeout(_READBACK_TIMEOUT_SECONDS):
                while True:
                    observed = self._read()
                    if observed == pending:
                        return True
                    if observed != current:
                        # Do not wait through an external write or unavailable
                        # controls, or overwrite them with the next field.
                        return False
                    await asyncio.sleep(_READBACK_POLL_SECONDS)
        except TimeoutError:
            _LOGGER.warning("Envoy DPEL readback not confirmed before deadline")
            return False

    async def _apply(self, target, record):
        current = self._read()
        if current is None:
            return False
        # An interrupted write may have reached the gateway before HA published
        # its state. Explicitly reassert the baseline instead of clearing an
        # uncertain journal merely because the old HA values still match.
        force = record.get("pending") is not None
        steps = []
        if not target["enabled"]:
            steps.append(("enabled", False))
        # Tighten before changing interpretation, then loosen to the final cap.
        # Never disable an active limiter merely to stage a new target.
        if target["limit"] < current["limit"]:
            steps.append(("limit", target["limit"]))
        steps.extend((key, target[key]) for key in ("mode", "limit", "enabled"))
        for key, value in steps:
            observed = self._read()
            if observed != current:
                return False
            if current[key] == value and not force:
                continue
            pending = {**current, key: value}
            record = {**record, "owned": current, "pending": pending}
            await self._save(record)
            domain = self.entities[key].split(".", 1)[0]
            data = {"entity_id": self.entities[key]}
            if key == "enabled":
                service = "turn_on" if value else "turn_off"
            elif key == "mode":
                service = "select_option"
                data["option"] = value
            else:
                service = "set_value"
                data["value"] = value
            await self.hass.services.async_call(domain, service, data, blocking=True)
            if not await self._wait_for_readback(current, pending):
                return False
            current = pending
            record = {**record, "owned": current, "pending": None}
            await self._save(record)
        return self._read() == target

    async def curtail(self, home_load_w=None, rated_capacity_w=None, *, shutdown=False):
        """Use native export=0 by default, or a production cap at site demand.

        Only explicit manual shutdown requests a full production stop in native
        export mode. Zero site demand must still preserve native load following.
        Production-following mode requires a known, finite site-demand target.
        """
        async with self._shared["lock"]:
            try:
                current = self._read()
                if current is None or self.model not in ("export", "production"):
                    return False
                if home_load_w is not None:
                    home_load_w = float(home_load_w)
                    if not math.isfinite(home_load_w) or home_load_w < 0:
                        return False
                production = self.model == "production" or shutdown
                if production and home_load_w is None and not shutdown:
                    return False
                limit = round(home_load_w) if production and not shutdown else 0
                attrs = self.hass.states.get(self.entities["limit"]).attributes
                minimum, maximum = float(attrs["min"]), float(attrs["max"])
                if not math.isfinite(minimum) or not math.isfinite(maximum) or not minimum <= limit <= maximum:
                    return False
                record = await self._load()
                if record is None:
                    record = {"original": current, "owned": current, "pending": None, "identity": self._gateway, "owner": self.entry_id}
                elif record.get("identity") != self._gateway or record.get("owner") != self.entry_id:
                    return False
                elif current not in (record["owned"], record.get("pending")):
                    _LOGGER.warning("Envoy DPEL changed outside PowerSync; refusing takeover")
                    return False
                target = {"enabled": True, "mode": "Production" if production else "Export", "limit": limit}
                return await self._apply(target, record)
            except Exception:
                _LOGGER.exception("Envoy Installer DPEL curtailment failed")
                return False

    async def restore(self):
        async with self._shared["lock"]:
            try:
                record = await self._load()
                if record is None:
                    return True
                current = self._read()
                if (current is None or record.get("identity") != self._gateway
                        or record.get("owner") != self.entry_id):
                    return False
                if current not in (record["owned"], record.get("pending")):
                    _LOGGER.warning("Envoy DPEL changed outside PowerSync; refusing restore")
                    return False
                if not await self._apply(record["original"], record):
                    return False
                await self._save(None)
                return True
            except Exception:
                _LOGGER.exception("Envoy Installer DPEL restore failed")
                return False

    async def get_status(self):
        state = self._read()
        if state is None:
            return InverterState(InverterStatus.OFFLINE, False, error_message="Envoy Installer DPEL entities unavailable")
        enabled = state["enabled"]
        return InverterState(
            InverterStatus.CURTAILED if enabled else InverterStatus.ONLINE,
            enabled,
            attributes={"data_source": "home_assistant_entities", "entity_prefix": self.prefix,
                        "dpel_enabled": enabled, "dpel_mode": state["mode"], "dpel_limit_w": state["limit"]},
        )
