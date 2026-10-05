#!/usr/bin/env python3
"""Regression coverage for the additive Indecab-parity completion contracts."""
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
    with tempfile.TemporaryDirectory(prefix="axiom-fleet-gap-") as temp_dir:
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
            status, signup = call(client, base, "POST", "/api/auth/signup", {
                "role": "vendor", "email": "gap.smoke@example.com", "password": "StrongPass123!",
                "full_name": "Gap Operator", "organization_name": "Gap Mobility", "city": "Bengaluru",
            })
            expect(status == 201, "gap smoke tenant authenticates")

            status, vehicle = call(client, base, "POST", "/api/vehicles", {
                "registration_number": "KA01GAP0001", "vehicle_type": "sedan", "vehicle_group": "sedan",
                "city": "Bengaluru", "seating_capacity": 4, "status": "available",
            })
            expect(status == 201, "availability has a tenant vehicle")
            status, driver = call(client, base, "POST", "/api/drivers", {
                "full_name": "Gap Driver", "phone": "+919900000001", "city": "Bengaluru", "status": "available",
            })
            expect(status == 201, "availability has a tenant driver")
            status, booking = call(client, base, "POST", "/api/bookings", {
                "passenger_name": "Availability Passenger", "passenger_phone": "+919900000002",
                "scheduled_at": "2026-10-03T10:00:00Z", "pickup": {"label": "Bengaluru"},
                "dropoff": {"label": "Airport"}, "duty_type": "airport",
            })
            expect(status == 201, "booking foundation accepts an employee trip")
            booking_id = booking["item"]["id"]

            status, availability = call(client, base, "POST", "/api/availability/optimize", {
                "booking_id": booking_id, "city": "Bengaluru", "passenger_count": 1, "auto_assign": True,
            })
            expect(status == 200 and availability["status"] == "available" and availability["auto_assigned"] is True, "availability evaluates and auto-assigns a compatible driver and vehicle")
            duty_id = availability["duty_id"]

            status, started = call(client, base, "POST", f"/api/duties/{duty_id}/route-log/start", {"tracking_mode": "background", "idempotency_key": "route-start-1"})
            expect(status == 200 and started["item"]["status"] == "recording", "background route logging starts with an idempotency boundary")
            status, points = call(client, base, "POST", f"/api/duties/{duty_id}/route-log", {"points": [
                {"latitude": 12.9716, "longitude": 77.5946, "accuracy_m": 8, "battery_pct": 88, "idempotency_key": "point-1"},
                {"latitude": 12.9750, "longitude": 77.6000, "accuracy_m": 9, "battery_pct": 86, "idempotency_key": "point-2"},
            ]})
            expect(status == 200 and points["inserted_points"] == 2, "route points are persisted without duplicate replay")
            status, stopped = call(client, base, "POST", f"/api/duties/{duty_id}/route-log/stop", {"points": [], "stop": True})
            expect(status == 200 and stopped["item"]["status"] == "completed" and stopped["item"]["summary_json"]["point_count"] == 2, "route closure produces distance and point evidence")

            status, share = call(client, base, "POST", f"/api/duties/{duty_id}/location-share", {"recipient": "passenger@example.com"})
            expect(status == 200 and share["item"]["url"].startswith("/api/location-shares/"), "passenger location share issues an expiring token")
            _, public_client = make_client(base)
            status, public_location = call(public_client, base, "GET", share["item"]["url"])
            expect(status == 200 and public_location["trip"]["last_location"]["latitude"] == 12.975, "public location view exposes only the latest scoped position")

            status, policy = call(client, base, "POST", "/api/driver-alert-policies", {
                "name": "GPS stale", "alert_type": "gps_stale", "severity": "critical",
                "threshold": {"minutes": 10}, "localized_guidance": {"hi-IN": "GPS जाँचें"},
            })
            expect(status == 200 and policy["item"]["severity"] == "critical", "driver alert policy stores a production threshold and localized guidance")
            status, alert = call(client, base, "POST", f"/api/duties/{duty_id}/driver-alerts", {
                "alert_type": "gps_stale", "idempotency_key": "alert-1", "payload": {"minutes": 12},
            })
            expect(status == 200 and alert["item"]["severity"] == "critical", "driver alert event follows its policy and is replay-safe")
            status, acknowledged = call(client, base, "POST", f"/api/duties/{duty_id}/driver-alerts/acknowledge", {"alert_id": alert["item"]["id"]})
            expect(status == 200 and acknowledged["status"] == "acknowledged", "driver alert acknowledgement is auditable")

            status, readiness = call(client, base, "POST", "/api/driver/device-readiness", {
                "device_id": "gap-android-1", "platform": "android", "app_version": "1.0.0", "os_version": "15",
                "push_token": "push-token", "permissions": {"push": True, "background_location": True, "media": True, "notifications": True},
            })
            expect(status == 200 and readiness["status"] == "ready", "driver rollout device readiness gates all required permissions")
            status, blocked = call(client, base, "POST", "/api/driver/device-readiness", {
                "device_id": "gap-android-2", "permissions": {"push": True},
            })
            expect(status == 200 and "background_location" in blocked["blockers"], "device readiness returns explicit physical-device blockers")

            status, provider = call(client, base, "POST", "/api/provider-connections", {
                "provider_type": "maps", "name": "Maps mock", "mode": "mock", "capabilities": ["places", "navigation"],
                "config": {"region": "IN", "api_key": "must-not-persist"},
            })
            expect(status == 200 and "api_key" not in provider["item"]["config_json"], "provider connection redacts secrets at the local boundary")
            status, provider_test = call(client, base, "POST", f"/api/provider-connections/{provider['item']['id']}/test", {})
            expect(status == 200 and provider_test["status"] == "healthy_mock" and provider_test["production_validated"] is False, "mock provider health never claims production connectivity")
            status, places = call(client, base, "GET", "/api/maps/places?q=Kempegowda%20Airport")
            expect(status == 200 and places["item"]["predictions"], "Google Places-compatible search contract is available behind an adapter")
            status, navigation = call(client, base, "POST", "/api/maps/navigation", {"pickup": {"label": "Bengaluru"}, "dropoff": {"label": "Airport"}})
            expect(status == 200 and navigation["item"]["deep_link"].startswith("https://maps.google.com"), "navigation contract returns provider-neutral routing and deep-link data")
            status, call_result = call(client, base, "POST", "/api/communications/click-to-call", {"to_number": "+919900000003", "context": "duty"})
            expect(status == 200 and call_result["item"]["masked"] is True, "click-to-call stays behind the masked telephony adapter")

            status, request = call(client, base, "POST", "/api/passenger/book-for-others", {
                "passenger_name": "Executive Passenger", "passenger_phone": "+919900000004", "scheduled_at": "2026-10-04T09:00:00Z",
                "pickup": {"label": "Office"}, "dropoff": {"label": "Airport"}, "idempotency_key": "passenger-request-1",
            })
            expect(status == 200 and request["item"]["status"] == "pending", "corporate book-for-others workflow creates an approval request")
            status, replay = call(client, base, "POST", "/api/passenger/book-for-others", {
                "passenger_name": "Executive Passenger", "scheduled_at": "2026-10-04T09:00:00Z", "pickup": {"label": "Office"}, "dropoff": {"label": "Airport"}, "idempotency_key": "passenger-request-1",
            })
            expect(status == 200 and replay.get("idempotent") is True, "passenger booking request replay is idempotent")
            status, approved = call(client, base, "POST", f"/api/passenger/booking-requests/{request['item']['id']}/approve", {})
            expect(status == 200 and approved["booking_id"], "passenger booking approval creates the Fleet booking")

            status, field = call(client, base, "POST", "/api/enterprise/custom-fields", {"entity_type": "booking", "field_key": "cost_center", "label": "Cost center"})
            expect(status == 200, "enterprise custom-field definition is available")
            status, field_value = call(client, base, "POST", "/api/enterprise/custom-field-values", {"field_id": field["item"]["id"], "entity_type": "booking", "entity_id": booking_id, "value": "CC-001"})
            expect(status == 200 and field_value["items"][0]["value_json"] == "CC-001", "custom-field values are tenant-scoped and upsertable")

            status, calculated = call(client, base, "POST", f"/api/duties/{duty_id}/calculate", {"base_paise": 100000, "distance_km": 20, "per_km_paise": 1500, "duration_minutes": 60, "per_hour_paise": 2000, "tax_rate_bps": 1800})
            expect(status == 200, "duty calculation supplies an invoiceable snapshot")
            status, completed = call(client, base, "POST", f"/api/duties/{duty_id}/force-close", {"reason": "Invoice automation smoke close"})
            expect(status in {200, 201} and completed["item"]["status"] == "completed", "completed duty unlocks invoice automation")
            status, automated = call(client, base, "POST", "/api/invoice-automation/run", {"duty_id": duty_id, "idempotency_key": "automation-1"})
            expect(status == 200 and automated["item"]["status"] == "completed" and automated.get("invoice", {}).get("id"), "invoice automation creates a replay-safe completed run")
            status, invoice = call(client, base, "POST", "/api/invoices", {"duty_id": duty_id})
            expect(status == 201, "calculated duty can create an invoice")
            invoice_id = invoice["item"]["id"]
            status, authorization = call(client, base, "POST", "/api/payment-authorizations", {"payment_method_token": "tok_smoke_4242", "max_amount_paise": 500000, "idempotency_key": "auth-1"})
            expect(status == 200 and authorization["item"]["token_last4"] == "4242" and "token_fingerprint" not in authorization["item"], "payment authorization stores token metadata rather than raw payment data")
            status, collected = call(client, base, "POST", f"/api/invoices/{invoice_id}/auto-collect", {"authorization_id": authorization["item"]["id"], "idempotency_key": "collect-1"})
            expect(status == 200 and collected["item"]["status"] == "succeeded", "auto-collect creates a replay-safe provider payment attempt")
            status, budget = call(client, base, "POST", "/api/finance/budgets", {"period_key": "2026-10", "budget_paise": 1000000})
            expect(status == 200 and budget["item"]["budget_paise"] == 1000000, "corporate expense budgets are persisted")
            status, forecast = call(client, base, "GET", "/api/finance/expense-forecast")
            expect(status == 200 and forecast["item"]["method"] == "three_month_invoice_average", "expense prediction returns a deterministic explainable forecast")

            status, sync = call(client, base, "POST", "/api/integrations/sync", {"sync_type": "hrms", "records": [{"employee_id": "E-1", "status": "active"}], "idempotency_key": "hrms-1"})
            expect(status == 200 and sync["item"]["records_applied"] == 1 and sync["production_validated"] is False, "HRMS lifecycle sync is accepted through the replaceable adapter boundary")
            status, exchange = call(client, base, "POST", "/api/network/supplier-exchange", {"network_program_id": "program-closed", "supplier_id": "supplier-1", "visibility": "invite_only", "qualification": {"status": "passed"}, "rate_card": {"currency": "INR"}, "idempotency_key": "exchange-1"})
            expect(status == 200 and exchange["item"]["visibility"] == "invite_only", "closed-network supplier exchange rejects public-marketplace semantics")

            print("RESULT gap completion smoke test passed")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
