#!/usr/bin/env python3
"""End-to-end smoke test for the One Fleet Live local domain APIs."""

from __future__ import annotations
import sys

import os
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

from backend_smoke_test import call, expect, free_port, make_client

ROOT = Path(__file__).resolve().parent


def main() -> None:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="axiom-fleet-domain-") as temp_dir:
        db_path = Path(temp_dir) / "axiom.sqlite3"
        env = os.environ.copy()
        env.update({"AXIOM_TEST_FIXTURES": "1", "PORT": str(port), "AXIOM_DB_PATH": str(db_path)})
        process = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            health = None
            for _ in range(50):
                try:
                    status, health = call(make_client(base)[1], base, "GET", "/api/health")
                    if status == 200:
                        break
                except Exception:
                    pass
                time.sleep(0.1)
            if not health or health.get("storage") != "sqlite":
                raise RuntimeError("domain backend did not start")

            jar, client = make_client(base)
            status, login = call(client, base, "POST", "/api/auth/login", {"email": "admin@blueorbit.in", "password": "motion2026"})
            expect(status == 200 and login["user"]["role"] == "vendor", "domain test authenticates vendor")

            status, customers = call(client, base, "GET", "/api/customers")
            expect(status == 200 and customers["count"] >= 1, "customer collection is scoped and readable")
            status, customer = call(client, base, "POST", "/api/customers", {"name": "Domain Test Customer", "email": "domain@example.com"})
            expect(status == 201 and customer["item"]["name"] == "Domain Test Customer", "customer creation persists")

            status, booking = call(client, base, "POST", "/api/bookings", {"customer_id": customer["item"]["id"], "passenger_name": "Test Passenger", "pickup": {"label": "BKC"}, "dropoff": {"label": "Airport T2"}, "duty_type": "airport"})
            expect(status == 201 and booking["item"]["status"] == "requested", "booking creation persists")
            booking_id = booking["item"]["id"]

            status, duty = call(client, base, "POST", "/api/duties", {"booking_id": booking_id})
            expect(status == 201 and duty["item"]["status"] == "draft", "duty creation persists")
            duty_id = duty["item"]["id"]

            status, calculation = call(client, base, "POST", f"/api/duties/{duty_id}/calculate", {"base_paise": 100000, "distance_km": 30, "per_km_paise": 1800, "duration_minutes": 90, "per_hour_paise": 2400, "tax_rate_bps": 1800})
            expect(status == 200 and calculation["calculation"]["total_paise"] == 185968, "duty calculation is persisted in paise")

            status, invoice = call(client, base, "POST", "/api/invoices", {"duty_id": duty_id})
            expect(status == 201 and invoice["item"]["status"] == "draft", "invoice is generated from duty proof")
            invoice_id = invoice["item"]["id"]

            status, issued = call(client, base, "PATCH", f"/api/invoices/{invoice_id}", {"status": "issued"})
            expect(status == 200 and issued["item"]["status"] == "issued", "invoice can be issued")

            status, payment = call(client, base, "POST", "/api/payments", {"invoice_id": invoice_id, "amount_paise": 185968, "mode": "manual", "idempotency_key": "domain-test-payment-1"})
            expect(status == 201 and payment["invoice"]["status"] == "paid", "payment updates invoice collection state")

            status, overview = call(client, base, "GET", "/api/overview")
            expect(status == 200 and overview["duties"].get("draft", 0) >= 1, "overview aggregates operational state")
            print("RESULT domain smoke test passed")
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
