<!-- release: v2.12.1382 -->

## What's Changed

**Keep signed Amber export rates through battery-export eligibility**
PowerSync now evaluates Amber's signed, unboosted feed-in rate before applying Export Boost. A negative rate remains visible in the plan while being excluded from intentional battery EXPORT, instead of being clamped to zero and incorrectly passing a zero-cent boost threshold.

**Fail closed for stale negative-price optimizer exports**
The execution boundary now rechecks a cached action against the signed settlement rate when it is available, while retaining contractual bonus handling and leaving manual ownership, native solar export, and Monitoring Mode boundaries unchanged.

Update available via HACS
