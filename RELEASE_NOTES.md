<!-- release: v2.12.1414 -->

## What's Changed

**Shared non-Tesla EV profiles use the selected loadpoint configuration**

Generic, OCPP, Sigenergy and Zaptec charging paths now resolve the explicitly selected EV profile before applying charger limits and external-session decisions. Ambiguous shared chargers fail closed instead of inheriting the first stored vehicle profile, while legacy single-profile installations retain their existing fallback behavior.

**External-session policy is honored across charging modes**

Under `external_control_policy: override`, Smart Schedule, Scheduled Charging and Price-Level now distinguish `adopt`, `abort` and `leave_alone` for fresh externally started non-Tesla sessions. Adoption follows the mode’s normal controller, abort uses the existing guarded stop path, and leave-alone does not claim ownership. Yield remains hands-off, and stale or missing charger evidence remains command-free.

Update available via HACS
