# Amber Smart Shift

PowerSync connects directly to Amber Smart Shift from the Home Assistant integration. No separate Amber battery integration, blueprint installation, or external controller is required. Your battery must already be enrolled in Smart Shift and working in the Amber app.

## Setup

Choose Amber Electric as the electricity provider and configure your public Amber API token and pricing site as usual. For the battery system, choose **Amber Smart Shift — native cloud battery control**, then **PowerSync native Amber Smart Shift** as the connection profile. Enter the credentials used by the Amber app. The discovered battery must belong to the selected pricing site.

The connection form exposes these settings:

| Setting | Meaning |
| --- | --- |
| Amber email | Your Amber account email. |
| Amber password | Your Amber account password. Leave blank when editing an existing connection to retain it. Passwords are never prefilled. |
| Let PowerSync manage battery operation | Off by default. Leave off for Amber-managed operation and manual PowerSync controls; enable to allow PowerSync optimisation and automation commands. |
| Allow PowerSync to enable Smart Shift for overrides | Off by default. When allowed, an override may enable Smart Shift and leave it enabled. Without permission, requests are blocked if Smart Shift is off. |
| Grid power (positive import) | A fresh W or kW sensor, positive for import and negative for export. Required for automated control. |
| Solar power | A fresh W or kW solar-production sensor. Required for automated control. |
| Home load power | A fresh W or kW home-load sensor. Required for automated control. |

Change these settings through **Configure → Amber Smart Shift connection and control owner**. Keep the battery capacity and rated charging/discharging power in PowerSync's optimisation settings accurate. Amber selects actual battery power; those ratings inform the plan and software safety checks.

## Operation

The PowerSync dashboard provides Charge, Export, Preserve, Self-consumption, and Cancel PowerSync override controls. Dashboard actions last 30 minutes; services accept durations from 1 to 240 minutes. Existing `power_sync.force_charge`, `force_discharge`, `hold_battery_soc`, `set_self_consumption`, and `restore_normal` services use this backend when selected. The entry-targeted `power_sync.preserve_battery` service provides a timed charge-preservation override.

Include the PowerSync `entry_id` in service calls. Explicit manual requests use `source: manual`; unattended automations use `source: automation` and require PowerSync management to be enabled. Target watts are unsupported: omit `power_w` or set it to zero. A nonzero explicit target is rejected.

PowerSync maps charge, export, preserve, and self-consumption to Amber's timed battery modes. Preserve holds charge without changing a persistent hardware reserve. Restoring normal operation cancels only the override PowerSync owns. An override from the Amber app remains external; cancel it in Amber before requesting a PowerSync override. Automatic PowerSync actions cannot replace or cancel a manual override.

Automatic overrides have a maximum ten-minute lease. The optimiser revisits the current action and its safety gates before renewing a lease near expiry; a stale plan cannot renew. Shorter reserve-safe durations remain shorter. When an override expires, normal Amber management resumes, including if Home Assistant is offline. Timed manual requests retain their requested duration.

Turning the Smart Shift switch off cancels PowerSync's own override and disables PowerSync-managed operation. Turning it on does not enable PowerSync management; choose that separately in configuration.

## Status and limitations

Battery SOC, battery power, capacity, Amber-reported activity, connectivity, last poll time, control owner, active override, expiry and command status appear as native PowerSync entities. Battery telemetry is polled every 30 seconds. Missing or stale measurements remain unavailable. Selected grid, solar and home-load meters must report within 90 seconds for automatic commands.

The dashboard distinguishes a requested action, API acknowledgement, and Amber's reported override. **Reported** means Amber returned the matching override ID and mode. It does not prove the battery physically charged or exported; check battery power, SOC and grid flow for that evidence. Planned watts are estimates.

Future or incompletely timed overrides appear as pending. Unavailable battery telemetry produces unknown current status instead of displaying the optimiser's planned action as an active mode.

Interval import cost, export earnings and net earnings use Amber's current interval metrics in cents. They are not settled billing totals and do not replace PowerSync's public Amber pricing, forecasts or metered-usage sensors.

This backend cannot set target watts, persistent hardware reserves, off-grid operation, or solar-production limits. It cannot enforce a dynamic network export-power envelope; forced export is blocked when one is active. Solar curtailment requires a separately supported inverter control path.

SOC reserve and charge limits are checked in software, including during active overrides. They are not hardware-enforced guarantees during an outage. Amber's own hardware protection remains separate. Automatic writes also require matching pricing/battery identity, current interval prices, fresh telemetry, and the existing monitoring, grid-charge, demand, export and ownership gates.

## Troubleshooting

- **Sign-in failed:** check the Amber credentials and complete any sign-in challenge in Amber. Unsupported challenges are rejected; PowerSync does not bypass them. Reconnect through HA's reauthentication prompt.
- **Site/configuration mismatch:** select the matching pricing site and reconnect. PowerSync does not guess which battery to control.
- **Command blocked:** check control-owner permission, Monitoring Mode, meter freshness, prices, SOC limits and Smart Shift status. A plan can remain visible while execution is blocked.
- **Unconfirmed command:** the API response or override readback is incomplete. PowerSync retains its journal and blocks replacement until reconciliation or expiry, rather than blindly repeating the write.
- **Cleanup pending:** PowerSync retains the exact owned override ID for retry. Check Amber connectivity and expiry. An override created later in the Amber app is never cancelled as cleanup for an older PowerSync command.

Amber battery control uses a private API. Changes or outages may temporarily make it unavailable. Price-only Amber setups and existing direct battery backends continue to use their existing paths.

## Verification boundary

The implementation has automated tests for transport errors, command routing, setup, identity, ownership, pending writes, restart cleanup, SOC limits and lease behavior. Account authentication, supported battery behavior, and physical charge/export require a supervised live verification after installation; no hardware commands are part of the automated checks.
