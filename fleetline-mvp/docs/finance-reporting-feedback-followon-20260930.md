# Axiom Fleet follow-on finance, reporting and feedback slice

This additive slice extends the existing Axiom Fleet hybrid UI without creating a parallel app surface. The local adapter remains dependency-free; Supabase is the production boundary.

## Delivered controls

- Supplier payment requests, advances, settlement approval and mock bank execution.
- Driver payout approval/disbursement with maker-checker state.
- Bank-file payroll CSV exports and statutory deduction/compliance reports.
- Fuel-station masters, append-only price history, variance and vehicle-efficiency analytics.
- Petty-cash and supplier/customer reconciliation records.
- Report builder filters for customer, supplier, city, branch, company and vehicle group.
- Saved report favourites and refresh, supplier/complete-vehicle profitability, customer/supplier pricing and bill-to-duty report types.
- Async private exports with signed URLs. CSV and JSON are supported; Tally/Tally Prime formats are intentionally skipped.
- Rich driver, vehicle, duty, customer, supplier and fuel-station import templates.
- Import validation preview, row-level correction, revalidation and commit actions in the Finance UI.
- Public passenger feedback links, anonymous/token-only submission, delivery queue processing, trend analytics and negative-feedback corrective-action routing.
- Immutable canonical duty evidence bundles containing closure, closure evidence, signed media references and adjustments.

## Production artifacts

- `supabase/migrations/20260930080000_finance_reporting_feedback_followon.sql`
- `supabase/migrations/20260930070000_enterprise_booking_evidence_slice.sql`
- `supabase/functions/finance-controls-orchestrator/index.ts`
- `supabase/functions/feedback-orchestrator/index.ts`
- `supabase/functions/feedback-public/index.ts`
- `supabase/functions/enterprise-orchestrator/index.ts`
- `supabase/client.js`
- `openapi.yaml`

Deploy the migrations before the functions. Configure `SUPABASE_SERVICE_ROLE_KEY` only as an Edge Function secret for private object-storage upload/signed URL operations and the token-only public feedback function. Create or retain the private `report-exports`, `payroll-exports` and `duty-evidence` buckets. A production worker should retry `feedback_notifications`, finalize/reconcile export jobs and record bank/provider outcomes.

The workspace does not claim that Supabase migrations, Edge Functions, object storage, bank providers, payroll providers or notification credentials have been deployed. Those remain release gates.
