"""Test suite for Optimistic Concurrency Control (OCC) and Offline Replay Conflict Prevention."""

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from backend_domain import DomainError, _create_duty, _update_duty, initialize_domain_schema
from backend_features import initialize_feature_schema
from backend_extended import initialize_extended_schema
from backend_operations_parity import _close_duty, initialize_operations_parity_schema

def run_tests():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_events (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            ip_address TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    initialize_domain_schema(conn)
    initialize_feature_schema(conn)
    initialize_extended_schema(conn)
    initialize_operations_parity_schema(conn)

    org = "org_test_fleet"
    user_vendor = {"id": "usr_vendor", "role": "vendor", "organization_id": org}
    user_driver = {"id": "usr_driver", "role": "driver", "organization_id": org}

    # Seed driver, vehicle, booking
    conn.execute("INSERT INTO domain_drivers (id, organization_id, user_id, full_name, status, created_at, updated_at) VALUES ('drv_1', ?, ?, 'Test Driver', 'active', '2026-10-27', '2026-10-27')", (org, user_driver["id"]))
    conn.execute("INSERT INTO domain_vehicles (id, organization_id, registration_number, status, created_at, updated_at) VALUES ('veh_1', ?, 'KA-01-AB-1234', 'active', '2026-10-27', '2026-10-27')", (org,))
    conn.execute("INSERT INTO domain_bookings (id, organization_id, booking_reference, passenger_name, status, scheduled_at, created_at, updated_at) VALUES ('bk_1', ?, 'BK-1001', 'Test Passenger', 'requested', '2026-10-27', '2026-10-27', '2026-10-27')", (org,))
    conn.commit()

    # 1. Create Duty (Initial version_id should be 1)
    duty_res = _create_duty(conn, user_vendor, {"booking_id": "bk_1", "driver_id": "drv_1", "vehicle_id": "veh_1"}, "127.0.0.1")
    duty_id = duty_res["item"]["id"]
    row = conn.execute("SELECT * FROM domain_duties WHERE id = ?", (duty_id,)).fetchone()
    assert row["version_id"] == 1, f"Expected initial version_id 1, got {row['version_id']}"
    print("PASS 1: Duty initialized with version_id = 1")

    # 2. Driver accepts duty with expected_version = 1 -> version_id advances to 2
    res2 = _update_duty(conn, user_driver, duty_id, {"status": "accepted", "expected_version": 1}, "127.0.0.1")
    row2 = conn.execute("SELECT * FROM domain_duties WHERE id = ?", (duty_id,)).fetchone()
    assert row2["version_id"] == 2, f"Expected version_id 2, got {row2['version_id']}"
    assert row2["status"] == "accepted"
    print("PASS 2: Driver accepted duty with expected_version=1; version advanced to 2")

    # 3. Offline conflict simulation: Stale replay with expected_version = 1 should raise 409
    try:
        _update_duty(conn, user_driver, duty_id, {"status": "en_route", "expected_version": 1}, "127.0.0.1")
        assert False, "Should have raised 409 concurrency_conflict"
    except DomainError as e:
        assert e.status == 409 and e.code == "concurrency_conflict"
    print("PASS 3: Stale offline mutation with outdated version_id correctly rejected with 409 concurrency_conflict")

    # 4. Valid progression: en_route -> started with expected_version = 2
    _update_duty(conn, user_driver, duty_id, {"status": "en_route", "expected_version": 2}, "127.0.0.1")
    _update_duty(conn, user_driver, duty_id, {"status": "started", "start_odometer": 1000, "expected_version": 3}, "127.0.0.1")
    row3 = conn.execute("SELECT * FROM domain_duties WHERE id = ?", (duty_id,)).fetchone()
    assert row3["version_id"] == 4
    print("PASS 4: Sequential status progression advanced version_id to 4")

    # 5. Duty Closure with Concurrency Guard
    # Try closing with stale version
    try:
        _close_duty(conn, user_driver, duty_id, {"start_odometer": 1000, "end_odometer": 1050, "expected_version": 2}, "127.0.0.1")
        assert False, "Should have failed with 409 concurrency_conflict"
    except DomainError as e:
        assert e.status == 409 and e.code == "concurrency_conflict"
    print("PASS 5: Duty closure rejected stale expected_version=2")

    # Close with valid version
    close_res = _close_duty(conn, user_driver, duty_id, {"start_odometer": 1000, "end_odometer": 1050, "expected_version": 4}, "127.0.0.1")
    row4 = conn.execute("SELECT * FROM domain_duties WHERE id = ?", (duty_id,)).fetchone()
    assert row4["status"] == "completed"
    assert row4["version_id"] == 5
    print("PASS 6: Duty successfully closed and sealed at version_id = 5")

    # 6. Reject closing already completed duty
    try:
        _close_duty(conn, user_driver, duty_id, {"start_odometer": 1000, "end_odometer": 1050}, "127.0.0.1")
        assert False, "Should have rejected closing already completed duty"
    except DomainError as e:
        assert e.status == 409 and e.code == "duty_already_closed_or_cancelled"
    print("PASS 7: Duplicate close on completed duty rejected with 409")

    print("\nALL OPTIMISTIC CONCURRENCY CONTROL TESTS PASSED (7/7)")

if __name__ == "__main__":
    run_tests()
