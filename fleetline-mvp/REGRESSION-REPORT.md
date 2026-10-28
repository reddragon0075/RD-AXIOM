# Axiom Fleet — Regression Test Report

**Test date:** 30 September 2026
**Build:** `/home/user/fleetline-mvp`  
**Architecture:** Axiom Fleet console + Driver PWA + Expo Driver client + Supabase production foundation + dependency-free SQLite fallback

## Final result

**PASS — 101/101 static, HTTP and interaction-contract checks.**

Phase 1/2, Phase 3 and AI Bill Intelligence SQLite coverage, provider-boundary tests, frontend JavaScript syntax checks and Supabase contract checks pass. The latest hardening slice also passes bounded Driver PWA inputs, parity-safe calculation ceilings, expense/proof server validation, deployment-header contracts, MFA/RLS/mutation guards and signed webhook-boundary contracts. The result is a complete local/mock-first implementation; Supabase project application, browser/WCAG verification and physical Android/pilot gates remain explicitly open.

The following end-to-end local suites also passed after the extended feature layer was integrated:

- `backend_smoke_test.py`
- `domain_engine_test.py`
- `golden_calculation_test.py` (1,000/1,000 generated cases)
- `domain_smoke_test.py`
- `execution_smoke_test.py`
- `provider_adapter_test.py`
- `feature_smoke_test.py`
- `uncovered_smoke_test.py` (reset-token lifecycle, static isolation and origin checks)
- `security_smoke_test.py` (production demo gating, Secure cookies, mock-payment gating, HMAC webhook verification and replay protection)
- `bill_intelligence_smoke_test.py` (OCR extraction, confidence/review, fuzzy vehicle fallback, duplicate/arithmetic checks, posting, timeline attribution, tenant isolation and undo)
- `masters_smoke_test.py`, `network_mvp_smoke_test.py`, `p0_smoke_test.py`
- `deep_feature_smoke_test.py`
- `supabase_contract_test.py`
- `mobile_driver_contract_test.py`
- `p0_smoke_test.py`
- `phase12_smoke_test.py`
- `phase3_smoke_test.py` (predictive alerts, graph, simulations, variance, sustainability, regions and tenant isolation)
- `phase3_ev_smoke_test.py` (EV eligibility, charging availability, range, energy cost, passenger-kilometre intensity, avoided emissions and reporting)
- `supabase_contract_test.py` (including Phase 1/2/3 tables, RLS guards and authenticated Edge Function boundaries)
- `regression_check.py` acceptance contracts for loading/recovery, validation, mobile cards, bulk workflows, saved views, command search, audit references and regionalization.
- `docs/ui-acceptance.md` product acceptance contract.

Browser/WCAG 2.2 AA verification and Expo/Android export remain release-gate checks. This environment has no browser automation runtime installed, so the current result covers source-level action binding, HTTP contracts and smoke suites; a real browser click-through is still required before release.

The deep suite now covers onboarding and provisioning, duplicate checks, master deactivation, employee lifecycle, price-book version approval, recurring and multi-stop bookings, capacity locks, multi-level booking approvals, duty exceptions, navigation, masked calling, SOS, supplier bills, fleet costs, payouts, financial approvals, tax calculation, billing notes, public payment links, e-invoice cancellation, receipt allocation, payment webhooks, driver preferences/devices/practice, passenger access/rating, alerts/geofences, polling updates, local TOTP/API-key security, queued jobs, associate network, settlements, report exports/views/schedules, privacy request fulfillment, retention, admin KPIs and feature flags. Phase 1/2 adds unified masters/import-export/versioning, rosters, ETA/GPS health, safety evidence and maker-checker closure, Network formula/dispute/reconciliation, saved views, permission bundles, mobile home and HRMS/GPS/maps/messaging/storage boundaries. Phase 3 adds deterministic predictive factors and lifecycle feedback, invite-only vendor-quality graph, idempotent cost/service simulation, reconciliation variance findings, sustainability factors/targets and controlled multi-country localization/FX/tax contracts.

Python compilation and JavaScript syntax checks also passed for the backend, extended layer, tests, inline console script and Supabase browser adapter.

## Live local HTTP validation

The live fallback server was restarted on `0.0.0.0:4173` and validated with:

- Root document: HTTP 200, `text/html`.
- Supplied logo: HTTP 200, `image/png`.
- Health route: HTTP 200, JSON.
- Gzip delivery: enabled; current response was 525,027 bytes raw and 113,291 bytes compressed.
- `regression_check.py`: **101/101 passed**.
- Authenticated live route probe: `/api/auth/me`, `/api/supplier-bills`, `/api/network/edges`, `/api/admin/kpis`, `/api/security/2fa` and `/api/privacy/requests` all returned HTTP 200.

## Implemented feature layer

### Local fallback backend

- `backend_extended.py` owns the extended PRD workflows and initializes its SQLite schema.
- `server.py` imports the extended layer, initializes it before serving, dispatches extended route families before existing handlers, and recognizes all added API prefixes.
- Organization ownership checks, role checks, idempotency behavior, audit events and mock provider references are applied in the local path.
- Static delivery is allowlisted, runtime SQLite data and source modules are not public, and security headers/CSP/HSTS are emitted in the appropriate environment.
- Password reset requests are rate-limited and use hashed, expiring, one-time tokens; login/signup/reset throttles persist in SQLite.
- Mock public payment capture is development-only by default; provider webhooks require HMAC verification, a replay-safe external event key and an organization scope.
- `/api/updates` provides a cursor-based polling fallback for duty and alert changes.
- `/api/tax/calculate` performs state-aware CGST/SGST versus IGST splitting in paise.
- `/api/sla` supports event creation and resolution.
- Recurring bookings, multi-stop route plans, capacity locks, billing notes, payment links, queued jobs, security factors/API keys, employee lifecycle and public payment-link capture are implemented with auditable local records.

### Security hardening slice

- `driver-app/index.html` now constrains expense categories, rupee/paise amounts, notes and OTP proof values before offline queueing or submission.
- `backend_domain.py` and `domain_engine.py` revalidate allowlists, OTP shape, finite/integer values and expense/calculation ceilings; local calculation products are overflow-safe.
- `supabase/functions/calculate-duty/index.ts` mirrors the same field ceilings, safe products and tax/total bounds.
- `supabase/migrations/20260930000000_axiom_security_hardening.sql` requires Auth `aal2` for vendor owners, corporate admins and platform roles; strengthens membership/permission RLS, locks the duty row, validates persisted snapshot numbers and prevents direct `calculation_snapshot` mutation. Expense/proof constraints and RPC checks are included, with all new tables remaining tenant/RLS scoped.
- `supabase/functions/webhook-gateway/index.ts` provides signed payment, SMS, WhatsApp and telephony ingress with per-provider HMAC secrets, replay timestamps, constant-time comparison and idempotent `webhook_events` recording. Provider-specific canonicalization and live credentials remain release gates.
- `vercel.json` declares CSP, frame-ancestor/clickjacking, HSTS, `nosniff`, permissions and referrer protections; the local server emits matching clickjacking protections.
- `execution_smoke_test.py`, `supabase_contract_test.py` and `regression_check.py` cover the new hardening contracts.

### Phase 1/2 local and production boundary

- `backend_phase12.py` is wired before compatibility handlers and keeps Fleet duties/bookings canonical while adding the unified registry, roster versions, live ETA/GPS health, safety evidence/closure approvals, Network activation/replacement/scorecard/reconciliation, saved views, bulk idempotency, mobile home and provider boundaries.
- `provider_adapters.py` now has deterministic HRMS and GPS/telematics adapters alongside maps, messaging, storage, telephony, payment and e-invoice mocks.
- `supabase/migrations/20260924000000_axiom_phase12_foundations.sql` mirrors the additive tables, permission keys, tenant RLS and audit trigger contracts.
- `supabase/functions/phase12-orchestrator/index.ts` is the authenticated Supabase Edge Function boundary expected by `supabase/client.js`; it covers registry import/export, rosters/ETA/bulk, safety, Network, views, bundles, mobile home and integrations without service-role credentials in browser code.
- The native Driver client hydrates `/api/mobile/home` into its Today screen while retaining offline replay, sticky quick actions and safety controls.

### Phase 3 moat layer

- `backend_phase3.py` is initialized after Phase 1/2 and before compatibility handlers. It keeps Fleet canonical while projecting deterministic alerts, vendor quality, simulations, variance findings, sustainability and localization.
- `phase3_smoke_test.py` passed on a fresh database with two tenant signups, idempotent replay, alert lifecycle/feedback, emissions targets, controlled region rejection, tenant isolation, FX and tax previews.
- `supabase/migrations/20260925000000_axiom_phase3_moat.sql` adds the production tables, controlled region/emission catalogs, permissions, RLS policies and conditional audit triggers.
- `supabase/functions/phase3-orchestrator/index.ts` is the authenticated JWT/anon-key Edge boundary; `supabase/client.js` routes `/api/phase3/*` through it when Supabase is enabled.
- The private console exposes **Axiom intelligence** with evaluation, scan, simulation, emissions and localization actions. Local calculations remain mock-labelled and deterministic until approved providers and factor/FX governance are configured.

### Supabase production direction

`supabase/migrations/20260919000000_axiom_fleet_foundation.sql` now includes extended tenant tables for:

- Onboarding state, record versions and duplicate matches.
- Supplier bills, cost entries, receipt allocations, payouts and financial actions.
- Approval steps, SLA events, trip shares and passenger ratings.
- Driver preferences, devices, calls, SOS events and practice duties.
- Alerts, geofences, notification events and webhook events.
- Network edges/offers/bids/settlements.
- Report exports/views/schedules.
- Consent receipts, retention locks, privacy requests and security events.
- Recurring bookings, booking stops, capacity locks, billing notes, payment links, jobs, auth factors, API keys and security events.

Each extended table has RLS enabled, authenticated grants and organization/member or user-scoped policies. The migration keeps the existing Auth, memberships, core domain tables and RPCs intact.

`supabase/client.js` now supports the onboarding/provisioning path and browser-side adapters for the extended financial, reporting, network, alert, tax, update, retention and admin KPI workflows. It continues to fall back to same-origin local APIs when Supabase is disabled.

A live Supabase project has not been connected or migration-tested because project URL, anon key and project credentials were not supplied. That is an environment gate, not a local implementation failure.

### Console exposure

- Onboarding progress is hydrated from `/api/onboarding` and can be completed from a server-persisted modal.
- The Overview quick actions now include a Workflow Center.
- Dedicated Finance controls, Network & partners, Admin health, Security & privacy and Passenger view pages hydrate from extended APIs.
- Progressive navigation keeps Overview, Duties, Bookings, Billing and Fleet visible while grouping advanced tools behind More tools; driver sessions land in Driver app mode.
- Overview now presents a three-move Today operating path: capture booking, clear duty queue and check field readiness.
- Driver app mode adapts to the signed-in driver, assigned-duty data and local sync queue; the help button opens a role-specific three-step product tour.
- `/driver-app/` now exposes a mobile-first Driver PWA vertical slice with sign-in, tenant-assigned duty lifecycle, offline queue, sync center, proof, expenses, masked call and SOS controls; no demo duty entry is rendered.
- `mobile-driver/` contains the Expo/React Native foundation for the same Driver flow, with secure mobile tokens, foreground location, notifications, offline replay and Android/iOS build configuration.
- Duties, fleet and corporate surfaces hydrate route, driver, vehicle, capacity, supplier, invoice and document context from live organization data; empty and unavailable states remain explicit and no operational demo fixtures are rendered.
- Workflow Center actions invoke supplier-bill, fleet-cost, driver-payout, report-export, network-edge, retention, updates, security and KPI endpoints using the current organization session.
- Existing Axiom Fleet public pages, protected route guard, logo and private console navigation remain intact; development fixtures are not rendered in the public UI and the known local fixture is disabled in production.

## Optimization and delivery checks

- Supplied transparent Axiom Fleet logo remains in six expected surfaces.
- Logo asset is 640×184 and 65,271 bytes, below the 100 KB target.
- Local static assets and script references resolve.
- Gzip compression and cache headers remain active.
- Static form labels, route templates, hash routing and authentication bindings remain green.

## Validation commands

```bash
python3 regression_check.py
python3 security_smoke_test.py
python3 uncovered_smoke_test.py
python3 backend_smoke_test.py
python3 domain_engine_test.py
python3 golden_calculation_test.py
python3 domain_smoke_test.py
python3 execution_smoke_test.py
python3 provider_adapter_test.py
python3 bill_intelligence_smoke_test.py
python3 feature_smoke_test.py
python3 corporate_foundation_smoke_test.py
python3 deep_feature_smoke_test.py
python3 supabase_contract_test.py
python3 mobile_driver_contract_test.py
python3 p0_smoke_test.py
python3 phase12_smoke_test.py
python3 phase3_smoke_test.py
python3 -m py_compile server.py backend_domain.py backend_features.py backend_extended.py backend_p0.py backend_phase12.py backend_phase3.py domain_engine.py provider_adapters.py mobile_driver_contract_test.py
npm run typecheck  # from mobile-driver/
npx expo export --platform android --output-dir /tmp/axiom-fleet-export  # from mobile-driver/
node --check /tmp/axiomfleet-regression.js
node --check /tmp/driver-app.js
node --check supabase/client.js
npx esbuild supabase/functions/phase12-orchestrator/index.ts --bundle --external:https://* --outfile=/tmp/phase12-orchestrator.js && node --check /tmp/phase12-orchestrator.js
npx esbuild supabase/functions/phase3-orchestrator/index.ts --bundle --external:https://* --outfile=/tmp/phase3-orchestrator.js && node --check /tmp/phase3-orchestrator.js
```

## Corporate account and policy foundation slice

The principal account/policy gap identified in the legacy rental platform comparison is now implemented as an additive domain boundary:

- Corporate account connection, setup wizard data, copied scope/pricing snapshots, activation guard and idempotent setup replay.
- Explicit admin, employee-admin and booker/passenger users with grants/denies and tenant visibility evaluation for branch, customer entity, sister company, city, vehicle group, duty type and company scope.
- Versioned booking policies for lead time, cancellation SLA, approval routes, supplier selection and auto-allotment.
- Explainable booking evaluation records with `allow`, `needs_approval` and `block` outcomes, enforced at booking creation/cancellation writes with pending-approval dispatch protection.
- Versioned duty types, vehicle groups, billing items, taxes, company scopes, pricing rules and document requirements.
- Deterministic allotment candidate resolution and document-validity guards; missing, pending or expired vehicle documents block eligibility.
- Passenger duty-slip state machine with hashed signed tokens, public token-only action route, approve/reject audit and manual/scheduled 48-hour auto-approval boundary.
- Supabase migration/RLS/permissions, corporate orchestrator and public signed-action Edge Function contracts; local SQLite remains the dependency-free fallback.

Focused validation: `python3 corporate_foundation_smoke_test.py` passed all assertions. The implementation notes and production handoff are in `docs/corporate-account-policy-foundation.md`.

## Known production gates

- Apply and validate the foundation, bill-intelligence and `20260930010000_corporate_account_policy_foundation.sql` migrations plus `20260930000000_axiom_security_hardening.sql` against a real project with Auth and RLS; run two-tenant policy assertions with AAL1/AAL2 sessions.
- Configure Supabase MFA enrollment/recovery for privileged roles, private Storage policies, Edge Functions, exact `AXIOM_ALLOWED_ORIGIN` CORS secrets, email templates and per-provider webhook secrets/canonicalization for the signed `webhook-gateway`.
- Validate the `vercel.json` header policy on the deployed origin, including CSP compatibility with the final Supabase domain and any trusted provider origins.
- Replace mock payment, messaging, maps, telephony and e-invoice adapters when credentials and compliance approvals are available; keep payment approval and bill posting inside reviewed database transactions/RPCs.
- Add native driver/passenger clients, Supabase Realtime, Redis-backed distributed throttling, production observability and security review.
- Complete pilot UAT, load/performance, retention-worker and DPDP fulfillment validation.

## Corporate dashboard and Network review

- The corporate role now opens an account-operations workspace rather than a generic fleet control room: direct/delegated request approvals, Super Admin → employee-admin → booker/passenger hierarchy, tenant-backed people access, policy/SLA watch, supplier and scope coverage, duty-slip governance, Network handoffs, finance evidence and audit activity are visible in one tenant-scoped hierarchy.
- The recovery surface now distinguishes a missing organization-linked session from a transient sync error. It explains why records are withheld and offers a sign-in or retry path instead of leaving a large blank workspace.
- The Network page now presents the closed B2B lifecycle as invite and qualify → publish demand → match and quote → approve award → Fleet handoff. Counts come from Network API collections; the page continues to avoid public vendor registration, anonymous lead resale and a second trip ledger.
- Competitive findings from the corporate page, partner network walkthrough and driver walkthrough are recorded in `docs/competitor-dashboard-analysis-20260930.md`. The review uses public product behavior as research and does not copy proprietary code, designs or text.

The correct release description is: **feature-complete local fallback with a Supabase production foundation; not yet a live production deployment.**

## Follow-on finance, reporting, feedback and evidence validation · 2026-09-30

The follow-on parity slice is now wired into the existing Finance and Reports UI rather than a parallel surface. It includes supplier payment/advance/settlement controls, driver payout maker-checker, bank-file payroll and statutory reports, fuel station/history/efficiency analytics, petty-cash and supplier/customer reconciliation, configurable reports/favourites/refresh/profitability/pricing/bill-to-duty exports, private async jobs, rich import preview/correction/commit UX, token-only public feedback and notification/corrective-action workflows. Tally/Tally Prime export formats are explicitly skipped.

The feedback delivery boundary is now hardened for production handoff: SMS, email and WhatsApp callbacks require channel-specific HMAC secrets with a five-minute timestamp window, constant-time signature comparison and provider-event deduplication. Transient callback failures schedule bounded retries, hard bounces remain terminal, and exhausted retries enter dead letter. The local smoke suite covers retry, bounce and dead-letter paths as well as receipt updates.

Focused validation passed:

- `python3 finance_feedback_smoke_test.py`
- `python3 enterprise_controls_smoke_test.py`
- `python3 finance_reporting_smoke_test.py`
- `python3 supabase_contract_test.py`
- `python3 regression_check.py` → 130/130
- `npx --yes deno check --no-config supabase/functions/*/index.ts` → all 17 Supabase Edge functions type-check
- `node --check supabase/client.js`
- Inline `index.html` JavaScript parsed with Node
- Supabase Edge TypeScript syntax parsed with esbuild for finance controls, feedback public/authenticated, enterprise and finance/reporting functions
- `openapi.yaml` parsed with PyYAML
- `git diff --check`

The implementation remains un-deployed. Supabase migration application, Edge deployment, Storage policy verification, real bank/payroll/notification provider credentials and production worker scheduling remain release gates.

## Booking, allotment and pricing parity validation · 2026-09-30

The additive booking lifecycle slice now covers parent/child, flat-rate, monthly and multi-day relationships; auditable booking actions and import/export; owned/company-supplier/DCO/invite-only Network dispatch; booking-wide allotment and re-allotment; arrival state; expiring temporary passenger/allotment records; versioned customer/supplier pricing; automatic duty-type switches; and invoice fuel-surcharge lines. Tally/Tally Prime export remains intentionally excluded.

Focused validation passed:

- `python3 booking_allotment_smoke_test.py`
- `python3 operations_parity_smoke_test.py`
- `python3 finance_reporting_smoke_test.py`
- `python3 regression_check.py` → `134/134`
- `npx --yes deno@2.4.0 check supabase/functions/booking-orchestrator/index.ts supabase/functions/operations-orchestrator/index.ts`
- `node --check supabase/client.js`
- Inline `index.html` JavaScript parsed with Node
- `npx --yes esbuild@0.25.0 supabase/functions/booking-orchestrator/index.ts --format=esm --platform=neutral`
- `git diff --check`

The local fallback and production Edge/migration contracts are implemented but not deployed to a live Supabase project. Physical Android testing, real push/object-storage credentials and the two-fleet pilot remain release gates.

## Final booking/allotment parity release validation · 2026-10-01

The final local and static validation pass completed after the booking import compatibility and invitation-route fixes:

- `python -m py_compile *.py` — passed for all repository Python modules.
- All 29 `*test.py` smoke/contract suites — passed, including booking/allotment, operations, finance/reporting, supplier finance, corporate foundation, enterprise controls, security, uncovered regression, mobile replay and Supabase contracts.
- `python regression_check.py` — `134/134 passed; 0 failed`.
- `npx --yes deno@2.4.0 check $(find supabase/functions -name index.ts -print | sort)` — all Supabase Edge functions passed.
- `node --check supabase/client.js` — passed.
- `openapi.yaml` — PyYAML parsed successfully as OpenAPI `3.1.0` with 277 paths.
- `git diff --check` — passed.
- Local preview server — healthy on port 4173 (`GET /api/health` returned 200).

Remaining release gates are operational rather than static: apply and verify the Supabase migrations/functions with real Auth/RLS, configure real push/provider/object-storage credentials, complete physical Android testing, and run the two-fleet pilot. Tally/Tally Prime export remains intentionally excluded.

## Follow-up parity hardening · 2026-10-01

- Network dispatch now requires an active vendor profile tied to an accepted, unexpired invite in both SQLite and Supabase paths; dispatch history stores `network_vendor_profile_id`.
- Supplier pricing quotes now select versioned supplier contracts in both local and Edge pricing paths.
- Automatic duty-type switching now reselects the switched duty-type rule before calculating package and extra-rate totals.
- Booking smoke coverage now includes invited Network dispatch and supplier pricing, while the existing full suite remains green.

## Broader local suite and date/routing hardening · 2026-10-01

The full repository smoke/contract sweep completed sequentially with all 33 `*_test.py` suites passing. During the sweep, two production-relevant local fallback issues were corrected:

- Compatibility handlers now reject unrelated routes before resolving tenant context. An unaffiliated driver can therefore accept an organization invitation, while every tenant-scoped feature route still requires organization access.
- Sustainability reporting filters by the duty's business/reporting timestamp when one exists, falling back to calculation time. Reports now include a September duty calculated on the following day instead of silently returning an empty period.

Validation after the fixes:

- All 33 `*_test.py` smoke/contract suites — passed.
- `python3 regression_check.py` — `134/134 passed; 0 failed`.
- `npx --yes deno@2.4.0 check $(find supabase/functions -name index.ts -print | sort)` — all 20 Supabase Edge functions passed.
- `node --check supabase/client.js` — passed.
- OpenAPI parsed as `3.1.0` with 304 paths.
- `git diff --check` — passed.

The local preview is running on port 4173. No Supabase project credentials are configured in this workspace, so live migration/RLS/Edge deployment and provider validation remain explicit release gates; this work does not claim production connectivity.
