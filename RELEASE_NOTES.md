<!-- release: v2.12.1442 -->

## What's Changed

**Powerwall tariff retries follow the latest command**
PowerSync now discards a waiting tariff upload when a newer force or restore command replaces it. This prevents an old retry from overwriting the newer command after a Tesla or Teslemetry rate-limit wait.

Force-charge and force-discharge uploads also stop when their tariff window expires, including when the upload finishes after expiry. Cleanup restores the prior settings instead of activating an expired session. Provider rate limits still apply; no configuration change is required.

Update available via HACS
