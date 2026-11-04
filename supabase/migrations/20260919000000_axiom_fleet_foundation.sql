-- Axiom Fleet / Supabase foundation
-- Supabase Auth owns passwords, sessions and refresh tokens.
-- This migration owns tenant data, memberships, permissions and core operational records.
-- Apply with: supabase db push

create extension if not exists pgcrypto;
create extension if not exists citext;

do $$ begin
  create type public.account_type as enum ('vendor', 'driver', 'corporate', 'platform');
exception when duplicate_object then null; end $$;
do $$ begin
  create type public.organization_kind as enum ('vendor', 'corporate');
exception when duplicate_object then null; end $$;
do $$ begin
  create type public.membership_role as enum (
    'vendor_owner', 'vendor_ops', 'vendor_finance', 'vendor_dispatch',
    'driver', 'corporate_admin', 'corporate_travel', 'corporate_finance',
    'platform_admin', 'platform_support'
  );
exception when duplicate_object then null; end $$;
do $$ begin
  create type public.membership_status as enum ('invited', 'active', 'suspended', 'removed');
exception when duplicate_object then null; end $$;
do $$ begin
  create type public.booking_status as enum ('requested', 'approved', 'confirmed', 'assigned', 'in_progress', 'completed', 'cancelled', 'no_show', 'disputed');
exception when duplicate_object then null; end $$;
do $$ begin
  create type public.duty_status as enum ('draft', 'assigned', 'accepted', 'en_route', 'started', 'paused', 'completed', 'cancelled', 'disputed');
exception when duplicate_object then null; end $$;
do $$ begin
  create type public.invoice_status as enum ('draft', 'issued', 'sent', 'partially_paid', 'paid', 'void', 'disputed');
exception when duplicate_object then null; end $$;
do $$ begin
  create type public.payment_status as enum ('pending', 'succeeded', 'failed', 'refunded');
exception when duplicate_object then null; end $$;
do $$ begin
  create type public.sync_status as enum ('queued', 'processing', 'synced', 'conflicted', 'failed');
exception when duplicate_object then null; end $$;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
security invoker
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email citext unique,
  full_name text not null default '',
  phone text not null default '',
  account_type public.account_type,
  preferred_language text not null default 'en',
  avatar_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.organizations (
  id uuid primary key default gen_random_uuid(),
  kind public.organization_kind not null,
  name text not null check (length(trim(name)) between 2 and 180),
  legal_name text,
  gstin text,
  phone text not null default '',
  city text not null default '',
  fleet_size integer check (fleet_size is null or fleet_size >= 0),
  employee_count integer check (employee_count is null or employee_count >= 0),
  owner_user_id uuid references auth.users(id) on delete set null,
  onboarding_state jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.branches (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  name text not null,
  city text not null default '',
  timezone text not null default 'Asia/Kolkata',
  numbering_series jsonb not null default '{}'::jsonb,
  tax_registration jsonb not null default '{}'::jsonb,
  is_default boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, name)
);

create table if not exists public.organization_memberships (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  branch_id uuid references public.branches(id) on delete set null,
  role public.membership_role not null,
  status public.membership_status not null default 'active',
  invited_by uuid references auth.users(id) on delete set null,
  joined_at timestamptz,
  created_at timestamptz not null default now(),
  unique (organization_id, user_id)
);

create table if not exists public.invitations (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  email citext not null,
  role public.membership_role not null,
  branch_id uuid references public.branches(id) on delete set null,
  token_hash text not null unique,
  invited_by uuid not null references auth.users(id) on delete restrict,
  expires_at timestamptz not null,
  accepted_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.permissions (
  key text primary key,
  description text not null default ''
);

create table if not exists public.role_permissions (
  role public.membership_role not null,
  permission_key text not null references public.permissions(key) on delete cascade,
  primary key (role, permission_key)
);

create table if not exists public.tenant_edges (
  id uuid primary key default gen_random_uuid(),
  from_organization_id uuid not null references public.organizations(id) on delete cascade,
  to_organization_id uuid not null references public.organizations(id) on delete cascade,
  status text not null default 'invited' check (status in ('invited', 'active', 'paused', 'removed')),
  trust_level text not null default 'new',
  cities text[] not null default '{}',
  invited_by uuid references auth.users(id) on delete set null,
  accepted_at timestamptz,
  created_at timestamptz not null default now(),
  unique (from_organization_id, to_organization_id),
  check (from_organization_id <> to_organization_id)
);

create table if not exists public.audit_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid references public.organizations(id) on delete set null,
  actor_id uuid references auth.users(id) on delete set null,
  action text not null,
  entity_type text not null,
  entity_id uuid,
  before_data jsonb,
  after_data jsonb,
  metadata jsonb not null default '{}'::jsonb,
  ip_address inet,
  device_fingerprint text,
  prev_hash text,
  row_hash text,
  retention_class text not null default 'standard' check (retention_class in ('standard', 'financial')),
  created_at timestamptz not null default now()
);

create table if not exists public.customers (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  branch_id uuid references public.branches(id) on delete set null,
  name text not null,
  customer_type text not null default 'company',
  email citext,
  phone text,
  gstin text,
  billing_address jsonb not null default '{}'::jsonb,
  status text not null default 'active',
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.suppliers (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  name text not null,
  supplier_type text not null default 'company',
  email citext,
  phone text,
  gstin text,
  cities text[] not null default '{}',
  status text not null default 'active',
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.drivers (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid references public.organizations(id) on delete set null,
  user_id uuid unique references auth.users(id) on delete set null,
  full_name text not null,
  phone text not null default '',
  license_number text,
  license_expires_at date,
  city text not null default '',
  status text not null default 'active',
  compliance jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.vehicles (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  registration_number text not null,
  vehicle_type text not null default 'sedan',
  vehicle_group text,
  make_model text,
  year integer,
  city text not null default '',
  status text not null default 'active',
  compliance jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, registration_number)
);

create table if not exists public.price_books (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  name text not null,
  effective_from date not null,
  effective_to date,
  status text not null default 'draft',
  version integer not null default 1,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (effective_to is null or effective_to >= effective_from)
);

create table if not exists public.price_book_items (
  id uuid primary key default gen_random_uuid(),
  price_book_id uuid not null references public.price_books(id) on delete cascade,
  duty_type text not null,
  vehicle_group text,
  base_paise bigint not null default 0 check (base_paise >= 0),
  per_km_paise bigint not null default 0 check (per_km_paise >= 0),
  per_hour_paise bigint not null default 0 check (per_hour_paise >= 0),
  waiting_paise bigint not null default 0 check (waiting_paise >= 0),
  tax_rate numeric(6,3) not null default 0 check (tax_rate >= 0),
  rules jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.bookings (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  branch_id uuid references public.branches(id) on delete set null,
  customer_id uuid references public.customers(id) on delete set null,
  requesting_organization_id uuid references public.organizations(id) on delete set null,
  vendor_organization_id uuid references public.organizations(id) on delete set null,
  status public.booking_status not null default 'requested',
  booking_reference text not null,
  passenger_name text,
  passenger_phone text,
  pickup jsonb not null default '{}'::jsonb,
  dropoff jsonb not null default '{}'::jsonb,
  stops jsonb not null default '[]'::jsonb,
  scheduled_at timestamptz,
  duty_type text,
  policy_context jsonb not null default '{}'::jsonb,
  source text not null default 'web',
  notes text,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, booking_reference)
);

create table if not exists public.duties (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  booking_id uuid not null references public.bookings(id) on delete restrict,
  driver_id uuid references public.drivers(id) on delete set null,
  vehicle_id uuid references public.vehicles(id) on delete set null,
  status public.duty_status not null default 'draft',
  reporting_at timestamptz,
  started_at timestamptz,
  completed_at timestamptz,
  start_odometer integer,
  end_odometer integer,
  start_location jsonb,
  end_location jsonb,
  calculation_snapshot jsonb not null default '{}'::jsonb,
  sync_version integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.duty_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  duty_id uuid not null references public.duties(id) on delete cascade,
  event_type text not null,
  event_at timestamptz not null default now(),
  source text not null default 'web',
  idempotency_key text,
  payload jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  unique (organization_id, idempotency_key)
);

create table if not exists public.duty_proofs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  duty_id uuid not null references public.duties(id) on delete cascade,
  proof_type text not null,
  storage_path text,
  proof_data jsonb not null default '{}'::jsonb,
  idempotency_key text,
  captured_at timestamptz not null default now(),
  captured_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);

create table if not exists public.track_points (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  duty_id uuid not null references public.duties(id) on delete cascade,
  recorded_at timestamptz not null,
  latitude numeric(10,7) not null,
  longitude numeric(10,7) not null,
  accuracy_m numeric(8,2),
  battery_pct numeric(5,2),
  source text not null default 'app',
  is_gap_boundary boolean not null default false,
  idempotency_key text,
  created_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);

create table if not exists public.sync_operations (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  user_id uuid not null references auth.users(id) on delete cascade,
  device_id text not null,
  idempotency_key text not null,
  entity_type text not null,
  entity_id uuid,
  operation text not null,
  status public.sync_status not null default 'queued',
  client_created_at timestamptz,
  server_processed_at timestamptz,
  payload jsonb not null default '{}'::jsonb,
  conflict_data jsonb,
  error_message text,
  unique (user_id, idempotency_key)
);

create table if not exists public.expenses (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  duty_id uuid not null references public.duties(id) on delete cascade,
  category text not null,
  amount_paise bigint not null check (amount_paise >= 0),
  note text not null default '',
  attachment jsonb not null default '{}'::jsonb,
  status text not null default 'submitted',
  idempotency_key text,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);

create table if not exists public.invoices (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  customer_id uuid references public.customers(id) on delete set null,
  booking_id uuid references public.bookings(id) on delete set null,
  invoice_number text not null,
  status public.invoice_status not null default 'draft',
  currency text not null default 'INR',
  subtotal_paise bigint not null default 0,
  tax_paise bigint not null default 0,
  total_paise bigint not null default 0,
  irn text,
  issued_at timestamptz,
  due_at timestamptz,
  immutable_snapshot jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, invoice_number)
);

create table if not exists public.invoice_lines (
  id uuid primary key default gen_random_uuid(),
  invoice_id uuid not null references public.invoices(id) on delete cascade,
  description text not null,
  quantity numeric(12,3) not null default 1,
  unit_paise bigint not null default 0,
  tax_rate numeric(6,3) not null default 0,
  amount_paise bigint not null default 0,
  source_entity_type text,
  source_entity_id uuid,
  created_at timestamptz not null default now()
);

create table if not exists public.payments (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  invoice_id uuid references public.invoices(id) on delete set null,
  amount_paise bigint not null check (amount_paise >= 0),
  mode text not null,
  status public.payment_status not null default 'pending',
  gateway_reference text,
  idempotency_key text,
  received_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);

create table if not exists public.notifications (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid references public.organizations(id) on delete cascade,
  recipient_id uuid references auth.users(id) on delete cascade,
  channel text not null,
  template_key text not null,
  status text not null default 'queued',
  provider_reference text,
  payload jsonb not null default '{}'::jsonb,
  sent_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.integration_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid references public.organizations(id) on delete set null,
  provider text not null,
  event_type text not null,
  external_id text,
  signature_valid boolean not null default false,
  idempotency_key text,
  status text not null default 'received',
  payload jsonb not null default '{}'::jsonb,
  processed_at timestamptz,
  created_at timestamptz not null default now(),
  unique (provider, idempotency_key)
);

create table if not exists public.employees (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  employee_code text not null,
  full_name text not null,
  email citext,
  phone text,
  department text not null default '',
  cost_center text not null default '',
  status text not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, employee_code)
);

create table if not exists public.travel_policies (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  name text not null,
  status text not null default 'draft',
  rules jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.booking_approvals (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  booking_id uuid not null references public.bookings(id) on delete cascade,
  approver_id uuid references auth.users(id) on delete set null,
  status text not null default 'pending',
  comment text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, booking_id, approver_id)
);

create table if not exists public.documents (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  entity_type text not null,
  entity_id uuid not null,
  document_type text not null,
  file_name text not null,
  storage_path text,
  status text not null default 'pending_review',
  expires_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  uploaded_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.support_tickets (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  opened_by uuid references auth.users(id) on delete set null,
  subject text not null,
  description text not null default '',
  priority text not null default 'normal',
  status text not null default 'open',
  assignee_id uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.privacy_requests (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  requester_id uuid references auth.users(id) on delete set null,
  request_type text not null,
  status text not null default 'open',
  notes text not null default '',
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

create table if not exists public.organization_settings (
  organization_id uuid primary key references public.organizations(id) on delete cascade,
  settings jsonb not null default '{}'::jsonb,
  updated_by uuid references auth.users(id) on delete set null,
  updated_at timestamptz not null default now()
);

create table if not exists public.einvoice_records (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  invoice_id uuid not null references public.invoices(id) on delete cascade,
  provider text not null default 'mock_einvoice',
  status text not null default 'issued',
  irn text not null,
  qr_payload text not null default '',
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (organization_id, invoice_id)
);

create table if not exists public.collection_actions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  invoice_id uuid not null references public.invoices(id) on delete cascade,
  action_type text not null,
  channel text not null,
  status text not null default 'queued',
  provider_reference text not null default '',
  scheduled_at timestamptz,
  created_at timestamptz not null default now()
);

alter table public.price_books add column if not exists branch_id uuid references public.branches(id) on delete set null;

create index if not exists idx_memberships_user on public.organization_memberships(user_id, status);
create index if not exists idx_memberships_org on public.organization_memberships(organization_id, status);
create index if not exists idx_bookings_org_status on public.bookings(organization_id, status, scheduled_at);
create index if not exists idx_duties_org_status on public.duties(organization_id, status, reporting_at);
create index if not exists idx_duty_events_duty on public.duty_events(duty_id, event_at);
create index if not exists idx_track_points_duty_time on public.track_points(duty_id, recorded_at);
create index if not exists idx_invoices_org_status on public.invoices(organization_id, status, due_at);
create index if not exists idx_payments_invoice_status on public.payments(invoice_id, status, received_at);
create index if not exists idx_expenses_duty_time on public.expenses(duty_id, created_at);
create index if not exists idx_audit_org_time on public.audit_events(organization_id, created_at);
create index if not exists idx_einvoice_org_invoice on public.einvoice_records(organization_id, invoice_id);
create index if not exists idx_collection_actions_invoice_time on public.collection_actions(organization_id, invoice_id, created_at);
create index if not exists idx_employees_org_status on public.employees(organization_id, status);
create index if not exists idx_policies_org_status on public.travel_policies(organization_id, status);
create index if not exists idx_approvals_booking_status on public.booking_approvals(booking_id, status);
create index if not exists idx_documents_entity on public.documents(organization_id, entity_type, entity_id);
create index if not exists idx_tickets_org_status on public.support_tickets(organization_id, status, created_at);
create index if not exists idx_privacy_org_status on public.privacy_requests(organization_id, status, created_at);

create or replace function public.is_org_member(target_org uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.organization_memberships m
    where m.organization_id = target_org
      and m.user_id = auth.uid()
      and m.status = 'active'::public.membership_status
  );
$$;

create or replace function public.has_org_role(target_org uuid, allowed_roles public.membership_role[])
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.organization_memberships m
    where m.organization_id = target_org
      and m.user_id = auth.uid()
      and m.status = 'active'::public.membership_status
      and m.role = any(allowed_roles)
  );
$$;

create or replace function public.has_permission(target_org uuid, permission_key text)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.organization_memberships m
    join public.role_permissions rp on rp.role = m.role
    where m.organization_id = target_org
      and m.user_id = auth.uid()
      and m.status = 'active'::public.membership_status
      and rp.permission_key = permission_key
  );
$$;

create or replace function public.is_platform_user()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.profiles p
    where p.id = auth.uid() and p.account_type = 'platform'::public.account_type
  );
$$;

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles(id, email, full_name, phone, account_type)
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data ->> 'full_name', ''),
    coalesce(new.raw_user_meta_data ->> 'phone', ''),
    nullif(new.raw_user_meta_data ->> 'account_type', '')::public.account_type
  )
  on conflict (id) do update set
    email = excluded.email,
    full_name = case when excluded.full_name <> '' then excluded.full_name else public.profiles.full_name end,
    phone = case when excluded.phone <> '' then excluded.phone else public.profiles.phone end,
    account_type = coalesce(excluded.account_type, public.profiles.account_type),
    updated_at = now();
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute procedure public.handle_new_user();

create or replace function public.create_organization(
  p_kind public.organization_kind,
  p_name text,
  p_city text default '',
  p_phone text default '',
  p_gstin text default '',
  p_fleet_size integer default null,
  p_employee_count integer default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  new_org public.organizations;
  new_branch public.branches;
  owner_role public.membership_role;
begin
  if auth.uid() is null then
    raise exception using errcode = '42501', message = 'Authentication required';
  end if;
  if p_kind not in ('vendor'::public.organization_kind, 'corporate'::public.organization_kind) then
    raise exception using errcode = '22023', message = 'Only vendor and corporate organizations can be created here';
  end if;
  owner_role := case when p_kind = 'vendor' then 'vendor_owner'::public.membership_role else 'corporate_admin'::public.membership_role end;

  insert into public.organizations(kind, name, phone, city, gstin, fleet_size, employee_count, owner_user_id)
  values (p_kind, trim(p_name), coalesce(p_phone, ''), coalesce(p_city, ''), upper(coalesce(p_gstin, '')), p_fleet_size, p_employee_count, auth.uid())
  returning * into new_org;

  insert into public.branches(organization_id, name, city, is_default)
  values (new_org.id, 'Main branch', coalesce(p_city, ''), true)
  returning * into new_branch;

  insert into public.organization_memberships(organization_id, user_id, branch_id, role, status, joined_at)
  values (new_org.id, auth.uid(), new_branch.id, owner_role, 'active', now());

  update public.profiles
  set account_type = case when p_kind = 'vendor' then 'vendor'::public.account_type else 'corporate'::public.account_type end,
      updated_at = now()
  where id = auth.uid();

  insert into public.audit_events(organization_id, actor_id, action, entity_type, entity_id, after_data)
  values (new_org.id, auth.uid(), 'organization.created', 'organization', new_org.id,
          jsonb_build_object('kind', p_kind, 'name', new_org.name));

  return jsonb_build_object(
    'organization_id', new_org.id,
    'branch_id', new_branch.id,
    'role', owner_role
  );
end;
$$;

create or replace function public.create_driver_profile(
  p_full_name text,
  p_phone text default '',
  p_city text default '',
  p_license_number text default ''
)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  driver_id uuid;
begin
  if auth.uid() is null then
    raise exception using errcode = '42501', message = 'Authentication required';
  end if;
  insert into public.profiles(id, email, full_name, phone, account_type)
  select auth.uid(), u.email, coalesce(p_full_name, ''), coalesce(p_phone, ''), 'driver'::public.account_type
  from auth.users u where u.id = auth.uid()
  on conflict (id) do update set
    full_name = excluded.full_name,
    phone = excluded.phone,
    account_type = 'driver'::public.account_type,
    updated_at = now();

  insert into public.drivers(user_id, full_name, phone, city, license_number)
  values (auth.uid(), coalesce(p_full_name, ''), coalesce(p_phone, ''), coalesce(p_city, ''), upper(coalesce(p_license_number, '')))
  on conflict (user_id) do update set
    full_name = excluded.full_name,
    phone = excluded.phone,
    city = excluded.city,
    license_number = excluded.license_number,
    updated_at = now()
  returning id into driver_id;
  return driver_id;
end;
$$;

create or replace function public.create_invitation(
  p_email citext,
  p_role public.membership_role,
  p_branch_id uuid default null,
  p_expires_days integer default 7
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  target_org uuid;
  raw_token text;
  invitation_row public.invitations;
begin
  select organization_id into target_org
  from public.organization_memberships
  where user_id = auth.uid() and status = 'active' and public.has_permission(organization_id, 'members.manage')
  order by joined_at limit 1;
  if target_org is null then raise exception using errcode = '42501', message = 'Invitation permission required'; end if;
  if p_role not in ('driver'::public.membership_role, 'vendor_ops'::public.membership_role, 'vendor_finance'::public.membership_role, 'vendor_dispatch'::public.membership_role, 'corporate_travel'::public.membership_role, 'corporate_finance'::public.membership_role) then
    raise exception using errcode = '22023', message = 'This membership role cannot be invited';
  end if;
  if p_branch_id is not null and not exists (select 1 from public.branches where id = p_branch_id and organization_id = target_org) then
    raise exception using errcode = '22023', message = 'Invitation branch does not belong to the organization';
  end if;
  if p_expires_days < 1 or p_expires_days > 30 then raise exception using errcode = '22023', message = 'Invitation expiry must be between 1 and 30 days'; end if;
  raw_token := encode(gen_random_bytes(24), 'hex');
  insert into public.invitations(organization_id, email, role, branch_id, token_hash, invited_by, expires_at)
  values (target_org, lower(p_email), p_role, p_branch_id, encode(digest(raw_token, 'sha256'), 'hex'), auth.uid(), now() + make_interval(days => p_expires_days))
  returning * into invitation_row;
  return jsonb_build_object('invitation', to_jsonb(invitation_row), 'invite_token', raw_token);
end;
$$;

create or replace function public.accept_invitation(p_token text)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  invitation_row public.invitations;
begin
  if auth.uid() is null then raise exception using errcode = '42501', message = 'Authentication required'; end if;
  select * into invitation_row from public.invitations where token_hash = encode(digest(p_token, 'sha256'), 'hex') and accepted_at is null and expires_at > now() for update;
  if invitation_row.id is null then raise exception using errcode = '22023', message = 'Invitation is invalid or expired'; end if;
  if lower((select email from auth.users where id = auth.uid())) <> lower(invitation_row.email::text) then raise exception using errcode = '42501', message = 'Invited email does not match'; end if;
  insert into public.organization_memberships as existing (organization_id, user_id, branch_id, role, status, invited_by, joined_at)
  values (invitation_row.organization_id, auth.uid(), invitation_row.branch_id, invitation_row.role, 'active', invitation_row.invited_by, now())
  on conflict (organization_id, user_id) do update set role = excluded.role, branch_id = excluded.branch_id, status = 'active', joined_at = coalesce(existing.joined_at, excluded.joined_at), invited_by = excluded.invited_by;
  update public.invitations set accepted_at = now() where id = invitation_row.id;
  return jsonb_build_object('organization_id', invitation_row.organization_id, 'role', invitation_row.role);
end;
$$;

insert into public.permissions(key, description) values
  ('organization.manage', 'Manage organization profile and branches'),
  ('members.manage', 'Invite and manage organization members'),
  ('customers.read', 'View customers'),
  ('customers.write', 'Create and update customers'),
  ('suppliers.read', 'View suppliers'),
  ('suppliers.write', 'Create and update suppliers'),
  ('drivers.read', 'View drivers'),
  ('drivers.write', 'Create and update drivers'),
  ('vehicles.read', 'View vehicles'),
  ('vehicles.write', 'Create and update vehicles'),
  ('pricing.read', 'View price books'),
  ('pricing.write', 'Create and update price books'),
  ('bookings.read', 'View bookings'),
  ('bookings.write', 'Create and update bookings'),
  ('bookings.approve', 'Approve bookings'),
  ('duties.read', 'View duties'),
  ('duties.write', 'Create and assign duties'),
  ('duties.force_close', 'Force-close a duty'),
  ('duties.proof_review', 'Review duty proof'),
  ('billing.read', 'View invoices and receipts'),
  ('billing.write', 'Create invoices and receipts'),
  ('billing.issue', 'Issue invoices'),
  ('billing.refund', 'Approve refunds and credits'),
  ('payments.read', 'View payments'),
  ('payments.write', 'Record payments'),
  ('reports.read', 'View reports'),
  ('reports.export', 'Export reports'),
  ('settings.manage', 'Manage operational settings'),
  ('notifications.send', 'Send operational notifications'),
  ('telephony.use', 'Use masked calling'),
  ('tracking.read', 'View live tracking'),
  ('network.manage', 'Manage associate network'),
  ('settlements.read', 'View settlements'),
  ('settlements.write', 'Manage settlements'),
  ('admin.clients', 'Manage platform clients'),
  ('admin.impersonate', 'Impersonate a client with an approved ticket'),
  ('admin.money_approve', 'Approve platform money actions'),
  ('support.manage', 'Manage support tickets'),
  ('audit.read', 'View audit history'),
  ('data.export', 'Export organization data'),
  ('data.delete', 'Request data deletion')
on conflict (key) do nothing;

insert into public.role_permissions(role, permission_key)
select 'vendor_owner'::public.membership_role, key from public.permissions
on conflict do nothing;
insert into public.role_permissions(role, permission_key)
select 'platform_admin'::public.membership_role, key from public.permissions
on conflict do nothing;
insert into public.role_permissions(role, permission_key)
select 'vendor_ops'::public.membership_role, key from public.permissions
where key in ('customers.read','customers.write','suppliers.read','suppliers.write','drivers.read','drivers.write','vehicles.read','vehicles.write','pricing.read','bookings.read','bookings.write','duties.read','duties.write','duties.proof_review','billing.read','reports.read','reports.export','notifications.send','tracking.read','audit.read')
on conflict do nothing;
insert into public.role_permissions(role, permission_key)
select 'vendor_finance'::public.membership_role, key from public.permissions
where key in ('customers.read','suppliers.read','pricing.read','bookings.read','duties.read','duties.proof_review','billing.read','billing.write','billing.issue','payments.read','payments.write','reports.read','reports.export','audit.read')
on conflict do nothing;
insert into public.role_permissions(role, permission_key)
select 'vendor_dispatch'::public.membership_role, key from public.permissions
where key in ('customers.read','drivers.read','vehicles.read','pricing.read','bookings.read','bookings.write','duties.read','duties.write','duties.proof_review','notifications.send','tracking.read')
on conflict do nothing;
insert into public.role_permissions(role, permission_key)
select 'corporate_admin'::public.membership_role, key from public.permissions
where key in ('organization.manage','members.manage','bookings.read','bookings.write','bookings.approve','duties.read','tracking.read','billing.read','reports.read','reports.export','audit.read','data.export')
on conflict do nothing;
insert into public.role_permissions(role, permission_key)
select 'corporate_travel'::public.membership_role, key from public.permissions
where key in ('bookings.read','bookings.write','bookings.approve','duties.read','tracking.read','reports.read')
on conflict do nothing;
insert into public.role_permissions(role, permission_key)
select 'corporate_finance'::public.membership_role, key from public.permissions
where key in ('bookings.read','duties.read','billing.read','reports.read','reports.export','audit.read')
on conflict do nothing;

-- Updated-at triggers.
do $$
declare t text;
begin
  foreach t in array array['profiles','organizations','branches','customers','suppliers','drivers','vehicles','price_books','bookings','duties','invoices'] loop
    execute format('drop trigger if exists %I_updated_at on public.%I', t, t);
    execute format('create trigger %I_updated_at before update on public.%I for each row execute procedure public.set_updated_at()', t, t);
  end loop;
end $$;

-- RLS helper functions are SECURITY DEFINER; policies remain deny-by-default.
alter table public.profiles enable row level security;
alter table public.organizations enable row level security;
alter table public.branches enable row level security;
alter table public.organization_memberships enable row level security;
alter table public.invitations enable row level security;
alter table public.tenant_edges enable row level security;
alter table public.audit_events enable row level security;
alter table public.customers enable row level security;
alter table public.suppliers enable row level security;
alter table public.drivers enable row level security;
alter table public.vehicles enable row level security;
alter table public.price_books enable row level security;
alter table public.price_book_items enable row level security;
alter table public.bookings enable row level security;
alter table public.duties enable row level security;
alter table public.duty_events enable row level security;
alter table public.duty_proofs enable row level security;
alter table public.track_points enable row level security;
alter table public.sync_operations enable row level security;
alter table public.expenses enable row level security;
alter table public.invoices enable row level security;
alter table public.invoice_lines enable row level security;
alter table public.payments enable row level security;
alter table public.notifications enable row level security;
alter table public.integration_events enable row level security;
alter table public.employees enable row level security;
alter table public.travel_policies enable row level security;
alter table public.booking_approvals enable row level security;
alter table public.documents enable row level security;
alter table public.support_tickets enable row level security;
alter table public.privacy_requests enable row level security;
alter table public.organization_settings enable row level security;
alter table public.einvoice_records enable row level security;
alter table public.collection_actions enable row level security;
alter table public.permissions enable row level security;
alter table public.role_permissions enable row level security;

create policy profiles_self_select on public.profiles for select to authenticated using (id = auth.uid() or public.is_platform_user());
create policy profiles_self_update on public.profiles for update to authenticated using (id = auth.uid() or public.is_platform_user()) with check (id = auth.uid() or public.is_platform_user());

create policy organizations_member_select on public.organizations for select to authenticated using (public.is_org_member(id) or owner_user_id = auth.uid() or public.is_platform_user());
create policy organizations_owner_update on public.organizations for update to authenticated using (public.has_permission(id, 'organization.manage') or public.is_platform_user()) with check (public.has_permission(id, 'organization.manage') or public.is_platform_user());

create policy branches_member_select on public.branches for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
create policy branches_manager_write on public.branches for all to authenticated using (public.has_permission(organization_id, 'organization.manage') or public.is_platform_user()) with check (public.has_permission(organization_id, 'organization.manage') or public.is_platform_user());

create policy memberships_member_select on public.organization_memberships for select to authenticated using (user_id = auth.uid() or public.has_permission(organization_id, 'members.manage') or public.is_platform_user());
create policy memberships_manager_write on public.organization_memberships for all to authenticated using (public.has_permission(organization_id, 'members.manage') or public.is_platform_user()) with check (public.has_permission(organization_id, 'members.manage') or public.is_platform_user());

create policy invitations_manager_access on public.invitations for all to authenticated using (public.has_permission(organization_id, 'members.manage') or public.is_platform_user()) with check (public.has_permission(organization_id, 'members.manage') or public.is_platform_user());
create policy tenant_edges_member_access on public.tenant_edges for select to authenticated using (public.is_org_member(from_organization_id) or public.is_org_member(to_organization_id) or public.is_platform_user());
create policy audit_member_select on public.audit_events for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());

create policy permissions_authenticated_select on public.permissions for select to authenticated using (true);
create policy role_permissions_authenticated_select on public.role_permissions for select to authenticated using (true);

-- Organization-scoped operational tables.
create policy customers_member_select on public.customers for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
create policy customers_permission_write on public.customers for all to authenticated using (public.has_permission(organization_id, 'customers.write') or public.is_platform_user()) with check (public.has_permission(organization_id, 'customers.write') or public.is_platform_user());
create policy suppliers_member_select on public.suppliers for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
create policy suppliers_permission_write on public.suppliers for all to authenticated using (public.has_permission(organization_id, 'suppliers.write') or public.is_platform_user()) with check (public.has_permission(organization_id, 'suppliers.write') or public.is_platform_user());
create policy drivers_member_select on public.drivers for select to authenticated using (public.is_org_member(organization_id) or user_id = auth.uid() or public.is_platform_user());
create policy drivers_permission_write on public.drivers for all to authenticated using (public.has_permission(organization_id, 'drivers.write') or user_id = auth.uid() or public.is_platform_user()) with check (public.has_permission(organization_id, 'drivers.write') or user_id = auth.uid() or public.is_platform_user());
create policy vehicles_member_select on public.vehicles for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
create policy vehicles_permission_write on public.vehicles for all to authenticated using (public.has_permission(organization_id, 'vehicles.write') or public.is_platform_user()) with check (public.has_permission(organization_id, 'vehicles.write') or public.is_platform_user());
create policy price_books_member_select on public.price_books for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
create policy price_books_permission_write on public.price_books for all to authenticated using (public.has_permission(organization_id, 'pricing.write') or public.is_platform_user()) with check (public.has_permission(organization_id, 'pricing.write') or public.is_platform_user());
create policy price_book_items_member_select on public.price_book_items for select to authenticated using (exists (select 1 from public.price_books p where p.id = price_book_id and (public.is_org_member(p.organization_id) or public.is_platform_user())));
create policy price_book_items_permission_write on public.price_book_items for all to authenticated using (exists (select 1 from public.price_books p where p.id = price_book_id and (public.has_permission(p.organization_id, 'pricing.write') or public.is_platform_user()))) with check (exists (select 1 from public.price_books p where p.id = price_book_id and (public.has_permission(p.organization_id, 'pricing.write') or public.is_platform_user())));

create policy bookings_member_select on public.bookings for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
create policy bookings_permission_write on public.bookings for all to authenticated using (public.has_permission(organization_id, 'bookings.write') or public.is_platform_user()) with check (public.has_permission(organization_id, 'bookings.write') or public.is_platform_user());
create policy duties_member_select on public.duties for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
create policy duties_permission_write on public.duties for all to authenticated using (public.has_permission(organization_id, 'duties.write') or public.is_platform_user()) with check (public.has_permission(organization_id, 'duties.write') or public.is_platform_user());
create policy duty_events_member_select on public.duty_events for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
create policy duty_events_permission_write on public.duty_events for all to authenticated using (public.has_permission(organization_id, 'duties.write') or public.is_platform_user()) with check (public.has_permission(organization_id, 'duties.write') or public.is_platform_user());
create policy duty_proofs_member_select on public.duty_proofs for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
create policy duty_proofs_permission_write on public.duty_proofs for all to authenticated using (public.has_permission(organization_id, 'duties.proof_review') or public.is_platform_user()) with check (public.has_permission(organization_id, 'duties.proof_review') or public.is_platform_user());
create policy track_points_member_select on public.track_points for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
create policy track_points_permission_write on public.track_points for all to authenticated using (public.has_permission(organization_id, 'tracking.read') or public.is_platform_user()) with check (public.has_permission(organization_id, 'tracking.read') or public.is_platform_user());
create policy sync_operations_user_access on public.sync_operations for all to authenticated using (user_id = auth.uid() or public.is_platform_user()) with check (user_id = auth.uid() or public.is_platform_user());
create policy expenses_member_select on public.expenses for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
create policy expenses_driver_write on public.expenses for all to authenticated using (public.has_permission(organization_id, 'duties.write') or exists (select 1 from public.duties d join public.drivers dr on dr.id = d.driver_id where d.id = duty_id and dr.user_id = auth.uid()) or public.is_platform_user()) with check (public.has_permission(organization_id, 'duties.write') or exists (select 1 from public.duties d join public.drivers dr on dr.id = d.driver_id where d.id = duty_id and dr.user_id = auth.uid()) or public.is_platform_user());

create policy invoices_member_select on public.invoices for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
create policy invoices_permission_write on public.invoices for all to authenticated using (public.has_permission(organization_id, 'billing.write') or public.is_platform_user()) with check (public.has_permission(organization_id, 'billing.write') or public.is_platform_user());
create policy invoice_lines_member_select on public.invoice_lines for select to authenticated using (exists (select 1 from public.invoices i where i.id = invoice_id and (public.is_org_member(i.organization_id) or public.is_platform_user())));
create policy invoice_lines_permission_write on public.invoice_lines for all to authenticated using (exists (select 1 from public.invoices i where i.id = invoice_id and (public.has_permission(i.organization_id, 'billing.write') or public.is_platform_user()))) with check (exists (select 1 from public.invoices i where i.id = invoice_id and (public.has_permission(i.organization_id, 'billing.write') or public.is_platform_user())));
create policy payments_member_select on public.payments for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
create policy payments_permission_write on public.payments for all to authenticated using (public.has_permission(organization_id, 'payments.write') or public.is_platform_user()) with check (public.has_permission(organization_id, 'payments.write') or public.is_platform_user());
create policy notifications_recipient_select on public.notifications for select to authenticated using (recipient_id = auth.uid() or public.is_org_member(organization_id) or public.is_platform_user());
create policy integration_events_member_select on public.integration_events for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
create policy employees_member_select on public.employees for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
create policy employees_manager_write on public.employees for all to authenticated using (public.has_permission(organization_id, 'members.manage') or public.is_platform_user()) with check (public.has_permission(organization_id, 'members.manage') or public.is_platform_user());
create policy travel_policies_member_select on public.travel_policies for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
create policy travel_policies_manager_write on public.travel_policies for all to authenticated using (public.has_permission(organization_id, 'organization.manage') or public.is_platform_user()) with check (public.has_permission(organization_id, 'organization.manage') or public.is_platform_user());
create policy booking_approvals_member_select on public.booking_approvals for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
create policy booking_approvals_write on public.booking_approvals for all to authenticated using (public.has_permission(organization_id, 'bookings.approve') or public.is_platform_user()) with check (public.has_permission(organization_id, 'bookings.approve') or public.is_platform_user());
create policy documents_member_select on public.documents for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
create policy documents_manager_write on public.documents for all to authenticated using (public.has_permission(organization_id, 'drivers.write') or public.has_permission(organization_id, 'duties.proof_review') or public.is_platform_user()) with check (public.has_permission(organization_id, 'drivers.write') or public.has_permission(organization_id, 'duties.proof_review') or public.is_platform_user());
create policy support_tickets_member_select on public.support_tickets for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
create policy support_tickets_member_write on public.support_tickets for all to authenticated using (public.is_org_member(organization_id) or public.is_platform_user()) with check (public.is_org_member(organization_id) or public.is_platform_user());
create policy privacy_requests_owner_access on public.privacy_requests for all to authenticated using (requester_id = auth.uid() or public.has_permission(organization_id, 'organization.manage') or public.is_platform_user()) with check (requester_id = auth.uid() or public.has_permission(organization_id, 'organization.manage') or public.is_platform_user());
create policy organization_settings_manager_access on public.organization_settings for all to authenticated using (public.has_permission(organization_id, 'organization.manage') or public.is_platform_user()) with check (public.has_permission(organization_id, 'organization.manage') or public.is_platform_user());
create policy einvoice_records_member_select on public.einvoice_records for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
create policy einvoice_records_billing_write on public.einvoice_records for insert to authenticated with check (public.has_permission(organization_id, 'billing.issue') or public.is_platform_user());
create policy collection_actions_member_select on public.collection_actions for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
create policy collection_actions_billing_write on public.collection_actions for insert to authenticated with check (public.has_permission(organization_id, 'billing.write') or public.has_permission(organization_id, 'notifications.send') or public.is_platform_user());

-- Domain state transitions are server-controlled. The browser can read organization-scoped
-- records through RLS, but issue/payment/duty transitions must be atomic and auditable.
create or replace function public.transition_duty(
  p_duty_id uuid,
  p_next_status public.duty_status,
  p_payload jsonb default '{}'::jsonb
)
returns public.duties
language plpgsql
security definer
set search_path = public
as $$
declare
  current_duty public.duties;
  updated_duty public.duties;
  allowed boolean := false;
  event_key text;
begin
  select * into current_duty
  from public.duties
  where id = p_duty_id
  for update;

  if current_duty.id is null then
    raise exception 'Duty not found';
  end if;
  if not (
    public.has_permission(current_duty.organization_id, 'duties.write')
    or exists (select 1 from public.drivers driver_row where driver_row.id = current_duty.driver_id and driver_row.user_id = auth.uid())
    or public.is_platform_user()
  ) then
    raise exception 'Duty transition is not permitted';
  end if;

  event_key := nullif(coalesce(p_payload->>'idempotency_key', ''), '');
  if event_key is not null and exists (
    select 1 from public.duty_events
    where organization_id = current_duty.organization_id and idempotency_key = event_key
  ) then
    return current_duty;
  end if;

  allowed :=
    (current_duty.status = p_next_status)
    or (current_duty.status = 'draft' and p_next_status in ('assigned', 'cancelled'))
    or (current_duty.status = 'assigned' and p_next_status in ('accepted', 'en_route', 'cancelled'))
    or (current_duty.status = 'accepted' and p_next_status in ('en_route', 'cancelled'))
    or (current_duty.status = 'en_route' and p_next_status in ('started', 'cancelled'))
    or (current_duty.status = 'started' and p_next_status in ('paused', 'completed', 'disputed'))
    or (current_duty.status = 'paused' and p_next_status in ('started', 'completed', 'disputed'))
    or (current_duty.status = 'completed' and p_next_status = 'disputed');

  if not allowed then
    raise exception 'Invalid duty transition from % to %', current_duty.status, p_next_status;
  end if;

  update public.duties
  set status = p_next_status,
      started_at = case when p_next_status = 'started' then coalesce(started_at, now()) else started_at end,
      completed_at = case when p_next_status = 'completed' then coalesce(completed_at, now()) else completed_at end,
      updated_at = now()
  where id = p_duty_id
  returning * into updated_duty;

  insert into public.duty_events (organization_id, duty_id, event_type, source, idempotency_key, payload, created_by)
  values (updated_duty.organization_id, updated_duty.id, 'status_changed', coalesce(p_payload->>'source', 'web'), event_key,
          coalesce(p_payload, '{}'::jsonb) || jsonb_build_object('from', current_duty.status, 'to', p_next_status), auth.uid());

  return updated_duty;
end;
$$;

create or replace function public.save_duty_calculation(
  p_duty_id uuid,
  p_snapshot jsonb
)
returns public.duties
language plpgsql
security definer
set search_path = public
as $$
declare
  target_duty public.duties;
begin
  select * into target_duty from public.duties where id = p_duty_id for update;
  if target_duty.id is null then raise exception 'Duty not found'; end if;
  if not (public.has_permission(target_duty.organization_id, 'duties.write') or public.is_platform_user()) then
    raise exception 'Duty calculation is not permitted';
  end if;
  if target_duty.status not in ('started', 'paused', 'completed', 'disputed') then
    raise exception 'Duty must be started before it can be calculated';
  end if;
  if p_snapshot is null or jsonb_typeof(p_snapshot) <> 'object' then
    raise exception 'Calculation snapshot must be a JSON object';
  end if;

  update public.duties
  set calculation_snapshot = p_snapshot,
      updated_at = now()
  where id = p_duty_id
  returning * into target_duty;
  return target_duty;
end;
$$;

create or replace function public.prevent_issued_invoice_mutation()
returns trigger
language plpgsql
as $$
begin
  if old.status = 'draft' then
    if new.status is distinct from old.status
       and not (new.status = 'issued' and public.has_permission(old.organization_id, 'billing.issue')) then
      raise exception 'Invoice state transitions must use the billing RPC';
    end if;
    if new.status = 'issued' and new.immutable_snapshot is null then
      raise exception 'Issued invoices require an immutable snapshot';
    end if;
  else
    if new.invoice_number is distinct from old.invoice_number
       or new.organization_id is distinct from old.organization_id
       or new.customer_id is distinct from old.customer_id
       or new.booking_id is distinct from old.booking_id
       or new.currency is distinct from old.currency
       or new.subtotal_paise is distinct from old.subtotal_paise
       or new.tax_paise is distinct from old.tax_paise
       or new.total_paise is distinct from old.total_paise
       or new.immutable_snapshot is distinct from old.immutable_snapshot then
      raise exception 'Issued invoice financial fields are immutable';
    end if;
    if new.status is distinct from old.status
       and coalesce(current_setting('axiom.invoice_state_transition', true), '') <> 'on' then
      raise exception 'Invoice state transitions must use the billing RPC';
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_prevent_issued_invoice_mutation on public.invoices;
create trigger trg_prevent_issued_invoice_mutation
before update on public.invoices
for each row execute function public.prevent_issued_invoice_mutation();

create or replace function public.issue_invoice(p_invoice_id uuid)
returns public.invoices
language plpgsql
security definer
set search_path = public
as $$
declare
  invoice_row public.invoices;
  snapshot jsonb;
begin
  select * into invoice_row from public.invoices where id = p_invoice_id for update;
  if invoice_row.id is null then raise exception 'Invoice not found'; end if;
  if not (public.has_permission(invoice_row.organization_id, 'billing.issue') or public.is_platform_user()) then
    raise exception 'Invoice issue is not permitted';
  end if;
  if invoice_row.status <> 'draft' then return invoice_row; end if;
  if invoice_row.total_paise < 0 then raise exception 'Invoice total cannot be negative'; end if;

  snapshot := jsonb_build_object(
    'invoice', to_jsonb(invoice_row),
    'lines', coalesce((select jsonb_agg(to_jsonb(line_row) order by line_row.created_at)
                       from public.invoice_lines line_row where line_row.invoice_id = invoice_row.id), '[]'::jsonb),
    'issued_by', auth.uid(),
    'issued_at', now()
  );

  perform set_config('axiom.invoice_state_transition', 'on', true);
  update public.invoices
  set status = 'issued',
      issued_at = coalesce(issued_at, now()),
      immutable_snapshot = snapshot,
      updated_at = now()
  where id = invoice_row.id
  returning * into invoice_row;
  return invoice_row;
end;
$$;

create or replace function public.record_payment(
  p_invoice_id uuid,
  p_amount_paise bigint,
  p_mode text,
  p_idempotency_key text default null
)
returns public.payments
language plpgsql
security definer
set search_path = public
as $$
declare
  invoice_row public.invoices;
  payment_row public.payments;
  collected bigint;
begin
  select * into invoice_row from public.invoices where id = p_invoice_id for update;
  if invoice_row.id is null then raise exception 'Invoice not found'; end if;
  if not (public.has_permission(invoice_row.organization_id, 'payments.write') or public.is_platform_user()) then
    raise exception 'Payment recording is not permitted';
  end if;
  if p_amount_paise <= 0 then raise exception 'Payment amount must be positive'; end if;
  if invoice_row.status = 'void' then raise exception 'Cannot pay a void invoice'; end if;

  if p_idempotency_key is not null then
    select * into payment_row from public.payments
    where organization_id = invoice_row.organization_id and idempotency_key = p_idempotency_key;
    if payment_row.id is not null then return payment_row; end if;
  end if;

  insert into public.payments (organization_id, invoice_id, amount_paise, mode, status, idempotency_key, received_at)
  values (invoice_row.organization_id, invoice_row.id, p_amount_paise, coalesce(nullif(p_mode, ''), 'other'), 'succeeded', p_idempotency_key, now())
  returning * into payment_row;

  select coalesce(sum(amount_paise), 0) into collected
  from public.payments
  where invoice_id = invoice_row.id and status = 'succeeded';

  perform set_config('axiom.invoice_state_transition', 'on', true);
  update public.invoices
  set status = case when collected >= total_paise then 'paid' else 'partially_paid' end,
      updated_at = now()
  where id = invoice_row.id and status <> 'void';
  return payment_row;
end;
$$;

create or replace function public.record_expense(
  p_duty_id uuid,
  p_category text,
  p_amount_paise bigint,
  p_note text default '',
  p_attachment jsonb default '{}'::jsonb,
  p_idempotency_key text default null
)
returns public.expenses
language plpgsql
security definer
set search_path = public
as $$
declare
  duty_row public.duties;
  expense_row public.expenses;
begin
  select * into duty_row from public.duties where id = p_duty_id;
  if duty_row.id is null then raise exception 'Duty not found'; end if;
  if not (public.has_permission(duty_row.organization_id, 'duties.write') or exists (select 1 from public.drivers driver_row where driver_row.id = duty_row.driver_id and driver_row.user_id = auth.uid()) or public.is_platform_user()) then
    raise exception 'Duty expense capture is not permitted';
  end if;
  if p_amount_paise <= 0 then raise exception 'Expense amount must be positive'; end if;
  if p_idempotency_key is not null then
    select * into expense_row from public.expenses where organization_id = duty_row.organization_id and idempotency_key = p_idempotency_key;
    if expense_row.id is not null then return expense_row; end if;
  end if;
  insert into public.expenses (organization_id, duty_id, category, amount_paise, note, attachment, idempotency_key, created_by)
  values (duty_row.organization_id, duty_row.id, p_category, p_amount_paise, coalesce(p_note, ''), coalesce(p_attachment, '{}'::jsonb), p_idempotency_key, auth.uid())
  returning * into expense_row;
  return expense_row;
end;
$$;

create or replace function public.capture_duty_proof(
  p_duty_id uuid,
  p_proof_type text,
  p_proof_data jsonb default '{}'::jsonb,
  p_storage_path text default null,
  p_idempotency_key text default null
)
returns public.duty_proofs
language plpgsql
security definer
set search_path = public
as $$
declare
  duty_row public.duties;
  proof_row public.duty_proofs;
begin
  select * into duty_row from public.duties where id = p_duty_id;
  if duty_row.id is null then raise exception 'Duty not found'; end if;
  if not (
    public.has_permission(duty_row.organization_id, 'duties.proof_review')
    or exists (select 1 from public.drivers driver_row where driver_row.id = duty_row.driver_id and driver_row.user_id = auth.uid())
    or public.is_platform_user()
  ) then
    raise exception 'Duty proof capture is not permitted';
  end if;
  if p_idempotency_key is not null then
    select * into proof_row from public.duty_proofs
    where organization_id = duty_row.organization_id and idempotency_key = p_idempotency_key;
    if proof_row.id is not null then return proof_row; end if;
  end if;
  insert into public.duty_proofs (organization_id, duty_id, proof_type, storage_path, proof_data, idempotency_key, captured_by)
  values (duty_row.organization_id, duty_row.id, p_proof_type, p_storage_path, coalesce(p_proof_data, '{}'::jsonb), p_idempotency_key, auth.uid())
  returning * into proof_row;
  return proof_row;
end;
$$;

create or replace function public.record_track_point(
  p_duty_id uuid,
  p_recorded_at timestamptz,
  p_latitude numeric,
  p_longitude numeric,
  p_accuracy_m numeric default null,
  p_battery_pct numeric default null,
  p_source text default 'driver_app',
  p_idempotency_key text default null
)
returns public.track_points
language plpgsql
security definer
set search_path = public
as $$
declare
  duty_row public.duties;
  point_row public.track_points;
begin
  select * into duty_row from public.duties where id = p_duty_id;
  if duty_row.id is null then raise exception 'Duty not found'; end if;
  if not (
    public.has_permission(duty_row.organization_id, 'tracking.read')
    or exists (select 1 from public.drivers driver_row where driver_row.id = duty_row.driver_id and driver_row.user_id = auth.uid())
    or public.is_platform_user()
  ) then
    raise exception 'Track point capture is not permitted';
  end if;
  if p_latitude < -90 or p_latitude > 90 or p_longitude < -180 or p_longitude > 180 then
    raise exception 'Location coordinates are out of range';
  end if;
  if p_idempotency_key is not null then
    select * into point_row from public.track_points
    where organization_id = duty_row.organization_id and idempotency_key = p_idempotency_key;
    if point_row.id is not null then return point_row; end if;
  end if;
  insert into public.track_points (organization_id, duty_id, recorded_at, latitude, longitude, accuracy_m, battery_pct, source, idempotency_key)
  values (duty_row.organization_id, duty_row.id, coalesce(p_recorded_at, now()), p_latitude, p_longitude, p_accuracy_m, p_battery_pct, coalesce(p_source, 'driver_app'), p_idempotency_key)
  returning * into point_row;
  return point_row;
end;
$$;

create or replace function public.enqueue_sync_operation(
  p_device_id text,
  p_idempotency_key text,
  p_entity_type text,
  p_entity_id uuid,
  p_operation text,
  p_payload jsonb default '{}'::jsonb,
  p_client_created_at timestamptz default null
)
returns public.sync_operations
language plpgsql
security definer
set search_path = public
as $$
declare
  driver_org uuid;
  sync_row public.sync_operations;
begin
  select organization_id into driver_org from public.drivers where user_id = auth.uid() and organization_id is not null limit 1;
  if driver_org is null then
    select m.organization_id into driver_org from public.organization_memberships m where m.user_id = auth.uid() and m.status = 'active' limit 1;
  end if;
  if driver_org is null then raise exception 'An organization-linked account is required'; end if;
  select * into sync_row from public.sync_operations where user_id = auth.uid() and idempotency_key = p_idempotency_key;
  if sync_row.id is not null then return sync_row; end if;
  insert into public.sync_operations (organization_id, user_id, device_id, idempotency_key, entity_type, entity_id, operation, payload, client_created_at)
  values (driver_org, auth.uid(), p_device_id, p_idempotency_key, p_entity_type, p_entity_id, p_operation, coalesce(p_payload, '{}'::jsonb), p_client_created_at)
  returning * into sync_row;
  return sync_row;
end;
$$;

-- Public clients use the anon key only for Auth. All data access is authenticated.
grant usage on schema public to anon, authenticated;
grant select, insert, update on public.profiles to authenticated;
grant select, update on public.organizations to authenticated;
grant select, insert, update on public.branches to authenticated;
grant select, insert, update on public.organization_memberships to authenticated;
grant select, insert, update on public.invitations to authenticated;
grant select on public.permissions, public.role_permissions to authenticated;
grant select on public.audit_events to authenticated;
grant select, insert, update on all tables in schema public to authenticated;
grant usage, select on all sequences in schema public to authenticated;
grant execute on function public.create_organization(public.organization_kind, text, text, text, text, integer, integer) to authenticated;
grant execute on function public.create_driver_profile(text, text, text, text) to authenticated;
grant execute on function public.create_invitation(citext, public.membership_role, uuid, integer) to authenticated;
grant execute on function public.accept_invitation(text) to authenticated;
grant execute on function public.transition_duty(uuid, public.duty_status, jsonb) to authenticated;
grant execute on function public.save_duty_calculation(uuid, jsonb) to authenticated;
grant execute on function public.issue_invoice(uuid) to authenticated;
grant execute on function public.record_payment(uuid, bigint, text, text) to authenticated;
grant execute on function public.record_expense(uuid, text, bigint, text, jsonb, text) to authenticated;
grant execute on function public.capture_duty_proof(uuid, text, jsonb, text, text) to authenticated;
grant execute on function public.record_track_point(uuid, timestamptz, numeric, numeric, numeric, numeric, text, text) to authenticated;
grant execute on function public.enqueue_sync_operation(text, text, text, uuid, text, jsonb, timestamptz) to authenticated;

-- Supabase Auth hook functions need access to profiles.
grant insert, update on public.profiles to supabase_auth_admin;
grant usage on schema public to supabase_auth_admin;

-- Extended feature layer. These tables keep the remaining PRD workflows
-- tenant-scoped while external systems remain mock adapters until credentials
-- and project-level infrastructure are supplied.
create table if not exists public.onboarding_states (
  organization_id uuid primary key references public.organizations(id) on delete cascade,
  steps jsonb not null default '{}'::jsonb,
  metadata jsonb not null default '{}'::jsonb,
  completed_at timestamptz,
  updated_by uuid references auth.users(id) on delete set null,
  updated_at timestamptz not null default now()
);
create table if not exists public.record_versions (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  entity_type text not null, entity_id uuid not null, version integer not null, change_type text not null default 'snapshot',
  payload jsonb not null default '{}'::jsonb, created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now(),
  unique (organization_id, entity_type, entity_id, version)
);
create table if not exists public.duplicate_matches (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  entity_type text not null, field_name text not null, normalized_value text not null, existing_id uuid, candidate_id uuid,
  status text not null default 'open', created_at timestamptz not null default now()
);
create table if not exists public.supplier_bills (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete restrict,
  supplier_id uuid references public.suppliers(id) on delete set null, bill_number text not null, subtotal_paise bigint not null default 0,
  tax_paise bigint not null default 0, total_paise bigint not null default 0, status text not null default 'captured', due_at timestamptz,
  duty_id uuid references public.duties(id) on delete set null, attachment jsonb not null default '{}'::jsonb,
  validation jsonb not null default '{}'::jsonb, created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  unique (organization_id, bill_number)
);
create table if not exists public.cost_entries (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete restrict,
  cost_type text not null, category text not null, amount_paise bigint not null default 0, vehicle_id uuid references public.vehicles(id) on delete set null,
  duty_id uuid references public.duties(id) on delete set null, supplier_bill_id uuid references public.supplier_bills(id) on delete set null,
  status text not null default 'submitted', attachment jsonb not null default '{}'::jsonb, notes text not null default '',
  created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now()
);
create table if not exists public.receipt_allocations (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete restrict,
  invoice_id uuid not null references public.invoices(id) on delete cascade, payment_id uuid references public.payments(id) on delete set null,
  amount_paise bigint not null check (amount_paise > 0), reference text not null default '', created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now()
);
create table if not exists public.payouts (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete restrict,
  recipient_type text not null, recipient_id uuid, period_start date, period_end date, amount_paise bigint not null default 0,
  status text not null default 'draft', metadata jsonb not null default '{}'::jsonb, approved_by uuid references auth.users(id) on delete set null,
  created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists public.financial_actions (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete restrict,
  action_type text not null, entity_type text not null, entity_id uuid not null, payload jsonb not null default '{}'::jsonb,
  status text not null default 'pending', requested_by uuid references auth.users(id) on delete set null, reviewed_by uuid references auth.users(id) on delete set null,
  review_comment text not null default '', created_at timestamptz not null default now(), reviewed_at timestamptz
);
create table if not exists public.approval_steps (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  booking_id uuid not null references public.bookings(id) on delete cascade, level integer not null, approver_role text not null,
  status text not null default 'pending', comment text not null default '', decided_by uuid references auth.users(id) on delete set null, decided_at timestamptz, created_at timestamptz not null default now(),
  unique (organization_id, booking_id, level)
);
create table if not exists public.sla_events (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  entity_type text not null, entity_id uuid not null, metric text not null, due_at timestamptz not null, status text not null default 'open', resolved_at timestamptz, created_at timestamptz not null default now()
);
create table if not exists public.trip_shares (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  duty_id uuid not null references public.duties(id) on delete cascade, token_hash text not null unique, recipient citext not null default '', expires_at timestamptz not null,
  status text not null default 'active', created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now()
);
create table if not exists public.passenger_ratings (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  duty_id uuid not null references public.duties(id) on delete cascade, rating integer not null check (rating between 1 and 5), tags text[] not null default '{}', comment text not null default '', created_at timestamptz not null default now()
);
create table if not exists public.driver_preferences (
  user_id uuid primary key references auth.users(id) on delete cascade, organization_id uuid references public.organizations(id) on delete cascade,
  language text not null default 'en-IN', quiet_hours jsonb not null default '{}'::jsonb, low_bandwidth boolean not null default true, updated_at timestamptz not null default now()
);
create table if not exists public.device_bindings (
  id uuid primary key default gen_random_uuid(), organization_id uuid references public.organizations(id) on delete cascade, user_id uuid not null references auth.users(id) on delete cascade,
  device_id text not null, platform text not null default 'web', status text not null default 'active', last_seen_at timestamptz not null default now(), push_token text not null default '', created_at timestamptz not null default now(), unique(user_id, device_id)
);
create table if not exists public.calls (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade, duty_id uuid references public.duties(id) on delete set null,
  caller_id uuid references auth.users(id) on delete set null, recipient text not null default '', masked_number text not null default '', status text not null default 'queued', provider_reference text not null default '', consent boolean not null default false, created_at timestamptz not null default now()
);
create table if not exists public.sos_events (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade, duty_id uuid references public.duties(id) on delete set null,
  driver_id uuid references public.drivers(id) on delete set null, latitude numeric, longitude numeric, status text not null default 'open', payload jsonb not null default '{}'::jsonb, created_at timestamptz not null default now(), resolved_at timestamptz
);
create table if not exists public.practice_duties (
  id uuid primary key default gen_random_uuid(), organization_id uuid references public.organizations(id) on delete cascade, user_id uuid not null references auth.users(id) on delete cascade,
  status text not null default 'available', scenario text not null default 'basic_execution', payload jsonb not null default '{}'::jsonb, created_at timestamptz not null default now(), completed_at timestamptz
);
create table if not exists public.alerts (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade, alert_type text not null, severity text not null default 'info',
  entity_type text, entity_id uuid, status text not null default 'open', payload jsonb not null default '{}'::jsonb, created_at timestamptz not null default now(), acknowledged_by uuid references auth.users(id) on delete set null, acknowledged_at timestamptz
);
create table if not exists public.geofences (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade, name text not null, latitude numeric not null, longitude numeric not null, radius_m numeric not null default 500, event_types text[] not null default '{}', status text not null default 'active', created_at timestamptz not null default now()
);
create table if not exists public.notification_events (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade, notification_id uuid references public.notifications(id) on delete cascade, event_type text not null, provider_reference text, payload jsonb not null default '{}', created_at timestamptz not null default now()
);
create table if not exists public.network_edges (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade, partner_organization_id uuid references public.organizations(id) on delete set null, partner_name text not null default '', status text not null default 'invited', cities text[] not null default '{}', trust_score numeric not null default 0, created_at timestamptz not null default now(), accepted_at timestamptz
);
create table if not exists public.network_offers (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade, edge_id uuid references public.network_edges(id) on delete set null, duty_id uuid references public.duties(id) on delete set null, status text not null default 'offered', amount_paise bigint not null default 0, expires_at timestamptz, created_at timestamptz not null default now()
);
create table if not exists public.network_bids (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade, offer_id uuid not null references public.network_offers(id) on delete cascade, bidder_organization_id uuid references public.organizations(id) on delete set null, amount_paise bigint not null default 0, status text not null default 'submitted', comment text not null default '', created_at timestamptz not null default now()
);
create table if not exists public.settlements (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade, partner_organization_id uuid references public.organizations(id) on delete set null, period_start date, period_end date, gross_paise bigint not null default 0, deductions_paise bigint not null default 0, net_paise bigint not null default 0, status text not null default 'draft', evidence jsonb not null default '{}', created_at timestamptz not null default now()
);
create table if not exists public.report_exports (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade, report_type text not null, filters jsonb not null default '{}', status text not null default 'ready', download_token text not null unique, content text not null default '', expires_at timestamptz not null, created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now()
);
create table if not exists public.report_views (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade, name text not null, config jsonb not null default '{}', created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now(), unique(organization_id, name)
);
create table if not exists public.report_schedules (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade, report_type text not null, cadence text not null default 'weekly', recipients citext[] not null default '{}', filters jsonb not null default '{}', status text not null default 'active', next_run_at timestamptz, created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now()
);
create table if not exists public.consents (
  id uuid primary key default gen_random_uuid(), organization_id uuid references public.organizations(id) on delete cascade, subject_id text not null, purpose text not null, policy_version text not null, status text not null default 'granted', evidence jsonb not null default '{}', captured_at timestamptz not null default now()
);
create table if not exists public.retention_locks (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade, entity_type text not null, entity_id uuid not null, reason text not null, expires_at timestamptz, created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now()
);
create table if not exists public.webhook_events (
  id uuid primary key default gen_random_uuid(), organization_id uuid references public.organizations(id) on delete cascade, provider text not null, event_type text not null, external_id text not null, payload jsonb not null default '{}', signature_valid boolean not null default false, status text not null default 'received', created_at timestamptz not null default now(), unique(provider, external_id)
);
create table if not exists public.booking_stops (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade, booking_id uuid not null references public.bookings(id) on delete cascade, stop_index integer not null, label text not null, address jsonb not null default '{}', arrival_at timestamptz, departure_at timestamptz, status text not null default 'planned', created_at timestamptz not null default now(), unique(organization_id, booking_id, stop_index)
);
create table if not exists public.recurring_bookings (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade, customer_id uuid references public.customers(id) on delete set null, cadence text not null, start_at timestamptz not null, end_at timestamptz, occurrences integer not null default 1 check (occurrences between 1 and 365), generated_count integer not null default 0, status text not null default 'active', template jsonb not null default '{}', created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists public.capacity_locks (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade, resource_type text not null, resource_id uuid not null, booking_id uuid references public.bookings(id) on delete set null, starts_at timestamptz not null, ends_at timestamptz not null, status text not null default 'held', created_at timestamptz not null default now(), released_at timestamptz, check (ends_at > starts_at)
);
create table if not exists public.billing_notes (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade, note_type text not null check (note_type in ('proforma','credit','debit')), invoice_id uuid references public.invoices(id) on delete set null, customer_id uuid references public.customers(id) on delete set null, reference text not null, amount_paise bigint not null default 0, tax_paise bigint not null default 0, status text not null default 'draft', reason text not null default '', created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now(), unique(organization_id, reference)
);
create table if not exists public.payment_links (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade, invoice_id uuid references public.invoices(id) on delete set null, amount_paise bigint not null default 0, token_hash text not null unique, short_code text not null unique, status text not null default 'created', expires_at timestamptz not null, paid_at timestamptz, provider_reference text, created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now()
);
create table if not exists public.jobs (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade, job_type text not null, status text not null default 'queued', payload jsonb not null default '{}', result jsonb not null default '{}', error_message text not null default '', attempts integer not null default 0, available_at timestamptz not null default now(), started_at timestamptz, completed_at timestamptz, created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now()
);
create table if not exists public.auth_factors (
  user_id uuid primary key references auth.users(id) on delete cascade, organization_id uuid references public.organizations(id) on delete cascade, factor_type text not null default 'totp', secret_hash text not null, status text not null default 'pending', recovery_codes jsonb not null default '[]', created_at timestamptz not null default now(), verified_at timestamptz, last_used_at timestamptz
);
create table if not exists public.api_keys (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade, name text not null, key_hash text not null unique, key_prefix text not null, scopes text[] not null default '{}', status text not null default 'active', last_used_at timestamptz, created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now(), revoked_at timestamptz
);
create table if not exists public.security_events (
  id uuid primary key default gen_random_uuid(), organization_id uuid references public.organizations(id) on delete cascade, user_id uuid references auth.users(id) on delete set null, event_type text not null, severity text not null default 'info', metadata jsonb not null default '{}', created_at timestamptz not null default now()
);

create index if not exists idx_onboarding_states_updated on public.onboarding_states(updated_at);
create index if not exists idx_record_versions_entity on public.record_versions(organization_id, entity_type, entity_id, version desc);
create index if not exists idx_duplicate_matches_lookup on public.duplicate_matches(organization_id, entity_type, field_name, normalized_value);
create index if not exists idx_supplier_bills_org_status on public.supplier_bills(organization_id, status, created_at desc);
create index if not exists idx_cost_entries_org_created on public.cost_entries(organization_id, created_at desc);
create index if not exists idx_receipt_allocations_invoice on public.receipt_allocations(organization_id, invoice_id);
create index if not exists idx_payouts_org_status on public.payouts(organization_id, status, created_at desc);
create index if not exists idx_financial_actions_org_status on public.financial_actions(organization_id, status, created_at desc);
create index if not exists idx_approval_steps_booking on public.approval_steps(organization_id, booking_id, level);
create index if not exists idx_sla_events_due on public.sla_events(organization_id, status, due_at);
create index if not exists idx_trip_shares_duty on public.trip_shares(organization_id, duty_id, status);
create index if not exists idx_alerts_org_status on public.alerts(organization_id, status, created_at desc);
create index if not exists idx_geofences_org_status on public.geofences(organization_id, status);
create index if not exists idx_network_edges_org_status on public.network_edges(organization_id, status);
create index if not exists idx_network_offers_org_status on public.network_offers(organization_id, status, created_at desc);
create index if not exists idx_network_bids_offer on public.network_bids(organization_id, offer_id, created_at desc);
create index if not exists idx_report_exports_expiry on public.report_exports(organization_id, expires_at);
create index if not exists idx_retention_locks_entity on public.retention_locks(organization_id, entity_type, entity_id);
create index if not exists idx_webhook_events_org_created on public.webhook_events(organization_id, created_at desc);
create index if not exists idx_booking_stops_booking on public.booking_stops(organization_id, booking_id, stop_index);
create index if not exists idx_recurring_bookings_org_status on public.recurring_bookings(organization_id, status, start_at);
create index if not exists idx_capacity_locks_resource on public.capacity_locks(organization_id, resource_type, resource_id, starts_at, ends_at);
create index if not exists idx_billing_notes_org_created on public.billing_notes(organization_id, created_at desc);
create index if not exists idx_payment_links_org_status on public.payment_links(organization_id, status, created_at desc);
create index if not exists idx_jobs_queue on public.jobs(organization_id, status, available_at);
create index if not exists idx_security_events_org_created on public.security_events(organization_id, created_at desc);

-- All extended tenant tables use the same membership boundary. Append-only
-- evidence tables can later be tightened to insert-only policies per role.
do $$
declare t text;
begin
  foreach t in array array['onboarding_states','record_versions','duplicate_matches','supplier_bills','cost_entries','receipt_allocations','payouts','financial_actions','approval_steps','sla_events','trip_shares','passenger_ratings','driver_preferences','device_bindings','calls','sos_events','practice_duties','alerts','geofences','notification_events','network_edges','network_offers','network_bids','settlements','report_exports','report_views','report_schedules','consents','retention_locks','webhook_events','booking_stops','recurring_bookings','capacity_locks','billing_notes','payment_links','jobs','auth_factors','api_keys','security_events'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('grant select, insert, update on public.%I to authenticated', t);
    execute format('drop policy if exists %I on public.%I', t || '_tenant_access', t);
    execute format('drop policy if exists %I on public.%I', t || '_user_access', t);
    execute format('drop policy if exists %I on public.%I', t || '_security_access', t);
    if t in ('driver_preferences','auth_factors') then
      execute format('create policy %I on public.%I for all to authenticated using (user_id = auth.uid() or public.is_platform_user()) with check (user_id = auth.uid() or public.is_platform_user())', t || '_user_access', t);
    elsif t in ('device_bindings','practice_duties') then
      execute format('create policy %I on public.%I for all to authenticated using (user_id = auth.uid() or public.is_org_member(organization_id) or public.is_platform_user()) with check (user_id = auth.uid() or public.is_org_member(organization_id) or public.is_platform_user())', t || '_user_access', t);
    elsif t = 'webhook_events' then
      execute format('create policy %I on public.%I for all to authenticated using (public.is_org_member(organization_id) or public.is_platform_user()) with check (public.is_org_member(organization_id) or public.is_platform_user())', t || '_tenant_access', t);
    elsif t = 'security_events' then
      execute format('create policy %I on public.%I for all to authenticated using (user_id = auth.uid() or public.is_org_member(organization_id) or public.is_platform_user()) with check (user_id = auth.uid() or public.is_org_member(organization_id) or public.is_platform_user())', t || '_security_access', t);
    else
      execute format('create policy %I on public.%I for all to authenticated using (public.is_org_member(organization_id) or public.is_platform_user()) with check (public.is_org_member(organization_id) or public.is_platform_user())', t || '_tenant_access', t);
    end if;
  end loop;
end $$;
