# Axiom Fleet — AI Bill Reading & Auto-Posting to Vehicles

Status: first implementation slice, local fallback complete, Supabase production parity scaffolded  
Date: 2026-09-29

## Product intent

AI Bill Reading is a protected **Finance / Workflow** capability. It turns supplier, fuel, maintenance, toll and insurance bill evidence into a reviewable structured record. It never bypasses a human confirmation when confidence is low, values conflict, a vehicle is ambiguous, or validation is blocking.

The bill-intelligence record is a derived evidence layer. Existing Axiom Fleet supplier bills, cost entries, fuel records and vehicle masters remain canonical. A posted bill links those canonical records back to the source file, extraction envelope, reviewer and audit event.

This slice is deliberately mock-first: local SQLite extracts from OCR text or structured test fields, and production Supabase uses the same authenticated route contract behind `bill-intelligence-orchestrator`. A vision/OCR provider can be added without changing the review or posting contract.

## Operator workflow

1. **Upload** from the protected Finance controls page. The request records filename, content type, source, storage reference, SHA-256 when available, uploader and an idempotency key.
2. **Extract** into strict fields: bill type, vendor/GSTIN, invoice number/date, registration, amount/tax, line quantity/rate, fuel type, odometer, insurance policy dates, maintenance due values and payment mode. Each field carries confidence and provenance.
3. **Validate** duplicate invoice/evidence, arithmetic and tax totals, date/quantity/rate consistency, positive totals, fuel/vehicle mismatch, registration candidates and odometer anomalies.
4. **Match** a vehicle using normalized registration exact match first, then fuzzy candidate match inside the same organization. A reviewer can select an explicit cab when OCR is missing or ambiguous.
5. **Review** the queue. The reviewer can correct fields, select a vehicle, add a note, reject the record, or approve it. Blocking errors remain visible rather than silently coercing values.
6. **Approve and post** idempotently. The system creates supplier-bill and vehicle-cost rows, creates a fuel entry for fuel bills, updates odometer/insurance/service compliance fields where applicable, and appends source-attributed vehicle timeline events.
7. **Undo / correct** with a reversal. The original evidence, postings, actor and reason remain in history; canonical rows are marked reversed/cancelled rather than deleted.

## Local contract

All local routes require the existing authenticated session and organization scope:

- `GET /api/bill-intelligence?status=all|draft|needs_review|posted|rejected|reversed`
- `POST /api/bill-intelligence`
- `GET /api/bill-intelligence/summary`
- `GET /api/bill-intelligence/{bill_id}`
- `POST /api/bill-intelligence/{bill_id}/review`
- `POST /api/bill-intelligence/{bill_id}/approve`
- `POST /api/bill-intelligence/{bill_id}/reject`
- `POST /api/bill-intelligence/{bill_id}/undo`
- `GET /api/bill-intelligence/vehicles/{vehicle_id}/timeline`

A capture body can include `filename`, `content_type`, `storage_reference`, `file_sha256`, `ocr_text`, optional structured `extracted` test fields, `vehicle_id`, `supplier_id`, `duty_id`, and `idempotency_key`.

`approve` accepts `vehicle_id`, optional `overrides`, and `note`. A replay after posting returns the original posting result. An `undo` replay returns the existing reversed result. Errors use the existing `{ok:false,error,code}` shape.

The OpenAPI representation is in `/openapi.yaml`; the path family is tagged `Finance`.

## Local storage model

`backend_bill_intelligence.py` initializes additive tables without changing the dependency-free preview contract:

- `bill_intelligence_records`: source metadata, OCR, strict extraction, confidence, validation, state and posting summary.
- `bill_intelligence_postings`: bill-to-canonical-entity links and reversal metadata.
- `bill_intelligence_fuel_entries`: quantity, rate, amount, odometer, mileage and anomaly code.
- `bill_intelligence_timeline`: vehicle events with `source` such as `ocr_bill`, `reviewer` or `manual`; fuel, `odometer_recorded`, compliance and reversal events remain source-attributed.

The initializer adds nullable/defaulted vehicle fields for current odometer, odometer timestamp, insurance policy number and service due values. It does not rename or remove existing tables.

## Supabase production parity

Migration: `supabase/migrations/20260929000000_axiom_bill_intelligence.sql`.

It creates the equivalent `public.bill_intelligence_*` tables, indexes, vehicle fields, permission keys, role grants, RLS policies, and optional `p0_audit_row()` triggers. RLS is organization-based and permission-based:

- `bill_intelligence.read`: tenant-scoped queue/detail/timeline reads.
- `bill_intelligence.upload`: source record creation.
- `bill_intelligence.review`: corrections, canonical postings and reversals.

The browser adapter routes the family to the authenticated Edge Function `supabase/functions/bill-intelligence-orchestrator/index.ts`. It never exposes a service-role key. The function resolves the caller's active organization from `organization_memberships` and supplies `organization_id` to every operation.

The current Edge Function is the production boundary and deterministic fallback contract. It performs authenticated extraction and review-state writes using the same field names. Its CORS policy is configured through the `AXIOM_ALLOWED_ORIGIN` Edge Function secret; wildcard CORS is intentionally not shipped. Before enabling autonomous provider writes, deploy the OCR/vision worker and move the approval-to-canonical posting sequence into a reviewed transaction or security-definer RPC. A provider failure must leave the evidence in `needs_review` and must not create a partial finance post.

Recommended production object-storage shape:

```text
bill-intelligence/{organization_id}/{yyyy}/{mm}/{bill_id}/{sha256-or-upload-id}.{extension}
```

Use a private bucket, signed short-lived read URLs, malware/type checks, size limits and retention policies. Store only the reference and hash in the bill row; do not put raw credentials or public file URLs in the browser.

## Tenant, permission and audit rules

- Vendor/operator organization scope is derived server-side; a client-supplied organization ID cannot grant access.
- Vehicle candidates are filtered by the caller's organization before fuzzy ranking.
- Supplier bill numbers are checked within the organization, not globally.
- Review, approve, reject and undo are staff/permissioned operations in the local handler and must map to `bill_intelligence.review` in Supabase.
- Approval emits an audit event and source-linked timeline events. Corrections are explicit field changes; reversal is a new event.
- Idempotency keys are unique per organization. Canonical posting checks existing bill state before creating downstream rows.
- Public Axiom Network routes, anonymous vendor registration, consumer marketplace behavior and financial escrow are not part of this feature.

## Release gates

Local acceptance is covered by `/home/user/fleetline-mvp/bill_intelligence_smoke_test.py`: fresh SQLite boot, demo login, tenant-scoped vehicle match, OCR extraction, review state, idempotent replay, canonical posting, timeline source attribution, second-tenant isolation and non-destructive undo.

Before production release, additionally require:

- Supabase migration applied and RLS/policy tests run with two organizations and driver/operator roles.
- Real private object storage, OCR/vision provider, malware checks and signed URL lifecycle configured.
- Atomic reviewed posting transaction/RPC with duplicate and replay tests.
- Authenticated Edge Function deployed with logs, rate limits and redacted trace IDs.
- Browser smoke test for upload, explicit vehicle fallback, low-confidence review, approve, reject and undo.
- Physical Android testing, real push credentials and the existing two-fleet pilot gates remain unchanged.
