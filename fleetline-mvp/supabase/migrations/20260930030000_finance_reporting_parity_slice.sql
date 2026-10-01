-- Axiom Fleet finance, collections and reporting parity slice.
-- Additive: it reuses invoices, invoice_lines, duties, bookings, payments and
-- report_exports from the foundation migration.

alter table public.invoices add column if not exists invoice_type text not null default 'tax';
alter table public.invoices add column if not exists company_id uuid;
alter table public.invoices add column if not exists gst_entity_id uuid;
alter table public.invoices add column if not exists letterhead_id uuid;

create table if not exists public.invoice_runs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  mode text not null check (mode in ('per_duty','monthly','cover','proforma')),
  period_start timestamptz,
  period_end timestamptz,
  status text not null default 'processing' check (status in ('processing','completed','partial','failed')),
  requested_count integer not null default 0,
  generated_count integer not null default 0,
  failed_count integer not null default 0,
  idempotency_key text,
  payload jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);

create table if not exists public.dunning_actions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  invoice_id uuid not null references public.invoices(id) on delete cascade,
  stage integer not null check (stage > 0),
  channel text not null default 'email',
  status text not null default 'queued',
  provider_reference text not null default '',
  scheduled_at timestamptz,
  sent_at timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, invoice_id, stage)
);

create table if not exists public.report_definitions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  name text not null,
  report_type text not null check (report_type in ('ageing','duty_count','vehicle_profitability','customer_summary')),
  filters jsonb not null default '{}',
  columns jsonb not null default '[]',
  status text not null default 'active',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, name)
);

create table if not exists public.export_profiles (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  name text not null,
  target text not null default 'csv' check (target in ('csv','json')),
  mapping jsonb not null default '{}',
  status text not null default 'active',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, name)
);

create index if not exists idx_invoice_runs_org_created on public.invoice_runs(organization_id, created_at desc);
create index if not exists idx_dunning_actions_org_invoice on public.dunning_actions(organization_id, invoice_id, stage);
create index if not exists idx_report_definitions_org_created on public.report_definitions(organization_id, created_at desc);
create index if not exists idx_export_profiles_org_created on public.export_profiles(organization_id, created_at desc);

alter table public.invoice_runs enable row level security;
alter table public.dunning_actions enable row level security;
alter table public.report_definitions enable row level security;
alter table public.export_profiles enable row level security;

drop policy if exists invoice_runs_member_select on public.invoice_runs;
create policy invoice_runs_member_select on public.invoice_runs for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
drop policy if exists invoice_runs_billing_write on public.invoice_runs;
create policy invoice_runs_billing_write on public.invoice_runs for all to authenticated using (public.has_permission(organization_id, 'billing.write') or public.is_platform_user()) with check (public.has_permission(organization_id, 'billing.write') or public.is_platform_user());
drop policy if exists dunning_actions_member_select on public.dunning_actions;
create policy dunning_actions_member_select on public.dunning_actions for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
drop policy if exists dunning_actions_billing_write on public.dunning_actions;
create policy dunning_actions_billing_write on public.dunning_actions for all to authenticated using (public.has_permission(organization_id, 'billing.write') or public.has_permission(organization_id, 'notifications.send') or public.is_platform_user()) with check (public.has_permission(organization_id, 'billing.write') or public.has_permission(organization_id, 'notifications.send') or public.is_platform_user());
drop policy if exists report_definitions_member_select on public.report_definitions;
create policy report_definitions_member_select on public.report_definitions for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
drop policy if exists report_definitions_reports_write on public.report_definitions;
create policy report_definitions_reports_write on public.report_definitions for all to authenticated using (public.has_permission(organization_id, 'reports.export') or public.has_permission(organization_id, 'reports.read') or public.is_platform_user()) with check (public.has_permission(organization_id, 'reports.export') or public.has_permission(organization_id, 'reports.read') or public.is_platform_user());
drop policy if exists export_profiles_member_select on public.export_profiles;
create policy export_profiles_member_select on public.export_profiles for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
drop policy if exists export_profiles_reports_write on public.export_profiles;
create policy export_profiles_reports_write on public.export_profiles for all to authenticated using (public.has_permission(organization_id, 'reports.export') or public.is_platform_user()) with check (public.has_permission(organization_id, 'reports.export') or public.is_platform_user());

create or replace function public.generate_invoice_run(
  p_organization_id uuid,
  p_actor uuid,
  p_mode text,
  p_payload jsonb default '{}',
  p_idempotency_key text default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  run_row public.invoice_runs;
  duty_row record;
  snapshot jsonb;
  subtotal bigint;
  tax bigint;
  total bigint;
  generated integer := 0;
  requested integer := 0;
  invoice_id uuid;
  invoice_number text;
  due_at timestamptz;
  period_start timestamptz;
  period_end timestamptz;
begin
  if not (public.has_permission(p_organization_id, 'billing.write') or public.is_platform_user()) then
    raise exception 'billing.write permission required';
  end if;
  if p_mode not in ('per_duty','monthly','cover','proforma') then raise exception 'unsupported invoice mode'; end if;
  if p_idempotency_key is not null then
    select * into run_row from public.invoice_runs where organization_id = p_organization_id and idempotency_key = p_idempotency_key;
    if found then return jsonb_build_object('ok', true, 'idempotent', true, 'run', to_jsonb(run_row)); end if;
  end if;
  period_start := nullif(p_payload->>'period_start','')::timestamptz;
  period_end := nullif(p_payload->>'period_end','')::timestamptz;
  due_at := nullif(p_payload->>'due_at','')::timestamptz;
  insert into public.invoice_runs(organization_id, mode, period_start, period_end, idempotency_key, payload, created_by)
  values (p_organization_id, p_mode, period_start, period_end, p_idempotency_key, coalesce(p_payload,'{}'), p_actor)
  returning * into run_row;

  for duty_row in
    select d.id, d.booking_id, b.customer_id, d.calculation_snapshot
    from public.duties d
    join public.bookings b on b.id = d.booking_id and b.organization_id = d.organization_id
    where d.organization_id = p_organization_id and d.status = 'completed'
      and not exists (select 1 from public.invoices i where i.organization_id = d.organization_id and i.duty_id = d.id)
      and (period_start is null or coalesce(d.completed_at, d.updated_at) >= period_start)
      and (period_end is null or coalesce(d.completed_at, d.updated_at) <= period_end)
      and (p_payload->'duty_ids' is null or d.id::text in (select jsonb_array_elements_text(p_payload->'duty_ids')))
      and (nullif(p_payload->>'customer_id','') is null or b.customer_id::text = p_payload->>'customer_id')
    order by coalesce(d.completed_at, d.updated_at), d.id
  loop
    requested := requested + 1;
    snapshot := coalesce(duty_row.calculation_snapshot, '{}');
    subtotal := coalesce(nullif(snapshot->>'subtotal_paise','')::bigint, 0);
    tax := coalesce(nullif(snapshot->>'tax_paise','')::bigint, 0);
    total := coalesce(nullif(snapshot->>'total_paise','')::bigint, subtotal + tax);
    if total <= 0 then continue; end if;
    invoice_number := coalesce(nullif(p_payload->>'invoice_number',''), 'INV-' || to_char(current_date, 'YYYY') || '-' || lpad((select count(*) + 1 from public.invoices where organization_id = p_organization_id)::text, 4, '0'));
    if p_mode = 'per_duty' then invoice_number := invoice_number || '-' || right(duty_row.id::text, 8); end if;
    insert into public.invoices(organization_id, customer_id, booking_id, invoice_number, status, subtotal_paise, tax_paise, total_paise, invoice_type, due_at, immutable_snapshot, created_by, issued_at)
    values (p_organization_id, duty_row.customer_id, duty_row.booking_id, invoice_number, 'draft', subtotal, tax, total, p_mode, due_at, snapshot, p_actor, case when p_mode = 'proforma' then null else now() end)
    returning id into invoice_id;
    insert into public.invoice_lines(invoice_id, description, quantity, unit_paise, amount_paise, source_entity_type, source_entity_id)
    select invoice_id, coalesce(line->>'label','Duty service'), coalesce(nullif(line->>'quantity','')::numeric, 1), coalesce(nullif(line->>'unit_paise','')::bigint,0), coalesce(nullif(line->>'amount_paise','')::bigint,0), 'duty', duty_row.id
    from jsonb_array_elements(coalesce(snapshot->'lines','[]'::jsonb)) line;
    if not found then insert into public.invoice_lines(invoice_id, description, quantity, unit_paise, amount_paise, source_entity_type, source_entity_id) values (invoice_id, 'Duty service', 1, total, total, 'duty', duty_row.id); end if;
    generated := generated + 1;
    if p_mode <> 'per_duty' then exit; end if;
  end loop;
  update public.invoice_runs set requested_count = requested, generated_count = generated, failed_count = greatest(requested-generated,0), status = case when generated = 0 then 'failed' when requested > generated then 'partial' else 'completed' end, updated_at = now() where id = run_row.id returning * into run_row;
  return jsonb_build_object('ok', true, 'run', to_jsonb(run_row), 'generated_count', generated);
end;
$$;

grant execute on function public.generate_invoice_run(uuid, uuid, text, jsonb, text) to authenticated;

create or replace function public.run_dunning_run(
  p_organization_id uuid,
  p_actor uuid,
  p_channel text default 'email'
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  invoice_row record;
  next_stage integer;
  action_count integer := 0;
  action_row public.dunning_actions;
begin
  if not (public.has_permission(p_organization_id, 'billing.write') or public.has_permission(p_organization_id, 'notifications.send') or public.is_platform_user()) then raise exception 'billing or notification permission required'; end if;
  for invoice_row in select i.* from public.invoices i where i.organization_id = p_organization_id and i.status in ('issued','sent','partially_paid') and i.due_at is not null and i.due_at < now() order by i.due_at loop
    select coalesce(max(stage),0)+1 into next_stage from public.dunning_actions where organization_id = p_organization_id and invoice_id = invoice_row.id;
    insert into public.dunning_actions(organization_id, invoice_id, stage, channel, status, scheduled_at, sent_at, created_by)
    values (p_organization_id, invoice_row.id, next_stage, coalesce(nullif(p_channel,''),'email'), 'queued', now(), now(), p_actor)
    on conflict (organization_id, invoice_id, stage) do nothing returning * into action_row;
    if found then action_count := action_count + 1; end if;
  end loop;
  return jsonb_build_object('ok', true, 'processed', action_count, 'run_at', now());
end;
$$;

grant execute on function public.run_dunning_run(uuid, uuid, text) to authenticated;

insert into public.audit_events(organization_id, actor_id, action, entity_type, entity_id, after_data)
select o.id, o.owner_user_id, 'finance_reporting_parity.migration', 'migration', null, jsonb_build_object('invoice_runs', true, 'dunning_actions', true)
from public.organizations o
where o.owner_user_id is not null;
