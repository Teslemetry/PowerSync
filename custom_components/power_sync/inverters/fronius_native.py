"""Native Fronius site export control through fronius_modbus's Web API entity.

Service completion and HA state are acknowledgements, not physical proof. The
caller still owns price/Monitoring gates and fresh grid convergence checks.
"""

from __future__ import annotations

import logging
import math

from .base import InverterController

_LOGGER = logging.getLogger(__name__)


class FroniusNativeExportLimit:
    """Own a saved site limit, scoped to one PowerSync entry and solar endpoint."""

    def __init__(self, hass, entry_id: str, host: str, port: int, slave_id: int):
        from homeassistant.helpers.storage import Store

        self.hass = hass
        self.host = host.strip().lower()
        self.entry_id = entry_id
        self._runtime_entry = getattr(hass, "data", {}).get("power_sync", {}).get(entry_id)
        self._runtime_generation = (
            self._runtime_entry.get("aemo_dispatch_generation")
            if self._runtime_entry is not None else None
        )
        # Native export limits are site-wide, independent of Modbus unit ID.
        self.request_lock = InverterController._get_endpoint_request_lock(
            self.host, 0, 0
        )
        self._store = Store(
            hass, 1,
            f"power_sync.fronius_export_restore.{self.host}",
        )
        self._snapshot = None

    async def _load(self):
        # Reload under the shared site lock: another controller instance may
        # have completed a session since this instance last read the store.
        snapshot = await self._store.async_load()
        self._snapshot = None
        if snapshot:
            if not isinstance(snapshot, dict) or not {
                "entity_id", "upstream_entry_id", "limit_w", "owner_entry_id"
            }.issubset(snapshot):
                raise ValueError("Invalid Fronius export restore snapshot")
            if snapshot["owner_entry_id"] != self.entry_id:
                raise ValueError("Fronius export limit is owned by another PowerSync entry")
            limit = float(snapshot["limit_w"])
            if not math.isfinite(limit) or limit < 0:
                raise ValueError("Invalid saved Fronius export limit")
            self._snapshot = snapshot

    def _surface(self):
        """Resolve only registry-owned controls on a unique matching endpoint."""
        from homeassistant.helpers import entity_registry as er

        if self._runtime_entry is not None:
            current = self.hass.data.get("power_sync", {}).get(self.entry_id)
            if current is not self._runtime_entry or (
                current.get("aemo_dispatch_generation") is not self._runtime_generation
            ):
                raise ValueError("Fronius export controller belongs to an unloaded PowerSync entry")
        entries = [
            entry for entry in self.hass.config_entries.async_entries("fronius_modbus")
            if str(entry.options.get("host", entry.data.get("host", ""))).strip().lower()
            == self.host
        ]
        if self._snapshot:
            entries = [e for e in entries if e.entry_id == self._snapshot["upstream_entry_id"]]
            if len(entries) != 1:
                raise ValueError("Saved Fronius export controller is unavailable")
        if not entries:
            return None
        if len(entries) != 1:
            raise ValueError("Ambiguous Fronius export endpoint")
        entry = entries[0]
        registry = er.async_get(self.hass)
        rows = [
            row for row in er.async_entries_for_config_entry(registry, entry.entry_id)
            if row.entity_id.startswith("number.")
            and str(getattr(row, "unique_id", "")).endswith("_export_soft_limit")
        ]
        if not rows and not self._snapshot:
            return None  # No native Web API capability; keep existing Modbus path.
        if len(rows) != 1 or getattr(rows[0], "disabled_by", None):
            raise ValueError("Fronius export soft-limit entity unavailable or ambiguous")
        state = getattr(entry.state, "value", entry.state)
        if state != "loaded":
            raise ValueError("Fronius upstream integration is not loaded")
        return entry.entry_id, rows[0].entity_id

    def _value(self, entity_id):
        state = self.hass.states.get(entity_id)
        if state is None or state.attributes.get("unit_of_measurement") != "W":
            raise ValueError("Fronius export limit must be available in watts")
        value = float(state.state)
        maximum = float(state.attributes.get("max", float("inf")))
        if not math.isfinite(value) or value < 0 or value > maximum:
            raise ValueError("Fronius export limit is not a finite nonnegative value")
        return value

    async def _write(self, entity_id, value):
        # Never claim an unavailable entity or a service ACK proves curtailment.
        self._value(entity_id)
        # Recheck registry ownership/upstream availability at the write boundary.
        if self._surface()[1] != entity_id:
            raise ValueError("Fronius export control changed before write")
        await self.hass.services.async_call(
            "number", "set_value", {"entity_id": entity_id, "value": value},
            blocking=True,
        )
        if abs(self._value(entity_id) - value) > 0.5:
            raise ValueError("Fronius export limit entity did not acknowledge the value")

    async def curtail(self) -> bool | None:
        """Return None only when no native capability exists, False on failure."""
        try:
            await self._load()
            surface = self._surface()
            if surface is None:
                return None
            upstream_entry_id, entity_id = surface
            current = self._value(entity_id)
            if self._snapshot is None:
                snapshot = {"entity_id": entity_id, "upstream_entry_id": upstream_entry_id,
                            "limit_w": current, "owner_entry_id": self.entry_id}
                # Save BEFORE any write; a crash or cancellation must retain restore data.
                await self._store.async_save(snapshot)
                self._snapshot = snapshot
            if current != 0:
                await self._write(entity_id, 0)
            _LOGGER.debug("Fronius native zero-export limit acknowledged via %s", entity_id)
            return True
        except Exception as err:
            _LOGGER.warning("Fronius native export curtailment deferred: %s", err)
            return False

    async def has_snapshot(self) -> bool:
        """Load ownership before restoration, including after HA restart."""
        await self._load()
        if self._snapshot is not None:
            _, entity_id = self._surface()
            self._value(entity_id)
        return self._snapshot is not None

    async def restore(self) -> bool:
        """Restore the saved site cap, retaining ownership after any failure."""
        try:
            await self._load()
            if self._snapshot is None:
                return True
            _, entity_id = self._surface()
            await self._write(entity_id, self._snapshot["limit_w"])
            await self._store.async_save({})
            self._snapshot = None
            return True
        except Exception as err:
            _LOGGER.warning("Fronius native export restore pending: %s", err)
            return False
