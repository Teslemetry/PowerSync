<!-- release: v2.12.1375 -->

## What's Changed

**Keep Fronius physical status pending until convergence**
PowerSync now keeps Fronius load-following and curtailment status pending when a device-limit acknowledgement exists but fresh site telemetry has not proved physical convergence, including unknown and failed convergence results. HA status and descriptions no longer present an acknowledged write as successful physical curtailment.

**Align mobile inverter status with HA status**
The mobile inverter-status API now applies the same physical-convergence overlay to both its cached status-sensor route and controller fallback route, while preserving offline and error states. Control commands, register handling, and native inverter settings are unchanged.

Update available via HACS
