-- Axiom Network collaboration and feedback delivery boundary.
-- Additive only: the Network remains closed B2B/invite-only and Fleet remains
-- the canonical booking, duty, invoice and payment ledger.

create table if not exists public.network_partner_directory (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  vendor_organization_id uuid not null references public.organizations(id) on delete cascade,
  vendor_profile_id uuid not null references public.network_vendor_profiles(id) on delete cascade,
  display_name text not null default '',
  verification_status text not null default 'verified' check (verification_status in ('pending','verified','suspended','revoked')),
  verified_at timestamptz,
  discovered_via text not null default 'invite',
  search_document jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, vendor_organization_id),
  unique (vendor_profile_id)
);

create table if not exists public.network_associates (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  vendor_organization_id uuid not null references public.organizations(id) on delete cascade,
  invite_id uuid not null unique references public.network_invites(id) on delete cascade,
  vendor_profile_id uuid references public.network_vendor_profiles(id) on delete set null,
  status text not null default 'pending' check (status in ('pending','accepted','rejected','revoked')),
  buyer_contact text not null default '',
  vendor_contact text not null default '',
  acceptance_note text not null default '',
  accepted_by uuid references auth.users(id) on delete set null,
  accepted_at timestamptz,
  rejected_at timestamptz,
  revoked_at timestamptz,
  metadata jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_network_partner_directory_org_status on public.network_partner_directory(organization_id, verification_status, updated_at desc);
create index if not exists idx_network_partner_directory_vendor on public.network_partner_directory(vendor_organization_id, verification_status);
create index if not exists idx_network_associates_org_status on public.network_associates(organization_id, status, created_at desc);
create index if not exists idx_network_associates_vendor_status on public.network_associates(vendor_organization_id, status, created_at desc);

-- Contract versions and normalized rate rows make synchronization explicit;
-- terms/rates are immutable snapshots and are never overwritten in place.
create table if not exists public.network_contract_versions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  contract_id uuid not null references public.network_contracts(id) on delete cascade,
  version integer not null,
  status text not null default 'draft' check (status in ('draft','published','accepted','superseded','rejected')),
  terms jsonb not null default '{}',
  effective_from timestamptz,
  effective_to timestamptz,
  source text not null default 'network',
  supersedes_version_id uuid references public.network_contract_versions(id) on delete set null,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  accepted_by uuid references auth.users(id) on delete set null,
  accepted_at timestamptz,
  unique (contract_id, version)
);
create table if not exists public.network_rate_cards (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  contract_version_id uuid not null references public.network_contract_versions(id) on delete cascade,
  rate_code text not null,
  service_type text not null default '',
  vehicle_type text not null default '',
  city text not null default '',
  unit text not null default 'trip',
  amount_paise bigint not null default 0 check (amount_paise >= 0),
  currency text not null default 'INR',
  effective_from timestamptz,
  effective_to timestamptz,
  status text not null default 'active' check (status in ('active','superseded','withdrawn')),
  terms jsonb not null default '{}',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (contract_version_id, rate_code)
);
create table if not exists public.network_contract_syncs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  contract_id uuid not null references public.network_contracts(id) on delete cascade,
  contract_version_id uuid references public.network_contract_versions(id) on delete set null,
  direction text not null default 'outbound' check (direction in ('outbound','inbound')),
  status text not null default 'queued' check (status in ('queued','sent','acknowledged','rejected','failed')),
  source_version integer,
  target_version integer,
  change_summary jsonb not null default '{}',
  provider_reference text not null default '',
  idempotency_key text,
  requested_by uuid references auth.users(id) on delete set null,
  acknowledged_by uuid references auth.users(id) on delete set null,
  requested_at timestamptz not null default now(),
  acknowledged_at timestamptz,
  error text not null default '',
  unique (organization_id, idempotency_key)
);
create index if not exists idx_network_contract_versions_contract on public.network_contract_versions(contract_id, version desc);
create index if not exists idx_network_rate_cards_version on public.network_rate_cards(contract_version_id, status, rate_code);
create index if not exists idx_network_contract_syncs_contract on public.network_contract_syncs(contract_id, requested_at desc);

create table if not exists public.network_exchange_envelopes (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  service_order_id uuid not null references public.network_service_orders(id) on delete cascade,
  exchange_type text not null check (exchange_type in ('booking','duty_slip','invoice','operational_message')),
  direction text not null default 'outbound' check (direction in ('outbound','inbound')),
  status text not null default 'queued' check (status in ('queued','sent','acknowledged','processed','rejected','failed')),
  schema_version text not null default 'v1',
  external_reference text not null default '',
  payload jsonb not null default '{}',
  attachments jsonb not null default '[]',
  idempotency_key text,
  sender_organization_id uuid references public.organizations(id) on delete set null,
  recipient_organization_id uuid references public.organizations(id) on delete set null,
  provider_reference text not null default '',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  sent_at timestamptz,
  acknowledged_at timestamptz,
  processed_at timestamptz,
  error text not null default '',
  unique (organization_id, idempotency_key)
);
create index if not exists idx_network_exchange_service_order on public.network_exchange_envelopes(service_order_id, exchange_type, created_at desc);
create index if not exists idx_network_exchange_due on public.network_exchange_envelopes(organization_id, status, created_at);

create table if not exists public.network_sla_observations (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  service_order_id uuid not null references public.network_service_orders(id) on delete cascade,
  sla_id uuid references public.network_slas(id) on delete set null,
  metric text not null,
  target_value numeric not null default 0,
  observed_value numeric not null default 0,
  unit text not null default '',
  status text not null default 'met' check (status in ('met','breached','waived','under_review')),
  severity text not null default 'warning',
  evidence jsonb not null default '{}',
  observed_at timestamptz not null default now(),
  source text not null default 'operator',
  idempotency_key text,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);
create table if not exists public.network_supplier_issues (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  service_order_id uuid not null references public.network_service_orders(id) on delete cascade,
  vendor_profile_id uuid references public.network_vendor_profiles(id) on delete set null,
  issue_type text not null check (issue_type in ('rejection','sla_breach','rate_discrepancy','settlement_dispute','operational')),
  status text not null default 'open' check (status in ('open','acknowledged','in_review','resolved','rejected','closed')),
  severity text not null default 'medium',
  reason_code text not null default '',
  description text not null default '',
  evidence jsonb not null default '{}',
  proposed_resolution jsonb not null default '{}',
  resolution jsonb not null default '{}',
  reported_by uuid references auth.users(id) on delete set null,
  assigned_to uuid references auth.users(id) on delete set null,
  due_at timestamptz,
  resolved_by uuid references auth.users(id) on delete set null,
  resolved_at timestamptz,
  idempotency_key text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);
create table if not exists public.network_rate_discrepancies (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  service_order_id uuid not null references public.network_service_orders(id) on delete cascade,
  contract_id uuid references public.network_contracts(id) on delete set null,
  rate_card_id uuid references public.network_rate_cards(id) on delete set null,
  issue_id uuid references public.network_supplier_issues(id) on delete set null,
  expected_paise bigint not null default 0,
  actual_paise bigint not null default 0,
  variance_paise bigint not null default 0,
  currency text not null default 'INR',
  status text not null default 'open' check (status in ('open','acknowledged','accepted','rejected','resolved')),
  reason text not null default '',
  evidence jsonb not null default '{}',
  resolution jsonb not null default '{}',
  idempotency_key text,
  created_by uuid references auth.users(id) on delete set null,
  resolved_by uuid references auth.users(id) on delete set null,
  resolved_at timestamptz,
  created_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);
create table if not exists public.network_settlement_resolutions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  service_order_id uuid references public.network_service_orders(id) on delete cascade,
  settlement_id uuid not null references public.network_settlements(id) on delete cascade,
  issue_id uuid references public.network_supplier_issues(id) on delete set null,
  discrepancy_id uuid references public.network_rate_discrepancies(id) on delete set null,
  status text not null default 'proposed' check (status in ('proposed','accepted','rejected','applied','void')),
  resolution_type text not null default 'adjustment',
  adjustment_paise bigint not null default 0,
  notes text not null default '',
  evidence jsonb not null default '{}',
  proposed_by uuid references auth.users(id) on delete set null,
  decided_by uuid references auth.users(id) on delete set null,
  decided_at timestamptz,
  applied_at timestamptz,
  idempotency_key text,
  created_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);
alter table public.network_settlement_resolutions add column if not exists service_order_id uuid references public.network_service_orders(id) on delete cascade;
create index if not exists idx_network_sla_observations_order on public.network_sla_observations(service_order_id, observed_at desc);
create index if not exists idx_network_supplier_issues_order on public.network_supplier_issues(service_order_id, status, created_at desc);
create index if not exists idx_network_rate_discrepancies_order on public.network_rate_discrepancies(service_order_id, status, created_at desc);
create index if not exists idx_network_settlement_resolutions_settlement on public.network_settlement_resolutions(settlement_id, created_at desc);

-- Feedback delivery policy, attempt and provider-receipt records.
alter table public.feedback_requests add column if not exists customer_id uuid references public.customers(id) on delete set null;
alter table public.feedback_public_links add column if not exists customer_id uuid references public.customers(id) on delete set null;
alter table public.feedback_notifications add column if not exists policy_id uuid;
alter table public.feedback_notifications add column if not exists attempt_limit integer not null default 5;
alter table public.feedback_notifications add column if not exists last_provider_event_id text not null default '';
alter table public.feedback_notifications add column if not exists bounce_code text not null default '';
alter table public.feedback_notifications add column if not exists dead_lettered_at timestamptz;
create table if not exists public.feedback_delivery_policies (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  customer_id uuid references public.customers(id) on delete cascade,
  name text not null,
  status text not null default 'active' check (status in ('active','paused','archived')),
  trigger_event text not null default 'duty_completed',
  channels jsonb not null default '["sms","email","whatsapp"]',
  fallback_channels jsonb not null default '["email"]',
  delay_minutes integer not null default 0,
  quiet_hours jsonb not null default '{}',
  template_keys jsonb not null default '{}',
  max_attempts integer not null default 5,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, customer_id, name)
);
create table if not exists public.feedback_escalation_policies (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  customer_id uuid references public.customers(id) on delete cascade,
  name text not null,
  status text not null default 'active' check (status in ('active','paused','archived')),
  conditions jsonb not null default '{"rating_lte":2}',
  action_type text not null default 'investigate',
  priority text not null default 'high',
  owner_id uuid references auth.users(id) on delete set null,
  due_minutes integer not null default 60,
  channels jsonb not null default '[]',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, customer_id, name)
);
create table if not exists public.feedback_delivery_attempts (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  notification_id uuid not null references public.feedback_notifications(id) on delete cascade,
  attempt_number integer not null,
  provider text not null default 'mock',
  channel text not null,
  status text not null default 'queued' check (status in ('queued','sent','delivered','bounced','failed','retrying','dead_letter')),
  provider_reference text not null default '',
  provider_event_id text,
  error_code text not null default '',
  error_message text not null default '',
  response_payload jsonb not null default '{}',
  next_attempt_at timestamptz,
  created_at timestamptz not null default now(),
  unique (notification_id, attempt_number),
  unique (provider, provider_event_id)
);
create table if not exists public.feedback_provider_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid references public.organizations(id) on delete cascade,
  provider text not null,
  external_event_id text not null,
  event_type text not null,
  provider_reference text not null default '',
  payload jsonb not null default '{}',
  processed_at timestamptz,
  created_at timestamptz not null default now(),
  unique (provider, external_event_id)
);
create index if not exists idx_feedback_delivery_policies_customer on public.feedback_delivery_policies(organization_id, customer_id, status);
create index if not exists idx_feedback_escalation_policies_customer on public.feedback_escalation_policies(organization_id, customer_id, status);
create index if not exists idx_feedback_delivery_attempts_notification on public.feedback_delivery_attempts(notification_id, attempt_number desc);
create index if not exists idx_feedback_delivery_attempts_due on public.feedback_delivery_attempts(organization_id, status, next_attempt_at);
create index if not exists idx_feedback_provider_events_reference on public.feedback_provider_events(provider, provider_reference);

-- Reusable audit helper for customer policy automation. The trigger is also
-- used by token-only submissions, so no public endpoint can bypass escalation.
create or replace function public.apply_feedback_escalation_policies()
returns trigger language plpgsql security definer set search_path = public as $$
declare policy_row record; customer_value uuid; rating_limit integer; sentiment_value text;
begin
  select customer_id into customer_value from public.bookings where id = new.booking_id;
  sentiment_value := new.sentiment;
  for policy_row in
    select * from public.feedback_escalation_policies
    where organization_id = new.organization_id and status = 'active'
      and (customer_id is null or customer_id = customer_value)
  loop
    rating_limit := nullif(policy_row.conditions ->> 'rating_lte','')::integer;
    if (rating_limit is null or new.rating <= rating_limit)
       and (coalesce(policy_row.conditions ->> 'sentiment','') = '' or policy_row.conditions ->> 'sentiment' = sentiment_value) then
      if not exists (select 1 from public.service_recovery_actions where response_id = new.id and rule_id = policy_row.id) then
        insert into public.service_recovery_actions(organization_id,response_id,action_type,owner_id,status,due_at,notes,created_by)
        values(new.organization_id,new.id,policy_row.action_type,policy_row.owner_id,'open',now() + make_interval(mins => policy_row.due_minutes), 'Automated escalation policy: ' || policy_row.name, null);
      end if;
    end if;
  end loop;
  return new;
end; $$;
drop trigger if exists feedback_escalation_policy_trigger on public.feedback_responses;
create trigger feedback_escalation_policy_trigger after insert on public.feedback_responses for each row execute procedure public.apply_feedback_escalation_policies();

-- Keep the directory in step with an accepted, active profile. It does not
-- create profiles or open a public registration path.
create or replace function public.sync_network_partner_directory()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if new.status = 'active' then
    insert into public.network_partner_directory(organization_id,vendor_organization_id,vendor_profile_id,display_name,verification_status,verified_at,discovered_via,search_document,created_by)
    values(new.organization_id,new.vendor_organization_id,new.id,new.vendor_name,'verified',now(),'invite',jsonb_build_object('cities',new.cities,'service_types',new.service_types,'vehicle_types',new.vehicle_types,'capabilities',new.capabilities,'capacity',new.capacity,'compliance',new.compliance),new.created_by)
    on conflict (vendor_profile_id) do update set display_name=excluded.display_name, verification_status='verified', verified_at=coalesce(public.network_partner_directory.verified_at,now()), search_document=excluded.search_document, updated_at=now();
  else
    update public.network_partner_directory set verification_status=case when new.status in ('suspended','revoked') then new.status else 'pending' end, updated_at=now() where vendor_profile_id=new.id;
  end if;
  return new;
end; $$;
drop trigger if exists network_partner_directory_sync on public.network_vendor_profiles;
create trigger network_partner_directory_sync after insert or update on public.network_vendor_profiles for each row execute procedure public.sync_network_partner_directory();

-- RLS: buyer members can manage their tenant; vendor members can see and
-- action only the explicitly linked relationship/service order.
do $$
declare t text; tables text[] := array[
  'network_partner_directory','network_associates','network_contract_versions','network_rate_cards','network_contract_syncs',
  'network_exchange_envelopes','network_sla_observations','network_supplier_issues','network_rate_discrepancies','network_settlement_resolutions',
  'feedback_delivery_policies','feedback_escalation_policies','feedback_delivery_attempts','feedback_provider_events'];
begin
  foreach t in array tables loop
    execute format('alter table public.%I enable row level security', t);
    execute format('grant select, insert, update on public.%I to authenticated', t);
  end loop;
end $$;

-- Existing MVP tables receive the same explicit vendor-side read boundary so
-- an associate can accept, view and operate only the buyer link it was invited
-- into. Buyer-side policies remain in force.
drop policy if exists network_invites_vendor_access on public.network_invites;
create policy network_invites_vendor_access on public.network_invites for all to authenticated using (public.is_org_member(organization_id) or public.is_org_member(vendor_organization_id) or public.is_platform_user()) with check (public.is_org_member(organization_id) or public.is_org_member(vendor_organization_id) or public.is_platform_user());
drop policy if exists network_service_orders_vendor_access on public.network_service_orders;
create policy network_service_orders_vendor_access on public.network_service_orders for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user() or exists (select 1 from public.network_vendor_profiles v where v.id=network_service_orders.vendor_profile_id and public.is_org_member(v.vendor_organization_id)));
drop policy if exists network_contracts_vendor_access on public.network_contracts;
create policy network_contracts_vendor_access on public.network_contracts for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user() or exists (select 1 from public.network_awards a join public.network_vendor_profiles v on v.id=a.vendor_profile_id where a.id=network_contracts.award_id and public.is_org_member(v.vendor_organization_id)));
drop policy if exists network_slas_vendor_access on public.network_slas;
create policy network_slas_vendor_access on public.network_slas for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user() or exists (select 1 from public.network_contracts c join public.network_awards a on a.id=c.award_id join public.network_vendor_profiles v on v.id=a.vendor_profile_id where c.id=network_slas.contract_id and public.is_org_member(v.vendor_organization_id)));
drop policy if exists network_settlements_vendor_access on public.network_settlements;
create policy network_settlements_vendor_access on public.network_settlements for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user() or exists (select 1 from public.network_service_orders so join public.network_vendor_profiles v on v.id=so.vendor_profile_id where so.id=network_settlements.service_order_id and public.is_org_member(v.vendor_organization_id)));

drop policy if exists network_partner_directory_select on public.network_partner_directory;
create policy network_partner_directory_select on public.network_partner_directory for select to authenticated using (public.is_org_member(organization_id) or public.is_org_member(vendor_organization_id) or public.is_platform_user());
drop policy if exists network_partner_directory_manage on public.network_partner_directory;
create policy network_partner_directory_manage on public.network_partner_directory for all to authenticated using (public.has_permission(organization_id,'network.manage') or public.is_platform_user()) with check (public.has_permission(organization_id,'network.manage') or public.is_platform_user());

drop policy if exists network_associates_access on public.network_associates;
create policy network_associates_access on public.network_associates for all to authenticated using (public.is_org_member(organization_id) or public.is_org_member(vendor_organization_id) or public.is_platform_user()) with check (public.is_org_member(organization_id) or public.is_org_member(vendor_organization_id) or public.is_platform_user());

-- Helper expression used by the collaboration policies.
drop policy if exists network_contract_versions_access on public.network_contract_versions;
create policy network_contract_versions_access on public.network_contract_versions for all to authenticated using (
  public.is_org_member(organization_id) or public.is_platform_user() or exists (select 1 from public.network_contracts c join public.network_awards a on a.id=c.award_id join public.network_vendor_profiles v on v.id=a.vendor_profile_id where c.id=network_contract_versions.contract_id and public.is_org_member(v.vendor_organization_id))
) with check (public.is_org_member(organization_id) or public.is_platform_user());
drop policy if exists network_rate_cards_access on public.network_rate_cards;
create policy network_rate_cards_access on public.network_rate_cards for all to authenticated using (
  public.is_org_member(organization_id) or public.is_platform_user() or exists (select 1 from public.network_contract_versions cv join public.network_contracts c on c.id=cv.contract_id join public.network_awards a on a.id=c.award_id join public.network_vendor_profiles v on v.id=a.vendor_profile_id where cv.id=network_rate_cards.contract_version_id and public.is_org_member(v.vendor_organization_id))
) with check (public.is_org_member(organization_id) or public.is_platform_user());
drop policy if exists network_contract_syncs_access on public.network_contract_syncs;
create policy network_contract_syncs_access on public.network_contract_syncs for all to authenticated using (public.is_org_member(organization_id) or public.is_platform_user() or exists (select 1 from public.network_contracts c join public.network_awards a on a.id=c.award_id join public.network_vendor_profiles v on v.id=a.vendor_profile_id where c.id=network_contract_syncs.contract_id and public.is_org_member(v.vendor_organization_id))) with check (public.is_org_member(organization_id) or public.is_platform_user());

-- Collaboration records use the buyer tenant as their audit owner. Vendor
-- members are admitted only through the service-order/profile relationship.
do $$
declare t text; tables text[] := array['network_exchange_envelopes','network_sla_observations','network_supplier_issues','network_rate_discrepancies'];
begin
  foreach t in array tables loop
    execute format('drop policy if exists %I on public.%I', t||'_access',t);
    execute format('create policy %I on public.%I for all to authenticated using (public.is_org_member(organization_id) or public.is_platform_user() or exists (select 1 from public.network_service_orders so join public.network_vendor_profiles v on v.id=so.vendor_profile_id where so.id=%I.service_order_id and public.is_org_member(v.vendor_organization_id))) with check (public.is_org_member(organization_id) or public.is_platform_user())', t||'_access',t,t);
  end loop;
end $$;
drop policy if exists network_settlement_resolutions_access on public.network_settlement_resolutions;
create policy network_settlement_resolutions_access on public.network_settlement_resolutions for all to authenticated using (public.is_org_member(organization_id) or public.is_platform_user() or exists (select 1 from public.network_settlements s join public.network_service_orders so on so.id=s.service_order_id join public.network_vendor_profiles v on v.id=so.vendor_profile_id where s.id=network_settlement_resolutions.settlement_id and public.is_org_member(v.vendor_organization_id))) with check (public.is_org_member(organization_id) or public.is_platform_user());

-- Feedback configuration is customer-specific but always tenant-owned.
do $$
declare t text; tables text[] := array['feedback_delivery_policies','feedback_escalation_policies'];
begin
  foreach t in array tables loop
    execute format('drop policy if exists %I on public.%I', t||'_access',t);
    execute format('create policy %I on public.%I for all to authenticated using (public.has_permission(organization_id,''feedback.manage'') or public.is_platform_user()) with check (public.has_permission(organization_id,''feedback.manage'') or public.is_platform_user())', t||'_access',t);
  end loop;
end $$;
drop policy if exists feedback_delivery_attempts_access on public.feedback_delivery_attempts;
create policy feedback_delivery_attempts_access on public.feedback_delivery_attempts for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());
drop policy if exists feedback_provider_events_access on public.feedback_provider_events;
create policy feedback_provider_events_access on public.feedback_provider_events for select to authenticated using (public.is_org_member(organization_id) or public.is_platform_user());

-- Operators can process their own delivery queue; provider webhooks use the
-- dedicated edge boundary with the service role after signature validation.
drop policy if exists feedback_notifications_delivery_write on public.feedback_notifications;
create policy feedback_notifications_delivery_write on public.feedback_notifications for all to authenticated using (public.has_permission(organization_id,'feedback.manage') or public.is_platform_user()) with check (public.has_permission(organization_id,'feedback.manage') or public.is_platform_user());
grant select, insert, update on public.feedback_notifications, public.feedback_delivery_policies, public.feedback_escalation_policies, public.feedback_delivery_attempts, public.feedback_provider_events to authenticated;

-- Relationship checks close the tenant-confused-deputy gap left by generic
-- organization policies on the additive feedback tables. Service-role Edge
-- functions still use the same checks in code, while direct PostgREST writes
-- cannot attach a record from another organization.
drop policy if exists feedback_requests_manage on public.feedback_requests;
create policy feedback_requests_manage on public.feedback_requests for all to authenticated
using (public.is_platform_user() or public.has_permission(organization_id,'feedback.manage'))
with check (
  public.is_platform_user() or (
    public.has_permission(organization_id,'feedback.manage')
    and exists (select 1 from public.feedback_forms f where f.id=feedback_requests.form_id and f.organization_id=feedback_requests.organization_id)
    and (customer_id is null or exists (select 1 from public.customers c where c.id=feedback_requests.customer_id and c.organization_id=feedback_requests.organization_id))
    and (duty_id is null or exists (select 1 from public.duties d where d.id=feedback_requests.duty_id and d.organization_id=feedback_requests.organization_id))
    and (booking_id is null or exists (select 1 from public.bookings b where b.id=feedback_requests.booking_id and b.organization_id=feedback_requests.organization_id))
  )
);
drop policy if exists feedback_responses_manage on public.feedback_responses;
create policy feedback_responses_manage on public.feedback_responses for all to authenticated
using (public.is_platform_user() or public.has_permission(organization_id,'feedback.manage'))
with check (
  public.is_platform_user() or (
    public.has_permission(organization_id,'feedback.manage')
    and exists (select 1 from public.feedback_requests r where r.id=feedback_responses.request_id and r.organization_id=feedback_responses.organization_id)
    and exists (select 1 from public.feedback_forms f where f.id=feedback_responses.form_id and f.organization_id=feedback_responses.organization_id)
  )
);
drop policy if exists service_recovery_manage on public.service_recovery_actions;
create policy service_recovery_manage on public.service_recovery_actions for all to authenticated
using (public.is_platform_user() or public.has_permission(organization_id,'feedback.manage'))
with check (
  public.is_platform_user() or (
    public.has_permission(organization_id,'feedback.manage')
    and exists (select 1 from public.feedback_responses r where r.id=service_recovery_actions.response_id and r.organization_id=service_recovery_actions.organization_id)
  )
);

drop policy if exists feedback_public_links_operator_write on public.feedback_public_links;
create policy feedback_public_links_operator_write on public.feedback_public_links for all to authenticated
using (public.is_platform_user() or public.has_permission(organization_id,'feedback.manage'))
with check (
  public.is_platform_user() or (
    public.has_permission(organization_id,'feedback.manage')
    and (form_id is null or exists (select 1 from public.feedback_forms f where f.id=feedback_public_links.form_id and f.organization_id=feedback_public_links.organization_id))
    and (request_id is null or exists (select 1 from public.feedback_requests r where r.id=feedback_public_links.request_id and r.organization_id=feedback_public_links.organization_id))
    and (customer_id is null or exists (select 1 from public.customers c where c.id=feedback_public_links.customer_id and c.organization_id=feedback_public_links.organization_id))
    and (duty_id is null or exists (select 1 from public.duties d where d.id=feedback_public_links.duty_id and d.organization_id=feedback_public_links.organization_id))
    and (booking_id is null or exists (select 1 from public.bookings b where b.id=feedback_public_links.booking_id and b.organization_id=feedback_public_links.organization_id))
  )
);
drop policy if exists feedback_notifications_operator_write on public.feedback_notifications;
drop policy if exists feedback_notifications_delivery_write on public.feedback_notifications;
create policy feedback_notifications_delivery_write on public.feedback_notifications for all to authenticated
using (public.is_platform_user() or public.has_permission(organization_id,'feedback.manage'))
with check (
  public.is_platform_user() or (
    public.has_permission(organization_id,'feedback.manage')
    and (feedback_link_id is null or exists (select 1 from public.feedback_public_links l where l.id=feedback_notifications.feedback_link_id and l.organization_id=feedback_notifications.organization_id))
    and (response_id is null or exists (select 1 from public.feedback_responses r where r.id=feedback_notifications.response_id and r.organization_id=feedback_notifications.organization_id))
  )
);
drop policy if exists feedback_corrective_actions_operator_write on public.feedback_corrective_actions;
create policy feedback_corrective_actions_operator_write on public.feedback_corrective_actions for all to authenticated
using (public.is_platform_user() or public.has_permission(organization_id,'feedback.manage'))
with check (
  public.is_platform_user() or (
    public.has_permission(organization_id,'feedback.manage')
    and (response_id is null or exists (select 1 from public.feedback_responses r where r.id=feedback_corrective_actions.response_id and r.organization_id=feedback_corrective_actions.organization_id))
  )
);
drop policy if exists feedback_delivery_policies_access on public.feedback_delivery_policies;
create policy feedback_delivery_policies_access on public.feedback_delivery_policies for all to authenticated
using (public.is_platform_user() or public.has_permission(organization_id,'feedback.manage'))
with check (
  public.is_platform_user() or (
    public.has_permission(organization_id,'feedback.manage')
    and (customer_id is null or exists (select 1 from public.customers c where c.id=feedback_delivery_policies.customer_id and c.organization_id=feedback_delivery_policies.organization_id))
  )
);
drop policy if exists feedback_escalation_policies_access on public.feedback_escalation_policies;
create policy feedback_escalation_policies_access on public.feedback_escalation_policies for all to authenticated
using (public.is_platform_user() or public.has_permission(organization_id,'feedback.manage'))
with check (
  public.is_platform_user() or (
    public.has_permission(organization_id,'feedback.manage')
    and (customer_id is null or exists (select 1 from public.customers c where c.id=feedback_escalation_policies.customer_id and c.organization_id=feedback_escalation_policies.organization_id))
    and (owner_id is null or exists (select 1 from public.organization_memberships m where m.user_id=feedback_escalation_policies.owner_id and m.organization_id=feedback_escalation_policies.organization_id and m.status='active'))
  )
);

insert into public.audit_events(organization_id, actor_id, action, entity_type, entity_id, metadata)
select o.id, o.owner_user_id, 'network_exchange_feedback_delivery.migration', 'migration', null,
       jsonb_build_object('network_directory',true,'contract_sync',true,'exchange_envelopes',true,'supplier_resolution',true,'feedback_delivery_policies',true,'provider_receipts',true)
from public.organizations o where o.owner_user_id is not null;
