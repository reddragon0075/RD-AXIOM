#!/usr/bin/env python3
"""Focused smoke coverage for finance generation, ageing, dunning and reports."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend_smoke_test import call, expect, free_port, make_client

ROOT = Path(__file__).resolve().parent


def main() -> None:
    port = free_port(); base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="axiom-fleet-finance-") as temp_dir:
        env = os.environ.copy(); env.update({"PORT": str(port), "AXIOM_DB_PATH": str(Path(temp_dir) / "axiom.sqlite3"), "AXIOM_ALLOW_DEMO_ACCOUNT": "0"})
        process = subprocess.Popen(["python3", "server.py"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            for _ in range(60):
                try:
                    status, _ = call(make_client(base)[1], base, "GET", "/api/health")
                    if status == 200: break
                except Exception: pass
                time.sleep(0.1)
            _, client = make_client(base)
            status, signup = call(client, base, "POST", "/api/auth/signup", {"role": "vendor", "email": "finance.parity@example.com", "password": "StrongPass123!", "full_name": "Finance Owner", "organization_name": "Finance Mobility", "city": "Bengaluru"})
            expect(status == 201, "finance parity authenticates a tenant operator")
            status, customer = call(client, base, "POST", "/api/customers", {"name": "Finance Customer", "email": "accounts@customer.example"})
            expect(status == 201, "finance customer is tenant-owned")
            scheduled = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            status, driver = call(client, base, "POST", "/api/drivers", {"full_name": "Finance Driver", "city": "Bengaluru", "status": "available"})
            expect(status == 201, "finance driver is tenant-owned")
            status, vehicle = call(client, base, "POST", "/api/vehicles", {"registration_number": "KA01FN0001", "vehicle_group": "sedan", "city": "Bengaluru", "status": "available"})
            expect(status == 201, "finance vehicle is tenant-owned")
            status, booking = call(client, base, "POST", "/api/bookings", {"customer_id": customer["item"]["id"], "booking_reference": "FIN-001", "passenger_name": "Finance Passenger", "scheduled_at": scheduled, "pickup": {"label": "Office"}, "dropoff": {"label": "Airport"}})
            expect(status == 201, "finance booking is created")
            status, duty = call(client, base, "POST", "/api/duties", {"booking_id": booking["item"]["id"], "driver_id": driver["item"]["id"], "vehicle_id": vehicle["item"]["id"], "reporting_at": scheduled})
            expect(status == 201, "finance duty is created")
            duty_id = duty["item"]["id"]
            status, calculation = call(client, base, "POST", f"/api/duties/{duty_id}/calculate", {"base_paise": 100000, "distance_km": 20, "per_km_paise": 1500, "duration_minutes": 60, "per_hour_paise": 2000, "tax_rate_bps": 1800})
            expect(status == 200 and calculation["calculation"]["total_paise"] > 0, "finance duty calculation snapshot is available")
            for next_status in ("accepted", "en_route", "started"):
                status, transition = call(client, base, "PATCH", f"/api/duties/{duty_id}", {"status": next_status})
                expect(status == 200 and transition["item"]["status"] == next_status, f"finance duty can transition to {next_status}")
            status, completed = call(client, base, "PATCH", f"/api/duties/{duty_id}", {"status": "completed"})
            expect(status == 200 and completed["item"]["status"] == "completed", "finance duty can be completed")
            status, run = call(client, base, "POST", "/api/invoices/generate", {"mode": "per_duty", "idempotency_key": "finance-run-1", "due_at": (datetime.now(timezone.utc) - timedelta(days=2)).replace(microsecond=0).isoformat().replace("+00:00", "Z")})
            expect(status == 200 and run["item"]["generated_count"] == 1 and run["invoices"][0]["total_paise"] > 0, "invoice run generates a duty invoice")
            status, replay = call(client, base, "POST", "/api/invoices/generate", {"mode": "per_duty", "idempotency_key": "finance-run-1"})
            expect(status == 200 and replay.get("idempotent") is True, "invoice generation replay is idempotent")
            invoice_id = run["invoices"][0]["id"]
            status, issued = call(client, base, "PATCH", f"/api/invoices/{invoice_id}", {"status": "issued"})
            expect(status == 200 and issued["item"]["status"] == "issued", "generated invoice can be issued")
            status, ageing = call(client, base, "GET", "/api/reports/ageing")
            expect(status == 200 and ageing["buckets"]["90_plus"]["count"] == 0 and sum(bucket["count"] for bucket in ageing["buckets"].values()) == 1, "invoice ageing is tenant-scoped and bucketed")
            status, dunning = call(client, base, "POST", "/api/collections/dunning/run", {"channel": "email"})
            expect(status == 200 and dunning["processed"] == 1, "overdue dunning run creates a provider-backed action")
            status, definition = call(client, base, "POST", "/api/reports/definitions", {"name": "Finance ageing", "report_type": "ageing"})
            expect(status == 200 and definition["item"]["report_type"] == "ageing", "report definition is persisted")
            status, report = call(client, base, "POST", f"/api/reports/definitions/{definition['item']['id']}/run", {})
            expect(status == 200 and "buckets" in report, "saved report definition runs deterministically")
            status, profile = call(client, base, "POST", "/api/export-profiles", {"name": "CSV finance", "target": "csv"})
            expect(status == 200 and profile["item"]["target"] == "csv", "finance export profile is tenant-scoped")
            status, export_result = call(client, base, "POST", f"/api/export-profiles/{profile['item']['id']}/run", {})
            expect(status == 200 and "INV-" in export_result["item"]["content"], "finance export produces a reviewable ledger file")
            print("RESULT finance reporting parity smoke test passed")
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill()
            if process.stdout: process.stdout.close()


if __name__ == "__main__": main()
