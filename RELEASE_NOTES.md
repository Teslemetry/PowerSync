<!-- release: v2.12.1406 -->

## What's Changed

- Shared Generic, OCPP, Sigenergy, and Zaptec chargers can now have multiple vehicle profiles. Select the currently connected EV with `power_sync.set_connected_ev`; PowerSync keeps charger ownership and command suppression on the physical loadpoint.
- A shared charger with no selected EV is safely left under manual control. Existing single-profile charger configurations retain their previous behavior.
- Vehicle profiles can declare an external-session action (`adopt`, `abort`, or `leave_alone`) for supported charging modes while external control is set to override. Yield remains hands-off.

Update available via HACS
