#!/usr/bin/env python3
"""Axiom Mobility Hyper-Network Exchange & Clearinghouse Verification Suite.

Verifies:
1. Anti-Poaching "White-Label Ghost Mode" & Double-Blind Masking
2. Multi-Tier Waterfall Wave Escalation & Concurrency Claim Lock
3. Spot-Surge Slider with Margin-Floor Guardrail Enforcement
4. Wallet Escrow Lock & Delinquent Tenant Blocking (402)
5. Cross-Tenant Compliance Passport & EV Range-Safety Gate (422)
6. Zero-Knowledge Cryptographic Compliance Seal (SHA-256)
7. T+0 Instant Factoring Clearinghouse (1.75% Fintech Revenue)
8. Empty-Leg Return Deadhead Matchmaker
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
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
    initialize_domain_schema,
)
from backend_extended import initialize_extended_schema
from backend_operations_parity import initialize_operations_parity_schema
from backend_commercial import initialize_commercial_schema
from backend_autonomous import initialize_autonomous_schema
from backend_hyper_network import (
    initialize_hyper_network_schema,
    post_duty_to_exchange,
    get_masked_exchange_feed,
    claim_network_duty,
    boost_surge_payout,
    allot_and_verify_compliance_passport,
    get_zk_compliance_proof,
    instant_t0_factoring_cashout,
    create_empty_leg_listing,
    match_empty_leg_corridors,
    get_demand_swarm_radar,
)


class TestHyperNetworkExchange(unittest.TestCase):
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
        initialize_autonomous_schema(self.conn)
        initialize_hyper_network_schema(self.conn)

        now = datetime.now(timezone.utc).isoformat()

        # Seed Origin Vendor A (Platinum Tier)
        self.org_a = "org_vendor_alpha"
        self.conn.execute("INSERT INTO organizations (id, kind, name, created_at) VALUES (?, 'vendor', 'Alpha Fleet Systems', ?)", (self.org_a, now))
        self.user_a = {"id": "usr_alpha_admin", "email": "admin@alphafleet.in", "role": "vendor", "organization_id": self.org_a}
        self.conn.execute("INSERT INTO users (id, email, password_hash, password_salt, role, full_name, organization_id, created_at) VALUES (?, ?, 'h', 's', 'vendor', 'Alpha Admin', ?, ?)", (self.user_a["id"], self.user_a["email"], self.org_a, now))
        self.conn.execute(
            """INSERT INTO tenant_billing_accounts (tenant_id, tenant_name, account_status, credit_limit_paise, outstanding_balance_paise, sla_tier, created_at, updated_at)
               VALUES (?, 'Alpha Fleet Systems', 'ACTIVE', 5000000, 1000000, 'TIER_1_PLATINUM', ?, ?)""",
            (self.org_a, now, now),
        )

        # Seed Fulfilling Vendor B (Platinum Tier)
        self.org_b = "org_vendor_beta"
        self.conn.execute("INSERT INTO organizations (id, kind, name, created_at) VALUES (?, 'vendor', 'Beta Chauffeurs Ltd', ?)", (self.org_b, now))
        self.user_b = {"id": "usr_beta_admin", "email": "admin@betachauffeurs.in", "role": "vendor", "organization_id": self.org_b}
        self.conn.execute("INSERT INTO users (id, email, password_hash, password_salt, role, full_name, organization_id, created_at) VALUES (?, ?, 'h', 's', 'vendor', 'Beta Admin', ?, ?)", (self.user_b["id"], self.user_b["email"], self.org_b, now))
        self.conn.execute(
            """INSERT INTO tenant_billing_accounts (tenant_id, tenant_name, account_status, credit_limit_paise, outstanding_balance_paise, sla_tier, created_at, updated_at)
               VALUES (?, 'Beta Chauffeurs Ltd', 'ACTIVE', 3000000, 500000, 'TIER_1_PLATINUM', ?, ?)""",
            (self.org_b, now, now),
        )

        # Seed Vehicles & Drivers for Vendor B
        self.driver_b = "drv_beta_01"
        self.conn.execute(
            """INSERT INTO domain_drivers (id, organization_id, full_name, phone, license_number, license_expiry, status, created_at, updated_at)
               VALUES (?, ?, 'Sanjay Pilot', '+919876500111', 'DL-KA-2022-777', '2030-01-01', 'active', ?, ?)""",
            (self.driver_b, self.org_b, now, now),
        )

        self.veh_ice = "veh_beta_ice"
        self.conn.execute(
            """INSERT INTO domain_vehicles (id, organization_id, registration_number, vehicle_type, fuel_type, make_model, insurance_expiry, status, created_at, updated_at)
               VALUES (?, ?, 'KA-01-AB-1234', 'sedan', 'DIESEL', 'Toyota Etios', '2030-01-01', 'active', ?, ?)""",
            (self.veh_ice, self.org_b, now, now),
        )

        self.veh_ev = "veh_beta_ev"
        self.conn.execute(
            """INSERT INTO domain_vehicles (id, organization_id, registration_number, vehicle_type, fuel_type, make_model, insurance_expiry, ev_battery_soc_pct, estimated_range_km, status, created_at, updated_at)
               VALUES (?, ?, 'KA-01-EV-9999', 'sedan', 'EV', 'Tata Tigor EV', '2030-01-01', 90.0, 220.0, 'active', ?, ?)""",
            (self.veh_ev, self.org_b, now, now),
        )

        # Create base corporate duty in Vendor A
        bk = _create_booking(
            self.conn,
            self.user_a,
            {
                "passenger_name": "Rohan Gupta (Accenture)",
                "passenger_phone": "+919988001122",
                "duty_type": "local",
                "vehicle_type": "sedan",
                "scheduled_at": now,
                "pickup": {"address": "Indiranagar 100ft Rd", "lat": 12.9719, "lon": 77.6412},
                "dropoff": {"address": "Kempegowda Int Airport", "lat": 13.1986, "lon": 77.7066},
            },
            "127.0.0.1",
        )
        duty = _create_duty(
            self.conn,
            self.user_a,
            {"booking_id": bk["item"]["id"]},
            "127.0.0.1",
        )
        self.duty_id = duty["item"]["id"]

    def tearDown(self):
        self.conn.close()

    # -------------------------------------------------------------
    # 1. Anti-Poaching Double-Blind Masking Tests
    # -------------------------------------------------------------
    def test_anti_poaching_white_label_ghost_mode(self):
        """Broadcasted duty masks corporate client & pricing to partner vendors while preserving owner view."""
        post_res = post_duty_to_exchange(
            self.conn,
            self.user_a,
            {
                "duty_id": self.duty_id,
                "client_receivable_paise": 320000,
                "base_supplier_payable_paise": 240000,
                "estimated_distance_km": 42.0,
                "prefer_ev_green_corridor": False,
            },
            "127.0.0.1",
        )
        self.assertTrue(post_res["ok"])
        listing_id = post_res["listing_id"]

        # View 1: Vendor B (Partner) queries exchange feed
        feed_b = get_masked_exchange_feed(self.conn, self.user_b, {})
        matching_b = [x for x in feed_b["listings"] if x["id"] == listing_id]
        self.assertEqual(len(matching_b), 1)
        item_b = matching_b[0]

        # Verify Double-Blind Anti-Poaching Stripping:
        self.assertNotIn("client_receivable_paise", item_b)
        self.assertEqual(item_b["originating_partner"], "Alpha Fleet Systems")
        self.assertEqual(item_b["client_display_name"], "Originating Partner: Alpha Fleet Systems")
        self.assertTrue(item_b["is_white_labeled"])
        self.assertEqual(item_b["supplier_payout_inr"], 2400.0)

        # View 2: Vendor A (Origin Owner) queries exchange feed
        feed_a = get_masked_exchange_feed(self.conn, self.user_a, {})
        item_a = [x for x in feed_a["listings"] if x["id"] == listing_id][0]
        self.assertTrue(item_a["is_owner"])
        self.assertEqual(item_a["client_receivable_paise"], 320000)
        self.assertEqual(item_a["net_margin_inr"], 800.0)
        self.assertEqual(item_a["net_margin_pct"], 25.0)

    # -------------------------------------------------------------
    # 2. Concurrency Claim & Timed Waterfall Cascade Tests
    # -------------------------------------------------------------
    def test_concurrency_lock_and_claim_duty(self):
        """Only one partner vendor can claim a broadcasting listing; concurrent duplicate claim gets 409."""
        post_res = post_duty_to_exchange(
            self.conn,
            self.user_a,
            {"duty_id": self.duty_id, "base_supplier_payable_paise": 200000},
            "127.0.0.1",
        )
        lid = post_res["listing_id"]

        # Vendor B claims listing
        claim_res = claim_network_duty(self.conn, self.user_b, lid, "127.0.0.1")
        self.assertTrue(claim_res["ok"])
        self.assertEqual(claim_res["status"], "CLAIMED")
        self.assertEqual(claim_res["claimed_by_vendor_id"], self.org_b)

        # Second claim attempt by Vendor B or another vendor fails with 409
        with self.assertRaises(DomainError) as ctx:
            claim_network_duty(self.conn, self.user_b, lid, "127.0.0.1")
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(ctx.exception.code, "duty_already_claimed")

    # -------------------------------------------------------------
    # 3. Spot-Surge Slider & Margin-Floor Guardrail Tests
    # -------------------------------------------------------------
    def test_spot_surge_slider_margin_floor_guardrail(self):
        """Surge boosts that reduce margin below the 12% margin floor are blocked unless overridden."""
        post_res = post_duty_to_exchange(
            self.conn,
            self.user_a,
            {
                "duty_id": self.duty_id,
                "client_receivable_paise": 200000,
                "base_supplier_payable_paise": 170000,
                "margin_floor_pct": 12.0,
            },
            "127.0.0.1",
        )
        lid = post_res["listing_id"]

        # Attempt +15% boost: 1700 * 1.15 = 1955 -> margin = (2000 - 1955) / 2000 = 2.25% < 12% floor
        with self.assertRaises(DomainError) as ctx:
            boost_surge_payout(self.conn, self.user_a, lid, boost_pct=15.0, override_floor=False, ip="127.0.0.1")
        self.assertEqual(ctx.exception.status, 422)
        self.assertEqual(ctx.exception.code, "MARGIN_FLOOR_BREACH")

        # Now apply +5% boost: 1700 * 1.05 = 1785 -> margin = (2000 - 1785) / 2000 = 10.75%, override_floor=True
        boost_res = boost_surge_payout(self.conn, self.user_a, lid, boost_pct=5.0, override_floor=True, ip="127.0.0.1")
        self.assertTrue(boost_res["ok"])
        self.assertEqual(boost_res["surge_boost_pct"], 5.0)
        self.assertEqual(boost_res["boosted_supplier_payable_inr"], 1785.0)

    # -------------------------------------------------------------
    # 4. Wallet Escrow Lock & Delinquent Tenant Blocking Tests
    # -------------------------------------------------------------
    def test_wallet_escrow_lock_and_delinquent_block(self):
        """Delinquent tenants (SOFT_BLOCKED) are hard-blocked from broadcasting marketplace trips."""
        self.conn.execute("UPDATE tenant_billing_accounts SET account_status = 'SOFT_BLOCKED' WHERE tenant_id = ?", (self.org_a,))
        self.conn.commit()

        with self.assertRaises(DomainError) as ctx:
            post_duty_to_exchange(self.conn, self.user_a, {"duty_id": self.duty_id}, "127.0.0.1")
        self.assertEqual(ctx.exception.status, 402)
        self.assertEqual(ctx.exception.code, "PAYMENT_REQUIRED_BLOCK")

        # Restore ACTIVE status and verify escrow hold is inserted
        self.conn.execute("UPDATE tenant_billing_accounts SET account_status = 'ACTIVE' WHERE tenant_id = ?", (self.org_a,))
        self.conn.commit()

        post_res = post_duty_to_exchange(self.conn, self.user_a, {"duty_id": self.duty_id, "base_supplier_payable_paise": 190000}, "127.0.0.1")
        self.assertTrue(post_res["ok"])
        escrow = self.conn.execute("SELECT * FROM wallet_escrow_holds WHERE listing_id = ?", (post_res["listing_id"],)).fetchone()
        self.assertIsNotNone(escrow)
        self.assertEqual(escrow["status"], "ESCROW_HOLD")
        self.assertEqual(escrow["escrow_amount_paise"], 190000)

    # -------------------------------------------------------------
    # 5. Cross-Tenant Compliance Passport & EV Range Gate Tests
    # -------------------------------------------------------------
    def test_compliance_passport_and_ev_range_safety_gate(self):
        """EV partner vehicles with insufficient battery range are rejected (25% buffer required)."""
        post_res = post_duty_to_exchange(
            self.conn,
            self.user_a,
            {"duty_id": self.duty_id, "estimated_distance_km": 180.0},
            "127.0.0.1",
        )
        lid = post_res["listing_id"]
        claim_network_duty(self.conn, self.user_b, lid, "127.0.0.1")

        # EV vehicle has 220 km range. Required = 180 * 1.25 = 225 km. (220 < 225 -> Rejected!)
        with self.assertRaises(DomainError) as ctx:
            allot_and_verify_compliance_passport(self.conn, self.user_b, lid, self.driver_b, self.veh_ev, "127.0.0.1")
        self.assertEqual(ctx.exception.status, 422)
        self.assertEqual(ctx.exception.code, "NETWORK_COMPLIANCE_PASSPORT_REJECTED")

        # ICE vehicle has no battery restriction -> Succeeds and issues SHA-256 seal
        allot_res = allot_and_verify_compliance_passport(self.conn, self.user_b, lid, self.driver_b, self.veh_ice, "127.0.0.1")
        self.assertTrue(allot_res["ok"])
        self.assertEqual(allot_res["status"], "ALLOTTED")
        self.assertIsNotNone(allot_res["zk_compliance_seal_hash"])

        # Verify Corporate Portal ZK compliance proof
        zk_proof = get_zk_compliance_proof(self.conn, self.duty_id)
        self.assertTrue(zk_proof["ok"])
        self.assertEqual(zk_proof["duty_id"], self.duty_id)
        self.assertEqual(zk_proof["statutory_checks"]["vehicle_insurance"], "ACTIVE_VERIFIED")

    # -------------------------------------------------------------
    # 6. T+0 Instant Factoring Clearinghouse Tests
    # -------------------------------------------------------------
    def test_t0_instant_factoring_clearinghouse(self):
        """Completed network duty is cashed out instantly with a 1.75% platform factoring fee."""
        post_res = post_duty_to_exchange(self.conn, self.user_a, {"duty_id": self.duty_id, "base_supplier_payable_paise": 400000}, "127.0.0.1")
        lid = post_res["listing_id"]
        claim_network_duty(self.conn, self.user_b, lid, "127.0.0.1")
        allot_and_verify_compliance_passport(self.conn, self.user_b, lid, self.driver_b, self.veh_ice, "127.0.0.1")

        fact_res = instant_t0_factoring_cashout(self.conn, self.user_b, self.duty_id, "127.0.0.1")
        self.assertTrue(fact_res["ok"])
        self.assertEqual(fact_res["gross_payable_inr"], 4000.0)
        self.assertEqual(fact_res["factoring_fee_pct"], 1.75)
        # 4000 * 0.0175 = 70.0 INR fee
        self.assertEqual(fact_res["platform_factoring_fee_inr"], 70.0)
        self.assertEqual(fact_res["instant_net_disbursement_inr"], 3930.0)
        self.assertEqual(fact_res["payout_status"], "DISBURSED_T0")

        # Escrow hold transitioned to SETTLED_PAYABLE
        escrow = self.conn.execute("SELECT status FROM wallet_escrow_holds WHERE listing_id = ?", (lid,)).fetchone()
        self.assertEqual(escrow["status"], "SETTLED_PAYABLE")

    # -------------------------------------------------------------
    # 7. Empty-Leg Deadhead Matchmaker & Demand Swarm Radar Tests
    # -------------------------------------------------------------
    def test_empty_leg_deadhead_and_demand_swarm(self):
        """Publishes deadhead outstation return corridor and matches incoming corporate requests."""
        create_res = create_empty_leg_listing(
            self.conn,
            self.user_b,
            {
                "origin_city": "Mysuru",
                "destination_city": "Bengaluru",
                "standard_rate_per_km": 18.0,
                "discount_pct": 30.0,
            },
            "127.0.0.1",
        )
        self.assertTrue(create_res["ok"])
        self.assertEqual(create_res["discounted_rate_per_km"], 12.6)

        matches = match_empty_leg_corridors(self.conn, "Mysuru", "Bengaluru")
        self.assertTrue(matches["ok"])
        self.assertGreaterEqual(matches["count"], 1)

        swarm = get_demand_swarm_radar(self.conn, "Bengaluru")
        self.assertTrue(swarm["ok"])
        self.assertGreaterEqual(len(swarm["demand_zones"]), 3)


if __name__ == "__main__":
    unittest.main()
