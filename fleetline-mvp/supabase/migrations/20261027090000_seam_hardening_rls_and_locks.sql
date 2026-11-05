-- Axiom Mobility (Fleetline) Seam Hardening: RLS Policies, State Locks & Audit Guarantees
-- Migration: 20261027090000_seam_hardening_rls_and_locks.sql

-- 1. SAAS MANAGEMENT WRITE POLICIES FOR PLATFORM SUPERADMINS
DROP POLICY IF EXISTS superadmin_wallets_write ON tenant_wallets;
CREATE POLICY superadmin_wallets_write ON tenant_wallets
    FOR ALL TO authenticated
    USING (auth.jwt() ->> 'role' IN ('admin', 'superadmin') OR auth.jwt() ->> 'is_axiom_hq' = 'true')
    WITH CHECK (auth.jwt() ->> 'role' IN ('admin', 'superadmin') OR auth.jwt() ->> 'is_axiom_hq' = 'true');

DROP POLICY IF EXISTS superadmin_flags_write ON tenant_feature_flags;
CREATE POLICY superadmin_flags_write ON tenant_feature_flags
    FOR ALL TO authenticated
    USING (auth.jwt() ->> 'role' IN ('admin', 'superadmin') OR auth.jwt() ->> 'is_axiom_hq' = 'true')
    WITH CHECK (auth.jwt() ->> 'role' IN ('admin', 'superadmin') OR auth.jwt() ->> 'is_axiom_hq' = 'true');

-- 2. PARTNER NETWORK SLA PROFILES & BREACHES RLS ISOLATION
ALTER TABLE tristack_partner_sla_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE tristack_sla_breaches ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_view_own_sla_profile ON tristack_partner_sla_profiles;
CREATE POLICY tenant_view_own_sla_profile ON tristack_partner_sla_profiles
    FOR SELECT TO authenticated
    USING (
        organization_id::text = (auth.jwt() ->> 'organization_id')
        OR auth.jwt() ->> 'role' IN ('admin', 'superadmin')
        OR auth.jwt() ->> 'is_axiom_hq' = 'true'
    );

DROP POLICY IF EXISTS tenant_view_own_sla_breaches ON tristack_sla_breaches;
CREATE POLICY tenant_view_own_sla_breaches ON tristack_sla_breaches
    FOR SELECT TO authenticated
    USING (
        organization_id::text = (auth.jwt() ->> 'organization_id')
        OR auth.jwt() ->> 'role' IN ('admin', 'superadmin')
        OR auth.jwt() ->> 'is_axiom_hq' = 'true'
    );

DROP POLICY IF EXISTS admin_manage_sla ON tristack_partner_sla_profiles;
CREATE POLICY admin_manage_sla ON tristack_partner_sla_profiles
    FOR ALL TO authenticated
    USING (auth.jwt() ->> 'role' IN ('admin', 'superadmin') OR auth.jwt() ->> 'is_axiom_hq' = 'true')
    WITH CHECK (auth.jwt() ->> 'role' IN ('admin', 'superadmin') OR auth.jwt() ->> 'is_axiom_hq' = 'true');

DROP POLICY IF EXISTS admin_manage_sla_breaches ON tristack_sla_breaches;
CREATE POLICY admin_manage_sla_breaches ON tristack_sla_breaches
    FOR ALL TO authenticated
    USING (auth.jwt() ->> 'role' IN ('admin', 'superadmin') OR auth.jwt() ->> 'is_axiom_hq' = 'true')
    WITH CHECK (auth.jwt() ->> 'role' IN ('admin', 'superadmin') OR auth.jwt() ->> 'is_axiom_hq' = 'true');

-- 3. STATE-MACHINE MUTATION LOCKS ON DUTIES & INVOICES
-- Prevents authenticated clients from directly mutating completed, invoiced, or locked duty slips
DROP POLICY IF EXISTS duties_state_lock_guard ON public.duties;
CREATE POLICY duties_state_lock_guard ON public.duties
    FOR UPDATE TO authenticated
    USING (
        (status::text NOT IN ('completed', 'invoiced', 'locked')
         OR auth.jwt() ->> 'role' IN ('admin', 'superadmin')
         OR auth.jwt() ->> 'is_axiom_hq' = 'true')
        AND (public.has_permission(organization_id, 'duties.write') OR public.is_platform_user())
    )
    WITH CHECK (
        (status::text NOT IN ('completed', 'invoiced', 'locked')
         OR auth.jwt() ->> 'role' IN ('admin', 'superadmin')
         OR auth.jwt() ->> 'is_axiom_hq' = 'true')
        AND (public.has_permission(organization_id, 'duties.write') OR public.is_platform_user())
    );

-- Prevents mutation of finalized / issued invoices
DROP POLICY IF EXISTS invoices_state_lock_guard ON public.invoices;
CREATE POLICY invoices_state_lock_guard ON public.invoices
    FOR UPDATE TO authenticated
    USING (
        (status::text NOT IN ('issued', 'paid', 'locked')
         OR auth.jwt() ->> 'role' IN ('admin', 'superadmin')
         OR auth.jwt() ->> 'is_axiom_hq' = 'true')
        AND (public.has_permission(organization_id, 'billing.write') OR public.is_platform_user())
    )
    WITH CHECK (
        (status::text NOT IN ('issued', 'paid', 'locked')
         OR auth.jwt() ->> 'role' IN ('admin', 'superadmin')
         OR auth.jwt() ->> 'is_axiom_hq' = 'true')
        AND (public.has_permission(organization_id, 'billing.write') OR public.is_platform_user())
    );
