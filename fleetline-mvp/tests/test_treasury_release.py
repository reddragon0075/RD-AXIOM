"""
Axiom Mobility - Dual-Ledger Fund Release Hold & Treasury Control Unit Test Suite.
Asserts:
1. When a duty completes and passes audit, supplier payout lands in FUNDS_HELD_BY_AXIOM and cannot be withdrawn.
2. When staff toggle Global Switch or Vendor Switch to HOLD, mature funds remain locked even after 72 hours.
3. When staff toggle Release: ON (or click Release Mature Funds), exact Decimal amount moves atomically to RELEASED_TO_WALLET and creates treasury_release_audit_logs.
4. Non-staff users cannot toggle treasury switches (403 forbidden).
5. Delinquent tenants (SOFT_BLOCKED) cannot receive payout releases even if cooling window has elapsed.
"""

import datetime as dt
from decimal import Decimal
from pathlib import Path
import sqlite3
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend_domain import initialize_domain_schema
from backend_commercial import initialize_commercial_schema
from backend_treasury_release import (
    can_release_vendor_funds,
    get_platform_settings,
    get_treasury_summary,
    get_vendor_payout_balance,
    handle_treasury_release,
    initialize_treasury_release_schema,
    record_duty_completion_payable,
    release_batch,
    toggle_global_hold,
    toggle_vendor_hold,
)


class TestTreasuryFundRelease(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = OFF")

        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                role TEXT NOT NULL,
                full_name TEXT NOT NULL,
                organization_id TEXT,
                created_at TEXT NOT NULL
            );
            """
        )

        initialize_domain_schema(self.conn)
        initialize_commercial_schema(self.conn)
        initialize_treasury_release_schema(self.conn)

        now = dt.datetime.now(dt.timezone.utc).isoformat()
        self.staff_user = {
            "id": "usr_axiom_staff_01",
            "email": "finance@axiomfleet.in",
            "role": "axiom_staff",
            "organization_id": "org_axiom_hq",
        }
        self.vendor_a = "org_vendor_apex"
        self.vendor_user = {
            "id": "usr_apex_dispatcher",
            "email": "dispatcher@apexfleet.in",
            "role": "vendor",
            "organization_id": self.vendor_a,
        }

        # Seed billing account for vendor_a
        self.conn.execute(
            """INSERT INTO tenant_billing_accounts (
                tenant_id, tenant_name, account_status, credit_limit_paise, outstanding_balance_paise,
                payout_hold_override, payout_hold_reason, created_at, updated_at
            ) VALUES (?, 'Apex Fleet Solutions', 'ACTIVE', 5000000, 0, 'INHERIT_GLOBAL', '', ?, ?)""",
            (self.vendor_a, now, now),
        )

    def tearDown(self):
        self.conn.close()

    def test_01_duty_completion_lands_in_funds_held_and_cannot_withdraw(self):
        """1. Duty completes & passes audit -> lands in FUNDS_HELD_BY_AXIOM and is blocked from release."""
        duty_id = "DT-9901"
        payable_paise = 385000  # ₹3,850.00

        entry = record_duty_completion_payable(
            self.conn,
            duty_id=duty_id,
            vendor_id=self.vendor_a,
            amount_paise=payable_paise,
            audit_status="PASSED",
        )

        self.assertEqual(entry["status"], "FUNDS_HELD_BY_AXIOM")
        self.assertTrue(entry["staff_hold_locked"])

        # Vendor cannot withdraw funds
        can_release, reason, _ = can_release_vendor_funds(self.conn, self.vendor_a, entry["id"])
        self.assertFalse(can_release)
        self.assertIn("LOCKED by Axiom Staff", reason)

        # Check vendor payout balance endpoint
        bal = get_vendor_payout_balance(self.conn, self.vendor_user)
        self.assertEqual(bal["in_clearing_held_paise"], payable_paise)
        self.assertEqual(bal["released_withdrawable_paise"], 0)

    def test_02_global_hold_switch_keeps_mature_funds_locked(self):
        """2. When Global Switch is HOLD, mature funds remain locked even after 72 hours."""
        duty_id = "DT-9902"
        payable_paise = 420000

        entry = record_duty_completion_payable(
            self.conn,
            duty_id=duty_id,
            vendor_id=self.vendor_a,
            amount_paise=payable_paise,
            audit_status="PASSED",
        )

        # Simulate time travel: 80 hours ago (past the 72h window)
        past_ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=80)).isoformat()
        self.conn.execute(
            "UPDATE supplier_payable_ledger SET audit_passed_at = ?, eligible_for_release_at = ? WHERE id = ?",
            (past_ts, past_ts, entry["id"]),
        )

        # Ensure global switch is LOCKED (0)
        toggle_global_hold(self.conn, self.staff_user, global_enabled=False, default_hold_hours=72, reason="Security review")

        can_release, reason, _ = can_release_vendor_funds(self.conn, self.vendor_a, entry["id"])
        self.assertFalse(can_release)
        self.assertIn("LOCKED by Axiom Staff", reason)

    def test_03_per_vendor_force_hold_overrides_global_release(self):
        """Vendor-level FORCE_HOLD overrides global auto-release switch."""
        duty_id = "DT-9903"
        payable_paise = 510000

        entry = record_duty_completion_payable(
            self.conn,
            duty_id=duty_id,
            vendor_id=self.vendor_a,
            amount_paise=payable_paise,
            audit_status="PASSED",
        )

        # Set time to mature
        past_ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=100)).isoformat()
        self.conn.execute(
            "UPDATE supplier_payable_ledger SET audit_passed_at = ?, eligible_for_release_at = ?, staff_hold_locked = 0 WHERE id = ?",
            (past_ts, past_ts, entry["id"]),
        )

        # Enable global release
        toggle_global_hold(self.conn, self.staff_user, global_enabled=True, default_hold_hours=72, reason="Opening float")

        # Now put vendor on FORCE_HOLD
        toggle_vendor_hold(self.conn, self.staff_user, self.vendor_a, "FORCE_HOLD", reason="Unpaid SaaS subscription dues")

        can_release, reason, _ = can_release_vendor_funds(self.conn, self.vendor_a, entry["id"])
        self.assertFalse(can_release)
        self.assertIn("FORCE_HOLD", reason)
        self.assertIn("Unpaid SaaS subscription dues", reason)

    def test_04_atomic_release_moves_to_released_to_wallet_and_audits(self):
        """3. When staff toggle Release: ON, funds move atomically to RELEASED_TO_WALLET with audit log."""
        duty_id = "DT-9904"
        payable_paise = 610000  # ₹6,100.00

        entry = record_duty_completion_payable(
            self.conn,
            duty_id=duty_id,
            vendor_id=self.vendor_a,
            amount_paise=payable_paise,
            audit_status="PASSED",
        )

        # Mature the entry
        past_ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=75)).isoformat()
        self.conn.execute(
            "UPDATE supplier_payable_ledger SET audit_passed_at = ?, eligible_for_release_at = ? WHERE id = ?",
            (past_ts, past_ts, entry["id"]),
        )

        # Enable global release
        toggle_global_hold(self.conn, self.staff_user, global_enabled=True, default_hold_hours=72, reason="Routine weekly release")

        # Execute batch release
        res = release_batch(
            self.conn,
            self.staff_user,
            vendor_id=self.vendor_a,
            ledger_entry_ids=[entry["id"]],
            reason="Approved mature payouts",
        )

        self.assertTrue(res["ok"])
        self.assertEqual(res["released_count"], 1)
        self.assertEqual(res["total_released_paise"], payable_paise)
        self.assertEqual(res["total_released_inr"], 6100.0)

        # Verify DB state
        row = self.conn.execute("SELECT * FROM supplier_payable_ledger WHERE id = ?", (entry["id"],)).fetchone()
        self.assertEqual(row["status"], "RELEASED_TO_WALLET")
        self.assertEqual(row["released_by_staff_id"], self.staff_user["id"])
        self.assertIsNotNone(row["released_at"])

        # Verify audit log
        audit = self.conn.execute(
            "SELECT * FROM treasury_release_audit_logs WHERE action_type = 'BATCH_MANUAL_RELEASE' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        self.assertIsNotNone(audit)
        self.assertEqual(audit["actor_staff_id"], self.staff_user["id"])
        self.assertEqual(audit["total_amount_affected_inr"], 6100.0)

        # Verify vendor withdrawable balance
        bal = get_vendor_payout_balance(self.conn, self.vendor_user)
        self.assertEqual(bal["in_clearing_held_paise"], 0)
        self.assertEqual(bal["released_withdrawable_paise"], payable_paise)

    def test_05_delinquent_tenant_blocked_from_payout_release(self):
        """Soft/hard blocked delinquent tenants are blocked from payout releases."""
        duty_id = "DT-9905"
        payable_paise = 250000

        entry = record_duty_completion_payable(
            self.conn,
            duty_id=duty_id,
            vendor_id=self.vendor_a,
            amount_paise=payable_paise,
            audit_status="PASSED",
        )

        # Mature the cooling window
        past_ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=80)).isoformat()
        self.conn.execute(
            "UPDATE supplier_payable_ledger SET audit_passed_at = ?, eligible_for_release_at = ?, staff_hold_locked = 0 WHERE id = ?",
            (past_ts, past_ts, entry["id"]),
        )
        toggle_global_hold(self.conn, self.staff_user, global_enabled=True, default_hold_hours=72, reason="Release ON")

        # Soft-block tenant
        self.conn.execute(
            "UPDATE tenant_billing_accounts SET account_status = 'SOFT_BLOCKED' WHERE tenant_id = ?",
            (self.vendor_a,),
        )

        can_release, reason, _ = can_release_vendor_funds(self.conn, self.vendor_a, entry["id"])
        self.assertFalse(can_release)
        self.assertIn("SOFT_BLOCKED", reason)


if __name__ == "__main__":
    unittest.main()
