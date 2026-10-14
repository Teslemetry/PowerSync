<!-- release: v2.12.1401 -->

## What's Changed

**Retry FoxESS self-consumption restoration after an unconfirmed control change**
PowerSync now treats a FoxESS self-consumption restore as failed when the inverter cannot be reached or does not confirm the restore. The optimizer keeps the prior action marker so the next cycle retries, avoiding a stale self-consumption status while a previous remote-control command may still be active. Existing curtailment ownership remains unchanged.

Update available via HACS
