<!-- release: v2.12.1384 -->

## What's Changed

**Restore historical calendar energy from Home Assistant statistics**
PowerSync now accepts Home Assistant recorder statistics whose `start` value is
the supported numeric Unix-second form as well as an existing datetime. Valid
historical daily-energy rows are no longer silently discarded, so calendar
day/week/month/year views can use the long-term statistics that Home Assistant
has recorded for PowerSync sensors.

Malformed, non-finite, boolean, and out-of-range timestamps remain ignored on a
row-by-row basis. Current-day live totals, timezone conversion, entity
selection, and the bounded raw-history fallback are unchanged.

**Regression coverage**
The calendar-history tests cover numeric and datetime starts, invalid timestamp
values, and a historical month response that converts a 12.5 kWh statistic to
12,500 Wh.

Update available via HACS
