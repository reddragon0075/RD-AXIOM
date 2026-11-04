-- Axiom Network governed MVP. Additive to the existing network_edges,
-- network_offers, network_bids and settlements compatibility contracts.
--
-- The module is closed and invite-only: there is no public vendor
-- registration table or anonymous marketplace flow. Every buyer-facing row is
-- tenant scoped, while explicitly authorized vendor reads/writes are granted
-- only through a buyer-owned vendor profile and an active membership in the
-- vendor organization.

create table if not exists public.network_feature_flags (
  organization_id uuid primary key references public.organizations(id) on delete cascade,
  enabled boolean not null default true,
  mode text not null default 'closed_invite_only',
  updated_by uuid references auth.users(id) on delete set null,
  updated_at timestamptz not null default now()
);
create table if not exists public.network_invites (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  vendor_organization_id uuid references public.organizations(id) on delete set null,
  vendor_name text not null default '',
  invite_email citext not null default '',
  status text not null default 'pending',
  expires_at timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  accepted_at timestamptz,
  revoked_at timestamptz,
  idempotency_key text,
  unique(organization_id, idempotency_key)
);
create table if not exists public.network_programs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  code text not null,
  name text not null,
  description text not null default '',
  status text not null default 'active',
  settings jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(organization_id, code)
);
create table if not exists public.network_requirements (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  program_id uuid not null references public.network_programs(id) on delete restrict,
  reference text not null,
  status text not null default 'draft',
  current_version integer,
  current_version_id uuid,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(organization_id, reference)
);
create table if not exists public.network_requirement_versions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  requirement_id uuid not null references public.network_requirements(id) on delete cascade,
  version integer not null,
  status text not null default 'draft',
  payload jsonb not null default '{}',
  change_note text not null default '',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  published_at timestamptz,
  unique(organization_id, requirement_id, version)
);
alter table public.network_requirements
  drop constraint if exists network_requirements_current_version_fk;
alter table public.network_requirements
  add constraint network_requirements_current_version_fk
  foreign key(current_version_id) references public.network_requirement_versions(id) on delete set null;

create table if not exists public.network_vendor_profiles (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  vendor_organization_id uuid not null references public.organizations(id) on delete cascade,
  vendor_name text not null,
  status text not null default 'active',
  cities text[] not null default '{}',
  service_types text[] not null default '{}',
  vehicle_types text[] not null default '{}',
  capabilities text[] not null default '{}',
  capacity jsonb not null default '{}',
  compliance jsonb not null default '{}',
  metadata jsonb not null default '{}',
  invite_id uuid references public.network_invites(id) on delete set null,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(organization_id, vendor_organization_id)
);
create table if not exists public.network_match_runs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  requirement_id uuid not null references public.network_requirements(id) on delete cascade,
  requirement_version_id uuid not null references public.network_requirement_versions(id) on delete restrict,
  rules_version text not null,
  status text not null default 'completed',
  rules jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  idempotency_key text,
  unique(organization_id, idempotency_key)
);
create table if not exists public.network_candidates (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  match_run_id uuid not null references public.network_match_runs(id) on delete cascade,
  requirement_id uuid not null references public.network_requirements(id) on delete cascade,
  vendor_profile_id uuid not null references public.network_vendor_profiles(id) on delete cascade,
  eligible boolean not null default false,
  exclusion_reasons jsonb not null default '[]',
  score jsonb not null default '{}',
  created_at timestamptz not null default now(),
  unique(match_run_id, vendor_profile_id)
);
create table if not exists public.network_quotes (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  requirement_id uuid not null references public.network_requirements(id) on delete cascade,
  vendor_profile_id uuid not null references public.network_vendor_profiles(id) on delete restrict,
  bidder_organization_id uuid not null references public.organizations(id) on delete restrict,
  status text not null default 'submitted',
  current_version integer not null default 0,
  current_version_id uuid,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(organization_id, requirement_id, vendor_profile_id)
);
create table if not exists public.network_quote_versions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  quote_id uuid not null references public.network_quotes(id) on delete cascade,
  requirement_id uuid not null references public.network_requirements(id) on delete cascade,
  vendor_profile_id uuid not null references public.network_vendor_profiles(id) on delete restrict,
  version integer not null,
  status text not null default 'submitted',
  payload jsonb not null default '{}',
  assumptions jsonb not null default '{}',
  submitted_by uuid references auth.users(id) on delete set null,
  submitted_at timestamptz not null default now(),
  idempotency_key text,
  unique(organization_id, idempotency_key),
  unique(quote_id, version)
);
alter table public.network_quotes
  drop constraint if exists network_quotes_current_version_fk;
alter table public.network_quotes
  add constraint network_quotes_current_version_fk
  foreign key(current_version_id) references public.network_quote_versions(id) on delete set null;
create table if not exists public.network_quote_line_items (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  quote_version_id uuid not null references public.network_quote_versions(id) on delete cascade,
  line_code text not null,
  description text not null default '',
  unit text not null default '',
  quantity numeric not null default 1,
  unit_paise bigint not null default 0,
  amount_paise bigint not null default 0,
  tax_bps integer not null default 0,
  created_at timestamptz not null default now(),
  unique(quote_version_id, line_code)
);
create table if not exists public.network_record_versions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  entity_type text not null,
  entity_id uuid not null,
  version integer not null,
  change_type text not null default 'snapshot',
  payload jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique(organization_id, entity_type, entity_id, version)
);
create table if not exists public.network_comparisons (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  requirement_id uuid not null references public.network_requirements(id) on delete cascade,
  match_run_id uuid references public.network_match_runs(id) on delete set null,
  status text not null default 'ready',
  quote_version_ids jsonb not null default '[]',
  quote_snapshots jsonb not null default '[]',
  rules jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  idempotency_key text,
  unique(organization_id, idempotency_key)
);
create table if not exists public.network_awards (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  requirement_id uuid not null references public.network_requirements(id) on delete cascade,
  comparison_id uuid not null references public.network_comparisons(id) on delete restrict,
  quote_version_id uuid not null references public.network_quote_versions(id) on delete restrict,
  vendor_profile_id uuid not null references public.network_vendor_profiles(id) on delete restrict,
  status text not null default 'pending_approval',
  award_reason text not null default '',
  rejected_alternatives jsonb not null default '[]',
  terms jsonb not null default '{}',
  approved_by uuid references auth.users(id) on delete set null,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  approved_at timestamptz,
  idempotency_key text,
  unique(organization_id, idempotency_key)
);
create table if not exists public.network_contracts (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  award_id uuid not null unique references public.network_awards(id) on delete cascade,
  status text not null default 'draft',
  starts_at timestamptz,
  ends_at timestamptz,
  terms jsonb not null default '{}',
  signed_by uuid references auth.users(id) on delete set null,
  signed_at timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.network_slas (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  contract_id uuid not null references public.network_contracts(id) on delete cascade,
  metric text not null,
  target_value numeric not null default 0,
  unit text not null default '',
  severity text not null default 'warning',
  evidence_required boolean not null default true,
  created_at timestamptz not null default now(),
  unique(contract_id, metric)
);
create table if not exists public.network_activation_checks (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  award_id uuid not null references public.network_awards(id) on delete cascade,
  check_key text not null,
  status text not null default 'pending',
  blocking boolean not null default true,
  evidence jsonb not null default '{}',
  checked_by uuid references auth.users(id) on delete set null,
  checked_at timestamptz,
  unique(award_id, check_key)
);
create table if not exists public.network_service_orders (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  award_id uuid not null unique references public.network_awards(id) on delete restrict,
  contract_id uuid not null references public.network_contracts(id) on delete restrict,
  requirement_id uuid not null references public.network_requirements(id) on delete restrict,
  vendor_profile_id uuid not null references public.network_vendor_profiles(id) on delete restrict,
  status text not null default 'active',
  fleet_booking_id uuid references public.bookings(id) on delete restrict,
  fleet_duty_id uuid references public.duties(id) on delete restrict,
  config jsonb not null default '{}',
  activated_by uuid references auth.users(id) on delete set null,
  activated_at timestamptz not null default now(),
  idempotency_key text,
  unique(organization_id, idempotency_key)
);
create table if not exists public.network_scorecards (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  service_order_id uuid not null references public.network_service_orders(id) on delete cascade,
  period_start date not null,
  period_end date not null,
  status text not null default 'submitted',
  metrics jsonb not null default '{}',
  evidence jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  idempotency_key text,
  unique(organization_id, idempotency_key)
);
create table if not exists public.network_settlements (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  service_order_id uuid not null references public.network_service_orders(id) on delete cascade,
  scorecard_id uuid references public.network_scorecards(id) on delete set null,
  period_start date not null,
  period_end date not null,
  gross_paise bigint not null default 0 check(gross_paise >= 0),
  deductions_paise bigint not null default 0 check(deductions_paise >= 0 and deductions_paise <= gross_paise),
  net_paise bigint generated always as (gross_paise - deductions_paise) stored,
  status text not null default 'draft',
  evidence jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  idempotency_key text,
  unique(organization_id, idempotency_key)
);
create table if not exists public.network_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  event_type text not null,
  aggregate_type text not null,
  aggregate_id uuid not null,
  payload jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);

create index if not exists idx_network_programs_org_status on public.network_programs(organization_id, status, updated_at desc);
create index if not exists idx_network_requirements_org_status on public.network_requirements(organization_id, status, updated_at desc);
create index if not exists idx_network_requirement_versions_requirement on public.network_requirement_versions(requirement_id, version desc);
create index if not exists idx_network_vendor_profiles_org_status on public.network_vendor_profiles(organization_id, status);
create index if not exists idx_network_vendor_profiles_vendor_org on public.network_vendor_profiles(vendor_organization_id, status);
create index if not exists idx_network_candidates_requirement on public.network_candidates(requirement_id, eligible, created_at desc);
create index if not exists idx_network_quotes_requirement on public.network_quotes(organization_id, requirement_id, status);
create index if not exists idx_network_quote_versions_quote on public.network_quote_versions(quote_id, version desc);
create index if not exists idx_network_quote_line_items_version on public.network_quote_line_items(quote_version_id, created_at);
create index if not exists idx_network_record_versions_entity on public.network_record_versions(organization_id, entity_type, entity_id, version desc);
create index if not exists idx_network_awards_org_status on public.network_awards(organization_id, status, created_at desc);
create index if not exists idx_network_checks_award on public.network_activation_checks(award_id, status);
create index if not exists idx_network_service_orders_org_status on public.network_service_orders(organization_id, status, activated_at desc);
create index if not exists idx_network_scorecards_order on public.network_scorecards(service_order_id, period_start desc);
create index if not exists idx_network_settlements_order on public.network_settlements(service_order_id, period_start desc);
create index if not exists idx_network_events_org_time on public.network_events(organization_id, created_at desc);

-- Reuse the foundation updated-at function where appropriate.
drop trigger if exists network_programs_updated_at on public.network_programs;
create trigger network_programs_updated_at before update on public.network_programs for each row execute procedure public.set_updated_at();
drop trigger if exists network_requirements_updated_at on public.network_requirements;
create trigger network_requirements_updated_at before update on public.network_requirements for each row execute procedure public.set_updated_at();
drop trigger if exists network_vendor_profiles_updated_at on public.network_vendor_profiles;
create trigger network_vendor_profiles_updated_at before update on public.network_vendor_profiles for each row execute procedure public.set_updated_at();
drop trigger if exists network_quotes_updated_at on public.network_quotes;
create trigger network_quotes_updated_at before update on public.network_quotes for each row execute procedure public.set_updated_at();
drop trigger if exists network_contracts_updated_at on public.network_contracts;
create trigger network_contracts_updated_at before update on public.network_contracts for each row execute procedure public.set_updated_at();

-- Tenant policies. The exceptions below use explicit candidate/profile links
-- so a vendor can only see its own requirement/quote surface.
do $$
declare t text;
begin
  foreach t in array array[
    'network_feature_flags','network_invites','network_programs','network_requirements',
    'network_requirement_versions','network_vendor_profiles','network_match_runs',
    'network_candidates','network_quotes','network_quote_versions','network_quote_line_items','network_record_versions','network_comparisons',
    'network_awards','network_contracts','network_slas','network_activation_checks',
    'network_service_orders','network_scorecards','network_settlements','network_events'
  ] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('grant select, insert, update on public.%I to authenticated', t);
    execute format('drop policy if exists %I on public.%I', t || '_tenant_access', t);
    execute format('create policy %I on public.%I for all to authenticated using (public.is_org_member(organization_id) or public.is_platform_user()) with check (public.is_org_member(organization_id) or public.is_platform_user())', t || '_tenant_access', t);
  end loop;
end $$;

-- Vendor-side access is intentionally narrower than a generic tenant policy.
drop policy if exists network_vendor_profiles_tenant_access on public.network_vendor_profiles;
create policy network_vendor_profiles_tenant_access on public.network_vendor_profiles for all to authenticated
using (public.is_org_member(organization_id) or public.is_org_member(vendor_organization_id) or public.is_platform_user())
with check (public.is_org_member(organization_id) or public.is_platform_user());

drop policy if exists network_requirements_tenant_access on public.network_requirements;
create policy network_requirements_tenant_access on public.network_requirements for all to authenticated
using (
  public.is_org_member(organization_id)
  or public.is_platform_user()
  or exists (
    select 1 from public.network_candidates c
    join public.network_vendor_profiles v on v.id = c.vendor_profile_id
    where c.requirement_id = network_requirements.id
      and c.eligible
      and public.is_org_member(v.vendor_organization_id)
  )
)
with check (public.is_org_member(organization_id) or public.is_platform_user());

drop policy if exists network_requirement_versions_tenant_access on public.network_requirement_versions;
create policy network_requirement_versions_tenant_access on public.network_requirement_versions for all to authenticated
using (
  public.is_org_member(organization_id)
  or public.is_platform_user()
  or exists (
    select 1 from public.network_candidates c
    join public.network_vendor_profiles v on v.id = c.vendor_profile_id
    where c.requirement_id = network_requirement_versions.requirement_id
      and c.eligible
      and public.is_org_member(v.vendor_organization_id)
  )
)
with check (public.is_org_member(organization_id) or public.is_platform_user());

drop policy if exists network_candidates_tenant_access on public.network_candidates;
create policy network_candidates_tenant_access on public.network_candidates for all to authenticated
using (
  public.is_org_member(organization_id)
  or public.is_platform_user()
  or exists (select 1 from public.network_vendor_profiles v where v.id = network_candidates.vendor_profile_id and public.is_org_member(v.vendor_organization_id))
)
with check (public.is_org_member(organization_id) or public.is_platform_user());

drop policy if exists network_quotes_tenant_access on public.network_quotes;
create policy network_quotes_tenant_access on public.network_quotes for all to authenticated
using (
  public.is_org_member(organization_id)
  or public.is_platform_user()
  or public.is_org_member(bidder_organization_id)
)
with check (
  public.is_org_member(organization_id)
  or public.is_platform_user()
  or (
    public.is_org_member(bidder_organization_id)
    and exists (
      select 1 from public.network_vendor_profiles v
      where v.id = network_quotes.vendor_profile_id
        and v.organization_id = network_quotes.organization_id
        and v.vendor_organization_id = network_quotes.bidder_organization_id
    )
  )
);

drop policy if exists network_quote_versions_tenant_access on public.network_quote_versions;
create policy network_quote_versions_tenant_access on public.network_quote_versions for all to authenticated
using (
  public.is_org_member(organization_id)
  or public.is_platform_user()
  or exists (select 1 from public.network_quotes q where q.id = network_quote_versions.quote_id and public.is_org_member(q.bidder_organization_id))
)
with check (
  public.is_org_member(organization_id)
  or public.is_platform_user()
  or exists (select 1 from public.network_quotes q where q.id = network_quote_versions.quote_id and public.is_org_member(q.bidder_organization_id))
);

drop policy if exists network_quote_line_items_tenant_access on public.network_quote_line_items;
create policy network_quote_line_items_tenant_access on public.network_quote_line_items for all to authenticated
using (
  public.is_org_member(organization_id)
  or public.is_platform_user()
  or exists (
    select 1 from public.network_quote_versions v
    join public.network_quotes q on q.id = v.quote_id
    where v.id = network_quote_line_items.quote_version_id and public.is_org_member(q.bidder_organization_id)
  )
)
with check (
  public.is_org_member(organization_id)
  or public.is_platform_user()
  or exists (
    select 1 from public.network_quote_versions v
    join public.network_quotes q on q.id = v.quote_id
    where v.id = network_quote_line_items.quote_version_id and public.is_org_member(q.bidder_organization_id)
  )
);

-- Immutable payload/snapshot safeguards. Status transitions may update the
-- quote envelope, but commercial payloads and buyer decision snapshots cannot
-- be overwritten in place.
create or replace function public.prevent_network_snapshot_mutation()
returns trigger
language plpgsql
as $$
begin
  if tg_table_name = 'network_quote_versions' then
    if old.payload is distinct from new.payload
       or old.assumptions is distinct from new.assumptions
       or old.version is distinct from new.version
       or old.quote_id is distinct from new.quote_id then
      raise exception 'Network quote versions are immutable; submit a new version';
    end if;
    return new;
  elsif tg_table_name = 'network_requirement_versions' then
    if old.payload is distinct from new.payload
       or old.version is distinct from new.version
       or old.requirement_id is distinct from new.requirement_id then
      raise exception 'Network requirement versions are immutable; create a new version';
    end if;
    return new;
  elsif tg_table_name = 'network_comparisons' then
    raise exception 'Network comparison snapshots are immutable';
  elsif tg_table_name = 'network_quote_line_items' then
    raise exception 'Network quote line items are immutable';
  elsif tg_table_name = 'network_record_versions' then
    raise exception 'Network record versions are immutable';
  end if;
  return new;
end;
$$;

drop trigger if exists network_quote_versions_immutable on public.network_quote_versions;
create trigger network_quote_versions_immutable before update on public.network_quote_versions for each row execute procedure public.prevent_network_snapshot_mutation();
drop trigger if exists network_requirement_versions_immutable on public.network_requirement_versions;
create trigger network_requirement_versions_immutable before update on public.network_requirement_versions for each row execute procedure public.prevent_network_snapshot_mutation();
drop trigger if exists network_comparisons_immutable on public.network_comparisons;
create trigger network_comparisons_immutable before update on public.network_comparisons for each row execute procedure public.prevent_network_snapshot_mutation();
drop trigger if exists network_quote_line_items_immutable on public.network_quote_line_items;
create trigger network_quote_line_items_immutable before update on public.network_quote_line_items for each row execute procedure public.prevent_network_snapshot_mutation();
drop trigger if exists network_record_versions_immutable on public.network_record_versions;
create trigger network_record_versions_immutable before update on public.network_record_versions for each row execute procedure public.prevent_network_snapshot_mutation();

-- Atomic production-direction activation. The local fallback mirrors this
-- behavior in backend_network.py and creates domain Fleet booking + duty rows.
create or replace function public.network_activate_award(p_award_id uuid, p_idempotency_key text default null)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  award_row public.network_awards;
  contract_row public.network_contracts;
  requirement_row public.network_requirements;
  version_row public.network_requirement_versions;
  check_count bigint;
  failed_count bigint;
  booking_id uuid;
  duty_id uuid;
  order_id uuid;
  booking_reference text;
  spec jsonb;
  now_value timestamptz := now();
begin
  select * into award_row from public.network_awards where id = p_award_id for update;
  if award_row.id is null then raise exception 'Network award not found'; end if;
  if not public.has_permission(award_row.organization_id, 'network.manage') and not public.is_platform_user() then
    raise exception 'Network activation is not permitted';
  end if;
  if award_row.status <> 'approved' then raise exception 'Only approved awards can activate'; end if;
  select * into contract_row from public.network_contracts where award_id = award_row.id;
  if contract_row.id is null or contract_row.status not in ('signed','active') then raise exception 'The Network contract must be signed'; end if;
  select count(*), count(*) filter (where status <> 'passed') into check_count, failed_count from public.network_activation_checks where award_id = award_row.id and blocking;
  if check_count = 0 or failed_count > 0 then raise exception 'Required activation checks are incomplete'; end if;
  if p_idempotency_key is not null then
    select id into order_id from public.network_service_orders where organization_id = award_row.organization_id and idempotency_key = p_idempotency_key;
    if order_id is not null then return jsonb_build_object('duplicate', true, 'service_order_id', order_id); end if;
  end if;
  select id into order_id from public.network_service_orders where award_id = award_row.id;
  if order_id is not null then return jsonb_build_object('duplicate', true, 'service_order_id', order_id); end if;
  select * into requirement_row from public.network_requirements where id = award_row.requirement_id;
  select * into version_row from public.network_requirement_versions where id = requirement_row.current_version_id;
  spec := coalesce(version_row.payload, '{}'::jsonb);
  booking_reference := coalesce(spec ->> 'booking_reference', 'NET-' || requirement_row.reference || '-' || right(replace(award_row.id::text, '-', ''), 8));
  insert into public.bookings(organization_id, requesting_organization_id, vendor_organization_id, status, booking_reference, passenger_name, passenger_phone, pickup, dropoff, scheduled_at, duty_type, source, notes, created_by)
  values (award_row.organization_id, award_row.organization_id, (select vendor_organization_id from public.network_vendor_profiles where id = award_row.vendor_profile_id), 'confirmed', booking_reference, coalesce(spec ->> 'passenger_name', 'Network service order'), coalesce(spec ->> 'passenger_phone', ''), coalesce(spec -> 'pickup', jsonb_build_object('label', coalesce(spec ->> 'pickup_label', 'Network origin'))), coalesce(spec -> 'dropoff', jsonb_build_object('label', coalesce(spec ->> 'dropoff_label', 'Network destination'))), nullif(coalesce(spec ->> 'scheduled_at', spec ->> 'start_at'), '')::timestamptz, 'network', 'network', 'Axiom Network award ' || award_row.id::text, auth.uid())
  returning id into booking_id;
  insert into public.duties(organization_id, booking_id, status, reporting_at)
  values (award_row.organization_id, booking_id, 'draft', nullif(coalesce(spec ->> 'scheduled_at', spec ->> 'start_at'), '')::timestamptz)
  returning id into duty_id;
  insert into public.network_service_orders(organization_id, award_id, contract_id, requirement_id, vendor_profile_id, status, fleet_booking_id, fleet_duty_id, config, activated_by, activated_at, idempotency_key)
  values (award_row.organization_id, award_row.id, contract_row.id, award_row.requirement_id, award_row.vendor_profile_id, 'active', booking_id, duty_id, jsonb_build_object('spec', spec, 'fleet_booking_id', booking_id, 'fleet_duty_id', duty_id, 'requirement_version', version_row.version), auth.uid(), now_value, p_idempotency_key)
  returning id into order_id;
  update public.network_contracts set status = 'active', updated_at = now_value where id = contract_row.id;
  update public.network_requirements set status = 'activated', updated_at = now_value where id = requirement_row.id;
  insert into public.audit_events(organization_id, actor_id, action, entity_type, entity_id, metadata, created_at)
  values (award_row.organization_id, auth.uid(), 'network.service_order.activated', 'network_service_order', order_id, jsonb_build_object('award_id', award_row.id, 'fleet_booking_id', booking_id, 'fleet_duty_id', duty_id), now_value);
  return jsonb_build_object('duplicate', false, 'service_order_id', order_id, 'fleet_booking_id', booking_id, 'fleet_duty_id', duty_id);
end;
$$;

grant execute on function public.network_activate_award(uuid, text) to authenticated;
-- Keep direct table access available to authenticated clients; RLS remains the
-- authorization boundary and the activation RPC is preferred for atomicity.
grant select, insert, update on all tables in schema public to authenticated;
