<!-- release: v2.12.1385 -->

## What's Changed

**Preserve solar during manual Sigenergy Force Discharge**
Manual Force Discharge now uses the same solar priority as optimizer export:
PV-first whenever live DC or third-party AC solar is present, and ESS-first
only when live solar is known to be zero.

Previously, manual control selected ESS-first when solar was below 80% of the
grid-export ceiling. For example, 1.72 kW of solar with a 5 kW ceiling selected
ESS-first despite available generation. That case now selects PV-first.
The configured export ceiling, ESS discharge limits, reserve protections,
timed control lifecycle, and failed-command rollback remain in place.

**Regression coverage and documentation**
Controller regressions cover the reported manual command, DC-only,
third-party AC-only and mixed solar, plus discharge headroom in both modes.
The Services Reference documents the shared solar priority. PV-first does not
guarantee a particular battery discharge rate; physical solar response still
requires verification on the inverter.

Update available via HACS
