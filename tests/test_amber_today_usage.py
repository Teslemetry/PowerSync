"""Regression coverage for partial-day Amber metered cost."""

import ast
from dataclasses import asdict, make_dataclass
from datetime import date, datetime, timedelta, timezone
import math
import logging
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
        "_process_intervals",
        "_load_store", "_save_store", "is_fresh",
    }
    cls.body = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    future = ast.ImportFrom(
        module="__future__", names=[ast.alias(name="annotations")], level=0
    )
    module = ast.Module(body=[future, cls], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "date": date,
        "datetime": datetime,
        "timedelta": timedelta,
        "math": math,
        "_QUALITY_RANK": {"estimated": 0, "mixed": 1, "billable": 2},
        "_LOGGER": logging.getLogger(__name__),
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


def _usage_row(day, nem_time, kwh=0.0, cost=0.0, channel="general"):
    return {"date": day, "nemTime": nem_time, "channelType": channel,
            "kwh": kwh, "cost": cost, "quality": "billable"}


def test_yesterdays_final_zero_interval_does_not_create_billable_today(usage_coordinator):
    coordinator, entry = usage_coordinator
    coordinator._days.clear()
    entry.options["daily_supply_charge"] = 0.0
    coordinator._process_intervals([
        _usage_row("2026-10-19", "2026-10-19T23:30:00+10:00", 2.0, 60.0),
        _usage_row("2026-10-19", "2026-10-20T00:00:00+10:00"),
    ])

    assert coordinator.get_summary("today")["days_count"] == 0
    yesterday = coordinator.get_summary("yesterday")
    assert yesterday["import_kwh"] == 2.0
    assert yesterday["net_cost"] == 0.60


@pytest.mark.parametrize("kwh,cost", [(0.0, 0.0), (2.0, 60.0)])
def test_genuine_today_rows_include_final_interval_in_same_billing_day(usage_coordinator, kwh, cost):
    coordinator, entry = usage_coordinator
    coordinator._days.clear()
    entry.options["daily_supply_charge"] = 0.0
    coordinator._process_intervals([
        _usage_row("2026-10-20", "2026-10-20T23:30:00+10:00", kwh, cost),
        _usage_row("2026-10-20", "2026-10-21T00:00:00+10:00", 1.0, -10.0, "feedIn"),
    ])

    today = coordinator.get_summary("today")
    assert today["days_count"] == 1
    assert today["import_kwh"] == kwh
    assert today["export_kwh"] == 1.0
    assert today["net_cost"] == round(cost / 100 - 0.10, 2)
    assert "2026-10-21" not in coordinator._days


def test_genuinely_measured_zero_remains_billable(usage_coordinator):
    coordinator, entry = usage_coordinator
    coordinator._days.clear()
    entry.options["daily_supply_charge"] = 0.0
    coordinator._process_intervals([
        _usage_row("2026-10-20", "2026-10-20T12:00:00+10:00")
    ])
    summary = coordinator.get_summary("today")
    assert summary["days_count"] == 1
    assert summary["quality"] == "billable"
    assert summary["net_cost"] == 0.0


@pytest.mark.parametrize("day", [None, "invalid", ""])
def test_invalid_billing_date_cannot_create_today_from_interval_end(usage_coordinator, day):
    coordinator, _ = usage_coordinator
    coordinator._days.clear()
    coordinator._process_intervals([
        _usage_row(day, "2026-10-20T00:00:00+10:00")
    ])
    assert coordinator._days == {}


@pytest.mark.asyncio
async def test_restart_discards_old_date_buckets_preserves_baselines_and_refetches(usage_coordinator):
    coordinator, _ = usage_coordinator
    saved = {
        "days": [asdict(du) for du in coordinator._days.values()],
        "baselines": {"2026-10-19": 2.0},
        "last_fetch": "2026-10-20T00:00:00+00:00",
    }

    async def load():
        return saved

    coordinator._store = SimpleNamespace(async_load=load)
    coordinator._days.clear()
    await coordinator._load_store()
    assert coordinator._days == {}  # _fetch_usage will backfill 90 days
    assert coordinator._baselines == {"2026-10-19": 2.0}
    assert not coordinator.is_fresh()

    coordinator._process_intervals([
        _usage_row("2026-10-19", "2026-10-20T00:00:00+10:00")
    ])
    coordinator._last_fetch = datetime(2026, 10, 20, tzinfo=timezone.utc)
    coordinator._store.async_delay_save = lambda callback, delay: saved.update(callback())
    coordinator._save_store()
    assert saved["billing_dates"] is True

    coordinator._days.clear()
    coordinator._last_fetch = None
    await coordinator._load_store()
    assert coordinator.is_fresh()
    assert coordinator.get_summary("today")["days_count"] == 0
    assert coordinator.get_summary("yesterday")["days_count"] == 1
    assert coordinator._baselines == {"2026-10-19": 2.0}
