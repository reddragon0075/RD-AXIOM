# Axiom Fleet action center and ease-of-operation slice

**Date:** 1 October 2026  
**Product decision:** Make Axiom Fleet the easier, more trustworthy alternative to feature-heavy car-rental back offices.

## Why this slice exists

Feature parity alone does not create a better product. Dispatchers and corporate travel teams should not have to remember which menu contains an approval, an unassigned booking, a stale device, a missing duty proof or an unpaid invoice. Axiom Fleet now turns those states into one explainable, tenant-scoped action queue.

The queue is intentionally different from a KPI wall:

- **Exception first:** show the next decision before aggregate metrics.
- **Explainable:** every item states why it exists, which source record produced it and what to do next.
- **Safe:** it never creates a parallel trip ledger, guesses a live location or exposes provider/payment secrets.
- **Recoverable:** an operator can open the source workflow, acknowledge ownership, snooze with a server-side expiry or resolve the queue item while the source record remains auditable.
- **Role-aware:** driver actions are restricted to the signed-in driver's assigned records; vendor and corporate operators see their tenant projection.
- **Honest:** an empty queue means no open action was returned by the current tenant response, not that a synthetic success metric was inserted.

## Contract

### `GET /api/workspace/next-actions?limit=12`

Returns:

- `items[]`: `id`, category, priority, title, why, next step, page, entity/source identity, due time, blocking state, signals and per-user state;
- `summary`: open, critical, high, blocking and acknowledged counts, contract version and generation time;
- `total_available`: count before the response limit.

The current local projection covers:

1. pending passenger/employee booking requests;
2. bookings without an active duty assignment;
3. duties missing a driver or vehicle;
4. Driver device readiness blockers and missing checks;
5. open Driver safety alerts;
6. stale GPS on active duties without claiming a position;
7. outstanding issued invoices;
8. completed duties without proof evidence;
9. incomplete tenant setup;
10. missing provider health validation.

### `POST /api/workspace/next-actions/{action_id}/status`

Body:

```json
{
  "status": "acknowledged | snoozed | resolved | reopened",
  "snooze_until": "2026-10-01T14:00:00Z",
  "note": "Dispatcher owns this before the morning shift"
}
```

Action state is per user and tenant. Resolving the action does not mutate the booking, duty, invoice, alert or proof record; the source workflow remains the place where the underlying operational state changes.

## Implementation

- Local SQLite: `backend_command_center.py`.
- Local server wiring: `server.py`.
- Local behavior coverage: `command_center_smoke_test.py`.
- Static parity coverage: `command_center_contract_test.py`.
- Supabase migration/RLS/audit: `supabase/migrations/20261001010000_workspace_action_center.sql`.
- Supabase authenticated Edge boundary: `supabase/functions/workspace-orchestrator/index.ts`.
- Browser adapter: `supabase/client.js`.
- Browser surface: Axiom action center on vendor and corporate Overview pages in `index.html`.
- Published contract: `openapi.yaml`.

## Product advantage beyond parity

Indecab comparison work identified a mature set of configuration and operational workflows. Axiom Fleet should close those gaps without copying its interface or creating configuration fatigue. The action center is the first layer of that advantage. The next product improvements should preserve the same rule: turn complexity into guided decisions, not more navigation.

Recommended follow-ons:

1. Add role-specific action playbooks that resolve an action through the correct existing workflow.
2. Add an operator command palette that searches action titles, source records and safe next steps.
3. Add saved action filters for branch, customer, driver, supplier and severity.
4. Add Realtime invalidation with polling fallback after the Supabase project is deployed.
5. Measure time-to-first-booking, time-to-allotment, duty-start errors, action-resolution time and offline recovery in the Bengaluru two-fleet pilot.

The production boundary remains explicit: Supabase migration/RLS, Edge deployment, provider credentials, physical Android validation and the two-fleet pilot must pass before production connectivity or Passenger native rollout is claimed.
