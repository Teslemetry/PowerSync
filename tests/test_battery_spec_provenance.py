"""Regression coverage for persisted battery-spec provenance."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
OPTIMIZATION_PATH = (
    ROOT
    / "custom_components"
    / "power_sync"
    / "optimization"
    / "coordinator.py"
)


def _load_provenance_helpers():
    source = OPTIMIZATION_PATH.read_text()
    tree = ast.parse(source)
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name
        in {
            "_positive_battery_spec_value",
            "_entry_battery_spec_value",
            "battery_specs_source_by_field",
        }
    ]
    assert {node.name for node in functions} == {
        "_positive_battery_spec_value",
        "_entry_battery_spec_value",
        "battery_specs_source_by_field",
    }
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace: dict[str, Any] = {
        "Any": Any,
        "_BATTERY_SPEC_FIELDS": (
            "battery_capacity_wh",
            "max_charge_w",
            "max_discharge_w",
        ),
        "_BATTERY_SPEC_PERSISTED_KEYS": {
            "battery_capacity_wh": "optimization_battery_capacity_wh",
            "max_charge_w": "optimization_max_charge_w",
            "max_discharge_w": "optimization_max_discharge_w",
        },
    }
    exec(compile(module, str(OPTIMIZATION_PATH), "exec"), namespace)
    return namespace["battery_specs_source_by_field"]


def test_canonical_options_keep_configured_values_manual_after_reload():
    source_by_field = _load_provenance_helpers()
    entry = SimpleNamespace(
        data={},
        options={
            "optimization_battery_capacity_wh": 9700,
            "optimization_max_charge_w": 5000,
            "optimization_max_discharge_w": 5000,
        },
    )

    assert source_by_field(entry) == {
        "battery_capacity_wh": "manual",
        "max_charge_w": "manual",
        "max_discharge_w": "manual",
    }


def test_options_override_legacy_data_and_partial_settings_remain_per_field():
    source_by_field = _load_provenance_helpers()
    entry = SimpleNamespace(
        data={
            "optimization_battery_capacity_wh": 12000,
            "optimization_max_charge_w": 4000,
        },
        options={
            "optimization_battery_capacity_wh": 9700,
        },
    )

    assert source_by_field(entry) == {
        "battery_capacity_wh": "manual",
        "max_charge_w": "manual",
        "max_discharge_w": "default",
    }


def test_missing_or_nonpositive_persisted_values_remain_default():
    source_by_field = _load_provenance_helpers()
    entry = SimpleNamespace(
        data={},
        options={
            "optimization_battery_capacity_wh": 0,
            "optimization_max_charge_w": -1,
            "optimization_max_discharge_w": None,
        },
    )

    assert source_by_field(entry) == {
        "battery_capacity_wh": "default",
        "max_charge_w": "default",
        "max_discharge_w": "default",
    }
