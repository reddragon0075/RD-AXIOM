# Legacy Rental Platform parity completion slice

Date: 2026-10-01

This slice closes the remaining local/Supabase contract gaps identified in the Legacy Rental Platform comparison. Tally/Tally Prime export is explicitly excluded.

## Implemented contracts

- Employee/passenger booking requests, corporate book-for-others approval and idempotent replay.
- Deterministic availability evaluation with optional driver/vehicle auto-assignment.
- Background route logs, location-point evidence, route distance summary and expiring passenger live-location shares.
- Driver alert policies/events, acknowledgement/resolution, localized guidance metadata and push-queue integration.
- Driver device-readiness matrix for push, background location, media and notification permissions.
- Provider connection configuration and health checks with secret redaction; Google Places-compatible search, navigation and masked click-to-call adapter contracts.
- Tokenized payment authorization, auto-collect attempts and provider-neutral reconciliation records.
- Invoice automation policy/run boundary and deterministic three-month corporate expense forecast plus budgets.
- HRMS, passenger-lifecycle and corporate-provisioning sync acceptance contracts.
- Closed B2B/invite-only Network supplier exchange for qualification, contract and rate-card payloads.
- Enterprise custom-field value upsert contract, complementing existing field definitions/company profile/signature administration.
- Supabase migration, RLS-scoped tables, Edge orchestration and browser adapter routing.
- OpenAPI path/schema entries and `gap_completion_smoke_test.py` regression coverage.

## Provider and release interpretation

The local adapters return deterministic mock/sandbox contracts. They do not claim live Google, messaging, telephony, payment, HRMS, GPS, storage or e-invoice connectivity. Production status becomes valid only after a credential reference is configured, the provider adapter is deployed, signed callbacks are verified and the relevant end-to-end validation passes.

The following remain release gates rather than workspace claims:

1. Apply and validate the Supabase migration and RLS policies in a real project.
2. Configure real push credentials and validate Android background-location/media behavior on physical devices.
3. Configure production object storage and signed URL retention/expiry policy.
4. Validate one real HRMS/GPS/maps/messaging/payment/e-invoice adapter with replay and failure tests.
5. Complete the two-fleet Bengaluru pilot and operational safety review.
6. Do not begin Passenger native-app rollout before the Driver physical-device matrix and pilot gate is complete. Passenger web/PWA/API foundations are implemented here.
