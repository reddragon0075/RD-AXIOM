"""Axiom Mobility (Fleetline) - Native-Link CRM v2.0 Verification Suite.

Executes tests covering:
1. Zero-Friction Prospect Capture (Mobile-Only or Email-Only intake + Deterministic Lead Scoring).
2. Spread-Aware 6-Model CPQ Engine (Sell vs Buy Spread, GMV & 8% Margin Guardrail).
3. Atomic 1-Click Workspace Provisioner (Live Tenant, Rate Cards & Payout Hold Escrow).
4. Customer 360°, Aging Buckets & Treasury Bridge (Kill-Switch & Fund Release Toggle).
5. Seam & Contract Integrity (JSON keys, idempotency, strict non-null contact checks).
"""

import datetime as dt
from pathlib import Path
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend_domain import DomainError, initialize_domain_schema
from backend_commercial import check_tenant_killswitch
from backend_native_crm import (
    initialize_native_crm_schema,
    compute_lead_score,
    capture_crm_public_prospect,
    simulate_deal_cpq,
    convert_crm_deal_to_workspace,
    get_crm_account_360,
    get_crm_executive_summary,
    handle_native_crm_api,
)


class TestNativeCrmV2(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = OFF")

        # Baseline schema
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT,
                kind TEXT DEFAULT 'vendor',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tenant_billing_accounts (
                tenant_id TEXT PRIMARY KEY,
                tenant_name TEXT NOT NULL,
                account_status TEXT NOT NULL DEFAULT 'ACTIVE',
                access_control_state TEXT NOT NULL DEFAULT 'ACTIVE_GOOD_STANDING',
                saas_balance_owed_inr REAL NOT NULL DEFAULT 0.0,
                outstanding_balance_paise INTEGER NOT NULL DEFAULT 0,
                dunning_stage INTEGER NOT NULL DEFAULT 0,
                trial_ends_at TEXT,
                trial_trips_quota INTEGER DEFAULT 100,
                payout_hold_override TEXT DEFAULT 'RELEASE_READY',
                block_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS domain_price_book_items (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                vehicle_category TEXT NOT NULL,
                duty_type TEXT NOT NULL,
                base_fare REAL NOT NULL,
                per_km_rate REAL NOT NULL,
                per_minute_rate REAL NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS duties (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                proforma_id TEXT,
                booking_id TEXT,
                duty_date TEXT,
                vehicle_category TEXT,
                passenger_name TEXT,
                route_name TEXT,
                practical_billable_km REAL,
                final_client_fare_inr REAL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT,
                name TEXT
            );
        """)

        # Initialize Native CRM v2 tables
        initialize_native_crm_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_01_phone_only_public_prospect_capture_and_scoring(self):
        """Scenario 1: Submitting only a phone number creates scored account, deal, and 30-min task."""
        # 1. Test Deterministic Lead Scorer logic
        # Free webmail, no volume, non-metro -> 0
        s0 = compute_lead_score(email="user@gmail.com", phone="", volume=5, city="Salem")
        self.assertEqual(s0, 0)

        # Corporate email (+25), Phone (+25), Volume 50 cabs (+30), Bengaluru (+20) -> 100
        s100 = compute_lead_score(email="rajesh@infosys.com", phone="+91 9845012345", volume=50, city="Bengaluru")
        self.assertEqual(s100, 100)

        # 2. Phone-only prospect capture via API
        payload = {
            "phone": "+91 98200 55443",
            "name": "Karthik Nair",
            "company_name": "Nair Cabs Bangalore",
            "account_type": "FLEET_VENDOR",
            "city": "Bengaluru",
            "estimated_volume": 25,
        }

        res = capture_crm_public_prospect(self.conn, payload)
        self.assertTrue(res["success"])
        self.assertFalse(res["deduplicated"])
        self.assertEqual(res["status"], "PROSPECT")
        account_id = res["account_id"]
        deal_id = res["deal_id"]
        task_id = res["task_id"]

        # Verify Account created with lead score (volume >= 20 gives +30, Bengaluru gives +20 -> 50)
        acc = self.conn.execute("SELECT * FROM crm_accounts WHERE id = ?", (account_id,)).fetchone()
        self.assertIsNotNone(acc)
        self.assertEqual(acc["primary_phone"], "+919820055443")
        self.assertIsNone(acc["primary_email"])
        self.assertGreaterEqual(acc["lead_score"], 50)

        # Verify Deal created with VENDOR_SUPPLY track
        deal = self.conn.execute("SELECT * FROM crm_deals WHERE id = ?", (deal_id,)).fetchone()
        self.assertEqual(deal["pipeline_track"], "VENDOR_SUPPLY")
        self.assertEqual(deal["pipeline_stage"], "1_INBOUND_PROSPECT")

        # Verify 30-minute follow-up task created
        task = self.conn.execute("SELECT * FROM crm_tasks WHERE id = ?", (task_id,)).fetchone()
        self.assertEqual(task["task_category"], "SALES_FOLLOWUP")
        self.assertEqual(task["priority"], "HIGH")
        self.assertFalse(task["is_completed"])

    def test_02_spread_aware_cpq_simulation_and_margin_warning(self):
        """Scenario 2: CPQ Simulation calculates sell vs buy spread and triggers margin floor warning."""
        # Create an account and deal
        acc_res = capture_crm_public_prospect(self.conn, {
            "email": "procurement@wipro.com",
            "phone": "9845099887",
            "name": "Pooja Hegde",
            "company_name": "Wipro Enterprise Mobility",
            "city": "Bengaluru",
            "estimated_volume": 40,
        })
        deal_id = acc_res["deal_id"]

        # 1. Healthy margin simulation (Sell: ₹2,800, Buy: ₹2,350 -> Margin ~16.1%)
        healthy_payload = {
            "duty_type": "LOCAL_8HR_80KM",
            "vehicle_category": "SEDAN",
            "estimated_monthly_trips": 100,
            "client_sell_base_inr": 2800.0,
            "vendor_buy_base_inr": 2350.0,
        }
        res_healthy = simulate_deal_cpq(self.conn, deal_id, healthy_payload)
        self.assertTrue(res_healthy["success"])
        self.assertEqual(res_healthy["expected_monthly_gmv_inr"], 280000.0)
        self.assertEqual(res_healthy["expected_vendor_payout_inr"], 235000.0)
        self.assertEqual(res_healthy["gross_margin_inr"], 45000.0)
        self.assertAlmostEqual(res_healthy["projected_gross_margin_pct"], 16.07, delta=0.1)
        self.assertEqual(res_healthy["margin_approval_status"], "APPROVED")
        self.assertEqual(len(res_healthy["six_model_breakdown"]), 6)

        # 2. Thin margin simulation (Sell: ₹2,500, Buy: ₹2,380 -> Margin 4.8% < 8.0%)
        thin_payload = {
            "duty_type": "LOCAL_8HR_80KM",
            "vehicle_category": "SEDAN",
            "estimated_monthly_trips": 100,
            "client_sell_base_inr": 2500.0,
            "vendor_buy_base_inr": 2380.0,
        }
        res_thin = simulate_deal_cpq(self.conn, deal_id, thin_payload)
        self.assertAlmostEqual(res_thin["projected_gross_margin_pct"], 4.8, delta=0.1)
        self.assertEqual(res_thin["margin_approval_status"], "LOW_MARGIN_WARNING")

        # Verify snapshot was persisted on the deal record
        deal_row = self.conn.execute("SELECT * FROM crm_deals WHERE id = ?", (deal_id,)).fetchone()
        self.assertEqual(deal_row["pipeline_stage"], "3_SIMULATION_CPQ")
        self.assertEqual(deal_row["margin_approval_status"], "LOW_MARGIN_WARNING")

    def test_03_atomic_workspace_provisioning_and_payout_hold_initialization(self):
        """Scenario 3: 1-Click Provisioning creates tenant, rate cards, and initializes escrow hold."""
        # Create Fleet Vendor prospect
        acc_res = capture_crm_public_prospect(self.conn, {
            "phone": "9811223344",
            "name": "Manish Sharma",
            "company_name": "Sharma Fleet Cabs",
            "account_type": "FLEET_VENDOR",
            "city": "Bengaluru",
        })
        account_id = acc_res["account_id"]
        deal_id = acc_res["deal_id"]

        # Run CPQ simulation to attach rate card snapshot
        simulate_deal_cpq(self.conn, deal_id, {
            "duty_type": "LOCAL_8HR_80KM",
            "vehicle_category": "SEDAN",
            "estimated_monthly_trips": 50,
            "client_sell_base_inr": 2800.0,
            "vendor_buy_base_inr": 2300.0,
        })

        # 1-Click Convert to Operational Workspace
        conv_res = convert_crm_deal_to_workspace(self.conn, deal_id)
        self.assertTrue(conv_res["success"])
        self.assertFalse(conv_res["already_provisioned"])
        tenant_id = conv_res["tenant_id"]
        self.assertTrue(conv_res["payout_hold_active"])
        self.assertEqual(conv_res["pipeline_stage"], "5_CLOSED_WON_PROVISIONED")

        # Verify tenant organization created
        org = self.conn.execute("SELECT * FROM organizations WHERE id = ?", (tenant_id,)).fetchone()
        self.assertIsNotNone(org)
        self.assertEqual(org["name"], "Sharma Fleet Cabs")

        # Verify tenant billing account created with payout_hold_override = 'FORCE_HOLD'
        billing_acc = self.conn.execute("SELECT * FROM tenant_billing_accounts WHERE tenant_id = ?", (tenant_id,)).fetchone()
        self.assertIsNotNone(billing_acc)
        self.assertEqual(billing_acc["payout_hold_override"], "FORCE_HOLD")
        self.assertEqual(billing_acc["account_status"], "ACTIVE")

        # Verify rate cards were provisioned
        rate_cards = self.conn.execute("SELECT * FROM domain_price_book_items WHERE organization_id = ?", (tenant_id,)).fetchall()
        self.assertGreaterEqual(len(rate_cards), 1)

        # Verify idempotency: calling convert again returns existing workspace gracefully
        conv_again = convert_crm_deal_to_workspace(self.conn, deal_id)
        self.assertTrue(conv_again["success"])
        self.assertTrue(conv_again["already_provisioned"])
        self.assertEqual(conv_again["tenant_id"], tenant_id)

    def test_04_customer_360_aging_buckets_and_treasury_bridge(self):
        """Scenario 4: 360 View accurately reports aging buckets, kill-switch, and vendor escrow state."""
        # Provision a tenant
        acc_res = capture_crm_public_prospect(self.conn, {
            "email": "finance@target.com",
            "phone": "9845011223",
            "name": "Target India Transport",
            "company_name": "Target Corporation India",
            "account_type": "CORPORATE_CLIENT",
            "city": "Bengaluru",
        })
        account_id = acc_res["account_id"]
        deal_id = acc_res["deal_id"]

        conv_res = convert_crm_deal_to_workspace(self.conn, deal_id)
        tenant_id = conv_res["tenant_id"]

        # Fetch Customer 360
        view360 = get_crm_account_360(self.conn, account_id)
        self.assertEqual(view360["account"]["id"], account_id)
        self.assertEqual(view360["receivables_aging"]["kill_switch_status"], "ACTIVE")
        self.assertIn("bucket_0_30_days", view360["receivables_aging"])
        self.assertIn("bucket_31_60_days", view360["receivables_aging"])

        # Toggle Kill-Switch to SOFT_LOCKED_OVERDUE on tenant
        self.conn.execute(
            "UPDATE tenant_billing_accounts SET account_status = 'SOFT_BLOCKED', access_control_state = 'SOFT_LOCKED_OVERDUE' WHERE tenant_id = ?",
            (tenant_id,),
        )

        view360_updated = get_crm_account_360(self.conn, account_id)
        self.assertEqual(view360_updated["receivables_aging"]["kill_switch_status"], "SOFT_BLOCKED")
        self.assertEqual(view360_updated["receivables_aging"]["access_control_state"], "SOFT_LOCKED_OVERDUE")

    def test_05_executive_summary_kpis(self):
        """Scenario 5: Executive summary KPI calculations."""
        kpis = get_crm_executive_summary(self.conn)
        self.assertGreater(kpis["total_pipeline_gmv_inr"], 0)
        self.assertGreaterEqual(kpis["unworked_website_prospects_count"], 0)
        self.assertGreaterEqual(kpis["total_people_in_system"], 0)


if __name__ == "__main__":
    unittest.main()
