"""Regression coverage for partial-day Amber metered cost."""

import ast
from dataclasses import asdict, make_dataclass
from datetime import date, datetime, timedelta, timezone
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
COORDINATOR = ROOT / "custom_components" / "power_sync" / "coordinator.py"
SENSOR = ROOT / "custom_components" / "power_sync" / "sensor.py"


def _coordinator_method(name: str, now: datetime):
    tree = ast.parse(COORDINATOR.read_text())
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AmberUsageCoordinator"
    )
    method = next(
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    module = ast.Module(body=[method], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "timedelta": timedelta,
        "DayUsage": object,
        "dt_util": SimpleNamespace(now=lambda: now),
    }
    exec(compile(module, str(COORDINATOR), "exec"), namespace)
    return namespace[name]


def test_today_period_selects_only_current_partial_day():
    now = datetime(2026, 7, 22, 14, 0, tzinfo=timezone.utc)
    get_days = _coordinator_method("_get_days_for_period", now)
    today = object()
    yesterday = object()
    holder = SimpleNamespace(
        _days={"2026-07-22": today, "2026-07-21": yesterday}
    )

    assert get_days(holder, "today") == [today]
    assert get_days(holder, "yesterday") == [yesterday]


def test_today_sensor_rejects_stale_or_missing_usage_instead_of_reporting_zero():
    source = SENSOR.read_text()
    amber = source[source.index("class AmberUsageSensor"):]

    assert 'if self._period == "today" and not coord.is_fresh():' in amber
    assert 'if self._period == "today" and summary.get("days_count", 0) == 0:' in amber
    assert 'attrs["partial_day"] = True' in amber
    assert 'attrs["fresh"] = coord.is_fresh()' in amber


def test_partial_today_can_refresh_even_if_interval_quality_temporarily_drops():
    source = COORDINATOR.read_text()
    process = source[
        source.index("    def _process_intervals"):
        source.index("    def _prune_old_days")
    ]

    assert 'is_partial_today = day_key == dt_util.now().date().isoformat()' in process
    assert "if existing and not is_partial_today:" in process


@pytest.fixture
def usage_coordinator():
    """Exercise the real constructor and aggregation without HA I/O."""
    tree = ast.parse(COORDINATOR.read_text())
    day_class = next(
        n for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "DayUsage"
    )
    day_type = make_dataclass(
        "DayUsage",
        [n.target.id for n in day_class.body if isinstance(n, ast.AnnAssign)],
    )
    cls = next(
        n for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "AmberUsageCoordinator"
    )
    names = {
        "__init__", "_daily_supply_fee", "_aggregate", "get_summary",
        "get_savings_summary", "get_range", "_get_days_for_period",
    }
    cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
    future = ast.ImportFrom(
        module="__future__", names=[ast.alias(name="annotations")], level=0
    )
    module = ast.Module(body=[future, cls], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "date": date,
        "timedelta": timedelta,
        "math": math,
        "asdict": asdict,
        "DayUsage": day_type,
        "AMBER_DEFAULT_MONTHLY_SUPPLY_FEE": 25.0,
        "CONF_DAILY_SUPPLY_CHARGE": "daily_supply_charge",
        "CONF_MONTHLY_SUPPLY_CHARGE": "monthly_supply_charge",
        "async_get_clientsession": lambda hass: None,
        "Store": lambda *args: None,
        "USAGE_STORAGE_VERSION": 2,
        "USAGE_STORAGE_KEY": "power_sync.amber_usage",
        "dt_util": SimpleNamespace(
            now=lambda: datetime(2026, 10, 20, tzinfo=timezone.utc)
        ),
    }
    exec(compile(module, str(COORDINATOR), "exec"), namespace)
    entry = SimpleNamespace(options={}, data={})
    hass = SimpleNamespace(config_entries=SimpleNamespace(
        async_get_entry=lambda entry_id: entry if entry_id == "test-entry" else None
    ))
    coordinator = namespace["AmberUsageCoordinator"](hass, "token", "site", "test-entry")
    for day in ("2026-10-19", "2026-10-20"):
        coordinator._days[day] = day_type(
            day, 2.0, 1.0, 0.0, 0.60, 0.10, 0.50, "billable"
        )
        coordinator._baselines[day] = 2.0
    return coordinator, entry


def test_saved_daily_charge_flows_into_today_summary_and_range(usage_coordinator):
    coordinator, entry = usage_coordinator
    entry.data["daily_supply_charge"] = 0.70
    entry.options.update(daily_supply_charge=1.08, monthly_supply_charge=25.0)

    summary = coordinator.get_savings_summary("today")

    assert summary["supply_charge"] == 1.08
    assert summary["net_cost"] == 1.58
    assert summary["import_cost"] == 0.60
    assert summary["export_earnings"] == 0.10
    assert summary["baseline_cost"] == 3.08
    assert summary["savings"] == 1.50
    days = coordinator.get_range("2026-10-19", "2026-10-20")
    assert [day["supply_charge"] for day in days] == [1.08, 1.08]
    assert [day["net_cost"] for day in days] == [1.58, 1.58]
    assert coordinator.get_summary("today")["net_cost"] == 1.58
    assert coordinator.get_summary("month")["net_cost"] == 1.58
    combined = coordinator._aggregate(list(coordinator._days.values()))
    assert combined["supply_charge"] == 2.16
    assert combined["net_cost"] == 3.16


def test_daily_charge_changes_apply_without_restart_or_usage_refetch(usage_coordinator):
    coordinator, entry = usage_coordinator
    assert coordinator.get_summary("today")["supply_charge"] == 0.81
    entry.data["daily_supply_charge"] = 1.08
    assert coordinator.get_summary("today")["supply_charge"] == 1.08
    entry.options["daily_supply_charge"] = 1.23
    assert coordinator.get_summary("today")["supply_charge"] == 1.23
    entry.options["daily_supply_charge"] = 0.0
    assert coordinator.get_summary("today")["supply_charge"] == 0.0
    assert coordinator.get_summary("today")["net_cost"] == 0.50


@pytest.mark.parametrize("value", [-1, "invalid", None, float("nan"), float("inf"), True])
def test_invalid_saved_daily_charge_keeps_valid_monthly_fallback(usage_coordinator, value):
    coordinator, entry = usage_coordinator
    entry.options.update(daily_supply_charge=value, monthly_supply_charge=31.0)
    assert coordinator.get_summary("today")["supply_charge"] == 1.0


def test_legacy_monthly_charge_uses_each_dates_month_and_live_options(usage_coordinator):
    coordinator, entry = usage_coordinator
    entry.data["monthly_supply_charge"] = 31.0
    assert coordinator._daily_supply_fee("2026-10-20") == 1.0
    entry.options["monthly_supply_charge"] = 29.0
    assert coordinator._daily_supply_fee("2024-02-29") == 1.0
    assert coordinator._daily_supply_fee("2026-02-20") == pytest.approx(29 / 28)
    entry.options["monthly_supply_charge"] = 0.0
    assert coordinator._daily_supply_fee("2026-10-20") == 0.0


@pytest.mark.parametrize("value", [-1, "invalid", None, float("nan"), float("inf"), True])
def test_invalid_monthly_charge_cannot_poison_totals(usage_coordinator, value):
    coordinator, entry = usage_coordinator
    entry.options["monthly_supply_charge"] = value
    assert coordinator.get_summary("today")["supply_charge"] == 0.0


def test_missing_usage_days_do_not_accrue_supply_charge(usage_coordinator):
    coordinator, entry = usage_coordinator
    entry.options["daily_supply_charge"] = 1.08
    coordinator._days.clear()
    assert coordinator.get_summary("today")["supply_charge"] == 0.0
    assert coordinator.get_range("2026-10-19", "2026-10-20") == []
