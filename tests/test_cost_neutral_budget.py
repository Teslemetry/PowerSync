"""Unit tests for Cost Neutral local-day accounting."""

import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "power_sync"
    / "optimization"
    / "cost_neutral.py"
)
SPEC = importlib.util.spec_from_file_location("cost_neutral_test_module", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
CostNeutralBudget = MODULE.CostNeutralBudget
CostNeutralPlan = MODULE.CostNeutralPlan
elapsed_settlement_seconds = MODULE.elapsed_settlement_seconds


def test_exact_daily_cost_example_produces_two_dollar_export_cap():
    budget = CostNeutralBudget(
        supply_charge=1.20,
        measured_import_cost=0.80,
        measured_export_earnings=0.50,
        forecast_import_cost=0.50,
        forecast_natural_export_earnings=0.0,
    )

    assert budget.base_projected_cost == 2.0
    assert budget.battery_export_earnings_cap == 2.0
    assert budget.fixed_cost_allowance == 1.5


def test_natural_export_covering_daily_cost_sets_zero_battery_export_cap():
    budget = CostNeutralBudget(
        supply_charge=0.0,
        measured_import_cost=0.50,
        measured_export_earnings=0.25,
        forecast_import_cost=0.25,
        forecast_natural_export_earnings=0.75,
    )

    assert budget.base_projected_cost == -0.25
    assert budget.battery_export_earnings_cap == 0.0


def test_missing_or_zero_supply_still_covers_import_costs():
    budget = CostNeutralBudget(
        supply_charge=0.0,
        measured_import_cost=0.75,
        measured_export_earnings=0.10,
        forecast_import_cost=0.35,
        forecast_natural_export_earnings=0.0,
    )

    assert budget.battery_export_earnings_cap == 1.0


def test_cost_neutral_plan_normalizes_alignment_and_invalid_values():
    plan = CostNeutralPlan(
        day_ids=["2026-08-01", "missing", "2026-08-02"],
        earnings_caps_by_day={
            "2026-08-01": 1.25,
            "2026-08-02": -1.0,
            "invalid": float("nan"),
        },
        forecast_import_costs_by_day={"2026-08-01": 0.25},
        fixed_cost_allowances_by_day={"2026-08-01": 1.0},
        current_day="2026-08-01",
        timezone="Australia/Sydney",
        forecast_natural_export_earnings_by_day={
            "2026-08-01": -0.25,
            "2026-08-02": 0.5,
            "missing": 1.0,
            "invalid": float("nan"),
        },
    ).normalized(4)

    assert plan.forecast_natural_export_earnings_by_day == {
        "2026-08-01": -0.25, "2026-08-02": 0.5,
    }
    assert plan.day_ids == ["2026-08-01", None, "2026-08-02", None]
    assert plan.earnings_caps_by_day == {
        "2026-08-01": 1.25,
        "2026-08-02": 0.0,
    }
    assert plan.forecast_import_costs_by_day == {
        "2026-08-01": 0.25,
        "2026-08-02": 0.0,
    }
    assert plan.fixed_cost_allowances_by_day == {
        "2026-08-01": 1.0,
        "2026-08-02": 0.0,
    }


def test_elapsed_settlement_time_uses_real_instants_across_dst_fallback():
    local_tz = ZoneInfo("Australia/Sydney")
    first_130 = datetime(2026, 4, 5, 2, 30, tzinfo=local_tz, fold=0)
    second_130 = datetime(2026, 4, 5, 2, 30, tzinfo=local_tz, fold=1)

    assert elapsed_settlement_seconds(first_130, second_130) == 3600.0
