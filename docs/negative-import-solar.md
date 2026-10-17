# Stop solar during negative import prices

Unreleased implementation for Home Assistant feature request #434. The policy is
**off by default**. It stops PV generation when the customer's current retail
import price is below zero, allowing existing household loads and permitted
battery charging to use paid grid imports. Zero export is a different operation:
it can leave solar supplying the house and battery.

Enable **Stop solar when the import price is negative** in PowerSync's
**Curtailment settings**. Existing battery dispatch, grid charging permissions,
SOC limits, electrical limits and EV settings continue to determine consumption.
The feature does not create extra loads or override those limits. Choosing to
stop solar can forgo export income; this is an explicit import-price policy,
not a calculation that selling solar is always less valuable.

## Controls and inverter coverage

Explicitly selected Home Assistant **PV production controls** work for any brand
whose integration exposes a suitable control. Multiple controls can cover
multiple inverters. A switch must mean **on = PV enabled, off = PV stopped**;
a number must limit **PV generation**, accept zero, and have readable limits.
Do not select an export limit, grid/islanding switch, battery dispatch setting,
whole-hybrid shutdown switch, or a general load relay.

With no production entities selected, the following native controls are used:

| Adapter | Production operation | Conditions and restore |
| --- | --- | --- |
| Enphase | DPEL with `enable=true`, `export_limit=false`, `limit_value_W=0`, dynamic limiting enabled | Requires readable modern DPEL settings and write access. Refreshes every 15 seconds. Restores the captured control fields, preserving fresh installer metadata. No DER, profile, opposite-export-flag or disabled-limiting fallback. |
| Fronius | SunSpec active output limit at 0% | Separate PV inverter only. Saves enable, limit and reversion settings; does not introduce a reversion-to-100% timeout that could overwrite a prior cap. Fronius GEN24 storage entries require an independently verified PV-only entity instead. |
| Sungrow SG | Run-mode register `5005=206` | Explicitly known standalone SG model and readable run-mode baseline required. Restores the saved run mode; never stops an SH hybrid or changes its battery settings. |
| SolarEdge | Active-power limit at 0% | Separate PV topology; duplicate battery endpoint remains blocked. Restores the previous percentage, including non-default limits. |
| Zeversolar | Percentage production limit at 0% | Reads the actual advanced settings, saves enabled/mode/limit fields and restores them exactly. |
| Sigenergy | PV maximum-power limit `40036`, unsigned 32-bit zero | DC PV only. Remote EMS must already be enabled in a mode where that register is effective (3–6). Never changes EMS mode, battery dispatch, grid export limits or third-party AC solar. Restores the original PV register even after the EMS mode changes. |
| FoxESS, Huawei, GoodWe, GoodWe entity bridge, SolaX, AlphaESS | Explicit PV production entities | Their existing PowerSync curtailment adapters control export/dispatch, not an established independent PV-only stop. They are not silently promoted to production controls. |
| Other brands | Explicit PV production entities | Requires a documented PV-only control exposed by the installed integration. A device without such a surface cannot be stopped by software through this feature. |

Reading back a zero limit confirms a setting, not a physical effect. The new
**Solar Production Control** sensor reports **Stop Pending** until a fresh
controlled-PV power observation demonstrates a transition from producing over
100 W to at most 100 W. Without a suitable power sensor, or when solar was already
zero at night, physical confirmation remains unknown. Command attempted,
acknowledgement, device readback and physical convergence are separate attributes.
`restore_required` identifies an outstanding ownership record;
`restore_pending` identifies recovery currently awaiting completion.

## Price validity and recovery

A fresh utility-grid connection is required before stopping PV. Tesla uses its
own current grid status. Other systems select **Grid connected sensor**: a
binary sensor whose `on` state means utility-connected, or a sensor reporting
`Active`, `Connected`, `SystemGridConnected` or `On-Grid`. Observations older
than 90 seconds are rejected. A lost/unknown grid connection withdraws the stop
and restores owned PV settings; it never suppresses backup solar from an old
negative-price quote. Only an off-grid fallback session owned by PowerSync can
be reconnected for this policy; a manual islanding state is not taken over.

Amber, Localvolts, Octopus and EPEX use finite, timestamped **current retail import
intervals**. Feed-in prices are unnecessary for this policy. Forecast intervals,
expired intervals, failed coordinator updates, NaN/infinity and raw AEMO/KWatch
wholesale observations cannot authorize a new stop.

Other providers can supply the optional **Retail import price sensor** with
`startTime`/`endTime` or `valid_from`/`valid_to` timezone-aware attributes. Supported
units are `c/kWh`, `¢/kWh`, `p/kWh`, `$/kWh`, `AUD/kWh`, `EUR/kWh`, `GBP/kWh`,
`€/kWh`, and `£/kWh`. Currency-per-kWh values are converted to minor units.
The value must be the customer's retail buy rate. An old scalar tariff or a
sensor's change timestamp is not a current tariff interval.

At zero or a positive price, missing/expired price, disabled policy, changed
controls or unload, PowerSync restores only the settings it still owns. The
baseline is saved durably before the first write and retained after lost replies,
partial writes and failed restores. Persistent device stops can remain in place while Home Assistant is offline; recovery needs Home Assistant and device connectivity. Restart loads that obligation before legacy
AC controls can write. Failed commands use bounded exponential retry intervals.
External changes are preserved and suspend this policy for the negative-price
window. Manual inverter services restore the owned production settings first
and suspend automatic stopping until a nonnegative price is observed.

Monitoring Mode blocks commands unless the existing explicit **Allow curtailment
control in Monitoring Mode** permission is enabled. Permission transitions settle
owned recovery before relinquishing control. Remaining export curtailment is
re-evaluated after production recovery. Negative-import stopping never islands
the Powerwall; optimizer off-grid projections exclude negative import slots.

## Optimizer and evidence

Enable **These controls cover all solar generation** only when every PV source is
covered. After current device controls have been confirmed, the optimizer can
project zero PV during negative import slots. Mixed or unconfirmed sites retain
their forecast. Raw solar forecasts are preserved, and deliberate production
suppression is excluded from forecast learning and cloud nowcasting.

The capability matrix was checked against the adapter implementations at
`0863c7d2e85ca46d8ff1272cc246685c28321cca` (published v2.12.1417), then covered
by focused control, recovery and routing regressions. These are source and
simulated-control checks; they do not establish physical inverter behavior.

Primary references:

- [Enphase Envoy integration](https://www.home-assistant.io/integrations/enphase_envoy): production controls and battery limitations.
- [Enphase solar troubleshooting guide](https://enphase.com/sites/default/files/2025-08/Enphase-solar-troubleshooting-guide-ING-00061-2.0-EN-INT-2025-08-14.pdf): production disabling also stops Enphase battery charging/discharging. The native implementation uses explicit DPEL production limiting instead of the whole-system production-disable control.
- [Fronius GEN24 Modbus instructions](https://manuals.fronius.com/html/4204102649/en-US.html): active-power limits affect inverter output; battery topology matters.
- [SolaX remote settings](https://www.solaxpower.com/uploads/file/a1-ess-g2-remote-setting-user-manual-en.pdf): export power is a grid-export constraint.
- [Zeversolar ZeverManager manual](https://www.zeversolar.com/fileadmin/user_upload/pdf/usermanuals_en/zevermanager_user_manual_en.pdf): active-power percentage limitation.
- The pinned repository adapters and the focused regressions are the protocol implementation evidence; no new undocumented register addresses are introduced.

No customer inverter commands, Home Assistant installation, physical import
increase or paid-import earnings were verified during implementation.

## Verification boundary

| Rung | Implemented evidence | Live proof |
| --- | --- | --- |
| Eligibility | Current retail interval, strict negative boundary, grid status, monitoring and capability regressions | Simulated |
| Planned action | Capability-scoped solar projection; negative import slots excluded from islanding | Simulated |
| Effective action | Manual/external ownership, shared control lock, expiry and unload/restart tests | Simulated |
| Command boundary | Native DPEL, Modbus and HTTP transports; explicitly selected HA production services | Fake transports only |
| Acknowledgement | Rejection, missing ACK, readback mismatch and retry cases | Simulated |
| Hardware readback | Exact prior/commanded register, DPEL or entity snapshots; partial-write recovery | Simulated |
| Physical effect | Fresh controlled-PV transition required; night/pre-command/missing observations remain unknown | Not measured on hardware |
| Status | Production sensor, existing AC status sensor and API keep unconfirmed stops pending | Simulated |

The first unproven live rung is an actual inverter command. Zero grid export,
zero PV at night, an accepted request and a real production stop are competing
explanations for superficially similar readings; the implementation keeps them
separate. Implementation and verification issued no live device controls.
