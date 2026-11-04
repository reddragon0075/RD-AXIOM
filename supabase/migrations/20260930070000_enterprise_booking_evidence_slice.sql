-- Axiom Fleet enterprise controls, passenger request API and duty evidence slice.
-- Additive only: existing corporate, operations, billing and Network contracts remain intact.

insert into public.permissions(key, description) values
  ('enterprise.manage', 'Manage company hierarchy, plans, portal access and booking controls'),
  ('enterprise.booking', 'Create enterprise quotes, allotment requests and exceptions'),
  ('enterprise.evidence', 'Manage duty execution, evidence, closure jobs and adjustments')
on conflict (key) do nothing;
insert into public.role_permissions(role, permission_key) values
  ('vendor_owner'::public.membership_role, 'enterprise.manage'),
  ('vendor_owner'::public.membership_role, 'enterprise.booking'),
  ('vendor_owner'::public.membership_role, 'enterprise.evidence'),
  ('vendor_ops'::public.membership_role, 'enterprise.manage'),
  ('vendor_ops'::public.membership_role, 'enterprise.booking'),
  ('vendor_ops'::public.membership_role, 'enterprise.evidence'),
  ('corporate_admin'::public.membership_role, 'enterprise.manage'),
  ('corporate_admin'::public.membership_role, 'enterprise.booking'),
  ('corporate_admin'::public.membership_role, 'enterprise.evidence'),
  ('corporate_travel'::public.membership_role, 'enterprise.booking')
on conflict do nothing;

-- Private evidence bucket; the Edge boundary issues short-lived signed URLs.
insert into storage.buckets (id, name, public) values ('duty-evidence', 'duty-evidence', false)
on conflict (id) do nothing;

create table if not exists public.enterprise_groups (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  group_type text not null default 'customer',
  code text not null,
  name text not null,
  parent_id uuid references public.enterprise_groups(id) on delete set null,
  status text not null default 'active',
  metadata jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, group_type, code)
);
create table if not exists public.enterprise_group_members (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  group_id uuid not null references public.enterprise_groups(id) on delete cascade,
  entity_type text not null,
  entity_id uuid not null,
  created_at timestamptz not null default now(),
  unique (group_id, entity_type, entity_id)
);
create table if not exists public.enterprise_companies (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  code text not null,
  legal_name text not null,
  trading_name text not null default '',
  gstin text not null default '',
  pan text not null default '',
  is_sister_company boolean not null default false,
  status text not null default 'active',
  billing jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, code)
);
create table if not exists public.enterprise_billing_profiles (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  company_id uuid references public.enterprise_companies(id) on delete cascade,
  tax_entity_id uuid,
  bank_account_id uuid,
  invoice_series text not null default '',
  currency text not null default 'INR',
  bill_to_mode text not null default 'company',
  status text not null default 'active',
  metadata jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, company_id)
);
create table if not exists public.enterprise_bank_accounts (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  company_id uuid references public.enterprise_companies(id) on delete set null,
  account_name text not null,
  masked_account text not null default '',
  ifsc text not null default '',
  bank_name text not null default '',
  account_type text not null default 'current',
  status text not null default 'active',
  metadata jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.enterprise_tax_entities (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  company_id uuid references public.enterprise_companies(id) on delete set null,
  name text not null,
  gstin text not null default '',
  state_code text not null default '',
  registration_type text not null default 'regular',
  status text not null default 'active',
  metadata jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.enterprise_billing_items (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  code text not null,
  name text not null,
  item_type text not null default 'charge',
  unit text not null default 'unit',
  tax_code text not null default '',
  mandatory boolean not null default false,
  rules jsonb not null default '{}',
  status text not null default 'active',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, code)
);
create table if not exists public.enterprise_custom_fields (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  entity_type text not null,
  field_key text not null,
  label text not null,
  field_type text not null default 'text',
  required boolean not null default false,
  options jsonb not null default '[]',
  status text not null default 'active',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, entity_type, field_key)
);
create table if not exists public.enterprise_company_profiles (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  company_id uuid references public.enterprise_companies(id) on delete cascade,
  display_name text not null default '',
  logo_path text not null default '',
  signature_path text not null default '',
  invoice_letterhead_path text not null default '',
  footer text not null default '',
  metadata jsonb not null default '{}',
  updated_by uuid references auth.users(id) on delete set null,
  updated_at timestamptz not null default now(),
  unique (organization_id, company_id)
);
create table if not exists public.enterprise_plan_subscriptions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  plan_code text not null,
  status text not null default 'active',
  starts_at timestamptz not null default now(),
  ends_at timestamptz,
  entitlements jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, plan_code)
);
create table if not exists public.enterprise_usage_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  feature_key text not null,
  quantity integer not null default 1 check (quantity > 0),
  period_key text not null,
  metadata jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);
create table if not exists public.enterprise_sso_configs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  provider text not null default 'oidc',
  issuer_url text not null default '',
  client_id text not null default '',
  domains jsonb not null default '[]',
  status text not null default 'draft',
  metadata jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, provider)
);
create table if not exists public.passenger_portal_tokens (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  customer_id uuid references public.customers(id) on delete set null,
  token_hash text not null unique,
  idempotency_key text,
  label text not null default '',
  status text not null default 'active',
  expires_at timestamptz not null,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  last_used_at timestamptz,
  unique (organization_id, idempotency_key)
);

create table if not exists public.booking_control_rules (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  name text not null,
  status text not null default 'active',
  package_minutes integer not null default 30 check (package_minutes > 0),
  package_base_paise bigint not null default 0 check (package_base_paise >= 0),
  extra_km_paise bigint not null default 0 check (extra_km_paise >= 0),
  extra_half_hour_paise bigint not null default 0 check (extra_half_hour_paise >= 0),
  auto_switch jsonb not null default '{}',
  supplier_city jsonb not null default '{}',
  eta_guard_minutes integer not null default 60,
  price_guard_paise bigint not null default 0,
  customer_controlled_allotment boolean not null default false,
  temporary_allotment boolean not null default false,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, name)
);
create table if not exists public.enterprise_booking_quotes (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  booking_id uuid not null references public.bookings(id) on delete cascade,
  rule_id uuid references public.booking_control_rules(id) on delete set null,
  status text not null default 'draft',
  duration_minutes integer not null default 0,
  distance_km numeric(12,3) not null default 0,
  package_minutes integer not null default 30,
  base_paise bigint not null default 0,
  extra_km_paise bigint not null default 0,
  extra_time_paise bigint not null default 0,
  total_paise bigint not null default 0,
  breakdown jsonb not null default '{}',
  idempotency_key text,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);
create table if not exists public.allotment_requests (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  booking_id uuid not null references public.bookings(id) on delete cascade,
  supplier_id uuid references public.suppliers(id) on delete set null,
  request_type text not null default 'multi_supplier',
  status text not null default 'requested',
  idempotency_key text,
  offered_amount_paise bigint,
  eta_minutes integer,
  payload jsonb not null default '{}',
  expires_at timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.allotment_responses (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  request_id uuid not null references public.allotment_requests(id) on delete cascade,
  supplier_id uuid references public.suppliers(id) on delete set null,
  status text not null,
  amount_paise bigint,
  eta_minutes integer,
  reason text not null default '',
  payload jsonb not null default '{}',
  created_at timestamptz not null default now()
);
create table if not exists public.allotment_exceptions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  booking_id uuid not null references public.bookings(id) on delete cascade,
  duty_id uuid references public.duties(id) on delete set null,
  exception_type text not null,
  severity text not null default 'medium',
  status text not null default 'open',
  reason text not null,
  resolution jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  resolved_at timestamptz
);

create table if not exists public.duty_execution_profiles (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  duty_id uuid not null references public.duties(id) on delete cascade,
  source text not null default 'dashboard',
  driver_mode text not null default 'assigned',
  garage_start text not null default '',
  garage_end text not null default '',
  network_supplier_id uuid references public.suppliers(id) on delete set null,
  attached_driver_id uuid references public.drivers(id) on delete set null,
  dco_user_id uuid references auth.users(id) on delete set null,
  config jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, duty_id)
);
create table if not exists public.duty_otps (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  duty_id uuid not null references public.duties(id) on delete cascade,
  otp_type text not null,
  otp_hash text not null,
  status text not null default 'issued',
  attempts integer not null default 0,
  expires_at timestamptz not null,
  verified_at timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);
create table if not exists public.duty_media_objects (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  duty_id uuid not null references public.duties(id) on delete cascade,
  media_type text not null,
  storage_path text not null,
  signed_url text not null default '',
  sha256 text not null default '',
  metadata jsonb not null default '{}',
  status text not null default 'pending',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);
create table if not exists public.duty_evidence_bundles (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  duty_id uuid not null references public.duties(id) on delete cascade,
  bundle_hash text not null,
  content jsonb not null default '{}',
  storage_path text not null,
  signed_url text not null default '',
  status text not null default 'immutable',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, duty_id, bundle_hash)
);
create or replace function public.prevent_duty_evidence_bundle_mutation()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  raise exception 'Duty evidence bundles are immutable; create a new bundle version';
end;
$$;
do $$ begin
  create trigger duty_evidence_bundles_immutable before update or delete on public.duty_evidence_bundles
  for each row execute function public.prevent_duty_evidence_bundle_mutation();
exception when duplicate_object then null; end $$;

create table if not exists public.duty_slip_documents (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  duty_id uuid not null references public.duties(id) on delete cascade,
  document_type text not null default 'combined_duty_slip',
  content jsonb not null default '{}',
  storage_path text not null default '',
  download_token_hash text not null default '',
  status text not null default 'ready',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, duty_id, document_type)
);
create table if not exists public.duty_adjustments (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  duty_id uuid not null references public.duties(id) on delete cascade,
  adjustment_type text not null check (adjustment_type in ('credit','debit')),
  amount_paise bigint not null check (amount_paise > 0),
  reason text not null,
  evidence jsonb not null default '{}',
  status text not null default 'pending',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  approved_by uuid references auth.users(id) on delete set null,
  approved_at timestamptz
);
create table if not exists public.duty_closure_jobs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  duty_id uuid not null references public.duties(id) on delete cascade,
  job_type text not null,
  status text not null default 'queued',
  attempts integer not null default 0,
  notification_attempts integer not null default 0,
  next_run_at timestamptz not null,
  next_notification_at timestamptz,
  last_error text not null default '',
  payload jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_enterprise_groups_org on public.enterprise_groups(organization_id,group_type,status);
create index if not exists idx_enterprise_usage_period on public.enterprise_usage_events(organization_id,period_key,feature_key);
create index if not exists idx_passenger_portal_hash on public.passenger_portal_tokens(token_hash,status,expires_at);
create index if not exists idx_enterprise_quotes_booking on public.enterprise_booking_quotes(organization_id,booking_id,created_at desc);
create unique index if not exists ux_enterprise_quotes_idempotency on public.enterprise_booking_quotes(organization_id,idempotency_key) where idempotency_key is not null;
create index if not exists idx_allotment_requests_booking on public.allotment_requests(organization_id,booking_id,status);
create unique index if not exists ux_allotment_requests_idempotency on public.allotment_requests(organization_id,idempotency_key) where idempotency_key is not null;
create index if not exists idx_execution_profiles_duty on public.duty_execution_profiles(organization_id,duty_id);
create index if not exists idx_duty_otps_duty on public.duty_otps(organization_id,duty_id,otp_type,status);
create index if not exists idx_duty_media_duty on public.duty_media_objects(organization_id,duty_id,created_at desc);
create index if not exists idx_duty_evidence_bundles_duty on public.duty_evidence_bundles(organization_id,duty_id,created_at desc);
create index if not exists idx_duty_closure_jobs_due on public.duty_closure_jobs(organization_id,status,next_run_at);

create or replace function public.enforce_enterprise_billing_items()
returns trigger language plpgsql security definer set search_path = public as $$
declare missing_code text;
begin
  select item.code into missing_code
    from public.enterprise_billing_items item
   where item.organization_id = new.organization_id and item.status = 'active' and item.mandatory
     and not exists (select 1 from jsonb_array_elements(coalesce(new.payload->'billing_items','[]'::jsonb)) value where value->>'code' = item.code or value->>'id' = item.id::text)
   limit 1;
  if missing_code is not null then raise exception 'Mandatory billing item is missing: %', missing_code; end if;
  return new;
end;
$$;
do $$ begin
  create trigger trg_enterprise_billing_item_guard before insert or update on public.duty_closures for each row execute function public.enforce_enterprise_billing_items();
exception when duplicate_object then null; end $$;

-- Keep timestamps consistent with the shared foundation trigger.
do $$ begin
  create trigger enterprise_groups_updated_at before update on public.enterprise_groups for each row execute function public.set_updated_at();
  create trigger enterprise_companies_updated_at before update on public.enterprise_companies for each row execute function public.set_updated_at();
  create trigger enterprise_billing_profiles_updated_at before update on public.enterprise_billing_profiles for each row execute function public.set_updated_at();
  create trigger enterprise_bank_accounts_updated_at before update on public.enterprise_bank_accounts for each row execute function public.set_updated_at();
  create trigger enterprise_tax_entities_updated_at before update on public.enterprise_tax_entities for each row execute function public.set_updated_at();
  create trigger enterprise_billing_items_updated_at before update on public.enterprise_billing_items for each row execute function public.set_updated_at();
  create trigger enterprise_sso_configs_updated_at before update on public.enterprise_sso_configs for each row execute function public.set_updated_at();
  create trigger booking_control_rules_updated_at before update on public.booking_control_rules for each row execute function public.set_updated_at();
  create trigger allotment_requests_updated_at before update on public.allotment_requests for each row execute function public.set_updated_at();
  create trigger duty_execution_profiles_updated_at before update on public.duty_execution_profiles for each row execute function public.set_updated_at();
  create trigger duty_closure_jobs_updated_at before update on public.duty_closure_jobs for each row execute function public.set_updated_at();
exception when duplicate_object then null; end $$;

alter table public.enterprise_groups enable row level security;
alter table public.enterprise_group_members enable row level security;
alter table public.enterprise_companies enable row level security;
alter table public.enterprise_bank_accounts enable row level security;
alter table public.enterprise_tax_entities enable row level security;
alter table public.enterprise_billing_items enable row level security;
alter table public.enterprise_custom_fields enable row level security;
alter table public.enterprise_company_profiles enable row level security;
alter table public.enterprise_plan_subscriptions enable row level security;
alter table public.enterprise_usage_events enable row level security;
alter table public.enterprise_sso_configs enable row level security;
alter table public.passenger_portal_tokens enable row level security;
alter table public.booking_control_rules enable row level security;
alter table public.enterprise_booking_quotes enable row level security;
alter table public.allotment_requests enable row level security;
alter table public.allotment_responses enable row level security;
alter table public.allotment_exceptions enable row level security;
alter table public.duty_execution_profiles enable row level security;
alter table public.duty_otps enable row level security;
alter table public.duty_media_objects enable row level security;
alter table public.duty_evidence_bundles enable row level security;
alter table public.duty_slip_documents enable row level security;
alter table public.duty_adjustments enable row level security;
alter table public.duty_closure_jobs enable row level security;

do $$
declare t text; p text;
begin
  foreach t in array array['enterprise_groups','enterprise_group_members','enterprise_companies','enterprise_billing_profiles','enterprise_bank_accounts','enterprise_tax_entities','enterprise_billing_items','enterprise_custom_fields','enterprise_company_profiles','enterprise_plan_subscriptions','enterprise_usage_events','enterprise_sso_configs','passenger_portal_tokens','booking_control_rules','enterprise_booking_quotes','allotment_requests','allotment_responses','allotment_exceptions','duty_execution_profiles','duty_otps','duty_media_objects','duty_evidence_bundles','duty_slip_documents','duty_adjustments','duty_closure_jobs'] loop
    p := case
      when t in ('enterprise_booking_quotes','allotment_requests','allotment_responses','allotment_exceptions') then 'enterprise.booking'
      when t in ('duty_execution_profiles','duty_otps','duty_media_objects','duty_evidence_bundles','duty_slip_documents','duty_adjustments','duty_closure_jobs') then 'enterprise.evidence'
      else 'enterprise.manage'
    end;
    execute format('create policy %I_member_select on public.%I for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user())', t || '_member_select', t);
    execute format('create policy %I_manage on public.%I for all to authenticated using (public.has_permission(organization_id,%L) or public.is_platform_user()) with check (public.has_permission(organization_id,%L) or public.is_platform_user())', t || '_manage', t, p, p);
  end loop;
exception when duplicate_object then null;
end $$;

grant select, insert, update on public.enterprise_groups, public.enterprise_group_members, public.enterprise_companies, public.enterprise_billing_profiles, public.enterprise_bank_accounts, public.enterprise_tax_entities, public.enterprise_billing_items, public.enterprise_custom_fields, public.enterprise_company_profiles, public.enterprise_plan_subscriptions, public.enterprise_usage_events, public.enterprise_sso_configs, public.passenger_portal_tokens, public.booking_control_rules, public.enterprise_booking_quotes, public.allotment_requests, public.allotment_responses, public.allotment_exceptions, public.duty_execution_profiles, public.duty_otps, public.duty_media_objects, public.duty_evidence_bundles, public.duty_slip_documents, public.duty_adjustments, public.duty_closure_jobs to authenticated;

create or replace function public.calculate_enterprise_booking_quote(
  p_organization_id uuid, p_booking_id uuid, p_actor uuid,
  p_duration_minutes integer, p_distance_km numeric, p_included_km numeric default 0, p_idempotency_key text default null
) returns jsonb language plpgsql security definer set search_path = public as $$
declare r public.booking_control_rules; q public.enterprise_booking_quotes; replay public.enterprise_booking_quotes; extra_blocks integer; extra_km numeric; km_total bigint; time_total bigint; total bigint;
begin
  if not (public.has_permission(p_organization_id,'enterprise.booking') or public.is_platform_user()) then raise exception 'enterprise.booking permission required'; end if;
  if p_idempotency_key is not null then select * into replay from public.enterprise_booking_quotes where organization_id=p_organization_id and idempotency_key=p_idempotency_key limit 1; if replay.id is not null then return jsonb_build_object('ok',true,'item',to_jsonb(replay),'idempotent_replay',true); end if; end if;
  if not exists (select 1 from public.bookings where id=p_booking_id and organization_id=p_organization_id) then raise exception 'Booking is outside the tenant'; end if;
  select * into r from public.booking_control_rules where organization_id=p_organization_id and status='active' order by updated_at desc limit 1;
  extra_km := greatest(coalesce(p_distance_km,0)-coalesce(p_included_km,0),0);
  extra_blocks := greatest(ceil((greatest(coalesce(p_duration_minutes,0)-coalesce(r.package_minutes,30),0))::numeric/30),0);
  km_total := round(extra_km * coalesce(r.extra_km_paise,0)); time_total := extra_blocks * coalesce(r.extra_half_hour_paise,0); total := coalesce(r.package_base_paise,0)+km_total+time_total;
  insert into public.enterprise_booking_quotes(organization_id,booking_id,rule_id,duration_minutes,distance_km,package_minutes,base_paise,extra_km_paise,extra_time_paise,total_paise,breakdown,idempotency_key,created_by)
  values(p_organization_id,p_booking_id,r.id,coalesce(p_duration_minutes,0),coalesce(p_distance_km,0),coalesce(r.package_minutes,30),coalesce(r.package_base_paise,0),km_total,time_total,total,jsonb_build_object('extra_km',extra_km,'extra_blocks',extra_blocks,'included_km',coalesce(p_included_km,0),'automatic_switch',coalesce(r.auto_switch,'{}'::jsonb)),p_idempotency_key,p_actor) returning * into q;
  insert into public.audit_events(organization_id,actor_id,action,entity_type,entity_id,after_data) values(p_organization_id,p_actor,'enterprise.booking_quote.created','booking_quote',q.id,to_jsonb(q));
  return jsonb_build_object('ok',true,'item',to_jsonb(q));
end;
$$;
grant execute on function public.calculate_enterprise_booking_quote(uuid,uuid,uuid,integer,numeric,numeric,text) to authenticated;

create or replace function public.process_enterprise_closure_jobs(p_organization_id uuid, p_limit integer default 100)
returns jsonb language plpgsql security definer set search_path = public as $$
declare count_value integer; approval_count integer := 0; retry_count integer := 0;
begin
  if not (public.has_permission(p_organization_id,'enterprise.evidence') or public.is_platform_user()) then raise exception 'enterprise.evidence permission required'; end if;
  -- Process SMS/closure jobs and retry notification work in bounded batches.
  update public.duty_closure_jobs set status='processing', attempts=attempts+1, updated_at=now() where id in (select id from public.duty_closure_jobs where organization_id=p_organization_id and status='queued' and next_run_at <= now() order by next_run_at limit greatest(p_limit,1));
  get diagnostics count_value = row_count;
  update public.duty_closure_jobs set notification_attempts=notification_attempts+1, next_notification_at=now()+interval '15 minutes', updated_at=now() where organization_id=p_organization_id and status in ('queued','processing') and next_notification_at is not null and next_notification_at <= now();
  get diagnostics retry_count = row_count;
  -- The corporate approval contract owns the 48-hour deadline. This worker
  -- invokes the same transition so scheduled production runs and dashboard
  -- recovery runs cannot diverge.
  update public.corporate_duty_slip_approvals set status='auto_approved', decision_reason='48_hour_expiry_auto_approval', decided_at=now()
   where organization_id=p_organization_id and status='pending' and auto_approve_at <= now();
  get diagnostics approval_count = row_count;
  if approval_count > 0 then
    insert into public.notification_events(organization_id,event_type,payload)
    values(p_organization_id,'duty_slip.auto_approved',jsonb_build_object('count',approval_count,'worker','enterprise-closure-worker','reason','48_hour_expiry_auto_approval'));
  end if;
  return jsonb_build_object('ok',true,'processed',count_value,'notification_retries',retry_count,'auto_approved',approval_count,'worker','enterprise-closure-worker','approval_window_hours',48);
end;
$$;
grant execute on function public.process_enterprise_closure_jobs(uuid,integer) to authenticated;

insert into public.audit_events(organization_id,actor_id,action,entity_type,entity_id,after_data)
select o.id,o.owner_user_id,'enterprise_controls.migration','migration',null,jsonb_build_object('tables',24,'passenger_api',true,'booking_controls',true,'duty_evidence',true)
from public.organizations o where o.owner_user_id is not null;
