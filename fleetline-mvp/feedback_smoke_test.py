#!/usr/bin/env python3
"""Focused smoke coverage for feedback forms and service recovery."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

from backend_smoke_test import call, expect, free_port, make_client

ROOT = Path(__file__).resolve().parent


def main() -> None:
    port = free_port(); base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="axiom-fleet-feedback-") as temp_dir:
        env = os.environ.copy(); env.update({"PORT": str(port), "AXIOM_DB_PATH": str(Path(temp_dir) / "axiom.sqlite3"), "AXIOM_ALLOW_DEMO_ACCOUNT": "0"})
        process = subprocess.Popen(["python3", "server.py"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            for _ in range(60):
                try:
                    status, _ = call(make_client(base)[1], base, "GET", "/api/health")
                    if status == 200: break
                except Exception: pass
                time.sleep(0.1)
            _, client = make_client(base)
            status, signup = call(client, base, "POST", "/api/auth/signup", {"role": "vendor", "email": "feedback.parity@example.com", "password": "StrongPass123!", "full_name": "Feedback Owner", "organization_name": "Feedback Mobility", "city": "Bengaluru"})
            expect(status == 201, "feedback parity authenticates a tenant operator")
            status, form = call(client, base, "POST", "/api/feedback/forms", {"name": "Post duty experience", "trigger_event": "duty_completed", "questions": [{"key": "cleanliness", "label": "How clean was the vehicle?", "type": "rating", "required": True}, {"key": "comment", "label": "Tell us more", "type": "text"}]})
            expect(status == 200 and form["item"]["status"] == "draft", "feedback form persists configurable questions")
            status, active = call(client, base, "POST", f"/api/feedback/forms/{form['item']['id']}/publish", {})
            expect(status == 200 and active["item"]["status"] == "active", "feedback form has an explicit publish state")
            status, request = call(client, base, "POST", "/api/feedback/requests", {"form_id": form["item"]["id"], "recipient": "passenger@example.com", "expires_at": "2099-12-31T00:00:00Z"})
            expect(status == 200 and request["item"]["status"] == "sent" and request.get("action_token"), "feedback request creates an expiring action token")
            status, response = call(client, base, "POST", f"/api/feedback/requests/{request['item']['id']}/submit", {"rating": 2, "answers": {"cleanliness": "2", "comment": "Vehicle was late and not clean"}, "tags": ["late", "cleanliness"], "comment": "Please call me"})
            expect(status == 200 and response["item"]["sentiment"] == "negative", "feedback response validates required questions and derives sentiment")
            status, replay = call(client, base, "POST", f"/api/feedback/requests/{request['item']['id']}/submit", {"rating": 1, "answers": {}})
            expect(status == 200 and replay.get("idempotent") is True, "feedback submission replay is idempotent")
            status, recovery = call(client, base, "POST", "/api/feedback/recovery", {"response_id": response["item"]["id"], "action_type": "call_customer", "notes": "Escalate within one business day"})
            expect(status == 200 and recovery["item"]["status"] == "open", "negative feedback creates a service recovery action")
            status, resolved = call(client, base, "POST", f"/api/feedback/recovery/{recovery['item']['id']}/resolve", {"notes": "Passenger contacted and issue closed"})
            expect(status == 200 and resolved["item"]["status"] == "resolved", "service recovery action is auditable to resolution")
            status, summary = call(client, base, "GET", "/api/feedback/summary")
            expect(status == 200 and summary["summary"]["responses"] == 1 and summary["summary"]["negative_count"] == 1, "feedback summary is tenant-scoped")
            print("RESULT feedback recovery smoke test passed")
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill()
            if process.stdout: process.stdout.close()


if __name__ == "__main__": main()
