-- Axiom Mobility: Hyper-Network Exchange & Market Disruption Engine Migration
-- Specification: White-label ghost mode, timed waterfall cascades, pre-authorized escrow,
-- T+0 instant factoring, empty-leg return matchmaker, EV SoC range verification, and ZK compliance seals.

-- 1. NETWORK LISTINGS (Marketplace Exchange Feed)
CREATE TABLE IF NOT EXISTS network_listings (
    id TEXT PRIMARY KEY,
    duty_id TEXT NOT NULL,
    origin_vendor_id TEXT NOT NULL,
    origin_vendor_name TEXT NOT NULL,
    client_brand_display_name TEXT NOT NULL,
    client_support_phone TEXT NOT NULL DEFAULT '+918069008800',
    client_logo_url TEXT NOT NULL DEFAULT '',
    trip_class TEXT NOT NULL DEFAULT 'Executive Sedan',
    city TEXT NOT NULL DEFAULT 'Bengaluru',
    zone TEXT NOT NULL DEFAULT 'HSR_KORAMANGALA',
    pickup_address TEXT NOT NULL,
    dropoff_address TEXT NOT NULL,
    reporting_time TIMESTAMPTZ NOT NULL,
    estimated_distance_km REAL NOT NULL DEFAULT 0.0,
    client_receivable_paise BIGINT NOT NULL DEFAULT 0,
    base_supplier_payable_paise BIGINT NOT NULL DEFAULT 0,
    surge_boost_pct REAL NOT NULL DEFAULT 0.0,
    boosted_supplier_payable_paise BIGINT NOT NULL DEFAULT 0,
    margin_floor_pct REAL NOT NULL DEFAULT 12.0,
    status TEXT NOT NULL DEFAULT 'BROADCASTING' CHECK (status IN ('BROADCASTING', 'CLAIMED', 'ALLOTTED', 'IN_PROGRESS', 'COMPLETED', 'EXPIRED', 'CANCELLED')),
    current_wave INTEGER NOT NULL DEFAULT 1 CHECK (current_wave IN (1, 2, 3)),
    wave_expires_at TIMESTAMPTZ NOT NULL,
    prefer_ev_green_corridor BOOLEAN NOT NULL DEFAULT FALSE,
    claimed_by_vendor_id TEXT,
    claimed_by_vendor_name TEXT,
    claimed_at TIMESTAMPTZ,
    allotted_driver_id TEXT,
    allotted_vehicle_id TEXT,
    zk_compliance_seal_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_network_listings_status ON network_listings(status, current_wave);
CREATE INDEX IF NOT EXISTS idx_network_listings_origin ON network_listings(origin_vendor_id);
CREATE INDEX IF NOT EXISTS idx_network_listings_claimed ON network_listings(claimed_by_vendor_id);

-- 2. WATERFALL WAVES AUDIT
CREATE TABLE IF NOT EXISTS network_waterfall_waves (
    id TEXT PRIMARY KEY,
    listing_id TEXT NOT NULL REFERENCES network_listings(id) ON DELETE CASCADE,
    wave_number INTEGER NOT NULL CHECK (wave_number IN (1, 2, 3)),
    eligible_tier TEXT NOT NULL CHECK (eligible_tier IN ('TIER_1_PLATINUM', 'TIER_2_GOLD', 'TIER_3_SILVER', 'MARKETPLACE')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_waterfall_listing ON network_waterfall_waves(listing_id, wave_number);

-- 3. WALLET ESCROW HOLDS
CREATE TABLE IF NOT EXISTS wallet_escrow_holds (
    id TEXT PRIMARY KEY,
    listing_id TEXT NOT NULL,
    origin_vendor_id TEXT NOT NULL,
    fulfilling_vendor_id TEXT,
    escrow_amount_paise BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ESCROW_HOLD' CHECK (status IN ('ESCROW_HOLD', 'SETTLED_PAYABLE', 'DISPUTED', 'RELEASED_REFUND')),
    hold_placed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    settled_at TIMESTAMPTZ,
    auto_settle_eligible_at TIMESTAMPTZ,
    dispute_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wallet_escrow_listing ON wallet_escrow_holds(listing_id);
CREATE INDEX IF NOT EXISTS idx_wallet_escrow_origin ON wallet_escrow_holds(origin_vendor_id, status);

-- 4. T+0 INSTANT FACTORING TRANSACTIONS
CREATE TABLE IF NOT EXISTS t0_factoring_transactions (
    id TEXT PRIMARY KEY,
    listing_id TEXT NOT NULL,
    duty_id TEXT NOT NULL,
    vendor_id TEXT NOT NULL,
    gross_payable_paise BIGINT NOT NULL,
    factoring_fee_pct REAL NOT NULL DEFAULT 1.75,
    factoring_fee_paise BIGINT NOT NULL,
    net_disbursement_paise BIGINT NOT NULL,
    payout_status TEXT NOT NULL DEFAULT 'DISBURSED_T0' CHECK (payout_status IN ('PENDING', 'DISBURSED_T0', 'FAILED')),
    disbursed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_t0_factoring_vendor ON t0_factoring_transactions(vendor_id);

-- 5. EMPTY-LEG RETURN CORRIDORS
CREATE TABLE IF NOT EXISTS empty_leg_corridors (
    id TEXT PRIMARY KEY,
    vendor_id TEXT NOT NULL,
    vendor_name TEXT NOT NULL,
    origin_city TEXT NOT NULL,
    destination_city TEXT NOT NULL,
    corridor_name TEXT NOT NULL,
    vehicle_id TEXT NOT NULL,
    vehicle_category TEXT NOT NULL,
    fuel_type TEXT NOT NULL DEFAULT 'DIESEL',
    available_window_start TIMESTAMPTZ NOT NULL,
    available_window_end TIMESTAMPTZ NOT NULL,
    discounted_partner_rate_per_km REAL NOT NULL,
    standard_rate_per_km REAL NOT NULL,
    discount_pct REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'AVAILABLE' CHECK (status IN ('AVAILABLE', 'MATCHED', 'EXPIRED', 'COMPLETED')),
    matched_booking_id TEXT,
    matched_vendor_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_empty_legs_corridor ON empty_leg_corridors(origin_city, destination_city, status);

-- 6. ZERO-KNOWLEDGE COMPLIANCE SEALS
CREATE TABLE IF NOT EXISTS zk_compliance_seals (
    id TEXT PRIMARY KEY,
    duty_id TEXT NOT NULL UNIQUE,
    listing_id TEXT,
    fulfilling_vendor_id TEXT NOT NULL,
    vehicle_id TEXT NOT NULL,
    driver_id TEXT NOT NULL,
    compliance_snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    verification_hash TEXT NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT NOT NULL DEFAULT 'VERIFIED'
);

CREATE INDEX IF NOT EXISTS idx_zk_seals_duty ON zk_compliance_seals(duty_id);

-- 7. ADD EV BATTERY & RANGE COLUMNS TO VEHICLES IF NOT PRESENT
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'vehicles') THEN
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'vehicles' AND column_name = 'ev_battery_soc_pct') THEN
            ALTER TABLE public.vehicles ADD COLUMN IF NOT EXISTS ev_battery_soc_pct REAL DEFAULT 100.0;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'vehicles' AND column_name = 'estimated_range_km') THEN
            ALTER TABLE public.vehicles ADD COLUMN IF NOT EXISTS estimated_range_km REAL DEFAULT 300.0;
        END IF;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'domain_vehicles') THEN
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'domain_vehicles' AND column_name = 'ev_battery_soc_pct') THEN
            ALTER TABLE public.domain_vehicles ADD COLUMN IF NOT EXISTS ev_battery_soc_pct REAL DEFAULT 100.0;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'domain_vehicles' AND column_name = 'estimated_range_km') THEN
            ALTER TABLE public.domain_vehicles ADD COLUMN IF NOT EXISTS estimated_range_km REAL DEFAULT 300.0;
        END IF;
    END IF;
END $$;
