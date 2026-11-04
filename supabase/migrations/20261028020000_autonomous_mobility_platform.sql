-- ==============================================================================
-- Axiom Mobility: Autonomous Next-Gen Mobility Platform Migration
-- 1. Trip Trust Score, Auto-Audit & Discrepancy Resolution Engine
-- 2. Predictive SLA Radar & Night Safety Guardian Tracking
-- 3. Automated Credit Limit Dunning & Self-Serve Unblock Support
-- ==============================================================================

-- 1. TRIP TRUST SCORE & AUDIT RESOLUTION
CREATE TABLE IF NOT EXISTS public.domain_duty_trust_audits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id TEXT NOT NULL,
    duty_id TEXT NOT NULL UNIQUE,
    trust_score INTEGER NOT NULL CHECK (trust_score >= 0 AND trust_score <= 100),
    audit_status TEXT NOT NULL DEFAULT 'AUTO_VERIFIED' CHECK (audit_status IN ('AUTO_VERIFIED', 'NEEDS_AUDIT', 'RESOLVED_APPROVED', 'RESOLVED_SNAPPED')),
    audit_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    odometer_distance_km NUMERIC(10,2) NOT NULL DEFAULT 0,
    expected_distance_km NUMERIC(10,2) NOT NULL DEFAULT 0,
    duration_hours NUMERIC(6,2) NOT NULL DEFAULT 0,
    implied_speed_kmh NUMERIC(6,2) NOT NULL DEFAULT 0,
    resolved_by TEXT,
    resolved_at TIMESTAMPTZ,
    resolution_action TEXT,
    resolution_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_trust_audits_org ON public.domain_duty_trust_audits(organization_id, audit_status);
CREATE INDEX IF NOT EXISTS idx_trust_audits_duty ON public.domain_duty_trust_audits(duty_id);

ALTER TABLE public.domain_duty_trust_audits ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS trust_audits_org_isolation ON public.domain_duty_trust_audits;
CREATE POLICY trust_audits_org_isolation ON public.domain_duty_trust_audits
    FOR ALL
    TO authenticated
    USING (
        organization_id = coalesce(auth.jwt() ->> 'organization_id', '')
        OR coalesce(auth.jwt() ->> 'role', '') IN ('axiom_super_admin', 'axiom_admin', 'service_role')
        OR coalesce(auth.jwt() ->> 'email', '') LIKE '%@axiomfleet.in'
    );

-- 2. ADD AUTO-BLOCK ON OVERDUE TO TENANT BILLING ACCOUNTS
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' 
          AND table_name = 'tenant_billing_accounts' 
          AND column_name = 'auto_block_on_overdue'
    ) THEN
        ALTER TABLE public.tenant_billing_accounts 
        ADD COLUMN auto_block_on_overdue BOOLEAN NOT NULL DEFAULT true;
    END IF;
END $$;
