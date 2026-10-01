#!/usr/bin/env python3
"""End-to-end smoke test for the local Axiom Fleet identity backend."""

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


def make_client(base: str) -> tuple[CookieJar, object]:
    jar = CookieJar()
    return jar, urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def call(opener, base: str, method: str, route: str, payload: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request_headers = {"Content-Type": "application/json"} if body is not None else {}
    request_headers.update(headers or {})
    request = urllib.request.Request(
        f"{base}{route}",
        data=body,
        method=method,
        headers=request_headers,
    )
    try:
        with opener.open(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"raw": raw}
        return error.code, body


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print("PASS", message)


def main() -> None:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="axiom-fleet-backend-") as temp_dir:
        db_path = Path(temp_dir) / "axiom.sqlite3"
        env = os.environ.copy()
        env.update({"AXIOM_TEST_FIXTURES": "1", "PORT": str(port), "AXIOM_DB_PATH": str(db_path)})
        process = subprocess.Popen(
            ["python3", "server.py"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            for _ in range(50):
                try:
                    status, health = call(make_client(base)[1], base, "GET", "/api/health")
                    if status == 200:
                        break
                except Exception:
                    pass
                time.sleep(0.1)
            else:
                output = process.stdout.read() if process.stdout else ""
                raise RuntimeError(f"backend did not start: {output}")

            expect(health.get("storage") == "sqlite", "health endpoint reports SQLite storage")

            vendor_jar, vendor = make_client(base)
            status, vendor_result = call(vendor, base, "POST", "/api/auth/signup", {
                "role": "vendor",
                "full_name": "Nisha Fleet",
                "email": "nisha.vendor@example.com",
                "password": "strongpass123",
                "phone": "+919876543210",
                "organization_name": "Nisha Mobility",
                "city": "Bengaluru",
                "timezone": "America/Los_Angeles",
                "gstin": "29ABCDE1234F1Z5",
                "fleet_size": 48,
            })
            expect(status == 201 and vendor_result["user"]["role"] == "vendor", "vendor signup creates an authenticated account")
            expect(vendor_result["user"]["organization"]["name"] == "Nisha Mobility", "vendor organization is stored")
            expect(vendor_result["user"]["profile"]["fleet_size"] == 48, "vendor fleet profile is stored")
            expect(vendor_result["user"]["profile"]["timezone"] == "America/Los_Angeles", "vendor timezone is stored")

            status, me = call(vendor, base, "GET", "/api/auth/me")
            expect(status == 200 and me["user"]["email"] == "nisha.vendor@example.com", "vendor session reads the current user")
            status, updated = call(vendor, base, "PATCH", "/api/auth/me", {"city": "Mysuru", "fleet_size": 52, "timezone": "Europe/London"})
            expect(status == 200 and updated["user"]["profile"]["city"] == "Mysuru", "profile update persists")
            expect(updated["user"]["profile"]["fleet_size"] == 52, "profile update changes fleet size")
            expect(updated["user"]["profile"]["timezone"] == "Europe/London", "profile timezone update persists")

            status, duplicate = call(vendor, base, "POST", "/api/auth/signup", {
                "role": "driver", "full_name": "Duplicate", "email": "nisha.vendor@example.com", "password": "strongpass123"
            })
            expect(status == 409 and duplicate["code"] == "email_in_use", "duplicate email is rejected")

            status, _ = call(vendor, base, "POST", "/api/auth/logout")
            expect(status == 200, "vendor logout succeeds")
            status, _ = call(vendor, base, "GET", "/api/auth/me")
            expect(status == 401, "logged-out session cannot read protected profile")

            driver_jar, driver = make_client(base)
            status, driver_result = call(driver, base, "POST", "/api/auth/signup", {
                "role": "driver",
                "full_name": "Arjun Driver",
                "email": "arjun.driver@example.com",
                "password": "driverpass123",
                "phone": "+919812345678",
                "city": "Pune",
                "timezone": "Asia/Kolkata",
                "license_number": "KA0120260001234",
            })
            expect(status == 201 and driver_result["user"]["role"] == "driver", "driver signup creates an authenticated account")
            expect(driver_result["user"]["organization"] is None, "driver can register without an organization")
            expect(driver_result["user"]["profile"]["license_number"] == "KA0120260001234", "driver license profile is stored")
            expect(driver_result["user"]["profile"]["timezone"] == "Asia/Kolkata", "driver timezone is stored")
            call(driver, base, "POST", "/api/auth/logout")

            corporate_jar, corporate = make_client(base)
            status, corporate_result = call(corporate, base, "POST", "/api/auth/signup", {
                "role": "corporate",
                "full_name": "Meera Travel",
                "email": "meera.corporate@example.com",
                "password": "corporatepass123",
                "phone": "+919899887766",
                "organization_name": "Northstar Technologies",
                "city": "Mumbai",
                "employee_count": 850,
            })
            expect(status == 201 and corporate_result["user"]["role"] == "corporate", "corporate signup creates an authenticated account")
            expect(corporate_result["user"]["organization"]["type"] == "corporate", "corporate organization is stored")
            expect(corporate_result["user"]["profile"]["employee_count"] == 850, "corporate employee profile is stored")
            call(corporate, base, "POST", "/api/auth/logout")

            status, login_result = call(vendor, base, "POST", "/api/auth/login", {
                "email": "nisha.vendor@example.com", "password": "strongpass123"
            })
            expect(status == 200 and login_result["user"]["role"] == "vendor", "stored vendor can log in again")
            status, _ = call(vendor, base, "POST", "/api/auth/login", {
                "email": "nisha.vendor@example.com", "password": "wrong-password"
            })
            expect(status == 401, "invalid credentials are rejected")

            call(vendor, base, "POST", "/api/auth/logout")
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            connection = sqlite3.connect(db_path)
            try:
                counts = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("organizations", "users", "profiles", "audit_events")}
            finally:
                connection.close()
            expect(counts["organizations"] == 3, "seed, vendor and corporate organizations are persisted")
            expect(counts["users"] == 4, "seed plus vendor, driver and corporate users are persisted")
            expect(counts["profiles"] == 4, "role profiles are persisted")
            expect(counts["audit_events"] >= 8, "authentication and profile events are audited")
            print("RESULT backend smoke test passed")
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
