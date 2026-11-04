-- Axiom Fleet push dispatch and mobile performance contracts.
-- This keeps the first provider adapter queue-based: a worker/Edge Function can
-- consume queued notifications and deliver Expo/FCM/APNs messages later.

create index if not exists idx_drivers_user_org on public.drivers(user_id, organization_id);
create index if not exists idx_duties_driver_org_status on public.duties(driver_id, organization_id, status, reporting_at);
create index if not exists idx_device_bindings_user_push on public.device_bindings(user_id, organization_id, status) where push_token <> '';

create or replace function public.queue_push_notification(
  p_organization_id uuid,
  p_recipient_id uuid,
  p_template_key text,
  p_payload jsonb default '{}'::jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  target record;
  queued_count integer := 0;
  notification_payload jsonb;
begin
  if auth.uid() is null or not public.is_org_member(p_organization_id) and not public.is_platform_user() then
    raise exception 'Not authorized to queue organization notifications' using errcode = '42501';
  end if;

  for target in
    select db.user_id, db.device_id
    from public.device_bindings db
    where db.organization_id = p_organization_id
      and db.status = 'active'
      and db.push_token <> ''
      and (p_recipient_id is null or db.user_id = p_recipient_id)
  loop
    notification_payload := coalesce(p_payload, '{}'::jsonb) || jsonb_build_object('device_id', target.device_id, 'recipient_id', target.user_id);
    insert into public.notifications (organization_id, recipient_id, channel, template_key, status, provider_reference, payload)
    values (p_organization_id, target.user_id, 'push', p_template_key, 'queued', 'mock_push_' || replace(gen_random_uuid()::text, '-', ''), notification_payload);
    queued_count := queued_count + 1;
  end loop;

  -- Preserve an operational notification even before a device is registered.
  if queued_count = 0 and p_recipient_id is not null then
    insert into public.notifications (organization_id, recipient_id, channel, template_key, status, provider_reference, payload)
    values (p_organization_id, p_recipient_id, 'push', p_template_key, 'queued', null, coalesce(p_payload, '{}'::jsonb));
    queued_count := 1;
  end if;

  return jsonb_build_object('queued', queued_count, 'template_key', p_template_key);
end;
$$;

revoke all on function public.queue_push_notification(uuid, uuid, text, jsonb) from public;
grant execute on function public.queue_push_notification(uuid, uuid, text, jsonb) to authenticated;

create or replace function public.notify_duty_assignment()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  driver_user_id uuid;
begin
  if new.driver_id is null or (tg_op = 'UPDATE' and new.driver_id is not distinct from old.driver_id) then
    return new;
  end if;

  select d.user_id into driver_user_id
  from public.drivers d
  where d.id = new.driver_id;

  if driver_user_id is not null then
    perform public.queue_push_notification(
      new.organization_id,
      driver_user_id,
      case when tg_op = 'UPDATE' then 'duty_reassigned' else 'duty_assigned' end,
      jsonb_build_object('duty_id', new.id, 'booking_id', new.booking_id, 'reporting_at', new.reporting_at)
    );
  end if;
  return new;
end;
$$;

drop trigger if exists duties_assignment_push on public.duties;
create trigger duties_assignment_push
after insert or update of driver_id on public.duties
for each row execute function public.notify_duty_assignment();

create or replace function public.raise_sos(
  p_duty_id uuid,
  p_latitude numeric default null,
  p_longitude numeric default null,
  p_payload jsonb default '{}'::jsonb
)
returns public.sos_events
language plpgsql
security definer
set search_path = public
as $$
declare
  duty_row public.duties;
  driver_row public.drivers;
  event_row public.sos_events;
  operator_row record;
  request_key text := nullif(p_payload->>'idempotency_key', '');
begin
  select * into duty_row from public.duties where id = p_duty_id;
  if duty_row.id is null then raise exception 'Duty not found' using errcode = 'P0002'; end if;

  select * into driver_row from public.drivers where id = duty_row.driver_id;
  if auth.uid() is null or not public.is_platform_user() and not public.has_permission(duty_row.organization_id, 'duties.write') and driver_row.user_id is distinct from auth.uid() then
    raise exception 'Not authorized to raise SOS for this duty' using errcode = '42501';
  end if;

  if request_key is not null then
    select * into event_row
    from public.sos_events
    where organization_id = duty_row.organization_id
      and payload @> jsonb_build_object('idempotency_key', request_key);
    if event_row.id is not null then return event_row; end if;
  end if;

  insert into public.sos_events (organization_id, duty_id, driver_id, latitude, longitude, status, payload)
  values (duty_row.organization_id, duty_row.id, duty_row.driver_id, p_latitude, p_longitude, 'open', coalesce(p_payload, '{}'::jsonb))
  returning * into event_row;

  insert into public.alerts (organization_id, alert_type, severity, entity_type, entity_id, status, payload)
  values (duty_row.organization_id, 'sos', 'critical', 'duty', duty_row.id, 'open', coalesce(p_payload, '{}'::jsonb) || jsonb_build_object('sos_event_id', event_row.id));

  for operator_row in
    select m.user_id
    from public.organization_memberships m
    where m.organization_id = duty_row.organization_id
      and m.status = 'active'
      and m.role <> 'driver'::public.membership_role
  loop
    perform public.queue_push_notification(
      duty_row.organization_id,
      operator_row.user_id,
      'sos_alert',
      jsonb_build_object('duty_id', duty_row.id, 'alert_id', event_row.id, 'severity', 'critical')
    );
  end loop;

  return event_row;
end;
$$;

revoke all on function public.raise_sos(uuid, numeric, numeric, jsonb) from public;
grant execute on function public.raise_sos(uuid, numeric, numeric, jsonb) to authenticated;

-- Apply the same idempotent operation semantics to reconnect replay. The local
-- adapter has the equivalent dispatcher in backend_domain.py.
create or replace function public.enqueue_sync_operation(
  p_device_id text,
  p_idempotency_key text,
  p_entity_type text,
  p_entity_id uuid,
  p_operation text,
  p_payload jsonb default '{}'::jsonb,
  p_client_created_at timestamptz default null
)
returns public.sync_operations
language plpgsql
security definer
set search_path = public
as $$
declare
  driver_org uuid;
  sync_row public.sync_operations;
  duty_result public.duties;
  proof_result public.duty_proofs;
  expense_result public.expenses;
  point_result public.track_points;
  sos_result public.sos_events;
  operation_payload jsonb := coalesce(p_payload, '{}'::jsonb) || jsonb_build_object('idempotency_key', p_idempotency_key);
begin
  select organization_id into driver_org from public.drivers where user_id = auth.uid() and organization_id is not null limit 1;
  if driver_org is null then
    select m.organization_id into driver_org from public.organization_memberships m where m.user_id = auth.uid() and m.status = 'active' limit 1;
  end if;
  if driver_org is null then raise exception 'An organization-linked account is required'; end if;

  select * into sync_row from public.sync_operations where user_id = auth.uid() and idempotency_key = p_idempotency_key;
  if sync_row.id is not null and sync_row.status <> 'failed' then return sync_row; end if;

  if sync_row.id is null then
    insert into public.sync_operations (organization_id, user_id, device_id, idempotency_key, entity_type, entity_id, operation, status, client_created_at, payload)
    values (driver_org, auth.uid(), p_device_id, p_idempotency_key, p_entity_type, p_entity_id, p_operation, 'processing', p_client_created_at, coalesce(p_payload, '{}'::jsonb))
    returning * into sync_row;
  else
    update public.sync_operations
    set status = 'processing', error_message = null, server_processed_at = null, conflict_data = null, payload = coalesce(p_payload, '{}'::jsonb)
    where id = sync_row.id
    returning * into sync_row;
  end if;

  begin
    if p_entity_type = 'duty' and p_operation = 'status_transition' then
      select * into duty_result from public.transition_duty(p_entity_id, (p_payload->>'status')::public.duty_status, operation_payload);
      update public.sync_operations set status = 'synced', server_processed_at = now(), conflict_data = to_jsonb(duty_result) where id = sync_row.id;
    elsif p_entity_type in ('duty', 'duty_proof') and p_operation in ('proof', 'capture_proof') then
      select * into proof_result from public.capture_duty_proof(p_entity_id, coalesce(p_payload->>'proof_type', 'otp'), coalesce(p_payload->'proof_data', p_payload), p_payload->>'storage_path', p_idempotency_key);
      update public.sync_operations set status = 'synced', server_processed_at = now(), conflict_data = to_jsonb(proof_result) where id = sync_row.id;
    elsif p_entity_type in ('duty', 'expense') and p_operation = 'expense' then
      select * into expense_result from public.record_expense(p_entity_id, coalesce(p_payload->>'category', 'other'), (p_payload->>'amount_paise')::bigint, coalesce(p_payload->>'note', ''), coalesce(p_payload->'attachment', '{}'::jsonb), p_idempotency_key);
      update public.sync_operations set status = 'synced', server_processed_at = now(), conflict_data = to_jsonb(expense_result) where id = sync_row.id;
    elsif p_entity_type = 'duty' and p_operation = 'sos' then
      select * into sos_result from public.raise_sos(p_entity_id, nullif(p_payload->>'latitude', '')::numeric, nullif(p_payload->>'longitude', '')::numeric, operation_payload);
      update public.sync_operations set status = 'synced', server_processed_at = now(), conflict_data = to_jsonb(sos_result) where id = sync_row.id;
    elsif p_entity_type = 'track_point' then
      select * into point_result from public.record_track_point(p_entity_id, nullif(p_payload->>'recorded_at', '')::timestamptz, (p_payload->>'latitude')::numeric, (p_payload->>'longitude')::numeric, nullif(p_payload->>'accuracy_m', '')::numeric, nullif(p_payload->>'battery_pct', '')::numeric, coalesce(p_payload->>'source', 'driver_app'), p_idempotency_key);
      update public.sync_operations set status = 'synced', server_processed_at = now(), conflict_data = to_jsonb(point_result) where id = sync_row.id;
    else
      raise exception 'Unsupported sync operation';
    end if;
  exception when others then
    update public.sync_operations set status = 'failed', server_processed_at = now(), error_message = sqlerrm where id = sync_row.id;
  end;

  select * into sync_row from public.sync_operations where id = sync_row.id;
  return sync_row;
end;
$$;

revoke all on function public.enqueue_sync_operation(text, text, text, uuid, text, jsonb, timestamptz) from public;
grant execute on function public.enqueue_sync_operation(text, text, text, uuid, text, jsonb, timestamptz) to authenticated;
