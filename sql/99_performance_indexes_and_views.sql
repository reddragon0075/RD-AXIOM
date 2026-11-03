-- ============================================================================
-- Axiom Mobility (Fleetline) - Performance Indexes & Bootstrap Function
-- Migration: 99_performance_indexes_and_views.sql
-- Optimizes hot operational queries, eliminates table scans, and provides
-- single-roundtrip workspace bootstrap aggregation for <100ms dashboard loads.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. High-Velocity Composite & Partial Indexes (PostgreSQL / Supabase)
-- ----------------------------------------------------------------------------

-- A. Live Operations & Dispatch Index (Composite on tenant, status, pickup date)
CREATE INDEX IF NOT EXISTS idx_duties_tenant_status_pickup
ON duties (tenant_id, status, pickup_datetime DESC);

-- B. Sequential Odometer Continuity Check (Partial Composite on completed vehicle duties)
-- Accelerates previous/next duty lookup from O(N) table scan to O(log N) B-Tree scan
CREATE INDEX IF NOT EXISTS idx_duties_vehicle_continuity
ON duties (tenant_id, vehicle_id, practical_end_time DESC)
WHERE status = 'COMPLETED';

-- C. External Trip-Sheet Dedup Index (Partial unique/lookup for bulk uploads)
CREATE INDEX IF NOT EXISTS idx_duties_tripsheet_dedup
ON duties (tenant_id, external_tripsheet_no)
WHERE external_tripsheet_no IS NOT NULL;

-- D. Axiom Treasury Hold & Release Gate Index (Dual-Ledger Supplier Release)
CREATE INDEX IF NOT EXISTS idx_supplier_ledger_release_gate
ON supplier_payable_ledger (tenant_id, vendor_id, status, eligible_for_release_at);

-- E. Native CRM Prospects Lookup Index (Fast mobile/email duplicate search)
CREATE INDEX IF NOT EXISTS idx_crm_prospects_lookup
ON sales_prospects (mobile_number, email_id, status);

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
    -- 1. Tenant Status & Treasury Global Hold Check
    SELECT COALESCE(status, 'ACTIVE_GOOD_STANDING'), COALESCE(treasury_hold_active, FALSE)
    INTO v_tenant_status, v_treasury_hold_active
    FROM organizations
    WHERE id = p_tenant_id;

    -- 2. Live Duty Counts
    SELECT
        COUNT(*) FILTER (WHERE status IN ('UNASSIGNED', 'DRAFT', 'CONFIRMED')),
        COUNT(*) FILTER (WHERE status IN ('DISPATCHED', 'EN_ROUTE', 'ARRIVED', 'IN_TRIP')),
        COUNT(*) FILTER (WHERE status = 'COMPLETED' AND (audit_status = 'FLAGGED' OR discrepancy_flag = TRUE)),
        COUNT(*) FILTER (WHERE status = 'COMPLETED' AND pickup_datetime::date = CURRENT_DATE)
    INTO v_unassigned_count, v_running_count, v_discrepancy_count, v_completed_today_count
    FROM duties
    WHERE tenant_id = p_tenant_id;

    -- 3. Dual-Ledger Summary (MTD)
    SELECT
        COALESCE(SUM(total_amount_inr), 0.0)
    INTO v_total_receivable
    FROM client_receivable_ledger
    WHERE tenant_id = p_tenant_id;

    SELECT
        COALESCE(SUM(payout_amount_inr), 0.0),
        COALESCE(SUM(CASE WHEN status = 'HOLD' OR eligible_for_release_at > NOW() THEN payout_amount_inr ELSE 0.0 END), 0.0),
        COALESCE(SUM(CASE WHEN status = 'AVAILABLE' AND eligible_for_release_at <= NOW() THEN payout_amount_inr ELSE 0.0 END), 0.0)
    INTO v_total_payable, v_held_float, v_withdrawable
    FROM supplier_payable_ledger
    WHERE tenant_id = p_tenant_id;

    -- 4. Super-Admin SaaS Summary (if applicable)
    IF p_user_role IN ('super_admin', 'platform_admin', 'axiom_support') THEN
        SELECT COUNT(*) INTO v_total_tenants FROM organizations;
        SELECT COUNT(*) INTO v_pending_prospects FROM sales_prospects WHERE status IN ('NEW_LEAD', 'DISCOVERY_CALL_SET');
        SELECT COALESCE(SUM(total_money_owed_inr), 0.0) INTO v_total_money_owed FROM platform_tenant_billing;
    END IF;

    -- Build consolidated payload
    v_result := jsonb_build_object(
        'status', 'ok',
        'tenant_id', p_tenant_id,
        'user_role', p_user_role,
        'server_timestamp', clock_timestamp(),
        'tenant_access', jsonb_build_object(
            'status', v_tenant_status,
            'treasury_hold_active', v_treasury_hold_active,
            'is_operational', (v_tenant_status != 'HARD_BLOCKED_NON_PAYMENT')
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
            WHEN p_user_role IN ('super_admin', 'platform_admin', 'axiom_support') THEN
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
