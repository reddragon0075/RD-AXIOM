-- Axiom Mobility: "Native-Link" CRM v2.0 (Revenue, Supply & Treasury OS)
-- Migration: fleetline-mvp/supabase/migrations/14_native_crm_v2.sql

-- 1. CRM ACCOUNTS TABLE (360 Organization & Commercial Lifecycle Entity)
CREATE TABLE IF NOT EXISTS public.crm_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES public.organizations(id) ON DELETE SET NULL,
    account_name TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK (account_type IN ('CORPORATE_CLIENT', 'FLEET_VENDOR', 'PARTNER_OPERATOR', 'PROSPECT_LEAD')),
    industry TEXT,
    city TEXT NOT NULL DEFAULT 'Bengaluru',
    billing_address TEXT,
    gstin TEXT,
    pan_number TEXT,
    primary_contact_name TEXT,
    primary_email TEXT,
    primary_phone TEXT,
    account_status TEXT NOT NULL DEFAULT 'PROSPECT' CHECK (account_status IN ('PROSPECT', 'ONBOARDING', 'ACTIVE', 'SOFT_BLOCKED', 'HARD_BLOCKED', 'CHURN_RISK', 'CHURNED')),
    credit_limit_inr NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    payment_terms_days INTEGER NOT NULL DEFAULT 30,
    contract_start_date DATE,
    contract_renewal_date DATE,
    lead_score INTEGER NOT NULL DEFAULT 50 CHECK (lead_score BETWEEN 0 AND 100),
    health_score INTEGER NOT NULL DEFAULT 100 CHECK (health_score BETWEEN 0 AND 100),
    estimated_fleet_or_headcount INTEGER NOT NULL DEFAULT 5,
    custom_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    assigned_owner_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_crm_account_contact_present CHECK (primary_email IS NOT NULL OR primary_phone IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_crm_accounts_tenant ON public.crm_accounts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_crm_accounts_type ON public.crm_accounts(account_type);
CREATE INDEX IF NOT EXISTS idx_crm_accounts_status ON public.crm_accounts(account_status);
CREATE INDEX IF NOT EXISTS idx_crm_accounts_phone ON public.crm_accounts(primary_phone);
CREATE INDEX IF NOT EXISTS idx_crm_accounts_email ON public.crm_accounts(primary_email);

-- 2. CRM CONTACTS TABLE (Multi-Stakeholder Organizational Mapping)
CREATE TABLE IF NOT EXISTS public.crm_contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES public.crm_accounts(id) ON DELETE CASCADE,
    full_name TEXT NOT NULL,
    role_type TEXT NOT NULL DEFAULT 'DECISION_MAKER' CHECK (role_type IN ('DECISION_MAKER', 'TRANSPORT_ADMIN', 'FINANCE_AP', 'PROCUREMENT', 'FLEET_OWNER', 'ESCALATION_SPOC')),
    email TEXT,
    phone TEXT,
    whatsapp_opt_in BOOLEAN NOT NULL DEFAULT TRUE,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crm_contacts_account ON public.crm_contacts(account_id);
CREATE INDEX IF NOT EXISTS idx_crm_contacts_email ON public.crm_contacts(email);
CREATE INDEX IF NOT EXISTS idx_crm_contacts_phone ON public.crm_contacts(phone);

-- 3. CRM DEALS TABLE (Dual-Track Pipeline & Spread CPQ Engine)
CREATE TABLE IF NOT EXISTS public.crm_deals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES public.crm_accounts(id) ON DELETE CASCADE,
    deal_title TEXT NOT NULL,
    pipeline_track TEXT NOT NULL DEFAULT 'CORPORATE_DEMAND' CHECK (pipeline_track IN ('CORPORATE_DEMAND', 'VENDOR_SUPPLY')),
    pipeline_stage TEXT NOT NULL DEFAULT '1_INBOUND_PROSPECT' CHECK (pipeline_stage IN ('1_INBOUND_PROSPECT', '2_DISCOVERY_QUALIFIED', '3_SIMULATION_CPQ', '4_COMPLIANCE_MSA_REVIEW', '5_CLOSED_WON_PROVISIONED', '6_CLOSED_LOST')),
    estimated_monthly_trips INTEGER NOT NULL DEFAULT 0,
    deal_gmv_estimated_inr NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    client_sell_tariff_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    vendor_buy_tariff_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    projected_gross_margin_pct NUMERIC(5, 2) NOT NULL DEFAULT 0.00,
    margin_approval_status TEXT NOT NULL DEFAULT 'APPROVED' CHECK (margin_approval_status IN ('APPROVED', 'LOW_MARGIN_WARNING', 'REJECTED')),
    probability_pct INTEGER NOT NULL DEFAULT 20 CHECK (probability_pct BETWEEN 0 AND 100),
    expected_close_date DATE,
    loss_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crm_deals_account ON public.crm_deals(account_id);
CREATE INDEX IF NOT EXISTS idx_crm_deals_track_stage ON public.crm_deals(pipeline_track, pipeline_stage);

-- 4. CRM ACTIVITIES TABLE (Unified Audit & Event Timeline)
CREATE TABLE IF NOT EXISTS public.crm_activities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES public.crm_accounts(id) ON DELETE CASCADE,
    deal_id UUID REFERENCES public.crm_deals(id) ON DELETE SET NULL,
    activity_type TEXT NOT NULL CHECK (activity_type IN ('CALL_LOG', 'WHATSAPP', 'MEETING', 'CPQ_QUOTE_SENT', 'STAGE_CHANGE', 'KILL_SWITCH_TOGGLED', 'PAYOUT_HOLD_TOGGLED', 'PAYMENT_RECEIVED', 'NOTE')),
    subject TEXT NOT NULL,
    description TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    performed_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crm_activities_account ON public.crm_activities(account_id);
CREATE INDEX IF NOT EXISTS idx_crm_activities_created ON public.crm_activities(created_at DESC);

-- 5. CRM TASKS TABLE (Follow-Up & Dunning SLA Queue)
CREATE TABLE IF NOT EXISTS public.crm_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES public.crm_accounts(id) ON DELETE CASCADE,
    deal_id UUID REFERENCES public.crm_deals(id) ON DELETE SET NULL,
    task_category TEXT NOT NULL DEFAULT 'SALES_FOLLOWUP' CHECK (task_category IN ('SALES_FOLLOWUP', 'ONBOARDING_DOCS', 'COLLECTIONS_DUNNING', 'CONTRACT_RENEWAL')),
    title TEXT NOT NULL,
    due_at TIMESTAMPTZ NOT NULL,
    priority TEXT NOT NULL DEFAULT 'MEDIUM' CHECK (priority IN ('LOW', 'MEDIUM', 'HIGH', 'URGENT')),
    is_completed BOOLEAN NOT NULL DEFAULT FALSE,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crm_tasks_account ON public.crm_tasks(account_id);
CREATE INDEX IF NOT EXISTS idx_crm_tasks_due ON public.crm_tasks(due_at, is_completed);

-- 6. ENABLE ROW LEVEL SECURITY
ALTER TABLE public.crm_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.crm_contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.crm_deals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.crm_activities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.crm_tasks ENABLE ROW LEVEL SECURITY;

-- Default Permissive Policies for Authenticated Operations Staff
CREATE POLICY crm_accounts_admin_policy ON public.crm_accounts FOR ALL USING (true);
CREATE POLICY crm_contacts_admin_policy ON public.crm_contacts FOR ALL USING (true);
CREATE POLICY crm_deals_admin_policy ON public.crm_deals FOR ALL USING (true);
CREATE POLICY crm_activities_admin_policy ON public.crm_activities FOR ALL USING (true);
CREATE POLICY crm_tasks_admin_policy ON public.crm_tasks FOR ALL USING (true);
