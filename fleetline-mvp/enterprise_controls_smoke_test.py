#!/usr/bin/env python3
"""Focused local smoke coverage for the enterprise/passenger/evidence slice."""
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
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="axiom-fleet-enterprise-") as temp_dir:
        env = os.environ.copy()
        env.update({"PORT": str(port), "AXIOM_DB_PATH": str(Path(temp_dir) / "axiom.sqlite3"), "AXIOM_ALLOW_DEMO_ACCOUNT": "0"})
        process = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(60):
                try:
                    if call(make_client(base)[1], base, "GET", "/api/health")[0] == 200:
                        break
                except Exception:
                    time.sleep(0.1)
            _, client = make_client(base)
            status, signup = call(client, base, "POST", "/api/auth/signup", {"role": "vendor", "email": "enterprise.smoke@example.com", "password": "StrongPass123!", "full_name": "Enterprise Owner", "organization_name": "Enterprise Mobility", "city": "Bengaluru"})
            expect(status == 201 and signup["user"]["role"] == "vendor", "enterprise smoke tenant authenticates")

            status, company = call(client, base, "POST", "/api/enterprise/companies", {"code": "AX-HQ", "legal_name": "Axiom Mobility Private Limited", "trading_name": "Axiom Fleet", "is_sister_company": True})
            expect(status == 200 and company["item"]["code"] == "AX-HQ", "company master supports sister-company hierarchy")
            status, group = call(client, base, "POST", "/api/enterprise/groups", {"code": "AX-GROUP", "name": "Axiom group", "group_type": "sister_company"})
            expect(status == 200 and group["item"]["group_type"] == "sister_company", "group master is tenant-scoped")
            status, member = call(client, base, "POST", "/api/enterprise/groups/members", {"group_id": group["item"]["id"], "entity_type": "company", "entity_id": company["item"]["id"]})
            expect(status == 200 and member["item"]["group_id"] == group["item"]["id"], "sister-company hierarchy accepts explicit membership")
            status, billing_profile = call(client, base, "POST", "/api/enterprise/billing-profiles", {"company_id": company["item"]["id"], "invoice_series": "AX-HQ/26-27", "currency": "INR", "bill_to_mode": "company"})
            expect(status == 200 and billing_profile["item"]["invoice_series"] == "AX-HQ/26-27", "multi-company billing profile selects a company scope")
            status, profile = call(client, base, "POST", "/api/enterprise/company-profile", {"display_name": "Axiom Fleet", "signature_path": "storage://signatures/axiom.png", "footer": "Payment due in 30 days"})
            expect(status == 200 and profile["item"]["signature_path"].startswith("storage://"), "company profile and signature metadata are retained")
            status, profile_list = call(client, base, "GET", "/api/enterprise/company-profile")
            expect(status == 200 and len(profile_list["items"]) == 1, "company profile list is queryable")
            status, controls = call(client, base, "POST", "/api/enterprise/booking-controls", {"name": "Half hour copied pricing", "package_minutes": 30, "package_base_paise": 10000, "extra_half_hour_paise": 2500, "extra_km_paise": 1200, "temporary_allotment": True, "customer_controlled_allotment": True, "auto_switch": {"duty_type": True, "vehicle_group": True}})
            expect(status == 200 and controls["item"]["package_minutes"] == 30 and controls["item"]["temporary_allotment"] == 1, "copy-pricing wizard persists half-hour and allotment controls")
            status, control_list = call(client, base, "GET", "/api/enterprise/booking-controls")
            expect(status == 200 and any(item["id"] == controls["item"]["id"] for item in control_list["items"]), "booking-control rules are queryable after creation")
            status, mandatory_item = call(client, base, "POST", "/api/enterprise/billing-items", {"code": "WAITING", "name": "Waiting charge", "mandatory": True, "unit": "half_hour"})
            expect(status == 200 and mandatory_item["item"]["mandatory"] == 1, "mandatory billing-item validation master is explicit")
            status, plan = call(client, base, "POST", "/api/enterprise/plans", {"plan_code": "PRO", "entitlements": {"passenger_portal": True, "api": True, "usage_limit": 1000}})
            expect(status == 200 and plan["item"]["plan_code"] == "PRO", "plan and usage entitlement administration is tenant-scoped")
            status, field = call(client, base, "POST", "/api/enterprise/custom-fields", {"entity_type": "booking", "field_key": "cost_center", "label": "Cost center", "required": True})
            expect(status == 200 and field["item"]["required"] == 1, "custom fields are explicit and required-aware")
            status, sso = call(client, base, "POST", "/api/enterprise/sso/config", {"provider": "oidc", "issuer_url": "https://login.example.com", "client_id": "axiom-client", "domains": ["example.com"], "status": "draft"})
            expect(status == 200 and sso["item"]["provider"] == "oidc", "company-email SSO boundary stores provider-neutral configuration")

            status, portal = call(client, base, "POST", "/api/passenger/portal-links", {"label": "Smoke passenger portal", "expires_at": "2026-10-07T00:00:00+00:00"})
            expect(status == 200 and portal.get("portal_token") and portal["portal_path"].startswith("/api/passenger/v1/portal/"), "passenger portal issues a one-time token boundary")
            _, public_client = make_client(base)
            status, portal_meta = call(public_client, base, "GET", portal["portal_path"])
            expect(status == 200 and portal_meta["portal"]["label"] == "Smoke passenger portal", "passenger API validates the signed portal boundary")
            status, passenger_booking = call(public_client, base, "POST", portal["portal_path"], {"passenger_name": "Portal Passenger", "passenger_phone": "+919800000000", "pickup": {"label": "Bengaluru"}, "dropoff": {"label": "Airport"}, "scheduled_at": "2026-10-02T10:00:00Z", "duty_type": "airport"})
            expect(status == 200 and passenger_booking["item"]["status"] == "requested" and passenger_booking["item"]["source"] == "passenger_portal", "passenger API creates a tenant booking request")

            status, booking = call(client, base, "POST", "/api/bookings", {"passenger_name": "Quote Passenger", "scheduled_at": "2026-10-03T10:00:00Z", "pickup": {"label": "Bengaluru"}, "dropoff": {"label": "Airport"}})
            expect(status == 201, "enterprise quote uses a normal tenant booking")
            booking_id = booking["item"]["id"]
            status, quote = call(client, base, "POST", f"/api/bookings/{booking_id}/quote", {"duration_minutes": 75, "distance_km": 20, "included_km": 10})
            expect(status == 200 and quote["item"]["extra_time_paise"] == 5000 and quote["item"]["extra_km_paise"] == 12000 and quote["item"]["total_paise"] == 27000, "half-hour quote calculates time and distance overage")
            status, calendar = call(client, base, "GET", "/api/availability/calendar?start=2026-10-03&end=2026-10-04")
            expect(status == 200 and "resources" in calendar and "vehicles" in calendar["resources"], "availability calendar returns live resource capacity")

            status, supplier = call(client, base, "POST", "/api/suppliers", {"name": "Smoke Supplier", "cities": ["Bengaluru"]})
            expect(status == 201, "supplier candidate exists for multi-supplier requests")
            status, requests = call(client, base, "POST", f"/api/bookings/{booking_id}/allotment-requests", {"supplier_ids": [supplier["item"]["id"]], "request_type": "multi_supplier"})
            expect(status == 200 and len(requests["items"]) == 1, "multi-supplier allotment request is recorded")
            request_id = requests["items"][0]["id"]
            status, response = call(client, base, "POST", f"/api/allotment-requests/{request_id}/respond", {"status": "accepted", "amount_paise": 26000, "eta_minutes": 30})
            expect(status == 200 and response["item"]["status"] == "accepted", "supplier response is recorded with ETA and price")

            status, duty = call(client, base, "POST", "/api/duties", {"booking_id": booking_id})
            expect(status == 201, "duty exists for evidence execution")
            duty_id = duty["item"]["id"]
            status, execution = call(client, base, "POST", f"/api/duties/{duty_id}/execution-profile", {"source": "network_driver", "driver_mode": "network_driver", "garage_start": "Bengaluru garage", "garage_end": "Airport garage"})
            expect(status == 200 and execution["item"]["source"] == "network_driver", "Network-driver and garage execution profile is explicit")
            status, otp = call(client, base, "POST", f"/api/duties/{duty_id}/otp", {"otp_type": "start"})
            expect(status == 200 and otp.get("otp") and len(otp["otp"]) == 6, "start OTP is issued without storing plaintext")
            status, verified = call(client, base, "POST", f"/api/duties/{duty_id}/otp/verify", {"otp_type": "start", "otp": otp["otp"]})
            expect(status == 200 and verified["verified"] is True, "OTP retrieval and verification are auditable")
            status, media = call(client, base, "POST", f"/api/duties/{duty_id}/media", {"media_type": "signed_slip", "sha256": "smoke-sha256"})
            expect(status == 200 and media["signed_url"].startswith("mock://"), "media upload returns a signed mock object boundary")
            status, adjustment = call(client, base, "POST", f"/api/duties/{duty_id}/adjustments", {"adjustment_type": "debit", "amount_paise": 1500, "reason": "Evidence-backed overage", "evidence": {"media_id": media["item"]["id"]}})
            expect(status == 200 and adjustment["item"]["adjustment_type"] == "debit", "credit/debit adjustments are tied to evidence metadata")
            status, close_link = call(client, base, "POST", f"/api/duties/{duty_id}/sms-close", {})
            expect(status == 200 and close_link.get("action_path"), "SMS closure issues an expiring action link")
            status, close_form = call(public_client, base, "GET", close_link["action_path"])
            expect(status == 200 and close_form["item"]["duty_id"] == duty_id, "SMS closure link is public but scoped")
            status, missing_billing = call(public_client, base, "POST", close_link["action_path"], {"start_odometer": 1000, "end_odometer": 1125, "evidence": [{"evidence_type": "duty_slip", "sha256": "smoke-sha256"}]})
            expect(status == 409 and missing_billing["code"] == "billing_items_required", "closure blocks when mandatory billing items are missing")
            status, closed = call(public_client, base, "POST", close_link["action_path"], {"start_odometer": 1000, "end_odometer": 1125, "billing_items": ["WAITING"], "evidence": [{"evidence_type": "duty_slip", "sha256": "smoke-sha256"}]})
            expect(status == 200 and closed.get("duty", {}).get("status") == "completed", "SMS duty closure transitions the duty with odometers")
            status, slip = call(client, base, "GET", f"/api/duties/{duty_id}/slip")
            expect(status == 200 and slip["item"]["document_type"] == "combined_duty_slip", "combined duty-slip document includes closure evidence")
            status, bundle = call(client, base, "POST", f"/api/duties/{duty_id}/evidence-bundle", {})
            expect(status == 200 and bundle.get("immutable") is True and bundle.get("bundle_hash") and bundle.get("download_token"), "immutable evidence bundle canonicalizes closure, media and adjustments")
            status, bundle_replay = call(client, base, "GET", f"/api/duties/{duty_id}/evidence-bundle")
            expect(status == 200 and bundle_replay.get("immutable") is True and bundle_replay.get("bundle_hash") == bundle.get("bundle_hash"), "evidence bundle replay is content-addressed and immutable")
            status, jobs = call(client, base, "POST", "/api/duty-closure-jobs/run", {})
            expect(status == 200 and "processed" in jobs, "closure worker endpoint is idempotent and observable")
            print("RESULT enterprise controls smoke test passed")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            if process.stdout:
                process.stdout.close()


if __name__ == "__main__":
    main()
