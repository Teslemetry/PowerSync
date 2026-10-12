"""Source-interval policy tests, independent of HA and hardware."""

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest


PATH = Path(__file__).resolve().parents[1] / "custom_components/power_sync/optimization/price_forecast_confidence.py"
spec = importlib.util.spec_from_file_location("amber_confidence_policy", PATH)
policy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = policy
spec.loader.exec_module(policy)
NOW = datetime(2026, 10, 12, 7, 0, tzinfo=timezone.utc)


def interval(start, end, hours, kind="ForecastInterval", spike=False):
    return policy.AmberPriceInterval(start, end, NOW + timedelta(hours=hours), kind, spike)


def test_spike_premium_decays_and_original_interval_slices_stay_identical():
    raw = [10.0] + [0.05] * 2 + [24.0] * 6
    records = [interval(0, 1, 0, "CurrentInterval"), interval(1, 2, 0.5), interval(2, 3, 1), interval(3, 9, 2)]
    adjusted, diagnostics = policy.weight_amber_export_forecast(raw, records, NOW)
    assert raw == [10.0] + [0.05] * 2 + [24.0] * 6
    assert adjusted[:3] == raw[:3]
    assert len(set(adjusted[3:])) == 1
    assert 0.15 < adjusted[3] < 10.0
    assert diagnostics["used"] is True
    assert diagnostics["adjusted_intervals"] == 1


@pytest.mark.parametrize("kind,hours", [("CurrentInterval", 2), ("ActualInterval", 2), ("ForecastInterval", -0.1), ("ForecastInterval", 0)])
def test_current_actual_and_containing_intervals_are_exactly_preserved(kind, hours):
    raw = [24.0, 0.05, 0.05, 24.0]
    records = [interval(0, 1, hours, kind), interval(1, 2, 0.5), interval(2, 3, 1), interval(3, 4, 2)]
    result, _ = policy.weight_amber_export_forecast(raw, records, NOW)
    assert result[0] == 24.0


@pytest.mark.parametrize("price", [-2.0, 0.0, 0.05, 0.10, 0.15])
def test_non_positive_and_ordinary_prices_are_exactly_preserved(price):
    raw = [0.05, 0.05, price]
    result, _ = policy.weight_amber_export_forecast(raw, [interval(0, 1, 0), interval(1, 2, 1), interval(2, 3, 2)], NOW)
    assert result == raw


def test_band_edge_is_continuous_and_sustained_ordinary_prices_are_retained():
    records = [interval(0, 1, 0), interval(1, 2, 1), interval(2, 3, 2)]
    result, info = policy.weight_amber_export_forecast([0.05, 0.05, 0.150001], records, NOW)
    assert info["baseline_per_kwh"] == pytest.approx(0.15)
    assert 0.15 < result[2] < 0.150001
    result, _ = policy.weight_amber_export_forecast([0.8, 0.8, 0.8], records, NOW)
    assert result == [0.8, 0.8, 0.8]


def test_timezone_offsets_are_elapsed_time_equivalent():
    records = [interval(0, 1, 0), interval(1, 2, 1), interval(2, 3, 2)]
    raw = [0.05, 0.05, 24.0]
    utc, _ = policy.weight_amber_export_forecast(raw, records, NOW)
    offset = timezone(timedelta(hours=10))
    other = [policy.AmberPriceInterval(r.start_slot, r.end_slot, r.start.astimezone(offset), r.interval_type) for r in records]
    converted, _ = policy.weight_amber_export_forecast(raw, other, NOW.astimezone(offset))
    assert converted == utc


def test_missing_metadata_degrades_whole_series_and_preserves_gap_markers():
    raw = [0.05, None, 0.05, 24.0]
    records = [interval(0, 1, 0), interval(2, 3, 1), policy.AmberPriceInterval(3, 4, None, "ForecastInterval")]
    result, info = policy.weight_amber_export_forecast(raw, records, NOW)
    assert result == raw
    assert info["used"] is False


def test_baseline_excludes_extreme_spikes_padding_and_duplicate_records():
    raw = [0.05, 0.05, 24.0, None]
    records = [interval(0, 1, 0), interval(1, 2, 1), interval(2, 3, 2)]
    result, info = policy.weight_amber_export_forecast(raw, records + records, NOW)
    assert info["baseline_per_kwh"] == pytest.approx(0.15)
    assert info["adjusted_intervals"] == 1
    assert result[-1] is None


def test_no_ordinary_baseline_retains_legacy_policy():
    raw = [10.0, 24.0]
    result, info = policy.weight_amber_export_forecast(raw, [interval(0, 1, 0), interval(1, 2, 2)], NOW)
    assert result == raw
    assert info["reason"] == "missing_ordinary_price_baseline"


def test_overlapping_current_interval_is_not_discounted_by_earlier_forecast():
    raw = [0.05, 0.05, 24.0]
    records = [interval(0, 1, 0), interval(1, 2, 1), interval(2, 3, 2), interval(2, 3, 0, "CurrentInterval")]
    result, _ = policy.weight_amber_export_forecast(raw, records, NOW)
    assert result == raw
