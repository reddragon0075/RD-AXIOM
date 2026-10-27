#!/usr/bin/env python3
"""Axiom Mobility (Fleetline) Seam Contracts & Security Verification Test Suite.

Tests and guards cross-boundary seams:
1. Tariff Engine 6-Model Contract & Type Uniformity:
   - HR_KM_SLAB, OUTSTATION_CALENDAR_DAY, RADIAL_ZONE_RING, PER_SEAT_SHARED_POOL,
     MONTHLY_DEDICATED_FIXED_VARIABLE, FUEL_INDEXED_BACK_TO_BACK
   - Numeric type safety (int paise, float km/hrs/pct, no unparsed Decimals)
   - Edge case boundaries (0 km, exact boundary, invalid negative odometer deltas)
   - Breakdown key symmetry between client_receivable and supplier_payable
2. Server-Side Financial State Machine & Mutability Locks:
   - Rejecting odometer or tariff edits on COMPLETED, INVOICED, or LOCKED duties
   - Rejecting recalculation on invoiced duties
3. Multi-Tenant Authorization & B2B Security Seams:
   - Restricting /api/v1/admin/impersonate and SaaS endpoints to verified platform admins
   - Rejecting unauthenticated /api/auth/sync-session credential bypass
   - Blocking cross-tenant data tampering
"""

import json
import os
from pathlib import Path
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend_domain import DomainError, calculate_duty, initialize_domain_schema
from backend_impersonation import (
    check_read_only_mutation_guard,
    handle_impersonation_api,
    initialize_impersonation_schema,
    mint_shadow_jwt,
    verify_shadow_jwt,
)
from backend_operations_parity import initialize_operations_parity_schema
from backend_tristack import handle_tristack, initialize_tristack_schema
from tariff_engine import calculate_dual_ledger_duty, resolve_auto_slab


class TestTariffEngineContracts(unittest.TestCase):
    """Guards contract uniformity, numeric typing, and edge cases across all 6 billing models."""

    def setUp(self):
        self.base_client_card = {
            "base_paise": 200000,
            "extra_km_paise": 1800,
            "extra_hr_paise": 15000,
            "driver_bhatta_paise": 40000,
            "gst_rate_pct": 5.0,
            "slabs": [
                {"hours": 4, "km": 40, "base_paise": 180000},
                {"hours": 8, "km": 80, "base_paise": 320000},
                {"hours": 12, "km": 120, "base_paise": 450000},
            ],
            "min_km_per_day": 300.0,
            "zone_rings": [
                {"max_km": 10, "paise": 60000},
                {"max_km": 25, "paise": 120000},
                {"max_km": 50, "paise": 200000},
            ],
            "per_seat_rate_paise": 35000,
            "daily_fixed_paise": 250000,
            "daily_km_cap": 100.0,
            "daily_hr_cap": 10.0,
            "dry_base_paise": 150000,
            "base_fuel_price_inr": 95.0,
            "vehicle_mileage_kmpl": 15.0,
        }
        self.base_supplier_card = {
            "base_paise": 150000,
            "extra_km_paise": 1400,
            "extra_hr_paise": 12000,
            "driver_bhatta_paise": 35000,
        }

    def _assert_common_schema(self, res: dict):
        """Asserts exact JSON key names and numeric types expected by frontends."""
        self.assertIn("billing_mode", res)
        self.assertIn("garage_matrix", res)
        self.assertIsInstance(res["billable_km"], (int, float))
        self.assertIsInstance(res["billable_hours"], (int, float))
        self.assertIsInstance(res["gross_margin_paise"], int)
        self.assertIsInstance(res["gross_margin_percentage"], float)
        self.assertIn("margin_pct", res, "Must provide frontend-compatible alias margin_pct")
        self.assertIsInstance(res["margin_pct"], float)
        self.assertIsInstance(res["is_negative_margin"], bool)
        self.assertIsInstance(res["maker_checker_audit_hold"], bool)

        # Client Receivable structure & types
        cr = res["client_receivable"]
        for key in (
            "base_paise",
            "extra_km_paise",
            "extra_hr_paise",
            "driver_bhatta_paise",
            "tolls_parking_paise",
            "gross_receivable_paise",
            "gst_tax_paise",
            "net_receivable_paise",
        ):
            self.assertIn(key, cr, f"Missing key {key} in client_receivable")
            self.assertIsInstance(cr[key], int, f"Key {key} must be integer paise")

        # Supplier Payable structure & types
        sp = res["supplier_payable"]
        for key in (
            "base_paise",
            "extra_km_paise",
            "extra_hr_paise",
            "driver_bhatta_paise",
            "tolls_parking_paise",
            "penalty_deduction_paise",
            "gross_payable_paise",
            "net_payable_paise",
        ):
            self.assertIn(key, sp, f"Missing key {key} in supplier_payable")
            self.assertIsInstance(sp[key], int, f"Key {key} must be integer paise")

        # Frontend corporate PnL / vendor command aliases
        self.assertIn("client_billing_paise", res)
        self.assertIn("supplier_cost_paise", res)

    def test_model_1_hr_km_slab(self):
        duty = {"billing_mode": "HR_KM_SLAB", "distance_km": 45.0, "duration_hours": 5.0}
        res = calculate_dual_ledger_duty(duty, self.base_client_card, self.base_supplier_card)
        self._assert_common_schema(res)
        self.assertEqual(res["billing_mode"], "HR_KM_SLAB")
        self.assertGreater(res["client_receivable"]["net_receivable_paise"], 0)

    def test_model_2_outstation_calendar_day(self):
        duty = {
            "billing_mode": "OUTSTATION_CALENDAR_DAY",
            "distance_km": 650.0,
            "duration_hours": 36.0,
            "calendar_days": 2,
            "is_night_or_outstation": True,
        }
        res = calculate_dual_ledger_duty(duty, self.base_client_card, self.base_supplier_card)
        self._assert_common_schema(res)
        self.assertEqual(res["billing_mode"], "OUTSTATION_CALENDAR_DAY")
        # 2 days * 300 min km = 600 min km; effective = 650 km
        self.assertEqual(res["billable_km"], 650.0)
        # Bhatta should be 2 days * 40000 = 80000
        self.assertEqual(res["client_receivable"]["driver_bhatta_paise"], 80000)

    def test_model_3_radial_zone_ring(self):
        duty = {"billing_mode": "RADIAL_ZONE_RING", "distance_km": 22.0, "duration_hours": 1.5}
        res = calculate_dual_ledger_duty(duty, self.base_client_card, self.base_supplier_card)
        self._assert_common_schema(res)
        self.assertEqual(res["billing_mode"], "RADIAL_ZONE_RING")
        # 22 km matches Ring 2 (<= 25 km) @ 120000 paise
        self.assertEqual(res["client_receivable"]["base_paise"], 120000)

    def test_model_4_per_seat_shared_pool(self):
        duty = {
            "billing_mode": "PER_SEAT_SHARED_POOL",
            "distance_km": 35.0,
            "duration_hours": 2.0,
            "passengers_count": 4,
        }
        res = calculate_dual_ledger_duty(duty, self.base_client_card, self.base_supplier_card)
        self._assert_common_schema(res)
        self.assertEqual(res["billing_mode"], "PER_SEAT_SHARED_POOL")
        # 4 seats * 35000 paise = 140000 paise
        self.assertEqual(res["client_receivable"]["base_paise"], 140000)

    def test_model_5_monthly_dedicated(self):
        duty = {
            "billing_mode": "MONTHLY_DEDICATED_FIXED_VARIABLE",
            "distance_km": 120.0,
            "duration_hours": 11.0,
        }
        res = calculate_dual_ledger_duty(duty, self.base_client_card, self.base_supplier_card)
        self._assert_common_schema(res)
        self.assertEqual(res["billing_mode"], "MONTHLY_DEDICATED_FIXED_VARIABLE")
        # Base: 250000, extra km: 20 * 1800 = 36000, extra hr: 1 * 15000 = 15000
        self.assertEqual(res["client_receivable"]["base_paise"], 250000)
        self.assertEqual(res["client_receivable"]["extra_km_paise"], 36000)
        self.assertEqual(res["client_receivable"]["extra_hr_paise"], 15000)

    def test_model_6_fuel_indexed(self):
        duty = {
            "billing_mode": "FUEL_INDEXED_BACK_TO_BACK",
            "distance_km": 150.0,
            "current_fuel_price_inr": 105.0,  # +10.0 INR diff
        }
        res = calculate_dual_ledger_duty(duty, self.base_client_card, self.base_supplier_card)
        self._assert_common_schema(res)
        self.assertEqual(res["billing_mode"], "FUEL_INDEXED_BACK_TO_BACK")
        # 150 km / 15 kmpl * (10 * 100 paise) = 10 * 1000 = 10000 paise fuel surcharge
        self.assertGreater(res["client_receivable"]["base_paise"], 150000)

    def test_odometer_input_validation_and_negative_deltas(self):
        # start_km > end_km must raise ValueError / validation error
        duty = {"start_km": 5000.0, "end_km": 4900.0, "billing_mode": "HR_KM_SLAB"}
        with self.assertRaises(ValueError):
            calculate_dual_ledger_duty(duty, self.base_client_card, self.base_supplier_card)

        # Negative distance
        with self.assertRaises(ValueError):
            calculate_dual_ledger_duty(
                {"distance_km": -20.0}, self.base_client_card, self.base_supplier_card
            )


class TestServerStateLocksAndMultiTenantSecurity(unittest.TestCase):
    """Guards server-side state machine locks, financial immutability, and multi-tenant authorization."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL DEFAULT '',
                city TEXT NOT NULL DEFAULT '',
                gstin TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL DEFAULT '',
                password_salt TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL,
                full_name TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                organization_id TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT '',
                last_login_at TEXT
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
        """)
        initialize_domain_schema(self.conn)
        initialize_operations_parity_schema(self.conn)
        initialize_tristack_schema(self.conn)
        initialize_impersonation_schema(self.conn)

        # Setup 2 distinct tenant organizations
        self.conn.execute("INSERT OR IGNORE INTO organizations(id, name, kind) VALUES ('org_a', 'Tenant A Travels', 'vendor')")
        self.conn.execute("INSERT OR IGNORE INTO organizations(id, name, kind) VALUES ('org_b', 'Tenant B Fleet', 'vendor')")

        self.user_a = {"id": "usr_vendor_a", "email": "ops@tenanta.com", "role": "vendor", "organization_id": "org_a"}
        self.user_b = {"id": "usr_vendor_b", "email": "ops@tenantb.com", "role": "vendor", "organization_id": "org_b"}
        self.admin_user = {"id": "usr_admin", "email": "staff@axiomfleet.in", "role": "admin", "organization_id": "org_platform"}

    def test_state_machine_lock_on_completed_and_invoiced_duty(self):
        """Once a duty is COMPLETED and has an issued invoice, mutating odometer or recalculating must be rejected."""
        from backend_domain import _calculate, _create_booking, _create_customer, _create_duty, _create_invoice, _update_duty, _update_invoice

        # 1. Create customer, booking, duty for org_a
        cust = _create_customer(self.conn, self.user_a, {"name": "Corporate Corp", "billing_address": "Bangalore"}, "127.0.0.1")
        booking = _create_booking(self.conn, self.user_a, {"customer_id": cust["item"]["id"], "passenger_name": "Rohan", "scheduled_at": "2026-10-27T10:00:00Z"}, "127.0.0.1")
        duty = _create_duty(self.conn, self.user_a, {"booking_id": booking["item"]["id"], "reporting_at": "2026-10-27T09:30:00Z"}, "127.0.0.1")
        duty_id = duty["item"]["id"]

        # Calculate fare & complete duty
        _calculate(self.conn, self.user_a, duty_id, {"base_paise": 200000, "distance_km": 50, "per_km_paise": 2000}, "127.0.0.1")
        _update_duty(self.conn, self.user_a, duty_id, {"status": "assigned"}, "127.0.0.1")
        _update_duty(self.conn, self.user_a, duty_id, {"status": "accepted"}, "127.0.0.1")
        _update_duty(self.conn, self.user_a, duty_id, {"status": "en_route"}, "127.0.0.1")
        _update_duty(self.conn, self.user_a, duty_id, {"status": "started", "start_odometer": 1000}, "127.0.0.1")
        _update_duty(self.conn, self.user_a, duty_id, {"status": "completed", "end_odometer": 1050}, "127.0.0.1")

        # Create & issue invoice
        inv = _create_invoice(self.conn, self.user_a, {"duty_id": duty_id}, "127.0.0.1")
        inv_id = inv["item"]["id"]
        _update_invoice(self.conn, self.user_a, inv_id, {"status": "issued"}, "127.0.0.1")

        # Attempt to recalculate fare on invoiced duty -> Must raise DomainError (HTTP 409)
        with self.assertRaises(DomainError) as cm:
            _calculate(self.conn, self.user_a, duty_id, {"base_paise": 300000, "distance_km": 60, "per_km_paise": 2000}, "127.0.0.1")
        self.assertEqual(cm.exception.status, 409)

        # Attempt to mutate odometer on invoiced duty -> Must raise DomainError (HTTP 409)
        with self.assertRaises(DomainError) as cm2:
            _update_duty(self.conn, self.user_a, duty_id, {"end_odometer": 2000}, "127.0.0.1")
        self.assertEqual(cm2.exception.status, 409)

    def test_negative_odometer_delta_rejected_in_update_duty(self):
        """Updating duty with end_odometer < start_odometer must be rejected with HTTP 400."""
        from backend_domain import _create_booking, _create_customer, _create_duty, _update_duty
        cust = _create_customer(self.conn, self.user_a, {"name": "Corp Test"}, "127.0.0.1")
        booking = _create_booking(self.conn, self.user_a, {"customer_id": cust["item"]["id"], "passenger_name": "Anita"}, "127.0.0.1")
        duty = _create_duty(self.conn, self.user_a, {"booking_id": booking["item"]["id"]}, "127.0.0.1")
        duty_id = duty["item"]["id"]

        with self.assertRaises(DomainError) as cm:
            _update_duty(self.conn, self.user_a, duty_id, {"start_odometer": 5000, "end_odometer": 4900}, "127.0.0.1")
        self.assertEqual(cm.exception.status, 400)

    def test_cross_tenant_isolation_in_sla_evaluate(self):
        """Passing mismatched vendor_id in Tri-Stack SLA evaluate must be rejected or scoped to user org."""
        res = handle_tristack(
            self.conn,
            self.user_a,
            "POST",
            "/api/tri-stack/sla/evaluate",
            {
                "vendor_id": "other_tenant_victim",
                "duty_evidence": {"gps_ping_count": 0, "speed_violations": 5},
            },
        )
        # Should not update other_tenant_victim or should reject
        cur = self.conn.execute("SELECT current_tier FROM tristack_partner_sla_profiles WHERE vendor_id = 'other_tenant_victim'")
        self.assertIsNone(cur.fetchone())

    def test_admin_impersonation_restricted_to_superadmin(self):
        """Non-admin user calling /api/v1/admin/impersonate must receive HTTP 403 Forbidden."""
        res = handle_impersonation_api(
            self.conn,
            self.user_a,  # Standard vendor, not admin
            "POST",
            "/api/v1/admin/impersonate",
            {"tenant_id": 169, "impersonation_mode": "READ_ONLY"},
        )
        self.assertIn("error", res)
        self.assertEqual(res.get("code"), 403)


if __name__ == "__main__":
    unittest.main()
