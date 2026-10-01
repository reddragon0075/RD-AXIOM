# Axiom Fleet supplier and fleet finance parity slice

This additive slice covers the finance workflows between duty completion and
settlement:

- supplier purchase duties and supplier bill ageing;
- supplier settlement statement generation;
- vehicle fuel entries with normalized millilitre quantities and receipt evidence;
- petty cash credits/debits;
- driver allowances with period and evidence metadata;
- payroll runs with allowance aggregation, deductions and idempotent replay.

## Routes

- `GET/POST /api/supplier-purchases`
- `GET /api/supplier-ageing`
- `GET /api/supplier-settlements`
- `POST /api/supplier-settlements/generate`
- `GET/POST /api/fuel-entries`
- `GET/POST /api/petty-cash/entries`
- `GET/POST /api/driver-allowances`
- `GET/POST /api/payroll/runs`
- `GET /api/payroll/runs/:id/lines`

Local fallback: `backend_supplier_finance.py` and
`supplier_finance_smoke_test.py`. Production artifacts:

- `supabase/migrations/20260930050000_supplier_fleet_finance_slice.sql`
- `supabase/functions/supplier-fleet-finance-orchestrator/index.ts`

Payroll and settlement generation use security-definer RPC boundaries in
Supabase. Statutory payroll deductions, bank-file export, supplier payment
gateway execution and tax-provider integrations remain production-specific
configuration and release gates.
