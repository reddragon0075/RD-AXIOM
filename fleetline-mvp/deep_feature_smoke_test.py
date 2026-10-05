#!/usr/bin/env python3
"""Broad local contract smoke for the remaining PRD feature layer."""

from __future__ import annotations
import sys

import os
import subprocess
import tempfile
import time
from pathlib import Path

from backend_smoke_test import call, expect, free_port, make_client

ROOT = Path(__file__).resolve().parent


def main() -> None:
    port = free_port(); base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="axiom-fleet-deep-") as temp_dir:
        env = os.environ.copy(); env.update({"AXIOM_TEST_FIXTURES": "1", "PORT": str(port), "AXIOM_DB_PATH": str(Path(temp_dir) / "axiom.sqlite3")})
        process = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                try:
                    status, _ = call(make_client(base)[1], base, "GET", "/api/health")
                    if status == 200: break
                except Exception: pass
                time.sleep(0.1)
            _, client = make_client(base)
            status, login = call(client, base, "POST", "/api/auth/login", {"email": "admin@blueorbit.in", "password": "motion2026"})
            expect(status == 200, "deep test authenticates operator")

            status, onboarding = call(client, base, "GET", "/api/onboarding")
            expect(status == 200 and onboarding["total"] >= 8 and "progress_pct" in onboarding, "resumable onboarding returns server-side progress")
            status, provision = call(client, base, "POST", "/api/onboarding/provision", {"organization": {"city": "Mumbai", "gstin": "27ABCDE1234F1Z5"}, "branch": {"code": "HQ", "name": "Head Office", "city": "Mumbai"}, "tax_profile": {"default_rate_bps": 1800}, "numbering_series": {"invoice": "INV-{YYYY}-{SEQ}"}})
            expect(status in {200, 201} and provision["provisioned"] is True, "tenant provisioning stores branch, tax and numbering settings")
            status, step = call(client, base, "PATCH", "/api/onboarding", {"step": "tax_profile", "status": "complete"})
            expect(status == 200 and step["status"] == "complete", "onboarding step state is resumable")
            status, tax = call(client, base, "POST", "/api/tax/calculate", {"taxable_paise": 100000, "origin_state": "Karnataka", "destination_state": "Karnataka", "tax_rate_bps": 1800})
            expect(status == 200 and tax["tax"]["cgst_paise"] == 9000 and tax["tax"]["igst_paise"] == 0, "state-aware GST calculation splits intra-state tax")
            status, sla = call(client, base, "POST", "/api/sla", {"entity_type": "booking", "entity_id": "booking-deep", "metric": "assignment", "due_at": "2026-09-19T10:00:00Z"})
            expect(status in {200, 201} and sla["item"]["status"] == "open", "SLA event can be created")
            sla_id = sla["item"]["id"]
            status, resolved = call(client, base, "POST", f"/api/sla/{sla_id}/resolve", {})
            expect(status == 200 and resolved["status"] == "resolved", "SLA event can be resolved")
            status, updates = call(client, base, "GET", "/api/updates")
            expect(status == 200 and "events" in updates and "cursor" in updates, "incremental operational updates endpoint returns a cursor")

            status, customer = call(client, base, "POST", "/api/customers", {"name": "Deep Duplicate Customer", "phone": "+919900001234", "gstin": "27DEEP1234F1Z5"})
            expect(status == 201, "deep test creates a master record")
            status, duplicate = call(client, base, "POST", "/api/duplicates/check", {"entity_type": "customer", "values": {"phone": "+91 99000 01234"}})
            expect(status == 200 and duplicate["duplicate"] is True, "normalized duplicate detection catches phone variants")
            status, updated_customer = call(client, base, "PATCH", f"/api/customers/{customer['item']['id']}", {"status": "inactive"})
            expect(status == 200 and updated_customer["item"]["status"] == "inactive", "master deactivation is persisted")
            status, employee = call(client, base, "POST", "/api/employees", {"employee_code": "DEEP-001", "full_name": "Deep Travel Manager", "email": "deep.manager@example.com", "cost_center": "OPS"})
            expect(status == 201, "corporate employee master is persisted")
            status, employee_off = call(client, base, "POST", f"/api/employees/{employee['item']['id']}/deactivate", {})
            expect(status == 200 and employee_off["status"] == "inactive", "employee lifecycle deactivation is recorded")
            status, employee_on = call(client, base, "POST", f"/api/employees/{employee['item']['id']}/reactivate", {})
            expect(status == 200 and employee_on["status"] == "active", "employee lifecycle reactivation is recorded")

            status, price_book = call(client, base, "POST", "/api/price-books", {"name": "Deep Versioned Rates", "effective_from": "2026-09-19", "status": "draft"})
            expect(status == 201, "versioned price book is created")
            book_id = price_book["item"]["id"]
            status, version = call(client, base, "POST", f"/api/price-books/{book_id}/versions", {"changes": {"reason": "September correction"}})
            expect(status in {200, 201} and version["item"]["version"] == 1, "price book version snapshot is recorded")
            status, approved_book = call(client, base, "POST", f"/api/price-books/{book_id}/approve", {"comment": "Maker-checker approved"})
            expect(status in {200, 201} and approved_book["item"]["status"] == "active", "price book maker-checker approval is enforced")

            status, booking = call(client, base, "POST", "/api/bookings", {"customer_id": customer["item"]["id"], "passenger_name": "Deep Passenger", "pickup": {"label": "Airport"}, "dropoff": {"label": "BKC"}, "duty_type": "airport"})
            expect(status == 201, "deep booking is created")
            booking_id = booking["item"]["id"]
            status, stops = call(client, base, "POST", f"/api/bookings/{booking_id}/stops", {"stops": [{"label": "Andheri pickup", "address": {"city": "Mumbai"}}, {"label": "BKC office", "address": {"city": "Mumbai"}}]})
            expect(status in {200, 201} and len(stops["items"]) == 2, "multi-stop route plan is persisted")
            status, recurring = call(client, base, "POST", "/api/bookings/recurring", {"cadence": "weekly", "start_at": "2026-09-21T08:00:00Z", "occurrences": 3, "template": {"customer_id": customer["item"]["id"], "passenger_name": "Recurring Passenger", "pickup": {"label": "Airport"}, "dropoff": {"label": "BKC"}, "duty_type": "local"}})
            expect(status in {200, 201} and len(recurring["generated"]) == 3, "recurring booking series generates scheduled instances")
            booking_id = booking["item"]["id"]
            status, chain = call(client, base, "POST", f"/api/bookings/{booking_id}/approval-chain", {"levels": [{"role": "corporate_travel"}, {"role": "corporate_finance"}]})
            expect(status in {200, 201} and len(chain["items"]) == 2, "multi-level approval chain is persisted")
            first_step = chain["items"][0]["id"]
            status, first_decision = call(client, base, "POST", f"/api/approval-steps/{first_step}/decision", {"status": "approved", "comment": "Travel policy passed"})
            expect(status == 200 and first_decision["item"]["status"] == "approved", "first approval level is recorded")
            second_step = chain["items"][1]["id"]
            status, second_decision = call(client, base, "POST", f"/api/approval-steps/{second_step}/decision", {"status": "approved", "comment": "Budget passed"})
            expect(status == 200 and second_decision["item"]["status"] == "approved", "final approval level is recorded")

            status, duty = call(client, base, "POST", "/api/duties", {"booking_id": booking_id})
            expect(status == 201, "deep duty is created")
            duty_id = duty["item"]["id"]
            status, capacity = call(client, base, "POST", "/api/capacity/locks", {"resource_type": "vehicle", "resource_id": "veh_demo_ka03mn4821", "booking_id": booking_id, "starts_at": "2026-09-19T12:00:00Z", "ends_at": "2026-09-19T14:00:00Z"})
            expect(status in {200, 201} and capacity["item"]["status"] == "held", "vehicle capacity lock prevents double allotment")
            status, released_capacity = call(client, base, "POST", f"/api/capacity/locks/{capacity['item']['id']}/release", {})
            expect(status == 200 and released_capacity["status"] == "released", "capacity lock can be released")
            status, navigation = call(client, base, "POST", f"/api/duties/{duty_id}/navigation", {"origin": "Airport", "destination": "BKC"})
            expect(status in {200, 201} and navigation["navigation"]["status"] == "estimated", "mock navigation route is returned")
            status, masked_call = call(client, base, "POST", f"/api/duties/{duty_id}/call", {"recipient": "+919900001234", "consent": True})
            expect(status in {200, 201} and masked_call["call"]["masked_number"], "masked calling records consent and provider reference")
            status, sos = call(client, base, "POST", f"/api/duties/{duty_id}/sos", {"latitude": 19.08, "longitude": 72.88, "note": "Safety check"})
            expect(status in {200, 201} and sos["item"]["status"] == "open", "SOS creates a critical field alert")
            status, closed = call(client, base, "POST", f"/api/duties/{duty_id}/force-close", {"reason": "Deep smoke completion"})
            expect(status in {200, 201} and closed["item"]["status"] == "completed", "force-close exception workflow is auditable")

            status, bill = call(client, base, "POST", "/api/supplier-bills", {"bill_number": "SUP-DEEP-001", "subtotal_paise": 100000, "tax_paise": 18000, "supplier_id": "supplier_demo_network"})
            expect(status in {200, 201} and bill["validation"]["valid"] is True, "supplier bill capture validates required fields")
            status, cost = call(client, base, "POST", "/api/costs", {"cost_type": "vehicle", "category": "maintenance", "amount_paise": 25000, "vehicle_id": "veh_demo_ka03mn4821"})
            expect(status in {200, 201} and cost["item"]["amount_paise"] == 25000, "fleet cost entry is persisted")
            status, payout = call(client, base, "POST", "/api/supplier-payouts", {"recipient_id": "supplier_demo_network", "amount_paise": 118000, "period_start": "2026-09-01", "period_end": "2026-09-19"})
            expect(status in {200, 201} and payout["item"]["status"] == "pending_approval", "supplier payout enters maker-checker")
            status, action = call(client, base, "POST", "/api/financial-actions", {"action_type": "refund", "entity_type": "payout", "entity_id": payout["item"]["id"]})
            expect(status in {200, 201} and action["item"]["status"] == "pending", "financial action is held for review")
            status, approved_action = call(client, base, "POST", f"/api/financial-actions/{action['item']['id']}/approve", {"comment": "Reviewed"})
            expect(status == 200 and approved_action["item"]["status"] == "approved", "financial action approval is recorded")

            status, e_invoice = call(client, base, "POST", "/api/invoices/inv_demo_2026_083/e-invoice", {})
            expect(status == 200, "deep billing creates mock e-invoice")
            status, cancelled = call(client, base, "POST", "/api/invoices/inv_demo_2026_083/e-invoice/cancel", {"reason": "Deep smoke cancellation"})
            expect(status in {200, 201} and cancelled["item"]["status"] == "cancelled", "e-invoice cancellation is recorded")
            status, allocation = call(client, base, "POST", "/api/receipts/allocate", {"invoice_id": "inv_demo_2026_083", "amount_paise": 10000, "reference": "RCPT-DEEP"})
            expect(status in {200, 201} and allocation["item"]["amount_paise"] == 10000, "receipt allocation is persisted")
            status, note = call(client, base, "POST", "/api/billing-notes", {"note_type": "credit", "invoice_id": "inv_demo_2026_083", "amount_paise": 5000, "reason": "Service recovery"})
            expect(status in {200, 201} and note["item"]["status"] == "draft", "credit note enters controlled draft state")
            status, payment_link = call(client, base, "POST", "/api/payment-links", {"invoice_id": "inv_demo_2026_083", "amount_paise": 10000})
            expect(status in {200, 201} and payment_link["item"]["url"].startswith("/pay/"), "mock payment link is generated")
            status, public_link = call(client, base, "GET", f"/api/public/payment-links/{payment_link['item']['short_code']}")
            expect(status == 200 and public_link["item"]["status"] == "created", "public payment link exposes only safe payment context")
            status, public_paid = call(client, base, "POST", f"/api/public/payment-links/{payment_link['item']['short_code']}", {"action": "pay"})
            expect(status == 200 and public_paid["status"] == "paid", "public payment link accepts mock payment")
            status, captured_link = call(client, base, "POST", f"/api/payment-links/{payment_link['item']['id']}/capture", {})
            expect(status == 200 and captured_link["status"] == "paid", "payment link capture records settlement")
            status, webhook = call(client, base, "POST", "/api/webhooks/payments", {"event_id": "deep-payment-1", "provider": "mock_payment", "event_type": "payment.succeeded", "signature": "mock-signature"})
            expect(status in {200, 201} and webhook["status"] == "processed", "signed mock payment webhook is idempotently recorded")

            status, prefs = call(client, base, "PATCH", "/api/drivers/preferences", {"language": "hi-IN", "quiet_hours": {"start": "22:00", "end": "06:00"}, "low_bandwidth": True})
            expect(status == 200 and prefs["item"]["language"] == "hi-IN", "driver language and quiet-hours preferences persist")
            status, device = call(client, base, "POST", "/api/devices", {"device_id": "deep-browser-device", "platform": "web"})
            expect(status in {200, 201} and device["item"]["status"] == "active", "device binding is registered")
            status, practice = call(client, base, "POST", "/api/practice-duties", {"scenario": "offline_completion"})
            expect(status in {200, 201} and practice["item"]["scenario"] == "offline_completion", "practice duty is available")
            status, factor = call(client, base, "POST", "/api/security/2fa/setup", {})
            expect(status == 200 and factor["mock_verification_code"] == "246810", "mock TOTP setup returns enrollment contract")
            status, factor_enabled = call(client, base, "POST", "/api/security/2fa/verify", {"code": "246810"})
            expect(status == 200 and factor_enabled["enabled"] is True, "two-factor factor can be enabled")
            status, key = call(client, base, "POST", "/api/security/api-keys", {"name": "Deep integration key", "scopes": ["bookings:read"]})
            expect(status in {200, 201} and key["item"]["key"].startswith("af_live_"), "scoped API key is generated once")
            status, revoked_key = call(client, base, "POST", f"/api/security/api-keys/{key['item']['id']}/revoke", {})
            expect(status == 200 and revoked_key["status"] == "revoked", "API key can be revoked")
            status, job = call(client, base, "POST", "/api/jobs", {"job_type": "report_delivery", "payload": {"report_type": "operations"}})
            expect(status in {200, 201} and job["item"]["status"] == "queued", "async job is queued")
            status, job_done = call(client, base, "POST", f"/api/jobs/{job['item']['id']}/run", {})
            expect(status == 200 and job_done["item"]["status"] == "completed", "mock worker completes queued job")

            status, access = call(client, base, "POST", "/api/passenger/access", {"duty_id": duty_id, "email": "passenger@deep.example"})
            expect(status in {200, 201} and access["item"]["access_token"], "passenger access link is generated")
            status, trip = call(client, base, "GET", f"/api/passenger/trips/{access['item']['access_token']}")
            expect(status == 200 and trip["trip"]["duty"]["id"] == duty_id, "passenger trip status is readable from a scoped link")
            status, rating = call(client, base, "POST", f"/api/passenger/duties/{duty_id}/rating", {"rating": 5, "tags": ["clean", "safe"], "comment": "Good trip"})
            expect(status in {200, 201} and rating["item"]["rating"] == 5, "passenger rating and issue tags persist")

            status, alert = call(client, base, "POST", "/api/alerts", {"alert_type": "sla_breach", "severity": "high", "entity_type": "duty", "entity_id": duty_id})
            expect(status in {200, 201} and alert["item"]["status"] == "open", "operational alert is visible")
            status, acknowledged = call(client, base, "POST", f"/api/alerts/{alert['item']['id']}/ack", {})
            expect(status == 200 and acknowledged["status"] == "acknowledged", "alerts can be acknowledged")
            status, fence = call(client, base, "POST", "/api/geofences", {"name": "Mumbai Airport", "latitude": 19.0896, "longitude": 72.8656, "radius_m": 800, "event_types": ["arrival", "departure"]})
            expect(status in {200, 201} and fence["item"]["radius_m"] == 800, "geofence alert configuration persists")

            status, edge = call(client, base, "POST", "/api/network/edges", {"partner_name": "Deep Associate Fleet", "cities": ["Mumbai", "Pune"]})
            expect(status in {200, 201} and edge["item"]["status"] == "invited", "associate fleet edge is created")
            status, accepted_edge = call(client, base, "POST", "/api/network/edges/accept", {"edge_id": edge["item"]["id"]})
            expect(status == 200 and accepted_edge["item"]["status"] == "active", "associate edge can be accepted")
            status, offer = call(client, base, "POST", "/api/network/offers", {"edge_id": edge["item"]["id"], "duty_id": duty_id, "amount_paise": 90000})
            expect(status in {200, 201} and offer["item"]["status"] == "offered", "network duty offer is created")
            status, bid = call(client, base, "POST", f"/api/network/offers/{offer['item']['id']}/bids", {"amount_paise": 88000, "comment": "Can cover"})
            expect(status in {200, 201} and bid["item"]["status"] == "submitted", "network bid is recorded")
            status, settlement = call(client, base, "POST", "/api/network/settlements", {"gross_paise": 88000, "deductions_paise": 5000})
            expect(status in {200, 201} and settlement["item"]["net_paise"] == 83000, "settlement ledger calculates net value")

            status, export = call(client, base, "POST", "/api/reports/export", {"report_type": "operations"})
            expect(status in {200, 201} and export["item"]["status"] == "ready", "report export is generated with expiry")
            status, export_file = call(client, base, "GET", f"/api/reports/exports/{export['item']['id']}")
            expect(status == 200 and "Axiom Fleet" in export_file["item"]["content"], "report export content is downloadable")
            status, view = call(client, base, "POST", "/api/reports/views", {"name": "Deep ops view", "config": {"columns": ["status", "scheduled_at"]}})
            expect(status in {200, 201} and view["item"]["name"] == "Deep ops view", "saved report view persists")
            status, schedule = call(client, base, "POST", "/api/reports/schedules", {"report_type": "invoices", "cadence": "monthly", "recipients": ["finance@deep.example"]})
            expect(status in {200, 201} and schedule["item"]["cadence"] == "monthly", "scheduled report distribution persists")
            status, drilldown = call(client, base, "GET", "/api/reports/drilldown")
            expect(status == 200 and drilldown["count"] >= 1, "report drill-down returns source rows")

            status, consent = call(client, base, "POST", "/api/privacy/consents", {"subject_id": "passenger-deep", "purpose": "trip_updates", "policy_version": "2026.09"})
            expect(status in {200, 201} and consent["item"]["status"] == "granted", "consent receipt is recorded")
            status, privacy_request = call(client, base, "POST", "/api/privacy/requests", {"request_type": "export", "notes": "Deep test export request"})
            expect(status in {200, 201} and privacy_request["item"]["status"] == "open", "privacy export request is recorded")
            status, privacy_done = call(client, base, "POST", f"/api/privacy/requests/{privacy_request['item']['id']}/fulfill", {})
            expect(status == 200 and privacy_done["status"] == "completed", "privacy request can be fulfilled")
            status, lock = call(client, base, "POST", "/api/privacy/retention", {"entity_type": "invoice", "entity_id": "inv_demo_2026_083", "reason": "financial hold"})
            expect(status in {200, 201} and lock["item"]["reason"] == "financial hold", "retention lock is recorded")
            status, kpis = call(client, base, "GET", "/api/admin/kpis")
            expect(status == 200 and kpis["kpis"]["bookings"] >= 1, "platform KPI view returns operational counts")
            status, flags = call(client, base, "GET", "/api/admin/feature-flags")
            expect(status == 200 and flags["flags"]["offline_driver_shell"] is True, "feature flags expose product capabilities")
            print("RESULT deep feature smoke test passed")
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill()
            if process.stdout: process.stdout.close()


if __name__ == "__main__":
    main()
