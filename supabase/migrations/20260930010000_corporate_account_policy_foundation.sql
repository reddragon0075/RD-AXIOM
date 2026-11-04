-- Axiom Fleet corporate account and policy foundation.
--
-- The local fallback is implemented by backend_corporate.py.  This migration is
-- the production/Postgres counterpart: all records remain organization scoped,
-- account setup is snapshotted, policy decisions are explainable, and passenger
-- duty-slip links store only a SHA-256 token hash.  Deploy the corporate
-- orchestrator Edge Function/RPCs together with this migration.

-- The local and browser adapters represent an approval-required booking as a
-- first-class booking status.  Add it before the production write guard is
-- installed so PostgREST callers cannot bypass the state machine with a
-- status value that the base enum does not understand.
alter type public.booking_status add value if not exists 'pending_approval';

alter table public.bookings add column if not exists passenger_email text;
alter table public.bookings add column if not exists customer_entity_id text;
alter table public.bookings add column if not exists sister_company_id text;
alter table public.bookings add column if not exists company_id text;
alter table public.bookings add column if not exists vehicle_group_code text;
alter table public.bookings add column if not exists duty_type_code text;

insert into public.permissions(key, description) values
  ('corporate.account.read', 'Read corporate account connection and setup scope'),
  ('corporate.account.manage', 'Connect, configure and activate corporate accounts'),
  ('corporate.people.read', 'Read corporate account users and entitlements'),
  ('corporate.people.manage', 'Invite, activate and manage corporate account users'),
  ('corporate.booking.evaluate', 'Evaluate corporate booking and cancellation policy'),
  ('corporate.policy.read', 'Read corporate booking policy'),
  ('corporate.policy.manage', 'Create and version corporate booking policy'),
  ('corporate.visibility.evaluate', 'Evaluate corporate account visibility scope'),
  ('corporate.allotment.evaluate', 'Evaluate supplier, allotment and document eligibility'),
  ('corporate.allotment.manage', 'Create and version supplier allotment rules'),
  ('corporate.duty_slip.read', 'Read passenger duty-slip approval records'),
  ('corporate.duty_slip.decide', 'Approve, reject and auto-approve duty slips'),
  ('corporate.masters.read', 'Read corporate scoped versioned masters'),
  ('corporate.masters.manage', 'Create and version corporate scoped masters')
on conflict (key) do nothing;

insert into public.role_permissions(role, permission_key)
select r.role, p.key
from (values
  ('vendor_owner'::public.membership_role), ('vendor_ops'::public.membership_role),
  ('vendor_dispatch'::public.membership_role), ('corporate_admin'::public.membership_role),
  ('corporate_travel'::public.membership_role), ('corporate_finance'::public.membership_role)
) as r(role)
cross join public.permissions p
where p.key like 'corporate.%'
  and p.key not in ('corporate.masters.manage')
on conflict do nothing;
insert into public.role_permissions(role, permission_key)
select r.role, p.key
from (values
  ('vendor_owner'::public.membership_role), ('corporate_admin'::public.membership_role)
) as r(role)
cross join public.permissions p
where p.key in ('corporate.account.manage','corporate.people.manage','corporate.policy.manage','corporate.allotment.manage','corporate.masters.manage')
on conflict do nothing;

create table if not exists public.corporate_accounts (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  name text not null,
  connection_type text not null default 'manual',
  external_account_id text not null default '',
  customer_id uuid references public.customers(id) on delete set null,
  status text not null default 'draft' check (status in ('draft','setup','active','suspended','archived')),
  copy_pricing boolean not null default false,
  visibility jsonb not null default '{}'::jsonb,
  pricing_scope jsonb not null default '{}'::jsonb,
  setup_snapshot_id uuid,
  setup_version integer not null default 0 check (setup_version >= 0),
  activated_at timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id)
);
create index if not exists idx_corporate_accounts_org_status on public.corporate_accounts(organization_id, status);

create table if not exists public.corporate_account_snapshots (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  account_id uuid not null references public.corporate_accounts(id) on delete cascade,
  version integer not null check (version > 0),
  snapshot jsonb not null default '{}'::jsonb,
  copied_price_book_ids uuid[] not null default '{}',
  copied_at timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (account_id, version)
);
create index if not exists idx_corporate_account_snapshots_org on public.corporate_account_snapshots(organization_id, account_id, version desc);

create table if not exists public.corporate_snapshot_price_books (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  account_id uuid not null references public.corporate_accounts(id) on delete cascade,
  snapshot_id uuid not null references public.corporate_account_snapshots(id) on delete cascade,
  source_price_book_id uuid not null,
  name text not null,
  effective_from date not null,
  effective_to date,
  source_status text not null default 'draft',
  source_version integer not null default 1,
  created_at timestamptz not null default now(),
  unique (snapshot_id, source_price_book_id)
);
create table if not exists public.corporate_snapshot_price_book_items (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  account_id uuid not null references public.corporate_accounts(id) on delete cascade,
  snapshot_price_book_id uuid not null references public.corporate_snapshot_price_books(id) on delete cascade,
  source_price_book_item_id uuid not null,
  duty_type text not null,
  vehicle_group text,
  base_paise bigint not null default 0,
  per_km_paise bigint not null default 0,
  per_hour_paise bigint not null default 0,
  waiting_paise bigint not null default 0,
  tax_rate numeric(6,3) not null default 0,
  rules jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (snapshot_price_book_id, source_price_book_item_id)
);
create index if not exists idx_corporate_snapshot_price_books_snapshot on public.corporate_snapshot_price_books(snapshot_id);
create index if not exists idx_corporate_snapshot_price_items_book on public.corporate_snapshot_price_book_items(snapshot_price_book_id);

alter table public.corporate_accounts
  drop constraint if exists corporate_accounts_setup_snapshot_fk;
alter table public.corporate_accounts
  add constraint corporate_accounts_setup_snapshot_fk foreign key (setup_snapshot_id) references public.corporate_account_snapshots(id) on delete set null;

create table if not exists public.corporate_account_users (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  account_id uuid not null references public.corporate_accounts(id) on delete cascade,
  user_id uuid references auth.users(id) on delete set null,
  employee_id uuid references public.employees(id) on delete set null,
  email text not null default '',
  full_name text not null default '',
  account_type text not null default 'booker_passenger' check (account_type in ('admin','employee_admin','booker_passenger')),
  permission_profile text not null default 'booker_passenger',
  grants jsonb not null default '[]'::jsonb,
  denies jsonb not null default '[]'::jsonb,
  visibility jsonb not null default '{}'::jsonb,
  status text not null default 'invited' check (status in ('invited','active','suspended')),
  invited_by uuid references auth.users(id) on delete set null,
  activated_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (account_id, email),
  unique (account_id, user_id)
);
create index if not exists idx_corporate_account_users_org on public.corporate_account_users(organization_id, account_id, status);

create table if not exists public.corporate_allotment_rules (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  account_id uuid not null references public.corporate_accounts(id) on delete cascade,
  name text not null,
  version integer not null default 1 check (version > 0),
  status text not null default 'draft' check (status in ('draft','active','archived')),
  priority integer not null default 100 check (priority >= 0),
  supplier_ids uuid[] not null default '{}',
  vehicle_group_codes text[] not null default '{}',
  duty_type_codes text[] not null default '{}',
  cities text[] not null default '{}',
  required_document_types text[] not null default '{}',
  auto_allot boolean not null default false,
  fallback_supplier_id uuid references public.suppliers(id) on delete set null,
  max_attempts integer not null default 1 check (max_attempts between 1 and 20),
  rules jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (account_id, name, version)
);
create index if not exists idx_corporate_allotment_rules_org on public.corporate_allotment_rules(organization_id, account_id, status, priority, version desc);

create table if not exists public.corporate_policies (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  account_id uuid not null references public.corporate_accounts(id) on delete cascade,
  name text not null,
  status text not null default 'draft' check (status in ('draft','active','archived')),
  version integer not null default 1 check (version > 0),
  booking_lead_time_minutes integer check (booking_lead_time_minutes between 0 and 525600),
  cancellation_cutoff_minutes integer check (cancellation_cutoff_minutes between 0 and 525600),
  approval_required boolean not null default false,
  approval_route jsonb not null default '[]'::jsonb,
  supplier_mode text not null default 'any' check (supplier_mode in ('any','allowlist','preferred','requested_only')),
  allowed_supplier_ids uuid[] not null default '{}',
  auto_allotment_enabled boolean not null default false,
  allotment_rule_id uuid references public.corporate_allotment_rules(id) on delete set null,
  passenger_duty_slip_approval boolean not null default false,
  duty_slip_auto_approval_hours integer not null default 48 check (duty_slip_auto_approval_hours between 1 and 720),
  visibility jsonb not null default '{}'::jsonb,
  rules jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (account_id, name, version)
);
create index if not exists idx_corporate_policies_org_account on public.corporate_policies(organization_id, account_id, status, version desc);

create table if not exists public.corporate_masters (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  kind text not null check (kind in ('duty_types','vehicle_groups','billing_items','taxes','company_scopes','pricing_rules','document_requirements')),
  code text not null,
  name text not null,
  version integer not null default 1 check (version > 0),
  status text not null default 'active' check (status in ('active','archived')),
  effective_from date,
  effective_to date,
  scope jsonb not null default '{}'::jsonb,
  config jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, kind, code, version)
);
create index if not exists idx_corporate_masters_org_kind on public.corporate_masters(organization_id, kind, status, code, version desc);

create table if not exists public.corporate_duty_slip_approvals (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  account_id uuid not null references public.corporate_accounts(id) on delete cascade,
  booking_id uuid references public.bookings(id) on delete set null,
  duty_id uuid references public.duties(id) on delete set null,
  passenger_email text not null default '',
  passenger_name text not null default '',
  status text not null default 'pending' check (status in ('pending','approved','rejected','auto_approved','expired')),
  action_token_hash text not null,
  token_expires_at timestamptz not null,
  auto_approve_at timestamptz not null,
  decision_comment text not null default '',
  decision_reason text not null default '',
  decided_by uuid references auth.users(id) on delete set null,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  decided_at timestamptz,
  unique (organization_id, action_token_hash)
);
create index if not exists idx_corporate_duty_slip_approvals_org on public.corporate_duty_slip_approvals(organization_id, account_id, status, auto_approve_at);

create table if not exists public.corporate_policy_evaluations (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  account_id uuid not null references public.corporate_accounts(id) on delete cascade,
  policy_id uuid references public.corporate_policies(id) on delete set null,
  evaluation_type text not null check (evaluation_type in ('booking','visibility','allotment','document')),
  outcome text not null check (outcome in ('allow','warn','needs_approval','block')),
  request_hash text not null default '',
  request jsonb not null default '{}'::jsonb,
  reasons jsonb not null default '[]'::jsonb,
  result jsonb not null default '{}'::jsonb,
  evaluated_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);
create index if not exists idx_corporate_policy_evaluations_org on public.corporate_policy_evaluations(organization_id, account_id, created_at desc);

create table if not exists public.corporate_idempotency_keys (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  key text not null,
  route text not null,
  result jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (organization_id, key, route)
);

-- -------------------------------------------------------------------------
-- Production write guards.
--
-- The browser and Edge preflight remain useful for explainable UX, but they
-- are not an authorization boundary.  These SECURITY DEFINER trigger guards
-- enforce the same corporate transitions for direct PostgREST callers and
-- service integrations that use an authenticated user token.
-- -------------------------------------------------------------------------

create or replace function public.corporate_scope_value_allowed(
  scope jsonb,
  scope_key text,
  requested_value text
)
returns boolean
language plpgsql
stable
security definer
set search_path = public
as $$
begin
  if coalesce(btrim(requested_value), '') = '' then
    return true;
  end if;
  if scope is null or jsonb_typeof(scope -> scope_key) <> 'array'
     or jsonb_array_length(scope -> scope_key) = 0 then
    return true;
  end if;
  return exists (
    select 1
      from jsonb_array_elements_text(scope -> scope_key) as allowed(value)
     where lower(btrim(allowed.value)) = lower(btrim(requested_value))
  );
end;
$$;

create or replace function public.corporate_current_user_allows(
  target_account uuid,
  required_permission text
)
returns boolean
language plpgsql
stable
security definer
set search_path = public
as $$
declare
  account_user public.corporate_account_users%rowtype;
  account_type text;
  base_allowed boolean := false;
begin
  if auth.role() = 'service_role' or public.is_platform_user() then
    return true;
  end if;

  select * into account_user
    from public.corporate_account_users
   where account_id = target_account
     and user_id = auth.uid()
     and status = 'active'
   limit 1;

  -- Older connected accounts may not yet have account-user rows.  Their
  -- organization membership/RLS permission remains the compatibility path;
  -- once a row exists, its explicit denies and grants are authoritative.
  if not found then
    return true;
  end if;

  if exists (
    select 1 from jsonb_array_elements_text(coalesce(account_user.denies, '[]'::jsonb)) denied(value)
    where denied.value = required_permission
  ) then
    return false;
  end if;

  account_type := account_user.account_type;
  base_allowed :=
    case
      when account_type = 'admin' then true
      when account_type = 'employee_admin' and required_permission in
        ('account.read','people.read','people.manage','booking.create','booking.cancel','booking.approve','policy.read','policy.manage','allotment.evaluate','allotment.manage','duty_slip.approve','duty_slip.reject','masters.read','masters.manage') then true
      when account_type = 'booker_passenger' and required_permission in
        ('account.read','booking.create','booking.cancel','allotment.evaluate','duty_slip.approve','duty_slip.reject','policy.read') then true
      else false
    end;

  return base_allowed or exists (
    select 1 from jsonb_array_elements_text(coalesce(account_user.grants, '[]'::jsonb)) granted(value)
    where granted.value = required_permission
  );
end;
$$;

create or replace function public.corporate_raise_policy_blocked(
  reason_code text,
  reason_message text,
  reason_field text default null
)
returns void
language plpgsql
volatile
security definer
set search_path = public
as $$
begin
  raise exception using
    errcode = 'P0001',
    message = 'corporate_policy_blocked',
    detail = jsonb_build_object(
      'code', reason_code,
      'field', reason_field,
      'message', reason_message
    )::text;
end;
$$;

create or replace function public.corporate_booking_write_guard()
returns trigger
language plpgsql
volatile
security definer
set search_path = public
as $$
declare
  account_row public.corporate_accounts%rowtype;
  policy_row public.corporate_policies%rowtype;
  account_user public.corporate_account_users%rowtype;
  city_value text;
  customer_scope_value text;
  duty_scope_value text;
  booking_status_changed boolean := false;
begin
  select * into account_row
    from public.corporate_accounts
   where organization_id = new.organization_id
     and status = 'active'
   limit 1;
  if not found then
    return new;
  end if;

  if auth.role() <> 'service_role' and not public.is_platform_user() then
    if tg_op = 'INSERT' and not public.has_permission(new.organization_id, 'bookings.write') then
      perform public.corporate_raise_policy_blocked('booking_write_permission_denied', 'The signed-in user cannot create bookings.');
    end if;
    if tg_op = 'UPDATE' and new.status is distinct from old.status
       and not public.has_permission(new.organization_id, 'bookings.write') then
      perform public.corporate_raise_policy_blocked('booking_write_permission_denied', 'The signed-in user cannot change booking state.');
    end if;
  end if;

  if tg_op = 'INSERT' then
    if not public.corporate_current_user_allows(account_row.id, 'booking.create') then
      perform public.corporate_raise_policy_blocked('account_entitlement_denied', 'The corporate account user cannot create bookings.');
    end if;
  end if;

  if tg_op = 'UPDATE' then
    booking_status_changed := new.status is distinct from old.status;
    if booking_status_changed and new.status = 'cancelled' then
      if not public.corporate_current_user_allows(account_row.id, 'booking.cancel') then
        perform public.corporate_raise_policy_blocked('account_entitlement_denied', 'The corporate account user cannot cancel bookings.');
      end if;
    elsif booking_status_changed and new.status in ('approved','confirmed','disputed') then
      if auth.role() <> 'service_role' and not public.is_platform_user()
         and not public.has_permission(new.organization_id, 'bookings.approve') then
        perform public.corporate_raise_policy_blocked('booking_approval_permission_denied', 'Booking approval permission is required for this state transition.');
      end if;
      if not public.corporate_current_user_allows(account_row.id, 'booking.approve') then
        perform public.corporate_raise_policy_blocked('account_entitlement_denied', 'The corporate account user cannot approve bookings.');
      end if;
    end if;
  end if;

  select * into policy_row
    from public.corporate_policies
   where account_id = account_row.id
     and status = 'active'
   order by version desc
   limit 1;

  city_value := coalesce(new.pickup ->> 'city', new.pickup ->> 'city_name', new.pickup ->> 'label', '');
  customer_scope_value := coalesce(new.customer_entity_id, new.customer_id::text, '');
  duty_scope_value := coalesce(new.duty_type_code, new.duty_type, '');

  -- Account, user and policy scopes all act as allow-lists when populated.
  if not public.corporate_scope_value_allowed(account_row.visibility, 'branch_ids', new.branch_id::text)
     or not public.corporate_scope_value_allowed(account_row.visibility, 'customer_entity_ids', customer_scope_value)
     or not public.corporate_scope_value_allowed(account_row.visibility, 'sister_company_ids', new.sister_company_id)
     or not public.corporate_scope_value_allowed(account_row.visibility, 'cities', city_value)
     or not public.corporate_scope_value_allowed(account_row.visibility, 'vehicle_group_codes', new.vehicle_group_code)
     or not public.corporate_scope_value_allowed(account_row.visibility, 'duty_type_codes', duty_scope_value)
     or not public.corporate_scope_value_allowed(account_row.visibility, 'company_ids', new.company_id) then
    perform public.corporate_raise_policy_blocked('account_scope_denied', 'The booking is outside the corporate account visibility scope.');
  end if;

  select * into account_user
    from public.corporate_account_users
   where account_id = account_row.id
     and user_id = auth.uid()
     and status = 'active'
   limit 1;
  if found and (
       not public.corporate_scope_value_allowed(account_user.visibility, 'branch_ids', new.branch_id::text)
    or not public.corporate_scope_value_allowed(account_user.visibility, 'customer_entity_ids', customer_scope_value)
    or not public.corporate_scope_value_allowed(account_user.visibility, 'sister_company_ids', new.sister_company_id)
    or not public.corporate_scope_value_allowed(account_user.visibility, 'cities', city_value)
    or not public.corporate_scope_value_allowed(account_user.visibility, 'vehicle_group_codes', new.vehicle_group_code)
    or not public.corporate_scope_value_allowed(account_user.visibility, 'duty_type_codes', duty_scope_value)
    or not public.corporate_scope_value_allowed(account_user.visibility, 'company_ids', new.company_id)
  ) then
    perform public.corporate_raise_policy_blocked('user_scope_denied', 'The booking is outside the corporate account user visibility scope.');
  end if;

  if policy_row.id is not null then
    if not public.corporate_scope_value_allowed(policy_row.visibility, 'branch_ids', new.branch_id::text)
       or not public.corporate_scope_value_allowed(policy_row.visibility, 'customer_entity_ids', customer_scope_value)
       or not public.corporate_scope_value_allowed(policy_row.visibility, 'sister_company_ids', new.sister_company_id)
       or not public.corporate_scope_value_allowed(policy_row.visibility, 'cities', city_value)
       or not public.corporate_scope_value_allowed(policy_row.visibility, 'vehicle_group_codes', new.vehicle_group_code)
       or not public.corporate_scope_value_allowed(policy_row.visibility, 'duty_type_codes', duty_scope_value)
       or not public.corporate_scope_value_allowed(policy_row.visibility, 'company_ids', new.company_id) then
      perform public.corporate_raise_policy_blocked('policy_scope_denied', 'The booking is outside the active corporate policy scope.');
    end if;

    if policy_row.booking_lead_time_minutes is not null
       and new.scheduled_at is not null
       and (tg_op = 'INSERT' or (tg_op = 'UPDATE' and new.scheduled_at is distinct from old.scheduled_at))
       and new.scheduled_at < now() + make_interval(mins => policy_row.booking_lead_time_minutes) then
      perform public.corporate_raise_policy_blocked('booking_lead_time', 'The booking is inside the configured lead-time window.');
    end if;

    if tg_op = 'UPDATE' and new.status = 'cancelled'
       and old.status is distinct from new.status
       and policy_row.cancellation_cutoff_minutes is not null
       and old.scheduled_at is not null
       and old.scheduled_at <= now() + make_interval(mins => policy_row.cancellation_cutoff_minutes) then
      perform public.corporate_raise_policy_blocked('cancellation_cutoff', 'The cancellation is inside the configured cancellation cutoff.');
    end if;

    if tg_op = 'INSERT'
       and policy_row.approval_required
       and not public.corporate_current_user_allows(account_row.id, 'booking.approve') then
      new.status := 'pending_approval';
    end if;
  end if;

  -- Create the pending approval row in the same transaction as the booking.
  -- The browser adapter only reads this row and therefore cannot create a
  -- second pending record or bypass the server-side state transition.
  if new.status = 'pending_approval'
     and (tg_op = 'INSERT' or (tg_op = 'UPDATE' and old.status is distinct from new.status))
     and not exists (
       select 1 from public.booking_approvals
        where organization_id = new.organization_id
          and booking_id = new.id
          and approver_id is null
          and status = 'pending'
     ) then
    insert into public.booking_approvals(
      organization_id, booking_id, approver_id, status, comment
    ) values (
      new.organization_id, new.id, null, 'pending',
      jsonb_build_object(
        'source', 'corporate_policy',
        'policy_id', policy_row.id,
        'policy_version', policy_row.version,
        'approval_route', coalesce(policy_row.approval_route, '[]'::jsonb)
      )::text
    );
  end if;

  return new;
end;
$$;

create or replace function public.corporate_booking_delete_guard()
returns trigger
language plpgsql
volatile
security definer
set search_path = public
as $$
begin
  if auth.role() <> 'service_role' and not public.is_platform_user()
     and exists (
       select 1 from public.corporate_accounts
        where organization_id = old.organization_id
          and status = 'active'
     ) then
    perform public.corporate_raise_policy_blocked('booking_delete_blocked', 'Active corporate bookings cannot be deleted; cancel or retain the audited record.');
  end if;
  return old;
end;
$$;

create or replace function public.corporate_booking_approval_delete_guard()
returns trigger
language plpgsql
volatile
security definer
set search_path = public
as $$
begin
  if auth.role() <> 'service_role' and not public.is_platform_user()
     and exists (
       select 1 from public.corporate_accounts
        where organization_id = old.organization_id
          and status = 'active'
     ) then
    perform public.corporate_raise_policy_blocked('approval_delete_blocked', 'Corporate approval records cannot be deleted; decide or retain the audited record.');
  end if;
  return old;
end;
$$;

create or replace function public.corporate_booking_approval_write_guard()
returns trigger
language plpgsql
volatile
security definer
set search_path = public
as $$
declare
  account_id uuid;
  account_status text;
begin
  select ca.id, ca.status into account_id, account_status
    from public.corporate_accounts ca
   where ca.organization_id = new.organization_id
   limit 1;
  if account_id is null or account_status <> 'active' then
    return new;
  end if;
  if new.status in ('approved', 'rejected') then
    if auth.role() <> 'service_role' and not public.is_platform_user()
       and not public.has_permission(new.organization_id, 'bookings.approve') then
      perform public.corporate_raise_policy_blocked('booking_approval_permission_denied', 'Booking approval permission is required for this approval record.');
    end if;
    if not public.corporate_current_user_allows(account_id, 'booking.approve') then
      perform public.corporate_raise_policy_blocked('account_entitlement_denied', 'The corporate account user cannot decide booking approvals.');
    end if;
  end if;
  return new;
end;
$$;

create or replace function public.corporate_duty_write_guard()
returns trigger
language plpgsql
volatile
security definer
set search_path = public
as $$
declare
  booking_state public.booking_status;
  booking_org uuid;
begin
  select b.status, b.organization_id into booking_state, booking_org
    from public.bookings b
   where b.id = new.booking_id;
  if booking_state = 'pending_approval' then
    perform public.corporate_raise_policy_blocked('approval_required', 'A pending corporate booking cannot create or update a duty.');
  end if;
  return new;
end;
$$;

revoke all on function public.corporate_scope_value_allowed(jsonb, text, text) from public;
revoke all on function public.corporate_current_user_allows(uuid, text) from public;
revoke all on function public.corporate_raise_policy_blocked(text, text, text) from public;
revoke all on function public.corporate_booking_write_guard() from public;
revoke all on function public.corporate_booking_delete_guard() from public;
revoke all on function public.corporate_booking_approval_write_guard() from public;
revoke all on function public.corporate_booking_approval_delete_guard() from public;
revoke all on function public.corporate_duty_write_guard() from public;

drop trigger if exists trg_corporate_bookings_write_guard on public.bookings;
create trigger trg_corporate_bookings_write_guard
before insert or update on public.bookings
for each row execute function public.corporate_booking_write_guard();

drop trigger if exists trg_corporate_bookings_delete_guard on public.bookings;
create trigger trg_corporate_bookings_delete_guard
before delete on public.bookings
for each row execute function public.corporate_booking_delete_guard();

drop trigger if exists trg_corporate_duties_write_guard on public.duties;
create trigger trg_corporate_duties_write_guard
before insert or update on public.duties
for each row execute function public.corporate_duty_write_guard();

drop trigger if exists trg_corporate_booking_approvals_write_guard on public.booking_approvals;
create trigger trg_corporate_booking_approvals_write_guard
before insert or update on public.booking_approvals
for each row execute function public.corporate_booking_approval_write_guard();

drop trigger if exists trg_corporate_booking_approvals_delete_guard on public.booking_approvals;
create trigger trg_corporate_booking_approvals_delete_guard
before delete on public.booking_approvals
for each row execute function public.corporate_booking_approval_delete_guard();

-- Security: no table is readable or writable through PostgREST without an
-- authenticated organization membership and the appropriate permission.
alter table public.corporate_accounts enable row level security;
alter table public.corporate_account_snapshots enable row level security;
alter table public.corporate_snapshot_price_books enable row level security;
alter table public.corporate_snapshot_price_book_items enable row level security;
alter table public.corporate_account_users enable row level security;
alter table public.corporate_allotment_rules enable row level security;
alter table public.corporate_policies enable row level security;
alter table public.corporate_masters enable row level security;
alter table public.corporate_duty_slip_approvals enable row level security;
alter table public.corporate_policy_evaluations enable row level security;
alter table public.corporate_idempotency_keys enable row level security;

do $$
begin
  create policy corporate_accounts_read on public.corporate_accounts for select to authenticated
    using (public.has_permission(organization_id, 'corporate.account.read'));
  create policy corporate_accounts_write on public.corporate_accounts for all to authenticated
    using (public.has_permission(organization_id, 'corporate.account.manage'))
    with check (public.has_permission(organization_id, 'corporate.account.manage'));
  create policy corporate_account_snapshots_read on public.corporate_account_snapshots for select to authenticated
    using (public.has_permission(organization_id, 'corporate.account.read'));
  create policy corporate_account_snapshots_write on public.corporate_account_snapshots for insert to authenticated
    with check (public.has_permission(organization_id, 'corporate.account.manage'));
  create policy corporate_snapshot_price_books_read on public.corporate_snapshot_price_books for select to authenticated
    using (public.has_permission(organization_id, 'corporate.account.read'));
  create policy corporate_snapshot_price_books_write on public.corporate_snapshot_price_books for insert to authenticated
    with check (public.has_permission(organization_id, 'corporate.account.manage'));
  create policy corporate_snapshot_price_items_read on public.corporate_snapshot_price_book_items for select to authenticated
    using (public.has_permission(organization_id, 'corporate.account.read'));
  create policy corporate_snapshot_price_items_write on public.corporate_snapshot_price_book_items for insert to authenticated
    with check (public.has_permission(organization_id, 'corporate.account.manage'));
  create policy corporate_account_users_read on public.corporate_account_users for select to authenticated
    using (public.has_permission(organization_id, 'corporate.people.read'));
  create policy corporate_account_users_write on public.corporate_account_users for all to authenticated
    using (public.has_permission(organization_id, 'corporate.people.manage'))
    with check (public.has_permission(organization_id, 'corporate.people.manage'));
  create policy corporate_policies_read on public.corporate_policies for select to authenticated
    using (public.has_permission(organization_id, 'corporate.policy.read'));
  create policy corporate_policies_write on public.corporate_policies for all to authenticated
    using (public.has_permission(organization_id, 'corporate.policy.manage'))
    with check (public.has_permission(organization_id, 'corporate.policy.manage'));
  create policy corporate_allotment_rules_read on public.corporate_allotment_rules for select to authenticated
    using (public.has_permission(organization_id, 'corporate.allotment.evaluate'));
  create policy corporate_allotment_rules_write on public.corporate_allotment_rules for all to authenticated
    using (public.has_permission(organization_id, 'corporate.allotment.manage'))
    with check (public.has_permission(organization_id, 'corporate.allotment.manage'));
  create policy corporate_masters_read on public.corporate_masters for select to authenticated
    using (public.has_permission(organization_id, 'corporate.masters.read'));
  create policy corporate_masters_write on public.corporate_masters for all to authenticated
    using (public.has_permission(organization_id, 'corporate.masters.manage'))
    with check (public.has_permission(organization_id, 'corporate.masters.manage'));
  create policy corporate_duty_slip_read on public.corporate_duty_slip_approvals for select to authenticated
    using (public.has_permission(organization_id, 'corporate.duty_slip.read'));
  create policy corporate_duty_slip_decide on public.corporate_duty_slip_approvals for all to authenticated
    using (public.has_permission(organization_id, 'corporate.duty_slip.decide'))
    with check (public.has_permission(organization_id, 'corporate.duty_slip.decide'));
  create policy corporate_evaluations_read on public.corporate_policy_evaluations for select to authenticated
    using (public.has_permission(organization_id, 'corporate.booking.evaluate'));
  create policy corporate_evaluations_insert on public.corporate_policy_evaluations for insert to authenticated
    with check (public.has_permission(organization_id, 'corporate.booking.evaluate'));
  create policy corporate_idempotency_all on public.corporate_idempotency_keys for all to authenticated
    using (public.is_org_member(organization_id))
    with check (public.is_org_member(organization_id));
exception when duplicate_object then null;
end $$;

-- The worker invokes this function on a schedule.  It only transitions pending
-- rows past their policy-specific 48-hour (or configured) deadline and returns
-- the affected IDs for notification/audit fan-out.
create or replace function public.corporate_auto_approve_duty_slips(target_org uuid)
returns table(approval_id uuid, decision text)
language plpgsql
security invoker
set search_path = public
as $$
begin
  if not public.has_permission(target_org, 'corporate.duty_slip.decide') then
    raise exception 'Corporate duty-slip permission denied';
  end if;
  return query
  update public.corporate_duty_slip_approvals
     set status = 'auto_approved',
         decision_reason = '48_hour_expiry_auto_approval',
         decided_at = now()
   where organization_id = target_org
     and status = 'pending'
     and auto_approve_at <= now()
  returning id, 'auto_approved'::text;
end;
$$;

grant select, insert, update on
  public.corporate_accounts,
  public.corporate_account_snapshots,
  public.corporate_snapshot_price_books,
  public.corporate_snapshot_price_book_items,
  public.corporate_account_users,
  public.corporate_allotment_rules,
  public.corporate_policies,
  public.corporate_masters,
  public.corporate_duty_slip_approvals,
  public.corporate_policy_evaluations,
  public.corporate_idempotency_keys
  to authenticated;
grant execute on function public.corporate_auto_approve_duty_slips(uuid) to authenticated;

comment on table public.corporate_accounts is 'Tenant-scoped corporate account connection and copied setup scope';
comment on table public.corporate_policies is 'Versioned lead-time, cancellation, approval, supplier and passenger-slip policy';
comment on table public.corporate_duty_slip_approvals is 'Passenger approval state machine; action_token_hash is never the signed token';
comment on table public.corporate_masters is 'Effective-dated corporate duty, vehicle, billing, tax, company and pricing masters';

create or replace function public.corporate_append_audit_event(
  target_org uuid,
  event_action text,
  event_entity_type text,
  event_entity_id uuid default null,
  event_metadata jsonb default '{}'::jsonb
)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  new_id uuid;
begin
  if not public.is_org_member(target_org) then
    raise exception 'Corporate audit organization access denied';
  end if;
  insert into public.audit_events(organization_id, actor_id, action, entity_type, entity_id, metadata)
  values (target_org, auth.uid(), event_action, event_entity_type, event_entity_id, coalesce(event_metadata, '{}'::jsonb))
  returning id into new_id;
  return new_id;
end;
$$;
revoke all on function public.corporate_append_audit_event(uuid, text, text, uuid, jsonb) from public;
grant execute on function public.corporate_append_audit_event(uuid, text, text, uuid, jsonb) to authenticated;

-- Public passenger capability link. Possession of the high-entropy token is
-- the authorization boundary; the token itself is never stored or returned
-- from this function. The optional approval ID narrows lookup without making
-- it an authority claim.
create or replace function public.corporate_signed_duty_slip_action(
  raw_token text,
  target_approval uuid default null,
  decision text default null,
  decision_comment text default ''
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  approval_row public.corporate_duty_slip_approvals;
  result jsonb;
  next_status text;
begin
  if coalesce(length(raw_token), 0) < 24 then
    raise exception 'Invalid signed action token';
  end if;
  select * into approval_row
    from public.corporate_duty_slip_approvals
   where action_token_hash = encode(digest(raw_token, 'sha256'), 'hex')
     and (target_approval is null or id = target_approval)
   for update;
  if not found then raise exception 'Invalid signed action token'; end if;
  if approval_row.token_expires_at <= now() then raise exception 'Signed action token expired'; end if;
  if decision is null or btrim(decision) = '' then
    return to_jsonb(approval_row) - 'action_token_hash';
  end if;
  if lower(decision) not in ('approve', 'reject') then raise exception 'Decision must be approve or reject'; end if;
  if approval_row.status <> 'pending' then return to_jsonb(approval_row) - 'action_token_hash'; end if;
  next_status := case when lower(decision) = 'approve' then 'approved' else 'rejected' end;
  update public.corporate_duty_slip_approvals
     set status = next_status,
         decision_comment = left(coalesce(decision_comment, ''), 500),
         decision_reason = 'passenger_signed_link',
         decided_at = now()
   where id = approval_row.id;
  insert into public.audit_events(organization_id, actor_id, action, entity_type, entity_id, metadata)
  values (approval_row.organization_id, null, 'corporate.duty_slip.' || lower(decision), 'corporate', approval_row.id, jsonb_build_object('source', 'signed_link'));
  select to_jsonb(a) - 'action_token_hash' into result from public.corporate_duty_slip_approvals a where a.id = approval_row.id;
  return result;
end;
$$;
revoke all on function public.corporate_signed_duty_slip_action(text, uuid, text, text) from public;
grant execute on function public.corporate_signed_duty_slip_action(text, uuid, text, text) to anon, authenticated;
