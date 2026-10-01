#!/usr/bin/env python3
"""Focused regression coverage for the Axiom exception-first action center."""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

from backend_smoke_test import call, expect, free_port, make_client

ROOT = Path(__file__).resolve().parent


def wait_for_health(base: str, client) -> None:
    for _ in range(60):
        try:
            if call(client, base, "GET", "/api/health")[0] == 200:
                return
        except Exception:
            pass
        time.sleep(0.1)
    raise AssertionError("local server did not become healthy")


def main() -> None:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="axiom-fleet-actions-") as temp_dir:
        env = os.environ.copy()
        env.update({"PORT": str(port), "AXIOM_DB_PATH": str(Path(temp_dir) / "axiom.sqlite3"), "AXIOM_ALLOW_DEMO_ACCOUNT": "0"})
        process = subprocess.Popen(["python3", "server.py"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            _, client = make_client(base)
            wait_for_health(base, client)
            status, signup = call(client, base, "POST", "/api/auth/signup", {
                "role": "vendor", "email": "actions.one@example.com", "password": "StrongPass123!",
                "full_name": "Action Operator", "organization_name": "Action Mobility", "city": "Bengaluru",
            })
            expect(status == 201 and signup["user"]["organization"], "action center tenant authenticates")
            status, booking = call(client, base, "POST", "/api/bookings", {
                "booking_reference": "ACT-001", "passenger_name": "Action Passenger", "scheduled_at": "2026-10-05T10:00:00Z",
                "pickup": {"label": "Indiranagar"}, "dropoff": {"label": "Airport"}, "duty_type": "airport",
            })
            expect(status == 201, "action center has a canonical unassigned booking")

            status, center = call(client, base, "GET", "/api/workspace/next-actions?limit=20")
            expect(status == 200 and center["summary"]["contract_version"] == "2026-10-01", "action center returns a versioned explainable summary")
            actions = center["items"]
            unassigned = next((item for item in actions if item["id"] == f"booking_unassigned:{booking['item']['id']}"), None)
            expect(unassigned is not None and unassigned["blocking"] is True and unassigned["source"] == "domain_bookings", "action center points to canonical source records and explains blocking dispatch")
            expect(all("token" not in str(item).lower() for item in actions), "action center does not expose provider or payment secrets")

            status, acknowledged = call(client, base, "POST", f"/api/workspace/next-actions/{unassigned['id']}/status", {
                "status": "acknowledged", "note": "Dispatcher owns this before the morning shift.",
            })
            expect(status == 200 and acknowledged["item"]["status"] == "acknowledged", "operator can acknowledge an action without mutating the source booking")
            status, after_ack = call(client, base, "GET", "/api/workspace/next-actions?limit=20")
            ack_item = next(item for item in after_ack["items"] if item["id"] == unassigned["id"])
            expect(ack_item["status"] == "acknowledged" and ack_item["entity_id"] == booking["item"]["id"], "acknowledgement remains visible with source identity")

            status, snoozed = call(client, base, "POST", f"/api/workspace/next-actions/{unassigned['id']}/status", {"status": "snoozed"})
            expect(status == 200 and snoozed["item"]["snooze_until"], "operator can snooze an action with a server-side expiry")
            status, after_snooze = call(client, base, "GET", "/api/workspace/next-actions?limit=20")
            expect(status == 200 and not any(item["id"] == unassigned["id"] for item in after_snooze["items"]), "snoozed actions leave the active queue without deleting source data")

            status, resolved = call(client, base, "POST", f"/api/workspace/next-actions/{unassigned['id']}/status", {"status": "resolved", "note": "Assignment completed in the dispatch board."})
            expect(status == 200 and resolved["item"]["status"] == "resolved", "operator can resolve an action with an audit-backed state")
            status, final_center = call(client, base, "GET", "/api/workspace/next-actions?limit=20")
            expect(status == 200 and not any(item["id"] == unassigned["id"] for item in final_center["items"]), "resolved actions are removed from the active queue")

            _, second_client = make_client(base)
            status, second_signup = call(second_client, base, "POST", "/api/auth/signup", {
                "role": "vendor", "email": "actions.two@example.com", "password": "StrongPass123!",
                "full_name": "Other Operator", "organization_name": "Other Mobility", "city": "Mysuru",
            })
            expect(status == 201, "second action-center tenant authenticates")
            status, isolated = call(second_client, base, "GET", "/api/workspace/next-actions?limit=20")
            expect(status == 200 and not any(item["entity_id"] == booking["item"]["id"] for item in isolated["items"]), "action center preserves tenant isolation")
            print("RESULT command center smoke test passed")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
