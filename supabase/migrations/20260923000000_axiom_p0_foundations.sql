-- Axiom Fleet + Network P0 foundations.
-- Additive production-direction schema. Complex transitions should be exposed
-- through authenticated Edge Functions/RPCs; RLS remains the final boundary.

alter table if exists public.network_requirements add column if not exists deadline_at timestamptz;
alter table if exists public.network_requirements add column if not exists expires_at timestamptz;
alter table if exists public.network_requirements add column if not exists closed_reason text not null default '';
alter table if exists public.network_requirements add column if not exists approved_at timestamptz;
alter table if exists public.network_requirements add column if not exists completed_at timestamptz;

insert into public.permissions(key, description) values
  ('p0.masters.read', 'Read governed master records'),
  ('p0.masters.write', 'Create and version governed master records'),
  ('p0.route_plans.read', 'Read route plans and dispatch boards'),
  ('p0.route_plans.write', 'Create and publish route plans'),
  ('p0.dispatch.respond', 'Accept or reject an offered assignment'),
  ('p0.dispatch.write', 'Create dispatch assignments and replacements'),
  ('p0.safety.read', 'Read safety incidents and policies'),
  ('p0.safety.write', 'Open, investigate and close safety incidents'),
  ('p0.network.read', 'Read Network P0 governance records'),
  ('p0.network.write', 'Manage Network P0 governance records'),
  ('p0.permissions.read', 'Read tenant P0 permission grants'),
  ('p0.permissions.write', 'Manage tenant P0 permission grants')
on conflict (key) do nothing;

insert into public.role_permissions(role, permission_key)
select r.role, p.key
from (values
  ('vendor_owner'::public.membership_role), ('vendor_ops'::public.membership_role), ('vendor_dispatch'::public.membership_role),
  ('corporate_admin'::public.membership_role), ('corporate_travel'::public.membership_role)
) r(role)
cross join public.permissions p
where p.key in ('p0.masters.read','p0.masters.write','p0.route_plans.read','p0.route_plans.write','p0.dispatch.write','p0.safety.read','p0.safety.write','p0.network.read','p0.network.write')
on conflict do nothing;
insert into public.role_permissions(role, permission_key)
select 'driver'::public.membership_role, p.key
from public.permissions p
where p.key in ('p0.route_plans.read','p0.dispatch.respond','p0.safety.read','p0.safety.write')
on conflict do nothing;
insert into public.role_permissions(role, permission_key)
select r.role, p.key
from (values ('vendor_owner'::public.membership_role), ('corporate_admin'::public.membership_role)) r(role)
cross join public.permissions p
where p.key in ('p0.permissions.read','p0.permissions.write')
on conflict do nothing;

create table if not exists public.p0_role_permissions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  role text not null,
  permission_key text not null references public.permissions(key) on delete cascade,
  allowed boolean not null default true,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, role, permission_key)
);

create or replace function public.has_permission(target_org uuid, requested_permission text)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.organization_memberships m
    left join public.role_permissions rp on rp.role = m.role
      and rp.permission_key = requested_permission
    left join public.p0_role_permissions p0rp on p0rp.organization_id = m.organization_id
      and p0rp.role = m.role::text
      and p0rp.permission_key = requested_permission
      and p0rp.allowed
    where m.organization_id = target_org
      and m.user_id = auth.uid()
      and m.status = 'active'::public.membership_status
      and (rp.permission_key is not null or p0rp.permission_key is not null)
  );
$$;

create table if not exists public.p0_master_records (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  kind text not null,
  code text not null,
  name text not null,
  status text not null default 'active',
  version integer not null default 1,
  effective_from date,
  effective_to date,
  config jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, kind, code)
);
create table if not exists public.p0_master_versions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  master_id uuid not null references public.p0_master_records(id) on delete cascade,
  version integer not null,
  change_type text not null,
  snapshot jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, master_id, version)
);

create table if not exists public.p0_sites (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  code text not null,
  name text not null,
  city text not null default '',
  address jsonb not null default '{}'::jsonb,
  status text not null default 'active',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, code)
);
create table if not exists public.p0_shifts (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  site_id uuid references public.p0_sites(id) on delete set null,
  code text not null,
  name text not null,
  starts_at timestamptz not null,
  ends_at timestamptz not null,
  demand jsonb not null default '{}'::jsonb,
  status text not null default 'active',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, code)
);

create table if not exists public.p0_route_plans (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  site_id uuid references public.p0_sites(id) on delete set null,
  plan_date date not null,
  version integer not null default 1,
  status text not null default 'draft',
  routing_mode text not null default 'sequence_by_reporting_at',
  constraints jsonb not null default '{}'::jsonb,
  feasibility jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  published_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.p0_route_stops (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  route_plan_id uuid not null references public.p0_route_plans(id) on delete cascade,
  duty_id uuid not null references public.duties(id) on delete restrict,
  sequence integer not null,
  pickup jsonb not null default '{}'::jsonb,
  dropoff jsonb not null default '{}'::jsonb,
  reporting_at timestamptz,
  status text not null default 'planned',
  created_at timestamptz not null default now(),
  unique (route_plan_id, duty_id)
);
create table if not exists public.p0_roster_assignments (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  route_plan_id uuid not null references public.p0_route_plans(id) on delete cascade,
  duty_id uuid not null references public.duties(id) on delete restrict,
  driver_id uuid references public.drivers(id) on delete set null,
  vehicle_id uuid references public.vehicles(id) on delete set null,
  status text not null default 'offered',
  offered_at timestamptz not null default now(),
  response_deadline timestamptz,
  responded_at timestamptz,
  rejection_reason text not null default '',
  created_by uuid references auth.users(id) on delete set null,
  updated_at timestamptz not null default now(),
  unique (organization_id, route_plan_id, duty_id)
);
create table if not exists public.p0_replacements (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  assignment_id uuid references public.p0_roster_assignments(id) on delete set null,
  duty_id uuid not null references public.duties(id) on delete restrict,
  reason text not null,
  status text not null default 'open',
  replacement_driver_id uuid references public.drivers(id) on delete set null,
  replacement_vehicle_id uuid references public.vehicles(id) on delete set null,
  due_at timestamptz,
  resolved_at timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.p0_dispatch_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  assignment_id uuid references public.p0_roster_assignments(id) on delete set null,
  duty_id uuid references public.duties(id) on delete set null,
  event_type text not null,
  payload jsonb not null default '{}'::jsonb,
  actor_id uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);

create table if not exists public.p0_safety_policies (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  code text not null,
  name text not null,
  version integer not null default 1,
  rules jsonb not null default '{}'::jsonb,
  status text not null default 'active',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, code, version)
);
create table if not exists public.p0_safety_incidents (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  duty_id uuid references public.duties(id) on delete set null,
  alert_type text not null,
  severity text not null,
  status text not null default 'open',
  title text not null,
  description text not null default '',
  owner_id uuid references auth.users(id) on delete set null,
  due_at timestamptz,
  root_cause text not null default '',
  evidence jsonb not null default '{}'::jsonb,
  opened_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  resolved_at timestamptz,
  closed_at timestamptz,
  closed_by uuid references auth.users(id) on delete set null
);
create table if not exists public.p0_safety_actions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  incident_id uuid not null references public.p0_safety_incidents(id) on delete cascade,
  title text not null,
  status text not null default 'open',
  owner_id uuid references auth.users(id) on delete set null,
  due_at timestamptz,
  evidence jsonb not null default '{}'::jsonb,
  resolution_note text not null default '',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.p0_network_regions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  code text not null,
  name text not null,
  cities text[] not null default '{}',
  feature_flags jsonb not null default '{}'::jsonb,
  status text not null default 'active',
  version integer not null default 1,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, code)
);
create table if not exists public.p0_network_vendor_approvals (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  vendor_profile_id uuid not null references public.network_vendor_profiles(id) on delete cascade,
  region_id uuid not null references public.p0_network_regions(id) on delete cascade,
  status text not null default 'pending',
  evidence jsonb not null default '{}'::jsonb,
  expires_at timestamptz,
  note text not null default '',
  decided_by uuid references auth.users(id) on delete set null,
  decided_at timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, vendor_profile_id, region_id)
);
create table if not exists public.p0_network_quote_evaluations (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  requirement_id uuid not null references public.network_requirements(id) on delete cascade,
  quote_id uuid not null references public.network_quotes(id) on delete cascade,
  version integer not null default 1,
  commercial_score numeric not null default 0,
  quality_score numeric not null default 0,
  risk_score numeric not null default 0,
  total_score numeric not null default 0,
  sample_size integer not null default 0,
  confidence text not null default 'cold_start',
  comments text not null default '',
  status text not null default 'draft',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, quote_id, version)
);
create table if not exists public.p0_network_messages (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  thread_key text not null,
  requirement_id uuid references public.network_requirements(id) on delete set null,
  service_order_id uuid references public.network_service_orders(id) on delete set null,
  vendor_profile_id uuid references public.network_vendor_profiles(id) on delete set null,
  visibility text not null default 'participants',
  body text not null,
  status text not null default 'open',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);
create table if not exists public.p0_network_metric_observations (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  service_order_id uuid not null references public.network_service_orders(id) on delete cascade,
  vendor_profile_id uuid references public.network_vendor_profiles(id) on delete set null,
  metric_key text not null,
  value numeric not null,
  unit text not null default '',
  sample_size integer not null default 0,
  source_event_ids uuid[] not null default '{}',
  formula_version text not null default 'v1',
  observed_at timestamptz not null,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);
create table if not exists public.p0_network_scorecard_runs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  service_order_id uuid not null references public.network_service_orders(id) on delete cascade,
  period_start date not null,
  period_end date not null,
  formula_version text not null default 'v1',
  sample_size integer not null default 0,
  confidence text not null default 'cold_start',
  score numeric not null default 0,
  metrics jsonb not null default '{}'::jsonb,
  status text not null default 'computed',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, service_order_id, period_start, period_end, formula_version)
);
create table if not exists public.p0_network_corrective_actions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  vendor_profile_id uuid references public.network_vendor_profiles(id) on delete set null,
  service_order_id uuid references public.network_service_orders(id) on delete set null,
  scorecard_run_id uuid references public.p0_network_scorecard_runs(id) on delete set null,
  title text not null,
  status text not null default 'open',
  owner_id uuid references auth.users(id) on delete set null,
  due_at timestamptz,
  evidence jsonb not null default '{}'::jsonb,
  resolution_note text not null default '',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.p0_network_disputes (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  entity_type text not null,
  entity_id uuid not null,
  service_order_id uuid references public.network_service_orders(id) on delete set null,
  amount_paise bigint not null default 0,
  reason text not null,
  status text not null default 'open',
  claimant_id uuid references auth.users(id) on delete set null,
  respondent_id uuid references auth.users(id) on delete set null,
  evidence jsonb not null default '{}'::jsonb,
  resolution_note text not null default '',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.p0_network_settlement_statements (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  service_order_id uuid not null references public.network_service_orders(id) on delete cascade,
  scorecard_run_id uuid references public.p0_network_scorecard_runs(id) on delete set null,
  period_start date not null,
  period_end date not null,
  subtotal_paise bigint not null default 0,
  tax_paise bigint not null default 0,
  fee_paise bigint not null default 0,
  deduction_paise bigint not null default 0,
  net_paise bigint not null default 0,
  status text not null default 'draft',
  reconciliation jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, service_order_id, period_start, period_end)
);
create table if not exists public.p0_network_settlement_lines (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  statement_id uuid not null references public.p0_network_settlement_statements(id) on delete cascade,
  line_type text not null,
  code text not null,
  description text not null default '',
  quantity numeric not null default 1,
  unit_paise bigint not null default 0,
  amount_paise bigint not null default 0,
  source_event_ids uuid[] not null default '{}',
  disputed boolean not null default false,
  created_at timestamptz not null default now()
);

create index if not exists idx_p0_role_permissions_org on public.p0_role_permissions(organization_id, role, permission_key);
create index if not exists idx_p0_master_records_org_kind on public.p0_master_records(organization_id, kind, status);
create index if not exists idx_p0_route_plans_org_date on public.p0_route_plans(organization_id, plan_date, status);
create index if not exists idx_p0_dispatch_org_status on public.p0_roster_assignments(organization_id, status, response_deadline);
create index if not exists idx_p0_safety_org_status on public.p0_safety_incidents(organization_id, status, severity, due_at);
create index if not exists idx_p0_network_messages_thread on public.p0_network_messages(organization_id, thread_key, created_at);
create index if not exists idx_p0_network_metrics_service on public.p0_network_metric_observations(organization_id, service_order_id, metric_key, observed_at);
create index if not exists idx_p0_network_settlements_status on public.p0_network_settlement_statements(organization_id, status, period_end);

-- RLS: every P0 record is tenant-scoped. Complex lifecycle transitions belong in
-- RPCs/Edge Functions and must repeat these organization and permission checks.
do $$
declare
  t text;
  read_permission text;
  write_permission text;
begin
  foreach t in array array[
    'p0_role_permissions','p0_master_records','p0_master_versions','p0_sites','p0_shifts','p0_route_plans','p0_route_stops',
    'p0_roster_assignments','p0_replacements','p0_dispatch_events','p0_safety_policies','p0_safety_incidents',
    'p0_safety_actions','p0_network_regions','p0_network_vendor_approvals','p0_network_quote_evaluations',
    'p0_network_messages','p0_network_metric_observations','p0_network_scorecard_runs','p0_network_corrective_actions',
    'p0_network_disputes','p0_network_settlement_statements','p0_network_settlement_lines'
  ] loop
    if t = 'p0_role_permissions' then
      read_permission := 'p0.permissions.read'; write_permission := 'p0.permissions.write';
    elsif t like 'p0_master_%' or t in ('p0_sites','p0_shifts') then
      read_permission := 'p0.masters.read'; write_permission := 'p0.masters.write';
    elsif t in ('p0_route_plans','p0_route_stops') then
      read_permission := 'p0.route_plans.read'; write_permission := 'p0.route_plans.write';
    elsif t in ('p0_roster_assignments','p0_replacements','p0_dispatch_events') then
      read_permission := 'p0.route_plans.read'; write_permission := 'p0.dispatch.write';
    elsif t like 'p0_safety_%' then
      read_permission := 'p0.safety.read'; write_permission := 'p0.safety.write';
    else
      read_permission := 'p0.network.read'; write_permission := 'p0.network.write';
    end if;
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists %I on public.%I', t || '_member_select', t);
    execute format('drop policy if exists %I on public.%I', t || '_p0_write', t);
    execute format('create policy %I on public.%I for select to authenticated using (public.has_permission(organization_id, %L) or public.is_platform_user())', t || '_member_select', t, read_permission);
    execute format('create policy %I on public.%I for all to authenticated using (public.has_permission(organization_id, %L) or public.is_platform_user()) with check (public.has_permission(organization_id, %L) or public.is_platform_user())', t || '_p0_write', t, write_permission, write_permission);
  end loop;
end $$;

-- Append-only audit trail for direct PostgREST writes. Edge Functions/RPCs may
-- add richer before/after metadata, but this trigger prevents silent changes.
create or replace function public.p0_audit_row()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  row_data jsonb;
  org_id uuid;
  row_id uuid;
begin
  row_data := case when tg_op = 'DELETE' then to_jsonb(old) else to_jsonb(new) end;
  org_id := nullif(row_data ->> 'organization_id', '')::uuid;
  row_id := nullif(row_data ->> 'id', '')::uuid;
  insert into public.audit_events(organization_id, actor_id, action, entity_type, entity_id, after_data, metadata)
  values (org_id, auth.uid(), 'p0.' || lower(tg_table_name) || '.' || lower(tg_op), tg_table_name, row_id,
          case when tg_op = 'DELETE' then null else row_data end,
          jsonb_build_object('source', 'p0_row_trigger'));
  if tg_op = 'DELETE' then
    return old;
  end if;
  return new;
end;
$$;

do $$
declare t text;
begin
  foreach t in array array[
    'p0_role_permissions','p0_master_records','p0_master_versions','p0_sites','p0_shifts','p0_route_plans','p0_route_stops',
    'p0_roster_assignments','p0_replacements','p0_dispatch_events','p0_safety_policies','p0_safety_incidents',
    'p0_safety_actions','p0_network_regions','p0_network_vendor_approvals','p0_network_quote_evaluations',
    'p0_network_messages','p0_network_metric_observations','p0_network_scorecard_runs','p0_network_corrective_actions',
    'p0_network_disputes','p0_network_settlement_statements','p0_network_settlement_lines'
  ] loop
    execute format('drop trigger if exists %I on public.%I', t || '_audit', t);
    execute format('create trigger %I after insert or update or delete on public.%I for each row execute function public.p0_audit_row()', t || '_audit', t);
  end loop;
end $$;

-- Membership-aware driver response needs a narrower policy than generic writes.
drop policy if exists p0_roster_assignments_driver_response on public.p0_roster_assignments;
create policy p0_roster_assignments_driver_response on public.p0_roster_assignments for update to authenticated using (
  exists (select 1 from public.drivers d where d.id = driver_id and d.user_id = auth.uid())
  and public.has_permission(organization_id, 'p0.dispatch.respond')
) with check (
  exists (select 1 from public.drivers d where d.id = driver_id and d.user_id = auth.uid())
  and public.has_permission(organization_id, 'p0.dispatch.respond')
);

-- Effective dates and status transitions must be enforced by the production
-- orchestrator; these tables intentionally do not grant anonymous access.
grant select, insert, update on all tables in schema public to authenticated;
