<!-- release: v2.12.1389 -->

## What's Changed

**Prevent stale Generic charger cleanup from stopping a superseding owner**
When a Generic charger start is still waiting for cloud readback, timeout or cancellation cleanup now verifies that the original request and PowerSync ownership are still current. A manual handoff or newer request remains command-neutral, while ordinary cancellation still performs the existing compensating stop.

This release does not change the 60-second confirmation timeout or add automatic adoption of late external charging; those remain separate, owner-approved feature decisions.

Update available via HACS
