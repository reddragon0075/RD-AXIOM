"""Axiom Mobility (Fleetline) - TimesFM Predictive Earnings & Corporate Expenditure Forecasting Service Layer.

Provides direct access to:
1. Two-Tier TimesFM Hybrid Forecasting Engine (TimesFMAdapter + SeasonalQuantileFallback).
2. Continuous Daily Time-Series Extractor & Cold-Start Prior Padding.
3. Vendor Future Earnings & Cash-Flow Forecaster (Withdrawable liquidity schedule & capacity recommendations).
4. Corporate Future Expenditure Forecaster (RAC vs ETS breakdown, budget breach dates, cost-saving levers).
5. Platform Treasury Float & Demand Forecaster (GTV, SaaS revenue, hold float).
6. PostgreSQL / SQLite Forecast Caching Layer.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add fleetline-mvp to sys.path
mvp_dir = Path(__file__).resolve().parent.parent / "fleetline-mvp"
if str(mvp_dir) not in sys.path:
    sys.path.insert(0, str(mvp_dir))

from backend_timesfm_forecast import (
    initialize_timesfm_forecast_schema,
    TimesFMAdapter,
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

__all__ = [
    "initialize_timesfm_forecast_schema",
    "TimesFMAdapter",
    "SeasonalQuantileFallback",
    "generate_timesfm_forecast",
    "extract_vendor_earnings_series",
    "extract_corporate_spend_series",
    "get_vendor_earnings_forecast",
    "get_corporate_expenditure_forecast",
    "get_platform_treasury_forecast",
    "set_corporate_travel_budget",
    "handle_timesfm_forecast_api",
]
