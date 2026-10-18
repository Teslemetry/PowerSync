<!-- release: v2.12.1424 -->

## What's Changed

**Fronius GEN24 solar curtailment**
PowerSync now uses the inverter’s native Export soft limit when the Fronius Modbus companion integration exposes that control for the configured solar inverter. This addresses setups where the AC output-limit setting is accepted but export continues; the previous export limit is saved and restored, including after a reload or restart.

The companion integration must already have a working Export soft limit control with local technician access. Keep separate export-limit automations disabled while PowerSync controls curtailment; physical status remains pending until fresh site readings confirm export has fallen.

Update available via HACS
