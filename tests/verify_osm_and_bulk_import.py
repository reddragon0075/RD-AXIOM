"""Axiom Mobility - OpenStreetMap (OSM) Engine, Completed Trips Bulk Importer
& ETS Routing Foundation Verification Suite.

Executes tests covering:
1. OSM Geocoding & Routing: Queries an address in Bengaluru, caches in osm_geocoding_cache,
   calculates road distance with 1.28x Indian urban tortuosity, and tests snapped_road_km.
2. Completed Trips Bulk Import: Stages a 10-row CSV containing 7 valid trips, 1 duplicate
   trip-sheet, 1 auto-slab upgrade candidate, and 1 missing vehicle. Asserts dry-run results,
   Dual-Ledger margins, and atomic transaction commit into duties and ledgers.
3. ETS Route Sequencer + POSH Night-Shift Check: Passes 4 employee coordinates + 1 office,
   verifying sequential ordering and night-shift female last-drop POSH guard auto-swap.
"""

import datetime as dt
from pathlib import Path
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
MVP_PATH = ROOT / "fleetline-mvp"
if str(MVP_PATH) not in sys.path:
    sys.path.insert(0, str(MVP_PATH))

from backend_domain import initialize_domain_schema
from backend_treasury_release import initialize_treasury_release_schema
from backend_practical_pricing import initialize_practical_pricing_schema
from backend.osm_spatial_service import (
    initialize_osm_spatial_schema,
    haversine_distance,
    osm_geocode_autocomplete,
    osm_calculate_route,
    osm_map_match_breadcrumbs,
    optimize_ets_route,
)
from backend.completed_trips_importer import (
    STANDARDIZED_SAMPLE_HEADERS,
    generate_sample_template,
    update_staged_trip_row,
    correct_duty_trip_details,
    handle_completed_trips_api,
    initialize_bulk_importer_schema,
    stage_completed_trips,
    commit_completed_trips_batch,
)


class TestOsmSpatialAndBulkImport(unittest.TestCase):
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
        initialize_osm_spatial_schema(self.conn)
        initialize_bulk_importer_schema(self.conn)

        self.vendor_org = "org_vendor_apex"
        self.operator_user = {
            "id": "usr_ops_01",
            "email": "ops@apexfleet.in",
            "role": "operator",
            "organization_id": self.vendor_org,
        }

        # Seed master vehicles and customers
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT INTO domain_customers (id, organization_id, name, created_at, updated_at)
            VALUES ('cust_infosys', ?, 'Infosys Campus', ?, ?),
                   ('cust_goldman', ?, 'Goldman Sachs', ?, ?)
            """,
            (self.vendor_org, now, now, self.vendor_org, now, now),
        )

        self.conn.execute(
            """
            INSERT INTO domain_vehicles (id, organization_id, registration_number, model, vehicle_type, status, created_at, updated_at)
            VALUES ('veh_1', ?, 'KA-01-MJ-4412', 'Maruti Dzire Tour', 'Sedan', 'available', ?, ?),
                   ('veh_2', ?, 'KA-04-AK-9821', 'Toyota Innova Crysta', 'SUV / Innova', 'available', ?, ?),
                   ('veh_3', ?, 'KA-05-MH-8841', 'Hyundai Aura', 'Sedan', 'available', ?, ?)
            """,
            (self.vendor_org, now, now, self.vendor_org, now, now, self.vendor_org, now, now),
        )

    def test_01_osm_geocoding_and_osrm_routing(self):
        """1. OSM Geocoding, landmark cache, road routing, and breadcrumb snapping."""
        # A. Query Address & Verify Cache Insertion
        res1 = osm_geocode_autocomplete(self.conn, "Whitefield Tech Park", city="Bengaluru")
        self.assertGreaterEqual(len(res1), 1)
        first_match = res1[0]
        self.assertIn("whitefield", first_match["display_name"].lower())
        self.assertAlmostEqual(first_match["lat"], 12.9863, places=2)

        # B. Verify Local Cache Hit (<5ms lookup)
        cache_row = self.conn.execute(
            "SELECT * FROM osm_geocoding_cache WHERE query_normalized = 'whitefield tech park'"
        ).fetchone()
        self.assertIsNotNone(cache_row)
        self.assertGreaterEqual(cache_row["hit_count"], 1)

        # C. OSRM Road Distance Calculation with 1.28x Urban Tortuosity Fallback
        origin = {"lat": 13.2008, "lng": 77.7088}  # Bangalore Airport T2
        dest = {"lat": 12.9863, "lng": 77.7381}    # Whitefield ITPB
        route = osm_calculate_route(origin, dest)

        self.assertTrue(route["ok"])
        self.assertEqual(route["tortuosity_factor"], 1.28)
        self.assertGreater(route["estimated_distance_km"], route["crow_distance_km"])
        self.assertIn("geojson_polyline", route)
        self.assertGreater(route["estimated_duration_mins"], 15)

        # D. 3-Way Distance Fraud Auditor: Map-matching breadcrumbs
        pings = [
            {"lat": 12.9716, "lng": 77.5946, "recorded_at": "2026-11-03T10:00:00Z"},
            {"lat": 12.9750, "lng": 77.6050, "recorded_at": "2026-11-03T10:05:00Z"},
            {"lat": 12.9751, "lng": 77.6051, "recorded_at": "2026-11-03T10:12:00Z"}, # >5 min stoppage
            {"lat": 12.9863, "lng": 77.7381, "recorded_at": "2026-11-03T10:45:00Z"},
        ]
        snap_res = osm_map_match_breadcrumbs(pings)
        self.assertTrue(snap_res["ok"])
        self.assertGreater(snap_res["snapped_road_km"], 0.0)
        self.assertGreaterEqual(snap_res["stoppages_count"], 1)
        self.assertEqual(snap_res["anti_fraud_audit"]["status"], "PASSED")

        print("PASS: OSM Geocoding Cache, OSRM Routing & Map-Matching Snapping verified.")

    def test_02_completed_trips_bulk_import_and_commit(self):
        """2. Bulk upload 10 completed trips: detects duplicates, missing vehicles, and commits."""
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        # Seed an existing duty to test duplicate detection
        self.conn.execute(
            """
            INSERT INTO domain_duties (
                id, organization_id, booking_id, status, external_tripsheet_no, created_at, updated_at
            ) VALUES ('duty_existing_01', ?, 'bk_00', 'completed', 'TS-DUP-999', ?, ?)
            """,
            (self.vendor_org, now, now),
        )

        # 10-row CSV content:
        # - Row 1 to 7: Valid trips
        # - Row 8: Duplicate trip sheet (TS-DUP-999)
        # - Row 9: 74 km Auto-Slab Upgrade candidate (from 40km to 74km)
        # - Row 10: Missing vehicle error (KA-99-ZZ-0000)
        csv_data = """Trip Sheet No,Cab No,Corporate,Passenger Name,Start KM,End KM,Start Time,End Time,Toll/Parking,Billed Amount,Vehicle Category
TS-IMP-001,KA-01-MJ-4412,Infosys Campus,Guest 1,1000,1040,2026-11-03 09:00,2026-11-03 13:00,0,1500,Sedan
TS-IMP-002,KA-04-AK-9821,Goldman Sachs,Guest 2,2000,2035,2026-11-03 10:00,2026-11-03 14:00,50,1550,SUV / Innova
TS-IMP-003,KA-01-MJ-4412,Infosys Campus,Guest 3,1040,1075,2026-11-03 14:00,2026-11-03 18:00,0,1500,Sedan
TS-IMP-004,KA-05-MH-8841,Goldman Sachs,Guest 4,500,530,2026-11-03 08:30,2026-11-03 12:30,0,1500,Sedan
TS-IMP-005,KA-01-MJ-4412,Infosys Campus,Guest 5,1075,1110,2026-11-03 18:30,2026-11-03 22:30,100,1600,Sedan
TS-IMP-006,KA-04-AK-9821,Goldman Sachs,Guest 6,2035,2070,2026-11-03 15:00,2026-11-03 19:00,0,1500,SUV / Innova
TS-IMP-007,KA-05-MH-8841,Infosys Campus,Guest 7,530,565,2026-11-03 13:00,2026-11-03 17:00,0,1500,Sedan
TS-DUP-999,KA-01-MJ-4412,Infosys Campus,Guest Dup,1110,1150,2026-11-03 09:00,2026-11-03 13:00,0,1500,Sedan
TS-IMP-009,KA-01-MJ-4412,Infosys Campus,Auto Slab Guest,1150,1224,2026-11-03 09:00,2026-11-03 13:00,0,2350,Sedan
TS-IMP-010,KA-99-ZZ-0000,Infosys Campus,Missing Veh Guest,100,140,2026-11-03 09:00,2026-11-03 13:00,0,1500,Sedan
"""

        # Step A: Stage & Dry-Run
        staged = stage_completed_trips(self.conn, self.operator_user, csv_data, "historical_10_trips.csv")
        self.assertTrue(staged["ok"])
        batch_id = staged["batch_id"]
        summary = staged["summary"]

        self.assertEqual(summary["total_rows"], 10)
        self.assertEqual(summary["duplicate_rows"], 1)  # TS-DUP-999
        self.assertEqual(summary["error_rows"], 1)      # KA-99-ZZ-0000 missing
        self.assertEqual(summary["valid_rows"], 8)      # 7 standard + 1 auto-slab
        self.assertGreater(summary["estimated_total_receivable_inr"], 10000.0)
        self.assertGreater(summary["net_margin_inr"], 2000.0)

        # Verify auto-slab upgrade calculation on Row 9 (74 km billable -> ₹2,350)
        row_9 = next(r for r in staged["staged_rows"] if r["external_tripsheet_no"] == "TS-IMP-009")
        self.assertEqual(row_9["practical_billable_km"], 74.0)
        self.assertEqual(row_9["computed_client_fare_inr"], 2350.0)

        # Step B: Atomic Commit to Duties & Ledgers
        commit_res = commit_completed_trips_batch(self.conn, self.operator_user, batch_id)
        self.assertTrue(commit_res["ok"])
        self.assertEqual(commit_res["status"], "COMMITTED")
        self.assertEqual(commit_res["committed_duties_count"], 8)  # Only valid/non-error rows committed

        # Verify database records
        duties_created = self.conn.execute(
            "SELECT * FROM domain_duties WHERE import_batch_id = ?",
            (batch_id,),
        ).fetchall()
        self.assertEqual(len(duties_created), 8)
        for d in duties_created:
            self.assertEqual(d["status"], "completed")
            self.assertEqual(d["closing_source"], "BULK_COMPLETED_IMPORT")

        print("PASS: Completed Trips Bulk Ingestion, Duplicate Blocking & Atomic Commit verified.")

    def test_03_ets_route_sequencer_and_posh_guard_rule(self):
        """3. ETS Route Sequencer: Optimal sequencing & POSH night-shift female last drop auto-swap."""
        campus = {"lat": 12.8452, "lng": 77.6602}  # Electronic City Campus

        # 4 Employee Stops (Logout Shift):
        # - Stop A (Female): BTM Layout (8 km from campus)
        # - Stop B (Male): Koramangala (11 km from campus)
        # - Stop C (Female): Indiranagar (15 km from campus - farthest)
        # - Stop D (Male): HSR Layout (6 km from campus)
        employees = [
            {"id": "emp_1", "name": "Pooja Hegde", "gender": "F", "lat": 12.9165, "lng": 77.6101, "address": "BTM Layout"},
            {"id": "emp_2", "name": "Rahul Verma", "gender": "M", "lat": 12.9345, "lng": 77.6265, "address": "Koramangala"},
            {"id": "emp_3", "name": "Sneha Roy", "gender": "F", "lat": 12.9719, "lng": 77.6412, "address": "Indiranagar"},
            {"id": "emp_4", "name": "Amit Sharma", "gender": "M", "lat": 12.9121, "lng": 77.6445, "address": "HSR Layout"},
        ]

        # Case A: Night Shift (22:30) without Security Guard
        # Sneha (Female) is farthest from office. Normally she would be dropped last.
        # POSH Rule should detect this and auto-swap with nearest male (Rahul) if detour <= 15m.
        route_night = optimize_ets_route(
            campus_coord=campus,
            employee_stops=employees,
            shift_type="LOGOUT",
            shift_time="22:30",
            has_security_guard=False,
        )

        self.assertTrue(route_night["ok"])
        self.assertEqual(route_night["total_stops"], 4)
        self.assertTrue(route_night["is_night_shift"])

        # Assert POSH Auto-Swap was executed: Last dropped passenger is Male!
        last_drop = route_night["optimized_stops"][-1]
        self.assertEqual(last_drop["gender"], "M", "Last drop in night shift must be Male when no guard is present!")
        self.assertTrue(route_night["posh_compliance"]["posh_swapped"])
        self.assertIn("POSH Auto-Swap", route_night["posh_compliance"]["reason"])

        # Case B: All female night shift without guard -> triggers POSH_GUARD_MANDATORY
        all_female_emps = [
            {"id": "emp_f1", "name": "Kavita R.", "gender": "F", "lat": 12.9165, "lng": 77.6101},
            {"id": "emp_f2", "name": "Deepa N.", "gender": "F", "lat": 12.9719, "lng": 77.6412},
        ]
        route_guard_req = optimize_ets_route(
            campus_coord=campus,
            employee_stops=all_female_emps,
            shift_type="LOGOUT",
            shift_time="23:00",
            has_security_guard=False,
        )
        self.assertEqual(route_guard_req["posh_compliance"]["status"], "POSH_GUARD_MANDATORY")
        self.assertTrue(route_guard_req["posh_compliance"]["guard_mandatory"])

        print("PASS: ETS OSRM Route Sequencer and POSH Night-Shift Guard Rules verified.")



    def test_04_sample_template_downloader(self):
        """4. Sample Template Generator: Validates exact 20 headers, UTF-8 BOM, and realistic sample data."""
        # 1. Direct function call for CSV
        csv_res = generate_sample_template("csv")
        self.assertTrue(csv_res["ok"])
        self.assertEqual(csv_res["format"], "csv")
        self.assertTrue(csv_res["csv_text"].startswith("\ufeff"), "CSV must include UTF-8 BOM for Microsoft Excel")
        self.assertEqual(csv_res["headers"], STANDARDIZED_SAMPLE_HEADERS)
        self.assertGreaterEqual(csv_res["rows_count"], 3)

        # 2. Direct function call for JSON
        json_res = generate_sample_template("json")
        self.assertTrue(json_res["ok"])
        self.assertEqual(json_res["format"], "json")
        self.assertEqual(len(json_res["rows"]), 3)
        self.assertIn("corporate_name", json_res["rows"][0])
        self.assertIn("client_final_price_inr", json_res["rows"][0])

        # 3. Via API dispatcher with query parameters
        api_res = handle_completed_trips_api(
            self.conn,
            self.operator_user,
            "GET",
            "/api/v1/imports/completed-trips/sample-template?format=csv",
        )
        self.assertIsNotNone(api_res)
        self.assertTrue(api_res["ok"])
        self.assertEqual(api_res["_content_type"], "text/csv; charset=utf-8")
        self.assertIn("axiom_completed_trips_template.csv", api_res["_disposition"])
        print("PASS: 1-Click Sample File Generator with UTF-8 BOM & Exact Standardized Headers verified.")

    def test_05_interactive_staging_row_correction(self):
        """5. Pre-Commit Staging Workbench: Inline cell editing, tariff auto-recalculation, and manual override lock."""
        # Stage a batch containing 1 missing vehicle row
        csv_data = """external_tripsheet_no,vehicle_registration,corporate_name,passenger_name,passenger_phone,practical_start_km,practical_end_km,start_time,end_time,toll_parking_inr,client_final_price_inr
TS-STG-001,KA-99-ZZ-0000,Infosys Campus,Guest Staging,+919880011111,1000,1040,2026-11-03 09:00,2026-11-03 13:00,0,1500
"""
        staged = stage_completed_trips(self.conn, self.operator_user, csv_data, "staging_test.csv")
        batch_id = staged["batch_id"]
        row_1 = staged["staged_rows"][0]
        row_id = row_1["id"]

        # Initial state: Missing vehicle -> ERROR_MISSING_REF
        self.assertEqual(row_1["validation_status"], "ERROR_MISSING_REF")

        # Step A: Correct the vehicle registration to an active vehicle in fleet
        corrected_veh = update_staged_trip_row(
            self.conn,
            self.operator_user,
            row_id,
            {"vehicle_registration": "KA-01-MJ-4412"},
        )
        self.assertTrue(corrected_veh["ok"])
        self.assertEqual(corrected_veh["row"]["validation_status"], "VALID")
        self.assertEqual(corrected_veh["batch_summary"]["valid_rows"], 1)
        self.assertEqual(corrected_veh["batch_summary"]["error_rows"], 0)

        # Step B: Modify End KM from 1040 to 1080 (40 km -> 80 km)
        # Automatic tariff engine should recalculate fare from base 1500 to 2500
        recalculated_km = update_staged_trip_row(
            self.conn,
            self.operator_user,
            row_id,
            {"practical_end_km": 1080.0, "toll_parking_inr": 120.0},
        )
        self.assertTrue(recalculated_km["ok"])
        row_updated = recalculated_km["row"]
        self.assertEqual(row_updated["practical_billable_km"], 80.0)
        self.assertEqual(row_updated["toll_parking_inr"], 120.0)
        # Expected: base 1500 + 40 extra km * 25 + toll 120 = 2620
        self.assertEqual(row_updated["computed_client_fare_inr"], 2620.0)

        # Step C: Toggle Manual Price Override Lock
        # Operator enforces special negotiated price ₹3,150
        locked_price = update_staged_trip_row(
            self.conn,
            self.operator_user,
            row_id,
            {"client_final_price_inr": 3150.0, "supplier_final_payout_inr": 2500.0, "override_tariff_lock": True},
        )
        self.assertTrue(locked_price["ok"])
        self.assertTrue(locked_price["row"]["override_tariff_lock"])
        self.assertEqual(locked_price["row"]["computed_client_fare_inr"], 3150.0)
        self.assertEqual(locked_price["row"]["computed_supplier_payout_inr"], 2500.0)
        self.assertEqual(locked_price["row"]["applied_slab_name"], "MANUAL_PRICE_OVERRIDE_LOCKED")
        print("PASS: Pre-Commit Staging Grid Editing, Tariff Recalculation & Override Lock verified.")

    def test_06_interactive_duty_trip_details_correction(self):
        """6. Post-Commit Trip Correction Workbench: Edits completed duty, recalculates or locks price, syncs ledger."""
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        duty_id = "duty_post_commit_01"
        booking_id = "bk_post_commit_01"

        # Seed booking and completed duty
        self.conn.execute(
            """
            INSERT INTO domain_bookings (
                id, organization_id, customer_id, booking_reference, status,
                passenger_name, scheduled_at, vehicle_category, estimated_distance_km,
                estimated_client_fare_inr, estimated_supplier_payout_inr, created_at, updated_at
            ) VALUES (?, ?, 'cust_infosys', 'BK-CORR-01', 'completed', 'Rohan Mehra', ?, 'Sedan', 40.0, 1500.0, 1200.0, ?, ?)
            """,
            (booking_id, self.vendor_org, now, now, now),
        )
        self.conn.execute(
            """
            INSERT INTO domain_duties (
                id, organization_id, booking_id, vehicle_id, status, reporting_at,
                started_at, completed_at, start_odometer, end_odometer,
                practical_start_km, practical_end_km, practical_billable_km,
                final_client_fare_inr, final_supplier_payout_inr, closing_source,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'veh_1', 'completed', ?, ?, ?, 1000, 1040, 1000.0, 1040.0, 40.0, 1500.0, 1200.0, 'BULK_COMPLETED_IMPORT', ?, ?)
            """,
            (duty_id, self.vendor_org, booking_id, now, now, now, now, now),
        )
        self.conn.execute(
            """
            INSERT INTO supplier_payable_ledger (
                id, duty_id, vendor_id, amount_paise, status, audit_passed_at, created_at, updated_at
            ) VALUES ('spl_post_01', ?, ?, 120000, 'FUNDS_HELD_BY_AXIOM', ?, ?, ?)
            """,
            (duty_id, self.vendor_org, now, now, now),
        )

        # Case 1: Post-commit correction with auto-tariff recalculation (Odometer changed from 40 km to 60 km)
        corr_auto = correct_duty_trip_details(
            self.conn,
            self.operator_user,
            duty_id,
            {"practical_start_km": 1000.0, "practical_end_km": 1060.0, "toll_parking_inr": 50.0, "override_tariff_lock": False},
        )
        self.assertTrue(corr_auto["ok"])
        self.assertEqual(corr_auto["practical_billable_km"], 60.0)
        # Expected: base 1500 + 20 extra km * 25 + toll 50 = 2050
        self.assertEqual(corr_auto["final_client_fare_inr"], 2050.0)
        self.assertEqual(corr_auto["closing_source"], "PRACTICAL_TARIFF_RECALCULATED")

        # Verify ledger sync
        spl_row = self.conn.execute("SELECT amount_paise FROM supplier_payable_ledger WHERE duty_id = ?", (duty_id,)).fetchone()
        self.assertEqual(spl_row["amount_paise"], int(round(corr_auto["final_supplier_payout_inr"] * 100)))

        # Case 2: Post-commit correction with Manual Price Override Lock
        corr_lock = correct_duty_trip_details(
            self.conn,
            self.operator_user,
            duty_id,
            {
                "client_final_price_inr": 2800.0,
                "supplier_final_payout_inr": 2200.0,
                "override_tariff_lock": True,
                "remarks": "Client agreed flat lump-sum fare after review",
            },
        )
        self.assertTrue(corr_lock["ok"])
        self.assertEqual(corr_lock["final_client_fare_inr"], 2800.0)
        self.assertEqual(corr_lock["final_supplier_payout_inr"], 2200.0)
        self.assertEqual(corr_lock["closing_source"], "MANUAL_PRICE_OVERRIDE")

        # Verify ledger updated with locked payout (₹2,200 = 220000 paise)
        spl_locked = self.conn.execute("SELECT amount_paise FROM supplier_payable_ledger WHERE duty_id = ?", (duty_id,)).fetchone()
        self.assertEqual(spl_locked["amount_paise"], 220000)

        # Verify parent booking updated
        bk_row = self.conn.execute("SELECT estimated_client_fare_inr, estimated_supplier_payout_inr FROM domain_bookings WHERE id = ?", (booking_id,)).fetchone()
        self.assertEqual(bk_row["estimated_client_fare_inr"], 2800.0)
        self.assertEqual(bk_row["estimated_supplier_payout_inr"], 2200.0)

        # Verify audit event
        audit_event = self.conn.execute("SELECT * FROM audit_events WHERE action = 'duty.trip_details_corrected' ORDER BY rowid DESC LIMIT 1").fetchone()
        self.assertIsNotNone(audit_event)
        self.assertIn("2800", audit_event["metadata_json"])

        print("PASS: Post-Commit Trip Correction Workbench, Price Override Lock & Dual-Ledger Sync verified.")

if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestOsmSpatialAndBulkImport)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
