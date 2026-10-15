"""Regression coverage for selected logical profiles on a shared EVSE."""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent / "custom_components" / "power_sync"
_ps = types.ModuleType("power_sync")
_ps.__path__ = [str(ROOT)]
sys.modules["power_sync"] = _ps
_automations = types.ModuleType("power_sync.automations")
_automations.__path__ = [str(ROOT / "automations")]
sys.modules["power_sync.automations"] = _automations

profiles = importlib.import_module("power_sync.automations.ev_loadpoint_profiles")
ownership = importlib.import_module("power_sync.automations.ev_ownership")


class _Entry:
    entry_id = "entry-1"
    data = {}
    options = {}


class _Store:
    def __init__(self, data):
        self._data = data
        self.saved = 0

    async def async_save(self):
        self.saved += 1


class _Hass:
    def __init__(self, data):
        self.data = {"power_sync": {"entry-1": {"automation_store": _Store(data)}}}
        self.created_tasks = []

    def async_create_task(self, coro):
        self.created_tasks.append(coro)
        coro.close()


def _shared_profiles():
    return [
        {
            "vehicle_id": "car-one",
            "charger_type": "generic",
            "charger_switch_entity": "switch.driveway_charge",
            "external_control_policy": "yield",
            "battery_capacity_kwh": 78,
        },
        {
            "vehicle_id": "car-two",
            "charger_type": "generic",
            "charger_switch_entity": "switch.driveway_charge",
            "external_control_policy": "override",
            "battery_capacity_kwh": 62,
        },
    ]


def test_shared_generic_requires_a_selection_and_selects_one_profile():
    data = {"vehicle_charging_configs": _shared_profiles()}
    loadpoint = profiles.physical_loadpoint_id(data["vehicle_charging_configs"][0])

    assert profiles.effective_profile(data["vehicle_charging_configs"], data, loadpoint) is None
    assert not profiles.profile_is_effective(data["vehicle_charging_configs"], data, "car-one")

    assert profiles.set_connected_ev(data, loadpoint, "car-two") == "car-two"
    selected = profiles.effective_profile(data["vehicle_charging_configs"], data, loadpoint)

    assert selected["vehicle_id"] == "car-two"
    assert selected["battery_capacity_kwh"] == 62
    assert profiles.profile_is_effective(data["vehicle_charging_configs"], data, "car-two")
    assert not profiles.profile_is_effective(data["vehicle_charging_configs"], data, "car-one")


def test_selection_service_is_persistent_command_free_and_rejects_owned_switch():
    data = {"vehicle_charging_configs": _shared_profiles()}
    hass = _Hass(data)
    loadpoint = profiles.physical_loadpoint_id(data["vehicle_charging_configs"][0])

    assert asyncio.run(profiles.async_set_connected_ev(hass, _Entry(), loadpoint, "car-one")) == "car-one"
    assert data["connected_ev_by_loadpoint"] == {loadpoint: "car-one"}
    assert hass.data["power_sync"]["entry-1"]["automation_store"].saved == 1
    assert ownership.get_ev_last_commands(hass, _Entry()) == {}

    ownership.claim_ev_ownership(hass, _Entry(), "car-one", owner_mode="smart_schedule")
    with pytest.raises(ValueError, match="cannot change"):
        asyncio.run(profiles.async_set_connected_ev(hass, _Entry(), loadpoint, "car-two"))


def test_shared_external_policy_is_selector_aware_and_unselected_fails_safe():
    data = {"vehicle_charging_configs": _shared_profiles()}
    hass = _Hass(data)
    loadpoint = profiles.physical_loadpoint_id(data["vehicle_charging_configs"][0])

    assert ownership.get_external_control_policy(hass, _Entry(), loadpoint) == "override"
    profiles.set_connected_ev(data, loadpoint, "car-one")
    assert ownership.get_external_control_policy(hass, _Entry(), loadpoint) == "yield"
    profiles.set_connected_ev(data, loadpoint, "car-two")
    assert ownership.get_external_control_policy(hass, _Entry(), loadpoint) == "override"


def test_legacy_single_profile_does_not_gain_selector_storage_or_change_policy():
    data = {
        "vehicle_charging_configs": [
            {"vehicle_id": "generic_ev", "charger_type": "generic", "external_control_policy": "yield"}
        ]
    }
    before = repr(data)
    hass = _Hass(data)

    assert profiles.effective_profile(data["vehicle_charging_configs"], data, "generic_ev")["vehicle_id"] == "generic_ev"
    assert ownership.get_external_control_policy(hass, _Entry(), None) == "yield"
    assert repr(data) == before


def test_mode_action_validation_and_yield_handsoff():
    data = {"vehicle_charging_configs": _shared_profiles()}
    data["vehicle_charging_configs"][1]["external_session_policy"] = {
        "smart_schedule": "abort"
    }
    hass = _Hass(data)
    loadpoint = profiles.physical_loadpoint_id(data["vehicle_charging_configs"][0])
    profiles.set_connected_ev(data, loadpoint, "car-two")

    assert ownership.get_external_session_policy(hass, _Entry(), loadpoint, "smart_schedule") == "abort"
    profiles.set_connected_ev(data, loadpoint, "car-one")
    # Yield remains hands-off even if a profile later adds an action field.
    data["vehicle_charging_configs"][0]["external_session_policy"] = "abort"
    assert ownership.get_external_session_policy(hass, _Entry(), loadpoint, "smart_schedule") is None
    with pytest.raises(ValueError):
        ownership.validate_external_session_policy("stop_forever")
