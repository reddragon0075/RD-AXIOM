#!/usr/bin/env python3
"""Focused smoke coverage for booking intake, deterministic allotment and closure evidence."""

from __future__ import annotations
import sys

import os
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend_smoke_test import call, expect, free_port, make_client

ROOT = Path(__file__).resolve().parent


def main() -> None:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="axiom-fleet-operations-") as temp_dir:
        env = os.environ.copy()
        env.update({"PORT": str(port), "AXIOM_DB_PATH": str(Path(temp_dir) / "axiom.sqlite3"), "AXIOM_ALLOW_DEMO_ACCOUNT": "0"})
        process = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(60):
                try:
                    status, _ = call(make_client(base)[1], base, "GET", "/api/health")
                    if status == 200:
                        break
                except Exception:
                    pass
                time.sleep(0.1)
            _, client = make_client(base)
            status, signup = call(client, base, "POST", "/api/auth/signup", {"role": "vendor", "email": "operations.parity@example.com", "password": "StrongPass123!", "full_name": "Operations Owner", "organization_name": "Operations Mobility", "city": "Bengaluru"})
            expect(status == 201, "operations parity authenticates a tenant operator")
            status, driver = call(client, base, "POST", "/api/drivers", {"full_name": "Available Driver", "city": "Bengaluru", "status": "available"})
            expect(status == 201, "availability driver is tenant-owned")
            status, vehicle = call(client, base, "POST", "/api/vehicles", {"registration_number": "KA01OP0001", "vehicle_group": "sedan", "city": "Bengaluru", "status": "available"})
            expect(status == 201, "availability vehicle is tenant-owned")
            scheduled = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            status, batch = call(client, base, "POST", "/api/bookings/batches", {"mode": "bulk", "idempotency_key": "batch-1", "rows": [{"booking_reference": "BULK-001", "passenger_name": "Bulk One", "scheduled_at": scheduled, "pickup": {"label": "Bengaluru", "city": "Bengaluru"}, "dropoff": {"label": "Airport"}}, {"booking_reference": "BULK-002", "passenger_name": "Bulk Two", "scheduled_at": scheduled, "pickup": {"label": "Bengaluru", "city": "Bengaluru"}, "dropoff": {"label": "Station"}}]})
            expect(status == 201 and batch["item"]["mode"] == "bulk" and batch["item"]["generated_count"] == 2, "bulk booking batch creates row-level bookings")
            status, replay = call(client, base, "POST", "/api/bookings/batches", {"mode": "bulk", "idempotency_key": "batch-1", "rows": []})
            expect(status == 201 and replay.get("idempotent") is True, "booking batch replay is idempotent")
            status, itinerary = call(client, base, "POST", "/api/bookings/batches", {"mode": "itinerary", "passenger_name": "Itinerary Passenger", "scheduled_at": scheduled, "pickup": {"label": "Bengaluru"}, "segments": [{"dropoff": {"label": "Airport"}}, {"pickup": {"label": "Airport"}, "dropoff": {"label": "Hotel"}}]})
            expect(status == 201 and itinerary["item"]["requested_count"] == 2, "itinerary batch creates one booking per segment")
            status, monthly = call(client, base, "POST", "/api/bookings/batches", {"mode": "monthly", "start_at": scheduled, "occurrences": 3, "template": {"passenger_name": "Monthly Passenger", "pickup": {"label": "Bengaluru"}, "dropoff": {"label": "Office"}}})
            expect(status == 201 and monthly["item"]["generated_count"] == 3, "monthly batch generates calendar occurrences")
            booking_id = batch["item"]["rows"][0]["booking_id"]
            status, availability = call(client, base, "POST", "/api/availability/evaluate", {"booking_id": booking_id, "scheduled_at": scheduled, "duration_hours": 2, "city": "Bengaluru", "vehicle_group": "sedan"})
            expect(status == 200 and availability["eligible"] is True and availability["deterministic"] is True, "availability evaluation is deterministic")
            status, allotment = call(client, base, "POST", f"/api/bookings/{booking_id}/allot", {"idempotency_key": "allot-1", "driver_id": driver["item"]["id"], "vehicle_id": vehicle["item"]["id"]})
            expect(status == 201 and allotment["decision"]["status"] == "assigned" and allotment["duty"]["status"] == "assigned", "allotment creates a duty and capacity holds")
            duty_id = allotment["duty"]["id"]
            status, closure = call(client, base, "POST", f"/api/duties/{duty_id}/close", {"start_odometer": 1000, "end_odometer": 1042, "required_evidence": ["signature", "duty_slip"], "evidence": [{"evidence_type": "signature", "content": "signed-by-passenger"}, {"evidence_type": "duty_slip", "storage_path": "mock://duty-slip.pdf"}, {"evidence_type": "toll", "metadata": {"amount_paise": 12000}}]})
            expect(status == 201 and closure["duty"]["status"] == "completed" and closure["item"]["completeness"]["complete"] is True, "duty closure stores complete evidence bundle")
            status, closure_replay = call(client, base, "GET", f"/api/duties/{duty_id}/closure")
            expect(status == 200 and len(closure_replay["item"]["evidence"]) == 3, "duty closure evidence is queryable")
            print("RESULT operations parity smoke test passed")
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
