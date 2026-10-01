#!/usr/bin/env python3
"""Fresh SQLite contract smoke test for the Phase 3 moat layer."""
from __future__ import annotations

import json
import os
import socket
import sqlite3
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


def client():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def call(opener, base, method, route, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(f"{base}{route}", data=body, method=method, headers={"Content-Type": "application/json"} if body is not None else {})
    try:
        with opener.open(request, timeout=8) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode())


def expect(condition, message):
    if not condition:
        raise AssertionError(message)
    print("PASS", message)


def signup(opener, base, email, name):
    status, result = call(opener, base, "POST", "/api/auth/signup", {
        "role": "vendor", "full_name": name, "email": email, "password": "phase3-smoke-password",
        "phone": "+919900001111", "organization_name": name + " Fleet", "city": "Bengaluru", "fleet_size": 12,
    })
    expect(status == 201 and result.get("user", {}).get("organization"), name + " tenant signup succeeds")


def main():
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="axiom-phase3-") as temp:
        db_path = Path(temp) / "phase3.sqlite3"
        env = os.environ.copy(); env.update({"AXIOM_TEST_FIXTURES": "1", "PORT": str(port), "AXIOM_DB_PATH": str(db_path)})
        process = subprocess.Popen(["python3", "server.py"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            probe = client()
            for _ in range(80):
                try:
                    if call(probe, base, "GET", "/api/health")[0] == 200:
                        break
                except Exception:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError(process.stdout.read() if process.stdout else "backend did not start")

            tenant_a = client(); tenant_b = client(); demo = client()
            signup(tenant_a, base, "phase3.a@example.com", "Phase 3 A")
            signup(tenant_b, base, "phase3.b@example.com", "Phase 3 B")
            status, login = call(demo, base, "POST", "/api/auth/login", {"email": "admin@blueorbit.in", "password": "motion2026"})
            expect(status == 200 and login["user"]["organization"]["id"] == "org_demo_blueorbit", "demo operator login succeeds")

            status, regions = call(tenant_a, base, "GET", "/api/phase3/regions")
            expect(status == 200 and regions["items"][0]["region_code"] == "IN-MH" and len(regions["catalog"]) >= 5, "regional profile and controlled country catalog are tenant scoped")
            status, rejected = call(tenant_a, base, "POST", "/api/phase3/regions", {"country_code": "ZZ", "region_code": "ZZ-XX", "name": "Uncontrolled"})
            expect(status == 400 and rejected["code"] == "validation_error", "unconstrained region codes are rejected")
            status, region = call(tenant_a, base, "POST", "/api/phase3/regions", {"region_code": "IN-KA", "is_default": True})
            expect(status == 200 and region["item"]["is_default"] == 1, "approved region can become the effective default")
            status, localization = call(tenant_a, base, "GET", "/api/phase3/localization")
            expect(status == 200 and localization["item"]["region_code"] == "IN-KA", "localization returns effective region, currency, tax and timezone")

            scenario = {"scenario_name": "Bengaluru peak", "idempotency_key": "phase3-scenario-1", "demand_duties": 40, "avg_distance_km": 18, "waiting_minutes": 12, "service_penalty_pct": 3}
            status, first = call(tenant_a, base, "POST", "/api/phase3/simulations/run", scenario)
            status2, replay = call(tenant_a, base, "POST", "/api/phase3/simulations/run", scenario)
            expect(status == 200 and first["replayed"] is False and status2 == 200 and replay["replayed"] is True, "simulation creation is idempotent and reproducible")
            outputs = first["item"]["outputs"]
            expect(outputs["baseline_total_minor"] >= 0 and "service_level_pct" in outputs and "emissions_kg" in outputs and outputs["assumptions"], "simulation returns cost ranges, service outcome, sustainability and assumptions")
            status, other_simulations = call(tenant_b, base, "GET", "/api/phase3/simulations")
            expect(status == 200 and not other_simulations["items"], "simulation history is tenant isolated")

            status, evaluated = call(demo, base, "POST", "/api/phase3/predictive-alerts/evaluate", {"idempotency_key": "phase3-alert-eval", "minimum_risk_score": 0})
            expect(status == 200 and evaluated["model_version"] == "predictive-v1" and evaluated["items"], "predictive evaluation returns model metadata and alert factors")
            alert_id = evaluated["items"][0]["id"]
            expect(evaluated["items"][0]["factors"] and "source_event_ids" in evaluated["items"][0], "predictive alert is explainable and source-linked")
            status, acknowledged = call(demo, base, "POST", f"/api/phase3/predictive-alerts/{alert_id}/acknowledge", {})
            status2, feedback = call(demo, base, "POST", f"/api/phase3/predictive-alerts/{alert_id}/feedback", {"outcome": "useful", "note": "Smoke test feedback"})
            expect(status == 200 and acknowledged["item"]["status"] == "acknowledged" and status2 == 200 and feedback["outcome"] == "useful", "alert acknowledgement and feedback are auditable")

            status, trips = call(demo, base, "POST", "/api/phase3/sustainability/trips", {"duty_ids": ["duty_demo_airport"], "distance_km": 22})
            expect(status == 200 and trips["items"][0]["factor_version"] == "factor-v1", "sustainability stores versioned duty emissions")
            status, summary = call(demo, base, "GET", "/api/phase3/sustainability/summary")
            expect(status == 200 and summary["total_emissions_kg"] > 0 and "recommendations" in summary, "sustainability summary reports intensity and reduction recommendations")
            status, target = call(demo, base, "POST", "/api/phase3/sustainability/targets", {"scope": "fleet", "period_start": "2026-09-01", "period_end": "2026-09-30", "baseline_kg": 100, "target_kg": 80})
            expect(status == 200 and target["item"]["target_kg"] == 80, "sustainability target is stored with a reporting period")

            # Seed one invite-only graph slice directly beside the canonical
            # Network tables so this smoke covers scorecard/duty projection,
            # not only the empty-state response.
            connection = sqlite3.connect(db_path)
            try:
                now = "2026-09-22T00:00:00Z"
                org = login["user"]["organization"]["id"]
                connection.execute("INSERT INTO domain_network_vendor_profiles(id, organization_id, vendor_organization_id, vendor_name, status, cities_json, service_types_json, vehicle_types_json, capabilities_json, capacity_json, compliance_json, metadata_json, created_at, updated_at) VALUES (?, ?, ?, ?, 'active', ?, '[]', '[]', '[]', '{}', '{}', '{}', ?, ?)", ("p3-smoke-profile", org, "p3-smoke-vendor-org", "Invite-only smoke vendor", '["Bengaluru"]', now, now))
                connection.execute("INSERT INTO domain_network_service_orders(id, organization_id, award_id, contract_id, requirement_id, vendor_profile_id, status, fleet_duty_id, activated_at) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)", ("p3-smoke-order", org, "p3-smoke-award", "p3-smoke-contract", "p3-smoke-requirement", "p3-smoke-profile", "duty_demo_airport", now))
                connection.execute("INSERT INTO domain_network_scorecards(id, organization_id, service_order_id, period_start, period_end, status, metrics_json, evidence_json, created_at) VALUES (?, ?, ?, ?, ?, 'submitted', ?, ?, ?)", ("p3-smoke-scorecard", org, "p3-smoke-order", "2026-09-01", "2026-09-30", '{"on_time": 92, "completion": 98, "safety": 90}', '{"source_event_ids": ["p3-smoke-evidence"]}', now))
                connection.commit()
            finally:
                connection.close()
            status, graph = call(demo, base, "GET", "/api/phase3/vendor-quality/graph")
            graph_types = {node.get("type") for node in graph.get("nodes", [])}
            expect(status == 200 and {"vendor", "service_order", "duty", "scorecard", "evidence"}.issubset(graph_types) and graph["formula_version"] == "vendor-quality-v1", "vendor quality graph links invite-only vendor, service order, duty, scorecard and evidence")
            status, variance = call(demo, base, "POST", "/api/phase3/variance/evaluate", {})
            expect(status == 200 and variance["rule_version"] == "variance-v1" and "items" in variance, "variance scan returns a versioned explainable finding set")
            status, fx = call(tenant_a, base, "POST", "/api/phase3/fx/convert", {"base_currency": "INR", "quote_currency": "AED", "amount_minor": 10000})
            expect(status == 200 and fx["converted_minor"] == 435 and fx["source"] == "mock_fx", "FX conversion is deterministic and mock-labelled")
            status, tax = call(tenant_a, base, "POST", "/api/phase3/tax/preview", {"amount_minor": 100000})
            expect(status == 200 and tax["tax_minor"] == 18000 and tax["tax_regime"] == "GST", "tax preview follows effective regional settings")

            connection = sqlite3.connect(db_path)
            try:
                tables = {row[0] for row in connection.execute("select name from sqlite_master where type='table'")}
                expect({"phase3_predictive_alerts", "phase3_vendor_quality_snapshots", "phase3_simulations", "phase3_variance_findings", "phase3_sustainability_trips", "phase3_regions"}.issubset(tables), "Phase 3 additive tables are initialized in SQLite")
            finally:
                connection.close()
            print("RESULT Phase 3 smoke test passed")
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill()
            if process.stdout: process.stdout.close()


if __name__ == "__main__":
    main()
