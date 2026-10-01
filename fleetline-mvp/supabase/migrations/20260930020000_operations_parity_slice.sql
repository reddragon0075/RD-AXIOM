-- Axiom Fleet operational parity slice.
-- Batch booking intake, deterministic availability/allotment and a unified
-- duty-closure/evidence boundary. All records stay tenant scoped.

insert into public.permissions(key, description) values
  ('operations.booking_batch', 'Create and review bulk, itinerary and monthly booking batches'),
  ('operations.availability', 'Evaluate vehicle and driver availability'),
  ('operations.allot', 'Allot an eligible vehicle and driver to a booking'),
  ('operations.close', 'Submit a complete duty closure and evidence bundle')
on conflict (key) do nothing;

create table if not exists public.booking_batches (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  mode text not null check (mode in ('bulk','itinerary','monthly')),
  status text not null default 'processing' check (status in ('processing','completed','partial','failed','cancelled')),
  requested_count integer not null default 0 check (requested_count between 0 and 500),
  generated_count integer not null default 0 check (generated_count >= 0),
  failed_count integer not null default 0 check (failed_count >= 0),
  start_at timestamptz,
  end_at timestamptz,
  idempotency_key text,
  payload jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);

create table if not exists public.booking_batch_rows (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  batch_id uuid not null references public.booking_batches(id) on delete cascade,
  row_number integer not null check (row_number > 0),
  status text not null default 'pending' check (status in ('pending','created','error')),
  source jsonb not null default '{}'::jsonb,
  booking_id uuid references public.bookings(id) on delete set null,
  error_code text,
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (batch_id, row_number)
);

create table if not exists public.allotment_decisions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  booking_id uuid not null references public.bookings(id) on delete cascade,
  attempt integer not null default 1 check (attempt > 0),
  status text not null check (status in ('assigned','blocked','released')),
  supplier_id uuid references public.suppliers(id) on delete set null,
  driver_id uuid references public.drivers(id) on delete set null,
  vehicle_id uuid references public.vehicles(id) on delete set null,
  score integer not null default 0,
  rationale jsonb not null default '{}'::jsonb,
  idempotency_key text,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, booking_id, idempotency_key)
);

create table if not exists public.duty_closures (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  duty_id uuid not null references public.duties(id) on delete cascade,
  status text not null default 'submitted' check (status in ('submitted','completed','disputed','rejected')),
  closure_version integer not null default 1 check (closure_version > 0),
  payload jsonb not null default '{}'::jsonb,
  completeness jsonb not null default '{}'::jsonb,
  submitted_by uuid references auth.users(id) on delete set null,
  submitted_at timestamptz not null default now(),
  approved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, duty_id, closure_version)
);

create table if not exists public.closure_evidence (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  closure_id uuid not null references public.duty_closures(id) on delete cascade,
  duty_id uuid not null references public.duties(id) on delete cascade,
  evidence_type text not null,
  storage_path text not null default '',
  sha256 text not null default '',
  metadata jsonb not null default '{}'::jsonb,
  required boolean not null default false,
  captured_by uuid references auth.users(id) on delete set null,
  captured_at timestamptz not null default now(),
  unique (organization_id, duty_id, evidence_type, sha256)
);

create index if not exists idx_booking_batches_org_created on public.booking_batches(organization_id, created_at desc);
create index if not exists idx_booking_batch_rows_batch on public.booking_batch_rows(organization_id, batch_id, row_number);
create index if not exists idx_allotment_decisions_booking on public.allotment_decisions(organization_id, booking_id, created_at desc);
create index if not exists idx_duty_closures_duty on public.duty_closures(organization_id, duty_id, closure_version desc);
create index if not exists idx_closure_evidence_duty on public.closure_evidence(organization_id, duty_id, captured_at desc);

alter table public.booking_batches enable row level security;
alter table public.booking_batch_rows enable row level security;
alter table public.allotment_decisions enable row level security;
alter table public.duty_closures enable row level security;
alter table public.closure_evidence enable row level security;

do $$
begin
  create policy booking_batches_member_read on public.booking_batches for select to authenticated
    using (public.is_org_member(organization_id) or public.is_platform_user());
  create policy booking_batches_write on public.booking_batches for all to authenticated
    using (public.has_permission(organization_id, 'bookings.write') or public.is_platform_user())
    with check (public.has_permission(organization_id, 'bookings.write') or public.is_platform_user());
  create policy booking_batch_rows_member_read on public.booking_batch_rows for select to authenticated
    using (public.is_org_member(organization_id) or public.is_platform_user());
  create policy booking_batch_rows_write on public.booking_batch_rows for all to authenticated
    using (public.has_permission(organization_id, 'bookings.write') or public.is_platform_user())
    with check (public.has_permission(organization_id, 'bookings.write') or public.is_platform_user());
  create policy allotment_decisions_member_read on public.allotment_decisions for select to authenticated
    using (public.is_org_member(organization_id) or public.is_platform_user());
  create policy allotment_decisions_write on public.allotment_decisions for all to authenticated
    using (public.has_permission(organization_id, 'duties.write') or public.has_permission(organization_id, 'bookings.write') or public.is_platform_user())
    with check (public.has_permission(organization_id, 'duties.write') or public.has_permission(organization_id, 'bookings.write') or public.is_platform_user());
  create policy duty_closures_member_read on public.duty_closures for select to authenticated
    using (public.is_org_member(organization_id) or public.is_platform_user());
  create policy duty_closures_write on public.duty_closures for all to authenticated
    using (public.has_permission(organization_id, 'duties.write') or exists (select 1 from public.duties d join public.drivers dr on dr.id = d.driver_id where d.id = duty_id and dr.user_id = auth.uid()) or public.is_platform_user())
    with check (public.has_permission(organization_id, 'duties.write') or exists (select 1 from public.duties d join public.drivers dr on dr.id = d.driver_id where d.id = duty_id and dr.user_id = auth.uid()) or public.is_platform_user());
  create policy closure_evidence_member_read on public.closure_evidence for select to authenticated
    using (public.is_org_member(organization_id) or public.is_platform_user());
  create policy closure_evidence_write on public.closure_evidence for all to authenticated
    using (public.has_permission(organization_id, 'duties.write') or exists (select 1 from public.duties d join public.drivers dr on dr.id = d.driver_id where d.id = duty_id and dr.user_id = auth.uid()) or public.is_platform_user())
    with check (public.has_permission(organization_id, 'duties.write') or exists (select 1 from public.duties d join public.drivers dr on dr.id = d.driver_id where d.id = duty_id and dr.user_id = auth.uid()) or public.is_platform_user());
exception when duplicate_object then null;
end $$;

grant select, insert, update on
  public.booking_batches,
  public.booking_batch_rows,
  public.allotment_decisions,
  public.duty_closures,
  public.closure_evidence
  to authenticated;

comment on table public.booking_batches is 'Bulk, itinerary and monthly booking intake with row-level outcomes';
comment on table public.allotment_decisions is 'Deterministic supplier/driver/vehicle selection evidence';
comment on table public.duty_closures is 'Unified dashboard, driver, SMS and Network duty closure evidence';
comment on table public.closure_evidence is 'Closure attachments, signatures, slips and billable proof references';

-- Driver-safe closure RPC. It keeps the final transition, odometers,
-- completeness calculation and evidence rows in one transaction instead of
-- requiring a driver token to receive direct update rights on duties.
create or replace function public.submit_duty_closure(
  p_duty_id uuid,
  p_start_odometer integer,
  p_end_odometer integer,
  p_payload jsonb default '{}'::jsonb,
  p_required_evidence text[] default '{}',
  p_evidence jsonb default '[]'::jsonb,
  p_idempotency_key text default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  duty_row public.duties;
  closure_row public.duty_closures;
  next_version integer;
  missing text[] := '{}';
  evidence_count integer := jsonb_array_length(coalesce(p_evidence, '[]'::jsonb));
  evidence_row jsonb;
  evidence_type text;
  completeness jsonb;
begin
  select * into duty_row from public.duties where id = p_duty_id for update;
  if duty_row.id is null then raise exception 'Duty not found'; end if;
  if not (
    public.has_permission(duty_row.organization_id, 'duties.write')
    or exists (select 1 from public.drivers dr where dr.id = duty_row.driver_id and dr.user_id = auth.uid())
    or public.is_platform_user()
  ) then
    raise exception 'Duty closure is not permitted';
  end if;
  if p_start_odometer is null or p_end_odometer is null or p_start_odometer < 0 or p_end_odometer < p_start_odometer then
    raise exception 'Odometer readings are invalid';
  end if;
  if p_idempotency_key is not null then
    select * into closure_row
      from public.duty_closures
     where organization_id = duty_row.organization_id
       and duty_id = p_duty_id
       and payload->>'idempotency_key' = p_idempotency_key
     order by closure_version desc
     limit 1;
    if closure_row.id is not null then
      return jsonb_build_object('closure', to_jsonb(closure_row), 'idempotent', true);
    end if;
  end if;

  select coalesce(array_agg(required_value), '{}') into missing
    from unnest(coalesce(p_required_evidence, '{}')) as required_value
   where not exists (
     select 1
       from jsonb_array_elements(coalesce(p_evidence, '[]'::jsonb)) as evidence(value)
      where lower(coalesce(evidence.value->>'evidence_type', evidence.value->>'type', '')) = lower(required_value)
   );
  if coalesce(array_length(missing, 1), 0) > 0 then
    raise exception 'Required closure evidence is missing: %', array_to_string(missing, ',');
  end if;

  select coalesce(max(closure_version), 0) + 1 into next_version
    from public.duty_closures
   where organization_id = duty_row.organization_id and duty_id = p_duty_id;
  completeness := jsonb_build_object(
    'start_odometer', true,
    'end_odometer', true,
    'required_evidence', to_jsonb(coalesce(p_required_evidence, '{}')),
    'missing_evidence', to_jsonb(coalesce(missing, '{}')),
    'evidence_count', evidence_count,
    'complete', true
  );
  insert into public.duty_closures(
    organization_id, duty_id, status, closure_version, payload, completeness,
    submitted_by, submitted_at, created_at, updated_at
  ) values (
    duty_row.organization_id, p_duty_id, 'completed', next_version,
    coalesce(p_payload, '{}'::jsonb) || jsonb_build_object('start_odometer', p_start_odometer, 'end_odometer', p_end_odometer, 'idempotency_key', p_idempotency_key),
    completeness, auth.uid(), now(), now(), now()
  ) returning * into closure_row;

  for evidence_row in select value from jsonb_array_elements(coalesce(p_evidence, '[]'::jsonb)) loop
    evidence_type := lower(coalesce(evidence_row->>'evidence_type', evidence_row->>'type', 'other'));
    insert into public.closure_evidence(
      organization_id, closure_id, duty_id, evidence_type, storage_path,
      sha256, metadata, required, captured_by, captured_at
    ) values (
      duty_row.organization_id, closure_row.id, p_duty_id, evidence_type,
      coalesce(evidence_row->>'storage_path', ''),
      coalesce(evidence_row->>'sha256', ''),
      coalesce(evidence_row->'metadata', '{}'::jsonb),
      evidence_type = any(coalesce(p_required_evidence, '{}')),
      auth.uid(), coalesce(nullif(evidence_row->>'captured_at', '')::timestamptz, now())
    ) on conflict (organization_id, duty_id, evidence_type, sha256) do nothing;
  end loop;

  update public.duties
     set status = 'completed',
         start_odometer = p_start_odometer,
         end_odometer = p_end_odometer,
         completed_at = coalesce(completed_at, now()),
         updated_at = now()
   where id = p_duty_id;
  insert into public.duty_events(organization_id, duty_id, event_type, source, idempotency_key, payload, created_by)
  values (duty_row.organization_id, p_duty_id, 'closed', coalesce(p_payload->>'source', 'web'), p_idempotency_key, jsonb_build_object('closure_id', closure_row.id, 'closure_version', next_version, 'completeness', completeness), auth.uid());
  insert into public.audit_events(organization_id, actor_id, action, entity_type, entity_id, metadata)
  values (duty_row.organization_id, auth.uid(), 'duty.closed', 'duty', p_duty_id, jsonb_build_object('closure_id', closure_row.id, 'closure_version', next_version, 'evidence_count', evidence_count));
  return jsonb_build_object('closure', to_jsonb(closure_row), 'duty_id', p_duty_id, 'completeness', completeness);
end;
$$;
revoke all on function public.submit_duty_closure(uuid, integer, integer, jsonb, text[], jsonb, text) from public;
grant execute on function public.submit_duty_closure(uuid, integer, integer, jsonb, text[], jsonb, text) to authenticated;
