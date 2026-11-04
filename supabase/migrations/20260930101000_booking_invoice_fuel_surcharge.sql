-- Replace the finance invoice RPC with the surcharge-aware version.  This is
-- deliberately a follow-on migration so existing invoice-run callers keep the
-- same function signature and idempotency contract.
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
  base_total bigint;
  total bigint;
  fuel_surcharge bigint;
  fuel_distance numeric;
  fuel_litres numeric;
  actual_fuel_price bigint;
  agreed_fuel_price bigint;
  average_km numeric;
  fuel_rule record;
  fuel_rule_id uuid;
  fuel_rate record;
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
    select d.id, d.booking_id, b.customer_id, b.pickup, b.vehicle_group_code, d.calculation_snapshot
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
    base_total := coalesce(nullif(snapshot->>'total_paise','')::bigint, subtotal + tax);
    if base_total <= 0 then continue; end if;
    fuel_surcharge := 0;
    fuel_rule_id := null;
    fuel_distance := coalesce(nullif(snapshot->>'distance_km','')::numeric, nullif(snapshot->>'distance','')::numeric, 0);
    select * into fuel_rule
      from public.customer_fuel_surcharge_rules r
     where r.organization_id = p_organization_id and r.status = 'active'
       and r.effective_from <= now()
       and (r.effective_to is null or r.effective_to >= now())
       and (r.customer_id is null or r.customer_id = duty_row.customer_id)
       and (r.vehicle_group = '' or r.vehicle_group = duty_row.vehicle_group_code)
     order by (r.customer_id is null), (r.vehicle_group = ''), r.effective_from desc
     limit 1;
    if found then
      fuel_rule_id := fuel_rule.id;
      select * into fuel_rate
        from public.fuel_rate_history f
       where f.organization_id = p_organization_id and f.fuel_type = fuel_rule.fuel_type
         and f.effective_at <= now()
         and (f.city = '' or lower(f.city) = lower(coalesce(duty_row.pickup->>'city', duty_row.pickup->>'label','')))
       order by (f.city = ''), f.effective_at desc
       limit 1;
      if found then
        average_km := greatest(coalesce(fuel_rule.average_km_per_litre, 10), 0.1);
        fuel_litres := fuel_distance / average_km;
        actual_fuel_price := fuel_rate.price_paise;
        agreed_fuel_price := fuel_rule.included_fuel_price_paise;
        if fuel_rule.surcharge_mode = 'percent' then
          fuel_surcharge := round(greatest(coalesce(snapshot->>'subtotal_paise','0')::numeric, 0) * fuel_rule.rate_percent_bps / 10000)::bigint;
        else
          fuel_surcharge := round(fuel_litres * greatest(actual_fuel_price - agreed_fuel_price, 0))::bigint;
        end if;
      end if;
    end if;
    total := base_total + fuel_surcharge;
    subtotal := subtotal + fuel_surcharge;
    invoice_number := coalesce(nullif(p_payload->>'invoice_number',''), 'INV-' || to_char(current_date, 'YYYY') || '-' || lpad((select count(*) + 1 from public.invoices where organization_id = p_organization_id)::text, 4, '0'));
    if p_mode = 'per_duty' then invoice_number := invoice_number || '-' || right(duty_row.id::text, 8); end if;
    insert into public.invoices(organization_id, customer_id, booking_id, invoice_number, status, subtotal_paise, tax_paise, total_paise, fuel_surcharge_paise, pricing_snapshot, invoice_type, due_at, immutable_snapshot, created_by, issued_at)
    values (p_organization_id, duty_row.customer_id, duty_row.booking_id, invoice_number, 'draft', subtotal, tax, total, fuel_surcharge, jsonb_build_object('fuel_surcharge_paise', fuel_surcharge, 'fuel_rule_id', fuel_rule_id), p_mode, due_at, snapshot, p_actor, case when p_mode = 'proforma' then null else now() end)
    returning id into invoice_id;
    insert into public.invoice_lines(invoice_id, description, quantity, unit_paise, amount_paise, source_entity_type, source_entity_id)
    select invoice_id, coalesce(line->>'label','Duty service'), coalesce(nullif(line->>'quantity','')::numeric, 1), coalesce(nullif(line->>'unit_paise','')::bigint,0), coalesce(nullif(line->>'amount_paise','')::bigint,0), 'duty', duty_row.id
    from jsonb_array_elements(coalesce(snapshot->'lines','[]'::jsonb)) line;
    if not found then insert into public.invoice_lines(invoice_id, description, quantity, unit_paise, amount_paise, source_entity_type, source_entity_id) values (invoice_id, 'Duty service', 1, base_total, base_total, 'duty', duty_row.id); end if;
    if fuel_surcharge > 0 then
      insert into public.invoice_lines(invoice_id, description, quantity, unit_paise, amount_paise, source_entity_type, source_entity_id) values (invoice_id, 'Fuel surcharge', 1, fuel_surcharge, fuel_surcharge, 'fuel_surcharge', duty_row.id);
    end if;
    generated := generated + 1;
    if p_mode <> 'per_duty' then exit; end if;
  end loop;
  update public.invoice_runs set requested_count = requested, generated_count = generated, failed_count = greatest(requested-generated,0), status = case when generated = 0 then 'failed' when requested > generated then 'partial' else 'completed' end, updated_at = now() where id = run_row.id returning * into run_row;
  return jsonb_build_object('ok', true, 'run', to_jsonb(run_row), 'generated_count', generated);
end;
$$;

grant execute on function public.generate_invoice_run(uuid, uuid, text, jsonb, text) to authenticated;
