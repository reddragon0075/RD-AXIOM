#!/usr/bin/env python3
"""Focused security contract checks for the dependency-free local boundary."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def request(base: str, method: str, route: str, payload=None, headers=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request_headers = {"Content-Type": "application/json"} if body is not None else {}
    request_headers.update(headers or {})
    req = urllib.request.Request(f"{base}{route}", data=body, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            raw = response.read().decode("utf-8")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {"raw": raw}
            return response.status, parsed, dict(response.headers)
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"raw": raw}
        return error.code, parsed, dict(error.headers)


def expect(condition, message):
    if not condition:
        raise AssertionError(message)
    print("PASS", message)


def main():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="axiom-fleet-security-") as temp:
        db = Path(temp) / "security.sqlite3"
        secret = "security-test-webhook-secret"
        env = os.environ.copy()
        env.update({"AXIOM_TEST_FIXTURES": "1", 
            "PORT": str(port),
            "AXIOM_DB_PATH": str(db),
            "AXIOM_ENV": "production",
            "AXIOM_PAYMENT_WEBHOOK_SECRET": secret,
        })
        process = subprocess.Popen(["python3", "server.py"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            base = f"http://127.0.0.1:{port}"
            for _ in range(80):
                try:
                    if request(base, "GET", "/api/health")[0] == 200:
                        break
                except Exception:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("production server did not start")

            status, health, _ = request(base, "GET", "/api/health")
            expect(status == 200 and health.get("ok") is True, "production boundary starts healthy")
            status, demo, _ = request(base, "POST", "/api/auth/login", {"email": "admin@blueorbit.in", "password": "motion2026"})
            expect(status == 401, "known demo credentials are disabled in production")
            status, private_source, _ = request(base, "GET", "/server.py")
            expect(status == 404, "source files are not exposed by the production static boundary")
            status, private_db, _ = request(base, "GET", "/data/axiom_fleet.sqlite3")
            expect(status == 404, "SQLite runtime data is not exposed by the production static boundary")

            signup = {"role": "vendor", "full_name": "Production Security User", "email": "security@example.com", "password": "security-password", "phone": "+919900009999", "organization_name": "Production Security Fleet", "city": "Bengaluru", "fleet_size": 2}
            status, created, headers = request(base, "POST", "/api/auth/signup", signup)
            expect(status == 201 and created.get("user", {}).get("organization", {}).get("id"), "production signup creates an isolated tenant")
            status, logged, headers = request(base, "POST", "/api/auth/login", {"email": signup["email"], "password": signup["password"]})
            cookie_header = headers.get("Set-Cookie", "")
            cookie = cookie_header.split(";", 1)[0]
            expect(status == 200 and "Secure" in cookie_header and cookie, "production sessions are Secure cookies")
            organization_id = created["user"]["organization"]["id"]

            link_payload = {"invoice_id": "invoice-security-1", "amount_paise": 1000}
            status, link, _ = request(base, "POST", "/api/payment-links", link_payload, {"Cookie": cookie})
            expect(status in {200, 201} and link.get("item", {}).get("short_code"), "authenticated production payment-link creation remains available")
            short_code = link["item"]["short_code"]
            status, blocked_payment, _ = request(base, "POST", f"/api/public/payment-links/{short_code}", {"action": "pay"})
            expect(status == 503 and blocked_payment.get("code") == "payment_provider_required", "mock self-payment is disabled in production")

            webhook = {"event_id": "security-event-1", "provider": "configured_provider", "event_type": "payment.succeeded", "organization_id": organization_id, "payment_link_id": link["item"]["id"], "provider_reference": "provider-ref-1"}
            raw = json.dumps(webhook).encode("utf-8")
            signature = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
            status, processed, _ = request(base, "POST", "/api/webhooks/payments", webhook, {"X-Payment-Signature": signature})
            expect(status == 200 and processed.get("status") == "processed", "valid HMAC payment webhook is processed")
            status, replay, _ = request(base, "POST", "/api/webhooks/payments", webhook, {"X-Payment-Signature": signature})
            expect(status == 200 and replay.get("status") == "duplicate", "payment webhook replay is harmless")
            status, invalid, _ = request(base, "POST", "/api/webhooks/payments", {**webhook, "event_id": "security-event-2"}, {"X-Payment-Signature": "bad"})
            expect(status == 401 and invalid.get("code") == "invalid_webhook_signature", "invalid payment webhook signature is rejected")
            print("RESULT security smoke test passed")
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
