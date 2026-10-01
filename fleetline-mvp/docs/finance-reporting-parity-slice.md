# Axiom Fleet finance and reporting parity slice

This additive slice completes the first production-oriented finance/reporting
workflow after operations closure:

- invoice generation runs for completed duties (`per_duty`, `monthly`, `cover`,
  and `proforma`) with deterministic idempotency;
- overdue invoice ageing buckets and provider-backed dunning actions;
- saved report definitions for ageing, duty counts, customer summaries and
  vehicle profitability;
- tenant-scoped CSV/JSON export profiles and reviewable ledger output (Tally/Tally Prime formats are explicitly out of scope);
- Supabase RPC boundaries for invoice generation and dunning so the browser
  never performs a partial multi-write ledger operation.

## Routes

- `POST /api/invoices/generate`
- `GET /api/invoice-runs`
- `GET/POST /api/collections/dunning` and `POST /api/collections/dunning/run`
- `GET /api/reports/ageing`
- `GET/POST /api/reports/definitions`
- `POST /api/reports/definitions/:id/run`
- `GET/POST /api/export-profiles`
- `POST /api/export-profiles/:id/run`

Local fallback: `backend_finance_parity.py` and
`finance_reporting_smoke_test.py`. Production artifacts:

- `supabase/migrations/20260930030000_finance_reporting_parity_slice.sql`
- `supabase/functions/finance-reporting-orchestrator/index.ts`

The messaging provider remains a mock adapter until real credentials and
provider delivery callbacks are configured. Invoice issuance and e-invoicing
remain subject to the existing billing/tax release gates.
