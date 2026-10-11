<!-- release: v2.12.1377 -->

## What's Changed

**Restore Home Assistant device registration on supported legacy releases**
PowerSync now selects the installed Home Assistant device-registry child-link field at runtime: resolved `via_device_id` where available and legacy `via_device` identifier links for older supported releases. This prevents Powerwall, provider-pricing, and battery-block entities from failing registration with an unexpected-keyword error while preserving their parent hierarchy.

Update available via HACS
