#!/usr/bin/env python3
"""Focused smoke coverage for tenant-managed templates, suppression and delivery evidence."""

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
    with tempfile.TemporaryDirectory(prefix="axiom-fleet-comms-") as temp_dir:
        env = os.environ.copy(); env.update({"PORT": str(port), "AXIOM_DB_PATH": str(Path(temp_dir) / "axiom.sqlite3"), "AXIOM_ALLOW_DEMO_ACCOUNT": "0"})
        process = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(60):
                try:
                    status, _ = call(make_client(base)[1], base, "GET", "/api/health")
                    if status == 200: break
                except Exception: pass
                time.sleep(0.1)
            _, client = make_client(base)
            status, signup = call(client, base, "POST", "/api/auth/signup", {"role": "vendor", "email": "communications.parity@example.com", "password": "StrongPass123!", "full_name": "Communications Owner", "organization_name": "Communications Mobility", "city": "Bengaluru"})
            expect(status == 201, "communications parity authenticates a tenant operator")
            status, template = call(client, base, "POST", "/api/communications/templates", {"template_key": "booking_confirmed", "name": "Booking confirmed", "channel": "email", "subject": "Booking {{booking_reference}} confirmed", "body": "Hello {{passenger_name}}, your booking {{booking_reference}} is confirmed."})
            expect(status == 200 and template["item"]["version"] == 1 and template["item"]["placeholders_json"] == ["booking_reference", "passenger_name"], "template is versioned and placeholders are validated")
            status, dispatch = call(client, base, "POST", "/api/communications/dispatch", {"template_key": "booking_confirmed", "channel": "email", "recipient": "passenger@example.com", "variables": {"booking_reference": "BK-COMM-001", "passenger_name": "Passenger"}, "idempotency_key": "comm-dispatch-1"})
            expect(status == 200 and dispatch["item"]["status"] in {"queued", "sent", "succeeded"}, "communication dispatch uses the configured provider adapter")
            status, replay = call(client, base, "POST", "/api/communications/dispatch", {"template_key": "booking_confirmed", "channel": "email", "recipient": "passenger@example.com", "variables": {}, "idempotency_key": "comm-dispatch-1"})
            expect(status == 200 and replay.get("idempotent") is True, "communication dispatch replay is idempotent")
            status, suppression = call(client, base, "POST", "/api/communications/suppressions", {"recipient": "suppressed@example.com", "channel": "email", "reason": "user_requested"})
            expect(status == 200 and suppression["item"]["status"] == "active", "communication suppression is tenant-scoped")
            status, suppressed = call(client, base, "POST", "/api/communications/dispatch", {"template_key": "booking_confirmed", "channel": "email", "recipient": "suppressed@example.com", "variables": {"booking_reference": "BK-COMM-002", "passenger_name": "Passenger"}, "idempotency_key": "comm-dispatch-2"})
            expect(status == 200 and suppressed["suppressed"] is True and suppressed["item"]["status"] == "suppressed", "suppression prevents provider dispatch")
            status, replacement = call(client, base, "POST", "/api/communications/templates", {"template_key": "booking_confirmed", "name": "Booking confirmed v2", "channel": "email", "subject": "Booking {{booking_reference}} ready", "body": "Hi {{passenger_name}}, booking {{booking_reference}} is ready."})
            expect(status == 200 and replacement["item"]["version"] == 2, "template changes create an immutable version")
            status, deliveries = call(client, base, "GET", "/api/communications/deliveries")
            expect(status == 200 and len(deliveries["items"]) == 2, "delivery history exposes sent and suppressed evidence")
            print("RESULT communications parity smoke test passed")
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill()
            if process.stdout: process.stdout.close()


if __name__ == "__main__": main()
