# Axiom Fleet operational parity slice

This slice adds the first post-corporate-foundation operating workflows:

- bulk, itinerary and monthly booking batches with row-level outcomes;
- deterministic availability checks for drivers and vehicles;
- actual allotment that creates a duty and capacity holds;
- unified duty closure with odometers, evidence completeness and attachments;
- idempotent replay and tenant-scoped audit evidence.

Local routes are implemented in `backend_operations_parity.py`. Production uses
`supabase/functions/operations-orchestrator/index.ts` and
`supabase/migrations/20260930020000_operations_parity_slice.sql`.

## Routes

- `GET/POST /api/bookings/batches`
- `GET /api/bookings/batches/:batch_id`
- `POST /api/bookings/batches/:batch_id/cancel`
- `POST /api/availability/evaluate`
- `POST /api/bookings/:booking_id/allot`
- `GET /api/allotment/decisions`
- `POST /api/duties/:duty_id/close`
- `GET /api/duties/:duty_id/closure`
- `POST /api/duties/:duty_id/closure/evidence`

Corporate booking database guards remain authoritative for active corporate
accounts. The production closure path uses `submit_duty_closure`, allowing a
linked driver to submit a final bundle without broad direct duty-update access.

Validation: `python3 operations_parity_smoke_test.py`.
