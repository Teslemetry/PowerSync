<!-- release: v2.12.1381 -->

## What's Changed

**Prevent Monitoring Mode from replaying Profit Max solar-export hold writes**
PowerSync now defers persisted hold startup cleanup and disable/action cleanup while Monitoring Mode is active, and drains a held export limit only on an explicit transition into Monitoring Mode. This keeps monitoring ownership write-free after the handoff.

**Require authoritative Sungrow charge-limit state for reversible export holds**
Sungrow solar-export holds now require configured charge-power telemetry and retain explicit write-health failures. BMS-current fallback or rejected limit writes fail closed instead of advertising reversible hold support.

Update available via HACS
