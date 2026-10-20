"""Native HA entities backed by Amber readback, rather than optimistic flags."""
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import family_device_info, SENSOR_FAMILY_BATTERY
from .runtime import number, timestamp, utcnow


class AmberEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, key, name):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_suggested_object_id = f"power_sync_{key}"
        self._attr_name = name

    @property
    def device_info(self):
        return family_device_info(self._entry.entry_id, SENSOR_FAMILY_BATTERY)

    @property
    def extra_state_attributes(self):
        return self.coordinator.api_data()["amber_smartshift"]


class AmberStatusSensor(AmberEntity, SensorEntity):
    def __init__(self, coordinator, entry, key, name, field):
        super().__init__(coordinator, entry, key, name)
        self.field = field

    @property
    def native_value(self):
        status = self.coordinator.api_data()["amber_smartshift"]
        if self.field == "mode":
            if not self.coordinator.api_data()["telemetry_ready"]:
                return None
            mode = status["override"].get("value")
            if mode and not status["override_active_now"]:
                return "pending"
            return {"charge": "force_charge", "discharge": "force_discharge", "preserve-charge": "hold_soc", "self-consume": "self_consumption"}.get(mode, "normal" if not mode else "unknown")
        if self.field == "override":
            return status["override"].get("value", "none")
        if self.field == "owner":
            return status["owner"] or {True: "amber", False: "none", None: "unknown"}[status["smartshift_enabled"]]
        if self.field == "last_read":
            return timestamp(status["last_read"])
        if self.field == "capacity":
            return self.coordinator.api_data()["battery_capacity_kwh"]
        if self.field.startswith("earnings:"):
            read = timestamp(status["interval_earnings_read"])
            if not read or int(read.timestamp()) // 300 != int(utcnow().timestamp()) // 300:
                return None
            return number(status["interval_earnings_cents"].get(self.field.split(":", 1)[1]))
        return status.get(self.field)


def sensors(coordinator, entry):
    definitions = (
        ("battery_mode", "Battery Mode", "mode", None),
        ("amber_override", "Amber Override", "override", None),
        ("amber_control_owner", "Amber Control Owner", "owner", None),
        ("amber_command_status", "Amber Command Status", "command_state", None),
        ("amber_power_state", "Amber Reported Activity", "power_state_description", None),
        ("amber_last_battery_poll", "Amber Last Battery Poll", "last_read", None),
        ("amber_battery_capacity", "Amber Battery Capacity", "capacity", "kWh"),
        ("amber_interval_import_cost", "Amber Interval Import Cost", "earnings:importCostsCents", "¢"),
        ("amber_interval_export_earnings", "Amber Interval Export Earnings", "earnings:exportEarningsCents", "¢"),
        ("amber_interval_net_earnings", "Amber Interval Net Earnings", "earnings:totalEarningsCents", "¢"),
    )
    result = []
    for key, name, field, unit in definitions:
        entity = AmberStatusSensor(coordinator, entry, key, name, field)
        entity._attr_native_unit_of_measurement = unit
        if field == "last_read":
            entity._attr_device_class = SensorDeviceClass.TIMESTAMP
        result.append(entity)
    return result


class AmberSmartShiftSwitch(AmberEntity, SwitchEntity):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "amber_smartshift", "Amber Smart Shift")

    @property
    def is_on(self):
        return self.coordinator.api_data()["amber_smartshift"]["smartshift_enabled"]

    async def async_turn_on(self, **kwargs):
        await self.coordinator.set_smartshift(True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.set_smartshift(False)


class AmberConnectionSensor(AmberEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "amber_battery_connection", "Amber Battery Connection")

    @property
    def is_on(self):
        return self.coordinator.api_data()["telemetry_ready"]


class AmberModeSwitch(AmberEntity, SwitchEntity):
    def __init__(self, coordinator, entry, mode, key, name):
        super().__init__(coordinator, entry, key, name)
        self.mode = mode

    @property
    def is_on(self):
        status = self.coordinator.api_data()["amber_smartshift"]
        return status["override_active_now"] and status["override"].get("value") == self.mode

    async def async_turn_on(self, **kwargs):
        service = {"charge": "force_charge", "discharge": "force_discharge"}[self.mode]
        await self.hass.services.async_call("power_sync", service,
            {"entry_id": self._entry.entry_id, "source": "manual", "duration": 30}, blocking=True)

    async def async_turn_off(self, **kwargs):
        if self.is_on:
            await self.hass.services.async_call("power_sync", "restore_normal",
                {"entry_id": self._entry.entry_id, "source": "manual"}, blocking=True)
