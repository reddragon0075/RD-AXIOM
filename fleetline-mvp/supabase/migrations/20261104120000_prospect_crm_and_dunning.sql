-- Axiom Mobility: Prospect Capture CRM, SaaS Dunning & Corporate Annexure Portal Schema
-- Migration: sql/13_prospect_crm_and_dunning.sql

-- 1. SALES PROSPECTS TABLE
CREATE TABLE IF NOT EXISTS public.sales_prospects (
    id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    company_name TEXT NOT NULL,
    mobile_number TEXT NOT NULL,
    email_id TEXT NOT NULL,
    city TEXT NOT NULL DEFAULT 'Bengaluru',
    fleet_size_estimate INTEGER NOT NULL DEFAULT 5,
    interest_type TEXT NOT NULL DEFAULT 'VENDOR_SAAS' CHECK (interest_type IN ('VENDOR_SAAS', 'CORPORATE_ETMS', 'PARTNER_NETWORK')),
    lead_source TEXT NOT NULL DEFAULT 'WEBSITE_FORM' CHECK (lead_source IN ('WEBSITE_FORM', 'REFERRAL', 'MANUAL')),
    status TEXT NOT NULL DEFAULT 'NEW_PROSPECT' CHECK (status IN ('NEW_PROSPECT', 'CONTACTED_QUERYING', 'DEMO_SCHEDULED', 'ONBOARDED_CONVERTED', 'LOST')),
    assigned_sales_rep_id TEXT,
    call_notes_jsonb JSONB NOT NULL DEFAULT '[]'::jsonb,
    converted_tenant_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sales_prospects_email ON public.sales_prospects(email_id);
CREATE INDEX IF NOT EXISTS idx_sales_prospects_mobile ON public.sales_prospects(mobile_number);
CREATE INDEX IF NOT EXISTS idx_sales_prospects_status ON public.sales_prospects(status);

-- 2. TENANT PLATFORM INVOICES (What Vendors Owe Axiom)
CREATE TABLE IF NOT EXISTS public.tenant_platform_invoices (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    invoice_number TEXT NOT NULL,
    billing_period TEXT NOT NULL,
    saas_base_fee_inr NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    trip_overage_fee_inr NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    total_amount_due_inr NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    amount_paid_inr NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    balance_owed_inr NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    due_date TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'UNPAID' CHECK (status IN ('UNPAID', 'PARTIALLY_PAID', 'PAID', 'OVERDUE')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tenant_platform_invoices_tenant ON public.tenant_platform_invoices(tenant_id, status);

-- 3. 3-STAGE ACCESS CONTROL COLUMNS ON TENANT BILLING ACCOUNTS / ORGANIZATIONS
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'tenant_billing_accounts') THEN
        ALTER TABLE public.tenant_billing_accounts ADD COLUMN IF NOT EXISTS access_control_state TEXT NOT NULL DEFAULT 'ACTIVE_GOOD_STANDING';
        ALTER TABLE public.tenant_billing_accounts ADD COLUMN IF NOT EXISTS saas_balance_owed_inr NUMERIC(12, 2) NOT NULL DEFAULT 0.00;
        ALTER TABLE public.tenant_billing_accounts ADD COLUMN IF NOT EXISTS dunning_stage INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE public.tenant_billing_accounts ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMPTZ;
        ALTER TABLE public.tenant_billing_accounts ADD COLUMN IF NOT EXISTS trial_trips_quota INTEGER DEFAULT 100;
    END IF;
END $$;

-- 4. CORPORATE PROFORMA ANNEXURE MAGIC SHARE TOKENS
CREATE TABLE IF NOT EXISTS public.proforma_annexure_shares (
    id TEXT PRIMARY KEY,
    proforma_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    corporate_name TEXT NOT NULL,
    corporate_email TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING_REVIEW' CHECK (status IN ('PENDING_REVIEW', 'PARTIALLY_APPROVED', 'APPROVED_LOCKED', 'EXPIRED')),
    approved_duty_ids_json TEXT NOT NULL DEFAULT '[]',
    flagged_duty_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_proforma_shares_token ON public.proforma_annexure_shares(token);
