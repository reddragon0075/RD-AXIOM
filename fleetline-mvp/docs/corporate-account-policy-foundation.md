# Axiom Fleet corporate account and policy foundation

**Implemented 30 September 2026 · local fallback plus Supabase production boundary**

This slice closes the principal corporate-account gap identified in the Legacy Rental Platform comparison without opening Axiom Network registration or inventing operational data. It is additive to the existing hybrid console and keeps the current tenant/auth/audit/idempotency contracts.

## Delivered contracts

| Capability | Local route | Production boundary |
|---|---|---|
| Connect and setup | `GET/POST/PATCH /api/corporate/account`, `POST /api/corporate/account/setup` | `corporate-orchestrator` + `corporate_accounts` |
| Activation guard | `POST /api/corporate/account/activate` | RLS permission + orchestrator transition |
| Employee/admin/booker entitlements | `GET/POST/PATCH /api/corporate/users` | `corporate_account_users` |
| Visibility | `POST /api/corporate/visibility/evaluate` | server-side policy evaluation |
| Booking/cancellation policy | `GET/POST/PATCH /api/corporate/policies`, `POST /api/corporate/policies/evaluate` | `corporate_policies` + Edge evaluation |
| Approval routing | policy `approval_route`, `approval_required` and explainable `needs_approval` result | policy JSONB, evaluation evidence |
| Supplier/allotment | `GET/POST /api/corporate/allotment/rules`, `POST /api/corporate/allotment/evaluate` | `corporate_allotment_rules` |
| Passenger duty-slip | `POST /api/corporate/duty-slip-approvals`, signed `/action` route, approve/reject, auto-approve | hashed link token + `corporate_auto_approve_duty_slips` RPC |
| Versioned masters | `GET/POST /api/corporate/masters`, `GET/PATCH /api/corporate/masters/:id` | `corporate_masters` |

All corporate routes are organization-scoped. The local handler uses the authenticated organization ID on every query, and the Supabase migration uses RLS plus permission functions. No public vendor registration, marketplace behavior, anonymous lead resale, autonomous Network awards or escrow is introduced.

## Setup snapshot behavior

`POST /api/corporate/account/setup` records:

- connection type and external account reference;
- account/customer linkage where the record belongs to the same tenant;
- explicit branch, customer entity, sister-company, city, vehicle-group, duty-type and company scopes;
- pricing scope, source price-book IDs and, when requested, an immutable copied price-book/item snapshot;
- a monotonically increasing setup version and actor/audit evidence.

Activation is a separate state transition. It requires a name and setup snapshot. The account response exposes a readiness object rather than implying that an empty tenant is configured.

## Entitlements and visibility

Account users have an explicit account type (`admin`, `employee_admin`, `booker_passenger`), permission profile, grants, denies, status and visibility scope. An explicit deny wins over a grant. Empty scope at a layer means unrestricted at that layer; a non-empty account, user or policy scope is an allow-list. The evaluator returns the exact layer and field that blocked a request. The corporate workspace now exposes direct access editing for grants/denies/visibility, plus versioned master and allotment-rule editors; all mutations remain tenant API calls rather than browser-only state.

## Policy evaluation

Booking evaluation returns:

- `allow` when no block or approval reason exists;
- `needs_approval` when the active policy route must decide;
- `block` for lead-time, cancellation-cutoff, scope, supplier or missing-policy violations;
- deterministic supplier candidates when auto-allotment is enabled, without assigning a supplier as a side effect.

Each evaluation stores a request hash, policy version, reasons and result in `corporate_policy_evaluations`. Lead-time and cancellation checks use the current UTC timestamp and an ISO scheduled time; missing timestamps are explained as blocks when the corresponding SLA is configured. Active local corporate accounts also enforce the evaluation at ordinary booking creation and cancellation writes: blocked requests return the explainable evaluation, approval-required bookings enter `pending_approval`, duty assignment cannot bypass that approval state, and approve/confirm/reject actions require the account user's `booking.approve` permission.

The production migration now installs the same write boundary in PostgreSQL. It adds the `pending_approval` booking state and scope columns, creates an atomic booking/approval-row trigger, enforces account-user entitlements and account/user/policy visibility, blocks lead-time and cancellation-cutoff violations, and rejects duty creation while approval is pending. The browser/Edge preflight remains for user-facing explanations; direct PostgREST callers cannot bypass the database trigger.

## Duty-slip state machine

A duty-slip request creates a pending record with:

- a cryptographically random action token returned once to the caller;
- only the SHA-256 token hash persisted;
- a seven-day action-link expiry;
- a policy-derived auto-approval deadline, defaulting to 48 hours;
- passenger action, comment, decision reason, decision time and audit record.

When an active policy enables passenger approval, completing a local duty with a booking `passenger_email` creates this request at the domain transition boundary; repeated completion/replay is idempotent. The explicit approval route remains available for imported or externally sourced duties. The local action route is public by design and needs the signed token, not a dashboard session. Replaying a decided link returns the final state and does not transition it again. `POST /api/corporate/duty-slip-approvals/auto-approve` provides the local/manual worker boundary; Supabase uses the corresponding scheduled RPC.

## Versioned masters and guards

Master writes never mutate an earlier version. Supported corporate kinds are duty types, vehicle groups, billing items, taxes, company scopes, pricing rules and document requirements. Allotment evaluation resolves suppliers in stable name/ID order and checks required vehicle documents for ownership, approved/valid status and expiry. Missing, pending, expired or uncheckable documents are blocking reasons; no resource is silently awarded.

## Validation

- `python3 corporate_foundation_smoke_test.py` — setup, immutable copied snapshot, idempotent replay, activation, entitlement, policy SLA, versioned master, signed passenger decision and document guard.
- `python3 regression_check.py` — `101/101 passed`.
- `node --check` against the inline `index.html` script — passed.
- `python3 supabase_contract_test.py` — production parity, RLS and database write-guard contracts passed.
- `node --check supabase/client.js` and Python compilation — passed.
- `git diff --check` — passed.

## Production release gates

Before production traffic, apply `supabase/migrations/20260930010000_corporate_account_policy_foundation.sql` (including the PostgreSQL booking/duty write guards), deploy `supabase/functions/corporate-orchestrator/index.ts` and `supabase/functions/corporate-duty-slip-action/index.ts`, configure the signed-link delivery/provider boundary and schedule the auto-approval RPC, test RLS and direct PostgREST writes with multiple organizations, and run the two-fleet pilot. Supabase deployment, real push/provider credentials, object storage, physical Android testing and the Driver matrix remain release gates. Passenger native work remains downstream of the Driver physical-device pilot.
