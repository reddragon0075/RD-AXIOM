#!/usr/bin/env python3
"""Fresh SQLite contract smoke test for bill extraction and auditable posting."""
from __future__ import annotations
import sys

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


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def client():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def call(opener, base, method, route, payload=None):
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


def expect(condition, message):
    if not condition:
        raise AssertionError(message)
    print("PASS", message)


def signup(opener, base, email, name):
    status, result = call(opener, base, "POST", "/api/auth/signup", {
        "role": "vendor", "full_name": name, "email": email,
        "password": "bill-intelligence-password", "phone": "+919900001111",
        "organization_name": name + " Fleet", "city": "Bengaluru", "fleet_size": 6,
    })
    expect(status == 201 and result.get("user", {}).get("organization"), f"{name} tenant signup succeeds")


def main():
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="axiom-bill-intelligence-") as temp:
        env = os.environ.copy()
        env.update({"AXIOM_TEST_FIXTURES": "1", "PORT": str(port), "AXIOM_DB_PATH": str(Path(temp) / "bills.sqlite3")})
        process = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

            operator = client(); other = client()
            status, login = call(operator, base, "POST", "/api/auth/login", {"email": "admin@blueorbit.in", "password": "motion2026"})
            expect(status == 200 and login["user"]["organization"]["id"] == "org_demo_blueorbit", "demo operator login succeeds")
            status, vehicles = call(operator, base, "GET", "/api/vehicles")
            expect(status == 200 and vehicles["items"], "tenant vehicle master is available")
            vehicle = vehicles["items"][0]

            ocr = """Bengaluru Fuel Stop\nGSTIN: 29ABCDE1234F1Z5\nInvoice No: FS-4921\nDate: 28-09-2026\nVehicle: KA 03 MN 4821\nFuel Type: Diesel\nOdometer: 45210 km\nQuantity: 32.4 L\nRate: 94.20\nTotal: 3052.08\n"""
            payload = {"filename": "FS-4921.jpg", "content_type": "image/jpeg", "ocr_text": ocr, "vehicle_id": vehicle["id"], "idempotency_key": "bill-smoke-1"}
            status, captured = call(operator, base, "POST", "/api/bill-intelligence", payload)
            expect(status == 201 and captured["item"]["status"] == "needs_review", "bill capture creates a reviewable extraction")
            item = captured["item"]
            expect(item["extracted"]["bill_type"] == "fuel" and item["extracted"]["invoice_number"] == "FS-4921", "strict extraction identifies fuel type and invoice number")
            expect(item["vehicle_id"] == vehicle["id"] and item["storage_reference"], "vehicle match and mock storage provenance are visible")
            expect(item["validation"]["auto_post_eligible"] is True and not item["validation"]["errors"], "high-confidence extraction is eligible after human confirmation")

            status, replay = call(operator, base, "POST", "/api/bill-intelligence", payload)
            expect(status == 201 and replay["replayed"] is True and replay["item"]["id"] == item["id"], "capture replay is idempotent")
            duplicate_payload = {**payload, "idempotency_key": "bill-smoke-duplicate"}
            status, duplicate = call(operator, base, "POST", "/api/bill-intelligence", duplicate_payload)
            expect(status == 201 and any(error.get("code") == "duplicate_bill" for error in duplicate["item"]["validation"]["errors"]), "duplicate invoice validation blocks a second bill")
            mismatch_payload = {"filename": "FS-4922.txt", "content_type": "text/plain", "extracted": {"bill_type": "fuel", "vendor_name": "Bengaluru Fuel Stop", "vendor_gstin": "29ABCDE1234F1Z5", "invoice_number": "FS-4922", "invoice_date": "2026-09-28", "vehicle_regd_no_raw": vehicle["registration_number"], "quantity": 10, "rate_per_unit": 120, "amount_fuel": 1000, "total_amount": 1000, "fuel_type": vehicle.get("fuel_type") or "diesel"}, "vehicle_id": vehicle["id"], "idempotency_key": "bill-smoke-mismatch"}
            status, mismatch = call(operator, base, "POST", "/api/bill-intelligence", mismatch_payload)
            expect(status == 201 and any(warning.get("code") == "amount_mismatch" for warning in mismatch["item"]["validation"]["warnings"]), "quantity and rate arithmetic mismatch is surfaced")
            status, rejected = call(operator, base, "POST", f"/api/bill-intelligence/{mismatch['item']['id']}/reject", {"note": "Arithmetic mismatch smoke case"})
            expect(status == 200 and rejected["item"]["status"] == "rejected", "invalid arithmetic evidence can be rejected without posting")
            fuzzy_payload = {"filename": "FS-4923.txt", "content_type": "text/plain", "extracted": {"bill_type": "fuel", "vendor_name": "Bengaluru Fuel Stop", "vendor_gstin": "29ABCDE1234F1Z5", "invoice_number": "FS-4923", "invoice_date": "2026-09-28", "vehicle_regd_no_raw": vehicle["registration_number"][:-1] + "2", "quantity": 10, "rate_per_unit": 94.2, "amount_fuel": 942, "total_amount": 942, "fuel_type": vehicle.get("fuel_type") or "diesel"}, "idempotency_key": "bill-smoke-fuzzy"}
            status, fuzzy = call(operator, base, "POST", "/api/bill-intelligence", fuzzy_payload)
            expect(status == 201 and fuzzy["item"]["validation"]["vehicle_candidates"] and fuzzy["item"]["validation"]["vehicle_candidates"][0]["score"] == 88, "near-match registration is surfaced for explicit cab fallback")
            status, fuzzy_rejected = call(operator, base, "POST", f"/api/bill-intelligence/{fuzzy['item']['id']}/reject", {"note": "Explicit vehicle fallback smoke case"})
            expect(status == 200 and fuzzy_rejected["item"]["status"] == "rejected", "ambiguous vehicle evidence remains reviewable")
            status, posted = call(operator, base, "POST", f"/api/bill-intelligence/{item['id']}/approve", {"vehicle_id": vehicle["id"]})
            expect(status == 200 and posted["item"]["status"] == "posted", "reviewer confirmation posts the bill")
            expect(posted["posted"]["fuel_entry_id"] and posted["posted"]["cost_entry_id"], "posting creates fuel and vehicle-cost records")
            status, detail = call(operator, base, "GET", f"/api/bill-intelligence/{item['id']}")
            expect(status == 200 and {"bill_captured", "fuel_posted", "vehicle_master_updated"}.issubset({event["event_type"] for event in detail["item"]["timeline"]}), "vehicle timeline records source-linked bill events")
            status, summary = call(operator, base, "GET", "/api/bill-intelligence/summary")
            expect(status == 200 and summary["summary"]["posted_count"] == 1 and summary["summary"]["posted_amount"] > 3000, "summary exposes posted count and captured amount")

            status, other_signup = call(other, base, "POST", "/api/auth/signup", {"role": "vendor", "full_name": "Other Fleet", "email": "bill.other@example.com", "password": "bill-intelligence-password", "phone": "+919900001112", "organization_name": "Other Fleet", "city": "Mumbai", "fleet_size": 2})
            expect(status == 201, "second tenant signup succeeds")
            status, isolated = call(other, base, "GET", "/api/bill-intelligence")
            expect(status == 200 and isolated["items"] == [], "bill records are tenant isolated")

            status, undone = call(operator, base, "POST", f"/api/bill-intelligence/{item['id']}/undo", {"note": "Smoke reversal"})
            expect(status == 200 and undone["item"]["status"] == "reversed", "posted bill supports an auditable reversal")
            status, final_detail = call(operator, base, "GET", f"/api/bill-intelligence/{item['id']}")
            expect(status == 200 and final_detail["item"]["timeline"][-1]["event_type"] == "bill_reversed", "reversal is visible in the vehicle timeline")
            print("RESULT Bill intelligence smoke test passed")
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
