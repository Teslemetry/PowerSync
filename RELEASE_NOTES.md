<!-- release: v2.12.1399 -->

## What's Changed

**Correct Amber live-price attribution in the TOU schedule**
PowerSync now uses the refreshed Amber current interval for the active TOU period and ignores expired cached five-minute data at a period boundary. This keeps the displayed buy and feed-in prices aligned with the live interval without changing optimizer pricing or hardware-control behavior.

Update available via HACS
