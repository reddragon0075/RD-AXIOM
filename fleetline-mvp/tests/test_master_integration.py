#!/usr/bin/env python3
"""Axiom Mobility Master Integration Pipeline Test.

Executes the full-lifecycle multi-actor workflow covering Phases 1 through 6:
1. Public Prospect Capture (mobile/email lead intake)
2. Tariff ROI Simulator (What-If scenario comparison across 6 models)
3. 1-Click Onboard Prospect to Active Corporate Tenant with credentials
4. Corporate Booking & Dispatch to Driver/Vehicle
5. SLA Radar & Night Safety Guardian Monitoring
6. Trip Closure with Inflated Odometer -> Triggers Algorithmic Trust Flag (NEEDS_AUDIT)
7. State Machine Guard: Invoicing blocked while duty in NEEDS_AUDIT
8. 1-Click Discrepancy Resolution (snap_gps_distance)
9. Invoicing generated cleanly after resolution
10. Automated Credit-Limit Dunning -> SOFT_BLOCKED kill-switch activation (402)
11. Instant Self-Serve Payment Settlement -> Restores ACTIVE status & unblocks operations
"""

from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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
from backend_impersonation import (
    initialize_impersonation_schema,
    mint_shadow_jwt,
    verify_shadow_jwt,
    check_read_only_mutation_guard,
)
from backend_hyper_network import (
    initialize_hyper_network_schema,
    post_duty_to_exchange,
    get_masked_exchange_feed,
    claim_network_duty,
    instant_t0_factoring_cashout,
    allot_and_verify_compliance_passport,
    get_zk_compliance_proof,
)
from backend_treasury_release import (
    initialize_treasury_release_schema,
    set_global_treasury_payout_hold,
)

from backend_autonomous import (
    initialize_autonomous_schema,
    compute_trip_trust_score,
    resolve_duty_audit,
    scan_sla_radar,
    simulate_tariff_scenarios,
    check_credit_limit_dunning,
    self_settle_tenant_dues,
)


class TestMasterIntegrationPipeline(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        # Initialize base schema
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
        initialize_autonomous_schema(self.conn)
        initialize_impersonation_schema(self.conn)
        initialize_hyper_network_schema(self.conn)
        initialize_treasury_release_schema(self.conn)

        now = datetime.now(timezone.utc).isoformat()
        # Seed Super-Admin
        self.admin_user = {
            "id": "usr_super_admin",
            "email": "superadmin@axiomfleet.in",
            "role": "axiom_super_admin",
            "organization_id": "org_axiom_hq",
        }
        self.conn.execute(
            "INSERT INTO organizations (id, kind, name, created_at) VALUES ('org_axiom_hq', 'axiom_hq', 'Axiom Mobility HQ', ?)",
            (now,),
        )
        self.conn.execute(
            "INSERT INTO users (id, email, password_hash, password_salt, role, full_name, organization_id, created_at) VALUES (?, ?, 'h', 's', ?, 'Super Admin', 'org_axiom_hq', ?)",
            (self.admin_user["id"], self.admin_user["email"], self.admin_user["role"], now),
        )

    def tearDown(self):
        self.conn.close()

    def test_full_autonomous_lifecycle_golden_pipeline(self):
        now = datetime.now(timezone.utc).isoformat()

        # -------------------------------------------------------------
        # STEP 1: Website Prospect Capture (Lead Intake)
        # -------------------------------------------------------------
        prospect_payload = {
            "contact_name": "Arun Verma",
            "company_name": "Verma Enterprises Ltd",
            "email": "arun.verma@vermaenterprises.in",
            "mobile_number": "+919876543210",
            "message": "Interested in deploying 45 cabs for our Bangalore campuses.",
        }
        lead_res = handle_public_prospects(
            self.conn, "POST", "/api/v1/public/prospects", prospect_payload, "127.0.0.1"
        )
        self.assertIsNotNone(lead_res)
        self.assertTrue(lead_res["ok"])
        prospect_id = lead_res["prospect_id"]
        self.assertEqual(lead_res["status"], "NEW")

        # -------------------------------------------------------------
        # STEP 2: Tariff ROI Simulator Execution
        # -------------------------------------------------------------
        sim_res = simulate_tariff_scenarios({
            "monthly_trips": 120,
            "average_distance_km": 40.0,
            "average_duration_hours": 3.5,
        })
        self.assertTrue(sim_res["ok"])
        self.assertEqual(len(sim_res["comparison_matrix"]), 6)
        self.assertIn("optimal_recommendation", sim_res)
        self.assertGreater(sim_res["optimal_recommendation"]["projected_monthly_spend_inr"], 0)

        # -------------------------------------------------------------
        # STEP 3: 1-Click Onboard Prospect to Active Tenant
        # -------------------------------------------------------------
        onboard_res = handle_commercial(
            self.conn,
            self.admin_user,
            "POST",
            f"/api/v1/admin/prospects/{prospect_id}/onboard",
            {},
            "127.0.0.1",
        )
        self.assertIsNotNone(onboard_res)
        self.assertTrue(onboard_res["ok"])
        tenant_id = onboard_res["tenant_id"]
        login_email = onboard_res["credentials"]["email"]

        # Verify tenant billing account
        acct = self.conn.execute("SELECT * FROM tenant_billing_accounts WHERE tenant_id = ?", (tenant_id,)).fetchone()
        self.assertIsNotNone(acct)
        self.assertEqual(acct["account_status"], "ACTIVE")

        tenant_user = {
            "id": f"usr_{tenant_id}",
            "email": login_email,
            "role": "vendor",
            "organization_id": tenant_id,
        }

        # -------------------------------------------------------------
        # STEP 4: Setup Fleet & Dispatch Duty
        # -------------------------------------------------------------
        driver_id = "drv_master_01"
        self.conn.execute(
            """INSERT INTO domain_drivers (id, organization_id, full_name, phone, license_number, license_expiry, status, created_at, updated_at)
               VALUES (?, ?, 'Mahesh Pilot', '+919876543299', 'DL-KA-2022-99', '2030-01-01', 'active', ?, ?)""",
            (driver_id, tenant_id, now, now),
        )
        backup_driver_id = "drv_master_backup"
        self.conn.execute(
            """INSERT INTO domain_drivers (id, organization_id, full_name, phone, license_number, license_expiry, status, created_at, updated_at)
               VALUES (?, ?, 'Kiran Backup', '+919876543298', 'DL-KA-2022-98', '2030-01-01', 'active', ?, ?)""",
            (backup_driver_id, tenant_id, now, now),
        )

        vehicle_id = "veh_master_01"
        self.conn.execute(
            """INSERT INTO domain_vehicles (id, organization_id, registration_number, vehicle_type, make_model, insurance_expiry, status, created_at, updated_at)
               VALUES (?, ?, 'KA-01-EQ-7788', 'sedan', 'Toyota Etios', '2030-01-01', 'active', ?, ?)""",
            (vehicle_id, tenant_id, now, now),
        )

        now_dt = datetime.now(timezone.utc)
        pickup_time = (now_dt + timedelta(minutes=15)).isoformat()
        bk_res = _create_booking(
            self.conn,
            tenant_user,
            {
                "passenger_name": "Sunita Rao (Female Solo)",
                "passenger_phone": "+919811122233",
                "duty_type": "local",
                "vehicle_type": "sedan",
                "scheduled_at": pickup_time,
                "pickup": {"address": "Manyata Tech Park", "lat": 13.0475, "lon": 77.6200},
                "dropoff": {"address": "Indiranagar 100ft Rd", "lat": 12.9719, "lon": 77.6412},
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
                "start_odometer": 1000,
            },
            "127.0.0.1",
        )
        duty_id = duty_res["item"]["id"]

        # -------------------------------------------------------------
        # STEP 5: SLA Breach Radar & Night Safety Guardian Scan
        # -------------------------------------------------------------
        radar = scan_sla_radar(self.conn, tenant_id)
        self.assertTrue(radar["ok"])
        self.assertGreaterEqual(radar["scanned_duties_count"], 1)
        self.assertEqual(len(radar["critical_trips"]), 1)
        self.assertEqual(radar["critical_trips"][0]["duty_id"], duty_id)
        self.assertGreaterEqual(len(radar["critical_trips"][0]["suggested_backups"]), 1)

        # -------------------------------------------------------------
        # STEP 6: Close Trip with Inflated Odometer (Discrepancy)
        # -------------------------------------------------------------
        # Start trip
        started_at = (now_dt - timedelta(minutes=40)).isoformat()
        self.conn.execute(
            "UPDATE domain_duties SET status = 'in_progress', started_at = ?, start_odometer = 1000 WHERE id = ?",
            (started_at, duty_id),
        )
        self.conn.commit()

        # Expected distance: 30 km; driver claims 80 km (166% variance!)
        closure_payload = {
            "end_odometer": 1080,
            "end_km": 1080,
            "expected_distance_km": 30.0,
            "otp_verified": True,
        }
        closed = _close_duty(self.conn, tenant_user, duty_id, closure_payload, "127.0.0.1")
        audit = closed["trust_audit"]
        self.assertEqual(audit["audit_status"], "NEEDS_AUDIT")
        self.assertLess(audit["trust_score"], 80)
        flag_codes = [f["code"] for f in audit["audit_flags"]]
        self.assertIn("ODOMETER_GPS_VARIANCE", flag_codes)

        # -------------------------------------------------------------
        # STEP 7: Verify State Machine Invoicing Lock on NEEDS_AUDIT
        # -------------------------------------------------------------
        # Inject calculation snapshot so invoice generation can be attempted
        calc_snapshot = {
            "subtotal_paise": 150000,
            "tax_paise": 7500,
            "total_paise": 157500,
            "distance_km": 80.0,
            "lines": [{"code": "base", "label": "Base Fare", "quantity": 1, "unit_paise": 150000, "amount_paise": 150000}],
        }
        self.conn.execute(
            "UPDATE domain_duties SET calculation_snapshot_json = ? WHERE id = ?",
            (json.dumps(calc_snapshot), duty_id),
        )
        self.conn.commit()

        with self.assertRaises(DomainError) as ctx:
            _create_invoice(self.conn, tenant_user, {"duty_id": duty_id}, "127.0.0.1")
        self.assertEqual(ctx.exception.status, 422)
        self.assertEqual(ctx.exception.code, "audit_resolution_required")

        # -------------------------------------------------------------
        # STEP 8: 1-Click Discrepancy Resolution (snap_gps_distance)
        # -------------------------------------------------------------
        res = resolve_duty_audit(
            self.conn,
            tenant_user,
            duty_id,
            "snap_gps_distance",
            "Auto-snapped to GPS route 30.0 km",
            "127.0.0.1",
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["audit_status"], "RESOLVED_SNAPPED")
        self.assertEqual(res["end_odometer"], 1030)

        # Recalculate snapshot with corrected distance
        calc_snapshot_corrected = {
            "subtotal_paise": 85000,
            "tax_paise": 4250,
            "total_paise": 89250,
            "distance_km": 30.0,
            "lines": [{"code": "base", "label": "Base Fare (30km)", "quantity": 1, "unit_paise": 85000, "amount_paise": 85000}],
        }
        self.conn.execute(
            "UPDATE domain_duties SET calculation_snapshot_json = ? WHERE id = ?",
            (json.dumps(calc_snapshot_corrected), duty_id),
        )
        self.conn.commit()

        # -------------------------------------------------------------
        # STEP 9: Invoice Generated Cleanly Post-Resolution
        # -------------------------------------------------------------
        inv_res = _create_invoice(self.conn, tenant_user, {"duty_id": duty_id}, "127.0.0.1")
        self.assertTrue(inv_res["ok"])
        self.assertIn("item", inv_res)
        duty_row = self.conn.execute("SELECT status FROM domain_duties WHERE id = ?", (duty_id,)).fetchone()
        self.assertEqual(duty_row["status"], "invoiced")

        # -------------------------------------------------------------
        # STEP 10: Tenant Credit Limit Breach & Auto-Dunning (SOFT_BLOCKED)
        # -------------------------------------------------------------
        self.conn.execute(
            """UPDATE tenant_billing_accounts SET
               credit_limit_paise = 100000,
               outstanding_balance_paise = 350000
               WHERE tenant_id = ?""",
            (tenant_id,),
        )
        self.conn.commit()

        check_credit_limit_dunning(self.conn, tenant_id)
        acct_post = self.conn.execute("SELECT account_status FROM tenant_billing_accounts WHERE tenant_id = ?", (tenant_id,)).fetchone()
        self.assertEqual(acct_post["account_status"], "SOFT_BLOCKED")

        # Kill-switch stops new bookings
        with self.assertRaises(DomainError) as ctx:
            check_tenant_killswitch(self.conn, tenant_id, "POST", "/api/v1/bookings")
        self.assertEqual(ctx.exception.status, 402)
        self.assertEqual(ctx.exception.code, "TENANT_BLOCKED_NON_PAYMENT")

        # -------------------------------------------------------------
        # STEP 11: Instant Self-Serve Settlement & Unblock
        # -------------------------------------------------------------
        settle_res = self_settle_tenant_dues(
            self.conn,
            tenant_user,
            {"payment_method": "UPI_INSTANT", "reference_id": "UPI_SETTLE_MASTER_01"},
            "127.0.0.1",
        )
        self.assertTrue(settle_res["ok"])
        self.assertEqual(settle_res["account_status"], "ACTIVE")
        self.assertEqual(settle_res["new_outstanding_balance_paise"], 0)

        # Operations unblocked
        check_tenant_killswitch(self.conn, tenant_id, "POST", "/api/v1/bookings")
        print("\n>> MASTER INTEGRATION PIPELINE VERIFIED: All 11 autonomous stages passed with zero seams.")



    def test_hyper_network_and_shadow_impersonation_lifecycle(self):
        """Exercises Shadow JWT Impersonation, Anti-Poaching Hyper-Network Exchange, ZK Passport & T+0 Factoring."""
        now = datetime.now(timezone.utc).isoformat()

        # Step 1: Create Partner Organizations & Billing Accounts
        org_alpha = "org_alpha_fleets"
        org_beta = "org_beta_transport"
        self.conn.execute("INSERT INTO organizations (id, kind, name, created_at) VALUES (?, 'vendor', 'Alpha Fleets', ?)", (org_alpha, now))
        self.conn.execute("INSERT INTO organizations (id, kind, name, created_at) VALUES (?, 'vendor', 'Beta Transport', ?)", (org_beta, now))
        self.conn.execute(
            """INSERT INTO tenant_billing_accounts (tenant_id, tenant_name, account_status, credit_limit_paise, outstanding_balance_paise, sla_tier, created_at, updated_at)
               VALUES (?, 'Alpha Fleets', 'ACTIVE', 5000000, 0, 'TIER_1_PLATINUM', ?, ?)""",
            (org_alpha, now, now),
        )
        self.conn.execute(
            """INSERT INTO tenant_billing_accounts (tenant_id, tenant_name, account_status, credit_limit_paise, outstanding_balance_paise, sla_tier, created_at, updated_at)
               VALUES (?, 'Beta Transport', 'ACTIVE', 5000000, 0, 'TIER_2_GOLD', ?, ?)""",
            (org_beta, now, now),
        )

        user_alpha = {"id": "usr_alpha_admin", "organization_id": org_alpha, "role": "vendor"}
        user_beta = {"id": "usr_beta_admin", "organization_id": org_beta, "role": "vendor"}

        # Step 2: Shadow JWT Impersonation & Guardrails
        token, exp_ts = mint_shadow_jwt(org_alpha, "Alpha Fleets", self.admin_user["id"], "usr_alpha_admin", "READ_ONLY", 30*60)
        claims = verify_shadow_jwt(token)
        self.assertIsNotNone(token)
        self.assertEqual(claims["impersonation_mode"], "READ_ONLY")
        self.assertEqual(claims["actor_admin_id"], self.admin_user["id"])

        # Verify read-only mutation guard prevents POST / PUT
        block = check_read_only_mutation_guard("POST", "/api/v1/bookings", claims)
        self.assertIsNotNone(block)
        status, body = block
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "READ_ONLY_SHADOW_MODE")

        # Privilege escalation prevention
        esc_block = check_read_only_mutation_guard("POST", "/admin/impersonate/start", claims)
        self.assertIsNotNone(esc_block)
        status, body = esc_block
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "PRIVILEGE_ESCALATION_FORBIDDEN")

        # Step 3: Seed Corporate Duty & Overflow to Hyper-Network Exchange
        bk = _create_booking(
            self.conn,
            user_alpha,
            {
                "passenger_name": "Dr. Ananya Sen (Confidential VIP)",
                "passenger_phone": "+919876543210",
                "duty_type": "outstation",
                "vehicle_type": "sedan",
                "scheduled_at": now,
                "pickup": {"address": "Koramangala 4th Block", "lat": 12.9352, "lon": 77.6245},
                "dropoff": {"address": "Mysuru Palace", "lat": 12.3052, "lon": 76.6552},
            },
            "127.0.0.1",
        )
        duty = _create_duty(self.conn, user_alpha, {"booking_id": bk["item"]["id"]}, "127.0.0.1")
        duty_id = duty["item"]["id"]

        post_res = post_duty_to_exchange(
            self.conn,
            user_alpha,
            {
                "duty_id": duty_id,
                "client_receivable_paise": 650000,  # INR 6500
                "base_supplier_payable_paise": 520000,  # INR 5200
                "estimated_distance_km": 145.0,
                "prefer_ev_green_corridor": False,
                "margin_floor_pct": 15.0,
            },
            "127.0.0.1",
        )
        self.assertTrue(post_res["ok"])
        listing_id = post_res["listing_id"]

        # Advance to Wave 2 so Gold partner Beta Transport sees it
        self.conn.execute("UPDATE network_listings SET current_wave = 2 WHERE id = ?", (listing_id,))
        self.conn.commit()

        # Step 4: Double-Blind Anti-Poaching Verification
        feed = get_masked_exchange_feed(self.conn, user_beta, {})
        partner_item = next(x for x in feed["listings"] if x["id"] == listing_id)
        self.assertNotIn("client_receivable_paise", partner_item)
        self.assertNotIn("passenger_name", partner_item)
        self.assertNotIn("passenger_phone", partner_item)
        self.assertEqual(partner_item["corporate_client_name"], "Confidential Enterprise Client")
        self.assertEqual(partner_item["client_brand_display_name"], "Axiom Partner Network")
        self.assertTrue(partner_item["is_white_labeled"])

        # Step 5: Partner Claim & Concurrency Guard
        claim_res = claim_network_duty(self.conn, user_beta, listing_id, "127.0.0.1")
        self.assertTrue(claim_res["ok"])
        self.assertEqual(claim_res["status"], "CLAIMED")

        # Second claim fails with 409
        with self.assertRaises(DomainError) as ctx:
            claim_network_duty(self.conn, user_beta, listing_id, "127.0.0.1")
        self.assertEqual(ctx.exception.status, 409)

        # Step 6: Driver/Vehicle Compliance Passport & ZK Seal Allotment
        drv_id = "drv_beta_pilot"
        veh_id = "veh_beta_car"
        self.conn.execute(
            """INSERT INTO domain_drivers (id, organization_id, full_name, phone, license_number, license_expiry, status, created_at, updated_at)
               VALUES (?, ?, 'Ramesh Gowda', '+919988112233', 'DL-KA-2023-999', '2032-01-01', 'active', ?, ?)""",
            (drv_id, org_beta, now, now),
        )
        self.conn.execute(
            """INSERT INTO domain_vehicles (id, organization_id, registration_number, vehicle_type, fuel_type, make_model, insurance_expiry, status, created_at, updated_at)
               VALUES (?, ?, 'KA-04-MN-5566', 'sedan', 'DIESEL', 'Maruti Dzire', '2030-01-01', 'active', ?, ?)""",
            (veh_id, org_beta, now, now),
        )
        self.conn.commit()

        passport_res = allot_and_verify_compliance_passport(self.conn, user_beta, listing_id, drv_id, veh_id, "127.0.0.1")
        self.assertTrue(passport_res["ok"])
        self.assertIn("zk_compliance_seal_hash", passport_res)

        zk_proof = get_zk_compliance_proof(self.conn, duty_id)
        self.assertTrue(zk_proof["ok"])
        self.assertIn("Cryptographic Compliance Seal Verified", zk_proof["seal_badge"])

        # Step 7: T+0 Factoring Cashout & Escrow Release
        t0_res = instant_t0_factoring_cashout(self.conn, user_beta, duty_id, "127.0.0.1")
        self.assertTrue(t0_res["ok"])
        self.assertEqual(t0_res["gross_payable_inr"], 5200.0)
        self.assertEqual(t0_res["platform_factoring_fee_inr"], 91.0)  # 5200 * 0.0175
        self.assertEqual(t0_res["instant_net_disbursement_inr"], 5109.0)

        # Duplicate cashout blocked with 409
        with self.assertRaises(DomainError) as ctx:
            instant_t0_factoring_cashout(self.conn, user_beta, duty_id, "127.0.0.1")
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(ctx.exception.code, "already_cashed_out")

        print("\n>> HYPER-NETWORK, SHADOW IMPERSONATION & T+0 FACTORING LIFECYCLE VERIFIED.")


if __name__ == "__main__":
    unittest.main()
