<!-- release: v2.12.1436 -->

## What's Changed

**Amber current prices in tariff sync**
PowerSync now accepts valid current Amber price intervals of 5, 15 or 30 minutes, avoiding an unnecessary fallback to forecast prices. Expired intervals are still rejected.

**Tesla and Teslemetry tariff upload retries**
Tariff sync, force actions and restore uploads to the same site now share the provider's rate-limit cooldown. Overlapping uploads are deferred; a force request may need a later retry, and other API clients can still cause rate limiting.

Update available via HACS
