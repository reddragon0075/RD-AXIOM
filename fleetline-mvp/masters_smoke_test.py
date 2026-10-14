#!/usr/bin/env python3
"""Smoke coverage for the first-class Masters workspace local API slice."""

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
        process = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

            vehicle = {"registration_number": "KA 01 UX 2026", "manufacturer": "Honda", "model": "City", "vehicle_type": "sedan", "vehicle_group": "Executive sedan", "year": 2024, "city": "Bengaluru", "fuel_type": "EV", "seating_capacity": 4, "luggage_capacity": 2, "ownership_type": "owned", "branch_name": "Whitefield", "gps_provider": "Mock GPS", "rc_expiry": "2027-01-01", "insurance_expiry": "2026-12-01", "puc_expiry": "2026-11-01"}
            status, created = call(operator, base, "POST", "/api/vehicles", vehicle)
            expect(status == 201 and created["item"]["vehicle_group"] == "Executive sedan", "vehicle master stores identity and group")
            expect(created["item"]["manufacturer"] == "Honda" and created["item"]["model"] == "City", "vehicle master stores separate manufacturer and model")
            expect(created["item"]["make_model"] == "Honda City", "make_model derived automatically from manufacturer and model")
            expect(created["item"]["seating_capacity"] == 4 and created["item"]["fuel_type"] == "EV", "vehicle master stores capacity and fuel")
            vehicle_id = created["item"]["id"]

            status, duplicate = call(operator, base, "POST", "/api/vehicles", vehicle)
            expect(status == 409 and duplicate["code"] == "duplicate_vehicle", "duplicate registration is rejected per tenant")

            status, updated = call(operator, base, "PATCH", f"/api/vehicles/{vehicle_id}", {"manufacturer": "Tata Motors", "model": "Nexon EV", "vehicle_group": "SUV", "seating_capacity": 6, "status": "inactive"})
            expect(status == 200 and updated["item"]["vehicle_group"] == "SUV", "vehicle master supports audited edits")
            expect(updated["item"]["manufacturer"] == "Tata Motors" and updated["item"]["model"] == "Nexon EV", "manufacturer and model update cleanly")
            expect(updated["item"]["make_model"] == "Tata Motors Nexon EV", "make_model re-synced on manufacturer/model update")
            expect(updated["item"]["seating_capacity"] == 6 and updated["item"]["status"] == "inactive", "vehicle operational fields update")

            status, mfrs = call(operator, base, "GET", "/api/manufacturers?limit=50")
            expect(status == 200 and len(mfrs.get("items", [])) >= 10, "manufacturers register auto-seeds default OEMs")
            mfr_names = [m["name"] for m in mfrs.get("items", [])]
            expect("Maruti Suzuki" in mfr_names and "Toyota" in mfr_names and "Tata Motors" in mfr_names, "key OEM brands present in masters")

            status, new_mfr = call(operator, base, "POST", "/api/manufacturers", {"name": "Volvo Cars", "code": "VOLVO", "country": "Sweden"})
            expect(status == 201 and new_mfr["item"]["name"] == "Volvo Cars", "can add custom manufacturer in masters")

            status, suppliers = call(operator, base, "GET", "/api/suppliers?limit=50")
            expect(status == 200 and isinstance(suppliers.get("items"), list), "supplier register is readable")
            status, supplier = call(operator, base, "POST", "/api/suppliers", {"name": "UX Test Mobility", "email": "ops@ux-test.example", "supplier_type": "company"})
            expect(status == 201 and supplier["item"]["name"] == "UX Test Mobility", "supplier register can create a record")

            status, branch = call(operator, base, "POST", "/api/branches", {"code": "BLR-WF", "name": "Whitefield dispatch", "city": "Bengaluru", "address": {"label": "ITPL Main Road"}})
            expect(status == 201 and branch["item"]["code"] == "BLR-WF", "branch register can create a dispatch centre")

            status, drv_own = call(operator, base, "POST", "/api/drivers", {"full_name": "Kavita Rao", "phone": "+919800011111", "driver_type": "own", "city": "Bengaluru"})
            expect(status == 201 and drv_own["item"]["driver_type"] == "own", "driver master supports own driver type")

            status, drv_supplier = call(operator, base, "POST", "/api/drivers", {"full_name": "Ramesh Kumar", "phone": "+919800022222", "driver_type": "supplier", "city": "Bengaluru"})
            expect(status == 201 and drv_supplier["item"]["driver_type"] == "supplier", "driver master supports supplier driver type")

            status, drv_dco = call(operator, base, "POST", "/api/drivers", {"full_name": "Suresh DCO", "phone": "+919800033333", "driver_type": "dco", "vehicle_registration": "KA01AB9999", "vehicle_group": "SUV"})
            expect(status == 201 and drv_dco["item"]["driver_type"] == "dco" and drv_dco["item"]["vehicle_registration"] == "KA01AB9999", "driver master supports DCO driver type")

            status, drv_updated = call(operator, base, "PATCH", f"/api/drivers/{drv_own['item']['id']}", {"driver_type": "dco", "vehicle_registration": "KA05CD1234"})
            expect(status == 200 and drv_updated["item"]["driver_type"] == "dco" and drv_updated["item"]["vehicle_registration"] == "KA05CD1234", "driver master can update driver type to DCO via PATCH")

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
