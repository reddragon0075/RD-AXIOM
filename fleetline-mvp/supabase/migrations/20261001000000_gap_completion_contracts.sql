-- Axiom Fleet enterprise completion contracts.
--
-- This migration is intentionally additive.  It covers the employee/passenger
-- request boundary, route/location evidence, driver rollout readiness, safe
-- provider configuration, tokenized collection, lifecycle sync, closed
-- supplier exchange and explainable expense forecasting.  It does not add
-- public marketplace behavior and it does not add Tally/Tally Prime export.
-- External credentials are references only; provider calls stay behind an Edge
-- adapter and must be validated in a real project before production use.

insert into public.permissions(key, description) values
  ('passenger.book', 'Create and decide passenger and employee booking requests'),
  ('operations.route_evidence', 'Manage background route and passenger location evidence'),
  ('operations.alerts', 'Manage driver alert policies and alert resolution'),
  ('integrations.manage', 'Configure provider connections and lifecycle sync boundaries'),
  ('payments.auto_collect', 'Manage tokenized payment authorizations and auto-collection'),
  ('finance.forecast', 'Manage corporate expense budgets and forecasts'),
  ('network.supplier_exchange', 'Exchange qualification, contract and rate data inside closed Network programs')
on conflict (key) do nothing;

insert into public.role_permissions(role, permission_key)
select r.role, p.key
from (values
  ('vendor_owner'::public.membership_role), ('vendor_ops'::public.membership_role),
  ('vendor_dispatch'::public.membership_role), ('vendor_finance'::public.membership_role),
  ('corporate_admin'::public.membership_role), ('corporate_travel'::public.membership_role),
  ('corporate_finance'::public.membership_role)
) as r(role)
cross join (values
  ('passenger.book'), ('operations.route_evidence'), ('operations.alerts'),
  ('integrations.manage'), ('payments.auto_collect'), ('finance.forecast'),
  ('network.supplier_exchange')
) as p(key)
on conflict do nothing;

create table if not exists public.gap_passenger_booking_requests (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  requester_user_id uuid not null references auth.users(id) on delete restrict,
  passenger_name text not null,
  passenger_phone text not null default '',
  passenger_email citext not null default '',
  customer_id uuid references public.customers(id) on delete set null,
  scheduled_at timestamptz not null,
  pickup jsonb not null default '{}',
  dropoff jsonb not null default '{}',
  duty_type text not null default 'local',
  notes text not null default '',
  status text not null default 'pending' check (status in ('pending','approved','rejected','cancelled')),
  booking_id uuid references public.bookings(id) on delete set null,
  decision_note text not null default '',
  decision_by uuid references auth.users(id) on delete set null,
  decision_at timestamptz,
  idempotency_key text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);

create table if not exists public.gap_route_logs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  duty_id uuid not null references public.duties(id) on delete cascade,
  status text not null default 'recording' check (status in ('recording','completed','aborted')),
  tracking_mode text not null default 'background',
  provider text not null default 'mock_gps',
  started_at timestamptz not null default now(),
  stopped_at timestamptz,
  summary jsonb not null default '{}',
  idempotency_key text,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);
create table if not exists public.gap_route_points (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  route_log_id uuid not null references public.gap_route_logs(id) on delete cascade,
  duty_id uuid not null references public.duties(id) on delete cascade,
  recorded_at timestamptz not null,
  latitude numeric(9,6) not null check (latitude between -90 and 90),
  longitude numeric(9,6) not null check (longitude between -180 and 180),
  accuracy_m numeric,
  speed_kph numeric,
  heading numeric,
  battery_pct numeric,
  source text not null default 'driver_background',
  idempotency_key text,
  created_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);
create index if not exists idx_gap_route_points_duty on public.gap_route_points(organization_id, duty_id, recorded_at);

create table if not exists public.gap_location_shares (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  duty_id uuid not null references public.duties(id) on delete cascade,
  token_hash text not null unique,
  recipient text not null default '',
  status text not null default 'active' check (status in ('active','revoked','expired')),
  expires_at timestamptz not null,
  last_accessed_at timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);

create table if not exists public.gap_driver_alert_policies (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  name text not null,
  alert_type text not null,
  severity text not null default 'warning',
  threshold jsonb not null default '{}',
  channels jsonb not null default '["push"]',
  localized_guidance jsonb not null default '{}',
  enabled boolean not null default true,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, name)
);
create table if not exists public.gap_driver_alert_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  duty_id uuid not null references public.duties(id) on delete cascade,
  policy_id uuid references public.gap_driver_alert_policies(id) on delete set null,
  alert_type text not null,
  severity text not null,
  status text not null default 'open' check (status in ('open','acknowledged','resolved')),
  payload jsonb not null default '{}',
  occurred_at timestamptz not null default now(),
  acknowledged_by uuid references auth.users(id) on delete set null,
  acknowledged_at timestamptz,
  resolved_by uuid references auth.users(id) on delete set null,
  resolved_at timestamptz,
  idempotency_key text,
  created_by uuid references auth.users(id) on delete set null,
  unique (organization_id, idempotency_key)
);

create table if not exists public.gap_device_readiness (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  device_id text not null,
  platform text not null default 'android',
  app_version text not null default '',
  os_version text not null default '',
  permissions jsonb not null default '{}',
  readiness_status text not null default 'blocked' check (readiness_status in ('ready','blocked')),
  blockers jsonb not null default '[]',
  push_token_present boolean not null default false,
  checked_at timestamptz not null default now(),
  unique (organization_id, user_id, device_id)
);

create table if not exists public.gap_provider_connections (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  provider_type text not null,
  name text not null,
  mode text not null default 'mock' check (mode in ('mock','sandbox','production')),
  status text not null default 'configured',
  credential_ref text not null default '',
  config jsonb not null default '{}',
  capabilities jsonb not null default '[]',
  last_tested_at timestamptz,
  last_error text not null default '',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, provider_type, name)
);

create table if not exists public.gap_payment_authorizations (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  customer_id uuid references public.customers(id) on delete set null,
  payer_email citext not null default '',
  provider text not null default 'mock_payment',
  token_fingerprint text not null,
  token_last4 text not null default '',
  max_amount_paise bigint not null default 0 check (max_amount_paise >= 0),
  currency text not null default 'INR',
  status text not null default 'active' check (status in ('active','revoked','expired')),
  authorized_at timestamptz not null default now(),
  expires_at timestamptz,
  idempotency_key text,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);
create table if not exists public.gap_auto_collect_attempts (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  authorization_id uuid not null references public.gap_payment_authorizations(id) on delete restrict,
  invoice_id uuid not null references public.invoices(id) on delete restrict,
  amount_paise bigint not null check (amount_paise > 0),
  status text not null default 'queued',
  provider_reference text not null default '',
  provider_payload jsonb not null default '{}',
  error_message text not null default '',
  idempotency_key text,
  attempted_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  unique (organization_id, idempotency_key)
);

create table if not exists public.gap_invoice_automation_policies (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  name text not null,
  customer_id uuid references public.customers(id) on delete set null,
  trigger_event text not null default 'duty_completed',
  issue_einvoice boolean not null default false,
  collect_payment boolean not null default false,
  send_channel text not null default 'email',
  payment_terms_days integer not null default 7 check (payment_terms_days >= 0),
  enabled boolean not null default true,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, name)
);
create table if not exists public.gap_invoice_automation_runs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  policy_id uuid references public.gap_invoice_automation_policies(id) on delete set null,
  duty_id uuid not null references public.duties(id) on delete cascade,
  invoice_id uuid references public.invoices(id) on delete set null,
  status text not null default 'queued',
  result jsonb not null default '{}',
  idempotency_key text,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);

create table if not exists public.gap_custom_field_values (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  field_id uuid not null references public.enterprise_custom_fields(id) on delete cascade,
  entity_type text not null,
  entity_id uuid not null,
  value jsonb not null default 'null',
  updated_by uuid references auth.users(id) on delete set null,
  updated_at timestamptz not null default now(),
  unique (organization_id, field_id, entity_type, entity_id)
);
create table if not exists public.gap_sync_runs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  sync_type text not null check (sync_type in ('hrms','passenger_lifecycle','corporate_provisioning')),
  provider text not null,
  status text not null default 'accepted',
  records_received integer not null default 0,
  records_applied integer not null default 0,
  provider_reference text not null default '',
  result jsonb not null default '{}',
  idempotency_key text,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);
create table if not exists public.gap_supplier_exchange_jobs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  network_program_id uuid not null,
  supplier_id uuid not null references public.suppliers(id) on delete restrict,
  direction text not null default 'outbound',
  visibility text not null default 'invite_only' check (visibility in ('invite_only','closed_b2b')),
  status text not null default 'queued',
  qualification jsonb not null default '{}',
  contract jsonb not null default '{}',
  rate_card jsonb not null default '{}',
  payload jsonb not null default '{}',
  idempotency_key text,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);
create table if not exists public.gap_expense_budgets (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  period_key text not null check (period_key ~ '^[0-9]{4}-[0-9]{2}$'),
  customer_id uuid references public.customers(id) on delete set null,
  budget_paise bigint not null check (budget_paise >= 0),
  alert_threshold_bps integer not null default 8000 check (alert_threshold_bps between 0 and 10000),
  status text not null default 'active',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, period_key, customer_id)
);

create index if not exists idx_gap_booking_requests_org_status on public.gap_passenger_booking_requests(organization_id, status, scheduled_at);
create index if not exists idx_gap_alert_events_duty on public.gap_driver_alert_events(organization_id, duty_id, status, occurred_at);
create index if not exists idx_gap_sync_runs_org on public.gap_sync_runs(organization_id, created_at desc);
create index if not exists idx_gap_exchange_jobs_org on public.gap_supplier_exchange_jobs(organization_id, network_program_id, status);

-- Every table is tenant-filtered at the database boundary.  Writes require the
-- feature permission, while members may read their own organization records.
do $$
declare
  table_name text;
begin
  foreach table_name in array array[
    'gap_passenger_booking_requests','gap_route_logs','gap_route_points','gap_location_shares',
    'gap_driver_alert_policies','gap_driver_alert_events','gap_device_readiness','gap_provider_connections',
    'gap_payment_authorizations','gap_auto_collect_attempts','gap_invoice_automation_policies',
    'gap_invoice_automation_runs','gap_custom_field_values','gap_sync_runs','gap_supplier_exchange_jobs','gap_expense_budgets'
  ] loop
    execute format('alter table public.%I enable row level security', table_name);
    execute format('drop policy if exists %I on public.%I', table_name || '_member_select', table_name);
    execute format('drop policy if exists %I on public.%I', table_name || '_operator_write', table_name);
    execute format('create policy %I on public.%I for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user())', table_name || '_member_select', table_name);
    execute format('create policy %I on public.%I for all to authenticated using (public.has_permission(organization_id, ''integrations.manage'') or public.is_platform_user()) with check (public.has_permission(organization_id, ''integrations.manage'') or public.is_platform_user())', table_name || '_operator_write', table_name);
  end loop;
end $$;

-- Reuse the foundation audit trigger when the P0 migration is present.  The
-- guard keeps this migration applyable in a staged project while ensuring the
-- final production ordering records every insert/update/delete as evidence.
do $$
declare
  table_name text;
begin
  if to_regprocedure('public.p0_audit_row()') is not null then
    foreach table_name in array array[
      'gap_passenger_booking_requests','gap_route_logs','gap_route_points','gap_location_shares',
      'gap_driver_alert_policies','gap_driver_alert_events','gap_device_readiness','gap_provider_connections',
      'gap_payment_authorizations','gap_auto_collect_attempts','gap_invoice_automation_policies',
      'gap_invoice_automation_runs','gap_custom_field_values','gap_sync_runs','gap_supplier_exchange_jobs','gap_expense_budgets'
    ] loop
      execute format('drop trigger if exists %I on public.%I', table_name || '_audit', table_name);
      execute format('create trigger %I after insert or update or delete on public.%I for each row execute function public.p0_audit_row()', table_name || '_audit', table_name);
    end loop;
  end if;
end $$;

-- More specific feature permissions are enforced by the Edge orchestrator.  A
-- platform/service worker can process provider callbacks without bypassing
-- tenant filters in user-facing queries.
grant select, insert, update on
  public.gap_passenger_booking_requests, public.gap_route_logs, public.gap_route_points,
  public.gap_location_shares, public.gap_driver_alert_policies, public.gap_driver_alert_events,
  public.gap_device_readiness, public.gap_provider_connections, public.gap_payment_authorizations,
  public.gap_auto_collect_attempts, public.gap_invoice_automation_policies,
  public.gap_invoice_automation_runs, public.gap_custom_field_values, public.gap_sync_runs,
  public.gap_supplier_exchange_jobs, public.gap_expense_budgets to authenticated;

comment on table public.gap_provider_connections is 'Provider-neutral configuration; credential_ref points to secret storage and never stores raw provider secrets.';
comment on table public.gap_payment_authorizations is 'Tokenized payment metadata only; raw card/bank details must never enter this table.';
comment on table public.gap_supplier_exchange_jobs is 'Closed B2B Network exchange only; visibility is constrained to invite_only or closed_b2b.';
