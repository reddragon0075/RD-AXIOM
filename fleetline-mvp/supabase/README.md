# Axiom Fleet Supabase foundation

This directory contains the Supabase/PostgreSQL foundation selected for the production-oriented backend transition.

## Included

- `migrations/20260919000000_axiom_fleet_foundation.sql`
  - Supabase Auth profile trigger
  - Vendor/corporate organizations and branches
  - Driver profiles
  - Memberships and one-time invitations with acceptance RPCs
  - Permission matrix and RLS helpers
  - Append-only audit event foundation
  - Customers, suppliers, drivers and vehicles
  - Price books
  - Bookings, duties, duty events and duty proofs
  - GPS points and offline sync operations
  - Invoices, invoice lines, expenses and payments
  - Employees, travel policies, booking approvals and organization settings
  - Documents, notifications, support tickets and privacy requests
  - Notifications, integration events, mock e-invoice records and collection actions
  - Core RLS policies, including visibility for billing-provider records
  - Extended tenant-scoped tables for onboarding state, duplicate matches, supplier bills, costs, payouts, financial approvals, approval chains, SLA events, passenger ratings, devices, calls/SOS, alerts/geofences, network offers/bids/settlements, report exports/views/schedules, consent/retention locks, webhook events, recurring bookings, multi-stop routes, capacity locks, billing notes, payment links, queued jobs, auth factors, API keys and security events
  - Idempotent RLS policy generation for the extended tables
  - Organization and driver onboarding RPCs
  - Atomic duty transitions and paise-snapshot persistence RPCs
  - Immutable invoice issue and idempotent payment recording RPCs

- `migrations/20260923000000_axiom_p0_foundations.sql`
  - Versioned tenant master records and master snapshots
  - Sites, shifts, route plans/stops, roster assignments, replacements and dispatch events
  - Safety policies, incidents and corrective actions
  - Closed Network regions, vendor approvals, quote evaluations, messages, metric observations, scorecard runs, corrective actions, disputes and settlement statements/lines
  - Tenant permission overrides integrated into `has_permission`
  - P0-specific indexes, RLS policies and security-definer audit triggers
  - Additive lifecycle columns for Network requirements

- `migrations/20260924000000_axiom_phase12_foundations.sql`
  - Unified Phase 1 master registry and version/audit records for all requested kinds
  - Roster versions, ETA snapshots and operational bulk jobs
  - Safety evidence, storage references, closure approvals and stale-location evaluation records
  - Network activation/replacement records, formula-versioned scorecards, disputes and reconciliation
  - Versioned permission bundles, saved views and provider configuration/event ledgers
  - Permission keys, tenant RLS policies and conditional audit-trigger wiring for every Phase 1/2 table

- `migrations/20260929000000_axiom_bill_intelligence.sql`
  - Tenant-scoped bill extraction/review/posting, fuel, timeline and reversal records with permission/RLS/audit contracts.

- `migrations/20260930000000_axiom_security_hardening.sql`
  - AAL2 MFA enforcement for privileged memberships, calculation/expense/proof bounds, row-locking and direct snapshot-mutation protection.
  - Tenant-scoped constraints and security-definer RPC parity for the local validation rules.

- `migrations/20260930010000_corporate_account_policy_foundation.sql`
  - Corporate account connection/setup snapshots, immutable copied price-book/item evidence and activation readiness.
  - Explicit employee-admin/booker/passenger entitlements and visibility scopes.
  - Versioned lead-time, cancellation, approval, supplier, allotment, duty-slip and master-data contracts.
  - Hashed passenger action links, 48-hour auto-approval RPC, evaluation evidence, idempotency and tenant RLS.
  - PostgreSQL booking/duty write guards: `pending_approval` status, scope/SLA/entitlement enforcement, atomic pending approval rows and delete protection for direct PostgREST callers.

- `migrations/20260930020000_operations_parity_slice.sql`
  - Bulk, itinerary and monthly booking batches with row-level outcomes.
  - Deterministic allotment decisions and driver/vehicle capacity evidence.
  - Unified duty closures, evidence bundles and the driver-safe `submit_duty_closure` RPC.

- `migrations/20260930030000_finance_reporting_parity_slice.sql`
  - Invoice-generation runs, overdue dunning actions, saved report definitions and export profiles.
  - `generate_invoice_run` and `run_dunning_run` transaction boundaries with tenant RLS.

- `migrations/20260930040000_communications_parity_slice.sql`
  - Versioned tenant templates, allow-listed placeholders, suppressions, dispatch idempotency and delivery evidence.
  - `queue_communication_dispatch` and `record_communication_delivery` RPC boundaries.

- `migrations/20260930050000_supplier_fleet_finance_slice.sql`
  - Supplier purchases, fuel, petty cash, driver allowances, payroll lines and supplier settlements.
  - `generate_payroll_run` and `generate_supplier_settlement` transaction boundaries with tenant RLS.

- `migrations/20260930060000_feedback_recovery_slice.sql`
  - Versioned feedback forms, expiring request records, response sentiment and service-recovery actions.
  - `create_feedback_form` and `submit_feedback_response` transaction boundaries.

The P0 and Phase 1/2 browser mappings live in `supabase/client.js`. Reads use tenant-scoped PostgREST collections; cross-aggregate lifecycle commands are sent to authenticated `p0-orchestrator` and `phase12-orchestrator` Edge Function boundaries so publish, activation, evidence closure, scorecard and reconciliation commands can remain atomic in production. The Edge Function deployments and their RPC/transaction implementations are still release gates; this workspace does not claim a live Supabase deployment.

## Edge function

`functions/calculate-duty/index.ts` is the production calculation path for the current paise-exact engine. Deploy it after the migration with `supabase functions deploy calculate-duty`; it validates the caller's session and persists the snapshot through `save_duty_calculation`. Its business ceilings must remain aligned with `domain_engine.py` and the hardening migration.

`functions/webhook-gateway/index.ts` is the production ingress boundary for normalized payment, SMS, email, WhatsApp and telephony events. Deploy it with `supabase functions deploy webhook-gateway`, set `AXIOM_*_WEBHOOK_SECRET` values in Supabase, and configure each provider's canonical signing contract before enabling delivery. It rejects missing/invalid/stale signatures and records verified events idempotently with the service role; it is not a browser endpoint.

`functions/feedback-delivery-webhook/index.ts` is the feedback-specific receipt boundary. It requires a five-minute HMAC-signed timestamp, accepts SMS, email and WhatsApp delivery events, deduplicates provider event IDs, records the provider event, updates the latest delivery attempt, and schedules bounded retries for transient failures while treating bounces and exhausted failures as terminal. Deploy it with `supabase functions deploy feedback-delivery-webhook`; configure `AXIOM_SMS_WEBHOOK_SECRET`, `AXIOM_EMAIL_WEBHOOK_SECRET` and `AXIOM_WHATSAPP_WEBHOOK_SECRET` (the shared `AXIOM_PROVIDER_WEBHOOK_SECRET` exists only as a migration-compatible fallback).

`functions/phase12-orchestrator/index.ts` is the authenticated Phase 1/2 boundary used by `supabase/client.js`. It covers the unified registry (including import/export), rosters/live board/ETA and idempotent bulk refresh, safety evidence/closure approvals, Network activation/replacements/scorecards/reconciliation, saved views, permission bundles, mobile home and provider configuration/events. It uses the caller bearer token and anon key so RLS and `has_permission` remain in force; it does not contain service-role credentials. Deploy it with:

```bash
supabase functions deploy phase12-orchestrator
```

`functions/corporate-orchestrator/index.ts` is the authenticated corporate setup/policy boundary used by the browser adapter. It enforces organization resolution, account permissions, setup snapshots, entitlement rows, server-side lead-time/cancellation/approval evaluation, versioned masters, versioned allotment-rule reads/writes, signed duty-slip issuance and deterministic allotment checks. Deploy it with:

```bash
supabase functions deploy corporate-orchestrator
```

`functions/operations-orchestrator/index.ts` is the authenticated boundary for bulk/itinerary/monthly intake, availability, actual allotment and driver-safe closure submission. Deploy it after the operations parity migration:

```bash
supabase functions deploy operations-orchestrator
```

`functions/finance-reporting-orchestrator/index.ts` is the authenticated
boundary for invoice runs, ageing, dunning and saved reports. Deploy it after
the finance/reporting migration:

```bash
supabase functions deploy finance-reporting-orchestrator
```

`functions/communications-orchestrator/index.ts` is the authenticated boundary
for tenant templates, suppression and idempotent dispatch. Deploy it after the
communications migration:

```bash
supabase functions deploy communications-orchestrator
```

`functions/supplier-fleet-finance-orchestrator/index.ts` is the authenticated
boundary for supplier purchases, fuel, petty cash, allowances, payroll and
settlements. Deploy it after the supplier/fleet finance migration:

```bash
supabase functions deploy supplier-fleet-finance-orchestrator
```

`functions/feedback-orchestrator/index.ts` is the authenticated boundary for
feedback forms, requests, responses and service recovery. Deploy it after the
feedback migration:

```bash
supabase functions deploy feedback-orchestrator
```

`functions/enterprise-orchestrator/index.ts` is the authenticated enterprise
control boundary for company/sister-company hierarchy, multi-company billing,
SSO configuration, plans and usage, passenger portal tokens, availability,
half-hour quotes, multi-supplier allotment, OTPs, execution profiles, signed
media, printable duty slips, adjustments and closure jobs. It also contains the
service-role-controlled token-only passenger booking and SMS closure paths.
Deploy it after the enterprise migration:

```bash
supabase functions deploy enterprise-orchestrator
```

Schedule `/api/duty-closure-jobs/run` through a protected worker every few
minutes. The worker processes notification retries and the corporate 48-hour
auto-approval boundary; configure `AXIOM_DUTY_EVIDENCE_BUCKET` and create the
private `duty-evidence` bucket before enabling real media uploads.

The 48-hour worker calls `corporate_auto_approve_duty_slips`; signed action tokens are hashes only in `corporate_duty_slip_approvals`. `functions/corporate-duty-slip-action/index.ts` is the public token-only passenger action endpoint backed by the security-definer `corporate_signed_duty_slip_action` RPC. Configure its signed-link delivery URL and scheduled invocation before enabling passenger close-out in production.

The local SQLite handler remains the fallback when Supabase is not configured. The function's provider responses are mock-mode contracts until project secrets and real provider workers are configured.

## Apply to a Supabase project

1. Create a Supabase project in the intended region.
2. Enable the Auth providers required for the first release.
3. Install the Supabase CLI and authenticate it.
4. Link the local directory to the Supabase project.
5. Apply the migration:

```bash
supabase db push
```

The exact project ref and credentials must be supplied by the project owner; they are intentionally not stored in this repository.

## Auth metadata contract

When creating a user with Supabase Auth, include these metadata keys so the profile trigger can initialize the profile:

```json
{
  "full_name": "Your Full Name",
  "phone": "Your phone number",
  "account_type": "vendor"
}
```

Allowed account types are `vendor`, `driver` and `corporate`. Persist the selected browser-supported IANA time zone in `profiles.timezone` after the account-specific RPC (for example, `Asia/Kolkata`); the browser adapter does this during signup and settings updates.

After a vendor or corporate user has a valid authenticated session, call the `create_organization` RPC to create the organization, default branch and owner membership atomically. For an independent driver, call `create_driver_profile`. Organization operators can call `create_invitation` to generate a hashed, expiring one-time token; the invited Auth user then calls `accept_invitation` from the matching email account to create the active membership.

## Security notes

- Set the Edge Function secret `AXIOM_ALLOWED_ORIGIN` (or the first value of `AXIOM_ALLOWED_ORIGINS`) to the exact deployed Axiom Fleet web origin before exposing the browser adapter. The shipped functions do not use wildcard CORS; unset configuration intentionally disables browser cross-origin access.
- Supabase Auth owns password hashing, access tokens and refresh tokens.
- Application tables are protected with RLS; the client must never send a tenant ID as an authority claim.
- Service-role keys must stay server-side and must never be placed in the browser.
- Apply the additive security hardening migration after the bill-intelligence migration and run the RLS assertions with AAL1 and AAL2 test sessions; privileged owner/admin/platform sessions intentionally fail closed without MFA.
- Storage buckets, Edge Functions, email templates, provider secrets, scheduled jobs and production observability still need project-level configuration.
- Provider webhook secrets are not credentials to place in the frontend. Payment, SMS, email, WhatsApp and telephony providers must be configured against the signed `webhook-gateway` path (and the feedback receipt boundary where applicable) with a five-minute replay window and provider-specific canonicalization tests.
- The migration is a foundation and still needs a Supabase security review before production data is loaded.

## Follow-on finance, reporting and feedback slice

`migrations/20260930080000_finance_reporting_feedback_followon.sql` is the additive follow-on for supplier/fleet finance, configurable reporting/imports and public feedback. It adds payment requests, advances, settlement approvals, driver payouts, bank-file payroll exports, statutory deduction reports, fuel stations/prices, petty-cash and supplier/customer reconciliations, report-builder configurations/favourites/export jobs, import preview jobs and token-only feedback links/notifications/analytics/corrective actions. It creates private `report-exports` and `payroll-exports` buckets and the security-definer `submit_public_feedback` RPC. Tally/Tally Prime formats are deliberately excluded.

Deploy the authenticated boundary after the migration:

```bash
supabase functions deploy finance-controls-orchestrator
supabase functions deploy feedback-orchestrator
supabase functions deploy feedback-public
```

`finance-controls-orchestrator` is the provider-neutral boundary for finance approvals, mock bank execution, fuel variance/efficiency reads, payroll bank CSVs, statutory reports, configurable profitability/pricing/bill-to-duty reports, row-level import validation and private signed export uploads. `feedback-orchestrator` adds public-link issuance, notification queue records, analytics trends and corrective-action reads/writes to the authenticated feedback boundary. `feedback-public` is unauthenticated by design: it accepts only a raw token, returns form metadata, and delegates the single-use write to `submit_public_feedback`; it must have `SUPABASE_SERVICE_ROLE_KEY` configured server-side and must never expose organization membership data.

Large exports are intended to be asynchronous jobs stored in private object storage with short-lived signed URLs. A production worker should retry `feedback_notifications`, finalize queued report jobs and reconcile provider/bank outcomes. Real bank, payroll, SMS/email and object-storage credentials, plus Tally/Tally Prime integration, remain release-gated or explicitly out of scope.

## Indecab parity completion contracts

Apply `migrations/20261001000000_gap_completion_contracts.sql` after the existing parity migrations, then deploy `functions/gap-completion-orchestrator`. It owns the additive passenger booking request, availability, route/location evidence, Driver readiness/alerts, provider configuration, tokenized auto-collect, invoice automation, lifecycle sync, closed Network supplier exchange and expense budget/forecast routes. The browser adapter routes these contracts through the function when Supabase is enabled and keeps SQLite as the local fallback.

The function intentionally returns `mock`, `sandbox` or `edge_adapter_pending` status until the relevant provider credential reference, signed callback path and production validation are configured. It is not a claim of live Google, messaging, telephony, payment, HRMS, GPS, storage or e-invoice connectivity. Native Passenger rollout remains gated on physical Driver device validation and the two-fleet pilot.

## Exception-first workspace action center

Apply `migrations/20261001010000_workspace_action_center.sql` after the parity completion migration, then deploy `functions/workspace-orchestrator`. It adds a small per-user `workspace_action_states` table and the `operations.action_center` permission. The Edge function projects pending approvals, unassigned bookings, incomplete duties, Driver device blockers, open safety alerts, stale GPS evidence, unpaid invoices and missing duty proof into an explainable queue. It supports `GET /api/workspace/next-actions` and `POST /api/workspace/next-actions/{action_id}/status` for acknowledge, snooze, resolve and reopen state.

The action center is intentionally a projection over canonical records, not a second trip ledger. The browser adapter uses the authenticated Edge boundary when Supabase is enabled; the local fallback uses the same contract and remains safe for pilot preview. Its queue is designed as an ease-of-operation differentiator: every item gives the operator the reason, the next recovery step and a direct destination instead of requiring them to search a dashboard.
