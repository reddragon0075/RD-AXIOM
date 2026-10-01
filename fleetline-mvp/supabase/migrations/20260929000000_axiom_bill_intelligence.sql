-- Axiom Fleet bill intelligence and auditable auto-posting foundation.
-- Extraction is a derived, reviewable layer. Canonical vehicles, supplier bills,
-- costs, duties and audit rows remain the source of truth for production writes.

insert into public.permissions(key, description) values
  ('bill_intelligence.read', 'Read tenant-scoped extracted bills, confidence and vehicle timelines'),
  ('bill_intelligence.upload', 'Upload or submit bill evidence for extraction'),
  ('bill_intelligence.review', 'Review, post, reject or reverse extracted bill evidence')
on conflict (key) do nothing;

insert into public.role_permissions(role, permission_key)
select r.role, p.key
from (values
  ('vendor_owner'::public.membership_role), ('vendor_ops'::public.membership_role),
  ('vendor_dispatch'::public.membership_role), ('corporate_admin'::public.membership_role),
  ('corporate_travel'::public.membership_role)
) r(role)
cross join public.permissions p
where p.key in ('bill_intelligence.read', 'bill_intelligence.upload', 'bill_intelligence.review')
on conflict do nothing;
insert into public.role_permissions(role, permission_key)
select 'driver'::public.membership_role, p.key
from public.permissions p
where p.key in ('bill_intelligence.read', 'bill_intelligence.upload')
on conflict do nothing;

alter table public.vehicles add column if not exists current_odometer_km numeric(14,3) not null default 0;
alter table public.vehicles add column if not exists odometer_updated_at timestamptz;
alter table public.vehicles add column if not exists insurance_policy_number text not null default '';
alter table public.vehicles add column if not exists next_service_due_km numeric(14,3);
alter table public.vehicles add column if not exists next_service_due_date date;

create table if not exists public.bill_intelligence_records (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  source text not null default 'vendor_portal',
  filename text not null default '',
  content_type text not null default 'application/octet-stream',
  storage_reference text not null default '',
  file_sha256 text not null default '',
  ocr_text text not null default '',
  bill_type text not null default 'other' check (bill_type in ('fuel','maintenance','toll','insurance','tyre','other')),
  vehicle_id uuid references public.vehicles(id) on delete set null,
  duty_id uuid references public.duties(id) on delete set null,
  supplier_id uuid references public.suppliers(id) on delete set null,
  status text not null default 'needs_review' check (status in ('draft','needs_review','posted','rejected','reversed')),
  extracted jsonb not null default '{}'::jsonb,
  confidence jsonb not null default '{}'::jsonb,
  validation jsonb not null default '{}'::jsonb,
  posting jsonb not null default '{}'::jsonb,
  review_note text not null default '',
  idempotency_key text,
  created_by uuid references auth.users(id) on delete set null,
  reviewed_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  posted_at timestamptz,
  unique (organization_id, idempotency_key)
);
create index if not exists idx_bill_intelligence_records_org_status on public.bill_intelligence_records(organization_id, status, created_at desc);
create index if not exists idx_bill_intelligence_records_org_vehicle on public.bill_intelligence_records(organization_id, vehicle_id, created_at desc);

create table if not exists public.bill_intelligence_postings (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  bill_id uuid not null references public.bill_intelligence_records(id) on delete restrict,
  posting_type text not null,
  entity_type text not null,
  entity_id uuid not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (bill_id, posting_type, entity_id)
);
create index if not exists idx_bill_intelligence_postings_bill on public.bill_intelligence_postings(organization_id, bill_id, created_at);

create table if not exists public.bill_intelligence_fuel_entries (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  bill_id uuid not null references public.bill_intelligence_records(id) on delete restrict,
  vehicle_id uuid not null references public.vehicles(id) on delete restrict,
  duty_id uuid references public.duties(id) on delete set null,
  fuel_type text not null default '',
  quantity numeric(14,3) not null default 0,
  unit text not null default 'L',
  rate_per_unit numeric(14,3),
  amount_paise bigint not null default 0,
  odometer_km numeric(14,3),
  station text not null default '',
  invoice_date date,
  mileage_km_per_unit numeric(14,4),
  anomaly_code text not null default '',
  status text not null default 'posted' check (status in ('posted','reversed')),
  created_at timestamptz not null default now(),
  reversed_at timestamptz
);
create index if not exists idx_bill_intelligence_fuel_vehicle on public.bill_intelligence_fuel_entries(organization_id, vehicle_id, created_at desc);

create table if not exists public.bill_intelligence_timeline (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  vehicle_id uuid not null references public.vehicles(id) on delete restrict,
  bill_id uuid references public.bill_intelligence_records(id) on delete set null,
  event_type text not null,
  source text not null default 'ocr_bill',
  payload jsonb not null default '{}'::jsonb,
  event_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null
);
create index if not exists idx_bill_intelligence_timeline_vehicle on public.bill_intelligence_timeline(organization_id, vehicle_id, event_at desc);

alter table public.bill_intelligence_records enable row level security;
alter table public.bill_intelligence_postings enable row level security;
alter table public.bill_intelligence_fuel_entries enable row level security;
alter table public.bill_intelligence_timeline enable row level security;

drop policy if exists bill_intelligence_records_select on public.bill_intelligence_records;
drop policy if exists bill_intelligence_records_upload on public.bill_intelligence_records;
drop policy if exists bill_intelligence_records_review on public.bill_intelligence_records;
create policy bill_intelligence_records_select on public.bill_intelligence_records for select to authenticated using ((organization_id is not null and public.has_permission(organization_id, 'bill_intelligence.read')) or public.is_platform_user());
create policy bill_intelligence_records_upload on public.bill_intelligence_records for insert to authenticated with check ((organization_id is not null and public.has_permission(organization_id, 'bill_intelligence.upload')) or public.is_platform_user());
create policy bill_intelligence_records_review on public.bill_intelligence_records for update to authenticated using ((organization_id is not null and public.has_permission(organization_id, 'bill_intelligence.review')) or public.is_platform_user()) with check ((organization_id is not null and public.has_permission(organization_id, 'bill_intelligence.review')) or public.is_platform_user());

do $$
declare t text;
begin
  foreach t in array array['bill_intelligence_postings','bill_intelligence_fuel_entries','bill_intelligence_timeline'] loop
    execute format('drop policy if exists %I on public.%I', t || '_select', t);
    execute format('drop policy if exists %I on public.%I', t || '_review', t);
    execute format('create policy %I on public.%I for select to authenticated using ((organization_id is not null and public.has_permission(organization_id, %L)) or public.is_platform_user())', t || '_select', t, 'bill_intelligence.read');
    execute format('create policy %I on public.%I for all to authenticated using ((organization_id is not null and public.has_permission(organization_id, %L)) or public.is_platform_user()) with check ((organization_id is not null and public.has_permission(organization_id, %L)) or public.is_platform_user())', t || '_review', t, 'bill_intelligence.review', 'bill_intelligence.review');
  end loop;
end $$;

grant select, insert, update on public.bill_intelligence_records to authenticated;
grant select, insert, update on public.bill_intelligence_postings, public.bill_intelligence_fuel_entries, public.bill_intelligence_timeline to authenticated;

do $$
declare t text;
begin
  if to_regprocedure('public.p0_audit_row()') is not null then
    foreach t in array array['bill_intelligence_records','bill_intelligence_postings','bill_intelligence_fuel_entries','bill_intelligence_timeline'] loop
      execute format('drop trigger if exists %I on public.%I', t || '_audit', t);
      execute format('create trigger %I after insert or update or delete on public.%I for each row execute function public.p0_audit_row()', t || '_audit', t);
    end loop;
  end if;
end $$;

create or replace function public.append_bill_intelligence_audit(
  p_organization_id uuid,
  p_action text,
  p_entity_type text,
  p_entity_id uuid,
  p_after_data jsonb default null,
  p_metadata jsonb default '{}'::jsonb
)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare audit_id uuid;
begin
  if not public.has_permission(p_organization_id, 'bill_intelligence.review') and not public.is_platform_user() then
    raise exception 'bill_intelligence.review permission required';
  end if;
  insert into public.audit_events(organization_id, actor_id, action, entity_type, entity_id, after_data, metadata, retention_class)
  values (p_organization_id, auth.uid(), p_action, p_entity_type, p_entity_id, p_after_data, p_metadata, 'financial')
  returning id into audit_id;
  return audit_id;
end;
$$;
grant execute on function public.append_bill_intelligence_audit(uuid, text, text, uuid, jsonb, jsonb) to authenticated;

comment on table public.bill_intelligence_records is 'OCR/vision extraction with field confidence, validation, source hash and human review state';
comment on table public.bill_intelligence_postings is 'Immutable map from a confirmed bill to canonical supplier, cost, fuel and vehicle updates';
comment on table public.bill_intelligence_fuel_entries is 'Auditable fuel readings and mileage anomalies produced by confirmed bill evidence';
comment on table public.bill_intelligence_timeline is 'Vehicle timeline events with OCR/manual/app provenance';
