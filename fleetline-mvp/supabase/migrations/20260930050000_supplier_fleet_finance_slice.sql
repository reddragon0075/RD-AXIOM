-- Axiom Fleet supplier purchase and fleet-finance parity slice.
-- Reuses suppliers, duties, vehicles, drivers, supplier_bills, cost_entries
-- and payouts from the foundation migration.

create table if not exists public.purchase_orders (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  supplier_id uuid references public.suppliers(id) on delete set null,
  duty_id uuid references public.duties(id) on delete set null,
  purchase_reference text not null,
  status text not null default 'draft',
  amount_paise bigint not null default 0 check (amount_paise >= 0),
  due_at timestamptz,
  supplier_bill_id uuid references public.supplier_bills(id) on delete set null,
  metadata jsonb not null default '{}',
  idempotency_key text,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, purchase_reference),
  unique (organization_id, idempotency_key)
);
create table if not exists public.fuel_entries (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  vehicle_id uuid not null references public.vehicles(id) on delete restrict,
  duty_id uuid references public.duties(id) on delete set null,
  driver_id uuid references public.drivers(id) on delete set null,
  fuel_station text not null default '',
  fuel_type text not null,
  quantity_millilitres integer not null check (quantity_millilitres > 0),
  amount_paise bigint not null check (amount_paise > 0),
  odometer_km integer,
  receipt jsonb not null default '{}',
  status text not null default 'submitted',
  transaction_reference text not null default '',
  idempotency_key text,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);
create table if not exists public.petty_cash_entries (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  driver_id uuid references public.drivers(id) on delete set null,
  duty_id uuid references public.duties(id) on delete set null,
  direction text not null check (direction in ('credit','debit')),
  category text not null,
  amount_paise bigint not null check (amount_paise > 0),
  note text not null default '',
  status text not null default 'submitted',
  idempotency_key text,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);
create table if not exists public.driver_allowances (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  driver_id uuid not null references public.drivers(id) on delete restrict,
  duty_id uuid references public.duties(id) on delete set null,
  category text not null,
  amount_paise bigint not null check (amount_paise > 0),
  period_start date,
  period_end date,
  status text not null default 'submitted',
  evidence jsonb not null default '{}',
  idempotency_key text,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);
create table if not exists public.payroll_runs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  period_start date not null,
  period_end date not null,
  status text not null default 'draft',
  gross_paise bigint not null default 0,
  deductions_paise bigint not null default 0,
  net_paise bigint not null default 0,
  idempotency_key text,
  metadata jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, period_start, period_end),
  unique (organization_id, idempotency_key)
);
create table if not exists public.payroll_lines (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  payroll_run_id uuid not null references public.payroll_runs(id) on delete cascade,
  driver_id uuid not null references public.drivers(id) on delete restrict,
  base_paise bigint not null default 0 check (base_paise >= 0),
  allowance_paise bigint not null default 0 check (allowance_paise >= 0),
  deduction_paise bigint not null default 0 check (deduction_paise >= 0),
  gross_paise bigint not null default 0,
  net_paise bigint not null default 0,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  unique (payroll_run_id, driver_id)
);
create table if not exists public.supplier_settlements (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  supplier_id uuid references public.suppliers(id) on delete set null,
  period_start date not null,
  period_end date not null,
  bill_count integer not null default 0,
  gross_paise bigint not null default 0,
  paid_paise bigint not null default 0,
  balance_paise bigint not null default 0,
  status text not null default 'draft',
  payout_id uuid references public.payouts(id) on delete set null,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, supplier_id, period_start, period_end)
);
create index if not exists idx_purchase_orders_org_due on public.purchase_orders(organization_id, status, due_at);
create index if not exists idx_fuel_entries_org_vehicle on public.fuel_entries(organization_id, vehicle_id, created_at desc);
create index if not exists idx_petty_cash_org_created on public.petty_cash_entries(organization_id, created_at desc);
create index if not exists idx_driver_allowances_org_driver on public.driver_allowances(organization_id, driver_id, period_start, period_end);
create index if not exists idx_payroll_runs_org_period on public.payroll_runs(organization_id, period_end desc);
create index if not exists idx_payroll_lines_run on public.payroll_lines(organization_id, payroll_run_id);
create index if not exists idx_supplier_settlements_org_period on public.supplier_settlements(organization_id, period_end desc);

alter table public.purchase_orders enable row level security;
alter table public.fuel_entries enable row level security;
alter table public.petty_cash_entries enable row level security;
alter table public.driver_allowances enable row level security;
alter table public.payroll_runs enable row level security;
alter table public.payroll_lines enable row level security;
alter table public.supplier_settlements enable row level security;

do $$
begin
  create policy purchase_orders_member_select on public.purchase_orders for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
  create policy purchase_orders_billing_write on public.purchase_orders for all to authenticated using (public.has_permission(organization_id,'billing.write') or public.has_permission(organization_id,'duties.write') or public.is_platform_user()) with check (public.has_permission(organization_id,'billing.write') or public.has_permission(organization_id,'duties.write') or public.is_platform_user());
  create policy fuel_entries_member_select on public.fuel_entries for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
  create policy fuel_entries_finance_write on public.fuel_entries for all to authenticated using (public.has_permission(organization_id,'billing.write') or exists (select 1 from public.drivers d where d.id = driver_id and d.user_id = auth.uid()) or public.is_platform_user()) with check (public.has_permission(organization_id,'billing.write') or exists (select 1 from public.drivers d where d.id = driver_id and d.user_id = auth.uid()) or public.is_platform_user());
  create policy petty_cash_member_select on public.petty_cash_entries for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
  create policy petty_cash_finance_write on public.petty_cash_entries for all to authenticated using (public.has_permission(organization_id,'billing.write') or exists (select 1 from public.drivers d where d.id = driver_id and d.user_id = auth.uid()) or public.is_platform_user()) with check (public.has_permission(organization_id,'billing.write') or exists (select 1 from public.drivers d where d.id = driver_id and d.user_id = auth.uid()) or public.is_platform_user());
  create policy driver_allowances_member_select on public.driver_allowances for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
  create policy driver_allowances_billing_write on public.driver_allowances for all to authenticated using (public.has_permission(organization_id,'billing.write') or exists (select 1 from public.drivers d where d.id = driver_id and d.user_id = auth.uid()) or public.is_platform_user()) with check (public.has_permission(organization_id,'billing.write') or exists (select 1 from public.drivers d where d.id = driver_id and d.user_id = auth.uid()) or public.is_platform_user());
  create policy payroll_runs_member_select on public.payroll_runs for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
  create policy payroll_runs_billing_write on public.payroll_runs for all to authenticated using (public.has_permission(organization_id,'billing.write') or public.is_platform_user()) with check (public.has_permission(organization_id,'billing.write') or public.is_platform_user());
  create policy payroll_lines_member_select on public.payroll_lines for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
  create policy payroll_lines_billing_write on public.payroll_lines for all to authenticated using (public.has_permission(organization_id,'billing.write') or public.is_platform_user()) with check (public.has_permission(organization_id,'billing.write') or public.is_platform_user());
  create policy supplier_settlements_member_select on public.supplier_settlements for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
  create policy supplier_settlements_billing_write on public.supplier_settlements for all to authenticated using (public.has_permission(organization_id,'billing.write') or public.is_platform_user()) with check (public.has_permission(organization_id,'billing.write') or public.is_platform_user());
exception when duplicate_object then null;
end $$;

grant select, insert, update on public.purchase_orders, public.fuel_entries, public.petty_cash_entries, public.driver_allowances, public.payroll_runs, public.payroll_lines, public.supplier_settlements to authenticated;

create or replace function public.generate_payroll_run(
  p_organization_id uuid,
  p_actor uuid,
  p_period_start date,
  p_period_end date,
  p_lines jsonb default '[]',
  p_idempotency_key text default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  run_row public.payroll_runs;
  line jsonb;
  v_driver_id uuid;
  base_amount bigint;
  deduction_amount bigint;
  allowance_amount bigint;
  gross_amount bigint;
  net_amount bigint;
  total_gross bigint := 0;
  total_deductions bigint := 0;
  total_net bigint := 0;
  line_count integer := 0;
begin
  if not (public.has_permission(p_organization_id,'billing.write') or public.is_platform_user()) then raise exception 'billing.write permission required'; end if;
  if p_idempotency_key is not null then select * into run_row from public.payroll_runs where organization_id = p_organization_id and idempotency_key = p_idempotency_key; if found then return jsonb_build_object('ok',true,'idempotent',true,'run',to_jsonb(run_row)); end if; end if;
  select * into run_row from public.payroll_runs where organization_id = p_organization_id and period_start = p_period_start and period_end = p_period_end;
  if found then return jsonb_build_object('ok',true,'idempotent',true,'run',to_jsonb(run_row)); end if;
  insert into public.payroll_runs(organization_id, period_start, period_end, idempotency_key, created_by) values (p_organization_id,p_period_start,p_period_end,p_idempotency_key,p_actor) returning * into run_row;
  for line in select value from jsonb_array_elements(coalesce(p_lines,'[]'::jsonb)) loop
    v_driver_id := (line->>'driver_id')::uuid;
    if not exists (select 1 from public.drivers where id = v_driver_id and organization_id = p_organization_id) then raise exception 'Payroll driver is outside the organization'; end if;
    base_amount := greatest(coalesce(nullif(line->>'base_paise','')::bigint,0),0);
    deduction_amount := greatest(coalesce(nullif(line->>'deduction_paise','')::bigint,0),0);
    select coalesce(sum(da.amount_paise),0) into allowance_amount from public.driver_allowances da where da.organization_id = p_organization_id and da.driver_id = v_driver_id and da.status = 'approved' and (da.period_start is null or da.period_start >= p_period_start) and (da.period_end is null or da.period_end <= p_period_end);
    allowance_amount := greatest(coalesce(nullif(line->>'allowance_paise','')::bigint, allowance_amount),0);
    gross_amount := base_amount + allowance_amount; net_amount := gross_amount - deduction_amount;
    if net_amount < 0 then raise exception 'Payroll net cannot be negative'; end if;
    insert into public.payroll_lines(organization_id,payroll_run_id,driver_id,base_paise,allowance_paise,deduction_paise,gross_paise,net_paise,metadata) values (p_organization_id,run_row.id,v_driver_id,base_amount,allowance_amount,deduction_amount,gross_amount,net_amount,coalesce(line->'metadata','{}'));
    total_gross := total_gross + gross_amount; total_deductions := total_deductions + deduction_amount; total_net := total_net + net_amount; line_count := line_count + 1;
  end loop;
  if line_count = 0 then raise exception 'Payroll requires at least one line'; end if;
  update public.payroll_runs set gross_paise=total_gross,deductions_paise=total_deductions,net_paise=total_net,updated_at=now() where id=run_row.id returning * into run_row;
  insert into public.audit_events(organization_id,actor_id,action,entity_type,entity_id,metadata) values (p_organization_id,p_actor,'payroll_run.created','payroll_run',run_row.id,jsonb_build_object('line_count',line_count,'gross_paise',total_gross,'net_paise',total_net));
  return jsonb_build_object('ok',true,'run',to_jsonb(run_row),'line_count',line_count);
end;
$$;
grant execute on function public.generate_payroll_run(uuid,uuid,date,date,jsonb,text) to authenticated;

create or replace function public.generate_supplier_settlement(
  p_organization_id uuid,
  p_actor uuid,
  p_supplier_id uuid,
  p_period_start date,
  p_period_end date
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  settlement_row public.supplier_settlements;
  gross bigint;
  bill_count integer;
begin
  if not (public.has_permission(p_organization_id,'billing.write') or public.is_platform_user()) then raise exception 'billing.write permission required'; end if;
  select * into settlement_row from public.supplier_settlements where organization_id=p_organization_id and supplier_id is not distinct from p_supplier_id and period_start=p_period_start and period_end=p_period_end;
  if found then return jsonb_build_object('ok',true,'idempotent',true,'item',to_jsonb(settlement_row)); end if;
  select coalesce(sum(total_paise),0),count(*) into gross,bill_count from public.supplier_bills where organization_id=p_organization_id and supplier_id is not distinct from p_supplier_id and created_at >= p_period_start::timestamptz and created_at < (p_period_end + 1)::timestamptz and status not in ('void');
  insert into public.supplier_settlements(organization_id,supplier_id,period_start,period_end,bill_count,gross_paise,balance_paise,created_by) values(p_organization_id,p_supplier_id,p_period_start,p_period_end,bill_count,gross,gross,p_actor) returning * into settlement_row;
  return jsonb_build_object('ok',true,'item',to_jsonb(settlement_row));
end;
$$;
grant execute on function public.generate_supplier_settlement(uuid,uuid,uuid,date,date) to authenticated;

insert into public.audit_events(organization_id, actor_id, action, entity_type, entity_id, after_data)
select o.id, o.owner_user_id, 'supplier_fleet_finance.migration', 'migration', null, jsonb_build_object('purchase_orders',true,'fuel_entries',true,'payroll',true)
from public.organizations o where o.owner_user_id is not null;
