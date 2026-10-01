# Network security and privacy baseline

- All `/api/network/v1` routes require an authenticated vendor or corporate organization-linked session.
- Buyer records are scoped by `organization_id`; vendor access is granted only through an eligible buyer-owned vendor profile/candidate link.
- Invite-only partner onboarding is enforced server-side; there is no public vendor registration or anonymous lead resale.
- Driver roles cannot manage Network programs, quotes, awards, contracts or settlements.
- Buyer quote list responses omit payload, assumptions and line-item amounts until the buyer creates an immutable comparison snapshot. Vendors can read only their own quote surface.
- Requirement, quote, comparison, award, contract, SLA, check, service-order, scorecard and settlement transitions are audited and version-snapshotted.
- Passed activation checks, scorecards and settlements require evidence.
- Exact employee addresses, bank details and unrelated tenant data are not copied into generic Network responses.
- Supabase production uses RLS, membership/permission helpers and security-definer mutation RPCs. The browser never receives a service-role key.
- Privileged `vendor_owner` and `corporate_admin` memberships require a Supabase Auth `aal2` session through `mfa_satisfied_for_role`; operators and drivers retain their scoped access model.
- Deployment headers are declared in `vercel.json`: restrictive CSP, `frame-ancestors 'none'`, `X-Frame-Options: DENY`, `nosniff`, HSTS, referrer and permissions policies. The local boundary emits the corresponding clickjacking/content protections.
- `supabase/migrations/20260930000000_axiom_security_hardening.sql` rechecks calculation, expense and proof ceilings in SQL, protects `calculation_snapshot` from direct table mutation, adds constrained expense/proof checks and preserves row locking in `save_duty_calculation`.
- Driver expense categories, paise amounts, notes and OTP proof values are bounded in the PWA and revalidated by the local API/RPC; browser validation is not treated as an authorization boundary.
- Production payment, SMS, email, WhatsApp and telephony ingress uses the `webhook-gateway` Edge Function with per-provider HMAC-SHA256 secrets, replay timestamps, constant-time comparison, tenant identity and idempotent `webhook_events` recording. Feedback delivery receipts additionally pass through `feedback-delivery-webhook`, which requires a signed timestamp, deduplicates provider event IDs, and bounds retry scheduling. Provider-specific canonicalization still must be configured before enabling a real provider.

Before production: perform a formal RLS review, object-storage signed URL review, retention/deletion review, vendor contract/DPA review, threat-led penetration testing and two-fleet pilot acceptance. Configure Supabase MFA enrollment/recovery and provider-specific webhook secrets/signature canonicalization; provider credentials, real push and production storage are release gates.
