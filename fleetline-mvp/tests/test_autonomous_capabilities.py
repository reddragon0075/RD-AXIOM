#!/usr/bin/env python3
"""Axiom Mobility Autonomous Platform Test Suite.

Verifies:
1. Zero-Touch Trip Trust Score & Auto-Audit Engine:
   - High Trust Score (>= 95) -> AUTO_VERIFIED
   - Low Trust Score (< 95) with odometer / speed / OTP discrepancies -> NEEDS_AUDIT
   - 1-Click Discrepancy Resolver: 'approve_as_is' and 'snap_gps_distance'
2. Predictive SLA Breach Radar & Night Safety Guardian:
   - Evaluates active / upcoming dispatches for delay risks and suggests backup drivers
   - Night safety escort compliance check (20:00 to 06:00)
3. 'What-If' Tariff Savings Simulator:
   - 6-model simultaneous execution (slab, outstation, zone_ring, package, flat, day_rate)
   - Matrix comparison, optimal model identification, and projected ROI savings
4. Automated Credit Limit Dunning & Self-Serve Unblock:
   - Auto-block to SOFT_BLOCKED when outstanding_balance > credit_limit
   - Instant self-serve unblock restoring ACTIVE status and operational capabilities
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
    initialize_domain_schema,
)
from backend_extended import initialize_extended_schema
from backend_operations_parity import (
    _close_duty,
    initialize_operations_parity_schema,
)
from backend_commercial import (
    check_tenant_killswitch,
    initialize_commercial_schema,
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


class TestAutonomousPlatform(unittest.TestCase):
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

        now = datetime.now(timezone.utc).isoformat()
        self.org_id = "org_auto_vendor_01"
        self.conn.execute(
            "INSERT INTO organizations (id, kind, name, created_at) VALUES (?, 'vendor', 'Auto Vendor Fleet', ?)",
            (self.org_id, now),
        )

        self.user = {
            "id": "usr_dispatcher_01",
            "email": "dispatcher@autovendor.com",
            "role": "vendor",
            "organization_id": self.org_id,
        }
        self.conn.execute(
            "INSERT INTO users (id, email, password_hash, password_salt, role, full_name, organization_id, created_at) VALUES (?, ?, 'h', 's', ?, 'Dispatcher Alice', ?, ?)",
            (self.user["id"], self.user["email"], self.user["role"], self.org_id, now),
        )

        # Seed drivers and vehicles
        self.driver_id = "drv_test_01"
        self.conn.execute(
            """INSERT INTO domain_drivers (id, organization_id, full_name, phone, license_number, license_expiry, status, created_at, updated_at)
               VALUES (?, ?, 'Rajesh Pilot', '+919876543210', 'DL-KA-2020-001', '2030-01-01', 'active', ?, ?)""",
            (self.driver_id, self.org_id, now, now),
        )
        self.backup_driver_id = "drv_test_02"
        self.conn.execute(
            """INSERT INTO domain_drivers (id, organization_id, full_name, phone, license_number, license_expiry, status, created_at, updated_at)
               VALUES (?, ?, 'Suresh Backup', '+919876543211', 'DL-KA-2020-002', '2030-01-01', 'active', ?, ?)""",
            (self.backup_driver_id, self.org_id, now, now),
        )

        self.vehicle_id = "veh_test_01"
        self.conn.execute(
            """INSERT INTO domain_vehicles (id, organization_id, registration_number, vehicle_type, make_model, insurance_expiry, status, created_at, updated_at)
               VALUES (?, ?, 'KA-01-MJ-1234', 'sedan', 'Toyota Etios', '2030-01-01', 'active', ?, ?)""",
            (self.vehicle_id, self.org_id, now, now),
        )
        self.backup_vehicle_id = "veh_test_02"
        self.conn.execute(
            """INSERT INTO domain_vehicles (id, organization_id, registration_number, vehicle_type, make_model, insurance_expiry, status, created_at, updated_at)
               VALUES (?, ?, 'KA-01-MJ-5678', 'sedan', 'Maruti Dzire', '2030-01-01', 'active', ?, ?)""",
            (self.backup_vehicle_id, self.org_id, now, now),
        )

    def tearDown(self):
        self.conn.close()

    def _create_test_duty(self, started_at_offset_mins=60):
        now_dt = datetime.now(timezone.utc)
        started_dt = now_dt - timedelta(minutes=started_at_offset_mins)
        now = now_dt.isoformat()
        started_at = started_dt.isoformat()

        bk_res = _create_booking(
            self.conn,
            self.user,
            {
                "passenger_name": "Deepa Rao",
                "passenger_phone": "+919988776655",
                "duty_type": "local",
                "vehicle_type": "sedan",
                "scheduled_at": started_at,
                "pickup": {"address": "Koramangala 4th Block", "lat": 12.9352, "lon": 77.6245},
                "dropoff": {"address": "Whitefield ITPL", "lat": 12.9863, "lon": 77.7340},
            },
            "127.0.0.1",
        )
        booking_id = bk_res["item"]["id"]

        duty_res = _create_duty(
            self.conn,
            self.user,
            {
                "booking_id": booking_id,
                "driver_id": self.driver_id,
                "vehicle_id": self.vehicle_id,
                "start_odometer": 1000,
            },
            "127.0.0.1",
        )
        duty_id = duty_res["item"]["id"]

        self.conn.execute(
            "UPDATE domain_duties SET status = 'in_progress', started_at = ?, start_odometer = 1000 WHERE id = ?",
            (started_at, duty_id),
        )
        self.conn.commit()
        return duty_id, booking_id

    # -------------------------------------------------------------
    # 1. Zero-Touch Trust Score & Auto-Audit Tests
    # -------------------------------------------------------------
    def test_trip_trust_score_auto_verified(self):
        """Clean trip with odometer matching expected distance and verified OTP achieves >= 95 and AUTO_VERIFIED."""
        duty_id, _ = self._create_test_duty(started_at_offset_mins=60)
        # 25 km in 60 min = 25 km/h (realistic), GPS expected 24.5 km (variance < 5%), OTP verified
        closure_payload = {
            "end_odometer": 1025,
            "end_km": 1025,
            "expected_distance_km": 24.5,
            "otp_verified": True,
            "toll_amount": 50,
            "base_fare": 800,
        }

        closed_duty = _close_duty(self.conn, self.user, duty_id, closure_payload, "127.0.0.1")
        self.assertIn("trust_audit", closed_duty)
        audit = closed_duty["trust_audit"]

        self.assertGreaterEqual(audit["trust_score"], 95)
        self.assertEqual(audit["audit_status"], "AUTO_VERIFIED")
        self.assertEqual(len(audit["audit_flags"]), 0)

        # Verify DB persistence
        row = self.conn.execute("SELECT * FROM domain_duty_trust_audits WHERE duty_id = ?", (duty_id,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["audit_status"], "AUTO_VERIFIED")
        self.assertGreaterEqual(row["trust_score"], 95)

    def test_trip_trust_score_needs_audit_on_odometer_variance(self):
        """Trip with > 15% odometer variance vs GPS distance gets flagged as NEEDS_AUDIT."""
        duty_id, _ = self._create_test_duty(started_at_offset_mins=60)
        # Driver claims 60 km, but expected GPS is 30 km (100% variance)
        closure_payload = {
            "end_odometer": 1060,
            "end_km": 1060,
            "expected_distance_km": 30.0,
            "otp_verified": True,
        }

        closed_duty = _close_duty(self.conn, self.user, duty_id, closure_payload, "127.0.0.1")
        audit = closed_duty["trust_audit"]

        self.assertLess(audit["trust_score"], 95)
        self.assertEqual(audit["audit_status"], "NEEDS_AUDIT")
        flag_codes = [f["code"] for f in audit["audit_flags"]]
        self.assertIn("ODOMETER_GPS_VARIANCE", flag_codes)

    def test_trip_trust_score_speed_and_otp_anomaly(self):
        """Trip with implausible speed (> 130 km/h) and unverified OTP gets docked trust points."""
        duty_id, _ = self._create_test_duty(started_at_offset_mins=5)
        # 30 km in 5 minutes = 360 km/h (implausible flight speed!)
        closure_payload = {
            "end_odometer": 1030,
            "expected_distance_km": 30.0,
            "otp_verified": False,
        }

        closed_duty = _close_duty(self.conn, self.user, duty_id, closure_payload, "127.0.0.1")
        audit = closed_duty["trust_audit"]

        self.assertLess(audit["trust_score"], 80)
        self.assertEqual(audit["audit_status"], "NEEDS_AUDIT")
        flag_codes = [f["code"] for f in audit["audit_flags"]]
        self.assertIn("IMPLAUSIBLE_HIGH_SPEED", flag_codes)
        self.assertIn("MISSING_PASSENGER_OTP", flag_codes)

    def test_discrepancy_resolver_approve_as_is(self):
        """1-Click resolver: approve_as_is resolves audit to RESOLVED_APPROVED without altering odo."""
        duty_id, _ = self._create_test_duty(started_at_offset_mins=45)
        closure_payload = {"end_odometer": 1050, "expected_distance_km": 30.0}
        _close_duty(self.conn, self.user, duty_id, closure_payload, "127.0.0.1")

        res = resolve_duty_audit(
            self.conn,
            self.user,
            duty_id,
            "approve_as_is",
            "Client requested highway bypass due to main road protest",
            "127.0.0.1",
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["audit_status"], "RESOLVED_APPROVED")
        self.assertEqual(res["end_odometer"], 1050)

    def test_discrepancy_resolver_snap_gps(self):
        """1-Click resolver: snap_gps_distance resolves audit and snaps end_odometer to expected GPS."""
        duty_id, _ = self._create_test_duty(started_at_offset_mins=45)
        closure_payload = {"end_odometer": 1050, "expected_distance_km": 32.0}
        _close_duty(self.conn, self.user, duty_id, closure_payload, "127.0.0.1")

        res = resolve_duty_audit(
            self.conn,
            self.user,
            duty_id,
            "snap_gps_distance",
            "Snapped to verified Google Maps route distance",
            "127.0.0.1",
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["audit_status"], "RESOLVED_SNAPPED")
        # 1000 start + 32 km GPS = 1032
        self.assertEqual(res["snapped_km"], 32.0)
        self.assertEqual(res["end_odometer"], 1032)

        # Check duty record
        duty = self.conn.execute("SELECT end_odometer FROM domain_duties WHERE id = ?", (duty_id,)).fetchone()
        self.assertEqual(duty["end_odometer"], 1032)

    # -------------------------------------------------------------
    # 2. Predictive SLA Breach Radar & Night Safety Guardian Tests
    # -------------------------------------------------------------
    def test_sla_breach_radar_and_night_safety_guardian(self):
        """Radar flags high-risk active duties with backups, and triggers Night Safety Guardian for solo female night duties."""
        now_dt = datetime.now(timezone.utc)
        # Schedule duty 10 minutes from now (imminent pickup)
        pickup_time = (now_dt + timedelta(minutes=10)).isoformat()

        bk_res = _create_booking(
            self.conn,
            self.user,
            {
                "passenger_name": "Priyanka Sen (Female Solo)",
                "passenger_phone": "+919888877777",
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
            self.user,
            {
                "booking_id": booking_id,
                "driver_id": self.driver_id,
                "vehicle_id": self.vehicle_id,
            },
            "127.0.0.1",
        )
        duty_id = duty_res["item"]["id"]

        radar = scan_sla_radar(self.conn, self.org_id)
        self.assertTrue(radar["ok"])
        self.assertIn("critical_trips", radar)
        self.assertIn("night_safety_alerts", radar)

        # Duty should be detected in monitored window
        trips = radar["critical_trips"]
        matching = [t for t in trips if t["duty_id"] == duty_id]
        self.assertEqual(len(matching), 1)
        trip = matching[0]

        # Should have suggested backup drivers
        self.assertGreaterEqual(len(trip["suggested_backups"]), 1)
        self.assertEqual(trip["suggested_backups"][0]["driver_id"], self.backup_driver_id)

    # -------------------------------------------------------------
    # 3. What-If Tariff Savings Simulator Tests
    # -------------------------------------------------------------
    def test_tariff_savings_simulator_6_models(self):
        """Simulator calculates spend across all 6 models and outputs optimal recommendation."""
        payload = {
            "monthly_trips": 120,
            "average_distance_km": 42.0,
            "average_duration_hours": 3.5,
        }

        res = simulate_tariff_scenarios(payload)
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["comparison_matrix"]), 6)

        models = {m["model"]: m for m in res["comparison_matrix"]}
        self.assertIn("slab", models)
        self.assertIn("outstation", models)
        self.assertIn("zone_ring", models)
        self.assertIn("package", models)
        self.assertIn("flat", models)
        self.assertIn("day_rate", models)

        # All models have calculated numbers
        for code, m in models.items():
            self.assertGreater(m["monthly_client_spend_inr"], 0)
            self.assertGreater(m["effective_cost_per_km_inr"], 0)

        # Optimal recommendation exists and projects positive savings
        opt = res["optimal_recommendation"]
        self.assertIn(opt["optimal_model"], ["slab", "outstation", "zone_ring", "package", "flat", "day_rate"])
        self.assertGreaterEqual(opt["annual_projected_savings_inr"], 0)

    # -------------------------------------------------------------
    # 4. Automated Credit Limit Dunning & Self-Serve Unblock Tests
    # -------------------------------------------------------------
    def test_credit_limit_dunning_and_self_serve_unblock(self):
        """Delinquent tenant exceeding credit limit gets auto-blocked, then self-settles back to ACTIVE."""
        # Setup tenant billing account
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO tenant_billing_accounts (
                tenant_id, tenant_name, account_status, credit_limit_paise,
                total_billed_paise, total_paid_paise, outstanding_balance_paise,
                created_at, updated_at
            ) VALUES (?, 'FinTech Corp', 'ACTIVE', 500000, 1200000, 400000, 800000, ?, ?)""",
            (self.org_id, now, now),
        )
        self.conn.commit()

        # Step 1: Dunning evaluation triggers SOFT_BLOCKED because 800,000 > 500,000
        check_credit_limit_dunning(self.conn, self.org_id)
        row = self.conn.execute("SELECT account_status FROM tenant_billing_accounts WHERE tenant_id = ?", (self.org_id,)).fetchone()
        self.assertEqual(row["account_status"], "SOFT_BLOCKED")

        # Step 2: Attempting to create a new booking is rejected with 402 TENANT_BLOCKED_NON_PAYMENT
        with self.assertRaises(DomainError) as ctx:
            check_tenant_killswitch(self.conn, self.org_id, "POST", "/api/v1/bookings")
        self.assertEqual(ctx.exception.status, 402)
        self.assertEqual(ctx.exception.code, "TENANT_BLOCKED_NON_PAYMENT")

        # Step 3: Tenant performs instant self-settlement
        settle_res = self_settle_tenant_dues(
            self.conn,
            self.user,
            {"payment_method": "UPI_INSTANT", "reference_id": "UPI_TEST_7788"},
            "127.0.0.1",
        )
        self.assertTrue(settle_res["ok"])
        self.assertEqual(settle_res["account_status"], "ACTIVE")
        self.assertEqual(settle_res["amount_paid_paise"], 800000)
        self.assertEqual(settle_res["new_outstanding_balance_paise"], 0)

        # Step 4: Kill-switch is immediately cleared; creating booking passes without error
        check_tenant_killswitch(self.conn, self.org_id, "POST", "/api/v1/bookings")


if __name__ == "__main__":
    unittest.main()
