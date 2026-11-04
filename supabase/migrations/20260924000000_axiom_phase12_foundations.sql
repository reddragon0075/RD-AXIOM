-- Axiom Fleet Phase 1 + Phase 2 additive contracts.
-- These tables are the production/Postgres counterparts of backend_phase12.py.
-- Cross-aggregate transitions must be executed by phase12-orchestrator (or an
-- equivalent RPC) after RLS checks; direct PostgREST access remains tenant and
-- permission scoped.

insert into public.permissions(key, description) values
  ('phase12.masters.read', 'Read the unified master registry'),
  ('phase12.masters.write', 'Create, version, import and archive master records'),
  ('phase12.operations.read', 'Read rosters, live board and ETA health'),
  ('phase12.operations.write', 'Create roster versions and bulk operations'),
  ('phase12.tracking.read', 'Read GPS, ETA and route-health signals'),
  ('phase12.safety.read', 'Read safety evidence and closure approvals'),
  ('phase12.safety.write', 'Capture evidence, evaluate alerts and request closure'),
  ('phase12.network.read', 'Read Network activation, replacement and scorecard contracts'),
  ('phase12.network.write', 'Manage Network activation, replacement and scorecard contracts'),
  ('phase12.permissions.read', 'Read permission bundles'),
  ('phase12.permissions.write', 'Create versioned permission bundles'),
  ('phase12.views.read', 'Read saved operational views'),
  ('phase12.views.write', 'Create and update saved operational views'),
  ('phase12.integrations.read', 'Read provider catalog and integration events'),
  ('phase12.integrations.write', 'Configure provider boundaries and receive events')
on conflict (key) do nothing;

insert into public.role_permissions(role, permission_key)
select r.role, p.key
from (values
  ('vendor_owner'::public.membership_role), ('vendor_ops'::public.membership_role), ('vendor_dispatch'::public.membership_role),
  ('corporate_admin'::public.membership_role), ('corporate_travel'::public.membership_role)
) r(role)
cross join public.permissions p
where p.key in (
  'phase12.masters.read','phase12.masters.write','phase12.operations.read','phase12.operations.write',
  'phase12.tracking.read','phase12.safety.read','phase12.safety.write','phase12.network.read','phase12.network.write',
  'phase12.permissions.read','phase12.views.read','phase12.views.write','phase12.integrations.read','phase12.integrations.write'
)
on conflict do nothing;
insert into public.role_permissions(role, permission_key)
select 'driver'::public.membership_role, p.key
from public.permissions p
where p.key in ('phase12.operations.read','phase12.tracking.read','phase12.safety.read','phase12.safety.write')
on conflict do nothing;
insert into public.role_permissions(role, permission_key)
select r.role, p.key
from (values ('vendor_owner'::public.membership_role), ('corporate_admin'::public.membership_role)) r(role)
cross join public.permissions p
where p.key in ('phase12.permissions.write','phase12.network.write')
on conflict do nothing;

create table if not exists public.phase12_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  event_type text not null,
  entity_type text not null,
  entity_id uuid,
  payload jsonb not null default '{}'::jsonb,
  actor_id uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);
create index if not exists idx_phase12_events_org_time on public.phase12_events(organization_id, created_at desc);

create table if not exists public.phase12_versions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  entity_type text not null,
  entity_id uuid not null,
  version integer not null,
  change_type text not null,
  snapshot jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, entity_type, entity_id, version)
);

create table if not exists public.phase12_master_records (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  kind text not null check (kind in ('duty_types','vehicle_groups','taxes','billing_items','documents','labels','employees','passengers','feedback_forms','branches','operating_regions','suppliers','drivers','vehicles','rate_cards','sites','shifts')),
  code text not null,
  name text not null,
  status text not null default 'active',
  version integer not null default 1,
  effective_from date,
  effective_to date,
  metadata jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, kind, code)
);
create index if not exists idx_phase12_master_records_org_kind on public.phase12_master_records(organization_id, kind, status);

create table if not exists public.phase12_roster_versions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  route_plan_id uuid not null references public.p0_route_plans(id) on delete restrict,
  plan_date date not null,
  version integer not null default 1,
  status text not null default 'draft',
  assignments jsonb not null default '[]'::jsonb,
  constraints jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, route_plan_id, version)
);
create index if not exists idx_phase12_roster_versions_org_date on public.phase12_roster_versions(organization_id, plan_date, status);

create table if not exists public.phase12_eta_snapshots (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  duty_id uuid not null references public.duties(id) on delete restrict,
  source text not null default 'mock_maps',
  latitude numeric,
  longitude numeric,
  distance_km numeric not null default 0,
  duration_minutes integer not null default 0,
  eta_at timestamptz,
  deviation_minutes integer not null default 0,
  status text not null default 'estimated',
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists idx_phase12_eta_snapshots_duty_time on public.phase12_eta_snapshots(organization_id, duty_id, created_at desc);

create table if not exists public.phase12_safety_evidence (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  incident_id uuid not null references public.p0_safety_incidents(id) on delete restrict,
  evidence_type text not null,
  storage_path text not null default '',
  source_event_id uuid,
  sha256 text not null default '',
  metadata jsonb not null default '{}'::jsonb,
  captured_by uuid references auth.users(id) on delete set null,
  captured_at timestamptz not null default now()
);
create index if not exists idx_phase12_safety_evidence_incident on public.phase12_safety_evidence(organization_id, incident_id, captured_at desc);

create table if not exists public.phase12_closure_approvals (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  incident_id uuid not null references public.p0_safety_incidents(id) on delete restrict,
  status text not null default 'pending' check (status in ('pending','approved','rejected')),
  requested_by uuid references auth.users(id) on delete set null,
  reviewed_by uuid references auth.users(id) on delete set null,
  review_note text not null default '',
  created_at timestamptz not null default now(),
  reviewed_at timestamptz
);

create table if not exists public.phase12_network_replacements (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  service_order_id uuid not null references public.network_service_orders(id) on delete restrict,
  duty_id uuid references public.duties(id) on delete set null,
  reason text not null,
  status text not null default 'open',
  replacement_driver_id uuid references public.drivers(id) on delete set null,
  replacement_vehicle_id uuid references public.vehicles(id) on delete set null,
  due_at timestamptz,
  evidence jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_phase12_network_replacements on public.phase12_network_replacements(organization_id, service_order_id, status);

create table if not exists public.phase12_scorecard_formulas (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  code text not null,
  version integer not null default 1,
  status text not null default 'active',
  weights jsonb not null default '{}'::jsonb,
  thresholds jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, code, version)
);
create table if not exists public.phase12_scorecard_disputes (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  scorecard_run_id uuid not null references public.p0_network_scorecard_runs(id) on delete restrict,
  reason text not null,
  status text not null default 'open',
  evidence jsonb not null default '{}'::jsonb,
  resolution_note text not null default '',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  resolved_at timestamptz
);
create table if not exists public.phase12_reconciliations (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  service_order_id uuid not null references public.network_service_orders(id) on delete restrict,
  scorecard_run_id uuid references public.p0_network_scorecard_runs(id) on delete set null,
  statement_id uuid references public.p0_network_settlement_statements(id) on delete set null,
  expected_paise bigint not null default 0,
  observed_paise bigint not null default 0,
  variance_paise bigint not null default 0,
  status text not null default 'review',
  evidence jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);

create table if not exists public.phase12_permission_bundles (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  role text not null,
  name text not null,
  description text not null default '',
  permissions jsonb not null default '[]'::jsonb,
  version integer not null default 1,
  status text not null default 'active',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, role, version)
);

create table if not exists public.phase12_saved_views (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  scope text not null,
  name text not null,
  filters jsonb not null default '{}'::jsonb,
  columns jsonb not null default '[]'::jsonb,
  sort jsonb not null default '{}'::jsonb,
  shared boolean not null default false,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, scope, name)
);

create table if not exists public.phase12_bulk_jobs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  idempotency_key text,
  operation text not null,
  entity_type text not null,
  entity_ids jsonb not null default '[]'::jsonb,
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'queued',
  result jsonb not null default '[]'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  unique (organization_id, idempotency_key)
);

create table if not exists public.phase12_integrations (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  provider_type text not null,
  provider_name text not null,
  mode text not null default 'mock',
  status text not null default 'available',
  config jsonb not null default '{}'::jsonb,
  last_sync_at timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, provider_type)
);
create table if not exists public.phase12_integration_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid references public.organizations(id) on delete set null,
  provider_type text not null,
  event_type text not null,
  external_id text not null,
  signature_valid boolean not null default false,
  status text not null default 'received',
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (provider_type, external_id)
);

-- Tenant isolation and local authorization are enforced for every Phase 1/2
-- collection. Providers never receive service-role access from the browser.
do $$
declare t text;
  read_permission text;
  write_permission text;
begin
  foreach t in array array[
    'phase12_events','phase12_versions','phase12_master_records','phase12_roster_versions','phase12_eta_snapshots',
    'phase12_safety_evidence','phase12_closure_approvals','phase12_network_replacements','phase12_scorecard_formulas',
    'phase12_scorecard_disputes','phase12_reconciliations','phase12_permission_bundles','phase12_saved_views',
    'phase12_bulk_jobs','phase12_integrations','phase12_integration_events'
  ] loop
    if t like '%master%' then read_permission := 'phase12.masters.read'; write_permission := 'phase12.masters.write';
    elsif t like '%roster%' or t like '%eta%' or t like '%bulk%' then read_permission := 'phase12.operations.read'; write_permission := 'phase12.operations.write';
    elsif t like '%safety%' or t like '%closure%' then read_permission := 'phase12.safety.read'; write_permission := 'phase12.safety.write';
    elsif t like '%network%' or t like '%scorecard%' or t like '%reconcil%' then read_permission := 'phase12.network.read'; write_permission := 'phase12.network.write';
    elsif t like '%permission%' then read_permission := 'phase12.permissions.read'; write_permission := 'phase12.permissions.write';
    elsif t like '%view%' then read_permission := 'phase12.views.read'; write_permission := 'phase12.views.write';
    else read_permission := 'phase12.integrations.read'; write_permission := 'phase12.integrations.write';
    end if;
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists %I on public.%I', t || '_select', t);
    execute format('drop policy if exists %I on public.%I', t || '_write', t);
    execute format('create policy %I on public.%I for select to authenticated using ((organization_id is not null and public.has_permission(organization_id, %L)) or public.is_platform_user())', t || '_select', t, read_permission);
    execute format('create policy %I on public.%I for all to authenticated using ((organization_id is not null and public.has_permission(organization_id, %L)) or public.is_platform_user()) with check ((organization_id is not null and public.has_permission(organization_id, %L)) or public.is_platform_user())', t || '_write', t, write_permission, write_permission);
  end loop;
end $$;

grant select, insert, update on all tables in schema public to authenticated;

-- Reuse the production audit trigger when it exists. The trigger is deliberately
-- conditional so this migration can be applied after a clean baseline as well.
do $$
declare t text;
begin
  if to_regprocedure('public.p0_audit_row()') is not null then
    foreach t in array array[
      'phase12_events','phase12_versions','phase12_master_records','phase12_roster_versions','phase12_eta_snapshots',
      'phase12_safety_evidence','phase12_closure_approvals','phase12_network_replacements','phase12_scorecard_formulas',
      'phase12_scorecard_disputes','phase12_reconciliations','phase12_permission_bundles','phase12_saved_views',
      'phase12_bulk_jobs','phase12_integrations','phase12_integration_events'
    ] loop
      execute format('drop trigger if exists %I on public.%I', t || '_audit', t);
      execute format('create trigger %I after insert or update or delete on public.%I for each row execute function public.p0_audit_row()', t || '_audit', t);
    end loop;
  end if;
end $$;
