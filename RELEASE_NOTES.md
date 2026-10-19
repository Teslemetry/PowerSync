<!-- release: v2.12.1430 -->

## What's Changed

**More reliable Enphase Envoy Installer curtailment**
PowerSync now waits for delayed DPEL confirmation from Home Assistant before continuing a curtailment or restore. This fixes changes being reported as failed before the Envoy integration refreshed its state; communication failures and conflicting control changes still stop the operation.

Update available via HACS
