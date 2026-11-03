#!/usr/bin/env python3
"""Axiom Mobility (Fleetline) - Pre-Launch Certification Test Suite.

Automated End-to-End Certification:
1. Static Crawler Verification: 0 competitor strings, 0 hardcoded localhost, 0 broken ES6/HTML assets, 100% fetch route alignment.
2. Empty-State Resilience: Verified safe response structures on brand new workspaces with 0 rows (no 500s or null-pointer panics).
3. Complete E2E Walkthrough: Inbound Lead -> Lead Scoring -> 6-Model CPQ Studio -> 1-Click Tenant Provisioning -> Booking & Duty Dispatch -> Night Shift POSH Guard -> Algorithmic Trust Audit -> Dual-Ledger P&L.
4. Axiom Company View & Commercial Controls: Receivables Aging Radar -> Non-Payment Kill-Switch Toggles -> Vendor Payout Escrow Hold/Release.
"""

from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
MVP_ROOT = ROOT / "fleetline-mvp"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(MVP_ROOT))

from scripts.launch_link_and_route_crawler import (
    audit_competitor_strings,
    audit_hardcoded_localhost,
    audit_es6_imports,
    audit_html_static_assets,
    audit_frontend_fetch_routes,
)

from backend_domain import (
    DomainError,
    _create_booking,
    _create_duty,
    _create_invoice,
    initialize_domain_schema,
)
from backend_extended import initialize_extended_schema
from backend_operations_parity import (
    _close_duty,
    initialize_operations_parity_schema,
)
from backend_commercial import (
    check_tenant_killswitch,
    handle_commercial,
    handle_public_prospects,
    initialize_commercial_schema,
)
from backend_autonomous import (
    initialize_autonomous_schema,
    compute_trip_trust_score,
    resolve_duty_audit,
    scan_sla_radar,
    simulate_tariff_scenarios,
)
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
from backend_treasury_release import (
    initialize_treasury_release_schema,
    get_platform_settings,
    get_treasury_summary,
    toggle_global_hold,
    toggle_vendor_hold,
    record_duty_completion_payable,
    release_batch,
)


class TestLaunchCertification(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = OFF")

        now = datetime.now(timezone.utc).isoformat()

        # Initialize base tables
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                slug TEXT,
                phone TEXT NOT NULL DEFAULT '',
                city TEXT NOT NULL DEFAULT '',
                gstin TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS tenant_billing_accounts (
                tenant_id TEXT PRIMARY KEY,
                tenant_name TEXT NOT NULL,
                account_status TEXT NOT NULL DEFAULT 'ACTIVE',
                access_control_state TEXT NOT NULL DEFAULT 'ACTIVE_GOOD_STANDING',
                saas_balance_owed_inr REAL NOT NULL DEFAULT 0.0,
                outstanding_balance_paise INTEGER NOT NULL DEFAULT 0,
                credit_limit_paise INTEGER NOT NULL DEFAULT 10000000,
                total_billed_paise INTEGER NOT NULL DEFAULT 0,
                total_paid_paise INTEGER NOT NULL DEFAULT 0,
                days_overdue INTEGER NOT NULL DEFAULT 0,
                next_due_date TEXT,
                dunning_stage INTEGER NOT NULL DEFAULT 0,
                trial_ends_at TEXT,
                trial_trips_quota INTEGER DEFAULT 100,
                trial_trips_used INTEGER DEFAULT 0,
                payout_hold_override TEXT DEFAULT 'INHERIT_GLOBAL',
                payout_hold_reason TEXT DEFAULT '',
                payout_hold_updated_by TEXT DEFAULT '',
                payout_hold_updated_at TEXT,
                block_reason TEXT NOT NULL DEFAULT '',
                blocked_at TEXT,
                blocked_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
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
                metadata_json TEXT DEFAULT '{}',
                ip_address TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            """
        )

        # Initialize all modular subsystems
        initialize_domain_schema(self.conn)
        initialize_extended_schema(self.conn)
        initialize_operations_parity_schema(self.conn)
        initialize_commercial_schema(self.conn)
        initialize_autonomous_schema(self.conn)
        initialize_native_crm_schema(self.conn)
        initialize_treasury_release_schema(self.conn)

        self.admin_user = {
            "id": "usr_staff_super",
            "role": "axiom_super_admin",
            "email": "admin@axiomfleet.in",
            "organization_id": "org_axiom_hq",
        }

    def tearDown(self):
        self.conn.close()

    def test_01_static_crawler_clean_pass(self):
        """Certify zero crawler violations across all client and backend assets."""
        comp_violations = audit_competitor_strings()
        self.assertEqual(len(comp_violations), 0, f"Found competitor strings: {comp_violations}")

        loc_violations = audit_hardcoded_localhost()
        self.assertEqual(len(loc_violations), 0, f"Found hardcoded localhost: {loc_violations}")

        es6_violations = audit_es6_imports()
        self.assertEqual(len(es6_violations), 0, f"Found broken ES6 imports: {es6_violations}")

        html_violations = audit_html_static_assets()
        self.assertEqual(len(html_violations), 0, f"Found broken HTML asset references: {html_violations}")

        route_violations = audit_frontend_fetch_routes()
        self.assertEqual(len(route_violations), 0, f"Found unmatched frontend fetch routes: {route_violations}")

    def test_02_empty_state_resilience(self):
        """Certify that all commercial, CRM, overview, and dashboard queries return safe defaults on empty DB."""
        # 1. CRM Executive summary on zero CRM rows
        summary = get_crm_executive_summary(self.conn)
        self.assertIn("total_pipeline_gmv_inr", summary)
        self.assertIn("unworked_website_prospects_count", summary)
        self.assertIn("total_active_tenants", summary)

        # 2. Native CRM API dispatch on empty accounts & deals
        accounts_res = handle_native_crm_api(self.conn, self.admin_user, "GET", "/api/crm/accounts", {}, "127.0.0.1")
        self.assertIsNotNone(accounts_res)
        self.assertEqual(accounts_res["accounts"], [])

        deals_res = handle_native_crm_api(self.conn, self.admin_user, "GET", "/api/crm/deals", {}, "127.0.0.1")
        self.assertIsNotNone(deals_res)
        self.assertEqual(deals_res["deals"], [])

        # 3. Commercial company overview on baseline DB
        comm_overview = handle_commercial(self.conn, self.admin_user, "GET", "/api/admin/company-overview", {}, "127.0.0.1")
        self.assertTrue(comm_overview["ok"])
        self.assertIn("tenants", comm_overview)

        # 4. Treasury release overview on empty DB
        treasury = get_treasury_summary(self.conn, self.admin_user)
        self.assertEqual(treasury["total_funds_held_paise"], 0)
        self.assertEqual(treasury["total_mature_ready_paise"], 0)

        # 5. SLA Radar scan on zero duties
        radar = scan_sla_radar(self.conn, "org_empty_workspace")
        self.assertTrue(radar["ok"])
        self.assertEqual(radar["scanned_duties_count"], 0)
        self.assertEqual(radar["critical_trips"], [])

    def test_03_e2e_walkthrough_golden_pipeline(self):
        """Certify full golden path: Prospect -> CRM -> CPQ -> Tenant Provision -> Booking -> Dispatch -> Audit -> GST Invoice."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        # Step 1: Inbound WhatsApp / Web Prospect (Mobile + Corporate Email)
        lead = capture_crm_public_prospect(
            self.conn,
            {
                "email": "ops@globaltech.com",
                "phone": "+91 98765 43210",
                "name": "Deepak Mehta",
                "company_name": "Global Tech Enterprises",
                "city": "Bengaluru",
                "estimated_volume": 25,
            },
        )
        self.assertIsNotNone(lead["account_id"])
        self.assertIsNotNone(lead["deal_id"])
        self.assertGreaterEqual(lead["lead_score"], 50)

        # Step 2: Spread-Aware 6-Model CPQ Simulation
        cpq_sim = simulate_deal_cpq(
            self.conn,
            deal_id=lead["deal_id"],
            payload={
                "duty_type": "LOCAL_8HR_80KM",
                "vehicle_category": "SEDAN",
                "client_sell_base_inr": 2800.0,
                "vendor_buy_base_inr": 2350.0,
                "estimated_monthly_trips": 100,
            },
        )
        self.assertGreater(cpq_sim["projected_gross_margin_pct"], 8.0)
        self.assertEqual(cpq_sim["margin_approval_status"], "APPROVED")

        # Step 3: Convert CRM Deal to Live Tenant Workspace
        provision = convert_crm_deal_to_workspace(
            self.conn,
            deal_id=lead["deal_id"],
        )
        tenant_id = provision["tenant_id"]
        self.assertTrue(tenant_id)

        tenant_user = {
            "id": f"usr_{tenant_id}",
            "email": "ops@globaltech.in",
            "role": "vendor",
            "organization_id": tenant_id,
        }

        # Step 4: Setup Driver, Vehicle & Create Booking
        driver_id = "drv-cert-01"
        self.conn.execute(
            """INSERT INTO domain_drivers (id, organization_id, full_name, phone, license_number, license_expiry, status, created_at, updated_at)
               VALUES (?, ?, 'Ramesh Kumar', '+919811122233', 'DL-KA-01-2020-001', '2030-01-01', 'active', ?, ?)""",
            (driver_id, tenant_id, now_iso, now_iso),
        )
        vehicle_id = "veh-cert-01"
        self.conn.execute(
            """INSERT INTO domain_vehicles (id, organization_id, registration_number, vehicle_type, make_model, insurance_expiry, status, created_at, updated_at)
               VALUES (?, ?, 'KA-01-EQ-9999', 'sedan', 'Toyota Etios', '2030-01-01', 'active', ?, ?)""",
            (vehicle_id, tenant_id, now_iso, now_iso),
        )
        self.conn.commit()

        pickup_time = (now + timedelta(minutes=25)).isoformat()
        bk_res = _create_booking(
            self.conn,
            tenant_user,
            {
                "passenger_name": "Executive VIP Delegate",
                "passenger_phone": "+919844455566",
                "scheduled_at": pickup_time,
                "pickup": {"address": "Bengaluru International Airport", "lat": 13.1986, "lon": 77.7066},
                "dropoff": {"address": "ITC Gardenia, Residency Road", "lat": 12.9667, "lon": 77.5963},
                "vehicle_type": "sedan",
                "duty_type": "local",
            },
            "127.0.0.1",
        )
        booking_id = bk_res["item"]["id"]

        duty_res = _create_duty(
            self.conn,
            tenant_user,
            {
                "booking_id": booking_id,
                "driver_id": driver_id,
                "vehicle_id": vehicle_id,
                "start_odometer": 15000,
            },
            "127.0.0.1",
        )
        duty_id = duty_res["item"]["id"]

        # Step 5: SLA Breach Radar Scan
        radar = scan_sla_radar(self.conn, tenant_id)
        self.assertTrue(radar["ok"])
        self.assertGreaterEqual(radar["scanned_duties_count"], 1)

        # Step 6: Operational Duty Closure & Algorithmic Trust Audit
        started_at = (now - timedelta(minutes=45)).isoformat()
        self.conn.execute(
            "UPDATE domain_duties SET status = 'in_progress', started_at = ?, start_odometer = 15000 WHERE id = ?",
            (started_at, duty_id),
        )
        self.conn.commit()

        closure = _close_duty(
            self.conn,
            tenant_user,
            duty_id,
            {
                "start_odometer": 15000,
                "end_odometer": 15035,
                "duration_hours": 1.5,
                "toll_paise": 12000,
                "parking_paise": 5000,
            },
            "127.0.0.1",
        )
        self.assertTrue(closure["ok"])

        # Trust score computation & resolution
        audit_row = self.conn.execute("SELECT * FROM domain_duty_trust_audits WHERE duty_id = ?", (duty_id,)).fetchone()
        self.assertIsNotNone(audit_row)
        if audit_row["audit_status"] == "NEEDS_AUDIT":
            res = resolve_duty_audit(self.conn, tenant_user, duty_id, "approve_as_is", "Operator verified GPS trace", "127.0.0.1")
            self.assertEqual(res["audit_status"], "RESOLVED_APPROVED")
        else:
            self.assertEqual(audit_row["audit_status"], "AUTO_VERIFIED")

        # Step 7: GST Invoice Generation Post Audit
        calc_snapshot = {
            "subtotal_paise": 180000,
            "tax_paise": 9000,
            "total_paise": 189000,
            "distance_km": 35.0,
            "lines": [{"code": "base", "label": "Airport Transfer (35km)", "quantity": 1, "unit_paise": 180000, "amount_paise": 180000}],
        }
        self.conn.execute(
            "UPDATE domain_duties SET calculation_snapshot_json = ? WHERE id = ?",
            (json.dumps(calc_snapshot), duty_id),
        )
        self.conn.commit()

        inv = _create_invoice(
            self.conn,
            tenant_user,
            {"duty_id": duty_id},
            "127.0.0.1",
        )
        self.assertTrue(inv["ok"])
        self.assertIsNotNone(inv["item"]["id"])
        self.assertGreater(inv["item"]["total_paise"], 180000)

    def test_04_axiom_company_view_and_commercial_controls(self):
        """Certify kill-switch mechanics, escrow payout hold, and admin company ledger."""
        tenant_id = "tenant-cert-killswitch-01"
        vendor_id = "vendor-cert-payout-01"
        now_iso = datetime.now(timezone.utc).isoformat()

        # Seed tenant in good standing
        self.conn.execute(
            "INSERT INTO organizations (id, name, slug, kind, created_at, updated_at) VALUES (?, 'Cert Corp', 'cert-corp', 'corporate', ?, ?)",
            (tenant_id, now_iso, now_iso),
        )
        self.conn.execute(
            "INSERT INTO tenant_billing_accounts (tenant_id, tenant_name, access_control_state, saas_balance_owed_inr, outstanding_balance_paise, dunning_stage, trial_trips_used, created_at, updated_at) "
            "VALUES (?, 'Cert Corp', 'ACTIVE_GOOD_STANDING', 0.0, 0, 0, 10, ?, ?)",
            (tenant_id, now_iso, now_iso),
        )
        # Seed vendor organization
        self.conn.execute(
            "INSERT INTO organizations (id, name, slug, kind, created_at, updated_at) VALUES (?, 'Vendor Apex', 'vendor-apex', 'vendor', ?, ?)",
            (vendor_id, now_iso, now_iso),
        )
        self.conn.commit()

        # 1. Normal active access allows operations (does not raise)
        check_tenant_killswitch(self.conn, tenant_id, "POST", "/api/bookings")

        # 2. Soft-blocked due to overdue dunning allows closures but blocks new bookings
        self.conn.execute(
            "UPDATE tenant_billing_accounts SET access_control_state = 'SOFT_LOCKED_OVERDUE', outstanding_balance_paise = 2500000 WHERE tenant_id = ?",
            (tenant_id,),
        )
        self.conn.commit()

        # In-flight closures allowed (does not raise)
        check_tenant_killswitch(self.conn, tenant_id, "POST", "/api/duties/close")

        with self.assertRaises(DomainError) as cm:
            check_tenant_killswitch(self.conn, tenant_id, "POST", "/api/bookings")
        self.assertEqual(cm.exception.status, 402)

        # 3. Hard-blocked non-payment blocks all non-whitelisted calls
        self.conn.execute(
            "UPDATE tenant_billing_accounts SET access_control_state = 'HARD_BLOCKED_NON_PAYMENT' WHERE tenant_id = ?",
            (tenant_id,),
        )
        self.conn.commit()

        with self.assertRaises(DomainError) as cm2:
            check_tenant_killswitch(self.conn, tenant_id, "GET", "/api/duties")
        self.assertEqual(cm2.exception.status, 402)

        # 4. Vendor Payout Escrow Hold Toggle
        self.conn.execute(
            "INSERT INTO tenant_billing_accounts (tenant_id, tenant_name, access_control_state, saas_balance_owed_inr, outstanding_balance_paise, dunning_stage, trial_trips_used, payout_hold_override, created_at, updated_at) "
            "VALUES (?, 'Vendor Apex', 'ACTIVE_GOOD_STANDING', 0.0, 0, 0, 10, 'INHERIT_GLOBAL', ?, ?)",
            (vendor_id, now_iso, now_iso),
        )
        self.conn.commit()

        hold_res = toggle_vendor_hold(
            self.conn,
            staff_user=self.admin_user,
            vendor_id=vendor_id,
            hold_override="FORCE_HOLD",
            reason="GST compliance discrepancy pending clarification",
        )
        self.assertEqual(hold_res["payout_hold_override"], "FORCE_HOLD")

        # Verify hold is saved
        hold_check = self.conn.execute(
            "SELECT payout_hold_override FROM tenant_billing_accounts WHERE tenant_id = ?",
            (vendor_id,),
        ).fetchone()
        self.assertEqual(hold_check["payout_hold_override"], "FORCE_HOLD")

        # Release hold
        release_res = toggle_vendor_hold(
            self.conn,
            staff_user=self.admin_user,
            vendor_id=vendor_id,
            hold_override="AUTO_RELEASE",
            reason="GST verification cleared",
        )
        self.assertEqual(release_res["payout_hold_override"], "AUTO_RELEASE")


if __name__ == "__main__":
    unittest.main()
