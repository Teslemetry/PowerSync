# Native Tesla Charge on Solar

PowerSync adds explicit Home Assistant actions for reading and managing Tesla's native Charge on Solar through the selected Teslemetry vehicle provider. The UI is Developer Tools → Actions; no new mobile control is implied. The actions, cost, eligibility and recovery procedure are documented in the wiki [Services Reference](https://github.com/bolagnaise/PowerSync/wiki/Services-Reference#native-tesla-charge-on-solar-teslemetry).

The native controller is distinct from PowerSync Solar Surplus and Smart Schedule. The implementation uses the documented Teslemetry custom GET/POST route and both limits; it does not synthesize native behavior with ordinary amps/charge-limit commands. Existing installations make no native requests until explicitly requested. The service uses the dedicated EV token or existing Teslemetry energy token only when the selected EV provider is Teslemetry. Fleet and PowerSync Cloud credentials are rejected.

The module persists a VIN control hold before each native request, serializes handover against in-flight PowerSync EV actions and dynamic updates, and retains the hold on rejected or uncertain requests. Only complete disabled readback releases it. Unresolved commands are blocked while a hold exists, including unidentified charger paths. An explicitly different identified vehicle remains separate. Reads are explicit, may wake the car, consume credits and have a 15-second minimum interval. Writes are blocked in monitoring mode; active PowerSync EV sessions block reads and writes.

Enabling requires confirmation of Tesla native setup, compatible Tesla/Powerwall hardware and firmware, no site/export limits, other controllers disarmed and request costs accepted. Native mode does not enforce PowerSync price, phase allocation or grid-import constraints. The local hold cannot fence another integration or product, so it must be disarmed before native activation. There is no automatic hardware activation, restoration, retry or background native polling.

Focused tests cover provider selection, monitoring mode, eligibility, active sessions, exact API protocol, strict response validation, write acknowledgement versus settings readback, persistent uncertain-state holds and serialization. Adjacent EV action and policy regressions exercise existing command routing. These are source-level tests, not live vehicle or solar-flow verification.

## Dot planning review

Dot handoff `dot-96948efd46b9caa85908eaa7a384e55fd097736b` returned a provisional plan on 20 October 2026. Its connector exposed different repository baselines and could not read HA `__init__.py`; its report explicitly withheld exact-baseline approval. Local review reconciled the supplied source hashes: HA ownership/actions/services/policy-test files match the requested baseline, and current `get_tesla_ev_api_token` was inspected directly. Cloud differences were independently reviewed, including versioned encryption and owned-stop recovery added since Dot's snapshot. The source hashes and reconciliation evidence are retained in the local handoff review note.

The adopted plan is a separate native controller with explicit paid operations, encrypted Cloud credentials, strict settings readback, persistent ownership inhibition, eligibility confirmation and source/build/release verification. Current-source implementation, testing and delivery remain local responsibilities. Dot did not implement or test these changes and its report is not hardware proof.

## Delivery validation

820 focused and adjacent tests passed when run in isolated files: native solar, EV OCPP actions, policy command view, solar surplus configuration, phase management, active charging, capability refresh and price-level ownership. The expanded combined collection hits an existing global device-registry-stub ordering failure; the same failure reproduces at unchanged baseline `28added32`. An additional ownership-leak test expects a BLE call without `allow_backoff=True`; that assertion also fails on the unchanged baseline. Neither unrelated harness issue is hidden by weakening an assertion.

Source-only and full wiki checks passed (128 step destinations/exclusions, 29 profiles, 11 providers, 668 field references and links/anchors). The repository does not contain the referenced `docs/release-notes.md` or `scripts/release_preflight.py`; release preparation followed the actual manifest-triggered workflow and its exact release-marker validation, with Python syntax, translation JSON, diff and documentation checks run locally.
