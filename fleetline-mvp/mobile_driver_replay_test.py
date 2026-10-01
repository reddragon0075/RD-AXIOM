#!/usr/bin/env python3
"""Local HTTP contract for native-driver reconnect replay and push dispatch."""

from __future__ import annotations

import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from backend_smoke_test import call, make_client

ROOT = Path(__file__).resolve().parent


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print("PASS", message)


def main() -> None:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="axiom-fleet-driver-replay-") as temp_dir:
        env = os.environ.copy()
        env.update({"AXIOM_TEST_FIXTURES": "1", "PORT": str(port), "AXIOM_DB_PATH": str(Path(temp_dir) / "axiom.sqlite3")})
        process = subprocess.Popen(["python3", "server.py"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            for _ in range(60):
                try:
                    if call(make_client(base)[1], base, "GET", "/api/health")[0] == 200:
                        break
                except Exception:
                    pass
                time.sleep(0.1)

            _, vendor = make_client(base)
            _, driver = make_client(base)
            status, vendor_result = call(vendor, base, "POST", "/api/auth/signup", {
                "role": "vendor", "full_name": "Replay Vendor", "email": "replay.vendor@example.com",
                "password": "strongpass123", "organization_name": "Replay Fleet", "city": "Bengaluru",
            })
            expect(status == 201, "replay test creates a vendor")
            status, driver_result = call(driver, base, "POST", "/api/auth/signup", {
                "role": "driver", "full_name": "Replay Driver", "email": "replay.driver@example.com",
                "password": "strongpass123", "city": "Bengaluru",
            })
            expect(status == 201, "replay test creates a driver")
            driver_user_id = driver_result["user"]["id"]
            status, driver_master = call(vendor, base, "POST", "/api/drivers", {"full_name": "Replay Driver", "user_id": driver_user_id, "city": "Bengaluru"})
            expect(status == 201, "vendor links the driver account")
            driver_master_id = driver_master["item"]["id"]
            call(vendor, base, "POST", "/api/devices", {"device_id": "control-test-1", "platform": "web", "push_token": "control-token"})
            call(driver, base, "POST", "/api/auth/login", {"email": "replay.driver@example.com", "password": "strongpass123"})
            status, device = call(driver, base, "POST", "/api/devices", {"device_id": "android-test-1", "platform": "android", "push_token": "driver-token"})
            expect(status == 200 and device.get("item", {}).get("push_token") == "driver-token", "driver push token is registered")

            status, booking = call(vendor, base, "POST", "/api/bookings", {"passenger_name": "Replay Passenger", "pickup": {"label": "A"}, "dropoff": {"label": "B"}})
            expect(status == 201, "replay test creates a booking")
            status, duty = call(vendor, base, "POST", "/api/duties", {"booking_id": booking["item"]["id"], "driver_id": driver_master_id})
            expect(status == 201, "vendor assignment creates a duty")
            duty_id = duty["item"]["id"]
            status, notifications = call(vendor, base, "GET", "/api/notifications")
            assignment = [item for item in notifications["items"] if item["template_key"] == "duty_assigned"]
            expect(status == 200 and assignment and assignment[0]["payload"]["device_id"] == "android-test-1", "assignment dispatch targets the registered driver device")

            operations = [
                {"entity_type": "duty", "entity_id": duty_id, "operation": "status_transition", "payload": {"status": "accepted"}, "idempotency_key": "replay-accepted"},
                {"entity_type": "duty", "entity_id": duty_id, "operation": "status_transition", "payload": {"status": "en_route"}, "idempotency_key": "replay-en-route"},
                {"entity_type": "duty", "entity_id": duty_id, "operation": "status_transition", "payload": {"status": "started"}, "idempotency_key": "replay-started"},
                {"entity_type": "duty", "entity_id": duty_id, "operation": "proof", "payload": {"proof_type": "otp", "proof_data": {"code": "1234", "note": "handoff"}}, "idempotency_key": "replay-proof"},
                {"entity_type": "duty", "entity_id": duty_id, "operation": "expense", "payload": {"category": "Parking", "amount_paise": 1000, "note": "offline"}, "idempotency_key": "replay-expense"},
                {"entity_type": "duty", "entity_id": duty_id, "operation": "sos", "payload": {"alert_type": "sos", "severity": "critical", "idempotency_key": "replay-sos"}, "idempotency_key": "replay-sos-operation"},
            ]
            status, first_replay = call(driver, base, "POST", "/api/sync/replay", {"device_id": "android-test-1", "operations": operations})
            expect(status == 200 and first_replay["failed"] == 0, "offline duty, proof, expense and SOS actions replay successfully")
            status, duplicate_replay = call(driver, base, "POST", "/api/sync/replay", {"device_id": "android-test-1", "operations": operations})
            expect(status == 200 and duplicate_replay["failed"] == 0 and all(item.get("idempotent") for item in duplicate_replay["results"]), "duplicate replay is idempotent")
            status, notifications = call(vendor, base, "GET", "/api/notifications")
            sos = [item for item in notifications["items"] if item["template_key"] == "sos_alert"]
            expect(status == 200 and sos and sos[0]["payload"]["device_id"] == "control-test-1", "SOS dispatch targets the registered control-room device")
            print("RESULT native driver replay test passed")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            if process.stdout:
                process.stdout.close()


if __name__ == "__main__":
    main()
