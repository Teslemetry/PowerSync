"""Opt-in Amber export-spike valuation; never changes billable tariff prices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Sequence


# Deliberately conservative heuristics, not calibrated event probabilities.
SPIKE_PREMIUM_HALF_LIFE_HOURS = 1.5
ORDINARY_SAMPLE_CEILING = 1.0  # $/kWh; exclude extreme prices from the baseline.
ORDINARY_PRICE_BUFFER = 0.10  # $/kWh above the ordinary median.


@dataclass(frozen=True)
class AmberPriceInterval:
    """Original provider coverage, before expansion or gap filling."""

    start_slot: int
    end_slot: int
    start: datetime | None
    interval_type: str | None
    is_spike: bool = False


def weight_amber_export_forecast(
    slots: Sequence[float | None],
    intervals: Sequence[AmberPriceInterval],
    now: datetime,
) -> tuple[list[float | None], dict]:
    """Discount future spike premiums once per source interval.

    Ordinary, non-positive and active prices are unchanged. Missing coverage
    remains None so the caller can fill gaps from the adjusted source series.
    No timestamp is invented for legacy data. An unusable baseline or missing
    future metadata asks the caller to retain its legacy export decay.
    """
    result = list(slots)
    diagnostics = {
        "used": False,
        "reason": "missing_forecast_metadata",
        "weighting": "lead_time_heuristic",
        "half_life_hours": SPIKE_PREMIUM_HALF_LIFE_HOURS,
        "policy_version": 1,
        "ordinary_sample_ceiling_per_kwh": ORDINARY_SAMPLE_CEILING,
        "adjusted_intervals": 0,
    }
    if now.tzinfo is None:
        return result, diagnostics

    owners: list[AmberPriceInterval | None] = [None] * len(slots)
    for interval in intervals:
        if not (0 <= interval.start_slot < interval.end_slot <= len(slots)):
            continue
        owners[interval.start_slot:interval.end_slot] = [interval] * (
            interval.end_slot - interval.start_slot
        )
    sources = []
    for interval in dict.fromkeys(intervals):
        covered = [pos for pos, owner in enumerate(owners) if owner == interval]
        if not covered:
            continue
        price = slots[covered[0]]
        if price is None or not math.isfinite(price):
            continue
        if interval.start is None or interval.start.tzinfo is None or interval.interval_type not in (
            "ActualInterval", "CurrentInterval", "ForecastInterval",
        ):
            return result, diagnostics
        sources.append((interval, price, covered))

    future = [
        (interval, price, covered)
        for interval, price, covered in sources
        if interval.interval_type == "ForecastInterval"
        and interval.start is not None
        and interval.start.tzinfo is not None
        and interval.start.astimezone(timezone.utc) > now.astimezone(timezone.utc)
    ]
    if not future:
        return result, diagnostics
    ordinary = [
        (price, len(covered)) for interval, price, covered in sources
        if not interval.is_spike and 0 <= price <= ORDINARY_SAMPLE_CEILING
        and (interval.start.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds() <= 24 * 3600
    ]
    if len(ordinary) < 2:
        diagnostics["reason"] = "missing_ordinary_price_baseline"
        return result, diagnostics

    def weighted_median(values: Sequence[tuple[float, int]]) -> float:
        midpoint = sum(duration for _, duration in values) / 2
        cumulative = 0
        for value, duration in sorted(values):
            cumulative += duration
            if cumulative >= midpoint:
                return value
        return values[-1][0]

    center = weighted_median(ordinary)
    deviation = weighted_median([(abs(price - center), duration) for price, duration in ordinary])
    # Discount only the premium ABOVE the ordinary band. This is continuous
    # at the band edge, unlike discounting an entire price above a hard cutoff.
    baseline = min(ORDINARY_SAMPLE_CEILING, center + max(ORDINARY_PRICE_BUFFER, 3 * deviation))
    diagnostics.update(used=True, reason="weighted", baseline_per_kwh=baseline)
    for interval, price, covered in future:
        if price <= baseline:
            continue
        lead_hours = (
            interval.start.astimezone(timezone.utc) - now.astimezone(timezone.utc)
        ).total_seconds() / 3600
        weight = 2 ** (-lead_hours / SPIKE_PREMIUM_HALF_LIFE_HOURS)
        adjusted = baseline + (price - baseline) * weight
        # Preserve any overlapping, higher-priority source value in the slot.
        for pos in covered:
            if slots[pos] == price:
                result[pos] = adjusted
        diagnostics["adjusted_intervals"] += 1
    return result, diagnostics
