-- Axiom Fleet Corporate Mobility, Automated Supplier Waterfall & REA Accounting Migration
--
-- Unifies Axiom Corporate engines into the core multi-tenant Supabase database.
-- All operations are strictly organization-scoped with RLS policies.

-- 1. Designation-Based Employee Bands
create table if not exists public.employee_bands (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  corporate_account_id uuid references public.corporate_accounts(id) on delete cascade,
  band_name text not null,
  allowed_vehicle_groups text[] not null default '{}',
  extended_vehicle_groups text[] not null default '{}',
  allowed_duty_types text[] not null default '{}',
  allowed_cities text[] not null default '{}',
  base_city text not null default '',
  allow_custom_passengers boolean not null default false,
  enable_auto_allotment boolean not null default true,
  skip_approval_start_hour integer check (skip_approval_start_hour between 0 and 23),
  skip_approval_end_hour integer check (skip_approval_end_hour between 0 and 23),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_employee_bands_org on public.employee_bands(organization_id, corporate_account_id);
alter table public.employee_bands enable row level security;

create policy employee_bands_org_isolation on public.employee_bands
  for all using (organization_id = (auth.jwt() ->> 'organization_id')::uuid or auth.role() = 'service_role');


-- 2. Supplier Waterfall Allotment Rules
create table if not exists public.supplier_waterfall_rules (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  corporate_account_id uuid references public.corporate_accounts(id) on delete cascade,
  supplier_id uuid not null references public.suppliers(id) on delete cascade,
  city text not null default '',
  vehicle_group text not null default '',
  priority_tier integer not null default 1 check (priority_tier in (1, 2, 3)),
  target_allocation_pct numeric(5,2) not null default 100.00,
  current_month_share_pct numeric(5,2) not null default 0.00,
  acceptance_sla_mins integer not null default 20,
  compressed_sla_mins integer not null default 8,
  daily_cap_duties integer not null default 50,
  today_allotted_count integer not null default 0,
  reliability_score numeric(5,2) not null default 100.00,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_supplier_waterfall_rules_org on public.supplier_waterfall_rules(organization_id, city, vehicle_group, priority_tier);
alter table public.supplier_waterfall_rules enable row level security;

create policy supplier_waterfall_rules_isolation on public.supplier_waterfall_rules
  for all using (organization_id = (auth.jwt() ->> 'organization_id')::uuid or auth.role() = 'service_role');


-- 3. Supplier Waterfall Allotment Attempts & Telemetry
create table if not exists public.supplier_waterfall_attempts (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  booking_id uuid not null references public.bookings(id) on delete cascade,
  supplier_id uuid not null references public.suppliers(id) on delete cascade,
  attempt_sequence integer not null default 1,
  priority_tier integer not null default 1,
  status text not null default 'DISPATCHED_WAITING' check (
    status in ('DISPATCHED_WAITING', 'ACCEPTED_ALLOTTED', 'REJECTED_BY_SUPPLIER', 'EXPIRED_SLA_TIMEOUT', 'CANCELLED_BY_CORPORATE')
  ),
  dispatched_at timestamptz not null default now(),
  sla_expires_at timestamptz not null,
  responded_at timestamptz,
  rejection_reason text,
  allotment_details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_waterfall_attempts_booking on public.supplier_waterfall_attempts(booking_id, attempt_sequence);
alter table public.supplier_waterfall_attempts enable row level security;

create policy supplier_waterfall_attempts_isolation on public.supplier_waterfall_attempts
  for all using (organization_id = (auth.jwt() ->> 'organization_id')::uuid or auth.role() = 'service_role');


-- 4. REA Resources (Standardized economic goods and tax rights)
create table if not exists public.rea_resources (
  id uuid primary key default gen_random_uuid(),
  code text unique not null,
  name text not null,
  resource_type text not null,
  unit_of_measure text not null,
  created_at timestamptz not null default now()
);

insert into public.rea_resources (code, name, resource_type, unit_of_measure)
values
  ('MOBILITY_SERVICE', 'Corporate Mobility Transport Fulfillment', 'SERVICE_CAPACITY', 'KM_HOURS'),
  ('INR_CURRENCY', 'Indian Rupee Fiat Balance', 'CURRENCY', 'INR'),
  ('GST_OUTPUT_TAX', 'GST Output Tax Liability (Payable to Govt)', 'TAX_CREDIT_OBLIGATION', 'INR'),
  ('GST_INPUT_TAX', 'GST Input Tax Credit (ITC Claimable)', 'TAX_CREDIT_OBLIGATION', 'INR')
on conflict (code) do nothing;


-- 5. REA Dualities (Dual-ledger trip settlement binding)
create table if not exists public.rea_dualities (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  booking_id uuid references public.bookings(id) on delete cascade,
  duality_type text not null default 'DUAL_LEDGER_TRIP_FULFILLMENT',
  status text not null default 'BALANCED' check (status in ('BALANCED', 'DISPUTED', 'ADJUSTED')),
  total_receivable_amount numeric(12,2) not null default 0,
  total_payable_amount numeric(12,2) not null default 0,
  gross_margin_amount numeric(12,2) not null default 0,
  margin_pct numeric(5,2) not null default 0,
  created_at timestamptz not null default now()
);

create index if not exists idx_rea_dualities_org on public.rea_dualities(organization_id, booking_id);
alter table public.rea_dualities enable row level security;

create policy rea_dualities_isolation on public.rea_dualities
  for all using (organization_id = (auth.jwt() ->> 'organization_id')::uuid or auth.role() = 'service_role');


-- 6. REA Economic Events (Immutable double-entry balance log)
create table if not exists public.rea_economic_events (
  id uuid primary key default gen_random_uuid(),
  duality_id uuid not null references public.rea_dualities(id) on delete cascade,
  event_type text not null check (
    event_type in (
      'SERVICE_CONSUMED', 'SERVICE_DELIVERED', 'RECEIVABLE_INCURRED',
      'PAYABLE_INCURRED', 'TAX_OUTPUT_ACCRUED', 'TAX_INPUT_CLAIMED',
      'DISPUTE_ADJUSTMENT'
    )
  ),
  direction text not null check (direction in ('INCREMENT', 'DECREMENT')),
  resource_code text not null references public.rea_resources(code),
  from_agent_name text not null,
  to_agent_name text not null,
  amount numeric(12,2) not null,
  currency text not null default 'INR',
  metadata jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now()
);

create index if not exists idx_rea_events_duality on public.rea_economic_events(duality_id);
