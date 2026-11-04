-- ═══════════════════════════════════════════════════════════════════════════
-- AXIOM FLEET ENTERPRISE - POSTGRESQL / SUPABASE ROW LEVEL SECURITY (RLS) LOCKDOWN
-- Migration: sql/98_rls_and_security_lockdown.sql
-- Enforces complete tenant isolation, super-admin gates & sensitive column masking
-- ═══════════════════════════════════════════════════════════════════════════

-- 1. ENABLE & FORCE RLS ON ALL SENSITIVE CORE & FINANCIAL ENTITIES
DO $$
DECLARE
    tbl text;
    sensitive_tables text[] := ARRAY[
        'users',
        'organizations',
        'corporate_accounts',
        'domain_customers',
        'domain_vehicles',
        'domain_drivers',
        'domain_bookings',
        'domain_duties',
        'domain_invoices',
        'tenant_platform_invoices',
        'axiom_receivable_ledger',
        'supplier_payable_ledger',
        'sales_prospects',
        'crm_accounts',
        'crm_deals',
        'completed_trip_import_batches',
        'financial_forecasts_cache'
    ];
BEGIN
    FOREACH tbl IN ARRAY sensitive_tables LOOP
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = tbl) THEN
            EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', tbl);
            EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY;', tbl);
        END IF;
    END LOOP;
END $$;

-- 2. HELPER MACROS FOR TENANT CONTEXT RESOLUTION
-- Checks auth.jwt() claims for Supabase, or app.current_tenant_id for native pooling
CREATE OR REPLACE FUNCTION current_axiom_tenant() RETURNS text AS $$
BEGIN
    RETURN COALESCE(
        current_setting('app.current_tenant_id', true),
        (current_setting('request.jwt.claims', true)::jsonb ->> 'organization_id'),
        (current_setting('request.jwt.claims', true)::jsonb ->> 'tenant_id')
    );
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

CREATE OR REPLACE FUNCTION is_axiom_super_admin() RETURNS boolean AS $$
BEGIN
    RETURN COALESCE(
        current_setting('app.current_user_role', true) IN ('superadmin', 'axiom_super_admin'),
        (current_setting('request.jwt.claims', true)::jsonb ->> 'role') IN ('superadmin', 'axiom_super_admin'),
        (current_setting('request.jwt.claims', true)::jsonb ->> 'is_axiom_hq') = 'true',
        false
    );
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- 3. TENANT ISOLATION POLICIES (TENANT CAN NEVER VIEW ANOTHER TENANT'S DATA)

-- A. USERS & PROFILES ISOLATION
DROP POLICY IF EXISTS tenant_users_isolation ON users;
CREATE POLICY tenant_users_isolation ON users
    FOR ALL TO authenticated
    USING (
        is_axiom_super_admin()
        OR organization_id = current_axiom_tenant()
        OR id = (current_setting('request.jwt.claims', true)::jsonb ->> 'sub')
    );

-- B. CORPORATE CLIENTS ISOLATION
DROP POLICY IF EXISTS tenant_corporate_isolation ON corporate_accounts;
CREATE POLICY tenant_corporate_isolation ON corporate_accounts
    FOR ALL TO authenticated
    USING (
        is_axiom_super_admin()
        OR organization_id = current_axiom_tenant()
    );

-- C. BOOKINGS & DUTIES ISOLATION
DROP POLICY IF EXISTS tenant_bookings_isolation ON domain_bookings;
CREATE POLICY tenant_bookings_isolation ON domain_bookings
    FOR ALL TO authenticated
    USING (
        is_axiom_super_admin()
        OR organization_id = current_axiom_tenant()
    );

DROP POLICY IF EXISTS tenant_duties_isolation ON domain_duties;
CREATE POLICY tenant_duties_isolation ON domain_duties
    FOR ALL TO authenticated
    USING (
        is_axiom_super_admin()
        OR organization_id = current_axiom_tenant()
    );

-- D. INVOICES & LEDGERS ISOLATION (ZERO CROSS-TENANT FINANCIAL LEAKAGE)
DROP POLICY IF EXISTS tenant_invoices_isolation ON domain_invoices;
CREATE POLICY tenant_invoices_isolation ON domain_invoices
    FOR ALL TO authenticated
    USING (
        is_axiom_super_admin()
        OR organization_id = current_axiom_tenant()
    );

DROP POLICY IF EXISTS tenant_platform_invoices_isolation ON tenant_platform_invoices;
CREATE POLICY tenant_platform_invoices_isolation ON tenant_platform_invoices
    FOR ALL TO authenticated
    USING (
        is_axiom_super_admin()
        OR tenant_id = current_axiom_tenant()
    );

DROP POLICY IF EXISTS tenant_supplier_payable_isolation ON supplier_payable_ledger;
CREATE POLICY tenant_supplier_payable_isolation ON supplier_payable_ledger
    FOR ALL TO authenticated
    USING (
        is_axiom_super_admin()
        OR organization_id = current_axiom_tenant()
    );

-- E. BULK IMPORTS & FINANCIAL FORECASTS ISOLATION
DROP POLICY IF EXISTS tenant_bulk_imports_isolation ON completed_trip_import_batches;
CREATE POLICY tenant_bulk_imports_isolation ON completed_trip_import_batches
    FOR ALL TO authenticated
    USING (
        is_axiom_super_admin()
        OR tenant_id = current_axiom_tenant()
    );

DROP POLICY IF EXISTS tenant_forecasts_cache_isolation ON financial_forecasts_cache;
CREATE POLICY tenant_forecasts_cache_isolation ON financial_forecasts_cache
    FOR ALL TO authenticated
    USING (
        is_axiom_super_admin()
        OR tenant_id = current_axiom_tenant()
    );

-- F. CRM ACCOUNTS & DEALS ISOLATION
DROP POLICY IF EXISTS tenant_crm_accounts_isolation ON crm_accounts;
CREATE POLICY tenant_crm_accounts_isolation ON crm_accounts
    FOR ALL TO authenticated
    USING (
        is_axiom_super_admin()
        OR tenant_id = current_axiom_tenant()
        OR organization_id = current_axiom_tenant()
    );

DROP POLICY IF EXISTS tenant_crm_deals_isolation ON crm_deals;
CREATE POLICY tenant_crm_deals_isolation ON crm_deals
    FOR ALL TO authenticated
    USING (
        is_axiom_super_admin()
        OR tenant_id = current_axiom_tenant()
    );

-- 4. SECURE USER VIEW EXCLUDING PASSWORD HASHES & AUTH SECRETS
-- Guarantees that public/tenant queries never serialize password digests
CREATE OR REPLACE VIEW v_safe_users AS
SELECT
    id,
    organization_id,
    email,
    role,
    full_name,
    phone,
    status,
    created_at,
    last_login_at
FROM users;

COMMENT ON VIEW v_safe_users IS 'Axiom Fleet secure user projection with password_hash and password_salt stripped.';
