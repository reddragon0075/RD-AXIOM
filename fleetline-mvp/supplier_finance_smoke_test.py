#!/usr/bin/env python3
"""Focused smoke coverage for supplier purchase and fleet finance workflows."""

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
    with tempfile.TemporaryDirectory(prefix="axiom-fleet-supplier-finance-") as temp_dir:
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
            status, signup = call(client, base, "POST", "/api/auth/signup", {"role": "vendor", "email": "supplier.finance@example.com", "password": "StrongPass123!", "full_name": "Supplier Finance Owner", "organization_name": "Supplier Finance Mobility", "city": "Bengaluru"})
            expect(status == 201, "supplier finance authenticates a tenant operator")
            status, supplier = call(client, base, "POST", "/api/suppliers", {"name": "Trusted Mobility Supplier", "email": "supplier@example.com", "city": "Bengaluru"})
            expect(status == 201, "supplier finance supplier is tenant-owned")
            status, driver = call(client, base, "POST", "/api/drivers", {"full_name": "Payroll Driver", "city": "Bengaluru", "status": "available"})
            expect(status == 201, "payroll driver is tenant-owned")
            status, vehicle = call(client, base, "POST", "/api/vehicles", {"registration_number": "KA01SF0001", "vehicle_group": "sedan", "city": "Bengaluru", "status": "available"})
            expect(status == 201, "fuel vehicle is tenant-owned")
            past_due = (datetime.now(timezone.utc) - timedelta(days=10)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            status, bill = call(client, base, "POST", "/api/supplier-bills", {"supplier_id": supplier["item"]["id"], "bill_number": "SUP-001", "subtotal_paise": 80000, "tax_paise": 14400, "total_paise": 94400, "due_at": past_due, "status": "captured"})
            expect(status == 200 and bill["item"]["total_paise"] == 94400, "supplier bill is captured with immutable amount evidence")
            status, purchase = call(client, base, "POST", "/api/supplier-purchases", {"supplier_id": supplier["item"]["id"], "purchase_reference": "PO-SF-001", "amount_paise": 94400, "due_at": past_due, "idempotency_key": "purchase-1"})
            expect(status == 200 and purchase["item"]["amount_paise"] == 94400, "supplier purchase order is persisted")
            status, purchase_replay = call(client, base, "POST", "/api/supplier-purchases", {"supplier_id": supplier["item"]["id"], "purchase_reference": "IGNORED", "amount_paise": 1, "idempotency_key": "purchase-1"})
            expect(status == 200 and purchase_replay.get("idempotent") is True, "supplier purchase replay is idempotent")
            status, ageing = call(client, base, "GET", "/api/supplier-ageing")
            expect(status == 200 and sum(bucket["count"] for bucket in ageing["buckets"].values()) == 1, "supplier ageing is tenant-scoped")
            status, fuel = call(client, base, "POST", "/api/fuel-entries", {"vehicle_id": vehicle["item"]["id"], "driver_id": driver["item"]["id"], "fuel_station": "Bengaluru Fuel Point", "fuel_type": "petrol", "quantity_litres": 20, "amount_paise": 220000, "odometer_km": 42000, "idempotency_key": "fuel-1"})
            expect(status == 200 and fuel["item"]["quantity_millilitres"] == 20000, "fuel entry stores normalized quantity and evidence")
            status, cash = call(client, base, "POST", "/api/petty-cash/entries", {"driver_id": driver["item"]["id"], "direction": "debit", "category": "toll", "amount_paise": 12000, "note": "Electronic toll", "idempotency_key": "cash-1"})
            expect(status == 200 and cash["item"]["status"] == "submitted", "petty cash entry is recorded")
            status, allowance = call(client, base, "POST", "/api/driver-allowances", {"driver_id": driver["item"]["id"], "category": "meal", "amount_paise": 18000, "period_start": "2026-09-01", "period_end": "2026-09-30", "status": "approved", "idempotency_key": "allowance-1"})
            expect(status == 200 and allowance["item"]["status"] == "approved", "driver allowance is evidence-backed")
            status, payroll = call(client, base, "POST", "/api/payroll/runs", {"period_start": "2026-09-01", "period_end": "2026-09-30", "lines": [{"driver_id": driver["item"]["id"], "base_paise": 250000, "deduction_paise": 15000}], "idempotency_key": "payroll-1"})
            expect(status == 200 and payroll["item"]["net_paise"] == 253000 and len(payroll["item"]["lines"]) == 1, "payroll run calculates approved allowances and deductions")
            status, payroll_replay = call(client, base, "POST", "/api/payroll/runs", {"period_start": "2026-09-01", "period_end": "2026-09-30", "lines": [], "idempotency_key": "payroll-1"})
            expect(status == 200 and payroll_replay.get("idempotent") is True, "payroll run replay is idempotent")
            status, lines = call(client, base, "GET", f"/api/payroll/runs/{payroll['item']['id']}/lines")
            expect(status == 200 and len(lines["items"]) == 1, "payroll lines are queryable")
            status, settlement = call(client, base, "POST", "/api/supplier-settlements/generate", {"supplier_id": supplier["item"]["id"], "period_start": "2020-01-01", "period_end": "2099-12-31"})
            expect(status == 200 and settlement["item"]["gross_paise"] == 94400 and settlement["item"]["bill_count"] == 1, "supplier settlement aggregates payable bills")
            print("RESULT supplier fleet finance smoke test passed")
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill()
            if process.stdout: process.stdout.close()


if __name__ == "__main__": main()
