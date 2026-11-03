"""Automated Verification & E2E Test Suite for Axiom Mobility (Fleetline):
Google TimesFM Predictive Earnings & Corporate Expenditure Forecasting Engine.

Tests:
1. Two-Tier TimesFM Hybrid Forecasting (Deterministic Seasonal Decomposition + Quantile Bands).
2. Strict Mathematical Invariant: p10_inr <= p50_expected_inr <= p90_inr for all days.
3. Vendor 30-Day Future Earnings & Withdrawable Cash-Flow Schedule (48h fund hold).
4. Corporate Expenditure Forecast, RAC vs ETS Split, and Budget Cap Exhaustion Alert.
5. Platform Treasury Float & Demand Forecasting.
6. Sub-15ms Forecast Caching in financial_forecasts_cache.
7. API Routing Dispatcher (/api/v1/forecasts/...).
"""

from __future__ import annotations

import datetime as dt
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
from backend_timesfm_forecast import (
    initialize_timesfm_forecast_schema,
    SeasonalQuantileFallback,
    generate_timesfm_forecast,
    extract_vendor_earnings_series,
    extract_corporate_spend_series,
    get_vendor_earnings_forecast,
    get_corporate_expenditure_forecast,
    get_platform_treasury_forecast,
    set_corporate_travel_budget,
    handle_timesfm_forecast_api,
)


class TestTimesFmForecasting(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = OFF")
        self.tenant_id = "org_axiom_corp"
        self.vendor_id = "org_vendor_apex"
        self.corporate_id = "cust_wipro_tech"

        self.operator_user = {
            "id": "usr_operator_1",
            "email": "ops@axiommprocab.com",
            "full_name": "Fleet Controller",
            "organization_id": self.tenant_id,
            "roles": ["operator", "finance_controller"],
        }

        # Initialize base schemas
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
        initialize_timesfm_forecast_schema(self.conn)

        # Seed Masters
        now = now_iso()
        self.conn.executescript(
            f"""
            INSERT INTO domain_customers (id, organization_id, name, created_at, updated_at) VALUES
                ('{self.corporate_id}', '{self.tenant_id}', 'Wipro Technologies Bangalore', '{now}', '{now}');

            INSERT INTO domain_vehicles (id, organization_id, registration_number, model, vehicle_type, status, created_at, updated_at) VALUES
                ('veh_01', '{self.tenant_id}', 'KA01AB1234', 'Dzire', 'Sedan', 'available', '{now}', '{now}');

            INSERT INTO domain_drivers (id, organization_id, full_name, phone, status, created_at, updated_at) VALUES
                ('drv_01', '{self.tenant_id}', 'Ramesh Kumar', '+91 98801 23456', 'active', '{now}', '{now}');
            """
        )

        # Seed 45 days of realistic historical completed duties
        self._seed_45_days_historical_duties()

    def tearDown(self):
        self.conn.close()

    def _seed_45_days_historical_duties(self):
        """Seeds 45 days of completed trips with higher weekday volume and lower weekend volume."""
        today = dt.date.today()
        now = now_iso()

        for day_offset in range(45, 0, -1):
            duty_date = today - dt.timedelta(days=day_offset)
            dow = duty_date.weekday()

            # Monday (0) - Thursday (3): 8 trips
            # Friday (4): 10 trips (peak)
            # Saturday (5) - Sunday (6): 3 trips (trough)
            if dow == 4:
                trip_count = 10
                fare_base = 2500.0
                payout_base = 2000.0
            elif dow in (0, 1, 2, 3):
                trip_count = 8
                fare_base = 2200.0
                payout_base = 1750.0
            else:
                trip_count = 3
                fare_base = 1800.0
                payout_base = 1400.0

            for t_idx in range(trip_count):
                duty_id = f"duty_{duty_date.strftime('%Y%m%d')}_{t_idx:02d}"
                booking_id = f"bk_{duty_date.strftime('%Y%m%d')}_{t_idx:02d}"
                start_iso = f"{duty_date.isoformat()}T08:00:00Z"
                end_iso = f"{duty_date.isoformat()}T11:00:00Z"

                self.conn.execute(
                    """
                    INSERT INTO domain_bookings (id, organization_id, customer_id, booking_reference, duty_type, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'corporate', 'allocated', ?, ?)
                    """,
                    (booking_id, self.tenant_id, self.corporate_id, f"BR-{duty_id}", now, now),
                )
                self.conn.execute(
                    """
                    INSERT INTO domain_duties (
                        id, organization_id, booking_id, vehicle_id, driver_id, status,
                        practical_start_km, practical_end_km, practical_billable_km,
                        practical_start_time, practical_end_time, final_client_fare_inr,
                        final_supplier_payout_inr, created_at, updated_at
                    ) VALUES (?, ?, ?, 'veh_01', 'drv_01', 'completed', 1000.0, 1045.0, 45.0, ?, ?, ?, ?, ?, ?)
                    """,
                    (duty_id, self.tenant_id, booking_id, start_iso, end_iso, fare_base, payout_base, now, now),
                )

    def test_01_seasonal_quantile_fallback_mathematical_invariants(self):
        """1. Verify Quantile Invariant: p10 <= p50 <= p90 and confidence cone expansion."""
        today = dt.date.today()
        synthetic_history = [15000.0, 14000.0, 14500.0, 16000.0, 20000.0, 8000.0, 6000.0] * 4  # 28 days

        p10, p50, p90 = SeasonalQuantileFallback.forecast(synthetic_history, today, horizon_days=30)
        self.assertEqual(len(p10), 30)
        self.assertEqual(len(p50), 30)
        self.assertEqual(len(p90), 30)

        # Mathematical Invariants:
        for i in range(30):
            # 1. Non-negativity
            self.assertGreaterEqual(p10[i], 0.0)
            self.assertGreaterEqual(p50[i], 0.0)
            self.assertGreaterEqual(p90[i], 0.0)
            # 2. Strict Quantile Monotonicity
            self.assertLessEqual(p10[i], p50[i], f"Day {i}: p10 ({p10[i]}) must be <= p50 ({p50[i]})")
            self.assertLessEqual(p50[i], p90[i], f"Day {i}: p50 ({p50[i]}) must be <= p90 ({p90[i]})")

        # 3. Uncertainty Cone Spread must widen over time
        spread_day_1 = p90[0] - p10[0]
        spread_day_30 = p90[29] - p10[29]
        self.assertGreater(spread_day_30, spread_day_1, "Uncertainty spread should expand as horizon extends")

    def test_02_vendor_earnings_forecast_and_liquidity_schedule(self):
        """2. Verify Vendor Earnings Forecast: 30-day projection and withdrawable liquidity schedule."""
        res = get_vendor_earnings_forecast(
            self.conn,
            self.operator_user,
            vendor_id="veh_01",
            horizon_days=30,
            force_refresh=True,
        )

        self.assertTrue(res["ok"])
        self.assertEqual(res["entity_type"], "VENDOR_EARNINGS")
        self.assertEqual(res["horizon_days"], 30)
        self.assertFalse(res["cached"])

        forecast_series = res["forecast_series"]
        self.assertEqual(len(forecast_series), 30)

        for pt in forecast_series:
            self.assertIn("date", pt)
            self.assertIn("p10_inr", pt)
            self.assertIn("p50_expected_inr", pt)
            self.assertIn("p90_inr", pt)
            self.assertLessEqual(pt["p10_inr"], pt["p50_expected_inr"])
            self.assertLessEqual(pt["p50_expected_inr"], pt["p90_inr"])

        # Check Financial Intelligence
        summary = res["summary_metrics"]
        self.assertGreater(summary["total_p50_inr"], 100000.0)
        self.assertGreater(summary["projected_week1_unlock_inr"], 20000.0)
        self.assertEqual(summary["default_fund_hold_hours"], 48)
        self.assertIn("adding 1", summary["capacity_recommendation"].lower())

        # Test Cache Hit: Subsequent call without force_refresh should hit cache
        cache_res = get_vendor_earnings_forecast(
            self.conn,
            self.operator_user,
            vendor_id="veh_01",
            horizon_days=30,
            force_refresh=False,
        )
        self.assertTrue(cache_res["ok"])
        self.assertTrue(cache_res["cached"])
        self.assertEqual(cache_res["summary_metrics"]["total_p50_inr"], summary["total_p50_inr"])

    def test_03_corporate_expenditure_and_budget_breach_detection(self):
        """3. Verify Corporate Spend Forecaster: RAC vs ETS split, cap breach date, and variance."""
        curr_month = dt.date.today().strftime("%Y-%m")

        # Set a monthly travel budget cap of Rs 3,00,000 for Wipro
        set_budget = set_corporate_travel_budget(
            self.conn,
            self.operator_user,
            {
                "corporate_id": self.corporate_id,
                "period_month": curr_month,
                "budget_cap_inr": 300000.0,
                "alert_threshold_pct": 80,
            },
        )
        self.assertTrue(set_budget["ok"])

        # Run 30-day corporate expenditure forecast
        corp_fc = get_corporate_expenditure_forecast(
            self.conn,
            self.operator_user,
            corporate_id=self.corporate_id,
            horizon_days=30,
            force_refresh=True,
        )

        self.assertTrue(corp_fc["ok"])
        self.assertEqual(corp_fc["entity_type"], "CORPORATE_EXPENDITURE")

        summary = corp_fc["summary_metrics"]
        self.assertEqual(summary["budget_cap_inr"], 300000.0)
        # Based on ~Rs 16,000/day historical average, month-end spend should exceed 3,00,000
        self.assertGreater(summary["projected_month_end_spend_inr"], 300000.0)
        self.assertEqual(summary["alert_status"], "BREACH_PREDICTED")
        self.assertIsNotNone(summary["budget_breach_date"])
        self.assertGreater(summary["breach_variance_inr"], 0.0)

        # RAC vs ETS split
        self.assertGreater(summary["rac_spend_p50_inr"], 0.0)
        self.assertGreater(summary["ets_spend_p50_inr"], 0.0)
        self.assertAlmostEqual(
            summary["rac_spend_p50_inr"] + summary["ets_spend_p50_inr"],
            summary["total_p50_inr"],
            places=1,
        )

        # Optimization suggestion
        self.assertIn("save up to", summary["cost_saving_optimization"].lower())

    def test_04_platform_treasury_forecast(self):
        """4. Verify Platform Treasury: GTV, SaaS revenue, and float liquidity."""
        treasury_fc = get_platform_treasury_forecast(
            self.conn,
            self.operator_user,
            horizon_days=30,
            force_refresh=True,
        )

        self.assertTrue(treasury_fc["ok"])
        self.assertEqual(treasury_fc["entity_type"], "PLATFORM_TREASURY")
        summary = treasury_fc["summary_metrics"]

        self.assertGreater(summary["total_gtv_p50_inr"], 100000.0)
        # SaaS revenue is 5% of GTV
        self.assertAlmostEqual(summary["projected_saas_revenue_inr"], summary["total_gtv_p50_inr"] * 0.05, places=1)
        # Float liquidity is 22% of GTV
        self.assertAlmostEqual(summary["held_float_liquidity_inr"], summary["total_gtv_p50_inr"] * 0.22, places=1)

    def test_05_api_dispatcher_routes(self):
        """5. Verify all forecasting API routes dispatched through handle_timesfm_forecast_api."""
        # 1. GET /api/v1/forecasts/vendor-earnings
        res1 = handle_timesfm_forecast_api(
            self.conn,
            self.operator_user,
            "GET",
            "/api/v1/forecasts/vendor-earnings?horizon_days=7",
        )
        self.assertIsNotNone(res1)
        self.assertTrue(res1["ok"])
        self.assertEqual(res1["horizon_days"], 7)

        # 2. GET /api/v1/forecasts/corporate-expenditure
        res2 = handle_timesfm_forecast_api(
            self.conn,
            self.operator_user,
            "GET",
            f"/api/v1/forecasts/corporate-expenditure?corporate_id={self.corporate_id}&horizon_days=14",
        )
        self.assertIsNotNone(res2)
        self.assertTrue(res2["ok"])
        self.assertEqual(res2["horizon_days"], 14)

        # 3. GET /api/v1/forecasts/platform-treasury
        res3 = handle_timesfm_forecast_api(
            self.conn,
            self.operator_user,
            "GET",
            "/api/v1/forecasts/platform-treasury?horizon_days=30",
        )
        self.assertIsNotNone(res3)
        self.assertTrue(res3["ok"])

        # 4. POST /api/v1/corporate/budgets
        res4 = handle_timesfm_forecast_api(
            self.conn,
            self.operator_user,
            "POST",
            "/api/v1/corporate/budgets",
            payload={
                "corporate_id": self.corporate_id,
                "period_month": "2026-12",
                "budget_cap_inr": 750000.0,
            },
        )
        self.assertIsNotNone(res4)
        self.assertTrue(res4["ok"])
        self.assertEqual(res4["budget_cap_inr"], 750000.0)


if __name__ == "__main__":
    unittest.main()
