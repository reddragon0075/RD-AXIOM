#!/usr/bin/env python3
"""Static parity guard for the production Supabase foundation and browser adapter."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
migration = (ROOT / "supabase/migrations/20260919000000_axiom_fleet_foundation.sql").read_text()
network_migration = (ROOT / "supabase/migrations/20260922000000_axiom_network_mvp.sql").read_text()
bill_migration = (ROOT / "supabase/migrations/20260929000000_axiom_bill_intelligence.sql").read_text()
bill_function = (ROOT / "supabase/functions/bill-intelligence-orchestrator/index.ts").read_text()
security_migration_path = ROOT / "supabase/migrations/20260930000000_axiom_security_hardening.sql"
security_migration = security_migration_path.read_text() if security_migration_path.is_file() else ""
webhook_function_path = ROOT / "supabase/functions/webhook-gateway/index.ts"
webhook_function = webhook_function_path.read_text() if webhook_function_path.is_file() else ""
corporate_migration_path = ROOT / "supabase/migrations/20260930010000_corporate_account_policy_foundation.sql"
corporate_migration = corporate_migration_path.read_text() if corporate_migration_path.is_file() else ""
corporate_function_path = ROOT / "supabase/functions/corporate-orchestrator/index.ts"
corporate_function = corporate_function_path.read_text() if corporate_function_path.is_file() else ""
corporate_action_path = ROOT / "supabase/functions/corporate-duty-slip-action/index.ts"
corporate_action = corporate_action_path.read_text() if corporate_action_path.is_file() else ""
operations_migration_path = ROOT / "supabase/migrations/20260930020000_operations_parity_slice.sql"
operations_migration = operations_migration_path.read_text() if operations_migration_path.is_file() else ""
operations_function_path = ROOT / "supabase/functions/operations-orchestrator/index.ts"
operations_function = operations_function_path.read_text() if operations_function_path.is_file() else ""
finance_migration_path = ROOT / "supabase/migrations/20260930030000_finance_reporting_parity_slice.sql"
finance_migration = finance_migration_path.read_text() if finance_migration_path.is_file() else ""
finance_function_path = ROOT / "supabase/functions/finance-reporting-orchestrator/index.ts"
finance_function = finance_function_path.read_text() if finance_function_path.is_file() else ""
communications_migration_path = ROOT / "supabase/migrations/20260930040000_communications_parity_slice.sql"
communications_migration = communications_migration_path.read_text() if communications_migration_path.is_file() else ""
communications_function_path = ROOT / "supabase/functions/communications-orchestrator/index.ts"
communications_function = communications_function_path.read_text() if communications_function_path.is_file() else ""
supplier_finance_migration_path = ROOT / "supabase/migrations/20260930050000_supplier_fleet_finance_slice.sql"
supplier_finance_migration = supplier_finance_migration_path.read_text() if supplier_finance_migration_path.is_file() else ""
supplier_finance_function_path = ROOT / "supabase/functions/supplier-fleet-finance-orchestrator/index.ts"
supplier_finance_function = supplier_finance_function_path.read_text() if supplier_finance_function_path.is_file() else ""
feedback_migration_path = ROOT / "supabase/migrations/20260930060000_feedback_recovery_slice.sql"
feedback_migration = feedback_migration_path.read_text() if feedback_migration_path.is_file() else ""
feedback_function_path = ROOT / "supabase/functions/feedback-orchestrator/index.ts"
feedback_function = feedback_function_path.read_text() if feedback_function_path.is_file() else ""
followon_migration_path = ROOT / "supabase/migrations/20260930080000_finance_reporting_feedback_followon.sql"
followon_migration = followon_migration_path.read_text() if followon_migration_path.is_file() else ""
finance_controls_function_path = ROOT / "supabase/functions/finance-controls-orchestrator/index.ts"
finance_controls_function = finance_controls_function_path.read_text() if finance_controls_function_path.is_file() else ""
feedback_public_function_path = ROOT / "supabase/functions/feedback-public/index.ts"
feedback_public_function = feedback_public_function_path.read_text() if feedback_public_function_path.is_file() else ""
enterprise_migration_path = ROOT / "supabase/migrations/20260930070000_enterprise_booking_evidence_slice.sql"
enterprise_migration = enterprise_migration_path.read_text() if enterprise_migration_path.is_file() else ""
enterprise_function_path = ROOT / "supabase/functions/enterprise-orchestrator/index.ts"
enterprise_function = enterprise_function_path.read_text() if enterprise_function_path.is_file() else ""
p0_migration = (ROOT / "supabase/migrations/20260923000000_axiom_p0_foundations.sql").read_text()
client = (ROOT / "supabase/client.js").read_text()

tables = [
    "onboarding_states", "record_versions", "duplicate_matches", "supplier_bills", "cost_entries",
    "receipt_allocations", "payouts", "financial_actions", "approval_steps", "sla_events",
    "trip_shares", "passenger_ratings", "driver_preferences", "device_bindings", "calls", "sos_events",
    "practice_duties", "alerts", "geofences", "notification_events", "network_edges", "network_offers",
    "network_bids", "settlements", "report_exports", "report_views", "report_schedules", "consents",
    "retention_locks", "webhook_events", "booking_stops", "recurring_bookings", "capacity_locks",
    "billing_notes", "payment_links", "jobs", "auth_factors", "api_keys", "security_events",
]
route_markers = [
    "route === '/api/onboarding'", "route === '/api/tax/calculate'", "route === '/api/updates'",
    "supplier-bills", "driver-payouts", "financial-actions", "networkRoute", "route === '/api/reports/export'",
    "route === '/api/privacy/retention'", "route === '/api/admin/kpis'", "recurringRoute", "stopsRoute",
    "capacityRoute", "billing-notes", "payment-links", "jobRun", "supabase_auth_mfa", "api_keys",
]
missing_tables = [name for name in tables if f"public.{name}" not in migration]
missing_routes = [marker for marker in route_markers if marker not in client]
assert not missing_tables, f"missing migration tables: {missing_tables}"
assert not missing_routes, f"missing adapter routes: {missing_routes}"
assert "foreach t in array" in migration and "enable row level security" in migration, "extended tables must enable RLS"
assert "drop policy if exists" in migration and "create policy" in migration, "extended policy generation missing"
assert "supabaseDomainRequest" in client and "AxiomSupabaseAdapter" in client, "browser adapter missing"
p0_tables = [
    "p0_role_permissions", "p0_master_records", "p0_master_versions", "p0_sites", "p0_shifts",
    "p0_route_plans", "p0_route_stops", "p0_roster_assignments", "p0_replacements", "p0_safety_policies",
    "p0_safety_incidents", "p0_safety_actions", "p0_network_regions", "p0_network_vendor_approvals",
    "p0_network_quote_evaluations", "p0_network_metric_observations", "p0_network_scorecard_runs",
    "p0_network_disputes", "p0_network_corrective_actions", "p0_network_settlement_statements"
]
p0_routes = [
    "supabaseP0Request", "p0-orchestrator", "p0_master_records", "p0_route_plans",
    "p0_roster_assignments", "p0_safety_incidents", "p0_role_permissions"
]
assert all(f"public.{name}" in p0_migration for name in p0_tables), "P0 Supabase tables missing"
assert all(marker in client for marker in p0_routes), "P0 Supabase browser mappings missing"
assert "p0_audit_row" in p0_migration and "p0_role_permissions" in p0_migration, "P0 audit/permission foundation missing"
assert "network_requirements add column if not exists deadline_at" in p0_migration, "Network lifecycle deadline extension missing"
phase12_migration = (ROOT / "supabase/migrations/20260924000000_axiom_phase12_foundations.sql").read_text()
phase12_function = (ROOT / "supabase/functions/phase12-orchestrator/index.ts").read_text()
phase12_tables = [
    "phase12_events", "phase12_versions", "phase12_master_records", "phase12_roster_versions", "phase12_eta_snapshots",
    "phase12_safety_evidence", "phase12_closure_approvals", "phase12_network_replacements", "phase12_scorecard_formulas",
    "phase12_scorecard_disputes", "phase12_reconciliations", "phase12_permission_bundles", "phase12_saved_views",
    "phase12_bulk_jobs", "phase12_integrations", "phase12_integration_events",
]
phase12_routes = [
    "/api/masters/registry", "/api/mobile/home", "/api/operations/live-board", "/api/operations/bulk",
    "/api/safety/monitor", "/api/network/v1/scorecard-formulas", "/api/views", "/api/permissions/bundles",
    "/api/integrations/catalog",
]
assert all(f"public.{name}" in phase12_migration for name in phase12_tables), "Phase 1/2 Supabase tables missing"
assert all(marker in phase12_function for marker in phase12_routes), "Phase 1/2 Edge Function routes missing"
assert "organization_id is not null" in phase12_migration and "is_platform_user()" in phase12_migration, "Phase 1/2 tenant policy guard missing"
assert "idempotency_key" in phase12_function and "getUser" in phase12_function and "phase12_events" in phase12_function, "Phase 1/2 Edge Function security/idempotency boundary missing"
phase3_migration = (ROOT / "supabase/migrations/20260925000000_axiom_phase3_moat.sql").read_text()
phase3_function = (ROOT / "supabase/functions/phase3-orchestrator/index.ts").read_text()
phase3_tables = [
    "phase3_region_catalog", "phase3_emission_factors", "phase3_events", "phase3_predictive_alerts", "phase3_alert_feedback",
    "phase3_vendor_quality_snapshots", "phase3_vendor_quality_edges", "phase3_simulations", "phase3_variance_findings",
    "phase3_sustainability_trips", "phase3_sustainability_targets", "phase3_charging_stations", "phase3_regions", "phase3_exchange_rates",
]
phase3_routes = [
    "/api/phase3/predictive-alerts", "/api/phase3/vendor-quality/graph", "/api/phase3/simulations",
    "/api/phase3/variance/findings", "/api/phase3/sustainability/summary", "/api/phase3/sustainability/report",
    "/api/phase3/sustainability/trips", "/api/phase3/sustainability/charging-stations", "/api/phase3/sustainability/ev-eligibility",
    "/api/phase3/regions", "/api/phase3/localization", "/api/phase3/fx/convert", "/api/phase3/tax/preview",
]
assert all(f"public.{name}" in phase3_migration for name in phase3_tables), "Phase 3 Supabase tables missing"
assert all(marker in phase3_function for marker in phase3_routes), "Phase 3 Edge Function routes missing"
assert "phase3-orchestrator" in client and "supabasePhase3Request" in client, "Phase 3 browser boundary missing"
assert "has_permission" in phase3_migration and "organization_id is not null" in phase3_migration and "p0_audit_row" in phase3_migration, "Phase 3 RLS/audit guard missing"
assert "idempotency_key" in phase3_function and "getUser" in phase3_function and "predictive-v1" in phase3_function, "Phase 3 security/idempotency/model boundary missing"
assert "ev-eligibility" in phase3_function and "charging_station" in phase3_function and "sustainability-report-v2" in phase3_function, "Phase 3 EV/charging/report parity missing"
assert "ev_eligible" in phase3_migration and "energy_consumption_kwh_per_km" in phase3_migration and "available_ports" in phase3_migration, "Phase 3 additive EV vehicle/charging fields missing"
bill_tables = ["bill_intelligence_records", "bill_intelligence_postings", "bill_intelligence_fuel_entries", "bill_intelligence_timeline"]
bill_routes = ["/api/bill-intelligence", "/api/bill-intelligence/summary", "(review|approve|reject|undo)", "bill-intelligence\\/vehicles\\/"]
assert all(f"public.{name}" in bill_migration for name in bill_tables), "Bill intelligence Supabase tables missing"
assert all(marker in bill_function for marker in bill_routes), "Bill intelligence Edge Function routes missing"
assert "bill-intelligence-orchestrator" in client and "supabaseBillIntelligenceRequest" in client, "Bill intelligence browser boundary missing"
assert "bill_intelligence.read" in bill_migration and "bill_intelligence.review" in bill_migration and "organization_id is not null" in bill_migration, "Bill intelligence RLS/permission guard missing"
assert "idempotency_key" in bill_function and "getUser" in bill_function and "supplier_bills" in bill_function and "bill_intelligence_timeline" in bill_function and "append_bill_intelligence_audit" in bill_migration and "append_bill_intelligence_audit" in bill_function, "Bill intelligence extraction/posting/audit boundary missing"
security_contracts = (
    "mfa_satisfied_for_role", "auth.jwt() ->> 'aal'", "trg_prevent_direct_calculation_snapshot_mutation",
    "expenses_amount_business_limit", "duty_proofs_otp_format", "p0_role_permissions", "Calculation total exceeds the allowed business limit",
)
assert security_migration_path.is_file() and all(marker in security_migration for marker in security_contracts), "Supabase security hardening migration missing MFA, mutation or bounds guards"
assert "AXIOM_ALLOWED_ORIGIN" in (ROOT / "supabase/functions/calculate-duty/index.ts").read_text(), "Configured Edge CORS guard missing"
webhook_contracts = ("payment", "sms", "whatsapp", "telephony", "crypto.subtle", "constantTimeEqual", "signature_valid", "webhook_events")
assert webhook_function_path.is_file() and all(marker in webhook_function for marker in webhook_contracts), "Signed multi-provider webhook gateway missing"
corporate_tables = ["corporate_accounts", "corporate_account_snapshots", "corporate_snapshot_price_books", "corporate_snapshot_price_book_items", "corporate_account_users", "corporate_allotment_rules", "corporate_policies", "corporate_masters", "corporate_duty_slip_approvals", "corporate_policy_evaluations", "corporate_idempotency_keys"]
corporate_routes = ["/api/corporate/account", "/api/corporate/account/setup", "/api/corporate/account/activate", "/api/corporate/users", "/api/corporate/policies", "/api/corporate/policies/evaluate", "/api/corporate/visibility/evaluate", "/api/corporate/permissions/evaluate", "/api/corporate/duty-slip-approvals", "/api/corporate/masters", "/api/corporate/allotment/rules", "/api/corporate/allotment/evaluate"]
assert corporate_migration_path.is_file() and all(f"public.{name}" in corporate_migration for name in corporate_tables), "Corporate account/policy Supabase tables missing"
assert all(marker in corporate_function for marker in corporate_routes), "Corporate Edge route parity missing"
assert "corporate_snapshot_price_books" in corporate_migration and "corporate_snapshot_price_book_items" in corporate_migration, "Copied pricing evidence tables missing"
assert "enable row level security" in corporate_migration and "corporate_accounts_read" in corporate_migration and "corporate_allotment_rules_write" in corporate_migration, "Corporate RLS policies missing"
assert "corporate_signed_duty_slip_action" in corporate_migration and "corporate_auto_approve_duty_slips" in corporate_migration and "functions/v1/corporate-duty-slip-action" in corporate_function, "Corporate signed action delivery boundary missing"
assert corporate_action_path.is_file() and "corporate_signed_duty_slip_action" in corporate_action and "Access-Control-Allow-Methods" in corporate_action, "Public signed duty-slip Edge boundary missing"
corporate_write_guards = [
    "alter type public.booking_status add value if not exists 'pending_approval'",
    "corporate_booking_write_guard",
    "corporate_booking_approval_write_guard",
    "corporate_duty_write_guard",
    "trg_corporate_bookings_write_guard",
    "trg_corporate_bookings_delete_guard",
    "trg_corporate_duties_write_guard",
    "trg_corporate_booking_approvals_delete_guard",
    "account_entitlement_denied",
    "booking_lead_time",
    "cancellation_cutoff",
]
assert all(marker in corporate_migration for marker in corporate_write_guards), "Corporate production database write guards missing"
assert "customer_entity_id" in client and "vehicle_group_code" in client and "pending booking" in client, "Corporate browser booking scope/status parity missing"
operations_tables = ["booking_batches", "booking_batch_rows", "allotment_decisions", "duty_closures", "closure_evidence"]
operations_routes = ["/api/bookings/batches", "/api/availability", "/api/allotment/decisions", "allotMatch", "closeMatch", "submit_duty_closure"]
assert operations_migration_path.is_file() and all(f"public.{name}" in operations_migration for name in operations_tables), "Operational parity Supabase tables missing"
assert operations_function_path.is_file() and all(marker in operations_function for marker in operations_routes), "Operational parity Edge routes missing"
assert "operations-orchestrator" in client and "submit_duty_closure" in operations_migration and "deterministic" in operations_function, "Operational parity browser/RPC boundary missing"
finance_tables = ["invoice_runs", "dunning_actions", "report_definitions", "export_profiles"]
finance_routes = ["/api/invoices/generate", "/api/invoice-runs", "/api/collections/dunning", "generate_invoice_run", "run_dunning_run"]
assert finance_migration_path.is_file() and all(f"public.{name}" in finance_migration for name in finance_tables), "Finance/reporting Supabase tables missing"
assert finance_function_path.is_file() and all(marker in finance_function for marker in finance_routes), "Finance/reporting Edge routes missing"
assert "finance-reporting-orchestrator" in client and "invoice_runs" in finance_migration and "ageing" in finance_function, "Finance/reporting browser/RPC boundary missing"
communications_tables = ["communication_templates", "communication_suppressions", "communication_dispatches", "communication_webhook_events"]
communications_routes = ["/api/communications/templates", "/api/communications/dispatch", "create_communication_template", "queue_communication_dispatch", "record_communication_delivery"]
assert communications_migration_path.is_file() and all(f"public.{name}" in communications_migration for name in communications_tables), "Communications Supabase tables missing"
assert communications_function_path.is_file() and all(marker in communications_function for marker in communications_routes), "Communications Edge routes missing"
assert "communications-orchestrator" in client and "placeholders" in communications_migration and "suppression" in communications_function, "Communications browser/RPC boundary missing"
supplier_finance_tables = ["purchase_orders", "fuel_entries", "petty_cash_entries", "driver_allowances", "payroll_runs", "payroll_lines", "supplier_settlements"]
supplier_finance_routes = ["/api/supplier-purchases", "/api/fuel-entries", "/api/driver-allowances", "/api/payroll/runs", "generate_payroll_run", "generate_supplier_settlement"]
assert supplier_finance_migration_path.is_file() and all(f"public.{name}" in supplier_finance_migration for name in supplier_finance_tables), "Supplier/fleet finance Supabase tables missing"
assert supplier_finance_function_path.is_file() and all(marker in supplier_finance_function for marker in supplier_finance_routes), "Supplier/fleet finance Edge routes missing"
assert "supplier-fleet-finance-orchestrator" in client and "payroll" in supplier_finance_migration and "supplier-ageing" in supplier_finance_function, "Supplier/fleet finance browser/RPC boundary missing"
feedback_tables = ["feedback_forms", "feedback_requests", "feedback_responses", "service_recovery_actions"]
feedback_routes = ["/api/feedback/forms", "/api/feedback/requests", "/api/feedback/notifications/run", "create_feedback_form", "submit_feedback_response"]
assert feedback_migration_path.is_file() and all(f"public.{name}" in feedback_migration for name in feedback_tables), "Feedback/recovery Supabase tables missing"
assert feedback_function_path.is_file() and all(marker in feedback_function for marker in feedback_routes), "Feedback/recovery Edge routes missing"
assert "feedback-orchestrator" in client and "feedback.manage" in feedback_migration and "sentiment" in feedback_function, "Feedback/recovery browser/RPC boundary missing"
followon_tables = [
    "finance_supplier_payment_requests", "finance_supplier_advances", "finance_payment_executions", "finance_settlement_approvals", "finance_driver_payouts", "finance_payroll_exports", "finance_payroll_compliance_reports", "finance_fuel_stations", "finance_fuel_prices", "finance_reconciliations",
    "report_builder_configs", "report_favorites", "report_export_jobs", "finance_import_templates", "finance_import_jobs", "feedback_public_links", "feedback_notifications", "feedback_analytics_snapshots", "feedback_corrective_actions"
]
followon_routes = [
    "/api/supplier-payment-requests", "/api/supplier-advances", "/api/supplier-settlement-approvals", "/api/driver-payouts/requests", "/api/payroll/exports", "/api/payroll/compliance", "/api/fuel-stations", "/api/fuel-prices", "/api/fuel-analytics", "/api/petty-cash/reconciliations", "/api/finance/reconciliations", "/api/reports/builder", "/api/reports/profitability", "/api/reports/exports", "/api/reporting/import-templates", "/api/imports/preview"
]
assert followon_migration_path.is_file() and all(f"public.{name}" in followon_migration for name in followon_tables), "Finance/reporting follow-on Supabase tables missing"
assert finance_controls_function_path.is_file() and all(marker in finance_controls_function for marker in followon_routes), "Finance/reporting follow-on Edge routes missing"
assert "finance-controls-orchestrator" in client and "Tally and Tally Prime" in finance_controls_function and "report-exports" in followon_migration and "payroll-exports" in followon_migration, "Async export/download boundary or Tally exclusion missing"
assert "enable row level security" in followon_migration and "finance.execute" in followon_migration and "reports.manage" in followon_migration and "submit_public_feedback" in followon_migration, "Follow-on permission/RLS/public feedback RPC guard missing"
assert feedback_public_function_path.is_file() and "feedback-public" in client and "tokenHash" in feedback_public_function and "Cache-Control" in feedback_public_function, "Public token-only feedback boundary missing"
enterprise_tables = [
    "enterprise_groups", "enterprise_group_members", "enterprise_companies", "enterprise_billing_profiles", "enterprise_bank_accounts", "enterprise_tax_entities",
    "enterprise_billing_items", "enterprise_custom_fields", "enterprise_company_profiles", "enterprise_plan_subscriptions", "enterprise_usage_events",
    "enterprise_sso_configs", "passenger_portal_tokens", "booking_control_rules", "enterprise_booking_quotes", "allotment_requests",
    "allotment_responses", "allotment_exceptions", "duty_execution_profiles", "duty_otps", "duty_media_objects", "duty_evidence_bundles", "duty_slip_documents",
    "duty_adjustments", "duty_closure_jobs"
]
enterprise_routes = [
    "/api/enterprise/groups", "/api/enterprise/companies", "/api/enterprise/billing-profiles", "/api/enterprise/groups/members", "/api/enterprise/booking-controls", "/api/enterprise/sso/config",
    "/api/passenger/portal-links", "/api/passenger/v1/portal", "/api/availability/calendar", "bookings\\/", "calculate_enterprise_booking_quote",
    "allotment-requests\\/", "/api/allotment-exceptions", "/api/duties/", "duty_otps", "/api/duty-close/v1", "evidence-bundle", "process_enterprise_closure_jobs"
]
assert enterprise_migration_path.is_file() and all(f"public.{name}" in enterprise_migration for name in enterprise_tables), "Enterprise controls Supabase tables missing"
assert enterprise_function_path.is_file() and all(marker in enterprise_function for marker in enterprise_routes), "Enterprise Edge routes missing"
assert "enterprise-orchestrator" in client and "supabaseEnterpriseRequest" in client and "publicRequest" in client, "Enterprise browser boundary missing"
assert "enterprise.manage" in enterprise_migration and "enterprise.booking" in enterprise_migration and "enterprise.evidence" in enterprise_migration and "enable row level security" in enterprise_migration, "Enterprise permissions/RLS boundary missing"
assert "trg_enterprise_billing_item_guard" in enterprise_migration and "mandatory billing item" in enterprise_migration.lower() and "notification_attempts" in enterprise_migration and "approval_window_hours',48" in enterprise_migration, "Enterprise closure billing/worker guard missing"
assert "passenger_portal_tokens" in enterprise_function and "SUPABASE_SERVICE_ROLE_KEY" in enterprise_function and "token_hash" in enterprise_function, "Passenger token boundary missing"
print(f"PASS Supabase parity contracts: {len(tables)} tables, {len(route_markers)} route families, {len(p0_tables)} P0 tables, {len(phase12_tables)} Phase 1/2 tables, {len(phase3_tables)} Phase 3 tables, {len(bill_tables)} bill intelligence tables, {len(corporate_tables)} corporate tables, {len(operations_tables)} operations parity tables, {len(finance_tables)} finance/reporting tables, {len(communications_tables)} communications tables, {len(supplier_finance_tables)} supplier/fleet finance tables, {len(feedback_tables)} feedback/recovery tables, {len(followon_tables)} finance/reporting/feedback follow-on tables, {len(enterprise_tables)} enterprise controls tables, RLS and production write guards present")
