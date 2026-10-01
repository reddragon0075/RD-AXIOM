-- Axiom Fleet exception-first workspace action center.
-- This is a projection over canonical bookings, duties, evidence and finance
-- tables. It adds no second trip ledger and stores only per-user queue state.

insert into public.permissions(key, description) values
  ('operations.action_center', 'Read and manage the tenant-scoped exception-first workspace action queue')
on conflict (key) do nothing;

insert into public.role_permissions(role, permission_key)
select r.role, 'operations.action_center'
from (values
  ('vendor_owner'::public.membership_role),
  ('vendor_ops'::public.membership_role),
  ('vendor_dispatch'::public.membership_role),
  ('corporate_admin'::public.membership_role),
  ('corporate_travel'::public.membership_role),
  ('driver'::public.membership_role)
) as r(role)
on conflict do nothing;

create table if not exists public.workspace_action_states (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  action_id text not null check (length(action_id) between 1 and 180),
  status text not null default 'acknowledged' check (status in ('acknowledged','snoozed','resolved','open')),
  snooze_until timestamptz,
  note text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, user_id, action_id)
);
create index if not exists idx_workspace_action_states_user
  on public.workspace_action_states(organization_id, user_id, status, updated_at desc);

alter table public.workspace_action_states enable row level security;
grant select, insert, update, delete on public.workspace_action_states to authenticated;

drop policy if exists workspace_action_states_member_select on public.workspace_action_states;
create policy workspace_action_states_member_select
  on public.workspace_action_states for select to authenticated
  using (
    user_id = auth.uid()
    and (public.is_org_member(organization_id) or public.is_platform_user())
  );

drop policy if exists workspace_action_states_manage on public.workspace_action_states;
create policy workspace_action_states_manage
  on public.workspace_action_states for all to authenticated
  using (
    user_id = auth.uid()
    and (public.has_permission(organization_id, 'operations.action_center') or public.is_platform_user())
  )
  with check (
    user_id = auth.uid()
    and (public.has_permission(organization_id, 'operations.action_center') or public.is_platform_user())
  );

do $$
begin
  if to_regprocedure('public.p0_audit_row()') is not null then
    execute 'drop trigger if exists workspace_action_states_audit on public.workspace_action_states';
    execute 'create trigger workspace_action_states_audit after insert or update or delete on public.workspace_action_states for each row execute function public.p0_audit_row()';
  end if;
end $$;
