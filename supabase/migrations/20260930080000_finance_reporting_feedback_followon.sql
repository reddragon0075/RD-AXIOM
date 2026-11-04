-- Axiom Fleet supplier/fleet finance, configurable reporting/imports and
-- passenger feedback follow-on. Tally and Tally Prime formats are intentionally
-- not represented; bank files and exports use private storage and signed URLs.

insert into public.permissions(key, description) values
  ('finance.execute', 'Approve supplier payments, advances and driver payouts'),
  ('finance.manage', 'Manage fuel, payroll, petty cash and reconciliation'),
  ('reports.manage', 'Build, save and export configurable reports'),
  ('feedback.public', 'Issue token-bound passenger feedback links')
on conflict (key) do nothing;
insert into public.role_permissions(role, permission_key) values
  ('vendor_owner'::public.membership_role, 'finance.execute'), ('vendor_owner'::public.membership_role, 'finance.manage'),
  ('vendor_owner'::public.membership_role, 'reports.manage'), ('vendor_owner'::public.membership_role, 'feedback.public'),
  ('vendor_ops'::public.membership_role, 'finance.execute'), ('vendor_ops'::public.membership_role, 'finance.manage'),
  ('vendor_ops'::public.membership_role, 'reports.manage'), ('vendor_ops'::public.membership_role, 'feedback.public'),
  ('corporate_admin'::public.membership_role, 'finance.execute'), ('corporate_admin'::public.membership_role, 'finance.manage'),
  ('corporate_admin'::public.membership_role, 'reports.manage'), ('corporate_admin'::public.membership_role, 'feedback.public')
on conflict do nothing;
insert into storage.buckets(id, name, public) values ('report-exports','report-exports',false), ('payroll-exports','payroll-exports',false) on conflict (id) do nothing;

create table if not exists public.finance_supplier_payment_requests (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  supplier_id uuid references public.suppliers(id) on delete set null, settlement_id uuid references public.supplier_settlements(id) on delete set null,
  advance_id uuid, amount_paise bigint not null check (amount_paise > 0), currency text not null default 'INR', status text not null default 'requested',
  requested_by uuid references auth.users(id) on delete set null, approved_by uuid references auth.users(id) on delete set null, approved_at timestamptz,
  due_at timestamptz, payment_reference text not null default '', metadata jsonb not null default '{}', idempotency_key text,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(), unique (organization_id, idempotency_key)
);
create table if not exists public.finance_supplier_advances (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  supplier_id uuid references public.suppliers(id) on delete set null, amount_paise bigint not null check (amount_paise > 0), purpose text not null default '',
  status text not null default 'requested', requested_by uuid references auth.users(id) on delete set null, approved_by uuid references auth.users(id) on delete set null,
  approved_at timestamptz, recovered_paise bigint not null default 0, evidence jsonb not null default '{}', idempotency_key text,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(), unique (organization_id, idempotency_key)
);
create table if not exists public.finance_payment_executions (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  request_id uuid not null references public.finance_supplier_payment_requests(id) on delete cascade, amount_paise bigint not null,
  method text not null default 'mock_bank', status text not null default 'queued', provider_reference text not null default '', idempotency_key text,
  executed_at timestamptz, metadata jsonb not null default '{}', created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);
create table if not exists public.finance_settlement_approvals (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  settlement_id uuid not null references public.supplier_settlements(id) on delete cascade, status text not null default 'pending', comments text not null default '',
  requested_by uuid references auth.users(id) on delete set null, decided_by uuid references auth.users(id) on delete set null, decided_at timestamptz, created_at timestamptz not null default now(),
  unique (organization_id, settlement_id)
);
create table if not exists public.finance_driver_payouts (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  driver_id uuid not null references public.drivers(id) on delete restrict, period_start date not null, period_end date not null,
  gross_paise bigint not null default 0, deductions_paise bigint not null default 0, net_paise bigint not null default 0, status text not null default 'pending_approval',
  bank_reference text not null default '', approved_by uuid references auth.users(id) on delete set null, approved_at timestamptz, disbursed_at timestamptz,
  idempotency_key text, metadata jsonb not null default '{}', created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  unique (organization_id, driver_id, period_start, period_end), unique (organization_id, idempotency_key)
);
create table if not exists public.finance_payroll_exports (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  payroll_run_id uuid references public.payroll_runs(id) on delete set null, export_format text not null default 'bank_csv', status text not null default 'ready',
  storage_path text not null default '', signed_url text not null default '', expires_at timestamptz not null, content_sha256 text not null default '',
  created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now()
);
create table if not exists public.finance_payroll_compliance_reports (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  period_start date not null, period_end date not null, report_type text not null default 'statutory_deductions', status text not null default 'ready', deductions jsonb not null default '{}', storage_path text not null default '',
  created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now(), unique (organization_id, period_start, period_end, report_type)
);
create table if not exists public.finance_fuel_stations (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  code text not null, name text not null, city text not null default '', address text not null default '', fuel_types jsonb not null default '[]', status text not null default 'active',
  created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now(), updated_at timestamptz not null default now(), unique (organization_id, code)
);
create table if not exists public.finance_fuel_prices (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  station_id uuid not null references public.finance_fuel_stations(id) on delete cascade, fuel_type text not null, price_paise bigint not null check (price_paise > 0),
  effective_from timestamptz not null, source text not null default 'operator', created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now()
);
create table if not exists public.finance_reconciliations (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  reconciliation_type text not null, status text not null default 'open', period_start date, period_end date, filters jsonb not null default '{}', summary jsonb not null default '{}', unmatched jsonb not null default '[]', resolved_count integer not null default 0,
  created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists public.report_builder_configs (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  name text not null, report_type text not null, filters jsonb not null default '{}', columns jsonb not null default '[]', sort jsonb not null default '{}', status text not null default 'active',
  created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now(), updated_at timestamptz not null default now(), unique (organization_id, name)
);
create table if not exists public.report_favorites (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  config_id uuid not null references public.report_builder_configs(id) on delete cascade, name text not null, refresh_cadence text not null default 'manual', last_run_at timestamptz,
  created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now(), unique (organization_id, name)
);
create table if not exists public.report_export_jobs (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  config_id uuid references public.report_builder_configs(id) on delete set null, export_type text not null, status text not null default 'queued', row_count integer not null default 0,
  storage_path text not null default '', signed_url text not null default '', download_token_hash text, expires_at timestamptz not null, error text not null default '',
  created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now(), updated_at timestamptz not null default now(), unique (organization_id, download_token_hash)
);
create table if not exists public.finance_import_templates (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  entity_type text not null, name text not null, version integer not null default 1, columns jsonb not null default '[]', validation jsonb not null default '{}', status text not null default 'active',
  created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now(), unique (organization_id, entity_type, name, version)
);
create table if not exists public.finance_import_jobs (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  template_id uuid references public.finance_import_templates(id) on delete set null, entity_type text not null, status text not null default 'preview', rows jsonb not null default '[]', errors jsonb not null default '[]', corrected_rows jsonb not null default '[]', total_rows integer not null default 0, valid_rows integer not null default 0,
  created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists public.feedback_public_links (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  form_id uuid references public.feedback_forms(id) on delete set null, request_id uuid references public.feedback_requests(id) on delete set null, duty_id uuid references public.duties(id) on delete set null, booking_id uuid references public.bookings(id) on delete set null,
  token_hash text not null unique, label text not null default '', expires_at timestamptz not null, status text not null default 'active', allow_anonymous boolean not null default true,
  response_id uuid references public.feedback_responses(id) on delete set null, created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now(), submitted_at timestamptz
);
create table if not exists public.feedback_notifications (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  feedback_link_id uuid references public.feedback_public_links(id) on delete cascade, response_id uuid references public.feedback_responses(id) on delete set null, channel text not null default 'email', recipient text not null default '', status text not null default 'queued', attempts integer not null default 0, next_attempt_at timestamptz, provider_reference text not null default '', error text not null default '', created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists public.feedback_analytics_snapshots (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  period_key text not null, average_rating numeric not null default 0, response_count integer not null default 0, positive_count integer not null default 0, negative_count integer not null default 0, tags jsonb not null default '{}', created_at timestamptz not null default now(), unique (organization_id, period_key)
);
create table if not exists public.feedback_corrective_actions (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id) on delete cascade,
  response_id uuid references public.feedback_responses(id) on delete cascade, rule_id uuid, action_type text not null, owner_id uuid references auth.users(id) on delete set null, status text not null default 'open', priority text not null default 'medium', due_at timestamptz, notes text not null default '', created_by uuid references auth.users(id) on delete set null, created_at timestamptz not null default now(), resolved_at timestamptz
);

create index if not exists idx_finance_payment_requests_org_status on public.finance_supplier_payment_requests(organization_id,status,created_at desc);
create index if not exists idx_finance_advances_org_status on public.finance_supplier_advances(organization_id,status,created_at desc);
create index if not exists idx_finance_payouts_org_status on public.finance_driver_payouts(organization_id,status,created_at desc);
create index if not exists idx_finance_fuel_prices_station on public.finance_fuel_prices(organization_id,station_id,effective_from desc);
create index if not exists idx_finance_reconciliations_org on public.finance_reconciliations(organization_id,created_at desc);
create index if not exists idx_report_jobs_org_status on public.report_export_jobs(organization_id,status,created_at desc);
create index if not exists idx_import_jobs_org_status on public.finance_import_jobs(organization_id,status,created_at desc);
create index if not exists idx_feedback_public_hash on public.feedback_public_links(token_hash,status,expires_at);
create index if not exists idx_feedback_notifications_due on public.feedback_notifications(organization_id,status,next_attempt_at);
create index if not exists idx_feedback_actions_status on public.feedback_corrective_actions(organization_id,status,created_at desc);
alter table public.bookings add column if not exists company_id uuid;
alter table public.vehicles add column if not exists branch_name text not null default '';

DO $$
declare table_name text; table_names text[] := ARRAY[
  'finance_supplier_payment_requests','finance_supplier_advances','finance_payment_executions','finance_settlement_approvals','finance_driver_payouts','finance_payroll_exports','finance_payroll_compliance_reports','finance_fuel_stations','finance_fuel_prices','finance_reconciliations',
  'report_builder_configs','report_favorites','report_export_jobs','finance_import_templates','finance_import_jobs','feedback_public_links','feedback_notifications','feedback_analytics_snapshots','feedback_corrective_actions'];
begin
  foreach table_name in array table_names loop
    execute format('alter table public.%I enable row level security', table_name);
    if not exists (select 1 from pg_policies where schemaname='public' and tablename=table_name and policyname=table_name||'_member_select') then
      execute format('create policy %I on public.%I for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user())', table_name||'_member_select', table_name);
    end if;
    if not exists (select 1 from pg_policies where schemaname='public' and tablename=table_name and policyname=table_name||'_operator_write') then
      execute format('create policy %I on public.%I for all to authenticated using (public.is_org_member(organization_id) and (public.has_permission(organization_id,''finance.manage'') or public.has_permission(organization_id,''finance.execute'') or public.has_permission(organization_id,''reports.manage'') or public.has_permission(organization_id,''feedback.manage'') or public.has_permission(organization_id,''feedback.public'') or public.is_platform_user())) with check (public.is_org_member(organization_id) and (public.has_permission(organization_id,''finance.manage'') or public.has_permission(organization_id,''finance.execute'') or public.has_permission(organization_id,''reports.manage'') or public.has_permission(organization_id,''feedback.manage'') or public.has_permission(organization_id,''feedback.public'') or public.is_platform_user()))', table_name||'_operator_write', table_name);
    end if;
  end loop;
end $$;

grant select, insert, update on public.finance_supplier_payment_requests, public.finance_supplier_advances, public.finance_payment_executions, public.finance_settlement_approvals, public.finance_driver_payouts, public.finance_payroll_exports, public.finance_payroll_compliance_reports, public.finance_fuel_stations, public.finance_fuel_prices, public.finance_reconciliations, public.report_builder_configs, public.report_favorites, public.report_export_jobs, public.finance_import_templates, public.finance_import_jobs, public.feedback_public_links, public.feedback_notifications, public.feedback_analytics_snapshots, public.feedback_corrective_actions to authenticated;

-- Public feedback never exposes organization membership. The token hash is the
-- only lookup key and the single-use update is locked in one transaction.
create or replace function public.submit_public_feedback(
  p_token_hash text, p_rating integer, p_answers jsonb default '{}', p_tags jsonb default '[]', p_comment text default ''
)
returns jsonb language plpgsql security definer set search_path = public as $$
declare link_row public.feedback_public_links; request_row public.feedback_requests; response_row public.feedback_responses; sentiment_value text;
begin
  if p_rating < 1 or p_rating > 5 then raise exception 'Feedback rating must be between 1 and 5'; end if;
  select * into link_row from public.feedback_public_links where token_hash=p_token_hash and status in ('active','submitted') for update;
  if not found then raise exception 'Feedback link is invalid'; end if;
  if link_row.expires_at < now() then raise exception 'Feedback link has expired'; end if;
  if link_row.response_id is not null then select * into response_row from public.feedback_responses where id=link_row.response_id; return jsonb_build_object('ok',true,'idempotent',true,'item',to_jsonb(response_row)); end if;
  if link_row.request_id is null then raise exception 'Feedback link request is not configured'; end if;
  select * into request_row from public.feedback_requests where id=link_row.request_id for update;
  sentiment_value := case when p_rating >= 4 then 'positive' when p_rating <= 2 then 'negative' else 'neutral' end;
  insert into public.feedback_responses(organization_id,request_id,form_id,duty_id,booking_id,rating,answers,tags,sentiment,comment) values(link_row.organization_id,request_row.id,request_row.form_id,link_row.duty_id,link_row.booking_id,p_rating,coalesce(p_answers,'{}'),coalesce(p_tags,'[]'),sentiment_value,coalesce(p_comment,'')) returning * into response_row;
  update public.feedback_requests set status='submitted',submitted_at=now() where id=request_row.id;
  update public.feedback_public_links set status='submitted',response_id=response_row.id,submitted_at=now() where id=link_row.id;
  insert into public.feedback_notifications(organization_id,feedback_link_id,response_id,channel,recipient,status,next_attempt_at) values(link_row.organization_id,link_row.id,response_row.id,'internal','', 'queued', now());
  if sentiment_value='negative' then insert into public.feedback_corrective_actions(organization_id,response_id,action_type,status,priority,notes) values(link_row.organization_id,response_row.id,'investigate','open','high','Automated negative passenger feedback routing'); end if;
  return jsonb_build_object('ok',true,'item',to_jsonb(response_row));
end;
$$;
grant execute on function public.submit_public_feedback(text,integer,jsonb,jsonb,text) to anon, authenticated;

insert into public.audit_events(organization_id, actor_id, action, entity_type, entity_id, after_data)
select o.id,o.owner_user_id,'finance_reporting_feedback.migration','migration',null,jsonb_build_object('finance_controls',true,'async_exports',true,'feedback_public_links',true)
from public.organizations o where o.owner_user_id is not null;
