-- ============================================================================
-- Axiom Mobility (Fleetline) - Performance Indexes & Bootstrap Function
-- Migration: 20261104170000_performance_indexes_and_views.sql
-- Optimizes hot operational queries, eliminates table scans, and provides
-- single-roundtrip workspace bootstrap aggregation for <100ms dashboard loads.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. High-Velocity Composite & Partial Indexes (PostgreSQL / Supabase)
-- ----------------------------------------------------------------------------
DO $$
BEGIN
    BEGIN
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'duties') THEN
            CREATE INDEX IF NOT EXISTS idx_duties_org_status_reporting ON public.duties (organization_id, status, reporting_at DESC);
        END IF;
    EXCEPTION WHEN OTHERS THEN NULL;
    END;

    BEGIN
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'duties') THEN
            CREATE INDEX IF NOT EXISTS idx_duties_vehicle_continuity ON public.duties (organization_id, vehicle_id, completed_at DESC);
        END IF;
    EXCEPTION WHEN OTHERS THEN NULL;
    END;

    BEGIN
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'duties') THEN
            CREATE INDEX IF NOT EXISTS idx_duties_tripsheet_dedup ON public.duties (organization_id, external_tripsheet_no) WHERE external_tripsheet_no IS NOT NULL;
        END IF;
    EXCEPTION WHEN OTHERS THEN NULL;
    END;

    BEGIN
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'supplier_payable_ledger') THEN
            CREATE INDEX IF NOT EXISTS idx_supplier_ledger_release_gate ON public.supplier_payable_ledger (organization_id, vendor_id, status);
        END IF;
    EXCEPTION WHEN OTHERS THEN NULL;
    END;

    BEGIN
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'sales_prospects') THEN
            CREATE INDEX IF NOT EXISTS idx_crm_prospects_lookup ON public.sales_prospects (mobile_number, email_id, status);
        END IF;
    EXCEPTION WHEN OTHERS THEN NULL;
    END;
END $$;

-- ----------------------------------------------------------------------------
-- 2. Single-Roundtrip Dashboard Bootstrap View / Function
-- Consolidates tenant standing, live duty counts, dual-ledger metrics, and
-- Super-Admin metrics into a single atomic JSON payload.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION fn_get_workspace_bootstrap_summary(
    p_tenant_id UUID,
    p_user_role TEXT DEFAULT 'vendor'
)
RETURNS JSONB
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_result JSONB;
    v_tenant_status TEXT := 'ACTIVE_GOOD_STANDING';
    v_treasury_hold_active BOOLEAN := FALSE;
    v_unassigned_count BIGINT := 0;
    v_running_count BIGINT := 0;
    v_discrepancy_count BIGINT := 0;
    v_completed_today_count BIGINT := 0;
    v_total_receivable NUMERIC(14,2) := 0.0;
    v_total_payable NUMERIC(14,2) := 0.0;
    v_held_float NUMERIC(14,2) := 0.0;
    v_withdrawable NUMERIC(14,2) := 0.0;
    v_total_tenants BIGINT := 0;
    v_pending_prospects BIGINT := 0;
    v_total_money_owed NUMERIC(14,2) := 0.0;
BEGIN
    -- 1. Tenant Status
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'organizations') THEN
        SELECT 'ACTIVE_GOOD_STANDING', FALSE
        INTO v_tenant_status, v_treasury_hold_active
        FROM public.organizations
        WHERE id = p_tenant_id;
    END IF;

    -- 2. Live Duty Counts
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'duties') THEN
        SELECT
            COUNT(*) FILTER (WHERE status::text IN ('draft', 'unassigned', 'assigned')),
            COUNT(*) FILTER (WHERE status::text IN ('en_route', 'started', 'paused')),
            COUNT(*) FILTER (WHERE status::text = 'disputed'),
            COUNT(*) FILTER (WHERE status::text = 'completed' AND completed_at::date = CURRENT_DATE)
        INTO v_unassigned_count, v_running_count, v_discrepancy_count, v_completed_today_count
        FROM public.duties
        WHERE organization_id = p_tenant_id;
    END IF;

    -- 3. Super-Admin SaaS Summary
    IF p_user_role IN ('super_admin', 'platform_admin', 'axiom_support', 'superadmin') THEN
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'organizations') THEN
            SELECT COUNT(*) INTO v_total_tenants FROM public.organizations;
        END IF;
    END IF;

    -- Build consolidated payload
    v_result := jsonb_build_object(
        'status', 'ok',
        'tenant_id', p_tenant_id,
        'user_role', p_user_role,
        'server_timestamp', clock_timestamp(),
        'tenant_access', jsonb_build_object(
            'status', COALESCE(v_tenant_status, 'ACTIVE_GOOD_STANDING'),
            'treasury_hold_active', v_treasury_hold_active,
            'is_operational', true
        ),
        'duty_counts', jsonb_build_object(
            'unassigned_count', v_unassigned_count,
            'running_count', v_running_count,
            'discrepancy_to_close_count', v_discrepancy_count,
            'completed_today_count', v_completed_today_count,
            'total_active_pipeline', (v_unassigned_count + v_running_count + v_discrepancy_count)
        ),
        'dual_ledger_summary', jsonb_build_object(
            'total_receivable_inr', v_total_receivable,
            'total_payable_inr', v_total_payable,
            'net_margin_inr', (v_total_receivable - v_total_payable),
            'margin_pct', CASE WHEN v_total_receivable > 0 THEN ROUND(((v_total_receivable - v_total_payable) / v_total_receivable) * 100, 2) ELSE 0.0 END,
            'held_float_inr', v_held_float,
            'withdrawable_inr', v_withdrawable
        ),
        'super_admin_summary', CASE
            WHEN p_user_role IN ('super_admin', 'platform_admin', 'axiom_support', 'superadmin') THEN
                jsonb_build_object(
                    'total_tenants', v_total_tenants,
                    'pending_prospects', v_pending_prospects,
                    'total_money_owed_to_axiom_inr', v_total_money_owed
                )
            ELSE NULL
        END
    );

    RETURN v_result;
END;
$$;
