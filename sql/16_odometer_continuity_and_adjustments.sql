-- Axiom Mobility: Sequential Vehicle Odometer Continuity Tracking & Post-Invoice Adjustments
-- Migration: sql/16_odometer_continuity_and_adjustments.sql

-- 1. ODOMETER CONTINUITY TRACKING ON COMPLETED_TRIP_IMPORT_ROWS
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'completed_trip_import_rows') THEN
        ALTER TABLE public.completed_trip_import_rows ADD COLUMN IF NOT EXISTS prev_duty_id TEXT;
        ALTER TABLE public.completed_trip_import_rows ADD COLUMN IF NOT EXISTS prev_duty_end_km NUMERIC(10,1);
        ALTER TABLE public.completed_trip_import_rows ADD COLUMN IF NOT EXISTS dead_mileage_gap_km NUMERIC(10,1);
        ALTER TABLE public.completed_trip_import_rows ADD COLUMN IF NOT EXISTS odometer_continuity_status TEXT DEFAULT 'FIRST_VEHICLE_TRIP';
        ALTER TABLE public.completed_trip_import_rows ADD COLUMN IF NOT EXISTS continuity_message TEXT;
    END IF;
END $$;

-- 2. ODOMETER CONTINUITY TRACKING ON DUTIES / DOMAIN_DUTIES
DO $$
DECLARE
    target_tbl TEXT;
BEGIN
    FOR target_tbl IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename IN ('duties', 'domain_duties') LOOP
        EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS prev_duty_id TEXT;', target_tbl);
        EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS prev_duty_end_km NUMERIC(10,1);', target_tbl);
        EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS dead_mileage_gap_km NUMERIC(10,1);', target_tbl);
        EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS odometer_continuity_status TEXT DEFAULT ''FIRST_VEHICLE_TRIP'';', target_tbl);
        EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS invoice_status TEXT DEFAULT ''UNBILLED'';', target_tbl);
    END LOOP;
END $$;

-- 3. FINANCIAL CREDIT & DEBIT NOTES TABLE (POST-INVOICE TRIP ADJUSTMENTS)
CREATE TABLE IF NOT EXISTS public.financial_credit_debit_notes (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    original_duty_id TEXT NOT NULL,
    original_invoice_id TEXT,
    note_type TEXT NOT NULL CHECK (note_type IN ('CREDIT_NOTE_CLIENT', 'DEBIT_NOTE_CLIENT', 'CREDIT_NOTE_SUPPLIER', 'DEBIT_NOTE_SUPPLIER')),
    note_number TEXT NOT NULL UNIQUE,
    previous_amount_inr NUMERIC(12,2) NOT NULL,
    corrected_amount_inr NUMERIC(12,2) NOT NULL,
    delta_amount_inr NUMERIC(12,2) NOT NULL,
    gst_adjustment_inr NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    reason_code TEXT NOT NULL DEFAULT 'ODOMETER_PRICE_CORRECTION',
    remarks TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cdn_tenant_duty ON public.financial_credit_debit_notes(tenant_id, original_duty_id);
CREATE INDEX IF NOT EXISTS idx_cdn_invoice ON public.financial_credit_debit_notes(original_invoice_id);
