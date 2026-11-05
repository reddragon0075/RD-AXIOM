-- ==============================================================================
-- Migration: 20261027030000_tristack_hardening.sql
-- Description: Second-Order Hardening for Tri-Stack Platform:
--   1. Security Guards Registry with Trip Start/End OTP verification
--   2. Idempotency Key Tracking & Replay Rejection
--   3. Maker-Checker Route Variance Audit Queue
--   4. System Controls (Force Majeure & Hourly Tier Demotion Locks)
-- ==============================================================================

-- 1. Security Guards Table
CREATE TABLE IF NOT EXISTS public.tristack_security_guards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    guard_name TEXT NOT NULL,
    badge_number TEXT NOT NULL,
    phone TEXT NOT NULL,
    agency_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'SUSPENDED', 'INACTIVE')),
    start_otp TEXT NOT NULL DEFAULT '123456',
    end_otp TEXT NOT NULL DEFAULT '654321',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_guard_badge_org UNIQUE (organization_id, badge_number)
);

CREATE INDEX IF NOT EXISTS idx_guards_org_status ON public.tristack_security_guards(organization_id, status);

ALTER TABLE public.tristack_security_guards ENABLE ROW LEVEL SECURITY;

CREATE POLICY tristack_security_guards_tenant_isolation ON public.tristack_security_guards
    FOR ALL
    USING (organization_id in (select organization_id from public.organization_memberships where user_id = auth.uid()) or organization_id = (auth.jwt() ->> 'organization_id')::uuid or auth.role() = 'service_role');

-- 2. Idempotency Keys Table
CREATE TABLE IF NOT EXISTS public.tristack_idempotency_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_path TEXT NOT NULL,
    response_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS idx_idempotency_key_lookup ON public.tristack_idempotency_keys(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_idempotency_created ON public.tristack_idempotency_keys(created_at);

ALTER TABLE public.tristack_idempotency_keys ENABLE ROW LEVEL SECURITY;

CREATE POLICY tristack_idempotency_tenant_isolation ON public.tristack_idempotency_keys
    FOR ALL
    USING (organization_id in (select organization_id from public.organization_memberships where user_id = auth.uid()) or organization_id = (auth.jwt() ->> 'organization_id')::uuid or auth.role() = 'service_role');

-- 3. Maker-Checker Variance Queue
CREATE TABLE IF NOT EXISTS public.tristack_maker_checker_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    duty_id UUID NOT NULL REFERENCES public.duties(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    odometer_delta_km NUMERIC(8,2) NOT NULL,
    snapped_route_km NUMERIC(8,2) NOT NULL,
    variance_pct NUMERIC(6,2) NOT NULL,
    variance_km NUMERIC(8,2) NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING_REVIEW' CHECK(status IN ('PENDING_REVIEW', 'APPROVED_OVERRIDE', 'ADJUSTED', 'REJECTED')),
    reviewed_by UUID REFERENCES auth.users(id),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_mcq_duty UNIQUE (organization_id, duty_id)
);

CREATE INDEX IF NOT EXISTS idx_mcq_org_status ON public.tristack_maker_checker_queue(organization_id, status);

ALTER TABLE public.tristack_maker_checker_queue ENABLE ROW LEVEL SECURITY;

CREATE POLICY tristack_mcq_tenant_isolation ON public.tristack_maker_checker_queue
    FOR ALL
    USING (organization_id in (select organization_id from public.organization_memberships where user_id = auth.uid()) or organization_id = (auth.jwt() ->> 'organization_id')::uuid or auth.role() = 'service_role');

-- 4. Hourly Demotion Lock & Partner SLA Profiles
CREATE TABLE IF NOT EXISTS public.tristack_partner_sla_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL,
    vendor_name TEXT NOT NULL,
    current_tier TEXT NOT NULL DEFAULT 'TIER_1_PLATINUM',
    rolling_ota_pct NUMERIC(5,2) NOT NULL DEFAULT 96.5,
    active_breaches_7d INTEGER NOT NULL DEFAULT 0,
    total_trips_allocated INTEGER NOT NULL DEFAULT 120,
    trips_completed INTEGER NOT NULL DEFAULT 118,
    total_penalties_paise BIGINT NOT NULL DEFAULT 0,
    last_demoted_hour TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_tristack_partner_vendor UNIQUE (organization_id, vendor_id)
);

CREATE TABLE IF NOT EXISTS public.tristack_sla_breaches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL,
    vendor_name TEXT NOT NULL,
    duty_id UUID REFERENCES public.duties(id) ON DELETE SET NULL,
    breach_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    penalty_paise BIGINT NOT NULL DEFAULT 0,
    debit_note_reference TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

ALTER TABLE public.tristack_partner_sla_profiles
    ADD COLUMN IF NOT EXISTS last_demoted_hour TEXT;

CREATE TABLE IF NOT EXISTS public.tristack_system_controls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    force_majeure_active BOOLEAN NOT NULL DEFAULT FALSE,
    force_majeure_reason TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_system_controls_org UNIQUE (organization_id)
);

ALTER TABLE public.tristack_system_controls ENABLE ROW LEVEL SECURITY;

CREATE POLICY tristack_controls_tenant_isolation ON public.tristack_system_controls
    FOR ALL
    USING (organization_id in (select organization_id from public.organization_memberships where user_id = auth.uid()) or organization_id = (auth.jwt() ->> 'organization_id')::uuid or auth.role() = 'service_role');
