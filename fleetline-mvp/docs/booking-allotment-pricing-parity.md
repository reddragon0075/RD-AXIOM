# Booking, allotment and pricing parity slice

Date: 2026-09-30

The booking desk now has one additive contract in the local fallback and
Supabase production boundary. Existing `/api/bookings/batches`, direct
`/api/bookings/{id}/allot`, enterprise quote/request paths and invoice runs
remain available.

## Lifecycle

- `domain_bookings` / `public.bookings` carry `booking_type`, parent/group IDs,
  sequence, flat-rate amount, start/end, recurrence, confirmation state,
  advance total, allotment mode and pricing snapshot.
- `single`, `parent`, `child`, `flat_rate`, `monthly` and `multi_day` are
  accepted. Direct monthly and multi-day creates can generate child occurrences;
  existing bulk, itinerary and monthly batch modes now retain a durable group,
  type and sequence.
- Booking mutations are append-only in `domain_booking_actions` /
  `booking_action_events`. Create, confirm, split, print, briefing, advance,
  attachment, soft-delete, restore, import, export, dispatch, re-allot and
  arrival events are auditable. Request/action idempotency keys replay the
  original result.
- Delete is a soft lifecycle delete. No Tally/Tally Prime export is exposed.

## Allotment and execution

`POST /api/bookings/{id}/allot-all` applies a driver/vehicle or supplier path to
the booking and its child duties. `owned`, `company_supplier`, `dco` and
`network` are represented by `booking_dispatches` /
`domain_booking_dispatches`; Network remains invite-only B2B and this slice does
not create public marketplace discovery. A Network dispatch must reference an
active vendor profile whose buyer-owned invite is accepted and unexpired;
`network_vendor_profile_id` is persisted with the dispatch for response and
audit traceability.

- `POST /api/bookings/{id}/reallot` releases open duty locks and records a new
  attempt.
- `POST /api/bookings/{id}/dispatch` creates a supplier/DCO/Network response
  envelope; `POST /api/booking-dispatches/{id}/respond` records the response.
- `POST /api/duties/{id}/arrival` records an idempotent arrival event and
  dispatch state.
- Temporary passenger/allotment records have an explicit expiry and are marked
  `expired` on the next tenant-scoped request or maintenance pass.

## Pricing and surcharge

- `booking_pricing_contracts` / `booking_pricing_rules` are versioned and can
  scope to a customer or supplier, city, vehicle group and duty type.
- Quotes calculate flat/package base, included kilometres, extra kilometres,
  extra half-hour/hour blocks, waiting, allowance and configured extras.
  `auto_switch` thresholds can select a different duty type before the quote is
  persisted to the booking.
- `customer_fuel_surcharge_rules` plus `fuel_rate_history` calculate a contract
  fuel difference or percentage surcharge. Local invoice generation and the
  Supabase `generate_invoice_run` RPC add a separate `fuel_surcharge` invoice
  line and persist the surcharge amount in the invoice snapshot.

## Supabase handoff

The production boundary is `supabase/functions/booking-orchestrator` and is
mapped by `supabase/client.js`. Schema/RLS is additive in:

- `20260930100000_booking_allotment_pricing_parity.sql`
- `20260930101000_booking_invoice_fuel_surcharge.sql`

Production deployment still requires the stated release gates: Supabase
migration/function deployment, real object storage and push credentials,
physical Android testing, and the two-fleet pilot. Local smoke coverage is in
`booking_allotment_smoke_test.py`.
