-- Axiom Mobility: Google TimesFM Time-Series Predictive Earnings & Corporate Expenditure Forecasting Engine
-- Migration: sql/17_timesfm_financial_forecasts.sql

-- 1. FINANCIAL FORECASTS CACHE TABLE
CREATE TABLE IF NOT EXISTS public.financial_forecasts_cache (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('VENDOR_EARNINGS', 'CORPORATE_EXPENDITURE', 'PLATFORM_TREASURY')),
    entity_id TEXT NOT NULL,
    horizon_days INTEGER NOT NULL CHECK (horizon_days IN (7, 14, 30, 60, 90)),
    model_backend_used TEXT NOT NULL,
    historical_series_jsonb JSONB NOT NULL DEFAULT '[]'::jsonb,
    forecast_series_jsonb JSONB NOT NULL DEFAULT '[]'::jsonb,
    summary_metrics_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_forecast_cache_lookup 
ON public.financial_forecasts_cache (tenant_id, entity_type, entity_id, horizon_days, expires_at);

-- 2. CORPORATE TRAVEL BUDGETS TABLE (SPEND CAPS & THRESHOLD ALERTS)
CREATE TABLE IF NOT EXISTS public.corporate_travel_budgets (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    corporate_id TEXT NOT NULL,
    cost_center_code TEXT NOT NULL DEFAULT 'GENERAL',
    period_month TEXT NOT NULL, -- e.g. '2026-11'
    budget_cap_inr NUMERIC(14,2) NOT NULL,
    alert_threshold_pct INTEGER NOT NULL DEFAULT 85,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_corp_budget_period UNIQUE (tenant_id, corporate_id, cost_center_code, period_month)
);

CREATE INDEX IF NOT EXISTS idx_corp_budgets_lookup 
ON public.corporate_travel_budgets (tenant_id, corporate_id, period_month);
