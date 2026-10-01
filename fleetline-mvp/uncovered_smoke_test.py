#!/usr/bin/env python3
"""Focused smoke coverage for the recently completed import and recovery contracts."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

from backend_smoke_test import call, expect, free_port, make_client

ROOT = Path(__file__).resolve().parent


def main() -> None:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="axiom-fleet-uncovered-") as temp_dir:
        env = os.environ.copy()
        env.update({"AXIOM_TEST_FIXTURES": "1", "PORT": str(port), "AXIOM_DB_PATH": str(Path(temp_dir) / "axiom.sqlite3"), "AXIOM_EXPOSE_RESET_TOKEN": "1"})
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
                    status, _ = call(make_client(base)[1], base, "GET", "/api/health")
                    if status == 200:
                        break
                except Exception:
                    pass
                time.sleep(0.1)
            else:
                output = process.stdout.read() if process.stdout else ""
                raise RuntimeError(f"backend did not start: {output}")

            _, client = make_client(base)
            status, login = call(client, base, "POST", "/api/auth/login", {"email": "admin@blueorbit.in", "password": "motion2026"})
            expect(status == 200 and login["user"]["organization"]["id"] == "org_demo_blueorbit", "focused test authenticates the seeded vendor")

            status, imported = call(client, base, "POST", "/api/bookings/import", {"bookings": [
                {
                    "booking_reference": "CSV-FOCUSED-001",
                    "passenger_name": "Imported Passenger",
                    "passenger_phone": "+919900001111",
                    "pickup": {"label": "Kempegowda International Airport"},
                    "dropoff": {"label": "Whitefield",
                    },
                    "scheduled_at": "2026-09-21T09:30:00+05:30",
                    "duty_type": "airport",
                },
                {"customer_id": "customer-does-not-exist"},
            ]})
            expect(status == 200, "booking import endpoint accepts a batch")
            expect(imported["imported"] == 1 and imported["failed"] == 1, "booking import returns imported and failed row counts")
            expect(imported["rows"][0]["status"] == "imported" and imported["rows"][1]["status"] == "error", "booking import returns row-level outcomes")
            expect(imported["rows"][0]["item"]["booking_reference"] == "CSV-FOCUSED-001", "imported booking preserves the source reference")

            status, known_reset = call(client, base, "POST", "/api/auth/password-reset", {"email": "admin@blueorbit.in"})
            status_unknown, unknown_reset = call(client, base, "POST", "/api/auth/password-reset", {"email": "nobody@example.com"})
            expect(status == 202 and status_unknown == 202, "password reset requests return an accepted response")
            expect(known_reset["message"] == unknown_reset["message"] and known_reset.get("debug_token"), "password reset does not disclose account existence")
            status, confirmed = call(client, base, "POST", "/api/auth/password-reset/confirm", {"token": known_reset["debug_token"], "password": "new-bill-password"})
            expect(status == 200, "password reset token changes the password")
            status, replayed = call(client, base, "POST", "/api/auth/password-reset/confirm", {"token": known_reset["debug_token"], "password": "another-password"})
            expect(status == 400 and replayed.get("code") == "invalid_reset_token", "password reset token is one-time")
            login_client = make_client(base)[1]
            status, relogin = call(login_client, base, "POST", "/api/auth/login", {"email": "admin@blueorbit.in", "password": "new-bill-password"})
            expect(status == 200, "new password can authenticate")

            status, audit = call(login_client, base, "GET", "/api/audit")
            expect(status == 200 and any(row["action"] == "auth.password_reset_requested" for row in audit["items"]) and any(row["action"] == "auth.password_reset_confirmed" for row in audit["items"]), "password reset lifecycle is audited")
            status, private_file = call(client, base, "GET", "/server.py")
            expect(status == 404, "private source files are not statically exposed")
            status, private_data = call(client, base, "GET", "/data/axiom_fleet.sqlite3")
            expect(status == 404, "runtime database is not statically exposed")
            status, bad_origin = call(client, base, "POST", "/api/auth/login", {"email": "admin@blueorbit.in", "password": "wrong"}, headers={"Origin": "https://evil.example"})
            expect(status == 403, "cross-origin mutating requests are rejected")
            print("RESULT focused uncovered smoke test passed")
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
