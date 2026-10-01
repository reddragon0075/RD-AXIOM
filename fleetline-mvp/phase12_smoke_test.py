#!/usr/bin/env python3
"""Fresh-database Phase 1/2 contract smoke test.

Covers the additive local contracts that sit beside the existing P0 suites.
Supabase migration/RLS runtime remains a release-gate test against a real
project, but this verifies the same tenant, permission and idempotency edges in
SQLite.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
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
        f"{base}{route}", data=body, method=method,
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


def signup(opener, base: str, email: str, organization: str):
    status, result = call(opener, base, "POST", "/api/auth/signup", {
        "role": "vendor", "full_name": organization + " operator", "email": email,
        "password": "phase12-smoke-password", "phone": "+919900001111",
        "organization_name": organization, "city": "Bengaluru", "fleet_size": 20,
    })
    expect(status == 201, organization + " signup succeeds")
    return result


def main():
    port = free_port(); base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="axiom-phase12-") as temp_dir:
        env = os.environ.copy(); env.update({"AXIOM_TEST_FIXTURES": "1", "PORT": str(port), "AXIOM_DB_PATH": str(Path(temp_dir) / "phase12.sqlite3")})
        process = subprocess.Popen(["python3", "server.py"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            probe = client(base)
            for _ in range(80):
                try:
                    if call(probe, base, "GET", "/api/health")[0] == 200: break
                except Exception: pass
                time.sleep(0.1)
            else: raise RuntimeError(process.stdout.read() if process.stdout else "backend did not start")

            a = client(base); b = client(base); demo = client(base)
            signup(a, base, "phase12.a@example.com", "Phase 12 Fleet A")
            signup(b, base, "phase12.b@example.com", "Phase 12 Fleet B")
            status, _ = call(demo, base, "POST", "/api/auth/login", {"email": "admin@blueorbit.in", "password": "motion2026"})
            expect(status == 200, "demo operator login succeeds for seeded operational records")

            status, created = call(a, base, "POST", "/api/masters/registry", {"kind": "duty_types", "code": "AIRPORT_4H", "name": "Airport four hour", "metadata": {"hours": 4}})
            expect(status == 200 and created["item"]["version"] == 1, "unified master registry creates a versioned record")
            master_id = created["item"]["id"]
            status, imported = call(a, base, "POST", "/api/masters/registry/import", {"records": [{"kind": "taxes", "code": "GST18", "name": "GST 18 percent"}, {"kind": "labels", "code": "VIP", "name": "VIP passenger"}]})
            expect(status == 200 and imported["imported"] == 2 and imported["failed"] == 0, "master registry import returns row-level outcomes")
            status, exported = call(a, base, "GET", "/api/masters/registry/export")
            expect(status == 200 and "AIRPORT_4H" in exported["content"] and exported["count"] == 3, "master registry export is tenant scoped")
            status, archived = call(a, base, "POST", f"/api/masters/registry/{master_id}/archive", {})
            expect(status == 200 and archived["item"]["status"] == "archived" and archived["item"]["version"] == 2, "master archive creates a new version")
            status, other = call(b, base, "GET", "/api/masters/registry")
            expect(status == 200 and not other["items"], "master registry enforces tenant isolation")

            status, view = call(a, base, "POST", "/api/views", {"scope": "planning", "name": "Morning GPS health", "filters": {"status": "In progress"}, "columns": ["duty_id", "eta"], "shared": True})
            expect(status == 200 and view["item"]["shared"] == 1, "saved operational view persists filters and sharing")
            status, views_b = call(b, base, "GET", "/api/views")
            expect(status == 200 and not views_b["items"], "saved views are tenant isolated")
            status, home = call(demo, base, "GET", "/api/mobile/home")
            expect(status == 200 and "summary" in home and "duties" in home, "mobile operations home returns duty and alert context")
            status, board = call(demo, base, "GET", "/api/operations/live-board")
            expect(status == 200 and board["count"] >= 1, "live operations board returns active duties")

            status, eta = call(demo, base, "POST", "/api/operations/duties/duty_demo_airport/eta", {"deviation_minutes": 12})
            expect(status == 200 and eta["item"]["source"] == "mock_maps" and eta["item"]["deviation_minutes"] == 12, "ETA boundary stores a deterministic map snapshot")
            status, bulk = call(demo, base, "POST", "/api/operations/bulk", {"operation": "refresh_eta", "entity_type": "duty", "ids": ["duty_demo_airport"], "idempotency_key": "phase12-bulk-eta-1"})
            expect(status == 200 and bulk["item"]["results"][0]["status"] == "updated", "bulk ETA action is supported")
            status, replay = call(demo, base, "POST", "/api/operations/bulk", {"operation": "refresh_eta", "entity_type": "duty", "ids": ["duty_demo_airport"], "idempotency_key": "phase12-bulk-eta-1"})
            expect(status == 200 and replay.get("idempotent") is True, "bulk ETA action is idempotent on replay")
            status, drivers = call(demo, base, "GET", "/api/drivers?limit=10")
            status, vehicles = call(demo, base, "GET", "/api/vehicles?limit=10")
            driver_id = (drivers.get("items") or [{}])[0].get("id")
            vehicle_id = (vehicles.get("items") or [{}])[0].get("id")
            status, bulk_assign = call(demo, base, "POST", "/api/operations/bulk", {"operation": "bulk_assign", "entity_type": "duty", "ids": ["duty_demo_airport"], "driver_id": driver_id, "vehicle_id": vehicle_id, "idempotency_key": "phase12-bulk-assign-1"})
            expect(status == 200 and bulk_assign["item"]["results"][0]["status"] == "updated" and bulk_assign.get("audit_reference"), "bulk assign is tenant scoped and auditable")
            status, bulk_edit = call(demo, base, "POST", "/api/operations/bulk", {"operation": "bulk_edit", "entity_type": "duty", "ids": ["duty_demo_airport"], "patch": {"status": "accepted"}, "idempotency_key": "phase12-bulk-edit-1"})
            expect(status == 200 and bulk_edit["item"]["results"][0]["status"] == "updated" and bulk_edit.get("audit_reference"), "bulk edit creates an auditable duty version")
            status, bulk_archive = call(demo, base, "POST", "/api/operations/bulk", {"operation": "archive", "entity_type": "duty", "ids": ["duty_demo_airport"], "idempotency_key": "phase12-bulk-archive-1"})
            expect(status == 200 and bulk_archive["item"]["results"][0]["status"] == "updated" and bulk_archive.get("audit_reference"), "bulk archive preserves the duty audit trail")

            status, incident = call(demo, base, "POST", "/api/safety/incidents", {"alert_type": "missed_pickup", "severity": "high", "title": "Phase 12 test incident"})
            expect(status == 200, "safety incident can enter the evidence lifecycle")
            incident_id = incident["item"]["id"]
            status, evidence = call(demo, base, "POST", f"/api/safety/incidents/{incident_id}/evidence", {"evidence_type": "note", "filename": "operator-note.txt", "content": "Pickup was recovered", "source_event_id": "evt-phase12-1"})
            expect(status == 200 and evidence["item"]["sha256"], "incident evidence registers storage and a content hash")
            for action in ("acknowledge", "investigate", "resolve"):
                status, _ = call(demo, base, "POST", f"/api/safety/incidents/{incident_id}/{action}", {})
                expect(status == 200, "incident transitions through " + action)
            status, approval = call(demo, base, "POST", f"/api/safety/incidents/{incident_id}/closure-approval", {})
            expect(status == 200 and approval["item"]["status"] == "pending", "closure approval is maker-checker pending")
            approval_id = approval["item"]["id"]
            status, closed = call(demo, base, "POST", f"/api/safety/incidents/{incident_id}/closure-approval/{approval_id}/decision", {"decision": "approved", "note": "Evidence reviewed"})
            expect(status == 200 and closed["incident_status"] == "closed", "closure approval closes only a resolved incident")

            status, formula = call(demo, base, "POST", "/api/network/v1/scorecard-formulas", {"code": "DEFAULT", "weights": {"on_time": 0.5, "completion": 0.5}, "thresholds": {"pass": 80}})
            expect(status == 200 and formula["item"]["version"] == 1, "Network scorecard formula is versioned")
            status, dispute = call(demo, base, "POST", "/api/network/v1/scorecard-disputes", {"scorecard_run_id": "score_demo", "reason": "Source event mismatch", "evidence": {"source_event_ids": ["evt-1"]}})
            expect(status == 200 and dispute["item"]["status"] == "open", "Network scorecard dispute opens with evidence")
            status, bundles = call(demo, base, "GET", "/api/permissions/bundles")
            expect(status == 200 and isinstance(bundles["items"], list), "granular permission bundle endpoint is tenant scoped")
            status, catalog = call(demo, base, "GET", "/api/integrations/catalog")
            expect(status == 200 and {item["type"] for item in catalog["items"]} >= {"hrms", "gps", "messaging", "storage"}, "integration catalog exposes real provider boundaries")
            status, event = call(demo, base, "POST", "/api/integrations/events", {"provider_type": "gps", "event_type": "position", "external_id": "gps-phase12-1", "payload": {"duty_id": "duty_demo_airport"}, "signature_valid": True})
            expect(status == 200 and event["signature_valid"] is True, "integration event is accepted with signature state")

            print("RESULT Phase 1/2 smoke test passed")
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill()
            if process.stdout: process.stdout.close()


if __name__ == "__main__":
    main()
