import { createClient, type SupabaseClient, type User } from "https://esm.sh/@supabase/supabase-js@2";

/*
 * Authenticated production boundary for the operational parity slice.
 *
 * Booking writes remain subject to the corporate PostgreSQL trigger when an
 * account is active. Duty closure uses submit_duty_closure so a driver can
 * submit odometers and evidence without receiving broad table-write access.
 */
const allowedOrigin = (Deno.env.get("AXIOM_ALLOWED_ORIGIN") || Deno.env.get("AXIOM_ALLOWED_ORIGINS")?.split(",")[0] || "").trim();
const cors = {
  ...(allowedOrigin ? { "Access-Control-Allow-Origin": allowedOrigin, "Vary": "Origin" } : {}),
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

type Json = Record<string, any>;

function reply(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { ...cors, "Content-Type": "application/json" } });
}
function message(error: unknown) { return error instanceof Error ? error.message : String(error || "Operations request failed"); }
function text(value: unknown, fallback = "") { return String(value ?? fallback).trim(); }
function list(value: unknown): any[] { return Array.isArray(value) ? value : []; }
function object(value: unknown): Json { return value && typeof value === "object" && !Array.isArray(value) ? value as Json : {}; }
function iso(value: Date) { return value.toISOString(); }
function token() { return crypto.randomUUID(); }
function monthAdd(value: Date, count: number) {
  const next = new Date(value.getTime());
  const day = next.getUTCDate();
  next.setUTCDate(1);
  next.setUTCMonth(next.getUTCMonth() + count);
  const last = new Date(Date.UTC(next.getUTCFullYear(), next.getUTCMonth() + 1, 0)).getUTCDate();
  next.setUTCDate(Math.min(day, last));
  return next;
}
function parseDate(value: unknown, field: string) {
  const parsed = new Date(text(value));
  if (!text(value) || Number.isNaN(parsed.getTime())) throw new Error(`${field} must be an ISO datetime`);
  return parsed;
}
function durationEnd(body: Json, start: Date) {
  if (text(body.ends_at)) return parseDate(body.ends_at, "ends_at");
  return new Date(start.getTime() + Number(body.duration_hours || 2) * 3600000);
}

async function auth(request: Request): Promise<{ supabase: SupabaseClient; user: User }> {
  const authorization = request.headers.get("Authorization");
  const url = Deno.env.get("SUPABASE_URL");
  const anonKey = Deno.env.get("SUPABASE_ANON_KEY");
  if (!authorization || !url || !anonKey) throw new Error("Authenticated Supabase configuration is required");
  const bearer = authorization.replace(/^Bearer\s+/i, "");
  const supabase = createClient(url, anonKey, { global: { headers: { Authorization: `Bearer ${bearer}` } } });
  const { data, error } = await supabase.auth.getUser(bearer);
  if (error || !data.user) throw new Error("Sign in required");
  return { supabase, user: data.user };
}

async function organization(supabase: SupabaseClient, user: User, requested: unknown) {
  const requestedId = text(requested);
  let query = supabase.from("organization_memberships").select("organization_id").eq("user_id", user.id).eq("status", "active").limit(20);
  if (requestedId) query = query.eq("organization_id", requestedId);
  const { data, error } = await query;
  if (error) throw new Error(error.message);
  if (requestedId && (data || []).some((row: Json) => String(row.organization_id) === requestedId)) return requestedId;
  if (!requestedId && (data || []).length === 1) return String(data![0].organization_id);
  if (requestedId) {
    const { data: owned } = await supabase.from("organizations").select("id").eq("id", requestedId).eq("owner_user_id", user.id).maybeSingle();
    if (owned?.id) return String(owned.id);
  }
  throw new Error("Organization access denied");
}

function normalizedBooking(source: Json, organizationId: string) {
  const pickup = source.pickup && typeof source.pickup === "object" ? source.pickup : { label: source.pickup || "" };
  const dropoff = source.dropoff && typeof source.dropoff === "object" ? source.dropoff : { label: source.dropoff || "" };
  const rawBookingType = String(source.booking_type || (source.mode === "monthly" ? "monthly" : source.mode === "itinerary" ? "multi_day" : "single")).toLowerCase().replace("-", "_");
  const bookingType = rawBookingType === "flat" ? "flat_rate" : ["single", "parent", "child", "flat_rate", "monthly", "multi_day"].includes(rawBookingType) ? rawBookingType : "single";
  const allotmentMode = String(source.allotment_mode || "owned").toLowerCase() === "own" ? "owned" : String(source.allotment_mode || "owned").toLowerCase();
  return {
    organization_id: organizationId,
    branch_id: source.branch_id || null,
    customer_id: source.customer_id || null,
    customer_entity_id: source.customer_entity_id || null,
    sister_company_id: source.sister_company_id || null,
    company_id: source.company_id || null,
    vehicle_group_code: source.vehicle_group_code || source.vehicle_group || null,
    duty_type_code: source.duty_type_code || source.duty_type || "local",
    requesting_organization_id: source.requesting_organization_id || null,
    vendor_organization_id: source.vendor_organization_id || null,
    status: source.status || "requested",
    booking_reference: source.booking_reference || `BK-${Date.now()}-${token().slice(0, 8).toUpperCase()}`,
    passenger_name: source.passenger_name || null,
    passenger_phone: source.passenger_phone || null,
    passenger_email: source.passenger_email || null,
    pickup,
    dropoff,
    stops: undefined,
    scheduled_at: source.scheduled_at || null,
    duty_type: source.duty_type || "local",
    policy_context: source.policy_context || {},
    source: source.source || "web",
    notes: source.notes || null,
    booking_type: bookingType,
    parent_booking_id: source.parent_booking_id || null,
    booking_group_id: source.booking_group_id || null,
    child_sequence: Number(source.child_sequence || 0),
    flat_rate_paise: Number(source.flat_rate_paise || source.flat_rate || 0),
    currency: String(source.currency || "INR").toUpperCase(),
    start_at: source.start_at || source.scheduled_at || null,
    end_at: source.end_at || null,
    recurrence_rule: source.recurrence_rule || source.recurrence || "",
    passenger_json: { ...(object(source.passenger)), ...(object(source.temporary_passenger)) },
    pricing_contract_id: source.pricing_contract_id || source.contract_id || null,
    pricing_snapshot: source.pricing_snapshot || {},
    confirmation_status: source.confirmation_status || "pending",
    advance_paise: Number(source.advance_paise || 0),
    allotment_mode: allotmentMode,
    source_import_id: source.source_import_id || null,
  };
}

function batchInputs(body: Json, mode: string): Json[] {
  if (mode === "bulk") return list(body.rows).map((row) => object(row));
  if (mode === "itinerary") {
    const segments = list(body.segments || body.rows);
    const base = { ...body };
    delete base.segments; delete base.rows; delete base.mode; delete base.idempotency_key;
    return segments.map((segment, index) => ({ ...base, ...object(segment), source: object(segment).source || "itinerary", itinerary_segment: index + 1 }));
  }
  const template = object(body.template);
  const start = parseDate(body.start_at, "start_at");
  const end = text(body.end_at) ? parseDate(body.end_at, "end_at") : null;
  const occurrences = Math.max(1, Math.min(365, Number(body.occurrences || 1)));
  const rows: Json[] = [];
  for (let index = 0; index < occurrences; index += 1) {
    const scheduled = monthAdd(start, index);
    if (end && scheduled > end) break;
    rows.push({ ...template, scheduled_at: iso(scheduled), monthly_occurrence: index + 1 });
  }
  return rows;
}

async function loadBatch(supabase: SupabaseClient, organizationId: string, id: string) {
  const { data: batch, error } = await supabase.from("booking_batches").select("*").eq("organization_id", organizationId).eq("id", id).maybeSingle();
  if (error) throw new Error(error.message); if (!batch) throw new Error("Booking batch not found");
  const { data: rows, error: rowError } = await supabase.from("booking_batch_rows").select("*").eq("organization_id", organizationId).eq("batch_id", id).order("row_number");
  if (rowError) throw new Error(rowError.message);
  return { ...batch, rows: rows || [] };
}

async function createBatch(supabase: SupabaseClient, user: User, organizationId: string, body: Json) {
  const mode = text(body.mode, "bulk").toLowerCase();
  if (!["bulk", "itinerary", "monthly"].includes(mode)) throw new Error("mode must be bulk, itinerary or monthly");
  const idempotencyKey = text(body.idempotency_key) || null;
  if (idempotencyKey) {
    const { data: existing } = await supabase.from("booking_batches").select("id").eq("organization_id", organizationId).eq("idempotency_key", idempotencyKey).maybeSingle();
    if (existing?.id) return { ok: true, item: await loadBatch(supabase, organizationId, existing.id), idempotent: true };
  }
  const rows = batchInputs(body, mode);
  if (!rows.length || rows.length > 500) throw new Error("Provide between 1 and 500 booking rows");
  const { data: batch, error: batchError } = await supabase.from("booking_batches").insert({ organization_id: organizationId, mode, status: "processing", requested_count: rows.length, start_at: body.start_at || null, end_at: body.end_at || null, idempotency_key: idempotencyKey, payload: { mode }, created_by: user.id }).select().single();
  if (batchError) throw new Error(batchError.message);
  const rowRecords = rows.map((source, index) => ({ organization_id: organizationId, batch_id: batch.id, row_number: index + 1, source }));
  const { error: rowError } = await supabase.from("booking_batch_rows").insert(rowRecords);
  if (rowError) throw new Error(rowError.message);
  let generated = 0; let failed = 0;
  for (const [index, source] of rows.entries()) {
    const payload = normalizedBooking(source, organizationId);
    const { data: booking, error } = await supabase.from("bookings").insert(payload).select().single();
    if (error) {
      failed += 1;
      await supabase.from("booking_batch_rows").update({ status: "error", error_code: "booking_write_failed", error_message: error.message }).eq("organization_id", organizationId).eq("batch_id", batch.id).eq("row_number", index + 1);
      continue;
    }
    generated += 1;
    const batchType = mode === "monthly" ? "monthly" : mode === "itinerary" ? "multi_day" : (text(source.booking_type, "single").toLowerCase().replace("-", "_") === "flat" ? "flat_rate" : text(source.booking_type, "single").toLowerCase().replace("-", "_") );
    const { error: lifecycleError } = await supabase.from("bookings").update({ booking_type: ["single", "parent", "child", "flat_rate", "monthly", "multi_day"].includes(batchType) ? batchType : "single", booking_group_id: batch.id, child_sequence: index + 1, flat_rate_paise: Number(source.flat_rate_paise || source.flat_rate || 0), start_at: source.start_at || source.scheduled_at || null, end_at: source.end_at || null, recurrence_rule: source.recurrence_rule || source.recurrence || "", allotment_mode: text(source.allotment_mode, "owned").toLowerCase() === "own" ? "owned" : text(source.allotment_mode, "owned").toLowerCase(), vehicle_group_code: source.vehicle_group_code || source.vehicle_group || "" }).eq("organization_id", organizationId).eq("id", booking.id);
    if (lifecycleError) throw new Error(lifecycleError.message);
    const stops = list(source.stops).map((stop, stopIndex) => ({ organization_id: organizationId, booking_id: booking.id, stop_index: stopIndex + 1, label: text(object(stop).label, `Stop ${stopIndex + 1}`), address: object(object(stop).address || stop), arrival_at: object(stop).arrival_at || null, departure_at: object(stop).departure_at || null, status: text(object(stop).status, "planned") }));
    if (stops.length) await supabase.from("booking_stops").insert(stops);
    await supabase.from("booking_batch_rows").update({ status: "created", booking_id: booking.id }).eq("organization_id", organizationId).eq("batch_id", batch.id).eq("row_number", index + 1);
  }
  const status = failed === 0 ? "completed" : generated ? "partial" : "failed";
  await supabase.from("booking_batches").update({ status, generated_count: generated, failed_count: failed, updated_at: new Date().toISOString() }).eq("organization_id", organizationId).eq("id", batch.id);
  return { ok: true, item: await loadBatch(supabase, organizationId, batch.id) };
}

async function availability(supabase: SupabaseClient, organizationId: string, body: Json) {
  const starts = parseDate(body.starts_at || body.scheduled_at, "starts_at");
  const ends = durationEnd(body, starts);
  if (ends <= starts) throw new Error("ends_at must be after starts_at");
  const city = text(body.city).toLowerCase();
  const vehicleGroup = text(body.vehicle_group || body.vehicle_group_code).toLowerCase();
  const { data: locks, error: lockError } = await supabase.from("capacity_locks").select("resource_type,resource_id,starts_at,ends_at").eq("organization_id", organizationId).eq("status", "held");
  if (lockError) throw new Error(lockError.message);
  const occupied = new Set((locks || []).filter((lock: Json) => new Date(lock.starts_at) < ends && new Date(lock.ends_at) > starts).map((lock: Json) => `${lock.resource_type}:${lock.resource_id}`));
  const { data: drivers, error: driverError } = await supabase.from("drivers").select("id,full_name,city,status").eq("organization_id", organizationId).in("status", ["active", "available"]).order("full_name");
  if (driverError) throw new Error(driverError.message);
  const { data: vehicles, error: vehicleError } = await supabase.from("vehicles").select("id,registration_number,vehicle_group,city,status").eq("organization_id", organizationId).in("status", ["active", "available"]).order("registration_number");
  if (vehicleError) throw new Error(vehicleError.message);
  const eligibleDrivers = (drivers || []).filter((row: Json) => !occupied.has(`driver:${row.id}`)).map((row: Json) => ({ ...row, score: city && text(row.city).toLowerCase() === city ? 0 : 1 }));
  const eligibleVehicles = (vehicles || []).filter((row: Json) => (!vehicleGroup || !text(row.vehicle_group) || text(row.vehicle_group).toLowerCase() === vehicleGroup) && !occupied.has(`vehicle:${row.id}`)).map((row: Json) => ({ ...row, score: city && text(row.city).toLowerCase() === city ? 0 : 1 }));
  eligibleDrivers.sort((a: Json, b: Json) => a.score - b.score || text(a.full_name).localeCompare(text(b.full_name)) || text(a.id).localeCompare(text(b.id)));
  eligibleVehicles.sort((a: Json, b: Json) => a.score - b.score || text(a.registration_number).localeCompare(text(b.registration_number)) || text(a.id).localeCompare(text(b.id)));
  const reasons = [] as Json[];
  if (!eligibleDrivers.length) reasons.push({ code: "no_available_driver", severity: "block", message: "No driver is available for the requested window." });
  if (!eligibleVehicles.length) reasons.push({ code: "no_available_vehicle", severity: "block", message: "No vehicle is available for the requested window." });
  return { starts_at: iso(starts), ends_at: iso(ends), drivers: eligibleDrivers, vehicles: eligibleVehicles, eligible: reasons.length === 0, reasons, deterministic: true };
}

async function allot(supabase: SupabaseClient, user: User, organizationId: string, bookingId: string, body: Json) {
  const { data: booking, error: bookingError } = await supabase.from("bookings").select("*").eq("organization_id", organizationId).eq("id", bookingId).maybeSingle();
  if (bookingError) throw new Error(bookingError.message); if (!booking) throw new Error("Booking not found");
  if (booking.status === "pending_approval") throw new Error("Booking approval is required before allotment");
  const key = text(body.idempotency_key) || null;
  if (key) {
    const { data: existing } = await supabase.from("allotment_decisions").select("*").eq("organization_id", organizationId).eq("booking_id", bookingId).eq("idempotency_key", key).maybeSingle();
    if (existing) return { ok: true, decision: existing, idempotent: true };
  }
  const availabilityResult = await availability(supabase, organizationId, { ...body, scheduled_at: booking.scheduled_at, city: object(booking.pickup).city || object(booking.pickup).label });
  if (!availabilityResult.eligible) {
    const { data: blocked } = await supabase.from("allotment_decisions").insert({ organization_id: organizationId, booking_id: bookingId, status: "blocked", rationale: availabilityResult, idempotency_key: key, created_by: user.id }).select().single();
    return { ok: false, eligible: false, decision: blocked, reasons: availabilityResult.reasons };
  }
  const driverId = text(body.driver_id) || (availabilityResult.drivers[0] as Json).id;
  const vehicleId = text(body.vehicle_id) || (availabilityResult.vehicles[0] as Json).id;
  if (!availabilityResult.drivers.some((row: Json) => row.id === driverId)) throw new Error("Selected driver is not available");
  if (!availabilityResult.vehicles.some((row: Json) => row.id === vehicleId)) throw new Error("Selected vehicle is not available");
  const { data: duty, error: dutyError } = await supabase.from("duties").insert({ organization_id: organizationId, booking_id: bookingId, driver_id: driverId, vehicle_id: vehicleId, status: "assigned", reporting_at: booking.scheduled_at }).select().single();
  if (dutyError) throw new Error(dutyError.message);
  const starts = new Date(availabilityResult.starts_at); const ends = new Date(availabilityResult.ends_at);
  const { error: lockError } = await supabase.from("capacity_locks").insert([
    { organization_id: organizationId, resource_type: "driver", resource_id: driverId, booking_id: bookingId, starts_at: starts.toISOString(), ends_at: ends.toISOString(), status: "held" },
    { organization_id: organizationId, resource_type: "vehicle", resource_id: vehicleId, booking_id: bookingId, starts_at: starts.toISOString(), ends_at: ends.toISOString(), status: "held" },
  ]);
  if (lockError) throw new Error(lockError.message);
  const { data: updated, error: updateError } = await supabase.from("bookings").update({ status: "assigned" }).eq("organization_id", organizationId).eq("id", bookingId).select().single();
  if (updateError) throw new Error(updateError.message);
  const { data: decision, error: decisionError } = await supabase.from("allotment_decisions").insert({ organization_id: organizationId, booking_id: bookingId, status: "assigned", driver_id: driverId, vehicle_id: vehicleId, rationale: { availability: availabilityResult, duty_id: duty.id }, idempotency_key: key, created_by: user.id }).select().single();
  if (decisionError) throw new Error(decisionError.message);
  return { ok: true, booking: updated, duty, decision, availability: availabilityResult };
}

async function closeDuty(supabase: SupabaseClient, organizationId: string, dutyId: string, body: Json) {
  const start = Number(body.start_odometer); const end = Number(body.end_odometer);
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end < start) throw new Error("Odometer readings are invalid");
  const evidence = list(body.evidence).map((item) => object(item));
  const required = list(body.required_evidence).map((item) => text(item).toLowerCase()).filter(Boolean);
  const { data, error } = await supabase.rpc("submit_duty_closure", {
    p_duty_id: dutyId,
    p_start_odometer: start,
    p_end_odometer: end,
    p_payload: Object.fromEntries(Object.entries(body).filter(([key]) => !["evidence", "required_evidence"].includes(key))),
    p_required_evidence: required,
    p_evidence: evidence,
    p_idempotency_key: text(body.idempotency_key) || null,
  });
  if (error) throw new Error(error.message);
  return { ok: true, item: data, organization_id: organizationId };
}

async function handle(request: Request) {
  const { supabase, user } = await auth(request);
  const envelope = request.method === "GET" ? {} : object(await request.json());
  const url = new URL(request.url);
  const path = text(envelope.path || url.searchParams.get("path"));
  const method = text(envelope.method || request.method, request.method).toUpperCase();
  const body = object(envelope.body);
  const organizationId = await organization(supabase, user, envelope.organization_id || body.organization_id);
  const query = object(envelope.query);

  if (path === "/api/bookings/batches" && method === "GET") {
    const { data, error } = await supabase.from("booking_batches").select("*").eq("organization_id", organizationId).order("created_at", { ascending: false }).limit(100);
    if (error) throw new Error(error.message);
    return { ok: true, items: await Promise.all((data || []).map((row: Json) => loadBatch(supabase, organizationId, row.id))), count: (data || []).length };
  }
  if (path === "/api/bookings/batches" && method === "POST") return createBatch(supabase, user, organizationId, body);
  const batchMatch = path.match(/^\/api\/bookings\/batches\/([^/]+)(?:\/(cancel|rows))?$/);
  if (batchMatch) {
    if (method === "GET") return { ok: true, item: await loadBatch(supabase, organizationId, batchMatch[1]) };
    if (method === "POST" && batchMatch[2] === "cancel") {
      const { error } = await supabase.from("booking_batches").update({ status: "cancelled", updated_at: iso(new Date()) }).eq("organization_id", organizationId).eq("id", batchMatch[1]).in("status", ["processing", "partial"]);
      if (error) throw new Error(error.message);
      return { ok: true, item: await loadBatch(supabase, organizationId, batchMatch[1]) };
    }
  }
  if (path === "/api/availability" || path === "/api/availability/evaluate") return { ok: true, ...(await availability(supabase, organizationId, { ...query, ...body })) };
  const allotMatch = path.match(/^\/api\/bookings\/([^/]+)\/allot$/);
  if (allotMatch && method === "POST") return allot(supabase, user, organizationId, allotMatch[1], body);
  if (path === "/api/allotment/decisions" && method === "GET") {
    const { data, error } = await supabase.from("allotment_decisions").select("*").eq("organization_id", organizationId).order("created_at", { ascending: false }).limit(100);
    if (error) throw new Error(error.message); return { ok: true, items: data || [], count: (data || []).length };
  }
  const closeMatch = path.match(/^\/api\/duties\/([^/]+)\/close$/);
  if (closeMatch && method === "POST") return closeDuty(supabase, organizationId, closeMatch[1], body);
  const closureMatch = path.match(/^\/api\/duties\/([^/]+)\/closure(?:\/evidence)?$/);
  if (closureMatch && method === "GET") {
    const { data: closure, error } = await supabase.from("duty_closures").select("*").eq("organization_id", organizationId).eq("duty_id", closureMatch[1]).order("closure_version", { ascending: false }).limit(1).maybeSingle();
    if (error) throw new Error(error.message);
    if (!closure) return { ok: true, item: null };
    const { data: evidence, error: evidenceError } = await supabase.from("closure_evidence").select("*").eq("organization_id", organizationId).eq("duty_id", closureMatch[1]).order("captured_at");
    if (evidenceError) throw new Error(evidenceError.message);
    return { ok: true, item: { ...closure, evidence: evidence || [] } };
  }
  throw new Error(`Unsupported operations route: ${method} ${path}`);
}

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") return new Response("ok", { status: 200, headers: cors });
  try { return reply(await handle(request)); }
  catch (error) { return reply({ ok: false, code: "operations_request_failed", message: message(error) }, 400); }
});
