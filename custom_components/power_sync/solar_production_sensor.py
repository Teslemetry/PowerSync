"""Separate requested/control/physical state for PV production stopping."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN


class SolarProductionControlSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Solar Production Control"
    _attr_icon = "mdi:solar-panel"

    def __init__(self, entry):
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_solar_production_control"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    def _data(self):
        return self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {}).get("solar_production_stop", {})

    @property
    def native_value(self):
        data = self._data()
        if data.get("state") == "limit_confirmed":
            return "Stopped" if data.get("physical_converged") is True else "Stop Pending"
        return {
            "normal": "Normal", "stop_pending": "Stop Pending",
            "restore_pending": "Restore Pending", "blocked": "Monitoring",
            "external_control": "External Control", "control_error": "Control Error",
            "unsupported": "Production Control Required",
            "grid_unavailable": "Grid Unavailable",
        }.get(data.get("state"), "Unknown")

    @property
    def extra_state_attributes(self):
        return dict(self._data())
