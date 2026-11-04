-- Axiom Fleet communications parity slice.
-- Provider credentials remain deployment configuration; this migration stores
-- templates, suppression decisions, dispatch idempotency and delivery evidence.

create table if not exists public.communication_templates (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  template_key text not null,
  name text not null,
  channel text not null check (channel in ('email','sms','whatsapp','push')),
  subject text not null default '',
  body text not null,
  placeholders jsonb not null default '[]',
  version integer not null default 1,
  status text not null default 'active' check (status in ('active','superseded','archived')),
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, template_key, channel, version)
);
create table if not exists public.communication_suppressions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  recipient text not null,
  channel text not null check (channel in ('email','sms','whatsapp','push')),
  reason text not null default '',
  status text not null default 'active',
  expires_at timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);
create table if not exists public.communication_dispatches (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  template_id uuid references public.communication_templates(id) on delete set null,
  template_key text not null,
  channel text not null,
  recipient text not null,
  status text not null default 'queued' check (status in ('queued','sent','delivered','failed','suppressed')),
  provider_reference text not null default '',
  payload jsonb not null default '{}',
  error_message text not null default '',
  scheduled_at timestamptz,
  sent_at timestamptz,
  idempotency_key text,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);
create table if not exists public.communication_webhook_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  provider text not null,
  external_event_id text not null,
  event_type text not null,
  payload jsonb not null default '{}',
  processed_at timestamptz,
  created_at timestamptz not null default now(),
  unique (provider, external_event_id)
);
create index if not exists idx_communication_templates_org_key on public.communication_templates(organization_id, template_key, channel, status);
create index if not exists idx_communication_suppressions_recipient on public.communication_suppressions(organization_id, recipient, channel, status);
create index if not exists idx_communication_dispatches_org_created on public.communication_dispatches(organization_id, created_at desc);

alter table public.communication_templates enable row level security;
alter table public.communication_suppressions enable row level security;
alter table public.communication_dispatches enable row level security;
alter table public.communication_webhook_events enable row level security;

drop policy if exists communication_templates_member_select on public.communication_templates;
create policy communication_templates_member_select on public.communication_templates for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
drop policy if exists communication_templates_notification_write on public.communication_templates;
create policy communication_templates_notification_write on public.communication_templates for all to authenticated using (public.has_permission(organization_id, 'notifications.send') or public.is_platform_user()) with check (public.has_permission(organization_id, 'notifications.send') or public.is_platform_user());
drop policy if exists communication_suppressions_member_select on public.communication_suppressions;
create policy communication_suppressions_member_select on public.communication_suppressions for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
drop policy if exists communication_suppressions_notification_write on public.communication_suppressions;
create policy communication_suppressions_notification_write on public.communication_suppressions for all to authenticated using (public.has_permission(organization_id, 'notifications.send') or public.is_platform_user()) with check (public.has_permission(organization_id, 'notifications.send') or public.is_platform_user());
drop policy if exists communication_dispatches_member_select on public.communication_dispatches;
create policy communication_dispatches_member_select on public.communication_dispatches for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
drop policy if exists communication_dispatches_notification_write on public.communication_dispatches;
create policy communication_dispatches_notification_write on public.communication_dispatches for all to authenticated using (public.has_permission(organization_id, 'notifications.send') or public.is_platform_user()) with check (public.has_permission(organization_id, 'notifications.send') or public.is_platform_user());
drop policy if exists communication_webhook_events_member_select on public.communication_webhook_events;
create policy communication_webhook_events_member_select on public.communication_webhook_events for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());

create or replace function public.create_communication_template(
  p_organization_id uuid,
  p_actor uuid,
  p_template_key text,
  p_name text,
  p_channel text,
  p_subject text,
  p_body text,
  p_placeholders jsonb default '[]'
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  next_version integer;
  template_row public.communication_templates;
begin
  if not (public.has_permission(p_organization_id, 'notifications.send') or public.is_platform_user()) then raise exception 'notifications.send permission required'; end if;
  if p_channel not in ('email','sms','whatsapp','push') then raise exception 'unsupported communication channel'; end if;
  select coalesce(max(version),0) + 1 into next_version from public.communication_templates where organization_id = p_organization_id and template_key = p_template_key and channel = p_channel;
  update public.communication_templates set status = 'superseded', updated_at = now() where organization_id = p_organization_id and template_key = p_template_key and channel = p_channel and status = 'active';
  insert into public.communication_templates(organization_id, template_key, name, channel, subject, body, placeholders, version, created_by)
  values (p_organization_id, p_template_key, p_name, p_channel, coalesce(p_subject,''), p_body, coalesce(p_placeholders,'[]'), next_version, p_actor)
  returning * into template_row;
  return jsonb_build_object('ok', true, 'item', to_jsonb(template_row));
end;
$$;
grant execute on function public.create_communication_template(uuid, uuid, text, text, text, text, text, jsonb) to authenticated;

create or replace function public.queue_communication_dispatch(
  p_organization_id uuid,
  p_actor uuid,
  p_template_key text,
  p_channel text,
  p_recipient text,
  p_variables jsonb default '{}',
  p_idempotency_key text default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  template_row public.communication_templates;
  existing_row public.communication_dispatches;
  suppression_row public.communication_suppressions;
  dispatch_row public.communication_dispatches;
  next_status text := 'queued';
  now_value timestamptz := now();
begin
  if not (public.has_permission(p_organization_id, 'notifications.send') or public.is_platform_user()) then raise exception 'notifications.send permission required'; end if;
  if p_channel not in ('email','sms','whatsapp','push') then raise exception 'unsupported communication channel'; end if;
  if p_idempotency_key is not null then
    select * into existing_row from public.communication_dispatches where organization_id = p_organization_id and idempotency_key = p_idempotency_key;
    if found then return jsonb_build_object('ok', true, 'idempotent', true, 'item', to_jsonb(existing_row)); end if;
  end if;
  select * into template_row from public.communication_templates where organization_id = p_organization_id and template_key = p_template_key and channel = p_channel and status = 'active' order by version desc limit 1;
  if not found then raise exception 'active communication template not found'; end if;
  select * into suppression_row from public.communication_suppressions where organization_id = p_organization_id and recipient = p_recipient and channel = p_channel and status = 'active' and (expires_at is null or expires_at > now()) order by created_at desc limit 1;
  if found then next_status := 'suppressed'; end if;
  insert into public.communication_dispatches(organization_id, template_id, template_key, channel, recipient, status, payload, scheduled_at, sent_at, idempotency_key, created_by)
  values (p_organization_id, template_row.id, p_template_key, p_channel, p_recipient, next_status, jsonb_build_object('variables', coalesce(p_variables,'{}'), 'template_id', template_row.id, 'placeholders', template_row.placeholders), now_value, case when next_status = 'suppressed' then null else now_value end, p_idempotency_key, p_actor)
  returning * into dispatch_row;
  return jsonb_build_object('ok', true, 'suppressed', next_status = 'suppressed', 'item', to_jsonb(dispatch_row));
end;
$$;
grant execute on function public.queue_communication_dispatch(uuid, uuid, text, text, text, jsonb, text) to authenticated;

create or replace function public.record_communication_delivery(
  p_organization_id uuid,
  p_dispatch_id uuid,
  p_status text,
  p_provider_reference text,
  p_error_message text default ''
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare updated_row public.communication_dispatches;
begin
  if not (public.is_platform_user() or public.has_permission(p_organization_id, 'notifications.send')) then raise exception 'notifications.send permission required'; end if;
  if p_status not in ('queued','sent','delivered','failed','suppressed') then raise exception 'unsupported delivery status'; end if;
  update public.communication_dispatches set status = p_status, provider_reference = coalesce(p_provider_reference,''), error_message = coalesce(p_error_message,''), sent_at = case when p_status in ('sent','delivered') then coalesce(sent_at, now()) else sent_at end where id = p_dispatch_id and organization_id = p_organization_id returning * into updated_row;
  if not found then raise exception 'communication dispatch not found'; end if;
  return jsonb_build_object('ok', true, 'item', to_jsonb(updated_row));
end;
$$;
grant execute on function public.record_communication_delivery(uuid, uuid, text, text, text) to authenticated;

insert into public.audit_events(organization_id, actor_id, action, entity_type, entity_id, after_data)
select o.id, o.owner_user_id, 'communications_parity.migration', 'migration', null, jsonb_build_object('templates', true, 'dispatch_idempotency', true, 'suppression', true)
from public.organizations o
where o.owner_user_id is not null;
