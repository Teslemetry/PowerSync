# HA optimiser licensing implementation

This is the tracked contract and implementation handoff for the HA subscription work. Commercial decisions are US$3/month through qualifying recurring GitHub sponsorship or A$4/month directly. Direct Stripe Checkout collects a card and grants one seven-day HA trial per account independently of legacy use and the announcement period. On completion, Stripe bills A$4/month automatically after the trial until cancelled. GitHub begins paid sponsorship without a trial. Hosted Cloud subscriptions do not include HA access.

## Current implementation stage

The first stage implements the isolated billing/entitlement foundation and the permission wire contract. It is not ready for production activation or a customer enforcement release.

Cloud source now contains HA-specific database tables, a pure source-union resolver, verified invoice coverage, card-required Stripe Checkout and a separate HA billing portal, account access and installation pairing endpoints, signed allow/deny permissions, GitHub OAuth linking with PKCE and browser binding, and complete private-inclusive sponsorship reconciliation via signed webhooks and an hourly scheduled check. Account bootstrap has a read-only endpoint. The HA account page at `/app/ha` bypasses Cloud feature gates and site setup. With the HA rollout enabled, Cloud trial creation requires explicit Cloud enrolment when entering the Cloud app. HA and Cloud use separate Stripe customers, preventing saved Cloud cards and the Cloud portal from leaking into HA signup.

HA verifies Worker-signed Ed25519 permissions and provides an admission generation that can invalidate queued work synchronously. Its read-only licensing status is registered in shadow mode. The admission gate is **not yet connected to inverter commands or recovery**, and the client storage/refresh and configuration flows are still required.

Mobile parses HA-provided licensing status and can present an enforced access notice. It does not derive HA access from the phone's hosted Cloud subscription, and hides the notice during shadow rollout. Existing Amber forecast-confidence, Hermes configuration and build-441 changes were carried into the same implementation branch at the user's request.

## Permission contract version 1

- Compact three-part encoding: base64url header, payload and Ed25519 signature over their exact encoded bytes.
- Header: `alg=EdDSA`, `typ=PSHA1`, explicit trusted `kid`.
- Issuer: `powersync-ha-licensing`; audience: `power_sync:ha_optimizer`.
- Installation UUID, credential generation, entitlement revision and policy epoch scope the permission.
- Integer UTC epoch seconds specify issue, refresh and expiry. Maximum permission lifetime is seven days, capped by the valid source horizon.
- Allowed features are exactly `["ha_optimizer"]`. A signed denial has `features=[]` and source `subscription_required` or `installation_revoked`.
- A denial cannot be replaced by an older allow response. A new paid permission after suspension requires explicit Resume before queued optimiser work can run.
- Signing keys remain Worker-only. The committed RFC 8032 fixture is public test material, not a production trust configuration.

The same public fixture is stored in HA `tests/fixtures/ha_optimizer_permission.json` and Cloud `worker/scripts/fixtures/ha_optimizer_permission.json`. The Worker check signs the fixture and compares it byte-for-byte; Python verifies those bytes and tests altered signatures, scopes, types, times, keys and stale revisions.

## Rollout configuration

`HA_LICENSING_ENABLED` defaults off. Do not enable it until the remaining launch gates below pass. The migration is `0075_ha_optimizer_licensing.sql`; it has not been applied remotely by this work.

Cloud configuration requires a distinct HA Stripe price ID, a dedicated HA portal configuration, pinned Stripe API version, explicit live/test mode, Ed25519 signing JWK/key ID and a positive deployment policy epoch. Before opening Checkout, source validates an active AUD recurring monthly price of exactly 400 cents and rejects either Cloud price ID. GitHub verification requires the verified PowerSync sponsorable ID and a credential proven to read private sponsorships. Identity linking also needs a GitHub OAuth client ID/secret with callback `https://api.powersync.cc/ha-license/v1/github/callback`; the signed webhook uses `/ha-sponsors/webhook`. OAuth tokens are not persisted. Only stable GitHub user IDs are linked; organisation sponsorships require an explicit support decision and are not inherited by arbitrary organisation members. Exact names are in `worker/src/types.ts`; signing/provider credentials are secrets.

Paid coverage advances only from verified paid HA invoice lines. Current subscription period dates and browser success URLs do not prove payment. Existing Cloud price mapping remains untouched; HA events are contained before it and at the legacy persistence boundary, including rollback handling.

## Remaining work before enforcement

1. Confirm the real price catalogue/private-sponsor credential and configure test/live isolation.
2. Verify real private/anonymous sponsor visibility, scheduled reconciliation and webhook delivery. Support identity linking remains to be implemented; no Discord role is assigned by this code.
3. Exercise card-required Checkout, automatic conversion, cancellation, refunds and the dedicated portal in Stripe test mode. Complete account deletion and account merging across the new HA tables. Existing admin delete/merge handlers now reject accounts with HA records before touching tokens or controls; Cloud-only enrolment rows cascade normally. The account page and Checkout source are implemented, but have not been browser-tested against real providers.
4. Implement HA installation secret/permission persistence, public-key configuration, pairing UI and bounded refresh/clock handling.
5. Connect the admission generation to every optimiser dispatch/reserve/cached-action path. Reuse and verify persistent owner-aware restoration; keep recovery available without paid access.
6. Complete entry-specific status/configuration, mobile controls/compatibility, support entitlements and store-policy checks.
7. Complete website/wiki/mobile activation guidance and the priority-support workflow. Reconcile the already-posted announcement with a revised go-live date after activation works. Keep campaign dates, personal trial dates, lease expiry and payment grace independent.
8. Run representative authorised readback/physical tests and staged enforcement. Publish website/wiki/release changes only through the authorised launch workflow.

## Acceptance evidence

The HA focused suite passed 129 tests. Worker checks exercise the actual Hono routers, signed webhooks and migration on real SQLite with mocked external providers. They cover price isolation, abandoned and repeated Checkout, trial invoice exclusion, immutable trial history, paid invoice coverage, rollback containment, pairing retries, signed revocation, private sponsors, provider outage, OAuth browser binding/replay/account conflict, and cancellation without revoking another paid source. Cloud Worker type checking and the web app build pass.

Mobile checks pass for access parsing, explicit Cloud enrolment with an older-Worker fallback, TypeScript, optimiser settings, EV display, build-441 consistency and the Amber-to-HA contract. Hermes reports three passes and two platform-dependent skips; CocoaPods and actual iOS compilation remain Mac-only checks.

## Validation commands

HA: Python 3.12 pytest for `test_ha_optimizer_permission.py`, `test_optimizer_restore_retry.py` and `test_optimization_price_source.py`.

Cloud Worker: `npm run test:ha-licensing`, `npm run test:subscription-plans`, `npm run test:auth-email-security`, and `npm run type-check`. Cloud app: `npm run build`.

Mobile: `npm run test:optimizer-access`, `npm run test:cloud-enrollment`, `npm run test:hermes-config`, `npm run test:build-version`, the Amber contract test with `POWERSYNC_TEST_PYTHON` set to the repository Python 3.12 harness, optimisation/EV regressions and TypeScript checking. Build-version checks require generated native inputs. Ruby/CocoaPods Hermes checks and actual iOS compilation run on the Mac.

All checks here are source/simulation evidence. No billing configuration, remote migration, release, store submission, public message or live hardware command was performed.

## Provider references

The linking flow follows [GitHub OAuth with state and PKCE](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps). The verifier uses stable sponsor identities, active/recurring state and private visibility from the [Sponsors GraphQL contract](https://docs.github.com/en/graphql/reference/sponsors). Checkout collects a payment method and configures the trial through the [Stripe Checkout trial API](https://docs.stripe.com/payments/checkout/free-trials).
