-- Axiom Mobility: Dual-Ledger Fund Release Hold & Treasury Control Toggle Migration
-- Specification: Global treasury freeze toggle, configurable cooling hold hours (72h default),
-- per-vendor payout hold override, supplier payable ledger state machine, and immutable audit logs.

-- 1. PLATFORM SETTINGS (Global Treasury & Float Control)
CREATE TABLE IF NOT EXISTS platform_settings (
    id TEXT PRIMARY KEY DEFAULT 'global_default',
    global_payout_release_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    default_fund_hold_hours INTEGER NOT NULL DEFAULT 72,
    t0_instant_cashout_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO platform_settings (id, global_payout_release_enabled, default_fund_hold_hours, t0_instant_cashout_enabled)
VALUES ('global_default', FALSE, 72, TRUE)
ON CONFLICT (id) DO NOTHING;

-- 2. TENANT / VENDOR PAYOUT HOLD CONTROLS
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'tenant_billing_accounts') THEN
        ALTER TABLE tenant_billing_accounts ADD COLUMN IF NOT EXISTS payout_hold_override TEXT NOT NULL DEFAULT 'INHERIT_GLOBAL';
        ALTER TABLE tenant_billing_accounts ADD COLUMN IF NOT EXISTS payout_hold_reason TEXT;
        ALTER TABLE tenant_billing_accounts ADD COLUMN IF NOT EXISTS payout_hold_updated_by TEXT;
        ALTER TABLE tenant_billing_accounts ADD COLUMN IF NOT EXISTS payout_hold_updated_at TIMESTAMPTZ;
    END IF;
END $$;

-- 3. UPGRADED SUPPLIER PAYABLE LEDGER
CREATE TABLE IF NOT EXISTS supplier_payable_ledger (
    id TEXT PRIMARY KEY,
    duty_id TEXT NOT NULL,
    vendor_id TEXT NOT NULL,
    amount_paise BIGINT NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ESCROW_LOCKED' CHECK (status IN ('ESCROW_LOCKED', 'AUDIT_HOLD', 'FUNDS_HELD_BY_AXIOM', 'READY_FOR_RELEASE', 'RELEASED_TO_WALLET')),
    audit_passed_at TIMESTAMPTZ,
    eligible_for_release_at TIMESTAMPTZ,
    staff_hold_locked BOOLEAN NOT NULL DEFAULT TRUE,
    released_by_staff_id TEXT,
    released_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_spl_vendor_status ON supplier_payable_ledger(vendor_id, status);
CREATE INDEX IF NOT EXISTS idx_spl_eligibility ON supplier_payable_ledger(status, eligible_for_release_at);

-- 4. IMMUTABLE TREASURY AUDIT LOGS
CREATE TABLE IF NOT EXISTS treasury_release_audit_logs (
    id TEXT PRIMARY KEY,
    actor_staff_id TEXT NOT NULL,
    action_type TEXT NOT NULL CHECK (action_type IN ('GLOBAL_TOGGLE', 'VENDOR_TOGGLE', 'BATCH_MANUAL_RELEASE', 'FORCE_RELEASE')),
    target_vendor_id TEXT,
    previous_state TEXT,
    new_state TEXT,
    total_amount_affected_inr REAL NOT NULL DEFAULT 0.0,
    reason_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_treasury_logs_vendor ON treasury_release_audit_logs(target_vendor_id);
CREATE INDEX IF NOT EXISTS idx_treasury_logs_action ON treasury_release_audit_logs(action_type, created_at DESC);
