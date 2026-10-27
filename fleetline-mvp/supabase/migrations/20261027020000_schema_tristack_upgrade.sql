-- ============================================================================
-- AXIOM MOBILITY (FLEETLINE) "TRI-STACK" ENTERPRISE UPGRADE MIGRATION
-- Benchmark: MoveInSync (ETMS/Safety) + Routematic (SLA/Rings) + Indecab (Dual-Ledger/ERP)
-- Migration: 20261027020000_schema_tristack_upgrade.sql
-- ============================================================================

-- Extensions for spatial route indexing
create extension if not exists postgis;
create extension if not exists "uuid-ossp";

-- ============================================================================
-- 1. ENUMS & DOMAIN CONSTANTS
-- ============================================================================

do $$ begin
  create type public.billing_mode_enum as enum (
    'HR_KM_SLAB',
    'OUTSTATION_CALENDAR_DAY',
    'RADIAL_ZONE_RING',
    'PER_SEAT_SHARED_POOL',
    'MONTHLY_DEDICATED_FIXED_VARIABLE',
    'FUEL_INDEXED_BACK_TO_BACK'
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type public.garage_matrix_enum as enum (
    'G2G_ACTUAL',
    'G2G_FIXED_BUFFER',
    'P2P_STRICT'
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type public.vendor_tier_enum as enum (
    'TIER_1_PLATINUM',
    'TIER_2_GOLD',
    'TIER_3_SILVER',
    'PROBATION',
    'BLOCKED'
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type public.safe_reach_tier_enum as enum (
    'TIER_1_PUSH_SMS',
    'TIER_2_IVR_CALL',
    'TIER_3_P0_ESCALATION_SUPERVISOR'
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type public.audit_hold_reason_enum as enum (
    'ODOMETER_GPS_DISCREPANCY',
    'NEGATIVE_MARGIN_BREACH',
    'FASTAG_UNMATCHED',
    'SLA_BREACH_PENALTY',
    'MANUAL_RATE_OVERRIDE'
  );
exception when duplicate_object then null; end $$;

-- ============================================================================
-- 2. PARENT BOOKINGS & MULTI-DAY CHILD DUTIES SCHEMA (1:N)
-- ============================================================================

create table if not exists public.parent_bookings (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  corporate_client_id uuid not null references public.customers(id) on delete restrict,
  booking_reference text not null,
  booking_category text not null check (booking_category in ('LOCAL_SPOT', 'OUTSTATION', 'AIRPORT_TRANSFER', 'MONTHLY_DEDICATED', 'SHIFT_COMMUTE')),
  billing_mode public.billing_mode_enum not null default 'HR_KM_SLAB',
  garage_matrix public.garage_matrix_enum not null default 'P2P_STRICT',
  start_date date not null,
  end_date date not null,
  total_days integer not null default 1,
  flight_number text,
  is_vip boolean not null default false,
  status text not null default 'confirmed',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, booking_reference)
);

-- Ensure version_id and parent booking relation exist on duties
alter table public.duties add column if not exists parent_booking_id uuid references public.parent_bookings(id) on delete set null;
alter table public.duties add column if not exists version_id integer not null default 1;
alter table public.duties add column if not exists day_sequence integer default 1;
alter table public.duties add column if not exists relief_duty_parent_id uuid references public.duties(id);
alter table public.duties add column if not exists is_relief_duty boolean not null default false;
alter table public.duties add column if not exists audit_hold boolean not null default false;
alter table public.duties add column if not exists audit_hold_reason public.audit_hold_reason_enum;

-- ============================================================================
-- 3. DUAL-LEDGER FINANCIAL ARCHITECTURE (RECEIVABLE VS PAYABLE)
-- ============================================================================

create table if not exists public.dual_ledger_duty_finances (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  duty_id uuid not null references public.duties(id) on delete cascade unique,
  -- Client Receivable Ledger (Billed to Corporate)
  client_rate_card_id uuid,
  client_billing_mode public.billing_mode_enum not null,
  client_base_paise bigint not null default 0,
  client_extra_km_paise bigint not null default 0,
  client_extra_hr_paise bigint not null default 0,
  client_bhatta_paise bigint not null default 0,
  client_toll_parking_paise bigint not null default 0,
  client_gross_receivable_paise bigint not null default 0,
  client_tax_paise bigint not null default 0,
  client_net_receivable_paise bigint not null default 0,
  -- Supplier Payable Ledger (Paid to Sub-vendor / DCO)
  supplier_id uuid references public.suppliers(id),
  supplier_rate_card_id uuid,
  supplier_base_paise bigint not null default 0,
  supplier_extra_km_paise bigint not null default 0,
  supplier_extra_hr_paise bigint not null default 0,
  supplier_bhatta_paise bigint not null default 0,
  supplier_toll_parking_paise bigint not null default 0,
  supplier_gross_payable_paise bigint not null default 0,
  supplier_penalty_deduction_paise bigint not null default 0,
  supplier_net_payable_paise bigint not null default 0,
  -- Live Unit Profitability & Margin Flag
  gross_margin_paise bigint generated always as (client_gross_receivable_paise - supplier_gross_payable_paise) stored,
  is_negative_margin boolean generated always as (client_gross_receivable_paise < supplier_gross_payable_paise) stored,
  maker_checker_approved boolean not null default false,
  approved_by uuid references auth.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- ============================================================================
-- 4. PARTNER NETWORK EXCHANGE & MULTI-VENDOR SLA GOVERNANCE
-- ============================================================================

create table if not exists public.vendor_sla_profiles (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  vendor_id uuid not null references public.suppliers(id) on delete cascade unique,
  tier public.vendor_tier_enum not null default 'TIER_2_GOLD',
  rolling_ota_pct numeric(5,2) not null default 98.50,
  rolling_acceptance_rate_pct numeric(5,2) not null default 99.00,
  rolling_compliance_score_pct numeric(5,2) not null default 99.50,
  active_breaches_7d integer not null default 0,
  is_demoted_on_breach boolean not null default false,
  last_demoted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.vendor_sla_breach_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  vendor_id uuid not null references public.suppliers(id) on delete cascade,
  duty_id uuid references public.duties(id) on delete set null,
  breach_type text not null check (breach_type in ('LATE_ARRIVAL_15M', 'LATE_CANCELLATION', 'UNAPPROVED_SWAP', 'GPS_BLACKOUT_20PCT', 'AC_FAILURE', 'NO_SHOW')),
  severity text not null check (severity in ('WARNING', 'CRITICAL', 'FATAL')),
  penalty_debit_paise bigint not null default 0,
  debit_note_reference text,
  occurred_at timestamptz not null default now(),
  acknowledged boolean not null default false
);

-- ============================================================================
-- 5. STATUTORY WOMEN'S SAFETY, GUARD LIFECYCLE & 16+ SECURITY ALERTS
-- ============================================================================

create table if not exists public.security_guards (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  full_name text not null,
  badge_number text not null,
  agency_name text not null,
  phone text not null,
  police_verification_expiry date not null,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists public.duty_safety_records (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  duty_id uuid not null references public.duties(id) on delete cascade unique,
  has_female_passenger boolean not null default false,
  is_night_shift boolean not null default false,
  guard_id uuid references public.security_guards(id),
  guard_checkin_at timestamptz,
  guard_checkout_at timestamptz,
  safe_reach_tier public.safe_reach_tier_enum not null default 'TIER_1_PUSH_SMS',
  safe_reach_confirmed boolean not null default false,
  safe_reach_confirmed_at timestamptz,
  p0_emergency_escalated boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists public.safety_telemetry_alerts (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  duty_id uuid not null references public.duties(id) on delete cascade,
  alert_code text not null check (alert_code in (
    'OVERSPEEDING', 'ROUTE_DEVIATION_500M', 'UNPLANNED_STOPPAGE_5M', 'GEOFENCE_BREACH',
    'HARSH_BRAKING', 'NIGHT_DRIVING_VIOLATION', 'MOCK_LOCATION_DETECTED', 'OFFLINE_DROPOUT',
    'LATE_DISPATCH', 'LATE_ARRIVAL', 'SOS_TRIGGERED', 'GUARD_MISSING_FEMALE_DROP',
    'UNVERIFIED_DRIVER_SWAP', 'DOCUMENT_EXPIRY_MID_ROSTER', 'ODOMETER_SPIKE', 'NO_SHOW_CASCADE'
  )),
  severity text not null check (severity in ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL_P0')),
  lat numeric(9,6),
  lng numeric(9,6),
  details_json jsonb not null default '{}'::jsonb,
  status text not null default 'open' check (status in ('open', 'acknowledged', 'resolved')),
  created_at timestamptz not null default now()
);

-- ============================================================================
-- 6. 3-WAY DISTANCE AUDIT, FASTAG RECONCILIATION & TELEMETRY
-- ============================================================================

create table if not exists public.duty_distance_audits (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  duty_id uuid not null references public.duties(id) on delete cascade unique,
  odometer_start integer not null,
  odometer_end integer not null,
  odometer_delta_km numeric(8,2) generated always as (odometer_end - odometer_start) stored,
  raw_gps_crumb_km numeric(8,2) not null default 0.0,
  snapped_route_km numeric(8,2) not null default 0.0,
  discrepancy_pct numeric(5,2) generated always as (
    case when snapped_route_km > 0
      then round(((odometer_end - odometer_start - snapped_route_km) / snapped_route_km) * 100.0, 2)
      else 0.0
    end
  ) stored,
  is_fraud_flagged boolean not null default false,
  fastag_toll_deductions_paise bigint not null default 0,
  fastag_matched_count integer not null default 0,
  created_at timestamptz not null default now()
);

-- ============================================================================
-- 7. ADMIN WEBHOOKS & EVENT INTEGRATION AUDIT LOGS
-- ============================================================================

create table if not exists public.admin_webhook_audit_logs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  direction text not null check (direction in ('INBOUND', 'OUTBOUND')),
  service_name text not null, -- Exotel, WhatsApp, FASTag, AIS140, Tally, IRP_EInvoice
  endpoint_url text not null,
  http_method text not null default 'POST',
  request_payload jsonb not null default '{}'::jsonb,
  response_payload jsonb not null default '{}'::jsonb,
  http_status integer,
  latency_ms integer not null default 0,
  retry_count integer not null default 0,
  is_dead_letter boolean not null default false,
  error_message text,
  created_at timestamptz not null default now()
);

-- ============================================================================
-- 8. STATUTORY GST E-INVOICING (IRN/QR) & TALLY EXPEDITION LEDGER
-- ============================================================================

create table if not exists public.statutory_e_invoices (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  invoice_id uuid not null references public.invoices(id) on delete cascade unique,
  invoice_number text not null,
  hsn_sac_code text not null default '996601',
  gst_rate_pct numeric(4,2) not null default 5.00,
  is_rcm_applicable boolean not null default false,
  supplier_gstin text not null,
  client_gstin text not null,
  irn_hash text,
  ack_no text,
  ack_dt timestamptz,
  signed_qr_code text,
  nic_payload_json jsonb not null default '{}'::jsonb,
  tally_sync_status text not null default 'PENDING' check (tally_sync_status in ('PENDING', 'SYNCED', 'FAILED')),
  tally_guid text,
  tally_synced_at timestamptz,
  created_at timestamptz not null default now()
);

-- ============================================================================
-- 9. ROW-LEVEL SECURITY (RLS) POLICIES
-- ============================================================================

alter table public.parent_bookings enable row level security;
alter table public.dual_ledger_duty_finances enable row level security;
alter table public.vendor_sla_profiles enable row level security;
alter table public.vendor_sla_breach_events enable row level security;
alter table public.security_guards enable row level security;
alter table public.duty_safety_records enable row level security;
alter table public.safety_telemetry_alerts enable row level security;
alter table public.duty_distance_audits enable row level security;
alter table public.admin_webhook_audit_logs enable row level security;
alter table public.statutory_e_invoices enable row level security;

-- Tenant Isolation Policies
create policy "Tenant isolation for parent_bookings" on public.parent_bookings
  for all using (organization_id in (select organization_id from public.organization_memberships where user_id = auth.uid()));

create policy "Tenant isolation for dual_ledger" on public.dual_ledger_duty_finances
  for all using (organization_id in (select organization_id from public.organization_memberships where user_id = auth.uid()));

create policy "Tenant isolation for vendor_sla" on public.vendor_sla_profiles
  for all using (organization_id in (select organization_id from public.organization_memberships where user_id = auth.uid()));

create policy "Tenant isolation for safety_alerts" on public.safety_telemetry_alerts
  for all using (organization_id in (select organization_id from public.organization_memberships where user_id = auth.uid()));

create policy "Tenant isolation for webhook_logs" on public.admin_webhook_audit_logs
  for all using (organization_id in (select organization_id from public.organization_memberships where user_id = auth.uid()));

create policy "Tenant isolation for e_invoices" on public.statutory_e_invoices
  for all using (organization_id in (select organization_id from public.organization_memberships where user_id = auth.uid()));
