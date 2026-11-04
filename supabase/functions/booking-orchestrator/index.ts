import { createClient, type SupabaseClient, type User } from "https://esm.sh/@supabase/supabase-js@2";

/*
 * Production boundary for the booking desk parity slice.  The browser never
 * writes lifecycle records directly: this function resolves the caller's
 * organization, applies the same relationship/action/idempotency rules as the
 * local fallback, and relies on PostgreSQL RLS for the second tenant guard.
 */
const allowedOrigin = (Deno.env.get("AXIOM_ALLOWED_ORIGIN") || Deno.env.get("AXIOM_ALLOWED_ORIGINS")?.split(",")[0] || "").trim();
const cors = {
  ...(allowedOrigin ? { "Access-Control-Allow-Origin": allowedOrigin, "Vary": "Origin" } : {}),
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info, x-request-id",
  "Access-Control-Allow-Methods": "GET, POST, PATCH, OPTIONS",
};
type Json = Record<string, any>;

type Context = { supabase: SupabaseClient; user: User; organizationId: string };
function reply(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { ...cors, "Content-Type": "application/json" } }); }
function text(value: unknown, fallback = "") { return String(value ?? fallback).trim(); }
function object(value: unknown): Json { return value && typeof value === "object" && !Array.isArray(value) ? value as Json : {}; }
function list(value: unknown): any[] { return Array.isArray(value) ? value : []; }
function now() { return new Date().toISOString(); }
function id() { return crypto.randomUUID(); }
function number(value: unknown, fallback = 0) { const result = Number(value); return Number.isFinite(result) ? result : fallback; }
function iso(value: unknown, field: string) { const date = new Date(text(value)); if (!text(value) || Number.isNaN(date.getTime())) throw new Error(`${field} must be an ISO datetime`); return date.toISOString(); }

async function authenticate(request: Request) {
  const authorization = request.headers.get("Authorization"); const url = Deno.env.get("SUPABASE_URL"); const anonKey = Deno.env.get("SUPABASE_ANON_KEY");
  if (!authorization || !url || !anonKey) throw new Error("Authenticated Supabase configuration is required");
  const bearer = authorization.replace(/^Bearer\s+/i, "");
  const supabase = createClient(url, anonKey, { global: { headers: { Authorization: `Bearer ${bearer}` } } });
  const { data, error } = await supabase.auth.getUser(bearer);
  if (error || !data.user) throw new Error("Sign in required");
  return { supabase, user: data.user as User };
}
async function resolveOrganization(supabase: SupabaseClient, user: User, requested: unknown) {
  const requestedId = text(requested);
  let query = supabase.from("organization_memberships").select("organization_id").eq("user_id", user.id).eq("status", "active").limit(20);
  if (requestedId) query = query.eq("organization_id", requestedId);
  const { data, error } = await query; if (error) throw new Error(error.message);
  if (requestedId && (data || []).some((row: Json) => String(row.organization_id) === requestedId)) return requestedId;
  if (!requestedId && (data || []).length === 1) return String(data![0].organization_id);
  if (requestedId) {
    const { data: owned } = await supabase.from("organizations").select("id").eq("id", requestedId).eq("owner_user_id", user.id).maybeSingle();
    if (owned?.id) return String(owned.id);
  }
  throw new Error("Organization access denied");
}
async function context(request: Request, envelope: Json): Promise<Context> {
  const auth = await authenticate(request);
  const organizationId = await resolveOrganization(auth.supabase, auth.user, envelope.organization_id || object(envelope.body).organization_id);
  return { ...auth, organizationId };
}
async function ownedBooking(supabase: SupabaseClient, organizationId: string, bookingId: string) {
  const { data, error } = await supabase.from("bookings").select("*").eq("organization_id", organizationId).eq("id", bookingId).maybeSingle();
  if (error) throw new Error(error.message); if (!data) throw new Error("Booking not found"); return data as Json;
}
async function action(supabase: SupabaseClient, user: User, organizationId: string, bookingId: string, actionType: string, payload: Json) {
  const key = text(payload.idempotency_key) || null;
  if (key) {
    const { data, error } = await supabase.from("booking_action_events").select("*").eq("organization_id", organizationId).eq("booking_id", bookingId).eq("action_type", actionType).eq("idempotency_key", key).maybeSingle();
    if (error) throw new Error(error.message); if (data) return { item: data, replay: true };
  }
  const { data, error } = await supabase.from("booking_action_events").insert({ organization_id: organizationId, booking_id: bookingId, action_type: actionType, payload, idempotency_key: key, actor_id: user.id }).select().single();
  if (error) throw new Error(error.message);
  return { item: data, replay: false };
}
function recurringDates(source: Json) {
  const provided = list(source.dates).map((value) => text(typeof value === "object" ? value.scheduled_at : value)).filter(Boolean);
  if (provided.length) return provided;
  const type = text(source.booking_type || source.booking_mode).toLowerCase().replace("-", "_");
  if (!(type === "monthly" || type === "multi_day") || !text(source.start_at || source.scheduled_at)) return [];
  const start = new Date(text(source.start_at || source.scheduled_at));
  if (Number.isNaN(start.getTime())) throw new Error("scheduled_at must be an ISO datetime");
  const end = text(source.end_at) ? new Date(text(source.end_at)) : null;
  if (end && Number.isNaN(end.getTime())) throw new Error("end_at must be an ISO datetime");
  const requested = Math.max(1, Math.min(365, Number(source.occurrences || (end ? 365 : 1))));
  const dates: string[] = [];
  for (let index = 0; index < requested; index += 1) {
    let point: Date;
    if (type === "monthly") {
      const monthIndex = start.getUTCMonth() + index;
      const year = start.getUTCFullYear() + Math.floor(monthIndex / 12);
      const month = monthIndex % 12;
      const day = Math.min(start.getUTCDate(), new Date(Date.UTC(year, month + 1, 0)).getUTCDate());
      point = new Date(Date.UTC(year, month, day, start.getUTCHours(), start.getUTCMinutes(), start.getUTCSeconds(), start.getUTCMilliseconds()));
    } else {
      point = new Date(start.getTime() + index * 86400000);
    }
    if (end && point > end) break;
    dates.push(point.toISOString());
  }
  return dates;
}

function normalized(source: Json, organizationId: string, parentId: string | null = null, sequence = 0, groupId: string | null = null) {
  const pickup = source.pickup && typeof source.pickup === "object" ? source.pickup : { label: source.pickup || "" };
  const dropoff = source.dropoff && typeof source.dropoff === "object" ? source.dropoff : { label: source.dropoff || "" };
  let bookingType = text(source.booking_type || source.booking_mode, "single").toLowerCase().replace("-", "_"); if (bookingType === "flat") bookingType = "flat_rate";
  if (!["single", "parent", "child", "flat_rate", "monthly", "multi_day"].includes(bookingType)) throw new Error("Invalid booking_type");
  const allotmentMode = text(source.allotment_mode, "owned").toLowerCase() === "own" ? "owned" : text(source.allotment_mode, "owned").toLowerCase();
  if (!["owned", "company_supplier", "dco", "network"].includes(allotmentMode)) throw new Error("Invalid allotment_mode");
  return {
    organization_id: organizationId,
    branch_id: source.branch_id || null,
    customer_id: source.customer_id || null,
    requesting_organization_id: source.requesting_organization_id || null,
    vendor_organization_id: source.vendor_organization_id || null,
    status: source.status || "requested",
    booking_reference: source.booking_reference || `BK-${Date.now()}-${id().slice(0, 8).toUpperCase()}`,
    passenger_name: source.passenger_name || null,
    passenger_phone: source.passenger_phone || null,
    passenger_email: source.passenger_email || null,
    pickup, dropoff, stops: Array.isArray(source.stops) ? source.stops : [],
    scheduled_at: source.scheduled_at || null,
    duty_type: source.duty_type || source.duty_type_code || "local",
    policy_context: source.policy_context || {}, source: source.source || "web", notes: source.notes || null,
    booking_type: bookingType, parent_booking_id: parentId || source.parent_booking_id || null,
    booking_group_id: groupId || source.booking_group_id || null, child_sequence: sequence || Number(source.child_sequence || 0),
    flat_rate_paise: Math.max(0, Number(source.flat_rate_paise || source.flat_rate || 0)), currency: text(source.currency, "INR").toUpperCase(),
    start_at: source.start_at || source.scheduled_at || null, end_at: source.end_at || null,
    recurrence_rule: text(source.recurrence_rule || source.recurrence), passenger_json: { ...(object(source.passenger)), ...(object(source.temporary_passenger)) },
    pricing_contract_id: source.pricing_contract_id || source.contract_id || null, pricing_snapshot: object(source.pricing_snapshot),
    confirmation_status: source.confirmation_status || (source.status === "confirmed" ? "confirmed" : "pending"), confirmed_at: source.confirmed_at || null,
    advance_paise: Math.max(0, Number(source.advance_paise || 0)), lifecycle_status: "active", allotment_mode: allotmentMode,
    vehicle_group_code: source.vehicle_group_code || source.vehicle_group || "", source_import_id: source.source_import_id || null,
  };
}
async function createBooking(ctx: Context, source: Json) {
  const key = text(source.idempotency_key);
  if (key) {
    const { data: existingKey, error: keyError } = await ctx.supabase.from("booking_request_keys").select("booking_id").eq("organization_id", ctx.organizationId).eq("idempotency_key", key).maybeSingle();
    if (keyError) throw new Error(keyError.message); if (existingKey) return { ok: true, item: await ownedBooking(ctx.supabase, ctx.organizationId, existingKey.booking_id), idempotent_replay: true };
  }
  const payload = normalized(source, ctx.organizationId);
  const { data, error } = await ctx.supabase.from("bookings").insert(payload).select().single();
  if (error) throw new Error(error.message);
  const item = data as Json;
  if (!item.booking_group_id) { const { error: groupError } = await ctx.supabase.from("bookings").update({ booking_group_id: item.id }).eq("organization_id", ctx.organizationId).eq("id", item.id); if (groupError) throw new Error(groupError.message); item.booking_group_id = item.id; }
  if (key) { const { error: keyError } = await ctx.supabase.from("booking_request_keys").insert({ organization_id: ctx.organizationId, idempotency_key: key, booking_id: item.id }); if (keyError) throw new Error(keyError.message); }
  const recorded = await action(ctx.supabase, ctx.user, ctx.organizationId, item.id, "create", { idempotency_key: key, source: source.source || "web" });
  const type = text(source.booking_type || source.booking_mode).toLowerCase().replace("-", "_");
  const dates = ["monthly", "multi_day"].includes(type) && !source.parent_booking_id ? recurringDates(source) : [];
  if (dates.length > 1) {
    const generated = await children(ctx, { ...item, booking_group_id: item.booking_group_id || item.id }, { dates: dates.slice(1) });
    return { ok: true, item: generated.parent, children: generated.items, action: recorded.item };
  }
  return { ok: true, item, action: recorded.item, children: [] };
}
async function children(ctx: Context, booking: Json, body: Json) {
  const requested = list(body.children || body.dates); if (!requested.length) requested.push({ scheduled_at: body.scheduled_at || booking.scheduled_at }); if (requested.length > 365) throw new Error("At most 365 child bookings can be created at once");
  const groupId = booking.booking_group_id || booking.id; const items = [] as Json[];
  for (const [index, value] of requested.entries()) {
    const child = typeof value === "object" ? object(value) : { scheduled_at: value };
    const source = { ...child, booking_reference: `${booking.booking_reference}-${String(index + 1).padStart(3, "0")}`, customer_id: booking.customer_id, passenger_name: child.passenger_name ?? booking.passenger_name, passenger_phone: child.passenger_phone ?? booking.passenger_phone, passenger_email: child.passenger_email ?? booking.passenger_email, pickup: child.pickup ?? booking.pickup, dropoff: child.dropoff ?? booking.dropoff, duty_type: child.duty_type ?? booking.duty_type, notes: child.notes ?? booking.notes, flat_rate_paise: child.flat_rate_paise ?? booking.flat_rate_paise, pricing_contract_id: child.pricing_contract_id ?? booking.pricing_contract_id, allotment_mode: child.allotment_mode ?? booking.allotment_mode, booking_type: "child" };
    const made = await createBooking({ ...ctx } as Context, { ...source, parent_booking_id: booking.id, booking_group_id: groupId, child_sequence: index + 1 }); items.push(made.item);
  }
  const { error } = await ctx.supabase.from("bookings").update({ booking_type: "parent", booking_group_id: groupId }).eq("organization_id", ctx.organizationId).eq("id", booking.id); if (error) throw new Error(error.message);
  const recorded = await action(ctx.supabase, ctx.user, ctx.organizationId, booking.id, "split", { ...body, child_ids: items.map((item) => item.id) });
  return { ok: true, parent: await ownedBooking(ctx.supabase, ctx.organizationId, booking.id), items, count: items.length, action: recorded.item };
}
async function pricing(ctx: Context, body: Json, booking?: Json) {
  const source = { ...(booking || {}), ...body }; const customerId = text(source.customer_id || booking?.customer_id); const supplierId = text(source.supplier_id || booking?.supplier_id); const pricingScope = text(source.pricing_scope).toLowerCase(); const contractType = pricingScope === "supplier" || (supplierId && !customerId) ? "supplier" : "customer"; const nowMs = Date.now();
  const { data: contracts, error: contractError } = await ctx.supabase.from("booking_pricing_contracts").select("*").eq("organization_id", ctx.organizationId).eq("contract_type", contractType).eq("status", "active").lte("effective_from", new Date(nowMs).toISOString()); if (contractError) throw new Error(contractError.message);
  const contract = (contracts || []).sort((a: Json, b: Json) => Number(Boolean(a.customer_id !== customerId)) - Number(Boolean(b.customer_id !== customerId)) || Number(Boolean(a.supplier_id !== supplierId)) - Number(Boolean(b.supplier_id !== supplierId)) || Number(b.version || 0) - Number(a.version || 0)).find((item: Json) => (!item.customer_id || item.customer_id === customerId) && (!item.supplier_id || item.supplier_id === supplierId)) || null;
  let rules: Json[] = []; if (contract) { const result = await ctx.supabase.from("booking_pricing_rules").select("*").eq("organization_id", ctx.organizationId).eq("contract_id", contract.id); if (result.error) throw new Error(result.error.message); rules = result.data || []; }
  const city = text(source.city || source.pickup_city || object(source.pickup).city).toLowerCase(); const group = text(source.vehicle_group || source.vehicle_group_code || booking?.vehicle_group_code).toLowerCase(); let dutyType = text(source.duty_type || booking?.duty_type, "local").toLowerCase();
  const duration = Math.max(0, Math.floor(number(source.duration_minutes))); const distance = Math.max(0, number(source.distance_km));
  let rule = rules.sort((a, b) => (Number(Boolean(b.city && b.city === city)) + Number(Boolean(b.vehicle_group && b.vehicle_group === group)) + Number(Boolean(b.duty_type && b.duty_type === dutyType))) - (Number(Boolean(a.city && a.city === city)) + Number(Boolean(a.vehicle_group && a.vehicle_group === group)) + Number(Boolean(a.duty_type && a.duty_type === dutyType)))).find((item) => (!item.city || item.city.toLowerCase() === city) && (!item.vehicle_group || item.vehicle_group.toLowerCase() === group) && (!item.duty_type || item.duty_type.toLowerCase() === dutyType)) || null;
  const requestedDutyType = dutyType;
  const switches = list(object(rule?.auto_switch).rules || object(rule?.auto_switch).thresholds); for (const item of switches) if ((item.max_km == null || distance <= number(item.max_km, distance)) && (item.max_minutes == null || duration <= number(item.max_minutes, duration))) { dutyType = text(item.duty_type || item.switch_to, dutyType).toLowerCase(); break; }
  if (dutyType !== requestedDutyType) rule = rules.find((item) => (!item.city || item.city.toLowerCase() === city) && (!item.vehicle_group || item.vehicle_group.toLowerCase() === group) && (!item.duty_type || item.duty_type.toLowerCase() === dutyType)) || rule;
  const packageMinutes = Number(source.package_minutes || rule?.package_minutes || 0); const includedKm = number(source.included_km ?? rule?.included_km); const base = Number(source.base_paise || rule?.base_paise || 0); const extraKmRate = Number(source.extra_km_paise || rule?.extra_km_paise || 0); const halfRate = Number(source.extra_half_hour_paise || rule?.extra_half_hour_paise || 0); const hourRate = Number(source.extra_hour_paise || rule?.extra_hour_paise || 0); const extraKm = Math.max(0, distance - includedKm); const extraMinutes = Math.max(0, duration - packageMinutes); const timeTotal = (halfRate ? Math.ceil(extraMinutes / 30) * halfRate : 0) + (hourRate ? Math.ceil(extraMinutes / 60) * hourRate : 0); const flat = Number(source.flat_rate_paise || source.flat_rate || 0); const transport = flat > 0 ? flat : base + Math.round(extraKm * extraKmRate) + timeTotal + Number(source.waiting_paise || rule?.waiting_paise || 0) + Number(source.allowance_paise || rule?.allowance_paise || 0);
  let fuelSurcharge = 0; let fuelDetails: Json = { amount_paise: 0, status: "not_configured" };
  let fuelQuery = ctx.supabase.from("customer_fuel_surcharge_rules").select("*").eq("organization_id", ctx.organizationId).eq("status", "active").lte("effective_from", new Date(nowMs).toISOString()).limit(100); const fuelResult = await fuelQuery; if (fuelResult.error) throw new Error(fuelResult.error.message);
  const fuelRule = (fuelResult.data || []).sort((a: Json, b: Json) => Number(Boolean(a.customer_id !== customerId)) - Number(Boolean(b.customer_id !== customerId)) || Number(Boolean(a.vehicle_group)) - Number(Boolean(b.vehicle_group))).find((item: Json) => (!item.customer_id || item.customer_id === customerId) && (!item.vehicle_group || item.vehicle_group.toLowerCase() === group));
  if (fuelRule) { const rates = await ctx.supabase.from("fuel_rate_history").select("*").eq("organization_id", ctx.organizationId).eq("fuel_type", fuelRule.fuel_type).lte("effective_at", new Date(nowMs).toISOString()).order("effective_at", { ascending: false }).limit(100); if (rates.error) throw new Error(rates.error.message); const fuelRate = (rates.data || []).find((item: Json) => !item.city || item.city.toLowerCase() === city) || null; if (fuelRate) { const litres = distance / Math.max(0.1, number(fuelRule.average_km_per_litre, 10)); fuelSurcharge = fuelRule.surcharge_mode === "percent" ? Math.round(transport * Number(fuelRule.rate_percent_bps || 0) / 10000) : Math.round(litres * Math.max(Number(fuelRate.price_paise || 0) - Number(fuelRule.included_fuel_price_paise || 0), 0)); fuelDetails = { amount_paise: fuelSurcharge, status: "calculated", rule_id: fuelRule.id, fuel_rate_id: fuelRate.id, distance_km: distance, litres, actual_price_paise: fuelRate.price_paise, agreed_price_paise: fuelRule.included_fuel_price_paise }; } }
  const result = { contract_id: contract?.id || null, rule_id: rule?.id || null, duty_type: dutyType, total_paise: transport + fuelSurcharge, breakdown: { flat_rate_paise: flat, base_paise: base, duration_minutes: duration, distance_km: distance, package_minutes: packageMinutes, included_km: includedKm, extra_km: extraKm, extra_time_paise: timeTotal, fuel_surcharge: fuelDetails, automatic_duty_type_switch: dutyType !== text(source.duty_type || booking?.duty_type, "local").toLowerCase() } };
  if (body.idempotency_key) { const existing = await ctx.supabase.from("booking_pricing_quotes").select("*").eq("organization_id", ctx.organizationId).eq("idempotency_key", body.idempotency_key).maybeSingle(); if (existing.error) throw new Error(existing.error.message); if (existing.data) return { ok: true, item: existing.data, idempotent_replay: true }; }
  const inserted = await ctx.supabase.from("booking_pricing_quotes").insert({ organization_id: ctx.organizationId, booking_id: booking?.id || body.booking_id || null, contract_id: result.contract_id, duty_type: result.duty_type, total_paise: result.total_paise, breakdown: result.breakdown, idempotency_key: body.idempotency_key || null, created_by: ctx.user.id }).select().single(); if (inserted.error) throw new Error(inserted.error.message);
  if (booking?.id) { const updated = await ctx.supabase.from("bookings").update({ pricing_contract_id: result.contract_id, pricing_snapshot: result, duty_type: result.duty_type }).eq("organization_id", ctx.organizationId).eq("id", booking.id); if (updated.error) throw new Error(updated.error.message); }
  return { ok: true, item: { ...result, id: inserted.data.id, booking_id: booking?.id || body.booking_id || null } };
}
async function dispatch(ctx: Context, booking: Json, body: Json, reallot = false) {
  let mode = text(body.allotment_mode || body.mode, booking.allotment_mode || "owned").toLowerCase(); if (mode === "own") mode = "owned"; if (!["owned", "company_supplier", "dco", "network"].includes(mode)) throw new Error("Invalid allotment mode");
  if (reallot) { const duties = await ctx.supabase.from("duties").select("id").eq("organization_id", ctx.organizationId).eq("booking_id", booking.id).not("status", "in", "(completed,cancelled)"); if (duties.error) throw new Error(duties.error.message); for (const duty of duties.data || []) { await ctx.supabase.from("duties").update({ status: "cancelled" }).eq("organization_id", ctx.organizationId).eq("id", duty.id); await ctx.supabase.from("capacity_locks").update({ status: "released" }).eq("organization_id", ctx.organizationId).eq("booking_id", booking.id).eq("status", "held"); } }
  const key = text(body.idempotency_key); if (key) { const existing = await ctx.supabase.from("booking_dispatches").select("*").eq("organization_id", ctx.organizationId).eq("idempotency_key", key).maybeSingle(); if (existing.error) throw new Error(existing.error.message); if (existing.data) return { ok: true, item: existing.data, idempotent_replay: true }; }
  const supplierId = text(body.supplier_id) || null; const driverId = text(body.driver_id) || null; const vehicleId = text(body.vehicle_id) || null; const networkProfileId = text(body.network_vendor_profile_id || body.vendor_profile_id) || null;
  if (mode === "network") {
    if (!networkProfileId) throw new Error("network_vendor_profile_id is required for Network allotment");
    const profile = await ctx.supabase.from("network_vendor_profiles").select("id,status,organization_id,invite_id").eq("id", networkProfileId).eq("organization_id", ctx.organizationId).eq("status", "active").maybeSingle();
    if (profile.error) throw new Error(profile.error.message); if (!profile.data?.id || !profile.data.invite_id) throw new Error("Network allotment requires an active invited vendor profile");
    const invite = await ctx.supabase.from("network_invites").select("status,expires_at").eq("id", profile.data.invite_id).eq("organization_id", ctx.organizationId).maybeSingle();
    if (invite.error) throw new Error(invite.error.message); if (invite.data?.status !== "accepted" || (invite.data.expires_at && new Date(invite.data.expires_at) <= new Date())) throw new Error("Network allotment requires an accepted, unexpired invite");
  }
  const status = mode === "owned" && driverId && vehicleId ? "dispatched" : "requested";
  const inserted = await ctx.supabase.from("booking_dispatches").insert({ organization_id: ctx.organizationId, booking_id: booking.id, allotment_mode: mode, supplier_id: supplierId, driver_id: driverId, vehicle_id: vehicleId, network_vendor_profile_id: networkProfileId, status, response_status: mode === "owned" ? "accepted" : "pending", dispatch_details: { ...body, network_vendor_profile_id: networkProfileId }, expires_at: body.expires_at || new Date(Date.now() + 7200000).toISOString(), idempotency_key: key, created_by: ctx.user.id }).select().single(); if (inserted.error) throw new Error(inserted.error.message);
  let duty = null;
  if (mode === "owned" && driverId && vehicleId) { const made = await ctx.supabase.from("duties").insert({ organization_id: ctx.organizationId, booking_id: booking.id, driver_id: driverId, vehicle_id: vehicleId, status: "assigned", reporting_at: booking.scheduled_at, allotment_mode: mode, dispatch_id: inserted.data.id }).select().single(); if (made.error) throw new Error(made.error.message); duty = made.data; }
  const updated = await ctx.supabase.from("bookings").update({ status: "assigned", allotment_mode: mode }).eq("organization_id", ctx.organizationId).eq("id", booking.id).select().single(); if (updated.error) throw new Error(updated.error.message);
  const recorded = await action(ctx.supabase, ctx.user, ctx.organizationId, booking.id, reallot ? "reallot" : "dispatch", { ...body, dispatch_id: inserted.data.id });
  return { ok: true, item: inserted.data, booking: updated.data, duty, action: recorded.item };
}
async function bookingRoute(ctx: Context, path: string, method: string, body: Json, query: Json) {
  if (path === "/api/bookings" && method === "POST") return createBooking(ctx, body);
  if (path === "/api/bookings/import" && method === "POST") {
    const key = text(body.idempotency_key) || null;
    if (key) { const replay = await ctx.supabase.from("booking_imports").select("*").eq("organization_id", ctx.organizationId).eq("idempotency_key", key).maybeSingle(); if (replay.error) throw new Error(replay.error.message); if (replay.data) return { ok: true, item: replay.data, idempotent_replay: true }; }
    const rows = list(body.bookings || body.rows); if (!rows.length || rows.length > 500) throw new Error("Provide between 1 and 500 booking rows");
    const started = await ctx.supabase.from("booking_imports").insert({ organization_id: ctx.organizationId, status: "processing", source_format: text(body.source_format, "json"), requested_count: rows.length, rows, idempotency_key: key, created_by: ctx.user.id }).select().single(); if (started.error) throw new Error(started.error.message);
    const results = []; let imported = 0;
    for (const [index, row] of rows.entries()) { try { const created = await createBooking(ctx, { ...object(row), source_import_id: started.data.id }); imported += 1; results.push({ row: index + 1, status: "imported", item: created.item }); } catch (error) { results.push({ row: index + 1, status: "error", message: error instanceof Error ? error.message : String(error) }); } }
    const status = imported === rows.length ? "completed" : imported ? "partial" : "failed"; const updated = await ctx.supabase.from("booking_imports").update({ status, imported_count: imported, failed_count: rows.length - imported, result: { rows: results } }).eq("organization_id", ctx.organizationId).eq("id", started.data.id).select().single(); if (updated.error) throw new Error(updated.error.message);
    return { ok: true, item: updated.data, rows: results, imported, failed: rows.length - imported };
  }
  const bookingMatch = path.match(/^\/api\/bookings\/([^/]+)(?:\/(.*))?$/); if (!bookingMatch) return null;
  const bookingId = bookingMatch[1]; const suffix = bookingMatch[2] || ""; const booking = await ownedBooking(ctx.supabase, ctx.organizationId, bookingId);
  if (!suffix && method === "GET") return { ok: true, item: booking };
  if (!suffix && method === "PATCH") {
    const patch: Json = {};
    for (const key of ["customer_id", "passenger_name", "passenger_phone", "passenger_email", "scheduled_at", "duty_type", "notes", "pickup", "dropoff", "booking_type", "parent_booking_id", "booking_group_id", "child_sequence", "flat_rate_paise", "currency", "start_at", "end_at", "recurrence_rule", "pricing_contract_id", "pricing_snapshot", "confirmation_status", "confirmed_at", "advance_paise", "allotment_mode", "vehicle_group_code"]) if (body[key] !== undefined) patch[key] = body[key];
    if (!Object.keys(patch).length) throw new Error("No booking fields supplied");
    const updated = await ctx.supabase.from("bookings").update(patch).eq("organization_id", ctx.organizationId).eq("id", bookingId).select().single(); if (updated.error) throw new Error(updated.error.message);
    const recorded = await action(ctx.supabase, ctx.user, ctx.organizationId, bookingId, "update", { fields: Object.keys(patch), idempotency_key: body.idempotency_key || null });
    return { ok: true, item: updated.data, action: recorded.item };
  }
  if (suffix === "children" && method === "GET") { const rows = await ctx.supabase.from("bookings").select("*").eq("organization_id", ctx.organizationId).or(`parent_booking_id.eq.${bookingId},booking_group_id.eq.${booking.booking_group_id || bookingId}`).neq("id", bookingId).order("child_sequence"); if (rows.error) throw new Error(rows.error.message); return { ok: true, items: rows.data || [] }; }
  if (["children", "split"].includes(suffix) && method === "POST") return children(ctx, booking, body);
  if (["confirm", "confirmation"].includes(suffix) && method === "POST") { const recorded = await action(ctx.supabase, ctx.user, ctx.organizationId, bookingId, "confirm", body); if (!recorded.replay) { const updated = await ctx.supabase.from("bookings").update({ status: "confirmed", confirmation_status: "confirmed", confirmed_at: now() }).eq("organization_id", ctx.organizationId).eq("id", bookingId); if (updated.error) throw new Error(updated.error.message); } return { ok: true, item: await ownedBooking(ctx.supabase, ctx.organizationId, bookingId), action: recorded.item, idempotent_replay: recorded.replay }; }
  if (suffix === "unconfirm" && method === "POST") { const recorded = await action(ctx.supabase, ctx.user, ctx.organizationId, bookingId, "unconfirm", body); if (!recorded.replay) await ctx.supabase.from("bookings").update({ status: "requested", confirmation_status: "pending", confirmed_at: null }).eq("organization_id", ctx.organizationId).eq("id", bookingId); return { ok: true, item: await ownedBooking(ctx.supabase, ctx.organizationId, bookingId), action: recorded.item }; }
  if (suffix === "delete" && method === "POST") { const recorded = await action(ctx.supabase, ctx.user, ctx.organizationId, bookingId, "delete", body); if (!recorded.replay) await ctx.supabase.from("bookings").update({ status: "cancelled", lifecycle_status: "deleted", deleted_at: now() }).eq("organization_id", ctx.organizationId).eq("id", bookingId); return { ok: true, item: await ownedBooking(ctx.supabase, ctx.organizationId, bookingId), action: recorded.item }; }
  if (suffix === "restore" && method === "POST") { const recorded = await action(ctx.supabase, ctx.user, ctx.organizationId, bookingId, "restore", body); if (!recorded.replay) await ctx.supabase.from("bookings").update({ status: "requested", lifecycle_status: "active", deleted_at: null }).eq("organization_id", ctx.organizationId).eq("id", bookingId); return { ok: true, item: await ownedBooking(ctx.supabase, ctx.organizationId, bookingId), action: recorded.item }; }
  if (suffix === "print" && method === "GET") { const recorded = await action(ctx.supabase, ctx.user, ctx.organizationId, bookingId, "print", body); return { ok: true, format: "html", item: booking, action: recorded.item, print_html: `<article><h1>${booking.booking_reference}</h1><p>${booking.passenger_name || ""}</p><p>${booking.scheduled_at || ""}</p></article>` }; }
  if (suffix === "briefing") { if (method === "GET") { const rows = await ctx.supabase.from("booking_briefings").select("*").eq("organization_id", ctx.organizationId).eq("booking_id", bookingId).order("version", { ascending: false }); if (rows.error) throw new Error(rows.error.message); return { ok: true, items: rows.data || [] }; } const latest = await ctx.supabase.from("booking_briefings").select("version").eq("organization_id", ctx.organizationId).eq("booking_id", bookingId).order("version", { ascending: false }).limit(1).maybeSingle(); if (latest.error) throw new Error(latest.error.message); const inserted = await ctx.supabase.from("booking_briefings").insert({ organization_id: ctx.organizationId, booking_id: bookingId, version: Number(latest.data?.version || 0) + 1, briefing: body.briefing || body, created_by: ctx.user.id }).select().single(); if (inserted.error) throw new Error(inserted.error.message); return { ok: true, item: inserted.data }; }
  if (suffix === "advance" && method === "POST") { const advanceKey = text(body.idempotency_key); if (advanceKey) { const replay = await ctx.supabase.from("booking_advances").select("*").eq("organization_id", ctx.organizationId).eq("idempotency_key", advanceKey).maybeSingle(); if (replay.error) throw new Error(replay.error.message); if (replay.data) return { ok: true, item: replay.data, idempotent_replay: true }; } const inserted = await ctx.supabase.from("booking_advances").insert({ organization_id: ctx.organizationId, booking_id: bookingId, amount_paise: Math.max(0, Number(body.amount_paise || body.amount || 0)), currency: text(body.currency, "INR"), mode: text(body.mode, "manual"), reference: text(body.reference), payload: body, idempotency_key: advanceKey || null, created_by: ctx.user.id }).select().single(); if (inserted.error) throw new Error(inserted.error.message); const updated = await ctx.supabase.from("bookings").update({ advance_paise: Number(booking.advance_paise || 0) + Number(inserted.data.amount_paise || 0) }).eq("organization_id", ctx.organizationId).eq("id", bookingId); if (updated.error) throw new Error(updated.error.message); return { ok: true, item: inserted.data }; }
  if (suffix === "attachments" && method === "GET") { const rows = await ctx.supabase.from("booking_attachments").select("*").eq("organization_id", ctx.organizationId).eq("booking_id", bookingId).order("created_at", { ascending: false }); if (rows.error) throw new Error(rows.error.message); return { ok: true, items: rows.data || [] }; }
  if (suffix === "attachments" && method === "POST") { const raw = text(body.content || body.data); const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(raw)); const sha256 = Array.from(new Uint8Array(digest)).map((value) => value.toString(16).padStart(2, "0")).join(""); const inserted = await ctx.supabase.from("booking_attachments").insert({ organization_id: ctx.organizationId, booking_id: bookingId, filename: text(body.filename, "attachment"), content_type: text(body.content_type, "application/octet-stream"), storage_path: text(body.storage_path, `bookings/${bookingId}/${id()}`), sha256, size_bytes: new TextEncoder().encode(raw).byteLength, metadata: object(body.metadata), created_by: ctx.user.id }).select().single(); if (inserted.error) throw new Error(inserted.error.message); return { ok: true, item: inserted.data }; }
  if (suffix === "export" && method === "GET") { const rows = [booking]; const fields = ["id", "booking_reference", "status", "booking_type", "parent_booking_id", "scheduled_at", "start_at", "end_at", "duty_type", "passenger_name", "passenger_phone", "customer_id", "flat_rate_paise", "advance_paise", "allotment_mode"]; const csv = [fields.join(","), ...rows.map((row) => fields.map((field) => JSON.stringify(row[field] ?? "")).join(","))].join("\n"); await action(ctx.supabase, ctx.user, ctx.organizationId, bookingId, "export", { format: "csv" }); return { ok: true, format: "csv", filename: `${booking.booking_reference}.csv`, content: csv, count: rows.length }; }
  if (suffix === "allot-all" && method === "POST") { const childrenRows = await ctx.supabase.from("bookings").select("*").eq("organization_id", ctx.organizationId).eq("booking_group_id", booking.booking_group_id || booking.id).neq("id", booking.id).order("child_sequence"); if (childrenRows.error) throw new Error(childrenRows.error.message); const targets = [booking, ...(childrenRows.data || [])]; const items = []; for (const target of targets) items.push(await dispatch(ctx, target, { ...body, idempotency_key: body.idempotency_key ? `${body.idempotency_key}:${target.id}` : undefined })); return { ok: true, booking_id: bookingId, items, count: items.length }; }
  if (["reallot", "re-allot"].includes(suffix) && method === "POST") return dispatch(ctx, booking, body, true);
  if (["dispatch", "supplier-dispatch"].includes(suffix) && method === "POST") return dispatch(ctx, booking, body);
  if (suffix === "dispatches" && method === "GET") { const rows = await ctx.supabase.from("booking_dispatches").select("*").eq("organization_id", ctx.organizationId).eq("booking_id", bookingId).order("updated_at", { ascending: false }); if (rows.error) throw new Error(rows.error.message); return { ok: true, items: rows.data || [] }; }
  if (suffix === "temporary-passenger" && method === "POST") { const passenger = object(body.passenger || body); const inserted = await ctx.supabase.from("temporary_passengers").insert({ organization_id: ctx.organizationId, customer_id: booking.customer_id, name: text(passenger.name || passenger.passenger_name), phone: text(passenger.phone || passenger.passenger_phone), email: text(passenger.email || passenger.passenger_email), metadata: passenger, expires_at: body.expires_at || new Date(Date.now() + 86400000).toISOString(), created_by: ctx.user.id }).select().single(); if (inserted.error) throw new Error(inserted.error.message); await ctx.supabase.from("bookings").update({ temporary_passenger_id: inserted.data.id, passenger_name: inserted.data.name, passenger_phone: inserted.data.phone, passenger_email: inserted.data.email, passenger_json: passenger }).eq("organization_id", ctx.organizationId).eq("id", bookingId); return { ok: true, item: inserted.data }; }
  if (suffix === "temporary-allotment" && method === "POST") { const mode = text(body.allotment_mode || body.mode, "owned"); const inserted = await ctx.supabase.from("temporary_allotments").insert({ organization_id: ctx.organizationId, booking_id: bookingId, allotment_mode: mode, supplier_id: body.supplier_id || null, driver_id: body.driver_id || null, vehicle_id: body.vehicle_id || null, details: body, expires_at: body.expires_at || new Date(Date.now() + 86400000).toISOString(), created_by: ctx.user.id }).select().single(); if (inserted.error) throw new Error(inserted.error.message); return { ok: true, item: inserted.data }; }
  if (suffix === "pricing" && method === "POST") return pricing(ctx, body, booking);
  if (suffix === "actions" && method === "GET") { const rows = await ctx.supabase.from("booking_action_events").select("*").eq("organization_id", ctx.organizationId).eq("booking_id", bookingId).order("created_at", { ascending: false }); if (rows.error) throw new Error(rows.error.message); return { ok: true, items: rows.data || [] }; }
  return null;
}
async function globalRoute(ctx: Context, path: string, method: string, body: Json, query: Json) {
  if (path === "/api/bookings/imports" && method === "GET") { const rows = await ctx.supabase.from("booking_imports").select("*").eq("organization_id", ctx.organizationId).order("created_at", { ascending: false }); if (rows.error) throw new Error(rows.error.message); return { ok: true, items: rows.data || [], count: (rows.data || []).length }; }
  if (path === "/api/pricing/contracts" && method === "GET") { const rows = await ctx.supabase.from("booking_pricing_contracts").select("*").eq("organization_id", ctx.organizationId).order("updated_at", { ascending: false }); if (rows.error) throw new Error(rows.error.message); return { ok: true, items: rows.data || [] }; }
  if (path === "/api/pricing/contracts" && method === "POST") { const payload = { organization_id: ctx.organizationId, contract_type: text(body.contract_type, "customer"), customer_id: body.customer_id || null, supplier_id: body.supplier_id || null, name: text(body.name, "Contract"), version: Number(body.version || 1), status: text(body.status, "active"), effective_from: body.effective_from || now(), effective_to: body.effective_to || null, currency: text(body.currency, "INR").toUpperCase(), terms: object(body.terms), created_by: ctx.user.id }; const inserted = await ctx.supabase.from("booking_pricing_contracts").upsert((body.id ? { ...payload, id: body.id } : payload) as any, { onConflict: "id" }).select().single(); if (inserted.error) throw new Error(inserted.error.message); return { ok: true, item: inserted.data }; }
  const ruleMatch = path.match(/^\/api\/pricing\/contracts\/([^/]+)\/rules$/); if (ruleMatch) { if (method === "GET") { const rows = await ctx.supabase.from("booking_pricing_rules").select("*").eq("organization_id", ctx.organizationId).eq("contract_id", ruleMatch[1]); if (rows.error) throw new Error(rows.error.message); return { ok: true, items: rows.data || [] }; } const payload = { organization_id: ctx.organizationId, contract_id: ruleMatch[1], city: text(body.city).toLowerCase(), vehicle_group: text(body.vehicle_group).toLowerCase(), duty_type: text(body.duty_type).toLowerCase(), package_minutes: Number(body.package_minutes || 0), included_km: number(body.included_km), base_paise: Number(body.base_paise || 0), extra_km_paise: Number(body.extra_km_paise || 0), extra_hour_paise: Number(body.extra_hour_paise || 0), extra_half_hour_paise: Number(body.extra_half_hour_paise || 0), waiting_paise: Number(body.waiting_paise || 0), allowance_paise: Number(body.allowance_paise || 0), auto_switch: object(body.auto_switch), extras: object(body.extras) }; const inserted = await ctx.supabase.from("booking_pricing_rules").insert((body.id ? { ...payload, id: body.id } : payload) as any).select().single(); if (inserted.error) throw new Error(inserted.error.message); return { ok: true, item: inserted.data }; }
  if (path === "/api/pricing/quote" && method === "POST") { const booking = body.booking_id ? await ownedBooking(ctx.supabase, ctx.organizationId, text(body.booking_id)) : undefined; return pricing(ctx, body, booking); }
  if (path === "/api/fuel-rates" && method === "GET") { const rows = await ctx.supabase.from("fuel_rate_history").select("*").eq("organization_id", ctx.organizationId).order("effective_at", { ascending: false }); if (rows.error) throw new Error(rows.error.message); return { ok: true, items: rows.data || [] }; }
  if (path === "/api/fuel-rates" && method === "POST") { const inserted = await ctx.supabase.from("fuel_rate_history").insert({ organization_id: ctx.organizationId, city: text(body.city).toLowerCase(), fuel_type: text(body.fuel_type, "petrol").toLowerCase(), price_paise: Number(body.price_paise || 0), effective_at: body.effective_at || now(), source: text(body.source, "manual"), created_by: ctx.user.id }).select().single(); if (inserted.error) throw new Error(inserted.error.message); return { ok: true, item: inserted.data }; }
  if (path === "/api/fuel-surcharge-rules" && method === "GET") { const rows = await ctx.supabase.from("customer_fuel_surcharge_rules").select("*").eq("organization_id", ctx.organizationId).order("updated_at", { ascending: false }); if (rows.error) throw new Error(rows.error.message); return { ok: true, items: rows.data || [] }; }
  if (path === "/api/fuel-surcharge-rules" && method === "POST") { const inserted = await ctx.supabase.from("customer_fuel_surcharge_rules").insert({ organization_id: ctx.organizationId, customer_id: body.customer_id || null, contract_id: body.contract_id || null, vehicle_group: text(body.vehicle_group).toLowerCase(), fuel_type: text(body.fuel_type, "petrol").toLowerCase(), included_fuel_price_paise: Number(body.included_fuel_price_paise || 0), average_km_per_litre: number(body.average_km_per_litre, 10), surcharge_mode: text(body.surcharge_mode, "difference"), rate_percent_bps: Number(body.rate_percent_bps || 0), status: text(body.status, "active"), effective_from: body.effective_from || now(), effective_to: body.effective_to || null, created_by: ctx.user.id }).select().single(); if (inserted.error) throw new Error(inserted.error.message); return { ok: true, item: inserted.data }; }
  if (path === "/api/booking-dispatches" && method === "GET") { const rows = await ctx.supabase.from("booking_dispatches").select("*").eq("organization_id", ctx.organizationId).order("updated_at", { ascending: false }); if (rows.error) throw new Error(rows.error.message); return { ok: true, items: rows.data || [] }; }
  const responseMatch = path.match(/^\/api\/booking-dispatches\/([^/]+)\/respond$/); if (responseMatch && method === "POST") { const responseStatus = text(body.response_status || body.status, "accepted"); if (!["accepted", "rejected", "expired", "countered"].includes(responseStatus)) throw new Error("Invalid response_status"); const updated = await ctx.supabase.from("booking_dispatches").update({ response_status: responseStatus, status: responseStatus === "accepted" ? "accepted" : responseStatus === "rejected" ? "rejected" : "requested", dispatch_details: body }).eq("organization_id", ctx.organizationId).eq("id", responseMatch[1]).select().single(); if (updated.error) throw new Error(updated.error.message); return { ok: true, item: updated.data }; }
  const arrivalMatch = path.match(/^\/api\/duties\/([^/]+)\/arrival$/); if (arrivalMatch && method === "POST") { const duty = await ctx.supabase.from("duties").select("*").eq("organization_id", ctx.organizationId).eq("id", arrivalMatch[1]).maybeSingle(); if (duty.error) throw new Error(duty.error.message); if (!duty.data) throw new Error("Duty not found"); if (body.idempotency_key) { const replay = await ctx.supabase.from("duty_events").select("*").eq("organization_id", ctx.organizationId).eq("duty_id", arrivalMatch[1]).eq("idempotency_key", body.idempotency_key).maybeSingle(); if (replay.error) throw new Error(replay.error.message); if (replay.data) return { ok: true, item: duty.data, event: replay.data, idempotent_replay: true }; } const event = await ctx.supabase.from("duty_events").insert({ organization_id: ctx.organizationId, duty_id: arrivalMatch[1], event_type: "arrival", event_at: body.arrival_at || now(), source: text(body.source, "web"), payload: body, idempotency_key: body.idempotency_key || null, created_by: ctx.user.id }).select().single(); if (event.error) throw new Error(event.error.message); const updated = await ctx.supabase.from("duties").update({ arrival_at: body.arrival_at || now(), arrival_status: text(body.arrival_status, "arrived") }).eq("organization_id", ctx.organizationId).eq("id", arrivalMatch[1]).select().single(); if (updated.error) throw new Error(updated.error.message); return { ok: true, item: updated.data, event: event.data }; }
  if (path === "/api/temporary-passengers" && method === "GET") { const rows = await ctx.supabase.from("temporary_passengers").select("*").eq("organization_id", ctx.organizationId).order("created_at", { ascending: false }); if (rows.error) throw new Error(rows.error.message); return { ok: true, items: rows.data || [] }; }
  if (path === "/api/temporary-allotments" && method === "GET") { const rows = await ctx.supabase.from("temporary_allotments").select("*").eq("organization_id", ctx.organizationId).order("created_at", { ascending: false }); if (rows.error) throw new Error(rows.error.message); return { ok: true, items: rows.data || [] }; }
  return null;
}
async function handle(request: Request) {
  if (request.method === "OPTIONS") return new Response("ok", { headers: cors });
  const envelope = object(await request.json()); const ctx = await context(request, envelope); const path = text(envelope.path); const method = text(envelope.method, request.method).toUpperCase(); const body = object(envelope.body); const query = object(envelope.query);
  const global = await globalRoute(ctx, path, method, body, query); if (global !== null) return global;
  const booking = await bookingRoute(ctx, path, method, body, query); if (booking !== null) return booking;
  throw new Error(`Booking route not found: ${method} ${path}`);
}
Deno.serve(async (request) => { try { return reply(await handle(request)); } catch (error) { return reply({ ok: false, error: error instanceof Error ? error.message : String(error || "Booking request failed") }, 400); } });
