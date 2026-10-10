<!-- release: v2.12.1372 -->

## What's Changed

**Solar Only plans only the solar budget that is actually available**
Solar Only Smart Schedule plans no longer convert unused site grid capacity into forecast solar. Battery charging and other-EV reservations remain within the shared solar budget, and the plan reports truthful power, energy, and deadline feasibility.

**Smart Schedule recovers after dynamic controller cleanup**
When a dynamic EV controller is released independently of Smart Schedule, the executor now reconciles the stale charging flag, restores any Solar Surplus curtailment override, and can rearm an eligible vehicle without treating the cached status as physical charging proof.

Update available via HACS
