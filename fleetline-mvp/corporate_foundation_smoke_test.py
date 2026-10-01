#!/usr/bin/env python3
"""Focused smoke coverage for the corporate account/policy foundation."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend_smoke_test import call, expect, free_port, make_client

ROOT = Path(__file__).resolve().parent


def main() -> None:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="axiom-fleet-corporate-") as temp_dir:
        env = os.environ.copy()
        env.update({"PORT": str(port), "AXIOM_DB_PATH": str(Path(temp_dir) / "axiom.sqlite3"), "AXIOM_ALLOW_DEMO_ACCOUNT": "0"})
        process = subprocess.Popen(["python3", "server.py"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            for _ in range(60):
                try:
                    status, _ = call(make_client(base)[1], base, "GET", "/api/health")
                    if status == 200:
                        break
                except Exception:
                    pass
                time.sleep(0.1)

            _, client = make_client(base)
            status, signup = call(client, base, "POST", "/api/auth/signup", {"role": "vendor", "email": "corporate.foundation@example.com", "password": "StrongPass123!", "full_name": "Foundation Owner", "organization_name": "Foundation Mobility", "city": "Bengaluru"})
            expect(status == 201 and signup["user"]["role"] == "vendor", "corporate foundation authenticates a tenant owner")

            status, branch = call(client, base, "POST", "/api/branches", {"code": "BLR", "name": "Bengaluru", "city": "Bengaluru"})
            expect(status == 201, "corporate scope branch is tenant-owned")
            status, customer = call(client, base, "POST", "/api/customers", {"name": "Foundation Customer"})
            expect(status == 201, "corporate customer entity is tenant-owned")
            status, price_book = call(client, base, "POST", "/api/price-books", {"name": "Foundation rates", "branch_id": branch["item"]["id"], "effective_from": "2026-09-30"})
            expect(status == 201, "corporate copied-pricing source is tenant-owned")
            status, supplier = call(client, base, "POST", "/api/suppliers", {"name": "Foundation Supplier", "cities": ["Bengaluru"]})
            expect(status == 201, "corporate supplier candidate is tenant-owned")

            status, setup = call(client, base, "POST", "/api/corporate/account/setup", {"name": "Foundation Corporate Account", "connection_type": "customer", "external_account_id": "CUST-FOUNDATION", "scope": {"branch_ids": [branch["item"]["id"]], "customer_entity_ids": [customer["item"]["id"]], "cities": ["Bengaluru"], "duty_type_codes": ["LOCAL"]}, "pricing_scope": {"currency": "INR", "price_book_ids": [price_book["item"]["id"]]}, "source_price_book_ids": [price_book["item"]["id"]], "copy_pricing": True, "idempotency_key": "corp-setup-1"})
            expect(status == 201 and setup["account"]["status"] == "setup" and setup["account"]["copy_pricing"] is True and setup["account"]["setup_version"] == 1, "account setup stores copied scope and pricing snapshot")
            status, replay = call(client, base, "POST", "/api/corporate/account/setup", {"name": "ignored replay", "idempotency_key": "corp-setup-1"})
            expect(status == 201 and replay["idempotent_replay"] is True and replay["account"]["setup_version"] == 1, "corporate setup replay is idempotent")
            status, activation = call(client, base, "POST", "/api/corporate/account/activate", {"idempotency_key": "corp-activate-1"})
            expect(status == 201 and activation["account"]["status"] == "active", "account activation guard allows a complete setup")

            status, rule = call(client, base, "POST", "/api/corporate/allotment/rules", {"name": "Foundation deterministic allotment", "status": "active", "supplier_ids": [supplier["item"]["id"]], "cities": ["Bengaluru"], "required_document_types": ["insurance"], "auto_allot": True, "idempotency_key": "corp-rule-1"})
            expect(status == 201 and rule["item"]["version"] == 1, "allotment rule is versioned and supplier-scoped")
            status, policy = call(client, base, "POST", "/api/corporate/policies", {"name": "Foundation booking policy", "status": "active", "booking_lead_time_minutes": 120, "cancellation_cutoff_minutes": 60, "approval_required": True, "approval_route": ["manager"], "supplier_mode": "allowlist", "allowed_supplier_ids": [supplier["item"]["id"]], "auto_allotment_enabled": True, "allotment_rule_id": rule["item"]["id"], "passenger_duty_slip_approval": True, "duty_slip_auto_approval_hours": 48, "idempotency_key": "corp-policy-1"})
            expect(status == 201 and policy["item"]["version"] == 1 and policy["item"]["approval_required"] is True, "corporate policy stores SLA, approval and supplier rules")

            status, master = call(client, base, "POST", "/api/corporate/masters", {"kind": "duty_types", "code": "LOCAL", "name": "Local transfer", "config": {"package_minutes": 240}, "idempotency_key": "corp-master-1"})
            status, master_v2 = call(client, base, "POST", "/api/corporate/masters", {"kind": "duty_types", "code": "LOCAL", "name": "Local transfer v2", "config": {"package_minutes": 300}, "idempotency_key": "corp-master-2"})
            expect(status == 201 and master["item"]["version"] == 1 and master_v2["item"]["version"] == 2, "duty type master versions are immutable and ordered")

            status, person = call(client, base, "POST", "/api/corporate/users", {"email": "booker@example.com", "full_name": "Booker", "account_type": "booker_passenger", "visibility": {"cities": ["Bengaluru"]}, "status": "invited", "idempotency_key": "corp-person-1"})
            expect(status == 201 and person["item"]["account_type"] == "booker_passenger", "booker/passenger entitlement is explicit")

            status, blocked = call(client, base, "POST", "/api/corporate/policies/evaluate", {"action": "book", "scheduled_at": "2026-09-30T14:00:00Z", "city": "Bengaluru", "duty_type_code": "LOCAL"})
            expect(status == 200 and blocked["outcome"] == "block" and any(item["code"] == "booking_lead_time_sla" for item in blocked["reasons"]), "booking lead-time evaluation returns an explainable block")
            status, out_of_scope = call(client, base, "POST", "/api/bookings", {"passenger_name": "Out of scope passenger", "scheduled_at": "2026-10-02T14:00:00Z", "pickup": {"label": "Mumbai"}, "dropoff": {"label": "Airport"}, "duty_type": "LOCAL"})
            expect(status == 409 and out_of_scope["code"] == "corporate_policy_blocked" and any(item["code"] == "account_scope_denied" for item in out_of_scope["details"]["reasons"]), "booking write enforces corporate visibility scope")
            status, approval = call(client, base, "POST", "/api/corporate/policies/evaluate", {"action": "book", "scheduled_at": "2026-10-02T14:00:00Z", "city": "Bengaluru", "duty_type_code": "LOCAL"})
            expect(status == 200 and approval["outcome"] == "needs_approval" and approval["deterministic"] is True, "booking evaluation returns deterministic approval routing")

            status, booking = call(client, base, "POST", "/api/bookings", {"passenger_name": "Foundation Passenger", "passenger_email": "passenger@example.com", "scheduled_at": "2026-10-02T14:00:00Z", "pickup": {"label": "Bengaluru"}, "dropoff": {"label": "Airport"}})
            expect(status == 201 and booking["item"]["status"] == "pending_approval" and booking["corporate_evaluation"]["outcome"] == "needs_approval", "booking write enforces corporate approval routing")
            status, approved_booking = call(client, base, "POST", f"/api/bookings/{booking['item']['id']}/approve", {"comment": "Foundation approval"})
            expect(status == 201 and approved_booking["item"]["status"] == "approved", "corporate approval releases the booking for dispatch")
            near_cutoff = (datetime.now(timezone.utc) + timedelta(minutes=30)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            status, _ = call(client, base, "PATCH", f"/api/bookings/{booking['item']['id']}", {"scheduled_at": near_cutoff})
            status, cancellation = call(client, base, "POST", f"/api/bookings/{booking['item']['id']}/cancel", {"comment": "Cutoff test"})
            expect(status == 409 and cancellation["code"] == "corporate_policy_blocked" and any(item["code"] == "cancellation_cutoff" for item in cancellation["details"]["reasons"]), "booking cancellation enforces the corporate cutoff")
            status, _ = call(client, base, "PATCH", f"/api/bookings/{booking['item']['id']}", {"scheduled_at": "2026-10-02T14:00:00Z"})
            status, duty = call(client, base, "POST", "/api/duties", {"booking_id": booking["item"]["id"]})
            expect(status == 201, "governed duty can be created from the approved booking")
            for transition in ("assigned", "accepted", "en_route", "started"):
                status, transition_result = call(client, base, "PATCH", f"/api/duties/{duty['item']['id']}", {"status": transition})
                expect(status == 200 and transition_result["item"]["status"] == transition, f"duty transition reaches {transition}")
            status, completion = call(client, base, "PATCH", f"/api/duties/{duty['item']['id']}", {"status": "completed"})
            slip = completion.get("duty_slip_approval", {}) if isinstance(completion, dict) else {}
            expect(status == 200 and slip.get("item", {}).get("status") == "pending" and slip["item"].get("action_token"), "duty completion creates a hashed-token pending slip")
            _, public_client = make_client(base)
            status, public_decision = call(public_client, base, "POST", slip["signed_link"], {"decision": "approve", "comment": "Passenger verified"})
            expect(status == 200 and public_decision["item"]["status"] == "approved" and public_decision["item"]["decision_reason"] == "passenger_signed_link", "signed duty-slip link works without a dashboard session")

            status, allotment = call(client, base, "POST", "/api/corporate/allotment/evaluate", {"city": "Bengaluru", "vehicle_id": "missing-vehicle", "required_document_types": ["insurance"]})
            expect(status == 404 or (status == 200 and allotment["outcome"] == "block"), "allotment document guard never silently awards an invalid vehicle")
            print("RESULT corporate foundation smoke test passed")
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
