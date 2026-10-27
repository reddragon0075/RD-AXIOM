#!/usr/bin/env python3
"""Axiom Mobility Commercial Control Plane, Sales CRM & Delinquent Tenant Kill-Switch Test Suite.

Verifies:
1. Public Prospect Capture (email-only, mobile-only, both, deduplication)
2. Sales Notes logging & 1-Click Onboarding with 409 duplicate prevention
3. Axiom Company Overview census & receivables ledger accuracy
4. Delinquent Tenant Blocking ("Kill Switch"):
   - SOFT_BLOCKED: Rejects new bookings & dispatches (HTTP 402 TENANT_BLOCKED_NON_PAYMENT), permits active duty completion
   - HARD_BLOCKED: Full API rejection
   - Payment settlement & auto-unblock restores full operational capabilities
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend_commercial import (
    check_tenant_killswitch,
    handle_commercial,
    handle_public_prospects,
    initialize_commercial_schema,
)
from backend_domain import (
    DomainError,
    _create_duty,
    initialize_domain_schema,
)
from backend_extended import initialize_extended_schema
from backend_operations_parity import _close_duty, initialize_operations_parity_schema


class TestProspectsAndKillSwitch(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        # Initialize base tables
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL DEFAULT '',
                city TEXT NOT NULL DEFAULT '',
                gstin TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                role TEXT NOT NULL,
                full_name TEXT NOT NULL,
                organization_id TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                ip_address TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            """
        )
        initialize_domain_schema(self.conn)
        initialize_extended_schema(self.conn)
        initialize_operations_parity_schema(self.conn)
        initialize_commercial_schema(self.conn)

        now = datetime.now(timezone.utc).isoformat()
        # Seed test admin & vendor
        self.admin_user = {
            "id": "usr_super_admin",
            "email": "superadmin@axiomfleet.in",
            "role": "axiom_super_admin",
            "organization_id": "org_axiom_hq",
        }
        self.conn.execute(
            "INSERT INTO users (id, email, password_hash, password_salt, role, full_name, organization_id, created_at) VALUES (?, ?, 'h', 's', 'axiom_super_admin', 'HQ Admin', 'org_axiom_hq', ?)",
            (self.admin_user["id"], self.admin_user["email"], now)
        )

        self.vendor_org_id = "org_vendor_test_42"
        self.conn.execute(
            "INSERT INTO organizations (id, kind, name, phone, city, gstin, created_at) VALUES (?, 'vendor', 'Test Fleet 42', '+919876543210', 'Pune', '27AABCT4242A1Z5', ?)",
            (self.vendor_org_id, now)
        )
        self.dispatcher_user = {
            "id": "usr_dispatcher_42",
            "email": "dispatch@testfleet42.com",
            "role": "vendor",
            "organization_id": self.vendor_org_id,
        }
        self.conn.execute(
            "INSERT INTO users (id, email, password_hash, password_salt, role, full_name, organization_id, created_at) VALUES (?, ?, 'h', 's', 'vendor', 'Test Dispatcher', ?, ?)",
            (self.dispatcher_user["id"], self.dispatcher_user["email"], self.vendor_org_id, now)
        )

        # Seed billing account for vendor
        self.conn.execute(
            """INSERT INTO tenant_billing_accounts
               (tenant_id, tenant_name, account_status, block_reason, total_billed_paise, total_paid_paise, outstanding_balance_paise, credit_limit_paise, days_overdue, created_at, updated_at)
               VALUES (?, 'Test Fleet 42', 'ACTIVE', '', 20000000, 15000000, 5000000, 10000000, 15, ?, ?)""",
            (self.vendor_org_id, now, now)
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_01_public_lead_capture_and_deduplication(self):
        """1. Mobile-only lead submission succeeds; missing both email and phone raises 400; duplicate lead deduplicates."""
        # A: Missing both email & mobile -> 400
        with self.assertRaises(DomainError) as ctx:
            handle_public_prospects(self.conn, "POST", "/api/public/prospects", {"contact_name": "Incomplete"}, "127.0.0.1")
        self.assertEqual(ctx.exception.status, 400)

        # B: Mobile-only submission succeeds
        res_mobile = handle_public_prospects(
            self.conn,
            "POST",
            "/api/public/prospects",
            {
                "contact_name": "Ananya Roy",
                "company_name": "Roy Shuttles",
                "mobile_number": "+91 99887 76655",
                "message": "Looking for employee transport solution in Noida.",
            },
            "127.0.0.1",
        )
        self.assertTrue(res_mobile["ok"])
        self.assertEqual(res_mobile["status"], "NEW")
        self.assertFalse(res_mobile["deduplicated"])
        pid = res_mobile["prospect_id"]

        # C: Duplicate submission with same mobile deduplicates cleanly
        res_dup = handle_public_prospects(
            self.conn,
            "POST",
            "/api/public/prospects",
            {
                "contact_name": "Ananya Roy Updated",
                "mobile_number": "9988776655",
                "message": "Urgent requirement for 20 cabs.",
            },
            "127.0.0.1",
        )
        self.assertTrue(res_dup["ok"])
        self.assertEqual(res_dup["prospect_id"], pid)
        self.assertTrue(res_dup["deduplicated"])

    def test_02_sales_call_note_logging(self):
        """2. Super-admin can query prospects and append timestamped call notes."""
        # Query prospects
        lead_list = handle_commercial(self.conn, self.admin_user, "GET", "/api/admin/prospects", {}, "127.0.0.1")
        self.assertTrue(lead_list["ok"])
        self.assertGreaterEqual(len(lead_list["prospects"]), 1)

        prospect_id = lead_list["prospects"][0]["id"]

        # Log call note
        patch_res = handle_commercial(
            self.conn,
            self.admin_user,
            "PATCH",
            f"/api/admin/prospects/{prospect_id}",
            {
                "status": "QUALIFIED",
                "note": "Spoke to customer. Requirement confirmed for 25 sedans in Pune.",
            },
            "127.0.0.1",
        )
        self.assertTrue(patch_res["ok"])
        self.assertEqual(patch_res["prospect"]["status"], "QUALIFIED")
        notes = patch_res["prospect"]["sales_notes"]
        self.assertTrue(any("25 sedans" in n["note"] for n in notes))

    def test_03_1click_onboard_and_duplicate_prevention(self):
        """3. Onboarding atomically creates active tenant; second onboard click raises 409 Conflict."""
        # Create a fresh prospect
        prsp = handle_public_prospects(
            self.conn,
            "POST",
            "/api/public/prospects",
            {
                "contact_name": "Deepak Patel",
                "company_name": "Patel Premium Travels",
                "email": "deepak@pateltravels.in",
                "mobile_number": "+919833445566",
            },
            "127.0.0.1",
        )
        pid = prsp["prospect_id"]

        # 1-Click Onboard
        onboard_res = handle_commercial(
            self.conn,
            self.admin_user,
            "POST",
            f"/api/admin/prospects/{pid}/onboard",
            {},
            "127.0.0.1",
        )
        self.assertTrue(onboard_res["ok"])
        new_tenant_id = onboard_res["tenant_id"]
        self.assertTrue(new_tenant_id.startswith("org_vendor_"))
        self.assertEqual(onboard_res["account_status"], "ACTIVE")
        self.assertEqual(onboard_res["credentials"]["email"], "deepak@pateltravels.in")

        # Verify tenant billing account created in DB
        billing_row = self.conn.execute("SELECT * FROM tenant_billing_accounts WHERE tenant_id = ?", (new_tenant_id,)).fetchone()
        self.assertIsNotNone(billing_row)
        self.assertEqual(billing_row["account_status"], "ACTIVE")

        # Attempt 2nd Onboard on same prospect -> must return 409 Conflict
        with self.assertRaises(DomainError) as ctx:
            handle_commercial(
                self.conn,
                self.admin_user,
                "POST",
                f"/api/admin/prospects/{pid}/onboard",
                {},
                "127.0.0.1",
            )
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(ctx.exception.code, "prospect_already_onboarded")

    def test_04_company_overview_census_and_receivables(self):
        """4. GET /api/admin/company-overview accurately computes total users, drivers, and money owed."""
        overview = handle_commercial(self.conn, self.admin_user, "GET", "/api/admin/company-overview", {}, "127.0.0.1")
        self.assertTrue(overview["ok"])
        self.assertGreaterEqual(overview["total_users_in_system"], 2)
        self.assertGreaterEqual(overview["total_tenants"], 1)
        self.assertGreater(overview["total_receivables_outstanding_paise"], 0)

        # Check tenant in breakdown
        t_match = next((t for t in overview["tenants"] if t["tenant_id"] == self.vendor_org_id), None)
        self.assertIsNotNone(t_match)
        self.assertEqual(t_match["amount_owed_paise"], 5000000)  # ₹50,000

    def test_05_kill_switch_blocking_and_in_flight_completion(self):
        """5. Delinquent tenant blocking: SOFT_BLOCKED blocks new bookings; allows in-flight duties to close."""
        # Create an in-flight duty while ACTIVE
        self.conn.execute(
            """INSERT INTO domain_duties (id, organization_id, booking_id, status, start_odometer, started_at, created_at, updated_at)
               VALUES ('d-active-101', ?, 'bk-active-101', 'in_progress', 45000, ?, ?, ?)""",
            (self.vendor_org_id, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat())
        )
        self.conn.commit()

        # A: Super-Admin sets SOFT_BLOCKED
        block_res = handle_commercial(
            self.conn,
            self.admin_user,
            "POST",
            f"/api/admin/tenants/{self.vendor_org_id}/block",
            {"mode": "SOFT_BLOCKED", "reason": "Overdue balance > 30 days"},
            "127.0.0.1",
        )
        self.assertTrue(block_res["ok"])
        self.assertEqual(block_res["account_status"], "SOFT_BLOCKED")

        # B: Vendor attempts to create a new booking / dispatch -> Blocked with 402 TENANT_BLOCKED_NON_PAYMENT
        with self.assertRaises(DomainError) as ctx:
            check_tenant_killswitch(self.conn, self.vendor_org_id, "POST", "/api/bookings")
        self.assertEqual(ctx.exception.status, 402)
        self.assertEqual(ctx.exception.code, "TENANT_BLOCKED_NON_PAYMENT")

        with self.assertRaises(DomainError) as ctx:
            check_tenant_killswitch(self.conn, self.vendor_org_id, "POST", "/api/duties")
        self.assertEqual(ctx.exception.status, 402)

        # C: Active duty in-flight close is permitted (does not throw)
        check_tenant_killswitch(self.conn, self.vendor_org_id, "POST", "/api/duties/d-active-101/close")

        # D: HARD_BLOCKED blocks all operations
        handle_commercial(
            self.conn,
            self.admin_user,
            "POST",
            f"/api/admin/tenants/{self.vendor_org_id}/block",
            {"mode": "HARD_BLOCKED", "reason": "Severe non-payment delinquency"},
            "127.0.0.1",
        )
        with self.assertRaises(DomainError) as ctx:
            check_tenant_killswitch(self.conn, self.vendor_org_id, "GET", "/api/overview")
        self.assertEqual(ctx.exception.status, 402)

    def test_06_payment_recording_and_auto_unblock(self):
        """6. Full payment settlement automatically clears overdue status and unblocks the tenant."""
        # Set tenant to SOFT_BLOCKED with 50,000 paise (₹500) balance
        self.conn.execute(
            """UPDATE tenant_billing_accounts SET
               account_status = 'SOFT_BLOCKED',
               total_billed_paise = 50000,
               total_paid_paise = 0,
               outstanding_balance_paise = 50000,
               block_reason = 'Payment overdue'
               WHERE tenant_id = ?""",
            (self.vendor_org_id,),
        )
        self.conn.commit()

        # Record full settlement payment
        pay_res = handle_commercial(
            self.conn,
            self.admin_user,
            "POST",
            f"/api/admin/tenants/{self.vendor_org_id}/payment",
            {"amount_paise": 50000, "reference_id": "UTR-AXIOM-9921"},
            "127.0.0.1",
        )
        self.assertTrue(pay_res["ok"])
        self.assertEqual(pay_res["new_amount_owed_paise"], 0)
        self.assertEqual(pay_res["account_status"], "ACTIVE")

        # Verify operational check now passes cleanly without raising 402
        check_tenant_killswitch(self.conn, self.vendor_org_id, "POST", "/api/bookings")
        check_tenant_killswitch(self.conn, self.vendor_org_id, "POST", "/api/duties")


if __name__ == "__main__":
    unittest.main()
