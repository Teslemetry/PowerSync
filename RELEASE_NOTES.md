<!-- release: v2.12.1408 -->

## What's Changed

- EV cards now present the Smart Schedule solar owner as **Smart Schedule (solar)** while leaving the internal ownership value and arbitration unchanged.
- The selected EV card now shows an active or next Smart Schedule window in local time, including its source. Clear no-plan, stale-plan, and unavailable-data states make this advisory information distinct from charger-command acknowledgement; measured charger status remains authoritative.
- Optimizer charts now retain aggregate planned EV load and show deterministic, per-EV planned-demand lines only when every series aligns with the current timestamp grid and plan snapshot. Malformed or stale series are omitted rather than shifted or assigned to another vehicle.
- Added regressions for exact selected-EV matching, local/DST-safe window snapshots, owner-label preservation, aligned EV chart series, and finalized plan fingerprinting.

Update available via HACS.
