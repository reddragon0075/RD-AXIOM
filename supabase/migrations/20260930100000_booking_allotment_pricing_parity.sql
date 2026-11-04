-- Axiom Fleet booking and allotment parity slice.
-- Additive only: existing booking batches, enterprise controls, duties and
-- billing records remain valid.  Every new record is tenant-scoped and every
-- lifecycle mutation is recorded in an append-only action table.

insert into public.permissions(key, description) values
  ('bookings.lifecycle', 'Manage booking relationships, actions, imports and exports'),
  ('allotment.manage', 'Allot, re-allot and dispatch bookings to fleet or suppliers'),
  ('pricing.manage', 'Manage versioned customer and supplier pricing contracts'),
  ('fuel.manage', 'Manage fuel rates and customer fuel surcharge rules')
on conflict (key) do nothing;

insert into public.role_permissions(role, permission_key)
select r.role, p.key
from (values ('vendor_owner'::public.membership_role), ('vendor_ops'::public.membership_role), ('vendor_finance'::public.membership_role), ('vendor_dispatch'::public.membership_role), ('corporate_admin'::public.membership_role), ('corporate_travel'::public.membership_role)) as r(role)
cross join (values ('bookings.lifecycle'), ('allotment.manage'), ('pricing.manage'), ('fuel.manage')) as p(key)
on conflict do nothing;

alter table public.bookings add column if not exists booking_type text not null default 'single';
alter table public.bookings add column if not exists parent_booking_id uuid references public.bookings(id) on delete set null;
alter table public.bookings add column if not exists booking_group_id uuid;
alter table public.bookings add column if not exists child_sequence integer not null default 0;
alter table public.bookings add column if not exists flat_rate_paise bigint not null default 0;
alter table public.bookings add column if not exists currency text not null default 'INR';
alter table public.bookings add column if not exists start_at timestamptz;
alter table public.bookings add column if not exists end_at timestamptz;
alter table public.bookings add column if not exists recurrence_rule text not null default '';
alter table public.bookings add column if not exists passenger_email citext;
alter table public.bookings add column if not exists passenger_json jsonb not null default '{}';
alter table public.bookings add column if not exists temporary_passenger_id uuid;
alter table public.bookings add column if not exists pricing_contract_id uuid;
alter table public.bookings add column if not exists pricing_snapshot jsonb not null default '{}';
alter table public.bookings add column if not exists confirmation_status text not null default 'pending';
alter table public.bookings add column if not exists confirmed_at timestamptz;
alter table public.bookings add column if not exists advance_paise bigint not null default 0;
alter table public.bookings add column if not exists lifecycle_status text not null default 'active';
alter table public.bookings add column if not exists deleted_at timestamptz;
alter table public.bookings add column if not exists allotment_mode text not null default 'owned';
alter table public.bookings add column if not exists vehicle_group_code text not null default '';
alter table public.bookings add column if not exists source_import_id uuid;

alter table public.duties add column if not exists arrival_at timestamptz;
alter table public.duties add column if not exists arrival_status text not null default 'pending';
alter table public.duties add column if not exists supplier_id uuid references public.suppliers(id) on delete set null;
alter table public.duties add column if not exists allotment_mode text not null default 'owned';
alter table public.duties add column if not exists dispatch_id uuid;
alter table public.invoices add column if not exists fuel_surcharge_paise bigint not null default 0;
alter table public.invoices add column if not exists pricing_snapshot jsonb not null default '{}';

create table if not exists public.booking_request_keys (
  organization_id uuid not null references public.organizations(id) on delete cascade,
  idempotency_key text not null,
  booking_id uuid not null references public.bookings(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (organization_id, idempotency_key)
);
create table if not exists public.booking_action_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  booking_id uuid not null references public.bookings(id) on delete cascade,
  action_type text not null,
  status text not null default 'completed',
  payload jsonb not null default '{}',
  idempotency_key text,
  actor_id uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, booking_id, action_type, idempotency_key)
);
create table if not exists public.booking_attachments (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  booking_id uuid not null references public.bookings(id) on delete cascade,
  filename text not null,
  content_type text not null default 'application/octet-stream',
  storage_path text not null default '',
  sha256 text not null default '',
  size_bytes bigint not null default 0,
  status text not null default 'active',
  metadata jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);
create table if not exists public.booking_briefings (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  booking_id uuid not null references public.bookings(id) on delete cascade,
  version integer not null default 1,
  status text not null default 'published',
  briefing jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, booking_id, version)
);
create table if not exists public.booking_advances (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  booking_id uuid not null references public.bookings(id) on delete cascade,
  amount_paise bigint not null check (amount_paise >= 0),
  currency text not null default 'INR',
  status text not null default 'requested',
  mode text not null default 'manual',
  reference text not null default '',
  payload jsonb not null default '{}',
  idempotency_key text,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);
create table if not exists public.booking_imports (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  status text not null default 'processing',
  source_format text not null default 'json',
  requested_count integer not null default 0,
  imported_count integer not null default 0,
  failed_count integer not null default 0,
  rows jsonb not null default '[]',
  result jsonb not null default '{}',
  idempotency_key text,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);
create table if not exists public.booking_dispatches (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  booking_id uuid not null references public.bookings(id) on delete cascade,
  allotment_mode text not null check (allotment_mode in ('owned','company_supplier','dco','network')),
  supplier_id uuid references public.suppliers(id) on delete set null,
  driver_id uuid references public.drivers(id) on delete set null,
  vehicle_id uuid references public.vehicles(id) on delete set null,
  network_vendor_profile_id uuid references public.network_vendor_profiles(id) on delete set null,
  status text not null default 'requested',
  response_status text not null default 'pending',
  dispatch_details jsonb not null default '{}',
  expires_at timestamptz,
  idempotency_key text,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);
create table if not exists public.temporary_passengers (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  customer_id uuid references public.customers(id) on delete set null,
  name text not null,
  phone text not null default '',
  email citext not null default '',
  metadata jsonb not null default '{}',
  status text not null default 'active',
  expires_at timestamptz not null,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.temporary_allotments (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  booking_id uuid not null references public.bookings(id) on delete cascade,
  allotment_mode text not null check (allotment_mode in ('owned','company_supplier','dco','network')),
  supplier_id uuid references public.suppliers(id) on delete set null,
  driver_id uuid references public.drivers(id) on delete set null,
  vehicle_id uuid references public.vehicles(id) on delete set null,
  status text not null default 'active',
  details jsonb not null default '{}',
  expires_at timestamptz not null,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.booking_pricing_contracts (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  contract_type text not null default 'customer',
  customer_id uuid references public.customers(id) on delete set null,
  supplier_id uuid references public.suppliers(id) on delete set null,
  name text not null,
  version integer not null default 1,
  status text not null default 'draft',
  effective_from timestamptz not null default now(),
  effective_to timestamptz,
  currency text not null default 'INR',
  terms jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, contract_type, name, version)
);
create table if not exists public.booking_pricing_rules (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  contract_id uuid not null references public.booking_pricing_contracts(id) on delete cascade,
  city text not null default '',
  vehicle_group text not null default '',
  duty_type text not null default '',
  package_minutes integer not null default 0,
  included_km numeric(12,3) not null default 0,
  base_paise bigint not null default 0,
  extra_km_paise bigint not null default 0,
  extra_hour_paise bigint not null default 0,
  extra_half_hour_paise bigint not null default 0,
  waiting_paise bigint not null default 0,
  allowance_paise bigint not null default 0,
  auto_switch jsonb not null default '{}',
  extras jsonb not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.customer_fuel_surcharge_rules (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  customer_id uuid references public.customers(id) on delete set null,
  contract_id uuid references public.booking_pricing_contracts(id) on delete set null,
  vehicle_group text not null default '',
  fuel_type text not null default 'petrol',
  included_fuel_price_paise bigint not null default 0,
  average_km_per_litre numeric(10,3) not null default 10,
  surcharge_mode text not null default 'difference',
  rate_percent_bps integer not null default 0,
  status text not null default 'active',
  effective_from timestamptz not null default now(),
  effective_to timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.fuel_rate_history (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  city text not null default '',
  fuel_type text not null default 'petrol',
  price_paise bigint not null check (price_paise >= 0),
  effective_at timestamptz not null default now(),
  source text not null default 'manual',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);
create table if not exists public.booking_pricing_quotes (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  booking_id uuid references public.bookings(id) on delete set null,
  contract_id uuid references public.booking_pricing_contracts(id) on delete set null,
  duty_type text not null default '',
  total_paise bigint not null default 0,
  breakdown jsonb not null default '{}',
  idempotency_key text,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);

create index if not exists idx_booking_lifecycle_parent on public.bookings(organization_id, parent_booking_id, child_sequence);
create index if not exists idx_booking_lifecycle_group on public.bookings(organization_id, booking_group_id, scheduled_at);
create index if not exists idx_booking_actions_booking on public.booking_action_events(organization_id, booking_id, created_at desc);
create index if not exists idx_booking_dispatches_booking on public.booking_dispatches(organization_id, booking_id, updated_at desc);
create index if not exists idx_temporary_passengers_expiry on public.temporary_passengers(organization_id, expires_at, status);
create index if not exists idx_temporary_allotments_expiry on public.temporary_allotments(organization_id, expires_at, status);
create index if not exists idx_pricing_rules_contract on public.booking_pricing_rules(organization_id, contract_id);
create index if not exists idx_fuel_rate_lookup on public.fuel_rate_history(organization_id, fuel_type, city, effective_at desc);

-- Tenant RLS for every new table.  The Edge boundary still performs the
-- membership/role checks before writes; RLS is the second independent guard.
DO $$
DECLARE
  table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'booking_request_keys','booking_action_events','booking_attachments','booking_briefings','booking_advances','booking_imports',
    'booking_dispatches','temporary_passengers','temporary_allotments','booking_pricing_contracts',
    'booking_pricing_rules','customer_fuel_surcharge_rules','fuel_rate_history','booking_pricing_quotes'
  ] LOOP
    EXECUTE format('alter table public.%I enable row level security', table_name);
    BEGIN
      EXECUTE format('create policy %I_member_read on public.%I for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user())', table_name, table_name);
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
      EXECUTE format('create policy %I_operator_write on public.%I for all to authenticated using (public.has_permission(organization_id, ''bookings.write'') or public.has_permission(organization_id, ''bookings.lifecycle'') or public.has_permission(organization_id, ''allotment.manage'') or public.has_permission(organization_id, ''pricing.manage'') or public.has_permission(organization_id, ''fuel.manage'') or public.is_platform_user()) with check (public.is_org_member(organization_id) and (public.has_permission(organization_id, ''bookings.write'') or public.has_permission(organization_id, ''bookings.lifecycle'') or public.has_permission(organization_id, ''allotment.manage'') or public.has_permission(organization_id, ''pricing.manage'') or public.has_permission(organization_id, ''fuel.manage'') or public.is_platform_user()))', table_name, table_name);
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
  END LOOP;
END $$;

-- Keep child/group relationships and expiry state consistent without making
-- the older booking enum carry new lifecycle labels.
create or replace function public.expire_booking_temporary_state()
returns trigger
language plpgsql
security invoker
set search_path = public
as $$
begin
  update public.temporary_passengers set status = 'expired', updated_at = now()
   where status = 'active' and expires_at <= now() and organization_id = new.organization_id;
  update public.temporary_allotments set status = 'expired', updated_at = now()
   where status = 'active' and expires_at <= now() and organization_id = new.organization_id;
  return new;
end;
$$;

-- Tally/Tally Prime export is intentionally not part of this contract.
