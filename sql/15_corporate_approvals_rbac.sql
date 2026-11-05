-- Axiom Mobility: Corporate Approvals Engine, Cost Centers, Policies & Multi-Level RBAC
-- Migration: fleetline-mvp/supabase/migrations/20261104150000_corporate_approvals_rbac.sql

-- 1. COST CENTERS TABLE
CREATE TABLE IF NOT EXISTS public.cost_centers (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    monthly_budget_inr NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    current_month_spend_inr NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    head_approver_user_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_cost_centers_tenant_code UNIQUE(tenant_id, code)
);

CREATE INDEX IF NOT EXISTS idx_corp_cost_centers ON public.cost_centers(tenant_id);
CREATE INDEX IF NOT EXISTS idx_corp_cost_centers_code ON public.cost_centers(tenant_id, code);

-- 2. CORPORATE USERS TABLE
CREATE TABLE IF NOT EXISTS public.corporate_users (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tenant_id TEXT NOT NULL,
    email TEXT NOT NULL,
    full_name TEXT NOT NULL,
    phone TEXT,
    employee_code TEXT,
    gender TEXT DEFAULT 'NOT_SPECIFIED',
    corp_role TEXT NOT NULL DEFAULT 'CORP_EMPLOYEE',
    manager_user_id TEXT,
    delegate_approver_user_id TEXT,
    cost_center_id TEXT,
    daily_spend_limit_inr NUMERIC(12, 2) NOT NULL DEFAULT 5000.00,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_corporate_users_tenant_email UNIQUE(tenant_id, email)
);

CREATE INDEX IF NOT EXISTS idx_corp_users_tenant ON public.corporate_users(tenant_id);
CREATE INDEX IF NOT EXISTS idx_corp_users_email ON public.corporate_users(email);
CREATE INDEX IF NOT EXISTS idx_corp_users_manager ON public.corporate_users(manager_user_id);
CREATE INDEX IF NOT EXISTS idx_corp_users_cost_center ON public.corporate_users(cost_center_id);

-- 3. CORPORATE APPROVAL POLICIES TABLE
CREATE TABLE IF NOT EXISTS public.corporate_approval_policies (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tenant_id TEXT NOT NULL UNIQUE,
    auto_approve_under_inr NUMERIC(12, 2) NOT NULL DEFAULT 800.00,
    require_manager_approval_for_models TEXT NOT NULL DEFAULT '["OUTSTATION", "AIRPORT", "8HR_80KM", "RENTAL"]',
    require_second_level_finance_above_inr NUMERIC(12, 2) NOT NULL DEFAULT 10000.00,
    rolling_24h_spend_cap_inr NUMERIC(12, 2) NOT NULL DEFAULT 2000.00,
    budget_enforcement_enabled INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_corp_policies_tenant ON public.corporate_approval_policies(tenant_id);

-- 4. BOOKING APPROVAL REQUESTS TABLE
CREATE TABLE IF NOT EXISTS public.booking_approval_requests (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    trip_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    requester_user_id TEXT NOT NULL,
    cost_center_id TEXT,
    estimated_fare_inr NUMERIC(12, 2) NOT NULL,
    booking_justification TEXT,
    approval_status TEXT NOT NULL DEFAULT 'PENDING_APPROVAL',
    booking_parameter_hash TEXT NOT NULL,
    vehicle_type TEXT,
    tariff_model TEXT,
    pickup_address TEXT,
    drop_address TEXT,
    scheduled_at TIMESTAMPTZ,
    l1_approver_id TEXT,
    l1_decided_at TIMESTAMPTZ,
    l1_decision_note TEXT,
    l2_approver_id TEXT,
    l2_decided_at TIMESTAMPTZ,
    l2_decision_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bar_trip ON public.booking_approval_requests(trip_id);
CREATE INDEX IF NOT EXISTS idx_bar_tenant_req ON public.booking_approval_requests(tenant_id, requester_user_id);
CREATE INDEX IF NOT EXISTS idx_bar_status ON public.booking_approval_requests(approval_status);
CREATE INDEX IF NOT EXISTS idx_bar_created ON public.booking_approval_requests(created_at DESC);

-- 5. ROW LEVEL SECURITY (RLS) LOCKDOWN
ALTER TABLE public.cost_centers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cost_centers FORCE ROW LEVEL SECURITY;

ALTER TABLE public.corporate_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.corporate_users FORCE ROW LEVEL SECURITY;

ALTER TABLE public.corporate_approval_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.corporate_approval_policies FORCE ROW LEVEL SECURITY;

ALTER TABLE public.booking_approval_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.booking_approval_requests FORCE ROW LEVEL SECURITY;

-- Helper function if not yet declared
CREATE OR REPLACE FUNCTION current_axiom_tenant() RETURNS text AS $$
BEGIN
    RETURN COALESCE(
        current_setting('app.current_tenant_id', true),
        (current_setting('request.jwt.claims', true)::jsonb ->> 'organization_id'),
        (current_setting('request.jwt.claims', true)::jsonb ->> 'tenant_id')
    );
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- RLS POLICIES FOR COST CENTERS
DROP POLICY IF EXISTS p_cost_centers_tenant_isolation ON public.cost_centers;
CREATE POLICY p_cost_centers_tenant_isolation ON public.cost_centers
    AS RESTRICTIVE
    USING (tenant_id = current_axiom_tenant() OR current_axiom_tenant() IS NULL);

-- RLS POLICIES FOR CORPORATE USERS
DROP POLICY IF EXISTS p_corporate_users_tenant_isolation ON public.corporate_users;
CREATE POLICY p_corporate_users_tenant_isolation ON public.corporate_users
    AS RESTRICTIVE
    USING (tenant_id = current_axiom_tenant() OR current_axiom_tenant() IS NULL);

-- RLS POLICIES FOR CORPORATE APPROVAL POLICIES
DROP POLICY IF EXISTS p_corporate_policies_tenant_isolation ON public.corporate_approval_policies;
CREATE POLICY p_corporate_policies_tenant_isolation ON public.corporate_approval_policies
    AS RESTRICTIVE
    USING (tenant_id = current_axiom_tenant() OR current_axiom_tenant() IS NULL);

-- RLS POLICIES FOR BOOKING APPROVAL REQUESTS
DROP POLICY IF EXISTS p_bar_tenant_isolation ON public.booking_approval_requests;
CREATE POLICY p_bar_tenant_isolation ON public.booking_approval_requests
    AS RESTRICTIVE
    USING (tenant_id = current_axiom_tenant() OR current_axiom_tenant() IS NULL);
