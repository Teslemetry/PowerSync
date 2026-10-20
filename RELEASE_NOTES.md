<!-- release: v2.12.1434 -->

## What's Changed

**Restore Powerwall gateway details**
Powerwall Local’s v1r Device and v1r Firmware sensors could remain unavailable on newer gateways even while live power readings worked. PowerSync now supports both older and newer gateway identity responses, and missing diagnostic responses are reported instead of being silently omitted.

Update through HACS and restart Home Assistant to apply the fix.

Update available via HACS
