<!-- release: v2.12.1397 -->

## What's Changed

**Zaptec price-level charging now cancels pending authorization safely**
When PowerSync has armed a Zaptec charger but the vehicle is still waiting for authorization, a price or home-battery guard rejection now cancels that charger session with the charger-scoped deauthorize-and-stop command. PowerSync keeps the pending session attributed and waits for fresh Zaptec telemetry before updating charging and home-battery-preservation status; installation-wide current limits are not used as a per-charger stop.

Update available via HACS
