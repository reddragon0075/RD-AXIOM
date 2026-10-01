# Axiom Fleet communications parity slice

This slice adds the tenant-managed communication control plane without
pretending provider credentials are configured:

- versioned SMS, email, WhatsApp and push templates;
- allow-listed placeholders and rendered payload evidence;
- recipient/channel suppression rules;
- idempotent provider dispatch records and delivery history;
- Supabase RPC boundaries for suppression and dispatch decisions.

## Routes

- `GET/POST /api/communications/templates`
- `POST /api/communications/dispatch`
- `GET /api/communications/deliveries`
- `GET/POST /api/communications/suppressions`

Local fallback: `backend_communications.py` and
`communications_smoke_test.py`. Production artifacts:

- `supabase/migrations/20260930040000_communications_parity_slice.sql`
- `supabase/functions/communications-orchestrator/index.ts`

DLT registration, WhatsApp BSP, email provider delivery callbacks, masked
calling and real push credentials remain release gates. The production
function is deliberately safe to deploy before those credentials: it records
queued/suppressed/idempotent work under tenant RLS rather than leaking a
browser-side provider secret.
