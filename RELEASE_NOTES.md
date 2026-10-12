<!-- release: v2.12.1379 -->

## What's Changed

**Preserve configured battery specifications after reload**

Fixed battery-capacity and charge/discharge-power settings being reported as
defaults after the optimizer restarted or reloaded its configuration. The
settings reader now uses the canonical persisted keys written by the Home
Assistant and mobile settings paths, while retaining options-over-legacy-data
precedence and existing reset behavior.

Added regression coverage for the reported 9.7 kWh / 5 kW / 5 kW configuration,
partial settings, legacy-data fallback, and nonpositive reset values. This
release does not claim installation or live hardware verification on any
reporter system.

Update available via HACS
