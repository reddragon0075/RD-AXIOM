-- Axiom Fleet Phase 3 additive moat layer.
-- Production source of truth: Supabase/Postgres. The authenticated
-- phase3-orchestrator is the only browser-facing write boundary for derived
-- calculations; Fleet duties, GPS, invoices and Network service orders remain
-- canonical sources of truth.

insert into public.permissions(key, description) values
  ('phase3.analytics.read', 'Read Phase 3 intelligence summaries'),
  ('phase3.analytics.write', 'Run Phase 3 intelligence evaluations'),
  ('phase3.predictive.read', 'Read explainable predictive alerts'),
  ('phase3.predictive.write', 'Evaluate, acknowledge and give feedback on predictive alerts'),
  ('phase3.vendor_quality.read', 'Read invite-only vendor quality graph'),
  ('phase3.vendor_quality.write', 'Recompute vendor quality graph projections'),
  ('phase3.simulation.read', 'Read cost and service simulations'),
  ('phase3.simulation.write', 'Run idempotent cost and service simulations'),
  ('phase3.variance.read', 'Read automated variance findings'),
  ('phase3.variance.write', 'Scan, assign and resolve variance findings'),
  ('phase3.sustainability.read', 'Read auditable sustainability intelligence'),
  ('phase3.sustainability.write', 'Calculate trips and manage sustainability targets'),
  ('phase3.regions.read', 'Read controlled regional localization settings'),
  ('phase3.regions.write', 'Manage tenant regional settings and FX inputs')
on conflict (key) do nothing;

insert into public.role_permissions(role, permission_key)
select r.role, p.key
from (values
  ('vendor_owner'::public.membership_role), ('vendor_ops'::public.membership_role),
  ('vendor_dispatch'::public.membership_role), ('corporate_admin'::public.membership_role),
  ('corporate_travel'::public.membership_role)
) r(role)
cross join public.permissions p
where p.key like 'phase3.%'
on conflict do nothing;
insert into public.role_permissions(role, permission_key)
select 'driver'::public.membership_role, p.key
from public.permissions p
where p.key in ('phase3.predictive.read','phase3.sustainability.read','phase3.regions.read')
on conflict do nothing;

-- Controlled country/region catalog. Tenants may select or activate these
-- profiles; they cannot invent a country code through the production API.
create table if not exists public.phase3_region_catalog (
  country_code text not null,
  region_code text primary key,
  name text not null,
  currency text not null,
  timezone text not null,
  locale text not null,
  tax_regime text not null,
  distance_unit text not null default 'km',
  status text not null default 'active' check (status in ('active','retired'))
);
insert into public.phase3_region_catalog(country_code, region_code, name, currency, timezone, locale, tax_regime, distance_unit) values
  ('IN','IN-MH','India · Maharashtra','INR','Asia/Kolkata','en-IN','GST','km'),
  ('IN','IN-KA','India · Karnataka','INR','Asia/Kolkata','en-IN','GST','km'),
  ('AE','AE-DU','United Arab Emirates · Dubai','AED','Asia/Dubai','en-AE','VAT','km'),
  ('SG','SG-SG','Singapore','SGD','Asia/Singapore','en-SG','GST','km'),
  ('GB','GB-LND','United Kingdom · London','GBP','Europe/London','en-GB','VAT','mi')
on conflict (region_code) do nothing;

create table if not exists public.phase3_emission_factors (
  fuel_type text primary key,
  factor_kg_per_km numeric(12,6) not null check (factor_kg_per_km >= 0),
  factor_version text not null,
  source text not null,
  status text not null default 'active' check (status in ('active','retired')),
  created_at timestamptz not null default now()
);
insert into public.phase3_emission_factors(fuel_type, factor_kg_per_km, factor_version, source) values
  ('petrol',0.192,'factor-v1','Axiom planning catalog'),
  ('diesel',0.171,'factor-v1','Axiom planning catalog'),
  ('cng',0.130,'factor-v1','Axiom planning catalog'),
  ('hybrid',0.100,'factor-v1','Axiom planning catalog'),
  ('ev',0.050,'factor-v1','Axiom planning catalog'),
  ('electric',0.050,'factor-v1','Axiom planning catalog')
on conflict (fuel_type) do nothing;

-- EV planning fields remain additive to the canonical Fleet vehicle record.
alter table public.vehicles add column if not exists ev_eligible boolean not null default false;
alter table public.vehicles add column if not exists battery_capacity_kwh numeric(12,3);
alter table public.vehicles add column if not exists usable_range_km numeric(14,3);
alter table public.vehicles add column if not exists energy_consumption_kwh_per_km numeric(12,6);
alter table public.vehicles add column if not exists charging_connector text not null default '';
alter table public.vehicles add column if not exists charging_power_kw numeric(12,3);
alter table public.vehicles add column if not exists charging_status text not null default 'unknown';
alter table public.vehicles add column if not exists energy_price_per_kwh_minor bigint;

create table if not exists public.phase3_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  event_type text not null,
  entity_type text not null,
  entity_id uuid,
  payload jsonb not null default '{}'::jsonb,
  actor_id uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);
create index if not exists idx_phase3_events_org_time on public.phase3_events(organization_id, created_at desc);

create table if not exists public.phase3_predictive_alerts (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  evaluation_key text not null,
  entity_type text not null,
  entity_id uuid not null,
  alert_type text not null,
  severity text not null check (severity in ('low','medium','high','critical')),
  risk_score numeric(6,2) not null default 0,
  confidence numeric(6,2) not null default 0,
  lead_time_minutes integer not null default 0,
  model_version text not null default 'predictive-v1',
  factors jsonb not null default '[]'::jsonb,
  source_event_ids jsonb not null default '[]'::jsonb,
  recommended_action text not null default '',
  status text not null default 'open' check (status in ('open','acknowledged','resolved','suppressed')),
  predicted_at timestamptz not null default now(),
  due_at timestamptz,
  acknowledged_by uuid references auth.users(id) on delete set null,
  acknowledged_at timestamptz,
  resolved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, evaluation_key)
);
create index if not exists idx_phase3_alerts_org_status on public.phase3_predictive_alerts(organization_id, status, severity, predicted_at desc);

create table if not exists public.phase3_alert_feedback (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  alert_id uuid not null references public.phase3_predictive_alerts(id) on delete cascade,
  outcome text not null,
  note text not null default '',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);

create table if not exists public.phase3_vendor_quality_snapshots (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  vendor_profile_id uuid not null references public.network_vendor_profiles(id) on delete restrict,
  vendor_organization_id uuid references public.organizations(id) on delete set null,
  formula_version text not null default 'vendor-quality-v1',
  score numeric(6,2) not null default 0,
  confidence text not null default 'cold_start',
  sample_size integer not null default 0,
  metrics jsonb not null default '{}'::jsonb,
  source_event_ids jsonb not null default '[]'::jsonb,
  computed_at timestamptz not null default now(),
  unique (organization_id, vendor_profile_id, formula_version)
);
create table if not exists public.phase3_vendor_quality_edges (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  edge_key text not null,
  from_type text not null,
  from_id uuid not null,
  to_type text not null,
  to_id uuid not null,
  edge_type text not null,
  weight numeric(12,4) not null default 1,
  evidence jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (organization_id, edge_key)
);
create index if not exists idx_phase3_vendor_edges_org on public.phase3_vendor_quality_edges(organization_id, from_type, from_id);

create table if not exists public.phase3_simulations (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  scenario_name text not null,
  status text not null default 'completed',
  model_version text not null default 'cost-service-v1',
  idempotency_key text,
  inputs jsonb not null default '{}'::jsonb,
  outputs jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);
create index if not exists idx_phase3_simulations_org_time on public.phase3_simulations(organization_id, created_at desc);

create table if not exists public.phase3_variance_findings (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  scan_key text not null,
  entity_type text not null,
  entity_id uuid not null,
  variance_type text not null,
  severity text not null default 'medium' check (severity in ('low','medium','high','critical')),
  expected_minor bigint not null default 0,
  observed_minor bigint not null default 0,
  variance_minor bigint not null default 0,
  variance_pct numeric(12,4) not null default 0,
  rule_version text not null default 'variance-v1',
  evidence jsonb not null default '{}'::jsonb,
  source_event_ids jsonb not null default '[]'::jsonb,
  status text not null default 'open' check (status in ('open','acknowledged','assigned','resolved','dismissed')),
  assigned_to uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  resolved_at timestamptz,
  unique (organization_id, scan_key)
);
create index if not exists idx_phase3_variance_org_status on public.phase3_variance_findings(organization_id, status, severity, created_at desc);

create table if not exists public.phase3_sustainability_trips (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  duty_id uuid not null references public.duties(id) on delete restrict,
  vehicle_id uuid references public.vehicles(id) on delete set null,
  region_code text references public.phase3_region_catalog(region_code) on delete restrict,
  fuel_type text not null default 'petrol',
  distance_km numeric(14,3) not null default 0,
  passenger_count integer not null default 1,
  energy_kwh numeric(14,3) not null default 0,
  energy_cost_minor bigint not null default 0,
  energy_price_per_kwh_minor bigint not null default 0,
  emissions_kg numeric(14,3) not null default 0,
  emissions_per_passenger_km_g numeric(14,3) not null default 0,
  baseline_emissions_kg numeric(14,3) not null default 0,
  avoided_emissions_kg numeric(14,3) not null default 0,
  factor_kg_per_km numeric(12,6) not null default 0,
  grid_factor_kg_per_kwh numeric(12,6) not null default 0,
  factor_version text not null default 'factor-v1',
  range_required_km numeric(14,3) not null default 0,
  range_remaining_km numeric(14,3),
  charging_station_id uuid,
  charging_available boolean not null default false,
  ev_eligibility_status text not null default 'not_applicable',
  ev_eligibility_reasons jsonb not null default '[]'::jsonb,
  source_event_ids jsonb not null default '[]'::jsonb,
  calculated_at timestamptz not null default now(),
  unique (organization_id, duty_id, factor_version)
);
alter table public.phase3_sustainability_trips add column if not exists passenger_count integer not null default 1;
alter table public.phase3_sustainability_trips add column if not exists energy_kwh numeric(14,3) not null default 0;
alter table public.phase3_sustainability_trips add column if not exists energy_cost_minor bigint not null default 0;
alter table public.phase3_sustainability_trips add column if not exists energy_price_per_kwh_minor bigint not null default 0;
alter table public.phase3_sustainability_trips add column if not exists emissions_per_passenger_km_g numeric(14,3) not null default 0;
alter table public.phase3_sustainability_trips add column if not exists baseline_emissions_kg numeric(14,3) not null default 0;
alter table public.phase3_sustainability_trips add column if not exists avoided_emissions_kg numeric(14,3) not null default 0;
alter table public.phase3_sustainability_trips add column if not exists grid_factor_kg_per_kwh numeric(12,6) not null default 0;
alter table public.phase3_sustainability_trips add column if not exists range_required_km numeric(14,3) not null default 0;
alter table public.phase3_sustainability_trips add column if not exists range_remaining_km numeric(14,3);
alter table public.phase3_sustainability_trips add column if not exists charging_station_id uuid;
alter table public.phase3_sustainability_trips add column if not exists charging_available boolean not null default false;
alter table public.phase3_sustainability_trips add column if not exists ev_eligibility_status text not null default 'not_applicable';
alter table public.phase3_sustainability_trips add column if not exists ev_eligibility_reasons jsonb not null default '[]'::jsonb;
create index if not exists idx_phase3_sustainability_org_time on public.phase3_sustainability_trips(organization_id, calculated_at desc);

create table if not exists public.phase3_charging_stations (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  region_code text not null references public.phase3_region_catalog(region_code) on delete restrict,
  name text not null,
  location_label text not null default '',
  connector_types jsonb not null default '[]'::jsonb,
  total_ports integer not null default 0 check (total_ports >= 0),
  available_ports integer not null default 0 check (available_ports >= 0 and available_ports <= total_ports),
  power_kw numeric(12,3) not null default 0,
  energy_price_per_kwh_minor bigint not null default 0,
  status text not null default 'active',
  operating_hours jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_phase3_charging_org_region on public.phase3_charging_stations(organization_id, region_code, status);

create table if not exists public.phase3_sustainability_targets (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  scope text not null default 'fleet',
  period_start date not null,
  period_end date not null,
  baseline_kg numeric(14,3) not null default 0,
  target_kg numeric(14,3) not null default 0,
  status text not null default 'active',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, scope, period_start, period_end)
);

create table if not exists public.phase3_regions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  catalog_region_code text not null references public.phase3_region_catalog(region_code) on delete restrict,
  country_code text not null,
  name text not null,
  currency text not null,
  timezone text not null,
  locale text not null,
  tax_regime text not null,
  distance_unit text not null default 'km',
  effective_from date,
  effective_to date,
  is_default boolean not null default false,
  status text not null default 'active',
  metadata jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, catalog_region_code)
);
alter table public.phase3_regions add column if not exists effective_from date;
alter table public.phase3_regions add column if not exists effective_to date;
create unique index if not exists idx_phase3_one_default_region on public.phase3_regions(organization_id) where is_default and status = 'active';

create table if not exists public.phase3_exchange_rates (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  base_currency text not null,
  quote_currency text not null,
  rate numeric(24,12) not null check (rate > 0),
  effective_at timestamptz not null,
  source text not null default 'mock_fx',
  version text not null default 'fx-v1',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, base_currency, quote_currency, effective_at)
);
create index if not exists idx_phase3_fx_org_pair on public.phase3_exchange_rates(organization_id, base_currency, quote_currency, effective_at desc);

-- RLS is explicit for tenant tables. The catalog is read-only to clients and
-- changes only through a reviewed migration.
alter table public.phase3_region_catalog enable row level security;
alter table public.phase3_emission_factors enable row level security;
drop policy if exists phase3_region_catalog_select on public.phase3_region_catalog;
drop policy if exists phase3_emission_factors_select on public.phase3_emission_factors;
create policy phase3_region_catalog_select on public.phase3_region_catalog for select to authenticated using (status = 'active');
create policy phase3_emission_factors_select on public.phase3_emission_factors for select to authenticated using (status = 'active');

do $$
declare t text;
  read_permission text;
  write_permission text;
begin
  foreach t in array array[
    'phase3_events','phase3_predictive_alerts','phase3_alert_feedback',
    'phase3_vendor_quality_snapshots','phase3_vendor_quality_edges','phase3_simulations',
    'phase3_variance_findings','phase3_sustainability_trips','phase3_sustainability_targets','phase3_charging_stations',
    'phase3_regions','phase3_exchange_rates'
  ] loop
    if t like '%predictive%' or t like '%alert%' then read_permission := 'phase3.predictive.read'; write_permission := 'phase3.predictive.write';
    elsif t like '%vendor_quality%' then read_permission := 'phase3.vendor_quality.read'; write_permission := 'phase3.vendor_quality.write';
    elsif t like '%simulation%' then read_permission := 'phase3.simulation.read'; write_permission := 'phase3.simulation.write';
    elsif t like '%variance%' then read_permission := 'phase3.variance.read'; write_permission := 'phase3.variance.write';
    elsif t like '%sustainability%' or t like '%charging%' then read_permission := 'phase3.sustainability.read'; write_permission := 'phase3.sustainability.write';
    elsif t like '%region%' or t like '%exchange%' then read_permission := 'phase3.regions.read'; write_permission := 'phase3.regions.write';
    else read_permission := 'phase3.analytics.read'; write_permission := 'phase3.analytics.write';
    end if;
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists %I on public.%I', t || '_select', t);
    execute format('drop policy if exists %I on public.%I', t || '_write', t);
    execute format('create policy %I on public.%I for select to authenticated using ((organization_id is not null and public.has_permission(organization_id, %L)) or public.is_platform_user())', t || '_select', t, read_permission);
    execute format('create policy %I on public.%I for all to authenticated using ((organization_id is not null and public.has_permission(organization_id, %L)) or public.is_platform_user()) with check ((organization_id is not null and public.has_permission(organization_id, %L)) or public.is_platform_user())', t || '_write', t, write_permission, write_permission);
  end loop;
end $$;

grant select on public.phase3_region_catalog, public.phase3_emission_factors to authenticated;
grant select, insert, update on all tables in schema public to authenticated;

-- Keep Phase 3 mutations inside the same auditable row-trigger boundary used by
-- P0 and Phase 1/2 when the baseline audit function is installed.
do $$
declare t text;
begin
  if to_regprocedure('public.p0_audit_row()') is not null then
    foreach t in array array[
      'phase3_events','phase3_predictive_alerts','phase3_alert_feedback',
      'phase3_vendor_quality_snapshots','phase3_vendor_quality_edges','phase3_simulations',
      'phase3_variance_findings','phase3_sustainability_trips','phase3_sustainability_targets','phase3_charging_stations',
      'phase3_regions','phase3_exchange_rates'
    ] loop
      execute format('drop trigger if exists %I on public.%I', t || '_audit', t);
      execute format('create trigger %I after insert or update or delete on public.%I for each row execute function public.p0_audit_row()', t || '_audit', t);
    end loop;
  end if;
end $$;

comment on table public.phase3_predictive_alerts is 'Explainable, model-versioned risk signals; never a replacement for canonical duty state';
comment on table public.phase3_vendor_quality_snapshots is 'Derived scorecard projection for invite-only Network vendors';
comment on table public.phase3_simulations is 'Reproducible what-if calculation with stored assumptions and formula version';
comment on table public.phase3_variance_findings is 'Auditable reconciliation and rate-card exceptions with deduplication key';
comment on table public.phase3_sustainability_trips is 'Versioned emissions, energy, EV eligibility, passenger-kilometre and avoided-emissions calculation from canonical duty/vehicle evidence';
comment on table public.phase3_charging_stations is 'Tenant-scoped charging availability and energy-price catalog for EV eligibility decisions';
