#!/usr/bin/env python3
"""Focused local smoke coverage for finance, reports/imports and public feedback."""
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
    with tempfile.TemporaryDirectory(prefix="axiom-fleet-finance-") as temp_dir:
        env = os.environ.copy()
        env.update({"PORT": str(port), "AXIOM_DB_PATH": str(Path(temp_dir) / "axiom.sqlite3"), "AXIOM_ALLOW_DEMO_ACCOUNT": "0"})
        process = subprocess.Popen(["python3", "server.py"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            for _ in range(60):
                try:
                    if call(make_client(base)[1], base, "GET", "/api/health")[0] == 200:
                        break
                except Exception:
                    time.sleep(0.1)
            jar, client = make_client(base)
            status, signup = call(client, base, "POST", "/api/auth/signup", {"role": "vendor", "email": "finance.smoke@example.com", "password": "StrongPass123!", "full_name": "Finance Owner", "organization_name": "Finance Mobility", "city": "Bengaluru"})
            expect(status == 201, "finance smoke tenant authenticates")

            status, supplier = call(client, base, "POST", "/api/suppliers", {"name": "Finance Supplier", "cities": ["Bengaluru"]})
            expect(status == 201, "supplier master supports finance workflow")
            supplier_id = supplier["item"]["id"]
            status, advance = call(client, base, "POST", "/api/supplier-advances", {"supplier_id": supplier_id, "amount_paise": 500000, "purpose": "Trip advance", "idempotency_key": "advance-1"})
            expect(status == 201 and advance["item"]["status"] == "requested", "supplier advances are requestable")
            advance_id = advance["item"]["id"]
            status, advance_replay = call(client, base, "POST", "/api/supplier-advances", {"supplier_id": supplier_id, "amount_paise": 500000, "purpose": "Trip advance", "idempotency_key": "advance-1"})
            expect(status == 201 and advance_replay.get("idempotent") is True, "supplier advance replay is idempotent")
            status, approved = call(client, base, "POST", f"/api/supplier-advances/{advance_id}/approve", {})
            expect(status in {200, 201} and approved["item"]["status"] == "approved", "supplier advance approval is auditable")

            status, request = call(client, base, "POST", "/api/supplier-payment-requests", {"supplier_id": supplier_id, "advance_id": advance_id, "amount_paise": 250000, "idempotency_key": "payment-1"})
            expect(status == 201 and request["item"]["status"] == "requested", "supplier payment request is tenant-scoped")
            request_id = request["item"]["id"]
            status, request_approved = call(client, base, "POST", f"/api/supplier-payment-requests/{request_id}/approve", {})
            expect(status in {200, 201} and request_approved["item"]["status"] == "approved", "supplier settlement payment approval works")
            status, executed = call(client, base, "POST", f"/api/supplier-payment-requests/{request_id}/execute", {"method": "mock_bank", "idempotency_key": "execution-1"})
            expect(status == 200 and executed["item"]["status"] == "executed", "supplier payment execution uses a mock bank adapter")
            status, execution_replay = call(client, base, "POST", f"/api/supplier-payment-requests/{request_id}/execute", {"method": "mock_bank", "idempotency_key": "execution-1"})
            expect(status == 200 and execution_replay.get("idempotent") is True, "payment execution replay is idempotent")

            status, settlement = call(client, base, "POST", "/api/supplier-settlements/generate", {"supplier_id": supplier_id, "period_start": "2026-09-01", "period_end": "2026-09-30"})
            expect(status == 200, "supplier settlement summary is available")
            settlement_id = settlement["item"]["id"]
            status, approval = call(client, base, "POST", "/api/supplier-settlement-approvals", {"settlement_id": settlement_id})
            expect(status == 201 and approval["item"]["status"] == "pending", "supplier settlement enters approval queue")
            approval_id = approval["item"]["id"]
            status, approval_done = call(client, base, "POST", f"/api/supplier-settlement-approvals/{approval_id}/approve", {"comments": "Checked bills"})
            expect(status in {200, 201} and approval_done["item"]["status"] == "approved", "supplier settlement approval is recorded")

            status, driver = call(client, base, "POST", "/api/drivers", {"full_name": "Payout Driver", "phone": "+919800000001"})
            expect(status == 201, "driver exists for payout")
            driver_id = driver["item"]["id"]
            status, payout = call(client, base, "POST", "/api/driver-payouts/requests", {"driver_id": driver_id, "period_start": "2026-09-01", "period_end": "2026-09-30", "gross_paise": 700000, "deductions_paise": 50000})
            expect(status == 201 and payout["item"]["net_paise"] == 650000, "driver payout calculates net amount")
            payout_id = payout["item"]["id"]
            status, payout_approved = call(client, base, "POST", f"/api/driver-payouts/{payout_id}/approve", {})
            expect(status in {200, 201} and payout_approved["item"]["status"] == "approved", "driver payout approval is separate from disbursement")
            status, payout_done = call(client, base, "POST", f"/api/driver-payouts/{payout_id}/disburse", {})
            expect(status == 200 and payout_done["item"]["status"] == "disbursed", "driver payout disbursement uses mock bank boundary")

            status, station = call(client, base, "POST", "/api/fuel-stations", {"code": "FS-01", "name": "Bengaluru Fuel", "city": "Bengaluru", "fuel_types": ["diesel"]})
            expect(status == 201, "fuel station master is available")
            status, price = call(client, base, "POST", "/api/fuel-prices", {"station_id": station["item"]["id"], "fuel_type": "diesel", "price_paise": 9500, "effective_from": "2026-09-30T00:00:00Z"})
            expect(status == 201, "fuel price history is append-only")
            status, petty = call(client, base, "POST", "/api/petty-cash/reconciliations", {"reconciliation_type": "petty_cash", "summary": {"closing_paise": 10000}, "unmatched": [{"reference": "PC-1"}]})
            expect(status == 201 and petty["item"]["reconciliation_type"] == "petty_cash", "petty-cash reconciliation records exceptions")
            status, fuel = call(client, base, "GET", "/api/fuel-analytics")
            expect(status == 200 and "price_history" in fuel, "fuel analytics exposes price history and efficiency boundary")

            status, payroll = call(client, base, "POST", "/api/payroll/exports", {"export_format": "bank_csv"})
            expect(status == 201 and payroll["item"]["format"] == "bank_csv", "payroll bank-file export is provider-neutral")
            status, payroll_download = call(client, base, "GET", payroll["item"]["signed_url"])
            expect(status == 200 and "content" in payroll_download["item"], "payroll export has a signed download boundary")
            status, compliance = call(client, base, "POST", "/api/payroll/compliance", {"period_start": "2026-09-01", "period_end": "2026-09-30", "deductions": {"pt": 12000, "pf": 45000}})
            expect(status == 201 and compliance["item"]["report_type"] == "statutory_deductions", "payroll statutory report is stored")

            status, template = call(client, base, "POST", "/api/reporting/import-templates", {"entity_type": "vehicles", "name": "Vehicle import", "columns": ["registration_number", "vehicle_group"]})
            expect(status == 201, "rich import template is configurable")
            status, preview = call(client, base, "POST", "/api/imports/preview", {"entity_type": "vehicles", "template_id": template["item"]["id"], "rows": [{"vehicle_group": "Sedan"}, {"registration_number": "KA01AB1234", "vehicle_group": "Sedan"}]})
            expect(status == 201 and preview["item"]["valid_rows"] == 1 and preview["row_errors"], "import preview returns row-level corrections")
            import_id = preview["item"]["id"]
            status, corrected = call(client, base, "POST", f"/api/imports/{import_id}/corrections", {"corrections": [{"row": 0, "values": {"registration_number": "KA01AB1235"}}]})
            expect(status == 200 and corrected["item"]["valid_rows"] == 2, "import correction UX revalidates rows")
            status, committed = call(client, base, "POST", f"/api/imports/{import_id}/commit", {})
            expect(status == 200 and committed["item"]["status"] == "committed", "validated import can be committed")

            status, config = call(client, base, "POST", "/api/reports/builder", {"name": "Vehicle profit", "report_type": "vehicle_profitability", "filters": {"city": "Bengaluru"}, "columns": ["revenue_paise", "profit_paise"]})
            expect(status == 201, "report builder saves filter and column configuration")
            status, favourite = call(client, base, "POST", "/api/reports/favorites", {"config_id": config["item"]["id"], "name": "Monthly vehicle profit"})
            expect(status == 201, "report favourites are saved")
            status, report = call(client, base, "POST", f"/api/reports/builder/{config['item']['id']}/run", {"async": True, "export_type": "vehicle_profitability"})
            expect(status == 200 and report["async"] is True, "large report runs through async export job boundary")
            job_token = report["job"]["signed_url"].split("/")[-2]
            status, download = call(client, base, "GET", f"/api/reports/exports/{job_token}/download")
            expect(status == 200 and "rows" in download["item"], "report export has a signed download boundary")
            status, refreshed = call(client, base, "POST", f"/api/reports/favorites/{favourite['item']['id']}/refresh", {})
            expect(status == 200 and refreshed["favorite_id"] == favourite["item"]["id"], "saved report refresh workflow is explicit")

            status, delivery_policy = call(client, base, "POST", "/api/feedback/delivery-policies", {"name": "Default customer feedback", "channels": ["sms", "email", "whatsapp"], "fallback_channels": ["email"], "max_attempts": 3})
            expect(status in {200, 201} and delivery_policy["item"]["status"] == "active", "customer-specific feedback delivery policy is configurable")
            status, escalation_policy = call(client, base, "POST", "/api/feedback/escalation-policies", {"name": "Low rating escalation", "conditions": {"rating_lte": 2, "sentiment": "negative"}, "action_type": "call_customer", "priority": "high", "due_minutes": 30})
            expect(status in {200, 201} and escalation_policy["item"]["status"] == "active", "automated feedback escalation policy is configurable")
            status, form = call(client, base, "POST", "/api/feedback/forms", {"name": "Passenger CSAT", "questions": [{"key": "service", "label": "Service", "type": "text", "required": False}]})
            expect(status in {200, 201}, "feedback form supports configurable questions")
            form_id = form["item"]["id"]
            status, active_form = call(client, base, "POST", f"/api/feedback/forms/{form_id}/publish", {})
            expect(status == 200 and active_form["item"]["status"] == "active", "feedback form can be published")
            status, link = call(client, base, "POST", "/api/feedback/public-links", {"form_id": form_id, "label": "Passenger link", "allow_anonymous": True})
            expect(status == 201 and link.get("feedback_token"), "public feedback link is token-only")
            status, deliveries = call(client, base, "POST", "/api/feedback/notifications/run", {"limit": 10})
            expect(status == 200 and deliveries.get("processed", 0) >= 1 and deliveries.get("provider") == "mock_sms_email_whatsapp_adapter", "feedback notification queue has a provider-neutral delivery workflow")
            status, notification_rows = call(client, base, "GET", "/api/feedback/notifications")
            expect(status == 200 and notification_rows["items"], "feedback notification state is inspectable")
            notification_id = notification_rows["items"][0]["id"]
            status, receipt = call(client, base, "POST", f"/api/feedback/notifications/{notification_id}/receipt", {"status": "delivered", "provider_reference": "mock-receipt-1", "provider_event_id": "event-1"})
            expect(status == 200 and receipt["item"]["status"] == "delivered", "provider delivery receipt updates notification state")
            status, attempts = call(client, base, "GET", "/api/feedback/delivery-attempts")
            expect(status == 200 and attempts["items"], "provider attempts and retry history are inspectable")
            status, retry_policy = call(client, base, "POST", "/api/feedback/delivery-policies", {"name": "Transient retry policy", "max_attempts": 3, "channels": ["email"]})
            expect(status in {200, 201} and retry_policy["item"]["max_attempts"] == 3, "feedback retry budget is configurable")
            status, retry_link = call(client, base, "POST", "/api/feedback/public-links", {"form_id": form_id, "policy_id": retry_policy["item"]["id"], "recipient": "retry@example.com", "label": "Retry path"})
            expect(status == 201 and retry_link.get("feedback_token"), "feedback notification binds to an explicit delivery policy")
            status, retry_run = call(client, base, "POST", "/api/feedback/notifications/run", {"limit": 10})
            expect(status == 200 and retry_run["failed"] >= 1, "transient feedback delivery schedules a retry")
            status, bounce_link = call(client, base, "POST", "/api/feedback/public-links", {"form_id": form_id, "policy_id": retry_policy["item"]["id"], "recipient": "bounce@example.com", "label": "Bounce path"})
            expect(status == 201, "feedback bounce fixture is queued")
            status, bounce_run = call(client, base, "POST", "/api/feedback/notifications/run", {"limit": 10})
            expect(status == 200 and bounce_run["bounced"] >= 1, "hard-bounced feedback delivery is terminal")
            status, dead_policy = call(client, base, "POST", "/api/feedback/delivery-policies", {"name": "Exhausted retry policy", "max_attempts": 1, "channels": ["sms"]})
            expect(status in {200, 201}, "feedback dead-letter budget is configurable")
            status, dead_link = call(client, base, "POST", "/api/feedback/public-links", {"form_id": form_id, "policy_id": dead_policy["item"]["id"], "recipient": "retry@example.com", "label": "Dead letter path"})
            expect(status == 201, "feedback exhausted-retry fixture is queued")
            status, dead_run = call(client, base, "POST", "/api/feedback/notifications/run", {"limit": 10})
            expect(status == 200 and dead_run["dead_letter"] >= 1, "exhausted feedback delivery enters dead letter")
            _, public_client = make_client(base)
            status, public_form = call(public_client, base, "GET", link["feedback_path"])
            expect(status == 200 and public_form["feedback"]["allow_anonymous"] is True, "anonymous passenger feedback endpoint exposes only form metadata")
            status, feedback = call(public_client, base, "POST", link["feedback_path"], {"rating": 2, "comment": "Vehicle arrived late"})
            expect(status == 200 and feedback["item"]["sentiment"] == "negative", "public feedback submission routes sentiment")
            status, feedback_replay = call(public_client, base, "POST", link["feedback_path"], {"rating": 2})
            expect(status == 200 and feedback_replay.get("idempotent") is True, "public feedback replay is idempotent")
            status, analytics = call(client, base, "GET", "/api/feedback/analytics")
            expect(status == 200 and analytics["trend"], "feedback dashboard exposes customer-satisfaction trends")
            status, actions = call(client, base, "GET", "/api/feedback/corrective-actions")
            expect(status == 200 and actions["items"], "negative feedback creates automated corrective action")
            print("RESULT finance/reporting/feedback smoke test passed")
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
