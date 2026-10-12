# Amber Forecast Confidence implementation

Approved scope: an opt-in HA optimizer switch, matching PowerSyncMobile
settings, wiki documentation, and a combined mobile build including existing
local build/Hermes changes. No device controls or store submission.

1. Keep displayed, settlement and eligibility prices intact. Add a pure Amber
   export valuation function with original provider interval metadata.
2. For future spike intervals, shrink only the premium above an ordinary-price
   band with a 90-minute half-life. The band uses the duration-weighted median
   plus max(10c, three median absolute deviations), capped at $1/kWh. Its
   samples exclude flagged spikes, prices above $1, duplicates and padding;
   at least two ordinary source intervals are required. Non-positive prices,
   prices within the band and the active interval retain their valuation.
   These constants are explicit risk heuristics, not measured probabilities.
3. Apply before export boosts/saving-session overlays, propagate adjusted
   values through gap filling, and replace legacy export decay only when the
   new function has usable metadata and an ordinary baseline. Import decay
   and other providers keep their existing behaviour. OFF is identical to the
   existing pipeline.
4. Persist `amber_forecast_confidence_enabled`, default false, through config
   flow, the HA config switch and optimizer GET/POST settings. Rebuild the plan
   after a change, synchronize state, and expose accepted-plan diagnostics.
5. Advertise provider visibility in shared settings metadata. Mobile renders
   the switch only for Amber and an advertising backend, forwards both true
   and false, and reads back the saved value without overwriting draft fields.
6. Verify source intervals/gaps, missing metadata, current prices, ordinary
   rates, negative rates, overlays, OFF equivalence, settings lifecycle, real
   LP tradeoffs, reserve/site/deadline controls, Cost Neutral and Spread Export.
   Replay cases are synthetic; no claim of historical revenue improvement.
7. Update Smart Optimization, Electricity Providers and Sensors wiki pages.
   Include the existing mobile edits in build 441; retain app version 1.0.7.
   Verify native versions, bundle export and signed build artifacts.

The feature changes scheduling preference. It cannot guarantee a spike,
partial export, revenue improvement or a physical hardware response.

## Verification and delivery

- 345 focused and adjacent Python regressions passed after integrating the
  current signed-price export gates and solar-export hold fixes. Compilation and diff
  checks passed across the HA integration, mobile app and wiki changes.
- Mobile settings, EV display, marketing/build version consistency, TypeScript
  and the actual mobile adapter → isolated HA POST/GET/restart tests passed.
- All five Hermes regression checks passed on the Mac, without skips.
- Android 1.0.7 / 441 AAB validated with bundletool; JAR signature and release
  certificate match the previous release. The packaged bytecode contains the
  feature and matches the final generated bundle.
- Signed iOS 1.0.7 / 441 archive verified: bundle ID/team, matching app/dSYM
  UUID, packaged feature, Release Hermes selection and scene delegate.
- Both builds are in the Mac's Downloads folder. AAB, archive ZIP, final source
  snapshot and verification JSON are also in /mnt/user/developer/artifacts.
- All originally pending mobile edits are included. The Mac's older checkout
  remains unchanged; its build used an isolated source snapshot.
- HA and wiki publication is authorized for v2.12.1383. Export Boost receives
  confidence-weighted valuation separately from signed settlement rates used
  for eligibility and anti-arbitrage checks. Mobile store submission and device
  commands remain outside this release.
