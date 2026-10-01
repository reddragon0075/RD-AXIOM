# Axiom Fleet enterprise controls implementation

This additive slice extends the existing corporate account, operations parity and evidence foundations.

## Local fallback

- `backend_enterprise_controls.py` adds tenant-scoped company, sister-company, multi-company billing-profile, bank-account, tax-entity, billing-item, custom-field, profile/signature, plan, usage and SSO records.
- Invite-only passenger portal links use a one-time plaintext token response and hashed storage. Portal POST requests create `requested` bookings under the token tenant.
- Availability is computed from live vehicle, driver and duty assignments.
- Booking quotes calculate half-hour blocks, distance overage and copied-pricing metadata.
- Allotment requests, supplier responses and exception records remain tenant-owned.
- Duty execution profiles cover DCO, attached-driver, garage-to-garage and Network-driver sources. OTPs are hashed and short-lived. Media uses mock signed object paths until production storage is configured.
- Combined duty-slip documents include an HTML print-to-PDF rendering boundary, SMS closure action jobs include notification retry counters and 48-hour corporate approval processing, and credit/debit adjustments remain evidence-linked through the new routes.

## Production handoff

- `supabase/migrations/20260930070000_enterprise_booking_evidence_slice.sql` adds the corresponding records, RLS policies, permissions, quote RPC and closure worker RPC.
- `supabase/functions/enterprise-orchestrator/index.ts` is the authenticated Edge boundary plus the service-role-controlled public token boundary. It is intentionally provider-neutral until Supabase Auth SSO, object storage and SMS credentials are configured.
- `supabase/client.js` delegates supported enterprise routes to the Edge function while the local adapter remains dependency-free.

## UI

- `index.html` adds an Enterprise controls surface with guided setup/copy-scope wizard, hierarchy and master summaries, passenger portal issuance, company SSO boundary, availability calendar and duty evidence readiness cards.

Production gates remain unchanged: deploy Supabase migrations/functions, configure company-email SSO, SMS/notification retries, object storage, scheduled 48-hour worker, real media providers and complete the physical Android/two-fleet pilot.
