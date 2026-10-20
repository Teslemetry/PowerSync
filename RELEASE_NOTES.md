<!-- release: v2.12.1433 -->

## What's Changed

**Restore Powerwall Local grid status**
Powerwall Local could show Unknown for grid status and the On-Grid/Off-Grid controls despite receiving healthy gateway readings. PowerSync now uses the actual grid connection readings, so a gateway’s backup policy is no longer mistaken for its connection state; incomplete or unhealthy readings still show Unknown.

Update through HACS and restart Home Assistant to apply the fix.

Update available via HACS
