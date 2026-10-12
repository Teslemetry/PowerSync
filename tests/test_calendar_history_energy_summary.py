"""Regression tests for non-Tesla calendar-history energy rows."""

from __future__ import annotations

import ast
import asyncio
import math
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any


INIT_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "power_sync"
    / "__init__.py"
)


def _calendar_namespace() -> dict[str, Any]:
    source = INIT_PATH.read_text()
    tree = ast.parse(source)
    wanted_functions = {
        "_energy_summary_wh",
        "_calendar_entry_from_energy_summary",
        "_calendar_entry_with_detail_aliases",
        "_calendar_entry_has_energy",
        "_calendar_energy_state_wh",
        "_calendar_entry_from_energy_sensor_states",
        "_merge_calendar_energy_entries",
        "_calendar_current_entry",
        "_calendar_time_series_from_energy_summary",
        "_calendar_statistic_suffixes",
        "_find_calendar_statistic_entity_ids",
        "_calendar_residual_entry",
        "_calendar_reconcile_current_day_rows",
        "_calendar_period_range",
        "_calendar_range_includes_today",
        "_calendar_statistics_end_dt",
        "_calendar_statistics_start_datetime",
        "_calendar_history_bucket_timestamp",
        "_calendar_time_series_from_state_history_rows",
        "_calendar_time_series_from_state_history",
        "_calendar_time_series_from_statistics",
        "_calendar_time_series_totals_kwh",
        "_find_calendar_tariff_schedule",
        "_calendar_tou_periods_from_price_keys",
        "_calendar_time_series_is_subdaily",
        "_calculate_cost_from_tariff",
        "_find_season_for_month",
        "_weighted_avg_rates",
        "_calendar_current_optimizer_cost_summary",
        "_calendar_result_from_energy_summary",
    }
    body: list[ast.stmt] = []
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "_CALENDAR_STATISTIC_FIELDS"
                for target in node.targets
            )
        ):
            body.append(node)
        elif (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "_CALENDAR_STATISTIC_FIELD_ALIASES"
                for target in node.targets
            )
        ):
            body.append(node)
        elif (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in wanted_functions
        ):
            body.append(node)

    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)

    namespace: dict[str, Any] = {
        "Any": Any,
        "datetime": datetime,
        "timedelta": timedelta,
        "timezone": timezone,
        "DOMAIN": "power_sync",
        "math": math,
        "HomeAssistant": object,
        "dt_util": SimpleNamespace(
            now=lambda: datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
            as_local=lambda value: value,
            as_utc=lambda value: value,
        ),
        "_LOGGER": SimpleNamespace(
            info=lambda *args, **kwargs: None,
            debug=lambda *args, **kwargs: None,
            warning=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
        ),
    }
    exec(compile(module, str(INIT_PATH), "exec"), namespace)
    return namespace


class _States:
    def __init__(self, states: dict[str, Any]) -> None:
        self._states = states

    def get(self, entity_id: str) -> Any:
        return self._states.get(entity_id)

    def async_all(self, domain: str) -> list[Any]:
        return []


def _state(value: str, unit: str = "kWh") -> SimpleNamespace:
    return SimpleNamespace(state=value, attributes={"unit_of_measurement": unit})


def _history_state(
    value: str,
    timestamp: datetime,
    unit: str = "kWh",
) -> SimpleNamespace:
    return SimpleNamespace(
        state=value,
        attributes={"unit_of_measurement": unit},
        last_changed=timestamp,
        last_updated=timestamp,
    )


@contextmanager
def _fake_entity_registry(entities: dict[str, Any]):
    helpers = SimpleNamespace()
    entity_registry = SimpleNamespace(
        async_get=lambda hass: SimpleNamespace(entities=entities)
    )
    helpers.entity_registry = entity_registry
    previous_homeassistant = sys.modules.get("homeassistant")
    previous_helpers = sys.modules.get("homeassistant.helpers")
    previous_registry = sys.modules.get("homeassistant.helpers.entity_registry")
    sys.modules["homeassistant"] = SimpleNamespace(helpers=helpers)
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.entity_registry"] = entity_registry
    try:
        yield
    finally:
        for module_name, previous in (
            ("homeassistant", previous_homeassistant),
            ("homeassistant.helpers", previous_helpers),
            ("homeassistant.helpers.entity_registry", previous_registry),
        ):
            if previous is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = previous


@contextmanager
def _fake_recorder_history(get_significant_states):
    class _Recorder:
        async def async_add_executor_job(self, target, *args):
            return target(*args)

    recorder = SimpleNamespace(get_instance=lambda hass: _Recorder())
    history = SimpleNamespace(get_significant_states=get_significant_states)
    components = SimpleNamespace(recorder=recorder)
    previous_modules = {
        name: sys.modules.get(name)
        for name in (
            "homeassistant",
            "homeassistant.components",
            "homeassistant.components.recorder",
            "homeassistant.components.recorder.history",
        )
    }
    sys.modules["homeassistant"] = SimpleNamespace(components=components)
    sys.modules["homeassistant.components"] = components
    sys.modules["homeassistant.components.recorder"] = recorder
    sys.modules["homeassistant.components.recorder.history"] = history
    try:
        yield
    finally:
        for module_name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = previous


@contextmanager
def _fake_recorder_statistics(statistics_during_period):
    class _Recorder:
        async def async_add_executor_job(self, target, *args):
            return target(*args)

    recorder = SimpleNamespace(get_instance=lambda hass: _Recorder())
    statistics = SimpleNamespace(
        statistics_during_period=statistics_during_period
    )
    components = SimpleNamespace(recorder=recorder)
    previous_modules = {
        name: sys.modules.get(name)
        for name in (
            "homeassistant",
            "homeassistant.components",
            "homeassistant.components.recorder",
            "homeassistant.components.recorder.statistics",
        )
    }
    sys.modules["homeassistant"] = SimpleNamespace(components=components)
    sys.modules["homeassistant.components"] = components
    sys.modules["homeassistant.components.recorder"] = recorder
    sys.modules["homeassistant.components.recorder.statistics"] = statistics
    try:
        yield
    finally:
        for module_name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = previous


def test_calendar_range_includes_today_when_end_is_now_snapshot():
    namespace = _calendar_namespace()
    first_now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
    later_now = first_now + timedelta(microseconds=1)
    today_start = datetime(2026, 5, 16, tzinfo=timezone.utc)
    yesterday_start = today_start - timedelta(days=1)

    assert namespace["_calendar_range_includes_today"](
        today_start,
        first_now,
        later_now,
    )
    assert not namespace["_calendar_range_includes_today"](
        yesterday_start,
        today_start,
        later_now,
    )


def test_day_period_statistics_include_today_until_request_end():
    namespace = _calendar_namespace()
    now = datetime(2026, 5, 16, 18, 30, tzinfo=timezone.utc)
    end_dt = now

    assert namespace["_calendar_statistics_end_dt"](
        "day",
        end_dt,
        now,
        True,
    ) == end_dt


def test_month_period_statistics_exclude_today_to_avoid_live_duplicate():
    namespace = _calendar_namespace()
    now = datetime(2026, 5, 16, 18, 30, tzinfo=timezone.utc)
    end_dt = now

    assert namespace["_calendar_statistics_end_dt"](
        "month",
        end_dt,
        now,
        True,
    ) == datetime(2026, 5, 16, tzinfo=timezone.utc)


def test_calendar_residual_entry_subtracts_existing_hourly_rows():
    namespace = _calendar_namespace()
    current_entry = {
        "timestamp": "2026-05-16T18:30:00+00:00",
        "solar_generation": 10000,
        "battery_discharge": 4000,
        "battery_charge": 6000,
        "grid_import": 12000,
        "grid_export": 3000,
        "home_consumption": 15000,
    }
    existing_rows = [
        {
            "timestamp": "2026-05-16T08:00:00+00:00",
            "solar_generation": 2500,
            "battery_discharge": 500,
            "battery_charge": 1000,
            "grid_import": 2000,
            "grid_export": 0,
            "home_consumption": 3000,
        },
        {
            "timestamp": "2026-05-16T09:00:00+00:00",
            "solar_generation": 3500,
            "battery_discharge": 1500,
            "battery_charge": 2000,
            "grid_import": 4000,
            "grid_export": 500,
            "home_consumption": 5000,
        },
    ]

    residual = namespace["_calendar_residual_entry"](current_entry, existing_rows)

    assert residual["solar_generation"] == 4000
    assert residual["battery_discharge"] == 2000
    assert residual["battery_charge"] == 3000
    assert residual["grid_import"] == 6000
    assert residual["grid_export"] == 2500
    assert residual["home_consumption"] == 7000
    assert residual["solar_energy_exported"] == 4000
    assert residual["consumer_energy_imported"] == 7000


def test_current_day_rows_fall_back_to_live_totals_when_statistics_are_stale():
    """A reset-skewed recorder row must not mix yesterday into today's summary."""
    namespace = _calendar_namespace()
    current_entry = {
        "timestamp": "2026-07-20T20:28:38+10:00",
        "solar_generation": 40_381,
        "battery_discharge": 18_350,
        "battery_charge": 38_680,
        "grid_import": 13_060,
        "grid_export": 13_440,
        "home_consumption": 20_260,
    }
    recorder_rows = [
        {
            "timestamp": "2026-07-20T00:00:00+10:00",
            "solar_generation": 23_440,
            "battery_discharge": 41_922,
            "battery_charge": 38_754,
            "grid_import": 31_592,
            "grid_export": 28_468,
            "home_consumption": 36_044,
        }
    ]

    rows = namespace["_calendar_reconcile_current_day_rows"](
        recorder_rows,
        current_entry,
    )

    assert len(rows) == 1
    assert rows[0]["solar_generation"] == 40_381
    assert rows[0]["battery_discharge"] == 18_350
    assert rows[0]["battery_charge"] == 38_680
    assert rows[0]["grid_import"] == 13_060
    assert rows[0]["grid_export"] == 13_440
    assert rows[0]["home_consumption"] == 20_260
    assert rows[0]["grid_energy_imported"] == 13_060
    assert rows[0]["grid_energy_exported"] == 13_440


def test_current_day_rows_keep_hourly_shape_when_statistics_match_live_totals():
    namespace = _calendar_namespace()
    current_entry = {
        "timestamp": "2026-07-20T20:28:38+10:00",
        "solar_generation": 10_000,
        "battery_discharge": 4_000,
        "battery_charge": 6_000,
        "grid_import": 12_000,
        "grid_export": 3_000,
        "home_consumption": 15_000,
    }
    recorder_rows = [
        {
            "timestamp": "2026-07-20T08:00:00+10:00",
            "solar_generation": 6_000,
            "battery_discharge": 2_000,
            "battery_charge": 3_000,
            "grid_import": 6_000,
            "grid_export": 500,
            "home_consumption": 8_000,
        }
    ]

    rows = namespace["_calendar_reconcile_current_day_rows"](
        recorder_rows,
        current_entry,
    )

    assert len(rows) == 2
    assert rows[0]["timestamp"] == "2026-07-20T08:00:00+10:00"
    assert sum(row["grid_import"] for row in rows) == 12_000
    assert sum(row["grid_export"] for row in rows) == 3_000
    assert sum(row["solar_generation"] for row in rows) == 10_000


def test_current_day_rows_treat_an_authoritative_zero_as_current():
    namespace = _calendar_namespace()
    current_entry = {
        "timestamp": "2026-07-20T08:00:00+10:00",
        "solar_generation": 10_000,
        "battery_discharge": 0,
        "battery_charge": 0,
        "grid_import": 0,
        "grid_export": 0,
        "home_consumption": 0,
    }
    recorder_rows = [
        {
            "timestamp": "2026-07-20T07:00:00+10:00",
            "solar_generation": 8_000,
            "battery_discharge": 0,
            "battery_charge": 0,
            "grid_import": 700,
            "grid_export": 600,
            "home_consumption": 0,
        }
    ]

    rows = namespace["_calendar_reconcile_current_day_rows"](
        recorder_rows,
        current_entry,
    )

    assert len(rows) == 1
    assert rows[0]["solar_generation"] == 10_000
    assert rows[0]["grid_export"] == 0


def test_current_day_rows_drop_single_stale_solar_carryover():
    """One yesterday-valued field must not survive beside progressed live totals."""
    namespace = _calendar_namespace()
    current_entry = {
        "timestamp": "2026-07-22T06:39:00+10:00",
        "solar_generation": 0,
        "battery_discharge": 4_060,
        "battery_charge": 0,
        "grid_import": 23,
        "grid_export": 24,
        "home_consumption": 4_060,
    }
    recorder_rows = [
        {
            "timestamp": "2026-07-22T00:00:00+10:00",
            "solar_generation": 42_600,
            "battery_discharge": 0,
            "battery_charge": 0,
            "grid_import": 0,
            "grid_export": 0,
            "home_consumption": 0,
        }
    ]

    rows = namespace["_calendar_reconcile_current_day_rows"](
        recorder_rows,
        current_entry,
    )

    assert len(rows) == 1
    assert rows[0]["solar_generation"] == 0
    assert rows[0]["battery_discharge"] == 4_060
    assert rows[0]["grid_import"] == 23
    assert rows[0]["grid_export"] == 24
    assert rows[0]["home_consumption"] == 4_060
    assert rows[0]["solar_energy_exported"] == 0
    assert rows[0]["battery_energy_exported"] == 4_060
    assert rows[0]["grid_energy_imported"] == 23
    assert rows[0]["grid_energy_exported"] == 24
    assert rows[0]["consumer_energy_imported"] == 4_060


def test_current_day_rows_keep_recorder_history_for_a_fresh_accumulator():
    namespace = _calendar_namespace()
    current_entry = {
        "timestamp": "2026-07-20T08:00:00+10:00",
        "solar_generation": 2_000,
        "battery_discharge": 1_000,
        "battery_charge": 0,
        "grid_import": 0,
        "grid_export": 0,
        "home_consumption": 0,
    }
    recorder_rows = [
        {
            "timestamp": "2026-07-20T07:00:00+10:00",
            "solar_generation": 12_000,
            "battery_discharge": 5_000,
            "battery_charge": 0,
            "grid_import": 0,
            "grid_export": 0,
            "home_consumption": 0,
        }
    ]

    rows = namespace["_calendar_reconcile_current_day_rows"](
        recorder_rows,
        current_entry,
    )

    assert len(rows) == 1
    assert sum(row["solar_generation"] for row in rows) == 12_000
    assert sum(row["battery_discharge"] for row in rows) == 5_000


def test_calendar_state_history_rows_convert_daily_totals_to_hourly_deltas():
    namespace = _calendar_namespace()
    start = datetime(2026, 5, 16, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
    history = {
        "sensor.power_sync_daily_solar_energy": [
            _history_state("2.0", datetime(2026, 5, 16, 9, 15, tzinfo=timezone.utc)),
            _history_state("4.5", datetime(2026, 5, 16, 10, 45, tzinfo=timezone.utc)),
        ],
        "sensor.power_sync_daily_grid_import": [
            _history_state("1.2", datetime(2026, 5, 16, 10, 10, tzinfo=timezone.utc)),
            _history_state("1.7", datetime(2026, 5, 16, 11, 5, tzinfo=timezone.utc)),
        ],
    }
    entity_to_field = {
        "sensor.power_sync_daily_solar_energy": "solar_generation",
        "sensor.power_sync_daily_grid_import": "grid_import",
    }

    rows = namespace["_calendar_time_series_from_state_history_rows"](
        history,
        entity_to_field,
        "day",
        start,
        end,
    )

    assert rows == [
        {
            "timestamp": "2026-05-16T09:00:00+00:00",
            "solar_generation": 2000,
            "battery_discharge": 0,
            "battery_charge": 0,
            "grid_import": 0,
            "grid_export": 0,
            "home_consumption": 0,
            "solar_energy_exported": 2000,
            "battery_energy_exported": 0,
            "battery_energy_imported": 0,
            "consumer_energy_imported": 0,
            "grid_energy_imported": 0,
            "grid_energy_exported": 0,
        },
        {
            "timestamp": "2026-05-16T10:00:00+00:00",
            "solar_generation": 2500,
            "battery_discharge": 0,
            "battery_charge": 0,
            "grid_import": 1200,
            "grid_export": 0,
            "home_consumption": 0,
            "solar_energy_exported": 2500,
            "battery_energy_exported": 0,
            "battery_energy_imported": 0,
            "consumer_energy_imported": 0,
            "grid_energy_imported": 1200,
            "grid_energy_exported": 0,
        },
        {
            "timestamp": "2026-05-16T11:00:00+00:00",
            "solar_generation": 0,
            "battery_discharge": 0,
            "battery_charge": 0,
            "grid_import": 500,
            "grid_export": 0,
            "home_consumption": 0,
            "solar_energy_exported": 0,
            "battery_energy_exported": 0,
            "battery_energy_imported": 0,
            "consumer_energy_imported": 0,
            "grid_energy_imported": 500,
            "grid_energy_exported": 0,
        },
    ]


def test_calendar_state_history_rows_ignore_same_day_transient_drop():
    namespace = _calendar_namespace()
    start = datetime(2026, 5, 16, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
    history = {
        "sensor.power_sync_daily_battery_charge_foxess": [
            _history_state("47.0", datetime(2026, 5, 16, 9, 0, tzinfo=timezone.utc)),
            _history_state("0", datetime(2026, 5, 16, 9, 5, tzinfo=timezone.utc)),
            _history_state("47.6", datetime(2026, 5, 16, 9, 10, tzinfo=timezone.utc)),
            _history_state("48.1", datetime(2026, 5, 16, 10, 0, tzinfo=timezone.utc)),
        ],
    }
    entity_to_field = {
        "sensor.power_sync_daily_battery_charge_foxess": "battery_charge",
    }

    rows = namespace["_calendar_time_series_from_state_history_rows"](
        history,
        entity_to_field,
        "day",
        start,
        end,
    )

    assert sum(row["battery_charge"] for row in rows) == 48100
    assert rows[0]["battery_charge"] == 47600
    assert rows[1]["battery_charge"] == 500


def test_calendar_state_history_rows_allow_next_day_reset():
    namespace = _calendar_namespace()
    start = datetime(2026, 5, 16, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 18, 0, 0, tzinfo=timezone.utc)
    history = {
        "sensor.power_sync_daily_solar_energy": [
            _history_state("8.0", datetime(2026, 5, 16, 23, 0, tzinfo=timezone.utc)),
            _history_state("0.5", datetime(2026, 5, 17, 7, 0, tzinfo=timezone.utc)),
            _history_state("3.0", datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)),
        ],
    }
    entity_to_field = {
        "sensor.power_sync_daily_solar_energy": "solar_generation",
    }

    rows = namespace["_calendar_time_series_from_state_history_rows"](
        history,
        entity_to_field,
        "week",
        start,
        end,
    )

    assert [row["solar_generation"] for row in rows] == [8000, 3000]


def test_calendar_state_history_excludes_pre_midnight_start_state():
    namespace = _calendar_namespace()
    start = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 7, 20, 6, 26, tzinfo=timezone.utc)
    captured: dict[str, bool] = {}

    def get_significant_states(
        hass,
        start_time,
        end_time,
        entity_ids,
        filters=None,
        include_start_time_state=True,
    ):
        captured["include_start_time_state"] = include_start_time_state
        states = []
        if include_start_time_state:
            # Home Assistant normally injects the pre-range state at start_time.
            states.append(_history_state("13.2", start_time))
        states.extend(
            [
                _history_state("0", start_time + timedelta(minutes=1)),
                _history_state("0.03", end_time - timedelta(minutes=1)),
            ]
        )
        return {entity_ids[0]: states}

    async def async_add_executor_job(target, *args):
        return target(*args)

    hass = SimpleNamespace(async_add_executor_job=async_add_executor_job)
    with _fake_recorder_history(get_significant_states):
        rows = asyncio.run(
            namespace["_calendar_time_series_from_state_history"](
                hass,
                "day",
                start,
                end,
                {"grid_import": "sensor.power_sync_daily_grid_import"},
            )
        )

    assert captured["include_start_time_state"] is False
    assert sum(row["grid_import"] for row in rows) == 30


def test_month_without_long_term_statistics_skips_raw_history_fallback():
    namespace = _calendar_namespace()
    entity_ids = {
        "solar_generation": "sensor.power_sync_daily_solar_energy",
    }
    namespace["_find_calendar_statistic_entity_ids"] = (
        lambda hass, entry_id: entity_ids
    )

    async def unexpected_raw_history(*_args, **_kwargs):
        raise AssertionError("month history must not scan raw recorder states")

    namespace["_calendar_time_series_from_state_history"] = unexpected_raw_history
    hass = SimpleNamespace(
        states=_States(
            {
                "sensor.power_sync_daily_solar_energy": _state("4.2"),
            }
        )
    )
    coordinator = SimpleNamespace(
        data={"energy_summary": {"pv_today_kwh": 4.2}}
    )

    def no_statistics(*_args, **_kwargs):
        return {}

    with _fake_recorder_statistics(no_statistics):
        rows, history_source = asyncio.run(
            namespace["_calendar_time_series_from_statistics"](
                hass,
                "month",
                None,
                coordinator,
                "entry-1",
            )
        )

    assert history_source == "long_term_statistics_unavailable"
    assert len(rows) == 1
    assert rows[0]["solar_generation"] == 4_200


def test_calendar_statistics_accept_numeric_starts_and_reject_invalid_values():
    namespace = _calendar_namespace()
    stamp = datetime(2026, 9, 16, 0, 0, tzinfo=timezone.utc)

    assert namespace["_calendar_statistics_start_datetime"](
        stamp.timestamp()
    ) == stamp
    assert namespace["_calendar_statistics_start_datetime"](stamp) is stamp
    assert namespace["_calendar_statistics_start_datetime"](True) is None
    assert namespace["_calendar_statistics_start_datetime"](math.nan) is None
    assert namespace["_calendar_statistics_start_datetime"](math.inf) is None
    assert namespace["_calendar_statistics_start_datetime"]("not-a-timestamp") is None


def test_calendar_statistics_numeric_start_populates_historical_month():
    namespace = _calendar_namespace()
    namespace["dt_util"].now = lambda: datetime(
        2026, 9, 19, 12, 0, tzinfo=timezone.utc
    )
    entity_id = "sensor.power_sync_daily_solar_energy"
    entity_ids = {"solar_generation": entity_id}
    namespace["_find_calendar_statistic_entity_ids"] = (
        lambda hass, entry_id: entity_ids
    )
    hass = SimpleNamespace(states=_States({entity_id: _state("4.2")}))
    coordinator = SimpleNamespace(
        data={"energy_summary": {"pv_today_kwh": 4.2}}
    )
    historical_start = datetime(2026, 9, 16, tzinfo=timezone.utc)

    def statistics(*_args: Any) -> dict[str, list[dict[str, Any]]]:
        return {
            entity_id: [
                {"start": historical_start.timestamp(), "change": 12.5}
            ]
        }

    with _fake_recorder_statistics(statistics):
        rows, history_source = asyncio.run(
            namespace["_calendar_time_series_from_statistics"](
                hass,
                "month",
                "2026-09-18",
                coordinator,
                "entry-1",
            )
        )

    assert history_source == "long_term_statistics"
    assert len(rows) == 1
    assert rows[0]["timestamp"] == historical_start.isoformat()
    assert rows[0]["solar_generation"] == 12_500


def test_calendar_statistic_finder_accepts_foxess_daily_battery_aliases():
    namespace = _calendar_namespace()
    entities = {
        "sensor.power_sync_daily_battery_charge_foxess": SimpleNamespace(
            domain="sensor",
            platform="power_sync",
            unique_id="entry-1_daily_battery_charge_foxess",
            entity_id="sensor.power_sync_daily_battery_charge_foxess",
        ),
        "sensor.power_sync_daily_battery_discharge_foxess": SimpleNamespace(
            domain="sensor",
            platform="power_sync",
            unique_id="entry-1_daily_battery_discharge_foxess",
            entity_id="sensor.power_sync_daily_battery_discharge_foxess",
        ),
    }
    hass = SimpleNamespace(
        states=_States(
            {
                "sensor.power_sync_daily_battery_charge_foxess": _state("47.5"),
                "sensor.power_sync_daily_battery_discharge_foxess": _state("42.7"),
            }
        )
    )

    with _fake_entity_registry(entities):
        entity_ids = namespace["_find_calendar_statistic_entity_ids"](
            hass, "entry-1"
        )

    assert entity_ids["battery_charge"] == "sensor.power_sync_daily_battery_charge_foxess"
    assert (
        entity_ids["battery_discharge"]
        == "sensor.power_sync_daily_battery_discharge_foxess"
    )


def test_current_calendar_entry_uses_live_daily_sensor_states_when_accumulator_is_zero():
    namespace = _calendar_namespace()
    entity_ids = {
        "solar_generation": "sensor.power_sync_daily_solar_energy",
        "grid_import": "sensor.power_sync_daily_grid_import",
        "grid_export": "sensor.power_sync_daily_grid_export",
        "home_consumption": "sensor.power_sync_daily_load",
    }
    namespace["_find_calendar_statistic_entity_ids"] = lambda hass, entry_id: entity_ids
    hass = SimpleNamespace(
        states=_States(
            {
                "sensor.power_sync_daily_solar_energy": _state("4.2"),
                "sensor.power_sync_daily_grid_import": _state("1.5"),
                "sensor.power_sync_daily_grid_export": _state("0.75"),
                "sensor.power_sync_daily_load": _state("5.6"),
            }
        )
    )
    coordinator = SimpleNamespace(data={"energy_summary": {}})

    entry = namespace["_calendar_current_entry"](hass, coordinator, "entry-1")

    assert entry["solar_generation"] == 4200
    assert entry["grid_import"] == 1500
    assert entry["grid_export"] == 750
    assert entry["home_consumption"] == 5600
    assert entry["solar_energy_exported"] == 4200
    assert entry["grid_energy_exported"] == 750
    assert entry["grid_energy_imported"] == 1500
    assert entry["consumer_energy_imported"] == 5600


def test_current_calendar_entry_keeps_coordinator_values_and_fills_only_missing_fields():
    namespace = _calendar_namespace()
    entity_ids = {
        "solar_generation": "sensor.power_sync_daily_solar_energy",
        "grid_import": "sensor.power_sync_daily_grid_import",
    }
    namespace["_find_calendar_statistic_entity_ids"] = lambda hass, entry_id: entity_ids
    hass = SimpleNamespace(
        states=_States(
            {
                "sensor.power_sync_daily_solar_energy": _state("9.9"),
                "sensor.power_sync_daily_grid_import": _state("1800", "Wh"),
            }
        )
    )
    coordinator = SimpleNamespace(
        data={
            "energy_summary": {
                "pv_today_kwh": 1.25,
                "grid_import_today_kwh": 0,
            }
        }
    )

    entry = namespace["_calendar_current_entry"](hass, coordinator, "entry-1")

    assert entry["solar_generation"] == 1250
    assert entry["grid_import"] == 1800


def test_current_calendar_entry_exposes_aggregate_tesla_style_aliases_only():
    namespace = _calendar_namespace()
    namespace["_find_calendar_statistic_entity_ids"] = lambda hass, entry_id: {}
    hass = SimpleNamespace(states=_States({}))
    coordinator = SimpleNamespace(
        data={
            "energy_summary": {
                "pv_today_kwh": 2.5,
                "discharge_today_kwh": 1.2,
                "charge_today_kwh": 3.4,
                "grid_import_today_kwh": 0.8,
                "grid_export_today_kwh": 0.6,
                "load_today_kwh": 2.1,
            }
        }
    )

    entry = namespace["_calendar_current_entry"](hass, coordinator, "entry-1")

    assert entry["solar_generation"] == 2500
    assert entry["battery_discharge"] == 1200
    assert entry["battery_charge"] == 3400
    assert entry["grid_import"] == 800
    assert entry["grid_export"] == 600
    assert entry["home_consumption"] == 2100
    assert entry["solar_energy_exported"] == 2500
    assert entry["battery_energy_exported"] == 1200
    assert entry["battery_energy_imported"] == 3400
    assert entry["grid_energy_imported"] == 800
    assert entry["grid_energy_exported"] == 600
    assert entry["consumer_energy_imported"] == 2100
    assert "battery_energy_imported_from_grid" not in entry
    assert "battery_energy_imported_from_solar" not in entry
    assert "consumer_energy_imported_from_grid" not in entry
    assert "consumer_energy_imported_from_solar" not in entry
    assert "consumer_energy_imported_from_battery" not in entry
    assert "grid_energy_exported_from_solar" not in entry
    assert "grid_energy_exported_from_battery" not in entry


def test_current_calendar_entry_does_not_invent_solar_or_battery_export_splits():
    namespace = _calendar_namespace()
    namespace["_find_calendar_statistic_entity_ids"] = lambda hass, entry_id: {}
    hass = SimpleNamespace(states=_States({}))
    coordinator = SimpleNamespace(
        data={
            "energy_summary": {
                "pv_today_kwh": 10.27,
                "discharge_today_kwh": 46.5,
                "charge_today_kwh": 52.1,
                "grid_import_today_kwh": 0,
                "grid_export_today_kwh": 33.73,
                "load_today_kwh": 0,
            }
        }
    )

    entry = namespace["_calendar_current_entry"](hass, coordinator, "entry-1")

    assert entry["solar_generation"] == 10270
    assert entry["grid_export"] == 33730
    assert entry["solar_energy_exported"] == 10270
    assert entry["grid_energy_exported"] == 33730
    assert "grid_energy_exported_from_solar" not in entry
    assert "grid_energy_exported_from_battery" not in entry


def test_energy_summary_period_costs_ignore_daily_recorder_reset_artifacts():
    namespace = _calendar_namespace()

    async def fake_statistics(
        *_args: Any,
        **_kwargs: Any,
    ) -> tuple[list[dict[str, Any]], str]:
        return ([
            {
                "timestamp": "2026-07-01T00:00:00+10:00",
                "grid_import": 100_000,
                "grid_export": 20_000,
                "home_consumption": 90_000,
                "solar_generation": 10_000,
                "battery_discharge": 5_000,
                "battery_charge": 6_000,
            },
            {
                "timestamp": "2026-07-02T00:00:00+10:00",
                "grid_import": 50_000,
                "grid_export": 5_000,
                "home_consumption": 45_000,
                "solar_generation": 8_000,
                "battery_discharge": 4_000,
                "battery_charge": 3_000,
            },
        ], "long_term_statistics")

    async def reset_skewed_costs(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {
            "import_cost": 1.62,
            "export_earnings": 0.88,
            "net_cost": 0.74,
            "estimated": False,
        }

    namespace["_calendar_time_series_from_statistics"] = fake_statistics
    namespace["_calculate_cost_from_statistics"] = reset_skewed_costs

    tariff_schedule = {
        "buy_rates": {"ALL": 0.40},
        "sell_rates": {"ALL": 0.10},
        "seasons": {},
        "tou_periods": {},
    }

    result = namespace["_calendar_result_from_energy_summary"](
        SimpleNamespace(),
        "month",
        None,
        SimpleNamespace(),
        "entry-1",
        tariff_schedule,
        "Sigenergy",
    )
    result = asyncio.run(result)

    assert result["cost_summary"]["estimated"] is True
    assert result["history_source"] == "long_term_statistics"
    assert result["cost_summary"]["import_cost"] == 60.0
    assert result["cost_summary"]["export_earnings"] == 2.5
    assert result["cost_summary"]["net_cost"] == 57.5


def test_current_week_starting_today_uses_mobile_day_optimizer_costs():
    namespace = _calendar_namespace()
    namespace["dt_util"].now = lambda: datetime(
        2026, 7, 27, 17, 11, tzinfo=timezone(timedelta(hours=10))
    )

    monday_row = {
        "timestamp": "2026-07-27T17:11:00+10:00",
        "grid_import": 46_400,
        "grid_export": 99,
        "home_consumption": 0,
        "solar_generation": 2_300,
        "battery_discharge": 0,
        "battery_charge": 0,
    }

    async def monday_only_statistics(
        *_args: Any, **_kwargs: Any
    ) -> tuple[list[dict[str, Any]], str]:
        return [monday_row], "long_term_statistics"

    cost_periods: list[str] = []

    async def unexpected_recorder_costs(
        _hass: Any, period: str, _end_date: str | None
    ) -> dict[str, Any]:
        cost_periods.append(period)
        raise AssertionError("optimizer cost source should win")

    namespace["_calendar_time_series_from_statistics"] = monday_only_statistics
    namespace["_calculate_cost_from_statistics"] = unexpected_recorder_costs

    tariff_schedule = {
        "buy_rates": {"ALL": 12.93 / 46.4},
        "sell_rates": {"ALL": 0.0},
        "seasons": {},
        "tou_periods": {},
    }
    assert namespace["_calculate_cost_from_tariff"](
        tariff_schedule,
        [monday_row],
        "week",
    )["import_cost"] == 12.93

    optimizer = SimpleNamespace(
        get_api_data=lambda: {
            "daily_cost_breakdown": {
                "actual_import_cost": 8.10,
                "actual_export_earnings": 0.0,
                "actual_cost": 8.10,
            }
        }
    )
    hass = SimpleNamespace(
        data={
            "power_sync": {
                "entry-1": {
                    "optimization_coordinator": optimizer,
                }
            }
        }
    )

    result = namespace["_calendar_result_from_energy_summary"](
        hass,
        "week",
        None,
        SimpleNamespace(),
        "entry-1",
        tariff_schedule,
        "Sigenergy",
    )
    result = asyncio.run(result)

    assert cost_periods == []
    assert result["cost_summary"]["import_cost"] == 8.10
    assert result["cost_summary"]["net_cost"] == 8.10
    assert result["cost_summary"]["estimated"] is True


def test_current_week_future_end_date_does_not_use_today_optimizer_costs():
    namespace = _calendar_namespace()
    namespace["dt_util"].now = lambda: datetime(
        2026, 7, 27, 17, 11, tzinfo=timezone(timedelta(hours=10))
    )

    async def period_statistics(
        *_args: Any, **_kwargs: Any
    ) -> tuple[list[dict[str, Any]], str]:
        return ([
            {
                "timestamp": "2026-07-27T17:11:00+10:00",
                "grid_import": 46_400,
                "grid_export": 0,
                "home_consumption": 0,
                "solar_generation": 0,
                "battery_discharge": 0,
                "battery_charge": 0,
            }
        ], "long_term_statistics")

    namespace["_calendar_time_series_from_statistics"] = period_statistics
    hass = SimpleNamespace(
        data={
            "power_sync": {
                "entry-1": {
                    "optimization_coordinator": SimpleNamespace(
                        get_api_data=lambda: {
                            "daily_cost_breakdown": {
                                "actual_import_cost": 8.10,
                                "actual_export_earnings": 0.0,
                                "actual_cost": 8.10,
                            }
                        }
                    )
                }
            }
        }
    )

    result = namespace["_calendar_result_from_energy_summary"](
        hass,
        "week",
        "2026-07-31",
        SimpleNamespace(),
        "entry-1",
        {
            "buy_rates": {"ALL": 12.93 / 46.4},
            "sell_rates": {"ALL": 0.0},
            "seasons": {},
            "tou_periods": {},
        },
        "Sigenergy",
    )
    result = asyncio.run(result)

    assert result["cost_summary"]["import_cost"] == 12.93
    assert result["cost_summary"]["estimated"] is True


def test_sigenergy_dynamic_display_tariff_is_available_for_calendar_costs():
    namespace = _calendar_namespace()
    tariff_schedule = {
        "buy_prices": {"PERIOD_00_00": 0.40},
        "sell_prices": {"PERIOD_00_00": 0.10},
    }
    hass = SimpleNamespace(
        data={
            "power_sync": {
                "entry-1": {
                    "tariff_schedule": tariff_schedule,
                }
            }
        }
    )

    assert namespace["_find_calendar_tariff_schedule"](hass) is tariff_schedule


def test_sigenergy_dynamic_display_tariff_prices_period_energy_rows():
    namespace = _calendar_namespace()
    buy_prices = {
        f"PERIOD_{hour:02d}_{minute:02d}": 0.40
        for hour in range(24)
        for minute in (0, 30)
    }
    sell_prices = {period: 0.10 for period in buy_prices}
    time_series = [
        {
            "timestamp": "2026-07-01T00:00:00+10:00",
            "grid_import": 100_000,
            "grid_export": 20_000,
        },
        {
            "timestamp": "2026-07-02T00:00:00+10:00",
            "grid_import": 50_000,
            "grid_export": 5_000,
        },
    ]

    result = namespace["_calculate_cost_from_tariff"](
        {
            "buy_prices": buy_prices,
            "sell_prices": sell_prices,
        },
        time_series,
    )

    assert result is not None
    assert result["import_cost"] == 60.0
    assert result["export_earnings"] == 2.5
    assert result["net_cost"] == 57.5


def test_month_with_more_than_seven_daily_rows_uses_daily_average_rates():
    namespace = _calendar_namespace()
    time_series = [
        {
            "timestamp": f"2026-07-{day:02d}T00:00:00+10:00",
            "grid_import": 100_000,
            "grid_export": 0,
        }
        for day in range(1, 11)
    ]
    tariff_schedule = {
        "buy_rates": {
            "CHEAP": 0.01,
            "STANDARD": 0.41,
        },
        "sell_rates": {"ALL": 0},
        "seasons": {},
        "tou_periods": {
            "CHEAP": {
                "periods": [
                    {
                        "fromHour": 0,
                        "toHour": 1,
                        "fromDayOfWeek": 0,
                        "toDayOfWeek": 6,
                    }
                ]
            },
            "STANDARD": {
                "periods": [
                    {
                        "fromHour": 1,
                        "toHour": 24,
                        "fromDayOfWeek": 0,
                        "toDayOfWeek": 6,
                    }
                ]
            },
        },
    }

    result = namespace["_calculate_cost_from_tariff"](tariff_schedule, time_series)

    assert result is not None
    assert result["import_cost"] == 393.33


def test_weighted_average_rates_include_half_hour_boundaries():
    namespace = _calendar_namespace()
    tou_periods = {
        "FIRST_HALF": {
            "periods": [
                {
                    "fromHour": 0,
                    "fromMinute": 0,
                    "toHour": 0,
                    "toMinute": 30,
                    "fromDayOfWeek": 0,
                    "toDayOfWeek": 6,
                }
            ]
        },
        "SECOND_HALF": {
            "periods": [
                {
                    "fromHour": 0,
                    "fromMinute": 30,
                    "toHour": 1,
                    "toMinute": 0,
                    "fromDayOfWeek": 0,
                    "toDayOfWeek": 6,
                }
            ]
        },
    }

    avg_buy, avg_sell = namespace["_weighted_avg_rates"](
        tou_periods,
        {"FIRST_HALF": 0.10, "SECOND_HALF": 0.30},
        {"FIRST_HALF": 0.02, "SECOND_HALF": 0.06},
    )

    assert avg_buy == 0.20
    assert avg_sell == 0.04


def test_dynamic_tariff_builds_final_half_hour_through_midnight():
    namespace = _calendar_namespace()

    tou_periods = namespace["_calendar_tou_periods_from_price_keys"](
        {"PERIOD_23_30": 0.40}
    )

    assert tou_periods["PERIOD_23_30"]["periods"] == [
        {
            "fromHour": 23,
            "fromMinute": 30,
            "toHour": 24,
            "toMinute": 0,
            "fromDayOfWeek": 0,
            "toDayOfWeek": 6,
        }
    ]


def test_subdaily_hour_averages_both_half_hour_tariff_rates():
    namespace = _calendar_namespace()
    namespace["_match_tou_period"] = (
        lambda _tou, hour, _dow, *, minute=0, **_kwargs:
        f"PERIOD_{hour:02d}_{minute:02d}"
    )
    time_series = [
        {
            "timestamp": "2026-07-10T22:00:00+10:00",
            "grid_import": 0,
            "grid_export": 0,
        },
        {
            "timestamp": "2026-07-10T23:00:00+10:00",
            "grid_import": 100_000,
            "grid_export": 20_000,
        },
    ]
    tariff_schedule = {
        "buy_prices": {
            "PERIOD_22_00": 0.10,
            "PERIOD_22_30": 0.10,
            "PERIOD_23_00": 0.20,
            "PERIOD_23_30": 0.40,
        },
        "sell_prices": {
            "PERIOD_22_00": 0.02,
            "PERIOD_22_30": 0.02,
            "PERIOD_23_00": 0.06,
            "PERIOD_23_30": 0.10,
        },
    }

    result = namespace["_calculate_cost_from_tariff"](
        tariff_schedule,
        time_series,
        "day",
    )

    assert result is not None
    assert result["import_cost"] == 30.0
    assert result["export_earnings"] == 1.6
    assert result["net_cost"] == 28.4
