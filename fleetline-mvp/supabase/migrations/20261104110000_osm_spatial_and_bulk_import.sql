-- Axiom Mobility: OpenStreetMap (OSM) Spatial Cache & Completed Trips Bulk Upload Schema
-- Migration: sql/12_osm_spatial_and_bulk_import.sql

-- 1. OSM GEOCODING CACHE TABLE
-- Caches Indian address lookups & landmarks to resolve in <5ms without external rate limits
CREATE TABLE IF NOT EXISTS public.osm_geocoding_cache (
    query_normalized TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    lat NUMERIC(10, 7) NOT NULL,
    lng NUMERIC(10, 7) NOT NULL,
    city TEXT NOT NULL DEFAULT 'Bengaluru',
    pincode TEXT,
    hit_count INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_osm_geocoding_city ON public.osm_geocoding_cache(city);

-- 2. OSM ROUTE MATRIX CACHE TABLE
-- Caches origin-destination geohash-6 pairs for lightning-fast theoretical estimates
CREATE TABLE IF NOT EXISTS public.osm_route_matrix_cache (
    id TEXT PRIMARY KEY,
    origin_geohash_6 TEXT NOT NULL,
    dest_geohash_6 TEXT NOT NULL,
    road_distance_km NUMERIC(10, 2) NOT NULL,
    typical_duration_mins INTEGER NOT NULL,
    encoded_polyline TEXT,
    hit_count INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(origin_geohash_6, dest_geohash_6)
);

CREATE INDEX IF NOT EXISTS idx_osm_route_geohash ON public.osm_route_matrix_cache(origin_geohash_6, dest_geohash_6);

-- 3. COMPLETED TRIPS BULK IMPORT BATCHES
CREATE TABLE IF NOT EXISTS public.completed_trip_import_batches (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    uploaded_by TEXT NOT NULL,
    filename TEXT NOT NULL,
    total_rows INTEGER NOT NULL DEFAULT 0,
    valid_rows INTEGER NOT NULL DEFAULT 0,
    warning_rows INTEGER NOT NULL DEFAULT 0,
    error_rows INTEGER NOT NULL DEFAULT 0,
    duplicate_rows INTEGER NOT NULL DEFAULT 0,
    estimated_total_receivable_inr NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    estimated_total_payable_inr NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    status TEXT NOT NULL DEFAULT 'STAGED_DRY_RUN' CHECK (status IN ('STAGED_DRY_RUN', 'COMMITTED', 'CANCELLED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trip_import_tenant ON public.completed_trip_import_batches(tenant_id, status);

-- 4. COMPLETED TRIPS BULK IMPORT STAGING ROWS
CREATE TABLE IF NOT EXISTS public.completed_trip_import_rows (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES public.completed_trip_import_batches(id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    row_number INTEGER NOT NULL,
    raw_json TEXT NOT NULL DEFAULT '{}',
    normalized_payload TEXT NOT NULL DEFAULT '{}',
    validation_status TEXT NOT NULL DEFAULT 'VALID' CHECK (validation_status IN ('VALID', 'WARNING_VARIANCE', 'ERROR_MISSING_REF', 'DUPLICATE_TRIPSHEET')),
    validation_messages TEXT NOT NULL DEFAULT '[]',
    computed_client_fare_inr NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    computed_supplier_payout_inr NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    applied_slab_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_import_rows_batch_status ON public.completed_trip_import_rows(batch_id, validation_status);

-- 5. UPGRADE DUTIES TABLE FOR BULK IMPORT PROVENANCE & EXTERNAL TRIP SHEET NO
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'duties') THEN
        ALTER TABLE public.duties ADD COLUMN IF NOT EXISTS external_tripsheet_no TEXT;
        ALTER TABLE public.duties ADD COLUMN IF NOT EXISTS import_batch_id TEXT;
        CREATE INDEX IF NOT EXISTS idx_duties_ext_tripsheet ON public.duties(organization_id, external_tripsheet_no);
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'domain_duties') THEN
        ALTER TABLE public.domain_duties ADD COLUMN IF NOT EXISTS external_tripsheet_no TEXT;
        ALTER TABLE public.domain_duties ADD COLUMN IF NOT EXISTS import_batch_id TEXT;
        CREATE INDEX IF NOT EXISTS idx_domain_duties_ext_tripsheet ON public.domain_duties(organization_id, external_tripsheet_no);
    END IF;
END $$;
