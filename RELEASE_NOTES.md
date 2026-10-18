<!-- release: v2.12.1422 -->

### Fronius self-consumption recovery

Fronius GEN24 restore failures are no longer reported as a successful self-consumption transition. The optimizer keeps the action retryable, and a failed manual Self-Use request does not leave its success toggle enabled.

Update available via HACS.
