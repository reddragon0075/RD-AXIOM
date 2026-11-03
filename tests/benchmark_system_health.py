#!/usr/bin/env python3
"""Axiom Mobility (Fleetline) - Full-Stack Performance & System Health Benchmark Suite.

Benchmarks:
1. Single-Roundtrip Workspace Bootstrap Speed (<100ms requirement).
2. Vectorized Completed Trips Bulk Upload Throughput (250 rows staged in <1.0s and committed atomically).
3. Thread-Safe In-Memory LRU/TTL Cache Speed (<1ms for cached OSM lookups).
4. Standardized JSON Error Payload Envelope verification.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import sqlite3
import sys
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parent.parent / "fleetline-mvp"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend_workspace_bootstrap import (
    get_workspace_bootstrap_summary,
    handle_workspace_bootstrap_api,
    initialize_performance_indexes,
)
from backend_completed_trips_importer import (
    commit_completed_trips_batch,
    initialize_bulk_importer_schema,
    stage_completed_trips,
)
from backend_osm_spatial import (
    GLOBAL_OSM_CACHE,
    TTLCache,
    initialize_osm_spatial_schema,
    osm_calculate_route,
    osm_geocode_autocomplete,
)
from backend_practical_pricing import initialize_practical_pricing_schema
from backend_odometer_and_adjustment import initialize_odometer_and_adjustment_schema
from backend_domain import initialize_domain_schema


class BenchmarkSystemHealth(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.tenant_id = "org_perf_test"
        self.user = {
            "id": "usr_perf_admin",
            "organization_id": self.tenant_id,
            "role": "super_admin",
        }

        self.conn.execute("PRAGMA foreign_keys = OFF")
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL DEFAULT 'vendor',
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE_GOOD_STANDING',
                created_at TEXT NOT NULL DEFAULT '2026-11-04T00:00:00+00:00'
            );
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                role TEXT NOT NULL,
                organization_id TEXT,
                created_at TEXT NOT NULL DEFAULT '2026-11-04T00:00:00+00:00'
            );
            CREATE TABLE IF NOT EXISTS supplier_payable_ledger (
                id TEXT PRIMARY KEY,
                duty_id TEXT,
                vendor_id TEXT,
                tenant_id TEXT,
                amount_paise INTEGER,
                payout_amount_inr REAL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'AVAILABLE',
                eligible_for_release_at TEXT,
                audit_passed_at TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            """
        )

        # Initialize full suite schemas
        initialize_domain_schema(self.conn)
        initialize_practical_pricing_schema(self.conn)
        initialize_bulk_importer_schema(self.conn)
        initialize_odometer_and_adjustment_schema(self.conn)
        initialize_osm_spatial_schema(self.conn)
        initialize_performance_indexes(self.conn)

        # Seed realistic operational data
        now = "2026-11-04T09:00:00+00:00"
        self.conn.execute(
            "INSERT INTO organizations (id, name, kind, status) VALUES (?, 'Axiom Bengaluru Ops', 'vendor', 'ACTIVE_GOOD_STANDING')",
            (self.tenant_id,),
        )
        self.conn.execute(
            "INSERT INTO domain_customers (id, organization_id, name, created_at, updated_at) VALUES ('cust_gs', ?, 'Goldman Sachs', ?, ?)",
            (self.tenant_id, now, now),
        )
        self.conn.execute(
            "INSERT INTO domain_vehicles (id, organization_id, registration_number, model, vehicle_type, created_at, updated_at) VALUES ('veh_1', ?, 'KA-01-AB-1234', 'Innova', 'SUV', ?, ?)",
            (self.tenant_id, now, now),
        )
        self.conn.execute(
            "INSERT INTO domain_drivers (id, organization_id, full_name, phone, created_at, updated_at) VALUES ('drv_1', ?, 'Ramesh Kumar', '+919880011223', ?, ?)",
            (self.tenant_id, now, now),
        )

        # Seed 10 existing completed duties with ascending timestamps
        for i in range(1, 11):
            bk_id = f"seed_bk_{i}"
            duty_id = f"seed_dt_{i}"
            duty_time = f"2026-11-04T08:{i:02d}:00+00:00"
            self.conn.execute(
                """
                INSERT INTO domain_bookings (
                    id, organization_id, customer_id, booking_reference, status,
                    passenger_name, passenger_phone, scheduled_at, vehicle_category,
                    estimated_distance_km, estimated_client_fare_inr, estimated_supplier_payout_inr,
                    created_at, updated_at
                ) VALUES (?, ?, 'cust_gs', ?, 'completed', 'Guest', '+919000000000', ?, 'SUV', 40.0, 3500.0, 2800.0, ?, ?)
                """,
                (bk_id, self.tenant_id, f"REF-{i}", duty_time, duty_time, duty_time),
            )
            self.conn.execute(
                """
                INSERT INTO domain_duties (
                    id, organization_id, booking_id, vehicle_id, status, reporting_at,
                    started_at, completed_at, start_odometer, end_odometer,
                    practical_start_km, practical_end_km, practical_billable_km,
                    practical_start_time, practical_end_time,
                    final_client_fare_inr, final_supplier_payout_inr,
                    external_tripsheet_no, created_at, updated_at
                ) VALUES (?, ?, ?, 'veh_1', 'completed', ?, ?, ?, ?, ?, ?, ?, 40.0, ?, ?, 3500.0, 2800.0, ?, ?, ?)
                """,
                (
                    duty_id, self.tenant_id, bk_id,
                    duty_time, duty_time, duty_time,
                    10000 + (i - 1) * 45, 10000 + i * 45,
                    10000 + (i - 1) * 45, 10000 + i * 45,
                    duty_time, duty_time,
                    f"EXT-SEED-{i}", duty_time, duty_time,
                ),
            )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_01_workspace_bootstrap_latency(self):
        """1. Workspace Bootstrap Benchmark: Responds with complete KPI payload in <100ms."""
        t0 = time.perf_counter()
        summary = get_workspace_bootstrap_summary(self.conn, self.user)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["tenant_access"]["status"], "ACTIVE_GOOD_STANDING")
        self.assertFalse(summary["tenant_access"]["treasury_hold_active"])
        self.assertEqual(summary["duty_counts"]["completed_today_count"], 10)
        self.assertEqual(summary["dual_ledger_summary"]["total_receivable_inr"], 35000.0)
        self.assertEqual(summary["dual_ledger_summary"]["total_payable_inr"], 28000.0)
        self.assertEqual(summary["dual_ledger_summary"]["net_margin_inr"], 7000.0)
        self.assertEqual(summary["dual_ledger_summary"]["margin_pct"], 20.0)
        self.assertIsNotNone(summary["super_admin_summary"])

        print(f"\n[BENCHMARK 1] Workspace Bootstrap Latency: {elapsed_ms:.2f}ms (Budget: <100ms)")
        self.assertLess(elapsed_ms, 100.0, f"Bootstrap latency {elapsed_ms:.2f}ms exceeded 100ms SLA")

    def test_02_vectorized_bulk_upload_250_rows_throughput(self):
        """2. Vectorized Bulk Upload Benchmark: Stages 250 rows in <1.0s and commits atomically."""
        # Generate 250 rows CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)
        headers = [
            "external_tripsheet_no", "trip_date", "corporate_name", "passenger_name", "passenger_phone",
            "pickup_location", "drop_location", "duty_type", "vehicle_category", "vehicle_registration",
            "driver_name", "driver_phone", "start_time", "end_time", "practical_start_km", "practical_end_km",
            "toll_parking_inr", "client_final_price_inr", "supplier_final_payout_inr", "remarks"
        ]
        writer.writerow(headers)

        base_km = 10450
        for i in range(1, 251):
            writer.writerow([
                f"TS-BULK-BENCH-{i}",
                "2026-11-04",
                "Goldman Sachs",
                f"Guest {i}",
                "+919880011223",
                "EGL Domlur",
                "Whitefield ITPL",
                "LOCAL_4HR_40KM",
                "SUV",
                "KA-01-AB-1234",
                "Ramesh Kumar",
                "+919880011223",
                "2026-11-04 10:00",
                "2026-11-04 11:30",
                str(base_km + (i - 1) * 40),
                str(base_km + i * 40),
                "0",
                "1500.00",
                "1200.00",
                "Benchmark Test Ride",
            ])

        csv_content = output.getvalue()

        # Step A: Benchmark Staging
        t_stage_start = time.perf_counter()
        stage_res = stage_completed_trips(self.conn, self.user, csv_content, "bench_250.csv")
        stage_elapsed_s = time.perf_counter() - t_stage_start

        batch_id = stage_res["batch_id"]
        self.assertEqual(stage_res["summary"]["total_rows"], 250)
        self.assertEqual(stage_res["summary"]["valid_rows"], 250)
        self.assertEqual(stage_res["summary"]["duplicate_rows"], 0)

        print(f"[BENCHMARK 2A] 250-Row Bulk Staging Time: {stage_elapsed_s:.3f}s (Budget: <1.0s)")
        self.assertLess(stage_elapsed_s, 1.0, f"Bulk staging took {stage_elapsed_s:.3f}s (>1.0s SLA)")

        # Step B: Benchmark Vectorized Atomic Commit
        t_commit_start = time.perf_counter()
        commit_res = commit_completed_trips_batch(self.conn, self.user, batch_id)
        commit_elapsed_s = time.perf_counter() - t_commit_start

        self.assertTrue(commit_res["ok"])
        self.assertEqual(commit_res["committed_duties_count"], 250)

        print(f"[BENCHMARK 2B] 250-Row Vectorized Atomic Commit Time: {commit_elapsed_s:.3f}s (Budget: <1.5s)")
        self.assertLess(commit_elapsed_s, 1.5, f"Bulk commit took {commit_elapsed_s:.3f}s (>1.5s SLA)")

    def test_03_in_memory_ttl_cache_speed(self):
        """3. In-Memory LRU/TTL Cache Benchmark: Cached lookups execute in <1ms."""
        GLOBAL_OSM_CACHE.clear()

        # Prime the cache
        osm_geocode_autocomplete(self.conn, "bangalore airport t2", "Bengaluru")

        # Second lookup should hit memory cache directly
        t0 = time.perf_counter()
        cached_results = osm_geocode_autocomplete(self.conn, "bangalore airport t2", "Bengaluru")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        self.assertTrue(len(cached_results) > 0)
        print(f"[BENCHMARK 3] OSM TTLCache Memory Hit Latency: {elapsed_ms:.3f}ms (Budget: <1.0ms)")
        self.assertLess(elapsed_ms, 1.0, f"Cache hit latency {elapsed_ms:.3f}ms exceeded 1.0ms")

    def test_04_standardized_json_error_envelope(self):
        """4. Standardized JSON Envelope: Endpoints return clean structured error contract."""
        from backend_domain import DomainError
        with self.assertRaises(DomainError) as ctx:
            handle_workspace_bootstrap_api(self.conn, self.user, "POST", "/api/v1/system/workspace-bootstrap")
        self.assertEqual(ctx.exception.status, 405)
        self.assertEqual(ctx.exception.code, "method_not_allowed")

        get_res = handle_workspace_bootstrap_api(self.conn, self.user, "GET", "/api/v1/system/workspace-bootstrap")
        self.assertTrue(get_res["ok"])
        self.assertEqual(get_res["status"], "ok")
        self.assertIn("tenant_access", get_res)
        self.assertIn("duty_counts", get_res)
        self.assertIn("dual_ledger_summary", get_res)


if __name__ == "__main__":
    unittest.main()
