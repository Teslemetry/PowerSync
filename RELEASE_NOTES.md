<!-- release: v2.12.1374 -->

## What's Changed

**Restore SolarEdge curtailment and release commands**

Fixed a PowerSync coordinator interface mismatch that raised `run_external_mutation() got an unexpected keyword argument 'determinate'` before a SolarEdge active-power write could start. Automatic curtailment during negative export prices and restoration when prices recover now reach the existing controller.

The coordinator now forwards the controller's write-determinacy check while retaining readiness checks, mutation locking, permission checks, and reconciliation for uncertain writes. Regression coverage exercises both curtailment and restoration through the runtime handler and coordinator, including successful writes, definite rejection, uncertain failure, and denied permissions.

Update available via HACS
