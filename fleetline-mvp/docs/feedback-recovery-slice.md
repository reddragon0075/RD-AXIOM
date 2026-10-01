# Axiom Fleet feedback and service-recovery parity slice

This slice adds the post-duty customer feedback loop:

- configurable, versioned feedback forms and question types;
- publish/archive lifecycle for forms;
- duty/booking-linked feedback requests with hashed action tokens;
- required-answer validation, rating, tags and derived sentiment;
- idempotent response submission;
- service-recovery actions with owners, due dates and resolution evidence;
- tenant-scoped response summaries.

## Routes

- `GET/POST /api/feedback/forms`
- `POST /api/feedback/forms/:id/publish`
- `POST /api/feedback/forms/:id/archive`
- `POST /api/feedback/requests`
- `POST /api/feedback/requests/:id/submit`
- `GET /api/feedback/responses`
- `GET /api/feedback/summary`
- `GET/POST /api/feedback/recovery`
- `POST /api/feedback/recovery/:id/resolve`

Local fallback: `backend_feedback.py` and `feedback_smoke_test.py`. Production
artifacts:

- `supabase/migrations/20260930060000_feedback_recovery_slice.sql`
- `supabase/functions/feedback-orchestrator/index.ts`

The current boundary is authenticated for the operator console. A production
passenger-facing link exposes only a narrowly scoped, expiring token endpoint
and delegates the single-use write to the security-definer RPC rather than
bypassing tenant RLS.

Feedback delivery is provider-neutral until credentials are configured. The
operator boundary queues SMS, email and WhatsApp notifications and records
attempts. `feedback-delivery-webhook` accepts only timestamped HMAC callbacks
for those channels, deduplicates provider event IDs, records delivery/bounce
receipts and schedules bounded retries for transient failures. Hard bounces and
exhausted retries are terminal/dead-lettered. Configure the three channel
secrets and provider-specific canonicalization before enabling production
callbacks; the local adapter remains deterministic and mock-labelled.
