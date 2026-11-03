"""Axiom Mobility (Fleetline) - Growth, Automation & Onboarding Verification Suite.

Executes tests covering:
1. "Parse AI" Unstructured Booking Extraction & OSM Rate Estimation:
   Regex/heuristic extraction from WhatsApp/email strings, resolving relative datetime,
   OpenStreetMap road geocoding & theoretical fare calculations.
2. Prospect Capture CRM & 1-Click Tenant Onboarding:
   Public prospect lead capture, deduplication by mobile/email, sales call logging,
   and 1-click conversion to live tenant with 14-day / 100-trip trial and rate card seeding.
3. Automated SaaS Dunning, Payout Hold & 3-Stage Killswitch:
   Platform invoice balance calculation, Soft-Lock auto-engaging Payout Hold ('FORCE_HOLD'),
   and Hard-Block throwing HTTP 402 on operational endpoints.
4. Zero-Login Corporate Proforma Review & Maker-Checker Dispute Routing:
   Generating secure share link, viewing duty slip proofs, 1-click batch approving duties,
   and auto-routing disputed items directly to Billing Maker-Checker queue.
"""

from pathlib import Path
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
MVP_PATH = ROOT / "fleetline-mvp"
if str(MVP_PATH) not in sys.path:
    sys.path.insert(0, str(MVP_PATH))

from backend_domain import DomainError, initialize_domain_schema
from backend_treasury_release import initialize_treasury_release_schema
from backend_practical_pricing import initialize_practical_pricing_schema
from backend_osm_spatial import initialize_osm_spatial_schema
from backend_completed_trips_importer import initialize_bulk_importer_schema
from backend_commercial import check_tenant_killswitch, initialize_commercial_schema
from backend.booking_ai_parser import (
    parse_unstructured_booking,
    parse_relative_datetime,
    handle_booking_ai_parser_api,
)
from backend.prospect_crm_service import (
    initialize_prospect_crm_schema,
    capture_public_prospect,
    list_prospects,
    add_prospect_note,
    convert_prospect_to_tenant,
    get_tenant_billing_overview,
    create_tenant_platform_invoice,
    update_tenant_access_control,
    generate_proforma_share_link,
    get_corporate_review_data,
    decide_corporate_review,
    handle_prospect_crm_api,
)


class TestGrowthAndAutomation(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = OFF")

        # Base tables
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT,
                kind TEXT DEFAULT 'vendor',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tenant_billing_accounts (
                tenant_id TEXT PRIMARY KEY,
                tenant_name TEXT NOT NULL,
                account_status TEXT NOT NULL DEFAULT 'ACTIVE',
                access_control_state TEXT NOT NULL DEFAULT 'ACTIVE_GOOD_STANDING',
                saas_balance_owed_inr REAL NOT NULL DEFAULT 0.0,
                outstanding_balance_paise INTEGER NOT NULL DEFAULT 0,
                dunning_stage INTEGER NOT NULL DEFAULT 0,
                trial_ends_at TEXT,
                trial_trips_quota INTEGER DEFAULT 100,
                payout_hold_override TEXT DEFAULT 'RELEASE_READY',
                block_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS domain_price_book_items (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                vehicle_category TEXT NOT NULL,
                duty_type TEXT NOT NULL,
                base_fare REAL NOT NULL,
                per_km_rate REAL NOT NULL,
                per_minute_rate REAL NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS duties (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                proforma_id TEXT,
                booking_id TEXT,
                duty_date TEXT,
                vehicle_category TEXT,
                passenger_name TEXT,
                route_name TEXT,
                practical_billable_km REAL,
                practical_start_km REAL,
                practical_end_km REAL,
                practical_duration_mins INTEGER,
                estimated_distance_km REAL,
                final_client_fare_inr REAL,
                estimated_client_fare_inr REAL,
                closing_source TEXT,
                has_discrepancy INTEGER DEFAULT 0,
                discrepancy_reason TEXT,
                physical_tripsheet_file_url TEXT
            );

            CREATE TABLE IF NOT EXISTS audit_events (
                id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                action TEXT NOT NULL,
                details_json TEXT,
                created_at TEXT NOT NULL
            );
        """)

        # Initialize schemas
        initialize_osm_spatial_schema(self.conn)
        initialize_prospect_crm_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_01_parse_ai_intake_extraction_and_theoretical_estimate(self):
        """Scenario 1: Parse AI accurately extracts fields and computes theoretical estimates."""
        raw_msg = (
            "Please book a sedan for Rohan Deshmukh (9845012345, rohan.d@infosys.com) "
            "tomorrow 6:30 AM from Koramangala 4th Block to BLR Kempegowda Airport for flight 6E-204. Need clean cab."
        )

        user = {"id": "usr_ops", "organization_id": "org_test"}
        res = handle_booking_ai_parser_api(self.conn, user, "POST", "/api/v1/bookings/parse-unstructured", {"raw_text": raw_msg})

        self.assertIsNotNone(res)
        self.assertEqual(res["passenger_name"], "Rohan Deshmukh")
        self.assertEqual(res["passenger_phone"], "9845012345")
        self.assertEqual(res["passenger_email"], "rohan.d@infosys.com")
        self.assertEqual(res["flight_number"], "6E-204")
        self.assertIn(res["duty_type"], {"AIRPORT_DROP", "AIRPORT_TRANSFER"})
        self.assertEqual(res["vehicle_category_hint"], "SEDAN")
        self.assertIn("Koramangala", res["pickup_address_raw"])
        self.assertIn("Airport", res["drop_address_raw"])
        self.assertGreaterEqual(res["confidence"], 0.8)
        self.assertGreater(res["estimated_distance_km"], 0)
        self.assertGreater(res["estimated_client_fare_inr"], 0)
        self.assertGreater(res["estimated_supplier_payout_inr"], 0)

    def test_02_prospect_capture_crm_and_one_click_tenant_conversion(self):
        """Scenario 2: Capture lead, deduplicate, log sales notes, and convert to tenant in 1 click."""
        lead_payload = {
            "full_name": "Siddharth Verma",
            "company_name": "Verma Premium Fleet Services",
            "mobile_number": "9811223344",
            "email_id": "siddharth@vermafleet.in",
            "city": "Bengaluru",
            "fleet_size_estimate": 25,
            "interest_type": "VENDOR_SAAS",
        }

        # 1. Capture public lead
        lead_res = capture_public_prospect(self.conn, lead_payload)
        self.assertTrue(lead_res["success"])
        self.assertFalse(lead_res["deduplicated"])
        prospect_id = lead_res["prospect_id"]

        # 2. Duplicate submission updates rather than inserting duplicates
        dup_res = capture_public_prospect(self.conn, lead_payload)
        self.assertTrue(dup_res["success"])
        self.assertTrue(dup_res["deduplicated"])
        self.assertEqual(dup_res["prospect_id"], prospect_id)

        # 3. Add sales call note
        note_res = add_prospect_note(self.conn, prospect_id, "Customer evaluated legacy software; wants 14-day trial for 25 cabs.", "Sales Lead")
        self.assertTrue(note_res["success"])
        self.assertEqual(note_res["status"], "CONTACTED_QUERYING")
        self.assertEqual(len(note_res["notes"]), 1)

        # 4. 1-Click Convert to Tenant
        conv_res = convert_prospect_to_tenant(self.conn, prospect_id)
        self.assertTrue(conv_res["success"])
        tenant_id = conv_res["tenant_id"]
        self.assertEqual(conv_res["trial_trips_quota"], 100)
        self.assertIsNotNone(conv_res["trial_ends_at"])
        self.assertEqual(conv_res["access_control_state"], "ACTIVE_GOOD_STANDING")

        # Verify rate cards were auto-seeded for this new tenant
        rate_cards = self.conn.execute("SELECT * FROM domain_price_book_items WHERE organization_id = ?", (tenant_id,)).fetchall()
        self.assertGreaterEqual(len(rate_cards), 4)

        # Verify prospect status updated
        p_row = self.conn.execute("SELECT status, converted_tenant_id FROM sales_prospects WHERE id = ?", (prospect_id,)).fetchone()
        self.assertEqual(p_row["status"], "ONBOARDED_CONVERTED")
        self.assertEqual(p_row["converted_tenant_id"], tenant_id)

    def test_03_automated_saas_dunning_payout_hold_and_3stage_killswitch(self):
        """Scenario 3: SaaS platform invoice creation, Soft-Lock payout hold, and Hard-Block 402."""
        tenant_id = "org_vendor_delinquent"
        self.conn.execute(
            """INSERT INTO tenant_billing_accounts (
                tenant_id, tenant_name, account_status, access_control_state, saas_balance_owed_inr, payout_hold_override, created_at, updated_at
            ) VALUES (?, 'Delinquent Fleet', 'ACTIVE', 'ACTIVE_GOOD_STANDING', 0.0, 'RELEASE_READY', '2026-11-01', '2026-11-01')""",
            (tenant_id,),
        )

        # 1. Create overdue SaaS invoice of ₹15,000
        inv_payload = {
            "saas_base_fee_inr": 12000.0,
            "trip_overage_fee_inr": 3000.0,
            "billing_period": "Oct 2026",
            "due_date": "2026-10-31",
        }
        inv_res = create_tenant_platform_invoice(self.conn, tenant_id, inv_payload)
        self.assertTrue(inv_res["success"])
        self.assertEqual(inv_res["total_amount_due_inr"], 15000.0)

        overview = get_tenant_billing_overview(self.conn, tenant_id)
        self.assertEqual(overview["saas_balance_owed_inr"], 15000.0)

        # 2. Stage 1: Engage Soft-Lock (Must auto-set payout_hold_override = 'FORCE_HOLD')
        soft_res = update_tenant_access_control(self.conn, tenant_id, "SOFT_LOCKED_OVERDUE", "Grace period expired")
        self.assertTrue(soft_res["success"])
        self.assertEqual(soft_res["access_control_state"], "SOFT_LOCKED_OVERDUE")
        self.assertEqual(soft_res["account_status"], "SOFT_BLOCKED")
        self.assertEqual(soft_res["payout_hold_override"], "FORCE_HOLD")

        # Check that Soft-Lock blocks new booking creations with 402
        with self.assertRaises(DomainError) as ctx:
            check_tenant_killswitch(self.conn, tenant_id, "POST", "/api/v1/bookings")
        self.assertEqual(ctx.exception.status, 402)
        self.assertEqual(ctx.exception.code, "TENANT_BLOCKED_NON_PAYMENT")

        # But existing duty updates or telemetry reads are permitted
        try:
            check_tenant_killswitch(self.conn, tenant_id, "GET", "/api/v1/duties/DUTY-101")
            check_tenant_killswitch(self.conn, tenant_id, "POST", "/api/v1/duties/DUTY-101/close-practical")
        except DomainError:
            self.fail("Duty closing should be allowed during soft-lock")

        # 3. Stage 2: Engage Hard-Block (Must block all mutations with 402)
        hard_res = update_tenant_access_control(self.conn, tenant_id, "HARD_BLOCKED_NON_PAYMENT", "Account suspended for non-payment")
        self.assertTrue(hard_res["success"])
        self.assertEqual(hard_res["access_control_state"], "HARD_BLOCKED_NON_PAYMENT")

        with self.assertRaises(DomainError) as ctx_hard:
            check_tenant_killswitch(self.conn, tenant_id, "POST", "/api/v1/duties/DUTY-101/close-practical")
        self.assertEqual(ctx_hard.exception.status, 402)

    def test_04_zero_login_corporate_annexure_review_and_dispute_routing(self):
        """Scenario 4: Corporate review link, duty-slip verification, and line-item dispute routing."""
        proforma_id = "PROF-2026-901"
        tenant_id = "org_vendor_blue"
        corp_name = "Wipro Enterprise Services"

        # Seed sample duties for this proforma
        self.conn.executescript(f"""
            INSERT INTO duties (id, organization_id, proforma_id, duty_date, vehicle_category, passenger_name, route_name, practical_billable_km, estimated_distance_km, final_client_fare_inr, physical_tripsheet_file_url)
            VALUES
            ('D-801', '{tenant_id}', '{proforma_id}', '2026-11-01', 'SEDAN', 'Amit Roy', 'Koramangala to Electronic City', 24.0, 23.5, 950.00, 'https://storage.axiom/slip_801.png'),
            ('D-802', '{tenant_id}', '{proforma_id}', '2026-11-01', 'SEDAN', 'Neha Sen', 'Whitefield to BLR Airport', 48.0, 47.0, 1950.00, 'https://storage.axiom/slip_802.png'),
            ('D-803', '{tenant_id}', '{proforma_id}', '2026-11-02', 'SUV_CRYSTA', 'Rakesh Pillai', 'Indiranagar to MG Road', 18.0, 10.0, 1200.00, 'https://storage.axiom/slip_803.png');
        """)

        # 1. Generate magic share token
        share_res = generate_proforma_share_link(self.conn, proforma_id, tenant_id, corp_name, "finance@wipro.com")
        self.assertTrue(share_res["success"])
        token = share_res["token"]
        self.assertIn(f"/billing/corporate-review/{token}", share_res["share_url"])

        # 2. Corporate reviewer accesses zero-login review data
        review_data = get_corporate_review_data(self.conn, token)
        self.assertEqual(review_data["proforma_id"], proforma_id)
        self.assertEqual(review_data["corporate_name"], corp_name)
        self.assertEqual(len(review_data["duties"]), 3)

        # 3. Corporate submits batch decision: Approve 2 duties, Flag 1 duty for dispute
        decision_payload = {
            "approved_duty_ids": ["D-801", "D-802"],
            "flagged_duties": [
                {
                    "duty_id": "D-803",
                    "dispute_reason": "Meter indicates 18km but Google Maps shows 10km direct route.",
                    "proposed_km": 10.0,
                }
            ],
        }
        dec_res = decide_corporate_review(self.conn, token, decision_payload)
        self.assertTrue(dec_res["success"])
        self.assertEqual(dec_res["approved_count"], 2)
        self.assertEqual(dec_res["flagged_count"], 1)
        self.assertEqual(dec_res["status"], "PARTIALLY_APPROVED")

        # 4. Verify disputed item was routed directly to Billing Maker-Checker audit queue
        audit_row = self.conn.execute("SELECT * FROM audit_events WHERE entity_id = 'D-803'").fetchone()
        self.assertIsNotNone(audit_row)
        self.assertEqual(audit_row["action"], "FLAGGED_BY_CORPORATE")
        self.assertIn("Meter indicates 18km", audit_row["details_json"])


if __name__ == "__main__":
    unittest.main()
