-- ==============================================================================
-- Axiom Mobility: Commercial & Revenue Control Plane Migration
-- 1. Prospects & Sales CRM Table (Website Lead Capture & 1-Click Onboarding)
-- 2. Tenant Billing Accounts, Axiom Receivables Ledger & Kill-Switch Status
-- 3. Audit Log Triggers on Tenant Account Status Changes
-- ==============================================================================

-- 1. PROSPECTS & SALES CRM TABLE
CREATE TABLE IF NOT EXISTS public.prospects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_name TEXT NOT NULL DEFAULT '',
    company_name TEXT NOT NULL DEFAULT '',
    email TEXT,
    mobile_number TEXT,
    message TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'WEBSITE',
    status TEXT NOT NULL DEFAULT 'NEW' CHECK (status IN ('NEW', 'CONTACTED', 'QUALIFIED', 'ONBOARDED', 'LOST')),
    sales_notes JSONB NOT NULL DEFAULT '[]'::jsonb,
    assigned_sales_rep TEXT NOT NULL DEFAULT '',
    converted_tenant_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    CONSTRAINT chk_prospect_contact_info CHECK (
        (email IS NOT NULL AND trim(email) <> '') OR 
        (mobile_number IS NOT NULL AND trim(mobile_number) <> '')
    )
);

-- Partial Unique Indexes to prevent duplicate leads while permitting nulls
CREATE UNIQUE INDEX IF NOT EXISTS idx_prospects_unique_email 
    ON public.prospects (lower(trim(email))) 
    WHERE email IS NOT NULL AND trim(email) <> '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_prospects_unique_mobile 
    ON public.prospects (trim(mobile_number)) 
    WHERE mobile_number IS NOT NULL AND trim(mobile_number) <> '';

CREATE INDEX IF NOT EXISTS idx_prospects_status ON public.prospects(status);
CREATE INDEX IF NOT EXISTS idx_prospects_created_at ON public.prospects(created_at DESC);

-- Enable RLS
ALTER TABLE public.prospects ENABLE ROW LEVEL SECURITY;

-- Anonymous public users can insert website prospects
DROP POLICY IF EXISTS prospects_anon_insert ON public.prospects;
CREATE POLICY prospects_anon_insert ON public.prospects
    FOR INSERT
    TO anon, authenticated
    WITH CHECK (true);

-- Axiom Super-Admins / Sales Staff have full access
DROP POLICY IF EXISTS prospects_admin_manage ON public.prospects;
CREATE POLICY prospects_admin_manage ON public.prospects
    FOR ALL
    TO authenticated
    USING (
        coalesce(auth.jwt() ->> 'role', '') IN ('axiom_super_admin', 'axiom_admin', 'axiom_staff', 'service_role')
        OR coalesce(auth.jwt() ->> 'email', '') LIKE '%@axiomfleet.in'
    );

-- 2. TENANT BILLING ACCOUNTS & ACCESS CONTROL ("KILL SWITCH")
CREATE TABLE IF NOT EXISTS public.tenant_billing_accounts (
    tenant_id TEXT PRIMARY KEY,
    tenant_name TEXT NOT NULL,
    account_status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (account_status IN ('ACTIVE', 'SOFT_BLOCKED', 'HARD_BLOCKED', 'SUSPENDED')),
    block_reason TEXT NOT NULL DEFAULT '',
    blocked_at TIMESTAMPTZ,
    blocked_by TEXT NOT NULL DEFAULT '',
    total_billed_paise BIGINT NOT NULL DEFAULT 0,
    total_paid_paise BIGINT NOT NULL DEFAULT 0,
    outstanding_balance_paise BIGINT GENERATED ALWAYS AS (total_billed_paise - total_paid_paise) STORED,
    credit_limit_paise BIGINT NOT NULL DEFAULT 10000000, -- ₹1,00,000 default credit limit
    next_due_date TIMESTAMPTZ,
    days_overdue INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_tenant_billing_status ON public.tenant_billing_accounts(account_status);
CREATE INDEX IF NOT EXISTS idx_tenant_billing_overdue ON public.tenant_billing_accounts(days_overdue DESC);

ALTER TABLE public.tenant_billing_accounts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_billing_admin_all ON public.tenant_billing_accounts;
CREATE POLICY tenant_billing_admin_all ON public.tenant_billing_accounts
    FOR ALL
    TO authenticated
    USING (
        coalesce(auth.jwt() ->> 'role', '') IN ('axiom_super_admin', 'axiom_admin', 'service_role')
        OR coalesce(auth.jwt() ->> 'email', '') LIKE '%@axiomfleet.in'
    );

DROP POLICY IF EXISTS tenant_billing_tenant_read ON public.tenant_billing_accounts;
CREATE POLICY tenant_billing_tenant_read ON public.tenant_billing_accounts
    FOR SELECT
    TO authenticated
    USING (
        tenant_id = coalesce(auth.jwt() ->> 'organization_id', '')
    );

-- 3. AXIOM RECEIVABLE LEDGER
CREATE TABLE IF NOT EXISTS public.axiom_receivable_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL REFERENCES public.tenant_billing_accounts(tenant_id) ON DELETE CASCADE,
    entry_type TEXT NOT NULL CHECK (entry_type IN ('INVOICE', 'PAYMENT', 'CREDIT_NOTE', 'ADJUSTMENT')),
    reference_id TEXT NOT NULL DEFAULT '',
    amount_paise BIGINT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    payment_method TEXT NOT NULL DEFAULT 'BANK_TRANSFER',
    created_by TEXT NOT NULL DEFAULT 'SYSTEM',
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_receivable_ledger_tenant ON public.axiom_receivable_ledger(tenant_id, created_at DESC);

ALTER TABLE public.axiom_receivable_ledger ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS receivable_ledger_admin_all ON public.axiom_receivable_ledger;
CREATE POLICY receivable_ledger_admin_all ON public.axiom_receivable_ledger
    FOR ALL
    TO authenticated
    USING (
        coalesce(auth.jwt() ->> 'role', '') IN ('axiom_super_admin', 'axiom_admin', 'service_role')
        OR coalesce(auth.jwt() ->> 'email', '') LIKE '%@axiomfleet.in'
    );

-- 4. AUDIT LOG TRIGGER FOR TENANT STATUS & ONBOARDING
CREATE OR REPLACE FUNCTION public.fn_audit_tenant_account_status_change()
RETURNS TRIGGER AS $$
BEGIN
    IF (OLD.account_status IS DISTINCT FROM NEW.account_status) THEN
        INSERT INTO public.audit_logs (
            id,
            organization_id,
            actor_id,
            action,
            entity_type,
            entity_id,
            payload_json,
            created_at
        ) VALUES (
            gen_random_uuid(),
            NEW.tenant_id,
            coalesce(NEW.blocked_by, 'SYSTEM'),
            'TENANT_STATUS_CHANGED',
            'tenant_billing_account',
            NEW.tenant_id,
            json_build_object(
                'previous_status', OLD.account_status,
                'new_status', NEW.account_status,
                'reason', NEW.block_reason,
                'outstanding_balance_paise', NEW.outstanding_balance_paise
            )::text,
            timezone('utc'::text, now())
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS trg_audit_tenant_account_status ON public.tenant_billing_accounts;
CREATE TRIGGER trg_audit_tenant_account_status
    AFTER UPDATE OF account_status ON public.tenant_billing_accounts
    FOR EACH ROW
    EXECUTE FUNCTION public.fn_audit_tenant_account_status_change();
