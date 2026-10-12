<!-- release: v2.12.1378 -->

## What's Changed

**Prevent stale Tesla restore retries from undoing newer commands**

Fixed a Tesla Powerwall control race where a failed restore could leave a retry
queued after a newer force-charge or force-discharge command had started. The
queued callback now carries the command generation it belongs to and skips
stale work; the restore service also rejects that generation if dispatch is
delayed. Valid same-generation retries, manual restores, retry limits, and
restart-persisted unfinished restores retain their existing behavior.

Regression coverage reproduces the already-queued callback variant and checks
the surrounding Tesla restore, baseline, and readback lifecycle. The affected
test surfaces pass 217 tests. This release does not claim installation or live
hardware verification on any reporter system.

Update available via HACS
