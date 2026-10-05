#!/usr/bin/env python3
"""Smoke coverage for the remaining local PRD feature surfaces."""

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
    with tempfile.TemporaryDirectory(prefix="axiom-fleet-features-") as temp_dir:
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
            expect(status == 200, "feature test authenticates vendor")
            status, checklist = call(client, base, "GET", "/api/organization/checklist")
            expect(status == 200 and checklist["total"] >= 6, "organization setup checklist is available")
            status, branch = call(client, base, "POST", "/api/branches", {"code": "BLR", "name": "Bengaluru control room", "city": "Bengaluru"})
            expect(status == 201 and branch["item"]["code"] == "BLR", "branch creation persists")
            status, supplier = call(client, base, "POST", "/api/suppliers", {"name": "Test Associate Fleet", "cities": ["Bengaluru"]})
            expect(status == 201 and supplier["item"]["name"] == "Test Associate Fleet", "supplier creation persists")
            status, price_book = call(client, base, "POST", "/api/price-books", {"name": "Pilot rates", "branch_id": branch["item"]["id"], "effective_from": "2026-09-20"})
            expect(status == 201, "price book creation persists")
            status, price_item = call(client, base, "POST", f"/api/price-books/{price_book['item']['id']}/items", {"duty_type": "local", "vehicle_group": "sedan", "base_paise": 100000, "per_km_paise": 1500, "tax_rate_bps": 1800})
            expect(status == 201 and price_item["item"]["base_paise"] == 100000, "price book item persists")
            status, employees = call(client, base, "POST", "/api/employees/import", {"employees": [{"employee_code": "E-100", "full_name": "Employee One", "email": "one@example.com"}, {"employee_code": "E-101", "full_name": "Employee Two", "email": "two@example.com"}]})
            expect(status == 200 and employees["imported"] == 2, "employee bulk import reports row results")
            status, policy = call(client, base, "POST", "/api/policies", {"name": "Night travel policy", "rules": {"approval_required": True}})
            expect(status == 201 and policy["item"]["name"] == "Night travel policy", "travel policy persists")
            status, document = call(client, base, "POST", "/api/documents", {"entity_type": "driver", "entity_id": "drv_demo_mahesh", "document_type": "license", "file_name": "license.pdf", "content_type": "application/pdf", "size_bytes": 5000, "expires_at": "2027-09-20"})
            expect(status == 201 and document["item"]["storage_path"].startswith("mock/"), "document metadata is stored through mock storage")
            status, customer = call(client, base, "POST", "/api/customers", {"name": "Feature Customer"})
            status, booking = call(client, base, "POST", "/api/bookings", {"customer_id": customer["item"]["id"], "passenger_name": "Approval Passenger", "pickup": {"label": "Bengaluru Airport"}, "dropoff": {"label": "Whitefield"}})
            booking_id = booking["item"]["id"]
            status, approved = call(client, base, "POST", f"/api/bookings/{booking_id}/approve", {"comment": "Policy approved"})
            expect(status == 200 and approved["item"]["status"] == "approved", "booking approval workflow persists")
            status, assigned = call(client, base, "POST", f"/api/bookings/{booking_id}/assign", {"driver_id": "drv_demo_mahesh", "vehicle_id": "veh_demo_ka03mn4821"})
            expect(status == 200 and assigned["duty"]["status"] == "assigned", "booking assignment workflow persists")
            status, einvoice = call(client, base, "POST", "/api/invoices/inv_demo_2026_083/e-invoice", {})
            expect(status == 200 and einvoice["item"]["irn"].startswith("mock_irn_"), "e-invoice workflow returns a mock IRN and QR payload")
            status, dispatch = call(client, base, "POST", "/api/invoices/inv_demo_2026_083/dispatch", {"channel": "email", "recipient": "finance@example.com"})
            expect(status == 200 and dispatch["dispatch"]["status"] == "queued", "invoice dispatch records a provider action")
            status, notification = call(client, base, "POST", "/api/notifications", {"channel": "email", "recipient": "ops@example.com", "template_key": "booking_assigned"})
            expect(status == 201 and notification["item"]["status"] == "sent", "notification workflow uses a mock provider")
            status, invitation = call(client, base, "POST", "/api/invitations", {"email": "invited.driver@example.com", "role": "driver"})
            expect(status == 201 and invitation["item"]["status"] == "pending" and invitation["item"].get("invite_token"), "organization invitation creates a one-time token")
            _, invited_driver = make_client(base)
            status, driver_signup = call(invited_driver, base, "POST", "/api/auth/signup", {"role": "driver", "full_name": "Invited Driver", "email": "invited.driver@example.com", "password": "driverpass123"})
            expect(status == 201, "invited driver account is created")
            status, accepted = call(invited_driver, base, "POST", "/api/invitations/accept", {"token": invitation["item"]["invite_token"]})
            expect(status == 200 and accepted["organization_id"] == "org_demo_blueorbit", "driver invitation can be accepted")
            status, ticket = call(client, base, "POST", "/api/tickets", {"subject": "Need a replacement vehicle", "priority": "high"})
            expect(status == 201 and ticket["item"]["status"] == "open", "support ticket persists")
            status, privacy = call(client, base, "POST", "/api/privacy/requests", {"request_type": "export", "notes": "Pilot data export"})
            expect(status == 201 and privacy["item"]["status"] == "open", "privacy request persists")
            status, report = call(client, base, "GET", "/api/reports/summary")
            expect(status == 200 and "invoices" in report["summary"], "tenant-scoped reports return operational aggregates")
            status, integrations = call(client, base, "GET", "/api/integrations")
            expect(status == 200 and len(integrations["items"]) >= 6, "integration health exposes mock adapters")
            status, audit = call(client, base, "GET", "/api/audit")
            expect(status == 200 and audit["count"] >= 1, "audit history is queryable")
            status, settings = call(client, base, "PATCH", "/api/settings", {"settings": {"language": "en-IN", "low_bandwidth": True}})
            expect(status == 200 and settings["item"]["settings"]["low_bandwidth"] is True, "workspace settings persist")
            print("RESULT feature surface smoke test passed")
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill()
            if process.stdout: process.stdout.close()


if __name__ == "__main__":
    main()
