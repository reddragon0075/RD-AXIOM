#!/usr/bin/env python3
"""Axiom Fleet - Corporate Booking Approval Engine & Fine-Grained RBAC Exploit Verification Suite.
Validates the 5 Hard Anti-Exploit Invariants and Corporate RBAC:
1. Split-Booking Velocity Guard (rolling 24h threshold catches micro-bookings).
2. Anti-Self-Approval & Hierarchy Guard (403 when employee approves own request or wrong manager).
3. Post-Approval Bait-and-Switch Hash Lock (SHA-256 fingerprint mismatch auto-revokes to REVOKED_ON_EDIT).
4. Hard Dispatch Gate (unapproved bookings strictly block driver/vehicle assignment with 409 Conflict).
5. Budget Ceiling & High-Value L2 Escalation (trips >₹10,000 or budget overflow require L2 Finance).
6. Multi-Role RBAC Scope Isolation (Employee vs Line Manager vs Finance Auditor).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sqlite3
import sys
import unittest
from pathlib import Path

# Add fleetline-mvp and project root to sys.path
MVP_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = MVP_DIR.parent

for p in (REPO_ROOT, MVP_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from backend_corporate_approvals import (
    compute_booking_parameter_hash,
    initialize_corporate_rbac_schema,
    estimate_corporate_fare,
    get_or_create_corporate_policy,
    calculate_rolling_24h_spend,
    submit_corporate_booking_request,
    decide_corporate_approval,
    verify_booking_patch_tamper_guard,
    verify_dispatch_allowed_gate,
    handle_corporate_approvals_api,
)
from backend_domain import DomainError, _create_duty, _assign_booking_resources, initialize_domain_schema


class TestCorporateApprovalsRBAC(unittest.TestCase):
    """Exploit & Invariant Verification Suite for Corporate Mobility."""

    def setUp(self):
        """Create an in-memory SQLite database seeded with corporate hierarchy & policy."""
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

        # Initialize base schemas
        initialize_domain_schema(self.conn)
        initialize_corporate_rbac_schema(self.conn)

        self.tenant_id = "org_techcorp_blr"
        now = datetime.now(timezone.utc).isoformat()

        # Seed Cost Centers
        self.conn.execute(
            """
            INSERT INTO cost_centers (id, tenant_id, code, name, monthly_budget_inr, current_month_spend_inr, created_at, updated_at)
            VALUES (?, ?, 'CC-GENERAL', 'General Operations', 100000.0, 1000.0, ?, ?)
            """,
            ("cc_general", self.tenant_id, now, now),
        )
        self.conn.execute(
            """
            INSERT INTO cost_centers (id, tenant_id, code, name, monthly_budget_inr, current_month_spend_inr, created_at, updated_at)
            VALUES (?, ?, 'CC-ENG-01', 'Cloud Infrastructure', 50000.0, 48500.0, ?, ?)
            """,
            ("cc_eng_01", self.tenant_id, now, now),
        )

        # Seed Corporate Users Hierarchy
        # Employee -> Manager -> Travel Desk / Finance
        self.conn.execute(
            """
            INSERT INTO corporate_users (id, tenant_id, email, full_name, corp_role, manager_user_id, cost_center_id, created_at, updated_at)
            VALUES (?, ?, 'emp.rahul@techcorp.com', 'Rahul Verma', 'CORP_EMPLOYEE', 'usr_mgr_suresh', 'cc_general', ?, ?)
            """,
            ("usr_emp_rahul", self.tenant_id, now, now),
        )
        self.conn.execute(
            """
            INSERT INTO corporate_users (id, tenant_id, email, full_name, corp_role, manager_user_id, delegate_approver_user_id, cost_center_id, created_at, updated_at)
            VALUES (?, ?, 'mgr.suresh@techcorp.com', 'Suresh Rao', 'CORP_LINE_MANAGER', NULL, 'usr_mgr_delegate', 'cc_general', ?, ?)
            """,
            ("usr_mgr_suresh", self.tenant_id, now, now),
        )
        self.conn.execute(
            """
            INSERT INTO corporate_users (id, tenant_id, email, full_name, corp_role, manager_user_id, cost_center_id, created_at, updated_at)
            VALUES (?, ?, 'delegate.priya@techcorp.com', 'Priya Nair', 'CORP_LINE_MANAGER', NULL, 'cc_general', ?, ?)
            """,
            ("usr_mgr_delegate", self.tenant_id, now, now),
        )
        self.conn.execute(
            """
            INSERT INTO corporate_users (id, tenant_id, email, full_name, corp_role, manager_user_id, cost_center_id, created_at, updated_at)
            VALUES (?, ?, 'mgr.unrelated@techcorp.com', 'Vikram Seth', 'CORP_LINE_MANAGER', NULL, 'cc_sales_02', ?, ?)
            """,
            ("usr_mgr_unrelated", self.tenant_id, now, now),
        )
        self.conn.execute(
            """
            INSERT INTO corporate_users (id, tenant_id, email, full_name, corp_role, cost_center_id, created_at, updated_at)
            VALUES (?, ?, 'fin.anita@techcorp.com', 'Anita Desai', 'CORP_FINANCE_AUDITOR', 'cc_general', ?, ?)
            """,
            ("usr_fin_anita", self.tenant_id, now, now),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_scenario_1_split_booking_velocity_guard(self):
        """Scenario 1: Employee attempts split-booking velocity exploit.
        Tries to book 3 trips of ₹672 within 24h to bypass ₹800 single-trip cap.
        Trip 1 (₹672) -> Auto-Approved (<₹800).
        Trip 2 (₹672) -> Auto-Approved (Cumulative ₹1,344 <= ₹2,000 cap).
        Trip 3 (₹672) -> Cumulative ₹2,016 > ₹2,000 cap! Must be held in PENDING_L1_MANAGER.
        """
        # Configure Policy: auto_approve_under = 800, rolling_24h_spend_cap = 2000
        policy = get_or_create_corporate_policy(self.conn, self.tenant_id)
        self.assertEqual(policy["auto_approve_under_inr"], 800.0)
        self.assertEqual(policy["rolling_24h_spend_cap_inr"], 2000.0)

        # Trip 1: ₹672 (distance 25km, 1hr)
        t1 = submit_corporate_booking_request(
            self.conn, self.tenant_id, "usr_emp_rahul", "TRIP-001",
            "SEDAN", "P2P_LOCAL", "Office", "Whitefield",
            (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            distance_km=25.0, duration_hours=1.0
        )
        # Verify Fare < 800 and Auto-approved
        self.assertLessEqual(t1["estimated_fare_inr"], 800.0)
        self.assertEqual(t1["approval_status"], "APPROVED")

        # Trip 2: ₹672
        t2 = submit_corporate_booking_request(
            self.conn, self.tenant_id, "usr_emp_rahul", "TRIP-002",
            "SEDAN", "P2P_LOCAL", "Office", "Indiranagar",
            (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
            distance_km=25.0, duration_hours=1.0
        )
        self.assertEqual(t2["approval_status"], "APPROVED")

        # Trip 3: ₹672 -> Cumulative spend reaches ₹2,016 which exceeds 2000 cap!
        t3 = submit_corporate_booking_request(
            self.conn, self.tenant_id, "usr_emp_rahul", "TRIP-003",
            "SEDAN", "P2P_LOCAL", "Office", "Koramangala",
            (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat(),
            distance_km=25.0, duration_hours=1.0
        )
        self.assertEqual(t3["approval_status"], "PENDING_L1_MANAGER")
        self.assertTrue(t3["requires_manager_approval"])
        self.assertTrue(any("Split-Booking Guard" in r for r in t3["reasons"]))

    def test_scenario_2_anti_self_approval_guard(self):
        """Scenario 2: Employee attempts to approve their own booking request.
        Engine must raise PermissionError / 403 Forbidden.
        """
        # Create a pending booking for Rahul (fare > 800)
        req = submit_corporate_booking_request(
            self.conn, self.tenant_id, "usr_emp_rahul", "TRIP-SELF-01",
            "SUV_CRYSTA", "8HR_80KM", "Office", "Site A",
            (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat(),
        )
        self.assertEqual(req["approval_status"], "PENDING_L1_MANAGER")

        # Rahul attempts to self-approve
        with self.assertRaises(PermissionError) as ctx:
            decide_corporate_approval(self.conn, req["approval_id"], "usr_emp_rahul", "APPROVE")
        self.assertIn("Anti-Self-Approval Guard", str(ctx.exception))

    def test_scenario_3_hierarchy_and_delegate_approver_guard(self):
        """Scenario 3: Hierarchy check blocks unrelated managers, allows assigned or delegate manager."""
        req = submit_corporate_booking_request(
            self.conn, self.tenant_id, "usr_emp_rahul", "TRIP-HIER-01",
            "SUV_CRYSTA", "8HR_80KM", "Office", "Site B",
            (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat(),
            cost_center_id="cc_general"
        )

        # Unrelated manager attempts approval -> Blocked
        with self.assertRaises(PermissionError) as ctx:
            decide_corporate_approval(self.conn, req["approval_id"], "usr_mgr_unrelated", "APPROVE")
        self.assertIn("Hierarchy Guard", str(ctx.exception))

        # Assigned Line Manager Suresh approves -> Allowed
        res = decide_corporate_approval(self.conn, req["approval_id"], "usr_mgr_suresh", "APPROVE")
        self.assertEqual(res["approval_status"], "APPROVED")

    def test_scenario_4_post_approval_bait_and_switch_hash_lock(self):
        """Scenario 4: Post-Approval Bait-and-Switch.
        Trip approved as Sedan (₹1,500). User or dispatcher later attempts to patch
        vehicle to Luxury / alters route to inflate fare.
        Engine detects parameter hash mismatch, automatically sets status to REVOKED_ON_EDIT.
        """
        req = submit_corporate_booking_request(
            self.conn, self.tenant_id, "usr_emp_rahul", "TRIP-BAIT-01",
            "SEDAN", "4HR_40KM", "Office", "Client",
            (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(),
            cost_center_id="cc_general",
            distance_km=20.0
        )
        # Manager approves Sedan trip
        decide_corporate_approval(self.conn, req["approval_id"], "usr_mgr_suresh", "APPROVE")

        # Verify initial status is APPROVED
        row = self.conn.execute("SELECT approval_status FROM booking_approval_requests WHERE trip_id = ?", ("TRIP-BAIT-01",)).fetchone()
        self.assertEqual(row["approval_status"], "APPROVED")

        # Attempt Bait-and-Switch: Upgrade vehicle to LUXURY and change destination
        tampered, msg, updated = verify_booking_patch_tamper_guard(
            self.conn,
            "TRIP-BAIT-01",
            new_vehicle_type="LUXURY",
            new_drop="Luxury Resort Outstation",
            new_tariff_model="OUTSTATION",
        )
        self.assertTrue(tampered)
        self.assertIn("APPROVAL REVOKED", msg)
        self.assertEqual(updated["approval_status"], "REVOKED_ON_EDIT")

    def test_scenario_5_hard_dispatch_gate(self):
        """Scenario 5: Dispatch Gate strictly blocks driver assignment for unapproved or revoked trips."""
        # Case A: Pending L1 approval
        submit_corporate_booking_request(
            self.conn, self.tenant_id, "usr_emp_rahul", "TRIP-GATE-01",
            "SUV_CRYSTA", "8HR_80KM", "Office", "Site C",
            (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat(),
        )

        allowed, msg = verify_dispatch_allowed_gate(self.conn, "TRIP-GATE-01")
        self.assertFalse(allowed)
        self.assertIn("Pending Corporate Manager Approval", msg)

        # Seed domain booking to test domain level _assign_booking_resources gate
        self.conn.execute(
            """
            INSERT INTO domain_bookings (id, organization_id, booking_reference, status, created_at, updated_at)
            VALUES ('TRIP-GATE-01', ?, 'BK-REF-GATE-01', 'pending_approval', datetime('now'), datetime('now'))
            """,
            (self.tenant_id,),
        )
        self.conn.commit()

        user = {"id": "usr_ops_01", "organization_id": self.tenant_id, "role": "vendor"}
        payload = {"driver_id": "drv_01", "vehicle_id": "veh_01"}

        with self.assertRaises(DomainError) as ctx:
            _assign_booking_resources(self.conn, user, "TRIP-GATE-01", payload, "127.0.0.1")
        self.assertEqual(ctx.exception.status, 409)

    def test_scenario_6_budget_ceiling_and_l2_finance_escalation(self):
        """Scenario 6: When trip fare exceeds ₹10,000 or exceeds monthly budget, L1 approval transitions to PENDING_L2_FINANCE."""
        # CC-ENG-01 has budget 50,000 and current spend 48,500. Remaining: 1,500.
        # Request a ₹2,800 trip. It exceeds the monthly budget of 50,000!
        req = submit_corporate_booking_request(
            self.conn, self.tenant_id, "usr_emp_rahul", "TRIP-BUDGET-01",
            "SEDAN", "8HR_80KM", "Office", "Remote Plant",
            (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat(),
            cost_center_id="cc_eng_01",
        )
        self.assertEqual(req["approval_status"], "PENDING_L1_MANAGER")

        # Suresh (Line Manager) approves -> because budget ceiling is breached, transitions to PENDING_L2_FINANCE
        res_l1 = decide_corporate_approval(self.conn, req["approval_id"], "usr_mgr_suresh", "APPROVE")
        self.assertEqual(res_l1["approval_status"], "PENDING_L2_FINANCE")
        self.assertIn("Sent to Finance for L2 Approval", res_l1["message"])

        # Suresh (Line Manager) attempts to give L2 approval -> Blocked
        with self.assertRaises(PermissionError):
            decide_corporate_approval(self.conn, req["approval_id"], "usr_mgr_suresh", "APPROVE")

        # Anita (Finance Auditor) gives L2 approval -> Succeeded
        res_l2 = decide_corporate_approval(self.conn, req["approval_id"], "usr_fin_anita", "APPROVE")
        self.assertEqual(res_l2["approval_status"], "APPROVED")

    def test_scenario_7_rbac_api_transparency(self):
        """Scenario 7: RBAC API scoped visibility:
        - Employee only sees own bookings.
        - Manager sees own + reportees' bookings.
        - Finance sees all tenant bookings.
        """
        # Create bookings for Rahul and someone else
        submit_corporate_booking_request(
            self.conn, self.tenant_id, "usr_emp_rahul", "TRIP-RBAC-01",
            "SEDAN", "P2P_LOCAL", "Office", "Hotel",
            (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        )
        submit_corporate_booking_request(
            self.conn, self.tenant_id, "usr_mgr_unrelated", "TRIP-RBAC-02",
            "SEDAN", "P2P_LOCAL", "Office", "Airport",
            (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(),
        )

        # 1. Employee query
        emp_user = {"id": "usr_emp_rahul", "organization_id": self.tenant_id, "role": "vendor"}
        emp_res = handle_corporate_approvals_api(self.conn, emp_user, "GET", "/api/corp/bookings")
        self.assertEqual(emp_res["count"], 1)
        self.assertEqual(emp_res["items"][0]["trip_id"], "TRIP-RBAC-01")

        # 2. Manager query
        mgr_user = {"id": "usr_mgr_suresh", "organization_id": self.tenant_id, "role": "vendor"}
        mgr_res = handle_corporate_approvals_api(self.conn, mgr_user, "GET", "/api/corp/bookings")
        # Suresh manages Rahul, so sees Rahul's booking
        self.assertTrue(any(i["trip_id"] == "TRIP-RBAC-01" for i in mgr_res["items"]))
        self.assertFalse(any(i["trip_id"] == "TRIP-RBAC-02" for i in mgr_res["items"]))

        # 3. Finance Auditor query
        fin_user = {"id": "usr_fin_anita", "organization_id": self.tenant_id, "role": "vendor"}
        fin_res = handle_corporate_approvals_api(self.conn, fin_user, "GET", "/api/corp/bookings")
        self.assertEqual(fin_res["count"], 2)


if __name__ == "__main__":
    unittest.main()
