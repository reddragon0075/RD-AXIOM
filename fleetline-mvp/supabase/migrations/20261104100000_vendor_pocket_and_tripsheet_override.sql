-- Axiom Mobility: Vendor Mobile Pocket App, Theoretical vs. Practical Fare Engine
-- and Physical Trip-Sheet Discrepancy Override Migration
-- File: sql/11_vendor_pocket_and_tripsheet_override.sql

-- 1. DUTIES / TRIPS THEORETICAL VS PRACTICAL PRICING SCHEMA UPGRADE
DO $$
BEGIN
    -- Ensure closing_source enum type exists if not created
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'closing_source_type') THEN
        CREATE TYPE closing_source_type AS ENUM (
            'DRIVER_APP_AUTO',
            'OPERATOR_PRACTICAL_ENTRY',
            'PHYSICAL_TRIPSHEET_OVERRIDE'
        );
    END IF;
END $$;

-- Upgrade public.duties table (or domain_duties if public.duties does not exist)
DO $$
DECLARE
    target_table TEXT := 'duties';
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'duties') THEN
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'domain_duties') THEN
            target_table := 'domain_duties';
        ELSE
            -- Create public.duties if neither exists
            CREATE TABLE IF NOT EXISTS public.duties (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                booking_id TEXT NOT NULL,
                driver_id TEXT,
                vehicle_id TEXT,
                supplier_id TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                reporting_at TIMESTAMPTZ,
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            target_table := 'duties';
        END IF;
    END IF;

    -- A. Theoretical Baseline (Locked at Booking / Dispatch)
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS estimated_start_km NUMERIC(10,1);', target_table);
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS estimated_end_km NUMERIC(10,1);', target_table);
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS estimated_distance_km NUMERIC(10,1) DEFAULT 0.0;', target_table);
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS estimated_duration_mins INTEGER DEFAULT 0;', target_table);
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS estimated_client_fare_inr NUMERIC(12,2) DEFAULT 0.00;', target_table);
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS estimated_supplier_payout_inr NUMERIC(12,2) DEFAULT 0.00;', target_table);

    -- B. Driver App Telemetry Capture (Captured automatically by Driver PWA)
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS app_captured_start_km NUMERIC(10,1);', target_table);
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS app_captured_end_km NUMERIC(10,1);', target_table);
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS app_gps_distance_km NUMERIC(10,1) DEFAULT 0.0;', target_table);
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS app_start_time TIMESTAMPTZ;', target_table);
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS app_end_time TIMESTAMPTZ;', target_table);

    -- C. Practical Final Values (Authoritative Billing Source of Truth)
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS practical_start_km NUMERIC(10,1);', target_table);
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS practical_end_km NUMERIC(10,1);', target_table);
    
    -- Generated billable km: GREATEST(0, practical_end_km - practical_start_km)
    -- Check if column exists, if not add generated column
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = target_table AND column_name = 'practical_billable_km'
    ) THEN
        BEGIN
            EXECUTE format('ALTER TABLE public.%I ADD COLUMN practical_billable_km NUMERIC(10,1) GENERATED ALWAYS AS (GREATEST(0, practical_end_km - practical_start_km)) STORED;', target_table);
        EXCEPTION WHEN OTHERS THEN
            -- Fallback for environments with standard numeric column
            EXECUTE format('ALTER TABLE public.%I ADD COLUMN practical_billable_km NUMERIC(10,1);', target_table);
        END;
    END IF;

    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS practical_start_time TIMESTAMPTZ;', target_table);
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS practical_end_time TIMESTAMPTZ;', target_table);
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS practical_duration_mins INTEGER DEFAULT 0;', target_table);
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS final_client_fare_inr NUMERIC(12,2) DEFAULT 0.00;', target_table);
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS final_supplier_payout_inr NUMERIC(12,2) DEFAULT 0.00;', target_table);

    -- D. Capture Source & Discrepancy Metadata
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS closing_source TEXT NOT NULL DEFAULT ''DRIVER_APP_AUTO'';', target_table);
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS has_discrepancy BOOLEAN NOT NULL DEFAULT FALSE;', target_table);
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS discrepancy_reason TEXT;', target_table);
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS physical_tripsheet_file_url TEXT;', target_table);
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS physical_tripsheet_uploaded_by TEXT;', target_table);
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS physical_tripsheet_uploaded_at TIMESTAMPTZ;', target_table);
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS closed_by_operator_id TEXT;', target_table);

    -- Add source check constraint if not already present
    BEGIN
        EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT chk_closing_source CHECK (closing_source IN (''DRIVER_APP_AUTO'', ''OPERATOR_PRACTICAL_ENTRY'', ''PHYSICAL_TRIPSHEET_OVERRIDE''));', target_table);
    EXCEPTION WHEN duplicate_object THEN
        NULL;
    END;
END $$;

-- 2. MANDATORY PROOF TRIGGER & CHECK CONSTRAINT
-- Enforce: If closing_source = 'PHYSICAL_TRIPSHEET_OVERRIDE' OR has_discrepancy = true,
-- then physical_tripsheet_file_url MUST NOT BE NULL AND discrepancy_reason MUST NOT BE NULL.
CREATE OR REPLACE FUNCTION check_physical_tripsheet_proof_requirement()
RETURNS TRIGGER AS $$
BEGIN
    IF (NEW.closing_source = 'PHYSICAL_TRIPSHEET_OVERRIDE' OR NEW.has_discrepancy = TRUE) THEN
        IF (NEW.physical_tripsheet_file_url IS NULL OR BTRIM(NEW.physical_tripsheet_file_url) = '') OR
           (NEW.discrepancy_reason IS NULL OR BTRIM(NEW.discrepancy_reason) = '') THEN
            RAISE EXCEPTION '422 PHYSICAL_TRIPSHEET_PROOF_REQUIRED: When closing via PHYSICAL_TRIPSHEET_OVERRIDE or reporting a discrepancy, physical_tripsheet_file_url and discrepancy_reason are strictly required.'
                USING ERRCODE = '23514'; -- check_violation
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'duties') THEN
        DROP TRIGGER IF EXISTS trg_duties_physical_tripsheet_proof ON public.duties;
        CREATE TRIGGER trg_duties_physical_tripsheet_proof
            BEFORE INSERT OR UPDATE ON public.duties
            FOR EACH ROW
            EXECUTE FUNCTION check_physical_tripsheet_proof_requirement();
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'domain_duties') THEN
        DROP TRIGGER IF EXISTS trg_domain_duties_physical_tripsheet_proof ON public.domain_duties;
        CREATE TRIGGER trg_domain_duties_physical_tripsheet_proof
            BEFORE INSERT OR UPDATE ON public.domain_duties
            FOR EACH ROW
            EXECUTE FUNCTION check_physical_tripsheet_proof_requirement();
    END IF;
END $$;

-- 3. AUDIT & DISCREPANCY LOGS TABLE
CREATE TABLE IF NOT EXISTS public.duty_tripsheet_audit_logs (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    duty_id TEXT NOT NULL,
    closing_source TEXT NOT NULL,
    estimated_distance_km NUMERIC(10,1),
    estimated_client_fare_inr NUMERIC(12,2),
    practical_billable_km NUMERIC(10,1),
    final_client_fare_inr NUMERIC(12,2),
    km_variance_delta NUMERIC(10,1),
    fare_variance_delta NUMERIC(12,2),
    has_discrepancy BOOLEAN NOT NULL DEFAULT FALSE,
    discrepancy_reason TEXT,
    physical_tripsheet_file_url TEXT,
    closed_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4. PERFORMANCE & FILTER INDEXES
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'duties') THEN
        CREATE INDEX IF NOT EXISTS idx_duties_closing_source ON public.duties(closing_source);
        CREATE INDEX IF NOT EXISTS idx_duties_discrepancy ON public.duties(has_discrepancy) WHERE has_discrepancy = TRUE;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'domain_duties') THEN
        CREATE INDEX IF NOT EXISTS idx_domain_duties_closing_source ON public.domain_duties(closing_source);
        CREATE INDEX IF NOT EXISTS idx_domain_duties_discrepancy ON public.domain_duties(has_discrepancy) WHERE has_discrepancy = TRUE;
    END IF;
END $$;
