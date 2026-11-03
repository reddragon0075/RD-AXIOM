"""Automated E2E Verification Suite for Axiom Mobility (Fleetline):
1. Sequential Vehicle Odometer Continuity Auditor (Rollbacks & Unaccounted Dead-Mileage Gaps).
2. Smart Partial Batch Commit & Error-Row CSV Exporter (21 columns with UTF-8 BOM).
3. Multi-Row Bulk Correction & Tariff Re-evaluation (Atomic updates & Dual-Ledger sync).
4. Post-Invoice Credit / Supplementary Debit Note Generator (GST audit compliance).
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
from pathlib import Path
import sqlite3
import sys
import unittest
import uuid

# Set up module paths
ROOT = Path(__file__).resolve().parent.parent
FLEETLINE_DIR = ROOT / "fleetline-mvp"
if str(FLEETLINE_DIR) not in sys.path:
    sys.path.insert(0, str(FLEETLINE_DIR))

from backend_domain import now_iso, new_id, initialize_domain_schema
from backend_practical_pricing import initialize_practical_pricing_schema
from backend_completed_trips_importer import (
    initialize_bulk_importer_schema,
    stage_completed_trips,
    commit_completed_trips_batch,
    update_staged_trip_row,
    correct_duty_trip_details,
    handle_completed_trips_api,
)
from backend_odometer_and_adjustment import (
    initialize_odometer_and_adjustment_schema,
    audit_vehicle_odometer_continuity,
    export_batch_errors_csv,
    bulk_correct_duties,
    create_post_invoice_adjustment,
    handle_odometer_and_adjustment_api,
)


class TestOdometerContinuityAndAdjustments(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = OFF")
        self.tenant_id = "org_axiom_corp"
        self.operator_user = {
            "id": "usr_operator_1",
            "email": "ops@axiommprocab.com",
            "full_name": "Senior Fleet Controller",
            "organization_id": self.tenant_id,
            "roles": ["operator", "fleet_manager", "finance_controller"],
        }

        # Initialize base schema
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'operator',
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
            CREATE TABLE IF NOT EXISTS supplier_payable_ledger (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                duty_id TEXT NOT NULL,
                amount_paise INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        initialize_domain_schema(self.conn)
        initialize_practical_pricing_schema(self.conn)
        initialize_bulk_importer_schema(self.conn)
        initialize_odometer_and_adjustment_schema(self.conn)

        # Seed Masters
        now = now_iso()
        self.conn.executescript(
            f"""
            INSERT INTO domain_customers (id, organization_id, name, created_at, updated_at) VALUES
                ('cust_infosys', '{self.tenant_id}', 'Infosys BPM Limited', '{now}', '{now}'),
                ('cust_wipro', '{self.tenant_id}', 'Wipro Technologies', '{now}', '{now}');

            INSERT INTO domain_vehicles (id, organization_id, registration_number, model, vehicle_type, status, created_at, updated_at) VALUES
                ('veh_01', '{self.tenant_id}', 'KA01AB1234', 'Dzire', 'Sedan', 'available', '{now}', '{now}'),
                ('veh_02', '{self.tenant_id}', 'KA04MJ9999', 'Innova Crysta', 'SUV', 'available', '{now}', '{now}');

            INSERT INTO domain_drivers (id, organization_id, full_name, phone, status, created_at, updated_at) VALUES
                ('drv_01', '{self.tenant_id}', 'Ramesh Kumar', '+91 98801 23456', 'active', '{now}', '{now}'),
                ('drv_02', '{self.tenant_id}', 'Suresh Patil', '+91 98801 77777', 'active', '{now}', '{now}');
            """
        )

    def tearDown(self):
        self.conn.close()

    def test_01_odometer_continuity_detection_rollback_and_dead_mileage(self):
        """1. Verify Odometer Continuity: detects rollbacks and >50km dead-mileage gaps."""
        # Setup: Duty #1 for KA01AB1234 ending at 10,500 km at 10:00 AM
        now = now_iso()
        duty_1_id = "duty_existing_01"
        self.conn.execute(
            """
            INSERT INTO domain_duties (
                id, organization_id, booking_id, vehicle_id, driver_id, status,
                practical_start_km, practical_end_km, practical_billable_km,
                practical_start_time, practical_end_time, final_client_fare_inr,
                final_supplier_payout_inr, created_at, updated_at
            ) VALUES (?, ?, 'bk_01', 'veh_01', 'drv_01', 'completed', 10450.0, 10500.0, 50.0, '2026-11-03T08:00:00Z', '2026-11-03T10:00:00Z', 1800.0, 1400.0, ?, ?)
            """,
            (duty_1_id, self.tenant_id, now, now),
        )

        # Audit a trip starting at 10,400 km (100 km LESS than prev trip End KM 10,500) -> ROLLBACK_ERROR
        chk_rollback = audit_vehicle_odometer_continuity(
            self.conn, self.tenant_id, "veh_01", 10400.0, "2026-11-03T12:00:00Z"
        )
        self.assertEqual(chk_rollback["odometer_continuity_status"], "ROLLBACK_ERROR")
        self.assertEqual(chk_rollback["prev_duty_id"], duty_1_id)
        self.assertEqual(chk_rollback["prev_duty_end_km"], 10500.0)
        self.assertEqual(chk_rollback["dead_mileage_gap_km"], -100.0)
        self.assertIn("previous trip End KM", chk_rollback["message"])
        self.assertIn("lower than", chk_rollback["message"])

        # Audit a trip starting at 10,650 km (150 km GREATER than prev trip End KM 10,500) -> HIGH_DEAD_MILEAGE_GAP (>50 km)
        chk_gap = audit_vehicle_odometer_continuity(
            self.conn, self.tenant_id, "veh_01", 10650.0, "2026-11-03T14:00:00Z"
        )
        self.assertEqual(chk_gap["odometer_continuity_status"], "HIGH_DEAD_MILEAGE_GAP")
        self.assertEqual(chk_gap["prev_duty_id"], duty_1_id)
        self.assertEqual(chk_gap["prev_duty_end_km"], 10500.0)
        self.assertEqual(chk_gap["dead_mileage_gap_km"], 150.0)
        self.assertIn("150 km unaccounted gap", chk_gap["message"])

        # Audit a continuous trip starting at 10,508 km (8 km gap <= 50 km) -> CONTINUOUS_OK
        chk_ok = audit_vehicle_odometer_continuity(
            self.conn, self.tenant_id, "veh_01", 10508.0, "2026-11-03T16:00:00Z"
        )
        self.assertEqual(chk_ok["odometer_continuity_status"], "CONTINUOUS_OK")
        self.assertEqual(chk_ok["prev_duty_end_km"], 10500.0)
        self.assertEqual(chk_ok["dead_mileage_gap_km"], 8.0)
        self.assertIn("Continuous", chk_ok["message"])

    def test_02_staging_row_and_duty_correction_with_continuity_audit(self):
        """2. Verify staging rows & post-commit duties update continuity live upon correction."""
        # Setup: Pre-existing trip
        now = now_iso()
        self.conn.execute(
            """
            INSERT INTO domain_duties (
                id, organization_id, booking_id, vehicle_id, driver_id, status,
                practical_start_km, practical_end_km, practical_billable_km,
                practical_start_time, practical_end_time, final_client_fare_inr,
                final_supplier_payout_inr, created_at, updated_at
            ) VALUES ('duty_prior', ?, 'bk_prior', 'veh_01', 'drv_01', 'completed', 5000.0, 5100.0, 100.0, '2026-11-02T10:00:00Z', '2026-11-02T12:00:00Z', 2500.0, 2000.0, ?, ?)
            """,
            (self.tenant_id, now, now),
        )

        # Stage CSV with a rollback row (start_km 4900 < 5100)
        csv_data = (
            "external_tripsheet_no,trip_date,corporate_name,passenger_name,passenger_phone,pickup_location,drop_location,duty_type,vehicle_category,vehicle_registration,driver_name,driver_phone,start_time,end_time,practical_start_km,practical_end_km,toll_parking_inr,client_final_price_inr,supplier_final_payout_inr,remarks\n"
            "TS-AUDIT-01,2026-11-02,Infosys BPM Limited,A. Sharma,+91 98800 11111,Electronic City,Airport,AIRPORT,Sedan,KA01AB1234,Ramesh Kumar,+91 98801 23456,14:00,16:00,4900,4950,150,1800,1400,Rollback test\n"
        )
        staged = stage_completed_trips(self.conn, self.operator_user, csv_data, "audit_test.csv")
        self.assertEqual(staged["summary"]["error_rows"], 1)
        row_id = staged["staged_rows"][0]["id"]
        self.assertEqual(staged["staged_rows"][0]["odometer_continuity_status"], "ROLLBACK_ERROR")

        # Edit row to fix the start KM from 4900 to 5105 (continuous +5 km)
        updated = update_staged_trip_row(
            self.conn,
            self.operator_user,
            row_id,
            {
                "practical_start_km": 5105,
                "practical_end_km": 5165,
                "override_tariff_lock": True,
            },
        )
        self.assertEqual(updated["row"]["validation_status"], "VALID")
        self.assertEqual(updated["row"]["odometer_continuity_status"], "CONTINUOUS_OK")
        self.assertEqual(updated["row"]["dead_mileage_gap_km"], 5.0)

    def test_03_partial_batch_commit_and_error_csv_export(self):
        """3. Verify Partial Commit of valid rows and Error CSV Export with 21 columns."""
        # Stage 5 rows: 4 valid, 1 error (unregistered vehicle)
        csv_data = (
            "external_tripsheet_no,trip_date,corporate_name,passenger_name,passenger_phone,pickup_location,drop_location,duty_type,vehicle_category,vehicle_registration,driver_name,driver_phone,start_time,end_time,practical_start_km,practical_end_km,toll_parking_inr,client_final_price_inr,supplier_final_payout_inr,remarks\n"
            "TS-P01,2026-11-03,Infosys BPM Limited,P1,+91 98800 11111,Koramangala,Indiranagar,LOCAL,Sedan,KA01AB1234,Ramesh Kumar,+91 98801 23456,08:00,10:00,1000,1030,0,1500,1200,Valid Row 1\n"
            "TS-P02,2026-11-03,Infosys BPM Limited,P2,+91 98800 11112,Indiranagar,Whitefield,LOCAL,Sedan,KA01AB1234,Ramesh Kumar,+91 98801 23456,11:00,12:00,1030,1060,0,1500,1200,Valid Row 2\n"
            "TS-P03,2026-11-03,Infosys BPM Limited,P3,+91 98800 11113,Whitefield,Airport,LOCAL,Sedan,KA01AB1234,Ramesh Kumar,+91 98801 23456,13:00,15:00,1060,1100,100,1600,1280,Valid Row 3\n"
            "TS-P04,2026-11-03,Infosys BPM Limited,P4,+91 98800 11114,Airport,Hebbal,LOCAL,Sedan,KA01AB1234,Ramesh Kumar,+91 98801 23456,16:00,17:00,1100,1130,0,1500,1200,Valid Row 4\n"
            "TS-P05,2026-11-03,Infosys BPM Limited,P5,+91 98800 11115,Hebbal,Majestic,LOCAL,Sedan,KA99ZZ0000,Ramesh Kumar,+91 98801 23456,18:00,19:00,1130,1150,0,1500,1200,Invalid Vehicle\n"
        )
        staged = stage_completed_trips(self.conn, self.operator_user, csv_data, "partial_batch.csv")
        batch_id = staged["batch_id"]
        self.assertEqual(staged["summary"]["valid_rows"], 4)
        self.assertEqual(staged["summary"]["error_rows"], 1)

        # 1. Export Error Rows via export_batch_errors_csv
        export_res = export_batch_errors_csv(self.conn, self.operator_user, batch_id)
        self.assertTrue(export_res["ok"])
        self.assertEqual(export_res["error_rows_count"], 1)
        self.assertEqual(export_res["format"], "csv")
        self.assertTrue(export_res["csv_text"].startswith("\ufeff"))

        # Parse exported CSV to verify 21 columns and the 21st header
        csv_reader = list(csv.reader(io.StringIO(export_res["csv_text"].lstrip("\ufeff"))))
        self.assertEqual(len(csv_reader), 2)  # Header + 1 error row
        header = csv_reader[0]
        self.assertEqual(len(header), 21)
        self.assertEqual(header[20], "axiom_error_explanation")
        error_row = csv_reader[1]
        self.assertEqual(error_row[0], "TS-P05")
        self.assertIn("Vehicle 'KA99ZZ0000' not found in registered fleet masters", error_row[20])

        # 2. Commit Partial Batch: commits 4 valid rows, skips 1 error row
        commit_res = commit_completed_trips_batch(self.conn, self.operator_user, batch_id)
        self.assertEqual(commit_res["committed_duties_count"], 4)

        # Confirm 4 duties were created in domain_duties
        duties_count = self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM domain_duties WHERE import_batch_id = ?",
            (batch_id,),
        ).fetchone()["cnt"]
        self.assertEqual(duties_count, 4)

    def test_04_multi_row_bulk_correction_patch(self):
        """4. Verify Multi-Row Bulk Correction: RECALCULATE_FROM_RATE_CARD and SET_CORPORATE."""
        # Insert 3 duties with un-recalculated fares
        now = now_iso()
        duty_ids = ["bulk_d1", "bulk_d2", "bulk_d3"]
        for d_id in duty_ids:
            self.conn.execute(
                """
                INSERT INTO domain_bookings (id, organization_id, customer_id, booking_reference, duty_type, status, created_at, updated_at)
                VALUES (?, ?, 'cust_infosys', ?, 'corporate', 'allocated', ?, ?)
                """,
                (f"bk_{d_id}", self.tenant_id, f"BR-BULK-{d_id}", now, now),
            )
            self.conn.execute(
                """
                INSERT INTO domain_duties (
                    id, organization_id, booking_id, vehicle_id, driver_id, status,
                    practical_start_km, practical_end_km, practical_billable_km,
                    practical_start_time, practical_end_time, final_client_fare_inr,
                    final_supplier_payout_inr, toll_parking_inr, created_at, updated_at
                ) VALUES (?, ?, ?, 'veh_01', 'drv_01', 'completed', 2000.0, 2080.0, 80.0, '2026-11-03T09:00:00Z', '2026-11-03T13:00:00Z', 1000.0, 800.0, 0.0, ?, ?)
                """,
                (d_id, self.tenant_id, f"bk_{d_id}", now, now),
            )
            # Create corresponding supplier payable ledger
            self.conn.execute(
                "INSERT INTO supplier_payable_ledger (id, organization_id, duty_id, amount_paise, status, created_at, updated_at) VALUES (?, ?, ?, 80000, 'PENDING', ?, ?)",
                (f"spl_{d_id}", self.tenant_id, d_id, now, now),
            )

        # Bulk recalculate rate-cards: 80 km for 4 hrs => 80 km * 25.0 = 2000 + 1500 base = 3500
        patch_payload = {
            "duty_ids": duty_ids,
            "action": "RECALCULATE_FROM_RATE_CARD",
        }
        bulk_res = bulk_correct_duties(self.conn, self.operator_user, patch_payload)
        self.assertTrue(bulk_res["ok"])
        self.assertEqual(bulk_res["modified_count"], 3)

        # Assert duties updated with recalculated fare and ledger synced
        for d_id in duty_ids:
            d = self.conn.execute("SELECT final_client_fare_inr, final_supplier_payout_inr FROM domain_duties WHERE id = ?", (d_id,)).fetchone()
            self.assertGreater(d["final_client_fare_inr"], 2000.0)
            spl = self.conn.execute("SELECT amount_paise FROM supplier_payable_ledger WHERE duty_id = ?", (d_id,)).fetchone()
            self.assertEqual(spl["amount_paise"], int(round(d["final_supplier_payout_inr"] * 100)))

        # Bulk change corporate to Wipro
        corp_patch = {
            "duty_ids": [duty_ids[0]],
            "action": "SET_CORPORATE",
            "corporate_name": "Wipro Technologies",
        }
        corp_res = bulk_correct_duties(self.conn, self.operator_user, corp_patch)
        self.assertTrue(corp_res["ok"])

    def test_05_post_invoice_credit_and_debit_adjustments(self):
        """5. Verify Post-Invoice Adjustments: leaves finalized invoice untouched, issues Credit/Debit Note."""
        now = now_iso()
        duty_id = "duty_invoiced_01"
        inv_id = "inv_tax_999"

        # 1. Create a duty marked as FINALIZED_IRN attached to Invoice ₹2,500
        self.conn.execute(
            """
            INSERT INTO domain_invoices (id, organization_id, customer_id, duty_id, invoice_number, status, total_paise, created_at, updated_at)
            VALUES (?, ?, 'cust_infosys', ?, 'INV-2026-0001', 'FINALIZED_IRN', 250000, ?, ?)
            """,
            (inv_id, self.tenant_id, duty_id, now, now),
        )
        self.conn.execute(
            """
            INSERT INTO domain_duties (
                id, organization_id, booking_id, vehicle_id, driver_id, status,
                practical_start_km, practical_end_km, practical_billable_km,
                practical_start_time, practical_end_time, final_client_fare_inr,
                final_supplier_payout_inr, invoice_status, invoice_id, created_at, updated_at
            ) VALUES (?, ?, 'bk_inv_1', 'veh_01', 'drv_01', 'completed', 3000.0, 3100.0, 100.0, '2026-11-01T08:00:00Z', '2026-11-01T12:00:00Z', 2500.0, 2000.0, 'FINALIZED_IRN', ?, ?, ?)
            """,
            (duty_id, self.tenant_id, inv_id, now, now),
        )
        self.conn.execute(
            "INSERT INTO supplier_payable_ledger (id, organization_id, duty_id, amount_paise, status, created_at, updated_at) VALUES ('spl_inv_1', ?, ?, 200000, 'PENDING', ?, ?)",
            (self.tenant_id, duty_id, now, now),
        )

        # 2. Issue post-invoice adjustment reducing client fare from ₹2,500 to ₹1,900 (Client overbilled by ₹600)
        adj_payload = {
            "practical_start_km": 3000.0,
            "practical_end_km": 3060.0,  # 60 km instead of 100 km
            "client_final_price_inr": 1900.0,
            "supplier_final_payout_inr": 1500.0,
            "override_tariff_lock": True,
            "reason_code": "ODOMETER_OVERSTATEMENT_REDUCTION",
            "remarks": "Driver entered 3100 instead of 3060 per physical slip loupe",
        }
        res_credit = create_post_invoice_adjustment(self.conn, self.operator_user, duty_id, adj_payload)
        self.assertTrue(res_credit["ok"])
        self.assertEqual(res_credit["note_type"], "CREDIT_NOTE_CLIENT")
        self.assertEqual(res_credit["delta_amount_inr"], 600.0)
        self.assertTrue(res_credit["is_credit_note"])
        self.assertEqual(res_credit["previous_amount_inr"], 2500.0)
        self.assertEqual(res_credit["corrected_amount_inr"], 1900.0)
        self.assertAlmostEqual(res_credit["gst_adjustment_inr"], 30.0)  # 5% of 600 = 30

        # Assert original GST invoice remains 100% UNTOUCHED
        inv = self.conn.execute("SELECT total_paise, status FROM domain_invoices WHERE id = ?", (inv_id,)).fetchone()
        self.assertEqual(inv["total_paise"], 250000)
        self.assertEqual(inv["status"], "FINALIZED_IRN")

        # Assert Credit Note is saved in financial_credit_debit_notes
        note_row = self.conn.execute("SELECT * FROM financial_credit_debit_notes WHERE original_duty_id = ?", (duty_id,)).fetchone()
        self.assertIsNotNone(note_row)
        self.assertEqual(note_row["note_type"], "CREDIT_NOTE_CLIENT")
        self.assertEqual(note_row["delta_amount_inr"], 600.0)

        # Assert Duty updated with corrected values
        updated_duty = self.conn.execute("SELECT practical_billable_km, final_client_fare_inr, final_supplier_payout_inr FROM domain_duties WHERE id = ?", (duty_id,)).fetchone()
        self.assertEqual(updated_duty["practical_billable_km"], 60.0)
        self.assertEqual(updated_duty["final_client_fare_inr"], 1900.0)
        self.assertEqual(updated_duty["final_supplier_payout_inr"], 1500.0)

        # Assert Supplier Payable Ledger synchronized to ₹1,500
        spl_row = self.conn.execute("SELECT amount_paise FROM supplier_payable_ledger WHERE duty_id = ?", (duty_id,)).fetchone()
        self.assertEqual(spl_row["amount_paise"], 150000)

        # 3. Test Debit Note (Client underbilled)
        duty_id_2 = "duty_invoiced_02"
        self.conn.execute(
            """
            INSERT INTO domain_duties (
                id, organization_id, booking_id, vehicle_id, driver_id, status,
                practical_start_km, practical_end_km, practical_billable_km,
                practical_start_time, practical_end_time, final_client_fare_inr,
                final_supplier_payout_inr, invoice_status, invoice_id, created_at, updated_at
            ) VALUES (?, ?, 'bk_inv_2', 'veh_01', 'drv_01', 'completed', 4000.0, 4050.0, 50.0, '2026-11-01T14:00:00Z', '2026-11-01T16:00:00Z', 1500.0, 1200.0, 'FINALIZED_IRN', ?, ?, ?)
            """,
            (duty_id_2, self.tenant_id, inv_id, now, now),
        )
        debit_payload = {
            "practical_start_km": 4000.0,
            "practical_end_km": 4080.0,
            "client_final_price_inr": 1950.0,  # ₹450 increase
            "supplier_final_payout_inr": 1500.0,
            "override_tariff_lock": True,
            "reason_code": "EXTRA_KM_UNDERBILLED",
        }
        res_debit = create_post_invoice_adjustment(self.conn, self.operator_user, duty_id_2, debit_payload)
        self.assertTrue(res_debit["ok"])
        self.assertEqual(res_debit["note_type"], "DEBIT_NOTE_CLIENT")
        self.assertEqual(res_debit["delta_amount_inr"], 450.0)
        self.assertTrue(res_debit["is_debit_note"])

    def test_06_api_dispatcher_routing(self):
        """6. Verify all new routes are cleanly routed via handle_completed_trips_api dispatcher."""
        # 1. Export Errors API: GET /api/v1/imports/completed-trips/{batch_id}/export-errors
        # Stage a batch with 1 error
        csv_data = (
            "external_tripsheet_no,trip_date,corporate_name,passenger_name,passenger_phone,pickup_location,drop_location,duty_type,vehicle_category,vehicle_registration,driver_name,driver_phone,start_time,end_time,practical_start_km,practical_end_km,toll_parking_inr,client_final_price_inr,supplier_final_payout_inr,remarks\n"
            "TS-ERR-API,2026-11-03,Infosys BPM Limited,Test User,+91 98800 00000,A,B,LOCAL,Sedan,KA99ZZ9999,Driver,+91 98800 11111,10:00,12:00,100,140,0,1500,1200,Bad Car\n"
        )
        staged = stage_completed_trips(self.conn, self.operator_user, csv_data, "bad.csv")
        batch_id = staged["batch_id"]

        api_res_export = handle_completed_trips_api(
            self.conn, self.operator_user, "GET", f"/api/v1/imports/completed-trips/{batch_id}/export-errors"
        )
        self.assertIsNotNone(api_res_export)
        self.assertTrue(api_res_export["ok"])
        self.assertEqual(api_res_export["error_rows_count"], 1)

        # 2. Bulk Correct API: PATCH /api/v1/duties/bulk-correct
        api_res_bulk = handle_completed_trips_api(
            self.conn,
            self.operator_user,
            "PATCH",
            "/api/v1/duties/bulk-correct",
            payload={"duty_ids": [], "action": "RECALCULATE_FROM_RATE_CARD"},
        )
        self.assertIsNotNone(api_res_bulk)
        self.assertTrue(api_res_bulk["ok"])

        # 3. Post Invoice Adjustment API: POST /api/v1/duties/{duty_id}/post-invoice-adjustment
        now = now_iso()
        self.conn.execute(
            """
            INSERT INTO domain_duties (
                id, organization_id, booking_id, vehicle_id, driver_id, status,
                practical_start_km, practical_end_km, practical_billable_km,
                practical_start_time, practical_end_time, final_client_fare_inr,
                final_supplier_payout_inr, invoice_status, created_at, updated_at
            ) VALUES ('duty_route_test', ?, 'bk_route_test', 'veh_01', 'drv_01', 'completed', 1000.0, 1050.0, 50.0, '2026-11-01T10:00:00Z', '2026-11-01T12:00:00Z', 1500.0, 1200.0, 'FINALIZED_IRN', ?, ?)
            """,
            (self.tenant_id, now, now),
        )
        api_res_adj = handle_completed_trips_api(
            self.conn,
            self.operator_user,
            "POST",
            "/api/v1/duties/duty_route_test/post-invoice-adjustment",
            payload={"client_final_price_inr": 1200.0, "override_tariff_lock": True},
        )
        self.assertIsNotNone(api_res_adj)
        self.assertTrue(api_res_adj["ok"])
        self.assertEqual(api_res_adj["note_type"], "CREDIT_NOTE_CLIENT")
        self.assertEqual(api_res_adj["delta_amount_inr"], 300.0)


if __name__ == "__main__":
    unittest.main()
