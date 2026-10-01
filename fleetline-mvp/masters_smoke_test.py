#!/usr/bin/env python3
"""Smoke coverage for the first-class Masters workspace local API slice."""

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
    jar = CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def call(opener, base: str, method: str, route: str, payload: dict | None = None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(f"{base}{route}", data=body, method=method, headers={"Content-Type": "application/json"} if body else {})
    try:
        with opener.open(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode())


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print("PASS", message)


def main() -> None:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="axiom-masters-") as temp_dir:
        env = os.environ.copy()
        env.update({"AXIOM_TEST_FIXTURES": "1", "PORT": str(port), "AXIOM_DB_PATH": str(Path(temp_dir) / "masters.sqlite3")})
        process = subprocess.Popen(["python3", "server.py"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            for _ in range(50):
                try:
                    if call(client(base), base, "GET", "/api/health")[0] == 200:
                        break
                except Exception:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("Masters test backend did not start")

            operator = client(base)
            status, login = call(operator, base, "POST", "/api/auth/login", {"email": "admin@blueorbit.in", "password": "motion2026"})
            expect(status == 200 and login["user"]["role"] == "vendor", "operator can enter the Masters API")

            vehicle = {"registration_number": "KA 01 UX 2026", "vehicle_type": "sedan", "vehicle_group": "Executive sedan", "make_model": "Honda City", "year": 2024, "city": "Bengaluru", "fuel_type": "EV", "seating_capacity": 4, "luggage_capacity": 2, "ownership_type": "owned", "branch_name": "Whitefield", "gps_provider": "Mock GPS", "rc_expiry": "2027-01-01", "insurance_expiry": "2026-12-01", "puc_expiry": "2026-11-01"}
            status, created = call(operator, base, "POST", "/api/vehicles", vehicle)
            expect(status == 201 and created["item"]["vehicle_group"] == "Executive sedan", "vehicle master stores identity and group")
            expect(created["item"]["seating_capacity"] == 4 and created["item"]["fuel_type"] == "EV", "vehicle master stores capacity and fuel")
            vehicle_id = created["item"]["id"]

            status, duplicate = call(operator, base, "POST", "/api/vehicles", vehicle)
            expect(status == 409 and duplicate["code"] == "duplicate_vehicle", "duplicate registration is rejected per tenant")

            status, updated = call(operator, base, "PATCH", f"/api/vehicles/{vehicle_id}", {"vehicle_group": "SUV", "seating_capacity": 6, "status": "inactive"})
            expect(status == 200 and updated["item"]["vehicle_group"] == "SUV", "vehicle master supports audited edits")
            expect(updated["item"]["seating_capacity"] == 6 and updated["item"]["status"] == "inactive", "vehicle operational fields update")

            status, suppliers = call(operator, base, "GET", "/api/suppliers?limit=50")
            expect(status == 200 and isinstance(suppliers.get("items"), list), "supplier register is readable")
            status, supplier = call(operator, base, "POST", "/api/suppliers", {"name": "UX Test Mobility", "email": "ops@ux-test.example", "supplier_type": "company"})
            expect(status == 201 and supplier["item"]["name"] == "UX Test Mobility", "supplier register can create a record")

            status, branch = call(operator, base, "POST", "/api/branches", {"code": "BLR-WF", "name": "Whitefield dispatch", "city": "Bengaluru", "address": {"label": "ITPL Main Road"}})
            expect(status == 201 and branch["item"]["code"] == "BLR-WF", "branch register can create a dispatch centre")

            print("RESULT Masters smoke test passed")
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
