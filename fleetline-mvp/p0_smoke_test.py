#!/usr/bin/env python3
"""P0 domain, authorization, transition and tenant-isolation smoke test.

This test intentionally runs against a fresh SQLite database. It is a local
contract test; Supabase/RLS still needs a real project validation run.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def client(base: str):
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def call(opener, base: str, method: str, route: str, payload: dict | None = None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{base}{route}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with opener.open(request, timeout=8) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode())


def expect(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)
    print("PASS", message)


def signup(opener, base, email, name, organization):
    status, result = call(opener, base, "POST", "/api/auth/signup", {
        "role": "vendor",
        "full_name": name,
        "email": email,
        "password": "p0-smoke-password",
        "phone": "+919900001111",
        "organization_name": organization,
        "city": "Bengaluru",
        "fleet_size": 20,
    })
    expect(status == 201, f"{organization} signup succeeds")
    return result


def main():
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="axiom-p0-") as temp_dir:
        env = os.environ.copy()
        env.update({"AXIOM_TEST_FIXTURES": "1", "PORT": str(port), "AXIOM_DB_PATH": str(Path(temp_dir) / "p0.sqlite3")})
        process = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(80):
                try:
                    if call(client(base), base, "GET", "/api/health")[0] == 200:
                        break
                except Exception:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError(process.stdout.read() if process.stdout else "P0 backend did not start")

            anonymous = client(base)
            status, _ = call(anonymous, base, "GET", "/api/masters")
            expect(status == 401, "P0 routes require authentication")

            tenant_a = client(base)
            tenant_b = client(base)
            signup(tenant_a, base, "p0.a@example.com", "P0 Operator A", "P0 Fleet A")
            signup(tenant_b, base, "p0.b@example.com", "P0 Operator B", "P0 Fleet B")

            status, masters = call(tenant_a, base, "GET", "/api/masters")
            expect(status == 200 and "duty_types" in masters["kinds"], "master catalogue exposes P0 kinds")
            status, created_master = call(tenant_a, base, "POST", "/api/masters/duty_types", {"code": "AIRPORT_4H", "name": "Airport four hour", "config": {"hours": 4, "km": 40}})
            expect(status == 200 and created_master["item"]["version"] == 1, "versioned master can be created")
            master_id = created_master["item"]["id"]
            status, duplicate = call(tenant_a, base, "POST", "/api/masters/duty_types", {"code": "AIRPORT_4H", "name": "Duplicate"})
            expect(status == 409 and duplicate["code"] == "duplicate_master", "duplicate master code is rejected")
            status, master_detail = call(tenant_a, base, "GET", f"/api/masters/duty_types/{master_id}")
            expect(status == 200 and len(master_detail["item"]["versions"]) == 1, "master detail exposes an audit version")
            status, other_masters = call(tenant_b, base, "GET", "/api/masters/duty_types")
            expect(status == 200 and not other_masters["items"], "tenant B cannot list tenant A masters")
            status, _ = call(tenant_b, base, "GET", f"/api/masters/duty_types/{master_id}")
            expect(status == 404, "tenant B cannot address tenant A master by identifier")

            status, site = call(tenant_a, base, "POST", "/api/operations/sites", {"code": "BLR-WF", "name": "Whitefield campus", "city": "Bengaluru", "address": {"label": "ITPL"}})
            expect(status == 200, "operations site can be created")
            site_id = site["item"]["id"]
            status, booking = call(tenant_a, base, "POST", "/api/bookings", {"passenger_name": "Asha Rao", "passenger_phone": "+919811122233", "pickup": {"label": "Whitefield"}, "dropoff": {"label": "Airport T2"}, "scheduled_at": "2026-09-23T07:30:00Z", "duty_type": "airport"})
            expect(status == 201, "canonical booking can be created for planning")
            booking_id = booking["item"]["id"]
            status, duty = call(tenant_a, base, "POST", "/api/duties", {"booking_id": booking_id, "reporting_at": "2026-09-23T07:00:00Z"})
            expect(status == 201 and duty["item"]["status"] == "draft", "canonical duty remains the planning source of truth")
            duty_id = duty["item"]["id"]

            status, plan = call(tenant_a, base, "POST", "/api/operations/route-plans", {"plan_date": "2026-09-23", "site_id": site_id, "duty_ids": [duty_id], "max_stops": 40})
            expect(status == 200 and plan["item"]["stops"][0]["duty_id"] == duty_id, "route plan creates an ordered stop")
            plan_id = plan["item"]["id"]
            status, published = call(tenant_a, base, "POST", f"/api/operations/route-plans/{plan_id}/publish", {})
            expect(status == 200 and published["item"]["status"] == "published", "route plan publish is an explicit transition")
            status, assignment = call(tenant_a, base, "POST", "/api/operations/assignments", {"route_plan_id": plan_id, "duty_id": duty_id, "response_deadline": "2026-09-23T06:45:00Z"})
            expect(status == 200 and assignment["item"]["status"] == "offered", "dispatch assignment starts as an offer")
            assignment_id = assignment["item"]["id"]
            status, accepted = call(tenant_a, base, "POST", f"/api/operations/assignments/{assignment_id}/accept", {"idempotency_key": "accept-p0-1"})
            expect(status == 200 and accepted["item"]["status"] == "accepted", "assignment acceptance transition updates the duty")
            status, replay = call(tenant_a, base, "POST", f"/api/operations/assignments/{assignment_id}/accept", {"idempotency_key": "accept-p0-1"})
            expect(status == 200 and replay.get("idempotent") is True, "assignment acceptance replay is idempotent")
            status, safe_replay = call(tenant_a, base, "POST", f"/api/operations/assignments/{assignment_id}/accept", {})
            expect(status == 200 and safe_replay["item"]["status"] == "accepted", "same dispatch state is a safe no-op")
            status, invalid = call(tenant_a, base, "POST", f"/api/operations/assignments/{assignment_id}/reject", {})
            expect(status == 409 and invalid["code"] == "invalid_transition", "invalid dispatch transition is rejected")
            status, _ = call(tenant_b, base, "GET", f"/api/operations/route-plans/{plan_id}")
            expect(status == 404, "tenant B cannot read tenant A route plan")

            status, policy = call(tenant_a, base, "POST", "/api/safety/policies", {"code": "DEFAULT", "name": "Default response rules", "rules": {"critical_minutes": 5, "high_minutes": 15}})
            expect(status == 200 and policy["item"]["version"] == 1, "safety policy is versioned")
            status, incident = call(tenant_a, base, "POST", "/api/safety/incidents", {"duty_id": duty_id, "alert_type": "missed_pickup", "severity": "high", "title": "Pickup missed", "description": "Test incident"})
            expect(status == 200 and incident["item"]["status"] == "open" and incident["item"]["due_at"], "safety incident creates an escalation deadline")
            incident_id = incident["item"]["id"]
            for action, target in (("acknowledge", "acknowledged"), ("investigate", "investigating"), ("resolve", "resolved"), ("close", "closed")):
                status, transitioned = call(tenant_a, base, "POST", f"/api/safety/incidents/{incident_id}/{action}", {})
                expect(status == 200 and transitioned["item"]["status"] == target, f"safety incident transitions to {target}")
            status, _ = call(tenant_b, base, "GET", f"/api/safety/incidents/{incident_id}")
            expect(status == 404, "tenant B cannot read tenant A safety incident")

            status, region = call(tenant_a, base, "POST", "/api/network/v1/regions", {"code": "BLR", "name": "Bengaluru operating region", "cities": ["Bengaluru"]})
            expect(status == 200 and region["item"]["status"] == "active", "Network region can be created in the closed module")
            status, regions_b = call(tenant_b, base, "GET", "/api/network/v1/regions")
            expect(status == 200 and not regions_b["items"], "Network region list is tenant isolated")

            status, permissions = call(tenant_a, base, "GET", "/api/permissions")
            expect(status == 200 and "route_plans.write" in permissions["permissions"], "permission bundle is visible")
            status, grant = call(tenant_a, base, "POST", "/api/permissions/grants", {"role": "vendor", "permission": "safety.incidents.manage", "allowed": False})
            expect(status == 200 and grant["allowed"] is False, "tenant permission override can be denied")
            status, denied = call(tenant_a, base, "POST", "/api/safety/incidents", {"alert_type": "manual", "severity": "low", "title": "Denied after grant"})
            expect(status == 403 and denied["code"] == "permission_denied", "permission denial is enforced by the backend")

            print("RESULT P0 smoke test passed")
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
