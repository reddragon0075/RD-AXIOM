"""Axiom Mobility - Vendor Mobile Pocket App, Theoretical-to-Practical Pricing Engine
& Physical Trip-Sheet Override Verification Suite.

Executes tests covering:
1. Mobile Pocket Assignment: Fetching unassigned bookings in the compact mobile payload
   and assigning a cab + driver in one atomic API call.
2. Theoretical vs. Practical Recalculation: Creating a booking estimated at 40 km (₹1,500),
   closing it with practical values of 74 km, asserting the final bill updates to the
   practical rate (₹2,350) while preserving the ₹1,500 theoretical baseline for reporting.
3. Physical Trip-Sheet Enforcement: Attempting to override a discrepant trip without
   physical_tripsheet_file_url (asserting 422 rejection), then uploading a trip-sheet URL
   and asserting successful trip closure and Dual-Ledger update.
"""

import datetime as dt
from pathlib import Path
import sqlite3
import sys
import unittest
import uuid

# Add root and fleetline-mvp to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
MVP_PATH = ROOT / "fleetline-mvp"
if str(MVP_PATH) not in sys.path:
    sys.path.insert(0, str(MVP_PATH))

from backend_domain import DomainError, initialize_domain_schema
from backend_treasury_release import initialize_treasury_release_schema
from backend.practical_pricing_service import (
    initialize_practical_pricing_schema,
    compute_theoretical_pricing,
    recalculate_practical_tariffs,
    close_duty_practical,
    get_vendor_pocket_pulse,
    get_vendor_pocket_unassigned,
    express_assign_cab,
    handle_practical_pricing_api,
)


class TestPocketAndTripSheetOverride(unittest.TestCase):
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
        initialize_treasury_release_schema(self.conn)
        initialize_practical_pricing_schema(self.conn)

        self.vendor_org = "org_vendor_apex"
        self.vendor_user = {
            "id": "usr_vendor_dispatcher",
            "email": "dispatcher@apexfleet.in",
            "role": "vendor",
            "organization_id": self.vendor_org,
        }
        self.operator_user = {
            "id": "usr_operator_01",
            "email": "ops@apexfleet.in",
            "role": "operator",
            "organization_id": self.vendor_org,
        }

        # Seed sample driver & vehicle for express assignment
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT INTO domain_drivers (id, organization_id, full_name, phone, license_number, license_expiry, status, created_at, updated_at)
            VALUES ('drv_test_01', ?, 'Ramesh Kumar', '+91 98765 43210', 'KA-01-2022-998', '2028-12-31', 'available', ?, ?)
            """,
            (self.vendor_org, now, now),
        )
        self.conn.execute(
            """
            INSERT INTO domain_vehicles (id, organization_id, registration_number, model, vehicle_type, insurance_expiry, status, created_at, updated_at)
            VALUES ('veh_test_01', ?, 'KA-01-MJ-4412', 'Maruti Dzire Tour', 'Sedan', '2028-12-31', 'available', ?, ?)
            """,
            (self.vendor_org, now, now),
        )

    def test_01_mobile_pocket_pulse_and_express_assignment(self):
        """1. Mobile Pocket Assignment: Fetching unassigned bookings & assigning cab in 1 call."""
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        b_id = "bk_test_pocket_01"

        # Create unassigned booking
        self.conn.execute(
            """
            INSERT INTO domain_bookings (
                id, organization_id, booking_reference, status, passenger_name, passenger_phone,
                pickup_json, dropoff_json, scheduled_at, vehicle_category,
                estimated_distance_km, estimated_client_fare_inr, estimated_supplier_payout_inr,
                created_at, updated_at
            ) VALUES (?, ?, 'BK-BLR-001', 'requested', 'Vikram Malhotra', '+91 98800 23456',
                      '{\"label\": \"Bangalore Airport T2\"}', '{\"label\": \"Whitefield Tech Park\"}',
                      ?, 'Sedan', 40.0, 1500.0, 1200.0, ?, ?)
            """,
            (b_id, self.vendor_org, now, now, now),
        )

        # A. Fetch pulse stats
        pulse_res = get_vendor_pocket_pulse(self.conn, self.vendor_user)
        self.assertTrue(pulse_res["ok"])
        self.assertGreaterEqual(pulse_res["pulse"]["unassigned_cabs"], 1)

        # B. Fetch unassigned list for mobile cards
        unassigned_res = get_vendor_pocket_unassigned(self.conn, self.vendor_user)
        self.assertTrue(unassigned_res["ok"])
        self.assertGreaterEqual(len(unassigned_res["unassigned_bookings"]), 1)
        found_bk = next((b for b in unassigned_res["unassigned_bookings"] if b["id"] == b_id), None)
        self.assertIsNotNone(found_bk)
        self.assertEqual(found_bk["vehicle_category"], "Sedan")
        self.assertEqual(found_bk["estimated_client_fare_inr"], 1500.0)

        # Verify suggested compliant pairs
        self.assertGreaterEqual(len(unassigned_res["suggested_pairs"]), 1)
        self.assertEqual(unassigned_res["suggested_pairs"][0]["compliance_badge"], "✅ Docs Valid")

        # C. Express Assign Cab in one atomic API call
        assign_payload = {
            "booking_id": b_id,
            "driver_id": "drv_test_01",
            "vehicle_id": "veh_test_01",
        }
        assign_res = express_assign_cab(self.conn, self.vendor_user, assign_payload)
        self.assertTrue(assign_res["ok"])
        self.assertEqual(assign_res["status"], "ALLOTTED")
        self.assertIn("dispatch_alert", assign_res)
        self.assertEqual(assign_res["dispatch_alert"]["status"], "DISPATCH_CONFIRMED")
        self.assertIn("KA-01-MJ-4412", assign_res["dispatch_alert"]["passenger_sms_text"])

        # Verify database state
        duty_row = self.conn.execute("SELECT * FROM domain_duties WHERE booking_id = ?", (b_id,)).fetchone()
        self.assertIsNotNone(duty_row)
        self.assertEqual(duty_row["status"], "ALLOTTED")
        self.assertEqual(duty_row["driver_id"], "drv_test_01")
        self.assertEqual(duty_row["vehicle_id"], "veh_test_01")

        print("PASS: Mobile Pocket Assignment and Express Allotment verified successfully.")

    def test_02_theoretical_vs_practical_recalculation(self):
        """2. Theoretical vs. Practical Recalculation: 40km (₹1500) -> 74km (₹2350)."""
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        duty_id = "duty_recalc_test_02"
        b_id = "bk_recalc_02"

        # Baseline theoretical values
        theo = compute_theoretical_pricing(distance_km=40.0, duration_mins=240, start_km=1000.0, base_rate_inr=1500.0)
        self.assertEqual(theo["estimated_distance_km"], 40.0)
        self.assertEqual(theo["estimated_client_fare_inr"], 1500.0)
        self.assertEqual(theo["estimated_supplier_payout_inr"], 1200.0)

        self.conn.execute(
            """
            INSERT INTO domain_duties (
                id, organization_id, booking_id, status, reporting_at,
                estimated_start_km, estimated_end_km, estimated_distance_km, estimated_duration_mins,
                estimated_client_fare_inr, estimated_supplier_payout_inr,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'ALLOTTED', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                duty_id, self.vendor_org, b_id, now,
                theo["estimated_start_km"], theo["estimated_end_km"],
                theo["estimated_distance_km"], theo["estimated_duration_mins"],
                theo["estimated_client_fare_inr"], theo["estimated_supplier_payout_inr"],
                now, now,
            ),
        )

        # Close trip with practical road execution:
        # Start Km: 1000.0, End Km: 1074.0 (Practical Billable = 74.0 km)
        close_payload = {
            "practical_start_km": 1000.0,
            "practical_end_km": 1074.0,
            "practical_start_time": "2026-11-03T09:00:00Z",
            "practical_end_time": "2026-11-03T13:00:00Z",
            "toll_parking_inr": 0.0,
            "closing_source": "OPERATOR_PRACTICAL_ENTRY",
        }

        closure_res = close_duty_practical(self.conn, self.operator_user, duty_id, close_payload)
        self.assertTrue(closure_res["ok"])

        # Assert final practical bill updates to ₹2,350 (Base ₹1500 + 34 km * ₹25)
        self.assertEqual(closure_res["practical_final"]["practical_billable_km"], 74.0)
        self.assertEqual(closure_res["practical_final"]["final_client_fare_inr"], 2350.0)
        self.assertEqual(closure_res["practical_final"]["variance_delta_inr"], 850.0)

        # Assert baseline ₹1,500 is strictly preserved for invoice annexure reporting
        self.assertEqual(closure_res["estimated_baseline"]["estimated_distance_km"], 40.0)
        self.assertEqual(closure_res["estimated_baseline"]["estimated_client_fare_inr"], 1500.0)

        # Assert DB record state
        d_row = self.conn.execute("SELECT * FROM domain_duties WHERE id = ?", (duty_id,)).fetchone()
        self.assertEqual(d_row["status"], "completed")
        self.assertEqual(d_row["estimated_client_fare_inr"], 1500.0)
        self.assertEqual(d_row["final_client_fare_inr"], 2350.0)
        self.assertEqual(d_row["practical_billable_km"], 74.0)

        print("PASS: Theoretical Baseline vs. Practical Final Recalculation verified successfully.")

    def test_03_physical_tripsheet_proof_enforcement(self):
        """3. Physical Trip-Sheet Enforcement: 422 rejection when missing proof, success on upload."""
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        duty_id = "duty_disc_enforce_03"
        b_id = "bk_disc_03"

        self.conn.execute(
            """
            INSERT INTO domain_duties (
                id, organization_id, booking_id, status, reporting_at,
                estimated_start_km, estimated_end_km, estimated_distance_km, estimated_duration_mins,
                estimated_client_fare_inr, estimated_supplier_payout_inr,
                app_captured_start_km, app_captured_end_km, app_gps_distance_km,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'ALLOTTED', ?, 1000.0, 1040.0, 40.0, 240, 1500.0, 1200.0, 1000.0, 1022.0, 20.5, ?, ?)
            """,
            (duty_id, self.vendor_org, b_id, now, now, now),
        )

        # Step 3A: Attempt override with discrepancy/override but MISSING trip-sheet photo
        discrepant_payload_no_proof = {
            "practical_start_km": 1000.0,
            "practical_end_km": 1074.0,
            "closing_source": "PHYSICAL_TRIPSHEET_OVERRIDE",
            "has_discrepancy": True,
            "discrepancy_reason": "GPS_DROP_IN_BASEMENT",
            "physical_tripsheet_file_url": None,  # Missing mandatory proof!
        }

        with self.assertRaises(DomainError) as ctx:
            close_duty_practical(self.conn, self.operator_user, duty_id, discrepant_payload_no_proof)

        self.assertEqual(ctx.exception.status, 422)
        self.assertIn("PHYSICAL_TRIPSHEET_PROOF_REQUIRED", str(ctx.exception))
        print("PASS: Mandatory proof gate successfully rejected override without paper trip-sheet (HTTP 422).")

        # Step 3B: Upload signed paper trip-sheet URL and close
        valid_tripsheet_url = "https://supabase.axiomfleet.in/storage/v1/object/public/trip-sheets/signed_duty_slip_74km.jpg"
        valid_payload = {
            "practical_start_km": 1000.0,
            "practical_end_km": 1074.0,
            "closing_source": "PHYSICAL_TRIPSHEET_OVERRIDE",
            "has_discrepancy": True,
            "discrepancy_reason": "GPS_DROP_IN_BASEMENT",
            "physical_tripsheet_file_url": valid_tripsheet_url,
            "toll_parking_inr": 150.0,
        }

        closure_res = close_duty_practical(self.conn, self.operator_user, duty_id, valid_payload)
        self.assertTrue(closure_res["ok"])
        self.assertEqual(closure_res["duty"]["status"], "completed")
        self.assertEqual(closure_res["duty"]["physical_tripsheet_file_url"], valid_tripsheet_url)
        self.assertEqual(closure_res["duty"]["closing_source"], "PHYSICAL_TRIPSHEET_OVERRIDE")
        self.assertEqual(closure_res["duty"]["has_discrepancy"], 1)

        # Verify audit log entry
        audit_log = self.conn.execute("SELECT * FROM duty_tripsheet_audit_logs WHERE duty_id = ?", (duty_id,)).fetchone()
        self.assertIsNotNone(audit_log)
        self.assertEqual(audit_log["closing_source"], "PHYSICAL_TRIPSHEET_OVERRIDE")
        self.assertEqual(audit_log["physical_tripsheet_file_url"], valid_tripsheet_url)

        # Verify Dual-Ledger synchronization in supplier_payable_ledger
        spl_row = self.conn.execute("SELECT * FROM supplier_payable_ledger WHERE duty_id = ?", (duty_id,)).fetchone()
        self.assertIsNotNone(spl_row)
        self.assertEqual(spl_row["status"], "FUNDS_HELD_BY_AXIOM")
        self.assertGreater(spl_row["amount_paise"], 0)

        print("PASS: Discrepant duty successfully reconciled and closed with paper trip-sheet proof & Dual-Ledger sync.")


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestPocketAndTripSheetOverride)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
