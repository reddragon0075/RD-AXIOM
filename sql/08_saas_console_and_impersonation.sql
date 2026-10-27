-- Axiom Mobility (Fleetline) Tri-Stack SaaS Console & Impersonation Engine
-- Migration: 08_saas_console_and_impersonation.sql
-- Enables Multi-Tenant Subscriptions, Wallets, Feature Entitlements, and Cryptographic Impersonation Audit Logs.

-- 1. TENANT SUBSCRIPTIONS
CREATE TABLE IF NOT EXISTS tenant_subscriptions (
    tenant_id BIGINT PRIMARY KEY,
    tenant_uuid TEXT NOT NULL UNIQUE,
    tenant_name TEXT NOT NULL,
    plan_tier TEXT NOT NULL DEFAULT 'GROWTH' CHECK (plan_tier IN ('SOLO', 'GROWTH', 'ENTERPRISE')),
    subscription_status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (subscription_status IN ('ACTIVE', 'TRIAL', 'PAST_DUE', 'CANCELLED', 'SLA_PROBATION')),
    mrr_paise BIGINT NOT NULL DEFAULT 500000, -- Integer paise (₹5,000.00)
    billing_cycle TEXT NOT NULL DEFAULT 'MONTHLY' CHECK (billing_cycle IN ('MONTHLY', 'ANNUAL')),
    current_period_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    current_period_end TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '30 days'),
    corporate_quota_total INT NOT NULL DEFAULT 5,
    corporate_quota_used INT NOT NULL DEFAULT 1,
    trip_quota_total INT NOT NULL DEFAULT 100,
    trip_quota_used INT NOT NULL DEFAULT 14,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tenant_subs_status ON tenant_subscriptions(subscription_status);
CREATE INDEX IF NOT EXISTS idx_tenant_subs_tier ON tenant_subscriptions(plan_tier);

-- 2. TENANT PRE-PAID WALLETS
CREATE TABLE IF NOT EXISTS tenant_wallets (
    tenant_id BIGINT PRIMARY KEY REFERENCES tenant_subscriptions(tenant_id) ON DELETE CASCADE,
    balance_paise BIGINT NOT NULL DEFAULT 0, -- Integer paise (e.g., 500 paise = ₹5.00)
    currency TEXT NOT NULL DEFAULT 'INR',
    auto_recharge_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    auto_recharge_threshold_paise BIGINT DEFAULT 100000,
    auto_recharge_amount_paise BIGINT DEFAULT 500000,
    last_topup_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. TENANT FEATURE ENTITLEMENTS (Instant Flag Toggles)
CREATE TABLE IF NOT EXISTS tenant_feature_flags (
    tenant_id BIGINT PRIMARY KEY REFERENCES tenant_subscriptions(tenant_id) ON DELETE CASCADE,
    network_exchange_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    marketplace_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    parse_ai_intake_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    whatsapp_bot_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    posh_compliance_enforced BOOLEAN NOT NULL DEFAULT TRUE,
    distance_fraud_gate_enforced BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4. CRYPTOGRAPHIC ADMIN IMPERSONATION AUDIT LOGS ("SUPPORT SHADOW SESSIONS")
CREATE TABLE IF NOT EXISTS admin_impersonation_audit_logs (
    id TEXT PRIMARY KEY,
    actor_admin_id TEXT NOT NULL,
    actor_admin_email TEXT NOT NULL,
    target_tenant_id BIGINT NOT NULL,
    target_tenant_name TEXT NOT NULL,
    target_vendor_user_id TEXT NOT NULL,
    impersonation_mode TEXT NOT NULL DEFAULT 'READ_ONLY' CHECK (impersonation_mode IN ('READ_ONLY', 'READ_WRITE')),
    reason_code TEXT,
    session_token_hash TEXT NOT NULL,
    ip_address TEXT NOT NULL,
    user_agent TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '30 minutes'),
    ended_at TIMESTAMPTZ,
    duration_seconds INT,
    mutation_count INT NOT NULL DEFAULT 0,
    session_status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (session_status IN ('ACTIVE', 'ENDED_BY_USER', 'EXPIRED', 'REVOKED'))
);

CREATE INDEX IF NOT EXISTS idx_impersonation_tenant ON admin_impersonation_audit_logs(target_tenant_id);
CREATE INDEX IF NOT EXISTS idx_impersonation_actor ON admin_impersonation_audit_logs(actor_admin_id);
CREATE INDEX IF NOT EXISTS idx_impersonation_status ON admin_impersonation_audit_logs(session_status);

-- 5. ROW-LEVEL SECURITY (RLS) POLICIES FOR SUPABASE POSTGRES
ALTER TABLE tenant_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_wallets ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_feature_flags ENABLE ROW LEVEL SECURITY;
ALTER TABLE admin_impersonation_audit_logs ENABLE ROW LEVEL SECURITY;

-- Super-Admin Policy (Full Access)
CREATE POLICY superadmin_all_tenant_subs ON tenant_subscriptions
    FOR ALL TO authenticated
    USING (auth.jwt() ->> 'role' = 'superadmin' OR auth.jwt() ->> 'is_axiom_hq' = 'true')
    WITH CHECK (auth.jwt() ->> 'role' = 'superadmin' OR auth.jwt() ->> 'is_axiom_hq' = 'true');

-- Vendor Self-View Policy
CREATE POLICY vendor_view_own_subscription ON tenant_subscriptions
    FOR SELECT TO authenticated
    USING (tenant_id = (auth.jwt() ->> 'tenant_id')::bigint);

CREATE POLICY vendor_view_own_wallet ON tenant_wallets
    FOR SELECT TO authenticated
    USING (tenant_id = (auth.jwt() ->> 'tenant_id')::bigint);

CREATE POLICY vendor_view_own_flags ON tenant_feature_flags
    FOR SELECT TO authenticated
    USING (tenant_id = (auth.jwt() ->> 'tenant_id')::bigint);

-- Impersonation Logs: Super-Admin Only
CREATE POLICY superadmin_view_impersonation_logs ON admin_impersonation_audit_logs
    FOR ALL TO authenticated
    USING (auth.jwt() ->> 'role' = 'superadmin' OR auth.jwt() ->> 'is_axiom_hq' = 'true')
    WITH CHECK (auth.jwt() ->> 'role' = 'superadmin' OR auth.jwt() ->> 'is_axiom_hq' = 'true');

-- 6. SEED INITIAL TENANTS & TEST FIXTURES
INSERT INTO tenant_subscriptions (tenant_id, tenant_uuid, tenant_name, plan_tier, subscription_status, mrr_paise, billing_cycle, corporate_quota_total, corporate_quota_used, trip_quota_total, trip_quota_used)
VALUES
    (169, 'ten_zion_169', 'Zion Travels', 'GROWTH', 'ACTIVE', 500000, 'MONTHLY', 5, 1, 100, 14),
    (170, 'ten_apex_170', 'Apex Cabs & Logistics', 'ENTERPRISE', 'ACTIVE', 2500000, 'ANNUAL', 25, 18, 1500, 1120),
    (171, 'ten_bluestar_171', 'BlueStar Mobility', 'GROWTH', 'SLA_PROBATION', 500000, 'MONTHLY', 5, 2, 100, 42),
    (172, 'ten_garuda_172', 'Garuda City Fleets', 'SOLO', 'TRIAL', 0, 'MONTHLY', 1, 1, 20, 19),
    (173, 'ten_royal_173', 'Royal Executive Rentals', 'GROWTH', 'PAST_DUE', 500000, 'MONTHLY', 5, 3, 100, 88)
ON CONFLICT (tenant_id) DO NOTHING;

INSERT INTO tenant_wallets (tenant_id, balance_paise, currency)
VALUES
    (169, 500, 'INR'),      -- ₹5.00
    (170, 425000, 'INR'),   -- ₹4,250.00
    (171, 120000, 'INR'),   -- ₹1,200.00
    (172, 0, 'INR'),        -- ₹0.00
    (173, 25000, 'INR')     -- ₹250.00
ON CONFLICT (tenant_id) DO NOTHING;

INSERT INTO tenant_feature_flags (tenant_id, network_exchange_enabled, marketplace_enabled, parse_ai_intake_enabled, whatsapp_bot_enabled)
VALUES
    (169, TRUE, TRUE, TRUE, FALSE),
    (170, TRUE, TRUE, TRUE, TRUE),
    (171, FALSE, TRUE, TRUE, FALSE),
    (172, FALSE, FALSE, TRUE, FALSE),
    (173, TRUE, TRUE, FALSE, FALSE)
ON CONFLICT (tenant_id) DO NOTHING;
