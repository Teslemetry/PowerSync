<!-- release: v2.12.1431 -->

## What's Changed

**Native Amber Smart Shift battery controls**
Connect your Smart Shift battery directly in PowerSync using your Amber email and password. Choose “Amber Smart Shift — native cloud battery control” during battery setup for manual charge, export, preserve and self-consumption controls, or optional control through PowerSync's optimiser and automations.

**Choose who manages your battery**
New connections leave normal battery management with Amber until you enable PowerSync management. PowerSync asks for separate permission to enable Smart Shift when an override needs it, and preserves overrides created in the Amber app.

**Clearer Amber status and timed overrides**
Native sensors and dashboard controls show Amber's reported override, control owner and expiry separately from the charging plan. Automatic overrides expire after at most ten minutes unless renewed by a fresh, eligible plan; expiry returns control to Amber even if Home Assistant is offline.

**Control requirements and limits**
Automatic operation requires fresh grid, solar and home-load sensors, and the Amber battery must match your configured Amber pricing site. This connection controls battery modes rather than target watts, hardware reserves or solar production; an accepted override is not proof of physical charging or export.

Update available via HACS
