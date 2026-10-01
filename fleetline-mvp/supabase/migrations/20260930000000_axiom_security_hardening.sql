-- Axiom Fleet security hardening
-- Apply after the foundation and additive feature migrations.
-- Privileged owner/admin memberships require a Supabase Auth AAL2 session.
-- Business ceilings are enforced again in the database/RPC layer; browser and
-- Edge validation are user-experience defenses, not authorization boundaries.

alter table public.expenses
  add constraint expenses_amount_business_limit check (amount_paise <= 100000000) not valid;
alter table public.expenses
  add constraint expenses_category_business_allowlist check (lower(category) in ('parking', 'toll', 'fuel', 'other')) not valid;
alter table public.expenses
  add constraint expenses_note_length_limit check (length(note) <= 500) not valid;
alter table public.duty_proofs
  add constraint duty_proofs_payload_length_limit check (length(proof_data::text) <= 100000) not valid;
alter table public.duty_proofs
  add constraint duty_proofs_otp_format check (lower(proof_type) <> 'otp' or coalesce(proof_data->>'code', proof_data->>'otp', '') ~ '^[0-9]{4,6}$') not valid;

create or replace function public.prevent_direct_calculation_snapshot_mutation()
returns trigger
language plpgsql
as $$
begin
  if new.calculation_snapshot is distinct from old.calculation_snapshot
     and coalesce(current_setting('axiom.allow_calculation_snapshot', true), '0') <> '1' then
    raise exception 'Calculation snapshots must be written through save_duty_calculation';
  end if;
  return new;
end;
$$;

drop trigger if exists trg_prevent_direct_calculation_snapshot_mutation on public.duties;
create trigger trg_prevent_direct_calculation_snapshot_mutation
before update on public.duties
for each row execute function public.prevent_direct_calculation_snapshot_mutation();

create or replace function public.mfa_satisfied_for_role(target_role public.membership_role)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select target_role not in ('vendor_owner'::public.membership_role, 'corporate_admin'::public.membership_role, 'platform_admin'::public.membership_role, 'platform_support'::public.membership_role)
    or coalesce(auth.jwt() ->> 'aal', 'aal1') = 'aal2';
$$;

create or replace function public.is_org_member(target_org uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.organization_memberships m
    where m.organization_id = target_org
      and m.user_id = auth.uid()
      and m.status = 'active'::public.membership_status
      and public.mfa_satisfied_for_role(m.role)
  );
$$;

create or replace function public.has_org_role(target_org uuid, allowed_roles public.membership_role[])
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.organization_memberships m
    where m.organization_id = target_org
      and m.user_id = auth.uid()
      and m.status = 'active'::public.membership_status
      and m.role = any(allowed_roles)
      and public.mfa_satisfied_for_role(m.role)
  );
$$;

create or replace function public.has_permission(target_org uuid, permission_key text)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.organization_memberships m
    left join public.role_permissions rp on rp.role = m.role and rp.permission_key = $2
    left join public.p0_role_permissions p0rp on p0rp.organization_id = m.organization_id
      and p0rp.role = m.role::text
      and p0rp.permission_key = $2
      and p0rp.allowed
    where m.organization_id = $1
      and m.user_id = auth.uid()
      and m.status = 'active'::public.membership_status
      and public.mfa_satisfied_for_role(m.role)
      and ((p0rp.id is not null and p0rp.allowed) or (p0rp.id is null and rp.permission_key is not null))
  );
$$;

create or replace function public.is_platform_user()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.profiles p
    where p.id = auth.uid()
      and p.account_type = 'platform'::public.account_type
      and coalesce(auth.jwt() ->> 'aal', 'aal1') = 'aal2'
  );
$$;

drop policy if exists organizations_member_select on public.organizations;
create policy organizations_member_select on public.organizations
for select to authenticated
using (public.is_org_member(id) or owner_user_id = auth.uid() or public.is_platform_user());

drop policy if exists memberships_member_select on public.organization_memberships;
create policy memberships_member_select on public.organization_memberships
for select to authenticated
using (user_id = auth.uid() or public.has_permission(organization_id, 'members.manage') or public.is_platform_user());

create or replace function public.save_duty_calculation(
  p_duty_id uuid,
  p_snapshot jsonb
)
returns public.duties
language plpgsql
security definer
set search_path = public
as $$
declare
  target_duty public.duties;
  input_key text;
  input_value text;
  input_limit numeric;
  line_row jsonb;
  line_key text;
  line_value text;
begin
  select * into target_duty from public.duties where id = p_duty_id for update;
  if target_duty.id is null then raise exception 'Duty not found'; end if;
  if not (public.has_permission(target_duty.organization_id, 'duties.write') or public.is_platform_user()) then
    raise exception 'Duty calculation is not permitted';
  end if;
  if target_duty.status not in ('started', 'paused', 'completed', 'disputed') then
    raise exception 'Duty must be started before it can be calculated';
  end if;
  if p_snapshot is null or jsonb_typeof(p_snapshot) <> 'object' then
    raise exception 'Calculation snapshot must be a JSON object';
  end if;
  if jsonb_typeof(p_snapshot->'lines') = 'array' and jsonb_array_length(p_snapshot->'lines') > 100 then
    raise exception 'Calculation contains too many line items';
  end if;

  -- Keep the persisted snapshot below the JavaScript safe-integer boundary.
  if p_snapshot ? 'subtotal_paise' then
    if coalesce(p_snapshot->>'subtotal_paise', '') !~ '^[0-9]+$' then
      raise exception 'Calculation subtotal is invalid';
    end if;
    if (p_snapshot->>'subtotal_paise')::numeric > 9000000000000000 then
      raise exception 'Calculation subtotal exceeds the allowed business limit';
    end if;
  end if;
  if p_snapshot ? 'total_paise' then
    if coalesce(p_snapshot->>'total_paise', '') !~ '^[0-9]+$' then
      raise exception 'Calculation total is invalid';
    end if;
    if (p_snapshot->>'total_paise')::numeric > 9000000000000000 then
      raise exception 'Calculation total exceeds the allowed business limit';
    end if;
  end if;
  if p_snapshot ? 'tax_paise' then
    if coalesce(p_snapshot->>'tax_paise', '') !~ '^[0-9]+$' then
      raise exception 'Calculation tax is invalid';
    end if;
    if (p_snapshot->>'tax_paise')::numeric > 9000000000000000 then
      raise exception 'Calculation tax exceeds the allowed business limit';
    end if;
  end if;
  if jsonb_typeof(p_snapshot->'lines') = 'array' then
    for line_row in select value from jsonb_array_elements(p_snapshot->'lines') loop
      if jsonb_typeof(line_row) <> 'object' then raise exception 'Calculation line must be an object'; end if;
      foreach line_key in array array['quantity', 'unit_paise', 'amount_paise'] loop
        if line_row ? line_key then
          line_value := line_row->>line_key;
          if line_value is null or line_value !~ '^[0-9]+$' then raise exception 'Calculation line value is invalid: %', line_key; end if;
          if line_value::numeric > 9000000000000000 then raise exception 'Calculation line value exceeds the allowed business limit: %', line_key; end if;
        end if;
      end loop;
    end loop;
  end if;
  if jsonb_typeof(p_snapshot->'inputs') = 'object' then
    for input_key, input_value in
      select key, value from jsonb_each_text(p_snapshot->'inputs')
    loop
      input_limit := case input_key
        when 'base_paise' then 100000000000
        when 'distance_km' then 1000000
        when 'per_km_paise' then 1000000
        when 'duration_minutes' then 1000000
        when 'per_hour_paise' then 100000000
        when 'waiting_minutes' then 1000000
        when 'waiting_paise' then 100000000
        when 'toll_paise' then 100000000
        when 'parking_paise' then 100000000
        when 'expense_paise' then 100000000
        when 'tax_rate_bps' then 10000
        else null
      end;
      if input_limit is not null then
        if input_value is null or input_value !~ '^[0-9]+$' then
          raise exception 'Calculation input is invalid: %', input_key;
        end if;
        if input_value::numeric > input_limit then
          raise exception 'Calculation input exceeds the allowed business limit: %', input_key;
        end if;
      end if;
    end loop;
  end if;

  perform set_config('axiom.allow_calculation_snapshot', '1', true);
  update public.duties
  set calculation_snapshot = p_snapshot,
      updated_at = now()
  where id = p_duty_id
  returning * into target_duty;
  perform set_config('axiom.allow_calculation_snapshot', '0', true);
  return target_duty;
end;
$$;

create or replace function public.record_expense(
  p_duty_id uuid,
  p_category text,
  p_amount_paise bigint,
  p_note text default '',
  p_attachment jsonb default '{}'::jsonb,
  p_idempotency_key text default null
)
returns public.expenses
language plpgsql
security definer
set search_path = public
as $$
declare
  duty_row public.duties;
  expense_row public.expenses;
  normalized_category text := lower(trim(coalesce(p_category, 'other')));
  normalized_note text := coalesce(p_note, '');
begin
  select * into duty_row from public.duties where id = p_duty_id;
  if duty_row.id is null then raise exception 'Duty not found'; end if;
  if not (
    public.has_permission(duty_row.organization_id, 'duties.write')
    or exists (select 1 from public.drivers driver_row where driver_row.id = duty_row.driver_id and driver_row.user_id = auth.uid())
    or public.is_platform_user()
  ) then
    raise exception 'Duty expense capture is not permitted';
  end if;
  if p_amount_paise is null or p_amount_paise <= 0 then raise exception 'Expense amount must be positive'; end if;
  if p_amount_paise > 100000000 then raise exception 'Expense amount exceeds the allowed business limit'; end if;
  if normalized_category not in ('parking', 'toll', 'fuel', 'other') then raise exception 'Unsupported expense category'; end if;
  if length(normalized_note) > 500 then raise exception 'Expense note is too long'; end if;
  if p_idempotency_key is not null then
    select * into expense_row from public.expenses
    where organization_id = duty_row.organization_id and idempotency_key = p_idempotency_key;
    if expense_row.id is not null then return expense_row; end if;
  end if;
  insert into public.expenses (organization_id, duty_id, category, amount_paise, note, attachment, idempotency_key, created_by)
  values (duty_row.organization_id, duty_row.id, normalized_category, p_amount_paise, normalized_note, coalesce(p_attachment, '{}'::jsonb), p_idempotency_key, auth.uid())
  returning * into expense_row;
  return expense_row;
end;
$$;

create or replace function public.capture_duty_proof(
  p_duty_id uuid,
  p_proof_type text,
  p_proof_data jsonb default '{}'::jsonb,
  p_storage_path text default null,
  p_idempotency_key text default null
)
returns public.duty_proofs
language plpgsql
security definer
set search_path = public
as $$
declare
  duty_row public.duties;
  proof_row public.duty_proofs;
  normalized_data jsonb := coalesce(p_proof_data, '{}'::jsonb);
  otp text;
begin
  select * into duty_row from public.duties where id = p_duty_id;
  if duty_row.id is null then raise exception 'Duty not found'; end if;
  if not (
    public.has_permission(duty_row.organization_id, 'duties.proof_review')
    or exists (select 1 from public.drivers driver_row where driver_row.id = duty_row.driver_id and driver_row.user_id = auth.uid())
    or public.is_platform_user()
  ) then
    raise exception 'Duty proof capture is not permitted';
  end if;
  if lower(coalesce(p_proof_type, '')) = 'otp' then
    otp := coalesce(normalized_data->>'code', normalized_data->>'otp', '');
    if otp !~ '^[0-9]{4,6}$' then raise exception 'OTP must contain 4 to 6 digits'; end if;
    normalized_data := normalized_data || jsonb_build_object('code', otp);
  end if;
  if length(coalesce(normalized_data->>'note', '')) > 500 then raise exception 'Proof note is too long'; end if;
  if length(normalized_data::text) > 100000 then raise exception 'Proof payload is too large'; end if;
  if p_idempotency_key is not null then
    select * into proof_row from public.duty_proofs
    where organization_id = duty_row.organization_id and idempotency_key = p_idempotency_key;
    if proof_row.id is not null then return proof_row; end if;
  end if;
  insert into public.duty_proofs (organization_id, duty_id, proof_type, storage_path, proof_data, idempotency_key, captured_by)
  values (duty_row.organization_id, duty_row.id, lower(coalesce(p_proof_type, '')), p_storage_path, normalized_data, p_idempotency_key, auth.uid())
  returning * into proof_row;
  return proof_row;
end;
$$;

revoke all on function public.mfa_satisfied_for_role(public.membership_role) from public;
grant execute on function public.mfa_satisfied_for_role(public.membership_role) to authenticated;
grant execute on function public.save_duty_calculation(uuid, jsonb) to authenticated;
grant execute on function public.record_expense(uuid, text, bigint, text, jsonb, text) to authenticated;
grant execute on function public.capture_duty_proof(uuid, text, jsonb, text, text) to authenticated;
