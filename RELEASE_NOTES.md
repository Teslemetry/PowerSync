<!-- release: v2.12.1412 -->

## What's Changed

**Manual self-consumption status survives a cleared optimizer plan**

PowerSync now keeps an accepted manual self-consumption takeover as the current and effective action when the optimizer has no cached plan or an empty plan. The planned action remains separate, so the status cannot fall back to `idle` solely because the plan was cleared.

Update available via HACS
