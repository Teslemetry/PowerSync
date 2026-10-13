<!-- release: v2.12.1388 -->

## What's Changed

**Enforce Price-Level limits on Generic and OCPP plug-in charging**
Price-Level Charging now applies its price thresholds and minimum home-battery
SOC to Generic and OCPP charges that started outside PowerSync. This includes
cars that automatically charge when plugged in and charging that is reported
after an earlier PowerSync start timed out. Previously, these charger paths
only stopped sessions already tracked as PowerSync-started, allowing an
untracked charge to continue above the configured price or below the battery
minimum.

The existing per-vehicle external-charging policy still applies. PowerSync
control enforces the limits; hands-off external charging preserves the external
session, including when the price is otherwise eligible. Saved hands-off
policies on older anonymous Generic/OCPP profiles are preserved for the exact
configured charger. Other PowerSync
owners and away/unplugged vehicles remain protected. Untracked charging must
have current charging-status or delivered-power telemetry from the exact
configured charger. Switch state, stale telemetry, another charger's readings,
and OCPP offered power do not establish an active charge.

**Configurable confirmation for cloud-polled Generic chargers**
Generic managed starts now wait up to 150 seconds by default for fresh charging
status or measured power, accommodating feedback such as a power update
arriving 86 seconds after the start command. Existing installations receive the
new default. Choose **Generic charger start confirmation timeout** under
**Configure > EV charging** to set a value from 30 to 300 seconds. Invalid saved
values fall back to 150 seconds, and invalid submitted values are rejected.

An accepted command or an on switch alone still does not confirm charging.
Unconfirmed or cancelled starts attempt a compensating stop, while a competing
owner acquired during confirmation is preserved. A pending Price-Level Generic
start can be cancelled if its decision becomes ineligible or Price-Level is
disabled before cloud feedback arrives. Late telemetry does not retroactively
promote a failed start; later evaluation uses normal eligibility and ownership
checks. A stop acknowledgement remains separate from physical stop proof.

## Regression coverage

Coverage includes Generic/OCPP plug-in starts at high prices and below the home
battery minimum, exact charger identity and telemetry freshness, hands-off and
other-owner preservation, away/unplugged scope, pending-start cancellation,
86-second cloud feedback, configured timeout precedence, invalid saved values,
manual takeover during timeout/cancellation, and option persistence. The EV
Smart Charging wiki has been updated with the settings and control boundaries.

Update available via HACS
