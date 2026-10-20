<!-- release: v2.12.1437 -->

## What's Changed

**Powerwall restore retries during rate limiting**
PowerSync now waits for a known Tesla or Teslemetry tariff cooldown before retrying a pending restore, so cleanup does not give up before uploads are allowed again. This completes the Amber current-price and shared tariff-cooldown fixes in v2.12.1436.

Update available via HACS
