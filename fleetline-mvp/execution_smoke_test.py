#!/usr/bin/env python3
"""Driver execution, proof, tracking and offline replay smoke test."""

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
    with tempfile.TemporaryDirectory(prefix="axiom-fleet-execution-") as temp_dir:
        env = os.environ.copy()
        env.update({"AXIOM_TEST_FIXTURES": "1", "PORT": str(port), "AXIOM_DB_PATH": str(Path(temp_dir) / "axiom.sqlite3")})
        process = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                try:
                    status, _ = call(make_client(base)[1], base, "GET", "/api/health")
                    if status == 200:
                        break
                except Exception:
                    pass
                time.sleep(0.1)

            vendor_jar, vendor = make_client(base)
            status, vendor_login = call(vendor, base, "POST", "/api/auth/login", {"email": "admin@blueorbit.in", "password": "motion2026"})
            expect(status == 200, "execution test authenticates vendor")
            driver_jar, driver = make_client(base)
            status, driver_signup = call(driver, base, "POST", "/api/auth/signup", {
                "role": "driver", "full_name": "Execution Driver", "email": "execution.driver@example.com",
                "password": "driverpass123", "phone": "+919900000001", "city": "Mumbai", "license_number": "MH012026000001"
            })
            expect(status == 201 and driver_signup["user"]["role"] == "driver", "execution driver account is created")
            driver_user_id = driver_signup["user"]["id"]
            call(driver, base, "POST", "/api/auth/logout")

            status, customer = call(vendor, base, "POST", "/api/customers", {"name": "Execution Customer"})
            status, booking = call(vendor, base, "POST", "/api/bookings", {"customer_id": customer["item"]["id"], "passenger_name": "Offline Passenger", "pickup": {"label": "BKC"}, "dropoff": {"label": "Airport"}})
            status, driver_row = call(vendor, base, "POST", "/api/drivers", {"user_id": driver_user_id, "full_name": "Execution Driver", "phone": "+919900000001", "license_number": "MH012026000001", "city": "Mumbai"})
            status, duty = call(vendor, base, "POST", "/api/duties", {"booking_id": booking["item"]["id"], "driver_id": driver_row["item"]["id"]})
            expect(status == 201 and duty["item"]["status"] == "assigned", "duty is assigned to a driver")
            duty_id = duty["item"]["id"]

            status, driver_login = call(driver, base, "POST", "/api/auth/login", {"email": "execution.driver@example.com", "password": "driverpass123"})
            expect(status == 200 and driver_login["user"]["organization"]["id"] == "org_demo_blueorbit", "driver session is organization-linked")
            status, driver_duties = call(driver, base, "GET", "/api/duties")
            expect(status == 200 and any(item["id"] == duty_id for item in driver_duties["items"]), "driver sees assigned duties only")

            status, started = call(driver, base, "PATCH", f"/api/duties/{duty_id}", {"status": "accepted", "idempotency_key": "exec-status-1"})
            expect(status == 200 and started["item"]["status"] == "accepted", "driver accepts assigned duty")
            status, en_route = call(driver, base, "PATCH", f"/api/duties/{duty_id}", {"status": "en_route", "idempotency_key": "exec-status-2"})
            expect(status == 200 and en_route["item"]["status"] == "en_route", "driver records en route milestone")
            status, replayed = call(driver, base, "POST", "/api/sync/replay", {"device_id": "pixel-test", "operations": [{"idempotency_key": "offline-status-1", "entity_type": "duty", "entity_id": duty_id, "operation": "status_transition", "payload": {"status": "started", "start_odometer": 42010}}]})
            expect(status == 200 and replayed["accepted"] == 1, "offline duty operation replays")
            status, duplicate = call(driver, base, "POST", "/api/sync/replay", {"device_id": "pixel-test", "operations": [{"idempotency_key": "offline-status-1", "entity_type": "duty", "entity_id": duty_id, "operation": "status_transition", "payload": {"status": "started"}}]})
            expect(status == 200 and duplicate["results"][0].get("idempotent") is True, "offline replay is idempotent")
            status, proof = call(driver, base, "POST", f"/api/duties/{duty_id}/proof", {"proof_type": "otp", "otp": "4821", "recipient_name": "Offline Passenger", "idempotency_key": "proof-1"})
            expect(status == 201 and proof["item"]["proof_type"] == "otp", "duty OTP proof is persisted")
            status, point = call(driver, base, "POST", f"/api/duties/{duty_id}/track", {"latitude": 19.0607, "longitude": 72.8631, "accuracy_m": 8, "battery_pct": 76, "idempotency_key": "track-1"})
            expect(status == 201 and point["item"]["latitude"] == 19.0607, "route location point is persisted")
            status, expense = call(driver, base, "POST", f"/api/duties/{duty_id}/expenses", {"category": "toll", "amount_paise": 24000, "note": "Eastern Freeway", "idempotency_key": "expense-1"})
            expect(status == 201 and expense["item"]["amount_paise"] == 24000, "driver expense is persisted")
            status, bounded_expense = call(driver, base, "POST", f"/api/duties/{duty_id}/expenses", {"category": "toll", "amount_paise": 100000001, "idempotency_key": "expense-too-large"})
            expect(status == 400 and bounded_expense.get("code") == "amount_limit_exceeded", "driver expense ceiling is enforced server-side")
            status, invalid_category = call(driver, base, "POST", f"/api/duties/{duty_id}/expenses", {"category": "cash_advance", "amount_paise": 1000, "idempotency_key": "expense-category"})
            expect(status == 400 and invalid_category.get("code") == "validation_error", "driver expense category allowlist is enforced")
            status, invalid_otp = call(driver, base, "POST", f"/api/duties/{duty_id}/proof", {"proof_type": "otp", "otp": "12x", "idempotency_key": "proof-invalid"})
            expect(status == 400 and invalid_otp.get("code") == "validation_error", "driver OTP format is enforced server-side")
            print("RESULT driver execution smoke test passed")
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
