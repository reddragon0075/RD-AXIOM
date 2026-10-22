"""Smoke and regression test for Gap 1 (Multi-Brand Legal Entities) and Gap 4 (Visual Rate Card Copy Tool)."""

import os
import sqlite3
import unittest
from backend_legal_entities import handle_legal_entities, initialize_legal_entities_schema
from backend_fare import handle_fare, initialize_fare_schema


class TestGaps1And4(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        # Setup tables
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                metadata_json TEXT,
                ip_address TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL DEFAULT 'vendor',
                name TEXT NOT NULL,
                phone TEXT DEFAULT '',
                city TEXT DEFAULT 'Mumbai',
                gstin TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO organizations (id, kind, name, created_at)
            VALUES ('org_v1', 'vendor', 'Apex Travels Pvt Ltd', '2026-01-01T00:00:00Z')
            """
        )
        initialize_legal_entities_schema(self.conn)
        initialize_fare_schema(self.conn)

        self.user_vendor = {
            "id": "usr_v1",
            "role": "vendor",
            "organization_id": "org_v1",
            "email": "owner@apex.in",
        }

    def tearDown(self):
        self.conn.close()

    def test_multi_brand_legal_entities(self):
        # 1. Create Brand A (Apex Luxury)
        payload_a = {
            "brand_name": "Apex Luxury",
            "legal_name": "Apex Travels Pvt Ltd",
            "gstin": "27AAAAA0000A1Z5",
            "pan": "AAAAA0000A",
            "state_code": "27",
            "address": "Terminal 2, Mumbai Airport",
            "city": "Mumbai",
            "pincode": "400099",
            "bank_name": "HDFC Bank",
            "account_number": "50200012345678",
            "ifsc_code": "HDFC0000123",
            "upi_id": "apex@hdfcbank",
            "invoice_prefix": "APX/LUX/",
            "next_invoice_number": 1001,
            "is_default": True,
        }
        res_a = handle_legal_entities(self.conn, self.user_vendor, "POST", "/api/legal-entities", payload_a, "127.0.0.1")
        self.assertTrue(res_a["ok"])
        entity_a_id = res_a["item"]["id"]
        self.assertEqual(res_a["item"]["brand_name"], "Apex Luxury")
        self.assertEqual(res_a["item"]["is_default"], 1)

        # 2. Create Brand B (Budget Cabs)
        payload_b = {
            "brand_name": "Budget Cabs",
            "legal_name": "Apex Budget Mobility LLP",
            "gstin": "29BBBBB1111B1Z6",
            "invoice_prefix": "BGT/KA/",
            "next_invoice_number": 500,
            "is_default": False,
        }
        res_b = handle_legal_entities(self.conn, self.user_vendor, "POST", "/api/legal-entities", payload_b, "127.0.0.1")
        self.assertTrue(res_b["ok"])
        entity_b_id = res_b["item"]["id"]

        # 3. List entities (includes auto-seeded primary entity + 2 newly added brands)
        list_res = handle_legal_entities(self.conn, self.user_vendor, "GET", "/api/legal-entities", {}, "127.0.0.1")
        self.assertTrue(list_res["ok"])
        self.assertEqual(len(list_res["items"]), 3)

        # 4. Generate sequential invoice numbers for Brand A & Brand B
        num_a1 = handle_legal_entities(self.conn, self.user_vendor, "POST", f"/api/legal-entities/{entity_a_id}/next-invoice-number", {}, "127.0.0.1")
        self.assertEqual(num_a1["invoice_number"], "APX/LUX/1001")
        num_a2 = handle_legal_entities(self.conn, self.user_vendor, "POST", f"/api/legal-entities/{entity_a_id}/next-invoice-number", {}, "127.0.0.1")
        self.assertEqual(num_a2["invoice_number"], "APX/LUX/1002")

        num_b1 = handle_legal_entities(self.conn, self.user_vendor, "POST", f"/api/legal-entities/{entity_b_id}/next-invoice-number", {}, "127.0.0.1")
        self.assertEqual(num_b1["invoice_number"], "BGT/KA/500")

        # 5. Set Brand B as default
        def_res = handle_legal_entities(self.conn, self.user_vendor, "POST", f"/api/legal-entities/{entity_b_id}/set-default", {}, "127.0.0.1")
        self.assertTrue(def_res["ok"])
        self.assertEqual(def_res["default_entity_id"], entity_b_id)

        # Verify Brand A is no longer default
        row_a = self.conn.execute("SELECT is_default FROM domain_legal_entities WHERE id = ?", (entity_a_id,)).fetchone()
        self.assertEqual(row_a["is_default"], 0)

    def test_rate_card_copy_tool(self):
        # 1. Create base tariff rule for Mumbai
        rule_payload = {
            "city_id": "Mumbai",
            "vehicle_group_id": "SEDAN",
            "fare_mode": "local",
            "package_name": "8Hr 80Km",
            "package_minutes": 480,
            "included_km": 80,
            "base_paise": 2000_00,       # Rs 2,000
            "extra_km_paise": 15_00,     # Rs 15/km
            "extra_hour_paise": 150_00,  # Rs 150/hr
            "driver_allowance_day_paise": 300_00,
        }
        res_create = handle_fare(self.conn, self.user_vendor, "POST", "/api/fare/rules", rule_payload, "127.0.0.1")
        self.assertTrue(res_create["ok"])

        # 2. Bulk copy Mumbai -> Pune with +15% markup
        copy_payload = {
            "source_city_id": "Mumbai",
            "target_city_id": "Pune",
            "markup_pct": 15.0,
            "overwrite": True,
        }
        res_copy = handle_fare(self.conn, self.user_vendor, "POST", "/api/fare/rules/copy", copy_payload, "127.0.0.1")
        self.assertTrue(res_copy["ok"])
        self.assertEqual(res_copy["copied_count"], 1)

        # 3. Verify Pune rate card in database has +15% rates
        pune_row = self.conn.execute(
            "SELECT * FROM domain_tariff_rules WHERE organization_id = 'org_v1' AND city_id = 'Pune'",
        ).fetchone()
        self.assertIsNotNone(pune_row)
        # 2000 * 1.15 = 2300
        self.assertEqual(pune_row["base_paise"], 2300_00)
        # 15 * 1.15 = 17.25 -> 1725 paise
        self.assertEqual(pune_row["extra_km_paise"], 1725)
        # 300 * 1.15 = 345
        self.assertEqual(pune_row["driver_allowance_day_paise"], 345_00)


if __name__ == "__main__":
    unittest.main()
