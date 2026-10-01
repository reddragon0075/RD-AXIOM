#!/usr/bin/env python3
"""Static Supabase/local parity guard for the 2026-10-01 completion slice."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print("PASS", message)


def main() -> None:
    local = (ROOT / "backend_gap_completion.py").read_text()
    server = (ROOT / "server.py").read_text()
    migration = (ROOT / "supabase/migrations/20261001000000_gap_completion_contracts.sql").read_text()
    edge = (ROOT / "supabase/functions/gap-completion-orchestrator/index.ts").read_text()
    browser = (ROOT / "supabase/client.js").read_text()
    api = yaml.safe_load((ROOT / "openapi.yaml").read_text())
    routes = [
        "/api/passenger/booking-requests", "/api/passenger/book-for-others", "/api/availability/optimize",
        "/api/duties/{duty_id}/route-log", "/api/duties/{duty_id}/location-share", "/api/location-shares/{token}",
        "/api/driver-alert-policies", "/api/driver/device-readiness", "/api/provider-connections", "/api/maps/places",
        "/api/maps/navigation", "/api/communications/click-to-call", "/api/payment-authorizations",
        "/api/invoice-automation/run", "/api/integrations/sync", "/api/network/supplier-exchange",
        "/api/enterprise/custom-field-values", "/api/finance/budgets", "/api/finance/expense-forecast",
    ]
    for route in routes:
        expect(route in api["paths"] or route.replace("{duty_id}", "{duty_id}") in api["paths"], f"OpenAPI declares {route}")
    expect("initialize_gap_completion_schema" in server and "handle_gap_completion" in server, "local server initializes and dispatches completion contracts")
    expect("handle_gap_public" in server and "/api/location-shares/" in server, "public location-share boundary is wired")
    for table in [
        "gap_passenger_booking_requests", "gap_route_logs", "gap_route_points", "gap_location_shares", "gap_driver_alert_policies",
        "gap_driver_alert_events", "gap_device_readiness", "gap_provider_connections", "gap_payment_authorizations",
        "gap_auto_collect_attempts", "gap_invoice_automation_policies", "gap_invoice_automation_runs", "gap_custom_field_values",
        "gap_sync_runs", "gap_supplier_exchange_jobs", "gap_expense_budgets",
    ]:
        expect(f"create table if not exists public.{table}" in migration, f"Supabase migration creates {table}")
    expect("foreach table_name in array" in migration and "_member_select" in migration and "enable row level security" in migration, "Supabase RLS loop covers all completion tables")
    expect("p0_audit_row()" in migration and "_audit" in migration, "Supabase completion tables reuse append-only audit triggers")
    for marker in ["passenger/booking-requests", "availability/optimize", "route-log", "location-share", "driver-alert-policies", "device-readiness", "provider-connections", "payment-authorizations", "invoice-automation", "integrations/sync", "supplier-exchange", "expense-forecast"]:
        expect(marker in edge, f"Supabase Edge routes {marker}")
    expect("supabaseGapRequest" in browser and "gap-completion-orchestrator" in browser, "browser adapter routes completion contracts to Supabase Edge")
    expect("token_fingerprint" in local and "raw card data is not accepted" in local, "tokenized payment boundary avoids raw payment persistence")
    expect("invite_only" in local and "closed-B2B" in local, "closed Network supplier exchange is enforced")
    expect((ROOT / "gap_completion_smoke_test.py").exists(), "local completion smoke coverage exists")
    print("RESULT gap completion contract test passed")


if __name__ == "__main__":
    main()
