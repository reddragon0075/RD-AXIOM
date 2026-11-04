import { createClient, type SupabaseClient, type User } from "https://esm.sh/@supabase/supabase-js@2";

/*
 * Supabase Edge boundary for the additive parity-completion contracts.  The
 * function intentionally returns provider-neutral/mock statuses until a real
 * provider adapter and secret reference have been configured and validated.
 */
const url = Deno.env.get("SUPABASE_URL") || "";
const anon = Deno.env.get("SUPABASE_ANON_KEY") || "";
const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
const allowedOrigin = (Deno.env.get("AXIOM_ALLOWED_ORIGIN") || Deno.env.get("AXIOM_ALLOWED_ORIGINS")?.split(",")[0] || "").trim();
const cors = {
  ...(allowedOrigin ? { "Access-Control-Allow-Origin": allowedOrigin, "Vary": "Origin" } : {}),
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info, x-request-id",
  "Access-Control-Allow-Methods": "GET, POST, PATCH, OPTIONS",
};
type Json = Record<string, any>;
type Envelope = { path: string; method?: string; organization_id?: string; query?: Json; body?: Json };
const reply = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { ...cors, "Content-Type": "application/json" } });
const object = (value: unknown): Json => value && typeof value === "object" && !Array.isArray(value) ? value as Json : {};
const required = (value: unknown, name: string) => { const text = String(value || "").trim(); if (!text) throw new Error(`${name} is required`); return text; };
const key = (body: Json) => String(body.idempotency_key || "").trim() || null;
const hash = async (value: string) => { const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)); return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join(""); };
const safeConfig = (value: unknown) => Object.fromEntries(Object.entries(object(value)).filter(([name]) => !["secret", "api_key", "token", "password", "private_key", "access_token"].includes(name.toLowerCase())));
const safeAuthorization = (value: Json) => { const copy = { ...value }; delete copy.token_fingerprint; return copy; };

async function authenticated(request: Request) {
  const token = request.headers.get("Authorization")?.replace(/^Bearer\s+/i, "");
  if (!token) throw new Error("Sign in required");
  const supabase = createClient(url, anon, { global: { headers: { Authorization: `Bearer ${token}` } } });
  const { data, error } = await supabase.auth.getUser(token);
  if (error || !data.user) throw new Error("Sign in required");
  return { supabase, user: data.user as User };
}
async function organization(supabase: SupabaseClient, user: User, requested?: string) {
  let query = supabase.from("organization_memberships").select("organization_id").eq("user_id", user.id).eq("status", "active").limit(20);
  if (requested) query = query.eq("organization_id", requested);
  const { data, error } = await query;
  if (error || !data?.length) throw new Error("Organization access denied");
  if (requested) return requested;
  if (data.length !== 1) throw new Error("Select one organization before using this contract");
  return String(data[0].organization_id);
}
async function staff(supabase: SupabaseClient, organizationId: string, permission: string) {
  const { data, error } = await supabase.rpc("has_permission", { target_org: organizationId, permission_key: permission });
  if (error || data !== true) throw new Error(`${permission} permission required`);
}
async function list(supabase: SupabaseClient, table: string, organizationId: string, limit = 200) {
  const { data, error } = await supabase.from(table).select("*").eq("organization_id", organizationId).order("created_at", { ascending: false }).limit(limit);
  if (error) throw new Error(error.message);
  return { ok: true, items: data || [] };
}
async function replay(supabase: SupabaseClient, table: string, organizationId: string, idempotencyKey: string | null) {
  if (!idempotencyKey) return null;
  const { data, error } = await supabase.from(table).select("*").eq("organization_id", organizationId).eq("idempotency_key", idempotencyKey).maybeSingle();
  if (error) throw new Error(error.message);
  return data ? { ok: true, item: data, idempotent: true } : null;
}
async function adminClient() {
  if (!serviceKey) throw new Error("Supabase service-role configuration is required for this public boundary");
  return createClient(url, serviceKey, { auth: { autoRefreshToken: false, persistSession: false } });
}

async function publicLocation(path: string) {
  const match = path.match(/^\/api\/location-shares\/([^/]+)$/);
  if (!match) return undefined;
  const admin = await adminClient();
  const tokenHash = await hash(match[1]);
  const { data: share, error } = await admin.from("gap_location_shares").select("*").eq("token_hash", tokenHash).eq("status", "active").gt("expires_at", new Date().toISOString()).maybeSingle();
  if (error || !share) throw new Error("Location share is invalid or expired");
  await admin.from("gap_location_shares").update({ last_accessed_at: new Date().toISOString() }).eq("id", share.id);
  const { data: points } = await admin.from("gap_route_points").select("recorded_at,latitude,longitude,accuracy_m,speed_kph,heading,battery_pct").eq("organization_id", share.organization_id).eq("duty_id", share.duty_id).order("recorded_at", { ascending: false }).limit(1);
  const { data: duty } = await admin.from("duties").select("id,status,booking_id").eq("id", share.duty_id).eq("organization_id", share.organization_id).maybeSingle();
  let booking: Json | null = null;
  if (duty?.booking_id) {
    const response = await admin.from("bookings").select("booking_reference,passenger_name").eq("id", duty.booking_id).eq("organization_id", share.organization_id).maybeSingle();
    booking = response.data || null;
  }
  return { ok: true, share: { id: share.id, duty_id: share.duty_id, expires_at: share.expires_at, status: share.status }, trip: { duty_status: duty?.status || "unknown", booking_reference: booking?.booking_reference || "", passenger_name: booking?.passenger_name || "", last_location: points?.[0] || null } };
}

async function route(supabase: SupabaseClient, user: User, org: string, envelope: Envelope) {
  const path = String(envelope.path || "").replace(/\/$/, "") || "/";
  const method = String(envelope.method || "GET").toUpperCase();
  const body = object(envelope.body);
  if (path === "/api/passenger/booking-requests" || path === "/api/passenger/book-for-others") {
    await staff(supabase, org, "passenger.book");
    if (method === "GET") return list(supabase, "gap_passenger_booking_requests", org);
    const idempotencyKey = key(body); const existing = await replay(supabase, "gap_passenger_booking_requests", org, idempotencyKey); if (existing) return existing;
    const { data, error } = await supabase.from("gap_passenger_booking_requests").insert({ organization_id: org, requester_user_id: user.id, passenger_name: required(body.passenger_name, "passenger_name"), passenger_phone: body.passenger_phone || "", passenger_email: body.passenger_email || "", customer_id: body.customer_id || null, scheduled_at: required(body.scheduled_at, "scheduled_at"), pickup: body.pickup || {}, dropoff: body.dropoff || {}, duty_type: body.duty_type || "local", notes: body.notes || "", idempotency_key: idempotencyKey }).select().single();
    if (error) throw new Error(error.message); return { ok: true, item: data };
  }
  const requestAction = path.match(/^\/api\/passenger\/booking-requests\/([^/]+)\/(approve|reject|cancel)$/);
  if (requestAction && method === "POST") {
    await staff(supabase, org, "passenger.book");
    const { data: request, error } = await supabase.from("gap_passenger_booking_requests").select("*").eq("organization_id", org).eq("id", requestAction[1]).maybeSingle();
    if (error || !request) throw new Error("Passenger booking request not found");
    if (request.status !== "pending") return { ok: true, item: request, idempotent: true };
    let bookingId = request.booking_id;
    if (requestAction[2] === "approve") {
      const booking = await supabase.from("bookings").insert({ organization_id: org, customer_id: request.customer_id, booking_reference: `PAX-${crypto.randomUUID().slice(0, 8).toUpperCase()}`, status: "requested", passenger_name: request.passenger_name, passenger_phone: request.passenger_phone, pickup: request.pickup, dropoff: request.dropoff, scheduled_at: request.scheduled_at, duty_type: request.duty_type, source: "passenger_request", notes: request.notes, created_by: user.id }).select().single();
      if (booking.error) throw new Error(booking.error.message); bookingId = booking.data.id;
    }
    const status = requestAction[2] === "approve" ? "approved" : `${requestAction[2]}d`;
    const updated = await supabase.from("gap_passenger_booking_requests").update({ status, booking_id: bookingId, decision_note: body.decision_note || "", decision_by: user.id, decision_at: new Date().toISOString(), updated_at: new Date().toISOString() }).eq("id", request.id).eq("organization_id", org).select().single();
    if (updated.error) throw new Error(updated.error.message); return { ok: true, item: updated.data, booking_id: bookingId };
  }
  if (path === "/api/availability/optimize" && method === "POST") {
    await staff(supabase, org, "operations.route_evidence");
    const vehicleQuery = supabase.from("vehicles").select("id,registration_number,vehicle_type,city,status").eq("organization_id", org).in("status", ["available", "active"]);
    const driverQuery = supabase.from("drivers").select("id,full_name,city,status").eq("organization_id", org).in("status", ["available", "active"]);
    const [{ data: vehicles, error: vehicleError }, { data: drivers, error: driverError }] = await Promise.all([vehicleQuery, driverQuery]);
    if (vehicleError || driverError) throw new Error(vehicleError?.message || driverError?.message || "Availability query failed");
    const city = String(body.city || "").toLowerCase();
    const candidates = (vehicles || []).flatMap((vehicle) => (drivers || []).map((driver) => ({ driver_id: driver.id, driver_name: driver.full_name, vehicle_id: vehicle.id, registration_number: vehicle.registration_number, vehicle_type: vehicle.vehicle_type, score: (city && vehicle.city?.toLowerCase() === city ? 110 : 100) - (city && driver.city && driver.city.toLowerCase() !== city ? 20 : 0), reasons: city && vehicle.city?.toLowerCase() === city ? ["vehicle_city_match"] : [] }))).sort((a, b) => b.score - a.score);
    const selected = candidates[0] || null;
    let dutyId: string | null = null;
    if (selected && body.auto_assign && body.booking_id) {
      const createdDuty = await supabase.from("duties").insert({ organization_id: org, booking_id: body.booking_id, driver_id: selected.driver_id, vehicle_id: selected.vehicle_id, status: "assigned", reporting_at: body.reporting_at || null }).select("id").single();
      if (createdDuty.error) throw new Error(createdDuty.error.message);
      dutyId = createdDuty.data.id;
      await supabase.from("bookings").update({ status: "assigned", updated_at: new Date().toISOString() }).eq("id", body.booking_id).eq("organization_id", org);
    }
    return { ok: true, status: selected ? "available" : "unavailable", candidates: candidates.slice(0, 50), selected, duty_id: dutyId, auto_assigned: Boolean(dutyId), provider: "supabase_capacity_contract", production_validated: false };
  }
  const shareRoute = path.match(/^\/api\/duties\/([^/]+)\/location-share$/);
  if (shareRoute) {
    await staff(supabase, org, "operations.route_evidence");
    if (method === "GET") { const rows = await supabase.from("gap_location_shares").select("id,duty_id,recipient,status,expires_at,last_accessed_at,created_at").eq("organization_id", org).eq("duty_id", shareRoute[1]).order("created_at", { ascending: false }); if (rows.error) throw new Error(rows.error.message); return { ok: true, items: rows.data || [] }; }
    const rawToken = `${crypto.randomUUID()}-${crypto.randomUUID()}`; const tokenHash = await hash(rawToken); const expires = new Date(Date.now() + Math.max(1, Math.min(Number(body.expires_hours || 12), 72)) * 3600000).toISOString();
    const inserted = await supabase.from("gap_location_shares").insert({ organization_id: org, duty_id: shareRoute[1], token_hash: tokenHash, recipient: body.recipient || "", expires_at: expires, created_by: user.id }).select("id,expires_at,status").single(); if (inserted.error) throw new Error(inserted.error.message); return { ok: true, item: { ...inserted.data, url: `/api/location-shares/${rawToken}` } };
  }
  const routeStart = path.match(/^\/api\/duties\/([^/]+)\/route-log(?:\/(start|stop))?$/);
  if (routeStart) {
    await staff(supabase, org, "operations.route_evidence");
    const dutyId = routeStart[1]; const action = routeStart[2];
    const { data: duty, error: dutyError } = await supabase.from("duties").select("id,status").eq("id", dutyId).eq("organization_id", org).maybeSingle();
    if (dutyError || !duty) throw new Error("Duty not found");
    if (method === "GET") { const logs = await list(supabase, "gap_route_logs", org); const { data: points } = await supabase.from("gap_route_points").select("*").eq("organization_id", org).eq("duty_id", dutyId).order("recorded_at"); return { ok: true, logs: logs.items.filter((item: Json) => item.duty_id === dutyId), points: points || [] }; }
    if (action === "start" || !Array.isArray(body.points)) {
      const existing = await supabase.from("gap_route_logs").select("*").eq("organization_id", org).eq("duty_id", dutyId).eq("status", "recording").maybeSingle();
      if (existing.data) return { ok: true, item: existing.data, idempotent: true };
      const inserted = await supabase.from("gap_route_logs").insert({ organization_id: org, duty_id: dutyId, tracking_mode: body.tracking_mode || "background", provider: body.provider || "mock_gps", idempotency_key: key(body), created_by: user.id }).select().single();
      if (inserted.error) throw new Error(inserted.error.message); return { ok: true, item: inserted.data };
    }
    const log = await supabase.from("gap_route_logs").select("*").eq("organization_id", org).eq("duty_id", dutyId).eq("status", "recording").order("created_at", { ascending: false }).limit(1).maybeSingle();
    if (log.error || !log.data) throw new Error("Start a route log before sending points");
    const rows = (body.points as unknown[]).map((point) => { const item = object(point); return { organization_id: org, route_log_id: log.data.id, duty_id: dutyId, recorded_at: item.recorded_at || new Date().toISOString(), latitude: Number(item.latitude), longitude: Number(item.longitude), accuracy_m: item.accuracy_m || null, speed_kph: item.speed_kph || null, heading: item.heading || null, battery_pct: item.battery_pct || null, source: item.source || "driver_background", idempotency_key: item.idempotency_key || null }; });
    const inserted = await supabase.from("gap_route_points").upsert(rows, { onConflict: "organization_id,idempotency_key" }).select(); if (inserted.error) throw new Error(inserted.error.message);
    if (action === "stop" || body.stop) await supabase.from("gap_route_logs").update({ status: "completed", stopped_at: new Date().toISOString(), summary: { point_count: inserted.data?.length || 0, provider: log.data.provider, mock: String(log.data.provider).startsWith("mock") } }).eq("id", log.data.id);
    const latest = await supabase.from("gap_route_logs").select("*").eq("id", log.data.id).single(); return { ok: true, item: latest.data, inserted_points: inserted.data?.length || 0 };
  }
  if (path === "/api/driver-alert-policies") {
    await staff(supabase, org, "operations.alerts");
    if (method === "GET") return list(supabase, "gap_driver_alert_policies", org);
    const inserted = await supabase.from("gap_driver_alert_policies").upsert({ organization_id: org, name: required(body.name, "name"), alert_type: required(body.alert_type, "alert_type"), severity: body.severity || "warning", threshold: body.threshold || {}, channels: body.channels || ["push"], localized_guidance: body.localized_guidance || {}, enabled: body.enabled !== false, created_by: user.id }, { onConflict: "organization_id,name" }).select().single(); if (inserted.error) throw new Error(inserted.error.message); return { ok: true, item: inserted.data };
  }
  const alertRoute = path.match(/^\/api\/duties\/([^/]+)\/driver-alerts(?:\/(acknowledge|resolve))?$/);
  if (alertRoute) {
    await staff(supabase, org, "operations.alerts");
    if (method === "GET") { const rows = await supabase.from("gap_driver_alert_events").select("*").eq("organization_id", org).eq("duty_id", alertRoute[1]).order("occurred_at", { ascending: false }); if (rows.error) throw new Error(rows.error.message); return { ok: true, items: rows.data || [] }; }
    if (alertRoute[2]) { const updated = await supabase.from("gap_driver_alert_events").update(alertRoute[2] === "acknowledge" ? { status: "acknowledged", acknowledged_by: user.id, acknowledged_at: new Date().toISOString() } : { status: "resolved", resolved_by: user.id, resolved_at: new Date().toISOString() }).eq("id", required(body.alert_id, "alert_id")).eq("organization_id", org).select().single(); if (updated.error) throw new Error(updated.error.message); return { ok: true, item: updated.data }; }
    const existing = await replay(supabase, "gap_driver_alert_events", org, key(body)); if (existing) return existing;
    const inserted = await supabase.from("gap_driver_alert_events").insert({ organization_id: org, duty_id: alertRoute[1], alert_type: body.alert_type || "operational", severity: body.severity || "warning", payload: body.payload || body, idempotency_key: key(body), created_by: user.id }).select().single(); if (inserted.error) throw new Error(inserted.error.message); return { ok: true, item: inserted.data };
  }
  if (path === "/api/driver/device-readiness") {
    if (method === "GET") return list(supabase, "gap_device_readiness", org);
    const permissions = object(body.permissions); const requiredPermissions = ["push", "background_location", "media", "notifications"]; const blockers = requiredPermissions.filter((name) => permissions[name] !== true);
    const inserted = await supabase.from("gap_device_readiness").upsert({ organization_id: org, user_id: user.id, device_id: required(body.device_id, "device_id"), platform: body.platform || "android", app_version: body.app_version || "", os_version: body.os_version || "", permissions, readiness_status: blockers.length ? "blocked" : "ready", blockers, push_token_present: Boolean(body.push_token), checked_at: new Date().toISOString() }, { onConflict: "organization_id,user_id,device_id" }).select().single(); if (inserted.error) throw new Error(inserted.error.message); return { ok: true, status: blockers.length ? "blocked" : "ready", blockers, item: inserted.data };
  }
  const providerRoute = path.match(/^\/api\/provider-connections(?:\/([^/]+)\/test)?$/);
  if (providerRoute) {
    await staff(supabase, org, "integrations.manage");
    if (method === "GET") return list(supabase, "gap_provider_connections", org);
    if (providerRoute[1]) { const checked = await supabase.from("gap_provider_connections").update({ status: "healthy_mock", last_tested_at: new Date().toISOString(), last_error: "" }).eq("organization_id", org).eq("id", providerRoute[1]).select().single(); if (checked.error) throw new Error(checked.error.message); return { ok: true, status: "healthy_mock", production_validated: false, item: checked.data }; }
    const inserted = await supabase.from("gap_provider_connections").upsert({ organization_id: org, provider_type: required(body.provider_type, "provider_type"), name: body.name || body.provider_type, mode: body.mode || "mock", status: "configured", credential_ref: body.credential_ref || "", config: safeConfig(body.config), capabilities: body.capabilities || [], created_by: user.id }, { onConflict: "organization_id,provider_type,name" }).select().single(); if (inserted.error) throw new Error(inserted.error.message); return { ok: true, item: inserted.data, production_validated: false };
  }
  if (path === "/api/maps/places" && method === "GET") {
    await staff(supabase, org, "integrations.manage");
    const query = String(envelope.query?.q || body.query || "").trim(); if (!query) throw new Error("q is required");
    return { ok: true, provider: "mock_maps", production_validated: false, item: { query, predictions: [{ place_id: `mock_${query.toLowerCase().replace(/[^a-z0-9]+/g, "_")}`, description: query, location: { latitude: 12.9716, longitude: 77.5946 }, provider: "mock_maps" }] } };
  }
  if (path === "/api/maps/navigation" && method === "POST") {
    await staff(supabase, org, "integrations.manage");
    const dropoff = object(body.dropoff); return { ok: true, provider: "mock_maps", production_validated: false, item: { status: "estimated", distance_km: 7, duration_minutes: 24, points: [body.pickup || {}, ...(Array.isArray(body.waypoints) ? body.waypoints : []), dropoff], deep_link: `https://maps.google.com/?api=1&destination=${encodeURIComponent(String(dropoff.label || dropoff.latitude || ""))}` } };
  }
  if (path === "/api/communications/click-to-call" && method === "POST") {
    await staff(supabase, org, "integrations.manage");
    return { ok: true, provider: "mock_telephony", production_validated: false, item: { reference: `mock_call_${crypto.randomUUID().slice(0, 16)}`, masked: true, to: body.to_number || "", context: body.context || "duty" } };
  }
  if (path === "/api/payment-authorizations") {
    await staff(supabase, org, "payments.auto_collect");
    if (method === "GET") { const rows = await supabase.from("gap_payment_authorizations").select("id,organization_id,customer_id,payer_email,provider,token_last4,max_amount_paise,currency,status,authorized_at,expires_at,idempotency_key,created_by,created_at").eq("organization_id", org).order("created_at", { ascending: false }); if (rows.error) throw new Error(rows.error.message); return { ok: true, items: rows.data || [] }; }
    const rawToken = required(body.payment_method_token, "payment_method_token"); const existing = await replay(supabase, "gap_payment_authorizations", org, key(body)); if (existing) return { ...existing, item: safeAuthorization(existing.item) };
    const inserted = await supabase.from("gap_payment_authorizations").insert({ organization_id: org, customer_id: body.customer_id || null, payer_email: body.payer_email || "", provider: body.provider || "mock_payment", token_fingerprint: await hash(rawToken), token_last4: rawToken.slice(-4), max_amount_paise: Number(body.max_amount_paise || 0), currency: body.currency || "INR", expires_at: body.expires_at || null, idempotency_key: key(body), created_by: user.id }).select().single(); if (inserted.error) throw new Error(inserted.error.message); return { ok: true, item: safeAuthorization(inserted.data) };
  }
  const collect = path.match(/^\/api\/invoices\/([^/]+)\/auto-collect$/);
  if (collect && method === "POST") {
    await staff(supabase, org, "payments.auto_collect"); const existing = await replay(supabase, "gap_auto_collect_attempts", org, key(body) || `auto_collect:${collect[1]}`); if (existing) return existing;
    const amount = Number(body.amount_paise || 0); if (!Number.isFinite(amount) || amount <= 0) throw new Error("amount_paise must be positive");
    const authorizationId = required(body.authorization_id, "authorization_id");
    const authorization = await supabase.from("gap_payment_authorizations").select("id,max_amount_paise,status").eq("organization_id", org).eq("id", authorizationId).eq("status", "active").maybeSingle();
    const invoice = await supabase.from("invoices").select("id,total_paise").eq("organization_id", org).eq("id", collect[1]).maybeSingle();
    if (authorization.error || invoice.error || !authorization.data || !invoice.data) throw new Error("Active authorization and invoice must belong to the current organization");
    if (Number(authorization.data.max_amount_paise || 0) > 0 && amount > Number(authorization.data.max_amount_paise)) throw new Error("Amount exceeds the authorization limit");
    const inserted = await supabase.from("gap_auto_collect_attempts").insert({ organization_id: org, authorization_id: authorizationId, invoice_id: collect[1], amount_paise: amount, status: "queued", provider_reference: "edge_adapter_pending", provider_payload: { production_validated: false }, idempotency_key: key(body) || `auto_collect:${collect[1]}`, created_by: user.id }).select().single(); if (inserted.error) throw new Error(inserted.error.message); return { ok: true, item: inserted.data, production_validated: false };
  }
  if (path === "/api/invoice-automation/policies") {
    await staff(supabase, org, "finance.forecast");
    if (method === "GET") return list(supabase, "gap_invoice_automation_policies", org);
    const inserted = await supabase.from("gap_invoice_automation_policies").upsert({ organization_id: org, name: body.name || "Default duty completion", customer_id: body.customer_id || null, trigger_event: body.trigger_event || "duty_completed", issue_einvoice: body.issue_einvoice === true, collect_payment: body.collect_payment === true, send_channel: body.send_channel || "email", payment_terms_days: Number(body.payment_terms_days || 7), enabled: body.enabled !== false, created_by: user.id }, { onConflict: "organization_id,name" }).select().single(); if (inserted.error) throw new Error(inserted.error.message); return { ok: true, item: inserted.data };
  }
  if (path === "/api/invoice-automation/run" && method === "POST") {
    await staff(supabase, org, "finance.forecast");
    const dutyId = required(body.duty_id, "duty_id"); const existing = await replay(supabase, "gap_invoice_automation_runs", org, key(body) || `invoice_automation:${dutyId}`); if (existing) return existing;
    const { data: duty, error: dutyError } = await supabase.from("duties").select("id,booking_id,calculation_snapshot").eq("id", dutyId).eq("organization_id", org).maybeSingle(); if (dutyError || !duty) throw new Error("Duty not found");
    const snapshot = object(duty.calculation_snapshot); const total = Number(snapshot.total_paise || 0); let invoiceId: string | null = null;
    if (total > 0) { const invoice = await supabase.from("invoices").insert({ organization_id: org, booking_id: duty.booking_id, invoice_number: `AUTO-${crypto.randomUUID().slice(0, 10).toUpperCase()}`, status: "draft", subtotal_paise: Number(snapshot.subtotal_paise || total), tax_paise: Number(snapshot.tax_paise || 0), total_paise: total, created_by: user.id }).select().single(); if (invoice.error) throw new Error(invoice.error.message); invoiceId = invoice.data.id; }
    const run = await supabase.from("gap_invoice_automation_runs").insert({ organization_id: org, duty_id: dutyId, invoice_id: invoiceId, status: invoiceId ? "completed" : "queued", result: { provider: "mock_invoice_boundary", production_validated: false }, idempotency_key: key(body) || `invoice_automation:${dutyId}`, created_by: user.id }).select().single(); if (run.error) throw new Error(run.error.message); return { ok: true, item: run.data, invoice_id: invoiceId, production_validated: false };
  }
  if (path === "/api/enterprise/custom-field-values") {
    await staff(supabase, org, "passenger.book");
    if (method === "GET") return list(supabase, "gap_custom_field_values", org);
    const values = Array.isArray(body.values) ? body.values : [body]; const saved: Json[] = [];
    for (const value of values) { const item = object(value); const upserted = await supabase.from("gap_custom_field_values").upsert({ organization_id: org, field_id: required(item.field_id, "field_id"), entity_type: required(item.entity_type, "entity_type"), entity_id: required(item.entity_id, "entity_id"), value: item.value ?? null, updated_by: user.id, updated_at: new Date().toISOString() }, { onConflict: "organization_id,field_id,entity_type,entity_id" }).select().single(); if (upserted.error) throw new Error(upserted.error.message); saved.push(upserted.data); }
    return { ok: true, items: saved };
  }
  if (path === "/api/integrations/sync") {
    await staff(supabase, org, "integrations.manage");
    if (method === "GET") return list(supabase, "gap_sync_runs", org);
    const syncType = required(body.sync_type, "sync_type"); const records = Array.isArray(body.records) ? body.records : []; const existing = await replay(supabase, "gap_sync_runs", org, key(body)); if (existing) return existing;
    const inserted = await supabase.from("gap_sync_runs").insert({ organization_id: org, sync_type: syncType, provider: body.provider || "mock_hrms", status: "accepted", records_received: records.length, records_applied: records.length, provider_reference: `edge_sync_${crypto.randomUUID().slice(0, 12)}`, result: { production_validated: false }, idempotency_key: key(body), created_by: user.id }).select().single(); if (inserted.error) throw new Error(inserted.error.message); return { ok: true, item: inserted.data, production_validated: false };
  }
  if (path === "/api/network/supplier-exchange") {
    await staff(supabase, org, "network.supplier_exchange");
    if (method === "GET") return list(supabase, "gap_supplier_exchange_jobs", org);
    if (!["invite_only", "closed_b2b"].includes(String(body.visibility || "invite_only"))) throw new Error("Network supplier exchange is invite-only and closed-B2B");
    const existing = await replay(supabase, "gap_supplier_exchange_jobs", org, key(body)); if (existing) return existing;
    const inserted = await supabase.from("gap_supplier_exchange_jobs").insert({ organization_id: org, network_program_id: required(body.network_program_id, "network_program_id"), supplier_id: required(body.supplier_id, "supplier_id"), direction: body.direction || "outbound", visibility: body.visibility || "invite_only", qualification: body.qualification || {}, contract: body.contract || {}, rate_card: body.rate_card || {}, payload: body.payload || {}, idempotency_key: key(body), created_by: user.id }).select().single(); if (inserted.error) throw new Error(inserted.error.message); return { ok: true, item: inserted.data };
  }
  if (path === "/api/finance/budgets") {
    await staff(supabase, org, "finance.forecast");
    if (method === "GET") return list(supabase, "gap_expense_budgets", org);
    const inserted = await supabase.from("gap_expense_budgets").upsert({ organization_id: org, period_key: required(body.period_key, "period_key"), customer_id: body.customer_id || null, budget_paise: Number(body.budget_paise || 0), alert_threshold_bps: Number(body.alert_threshold_bps || 8000), created_by: user.id }, { onConflict: "organization_id,period_key,customer_id" }).select().single(); if (inserted.error) throw new Error(inserted.error.message); return { ok: true, item: inserted.data };
  }
  if (path === "/api/finance/expense-forecast" && method === "GET") {
    await staff(supabase, org, "finance.forecast");
    const now = new Date(); const periods = [3, 2, 1].map((offset) => { const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - offset, 1)); return d.toISOString().slice(0, 7); });
    const { data: invoices, error } = await supabase.from("invoices").select("total_paise,created_at").eq("organization_id", org).gte("created_at", `${periods[0]}-01T00:00:00Z`); if (error) throw new Error(error.message);
    const totals = periods.map((period) => (invoices || []).filter((invoice: Json) => String(invoice.created_at).slice(0, 7) === period).reduce((sum, invoice: Json) => sum + Number(invoice.total_paise || 0), 0));
    const average = Math.round(totals.reduce((sum, value) => sum + value, 0) / periods.length); return { ok: true, item: { period_key: now.toISOString().slice(0, 7), history_periods: periods, history_totals_paise: totals, average_monthly_paise: average, forecast_paise: average, method: "three_month_invoice_average", model: "deterministic_supabase", production_validated: false } };
  }
  throw new Error(`Gap route not found: ${method} ${path}`);
}

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") return new Response("ok", { headers: cors });
  try {
    const raw = await request.json().catch(() => ({}));
    const envelope = object(raw) as Envelope;
    const path = String(envelope.path || "").replace(/\/$/, "") || "/";
    const publicResult = await publicLocation(path);
    if (publicResult !== undefined) return reply(publicResult);
    const { supabase, user } = await authenticated(request);
    const org = await organization(supabase, user, envelope.organization_id);
    return reply(await route(supabase, user, org, envelope));
  } catch (error) {
    return reply({ ok: false, error: error instanceof Error ? error.message : String(error || "Gap contract failed") }, 400);
  }
});
