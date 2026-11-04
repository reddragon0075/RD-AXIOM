-- Axiom Fleet configurable feedback and service-recovery parity slice.

insert into public.permissions(key, description) values
  ('feedback.manage', 'Configure feedback forms and service recovery')
on conflict (key) do nothing;
insert into public.role_permissions(role, permission_key) values
  ('vendor_owner'::public.membership_role, 'feedback.manage'),
  ('vendor_ops'::public.membership_role, 'feedback.manage'),
  ('corporate_admin'::public.membership_role, 'feedback.manage')
on conflict do nothing;

create table if not exists public.feedback_forms (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  name text not null,
  trigger_event text not null default 'duty_completed',
  status text not null default 'draft' check (status in ('draft','active','archived')),
  version integer not null default 1,
  questions jsonb not null default '[]',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, name, version)
);
create table if not exists public.feedback_requests (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  form_id uuid not null references public.feedback_forms(id) on delete restrict,
  duty_id uuid references public.duties(id) on delete set null,
  booking_id uuid references public.bookings(id) on delete set null,
  recipient text not null default '',
  token_hash text not null default '',
  status text not null default 'sent',
  expires_at timestamptz,
  sent_at timestamptz,
  submitted_at timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, token_hash)
);
create table if not exists public.feedback_responses (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  request_id uuid not null references public.feedback_requests(id) on delete restrict,
  form_id uuid not null references public.feedback_forms(id) on delete restrict,
  duty_id uuid references public.duties(id) on delete set null,
  booking_id uuid references public.bookings(id) on delete set null,
  rating integer not null check (rating between 1 and 5),
  answers jsonb not null default '{}',
  tags jsonb not null default '[]',
  sentiment text not null default 'neutral',
  comment text not null default '',
  created_at timestamptz not null default now(),
  unique (organization_id, request_id)
);
create table if not exists public.service_recovery_actions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  response_id uuid not null references public.feedback_responses(id) on delete cascade,
  action_type text not null,
  owner_id uuid references auth.users(id) on delete set null,
  status text not null default 'open',
  due_at timestamptz,
  notes text not null default '',
  resolved_at timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_feedback_forms_org_status on public.feedback_forms(organization_id,status,created_at desc);
create index if not exists idx_feedback_requests_org_status on public.feedback_requests(organization_id,status,created_at desc);
create index if not exists idx_feedback_responses_org_created on public.feedback_responses(organization_id,created_at desc);
create index if not exists idx_service_recovery_org_status on public.service_recovery_actions(organization_id,status,created_at desc);

alter table public.feedback_forms enable row level security;
alter table public.feedback_requests enable row level security;
alter table public.feedback_responses enable row level security;
alter table public.service_recovery_actions enable row level security;

do $$
begin
  create policy feedback_forms_member_select on public.feedback_forms for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
  create policy feedback_forms_manage on public.feedback_forms for all to authenticated using (public.has_permission(organization_id,'feedback.manage') or public.is_platform_user()) with check (public.has_permission(organization_id,'feedback.manage') or public.is_platform_user());
  create policy feedback_requests_member_select on public.feedback_requests for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
  create policy feedback_requests_manage on public.feedback_requests for all to authenticated using (public.has_permission(organization_id,'feedback.manage') or public.is_platform_user()) with check (public.has_permission(organization_id,'feedback.manage') or public.is_platform_user());
  create policy feedback_responses_member_select on public.feedback_responses for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
  create policy feedback_responses_manage on public.feedback_responses for all to authenticated using (public.has_permission(organization_id,'feedback.manage') or public.is_platform_user());
  create policy service_recovery_member_select on public.service_recovery_actions for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
  create policy service_recovery_manage on public.service_recovery_actions for all to authenticated using (public.has_permission(organization_id,'feedback.manage') or public.is_platform_user()) with check (public.has_permission(organization_id,'feedback.manage') or public.is_platform_user());
exception when duplicate_object then null;
end $$;

grant select,insert,update on public.feedback_forms, public.feedback_requests, public.feedback_responses, public.service_recovery_actions to authenticated;

create or replace function public.create_feedback_form(
  p_organization_id uuid,
  p_actor uuid,
  p_name text,
  p_trigger_event text,
  p_questions jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare form_row public.feedback_forms; next_version integer;
begin
  if not (public.has_permission(p_organization_id,'feedback.manage') or public.is_platform_user()) then raise exception 'feedback.manage permission required'; end if;
  select coalesce(max(version),0)+1 into next_version from public.feedback_forms where organization_id=p_organization_id and name=p_name;
  insert into public.feedback_forms(organization_id,name,trigger_event,version,questions,created_by) values(p_organization_id,p_name,coalesce(nullif(p_trigger_event,''),'duty_completed'),next_version,coalesce(p_questions,'[]'),p_actor) returning * into form_row;
  return jsonb_build_object('ok',true,'item',to_jsonb(form_row));
end;
$$;
grant execute on function public.create_feedback_form(uuid,uuid,text,text,jsonb) to authenticated;

create or replace function public.submit_feedback_response(
  p_organization_id uuid,
  p_actor uuid,
  p_request_id uuid,
  p_rating integer,
  p_answers jsonb default '{}',
  p_tags jsonb default '[]',
  p_comment text default ''
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare request_row public.feedback_requests; form_row public.feedback_forms; response_row public.feedback_responses; sentiment_value text;
begin
  select * into request_row from public.feedback_requests where id=p_request_id and organization_id=p_organization_id for update;
  if not found then raise exception 'Feedback request not found'; end if;
  if request_row.status='submitted' then select * into response_row from public.feedback_responses where request_id=p_request_id; return jsonb_build_object('ok',true,'idempotent',true,'item',to_jsonb(response_row)); end if;
  if request_row.expires_at is not null and request_row.expires_at < now() then raise exception 'Feedback request has expired'; end if;
  if p_rating < 1 or p_rating > 5 then raise exception 'Feedback rating must be between 1 and 5'; end if;
  select * into form_row from public.feedback_forms where id=request_row.form_id;
  sentiment_value := case when p_rating >= 4 then 'positive' when p_rating <= 2 then 'negative' else 'neutral' end;
  insert into public.feedback_responses(organization_id,request_id,form_id,duty_id,booking_id,rating,answers,tags,sentiment,comment) values(p_organization_id,p_request_id,form_row.id,request_row.duty_id,request_row.booking_id,p_rating,coalesce(p_answers,'{}'),coalesce(p_tags,'[]'),sentiment_value,coalesce(p_comment,'')) returning * into response_row;
  update public.feedback_requests set status='submitted',submitted_at=now() where id=p_request_id;
  insert into public.audit_events(organization_id,actor_id,action,entity_type,entity_id,metadata) values(p_organization_id,p_actor,'feedback.submitted','feedback_response',response_row.id,jsonb_build_object('rating',p_rating,'sentiment',sentiment_value));
  return jsonb_build_object('ok',true,'item',to_jsonb(response_row));
end;
$$;
grant execute on function public.submit_feedback_response(uuid,uuid,uuid,integer,jsonb,jsonb,text) to authenticated;

insert into public.audit_events(organization_id, actor_id, action, entity_type, entity_id, after_data)
select o.id,o.owner_user_id,'feedback_recovery.migration','migration',null,jsonb_build_object('forms',true,'responses',true,'recovery',true)
from public.organizations o where o.owner_user_id is not null;
