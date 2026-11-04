import { createClient, type SupabaseClient, type User } from "https://esm.sh/@supabase/supabase-js@2";

const allowedOrigin = (Deno.env.get("AXIOM_ALLOWED_ORIGIN") || Deno.env.get("AXIOM_ALLOWED_ORIGINS")?.split(",")[0] || "").trim();
const cors = {
  ...(allowedOrigin ? { "Access-Control-Allow-Origin": allowedOrigin, "Vary": "Origin" } : {}),
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type, x-request-id",
  "Access-Control-Allow-Methods": "GET, POST, PATCH, OPTIONS",
};
type Json = Record<string, any>;
type Envelope = { path: string; method?: string; organization_id?: string; query?: Record<string, string>; body?: Record<string, unknown> };
const url = Deno.env.get("SUPABASE_URL") || "";
const anon = Deno.env.get("SUPABASE_ANON_KEY") || "";
const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
const json = (value: unknown) => JSON.stringify(value);
const escapeHtml = (value: string) => value.replace(/[&<>\"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#039;" }[character] || character));
const reply = (value: unknown, status = 200) => new Response(json(value), { status, headers: { ...cors, "Content-Type": "application/json" } });
const hash = async (value: string) => { const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)); return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join(""); };
const stableJson = (value: unknown): string => { if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null"; if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`; return `{${Object.keys(value as Record<string, unknown>).sort().map((key) => `${JSON.stringify(key)}:${stableJson((value as Record<string, unknown>)[key])}`).join(",")}}`; };
const required = (value: unknown, name: string) => { const text = String(value || "").trim(); if (!text) throw new Error(`${name} is required`); return text; };
const bodyJson = (body: Record<string, unknown> | undefined, key: string, fallback: unknown) => body && typeof body[key] === "object" && body[key] !== null ? body[key] : fallback;

async function authenticated(request: Request): Promise<{ supabase: SupabaseClient; user: User }> {
  const token = request.headers.get("Authorization")?.replace(/^Bearer\s+/i, "");
  if (!token) throw new Error("Sign in required.");
  const supabase = createClient(url, anon, { global: { headers: { Authorization: `Bearer ${token}` } } });
  const { data, error } = await supabase.auth.getUser(token);
  if (error || !data.user) throw new Error("Sign in required.");
  return { supabase, user: data.user };
}
async function organization(supabase: SupabaseClient, user: User, requested?: string) {
  const query = supabase.from("organization_memberships").select("organization_id,role,status").eq("user_id", user.id).eq("status", "active");
  const { data, error } = requested ? await query.eq("organization_id", requested).limit(1) : await query.limit(1);
  if (error || !data?.[0]) throw new Error("An organization-linked account is required.");
  return data[0].organization_id as string;
}
async function staff(supabase: SupabaseClient, user: User, org: string, permission: string) {
  const { data, error } = await supabase.rpc("has_permission", { target_org: org, permission_key: permission });
  if (error || data !== true) throw new Error(`${permission} permission required`);
}
async function list(supabase: SupabaseClient, table: string, org: string, query = "created_at.desc") {
  const orderColumn = table === "enterprise_company_profiles" ? "updated_at" : query.split(".")[0];
  const { data, error } = await supabase.from(table).select("*").eq("organization_id", org).order(orderColumn, { ascending: query.endsWith("asc") }).limit(500);
  if (error) throw new Error(error.message);
  return { ok: true, items: data || [], count: data?.length || 0 };
}
async function insert(supabase: SupabaseClient, table: string, org: string, user: User, value: Record<string, unknown>) {
  const { data, error } = await supabase.from(table).insert({ ...value, organization_id: org, created_by: user.id }).select().single();
  if (error) throw new Error(error.message);
  return { ok: true, item: data };
}
async function publicClient() {
  if (!serviceKey) throw new Error("Public provider adapter is not configured.");
  return createClient(url, serviceKey, { auth: { autoRefreshToken: false, persistSession: false } });
}
async function publicPassenger(path: string, method: string, body: Record<string, unknown>) {
  const passenger = path.match(/^\/api\/passenger\/v1\/portal\/([^/]+)$/);
  const close = path.match(/^\/api\/duty-close\/v1\/([^/]+)$/);
  if (!passenger && !close) return undefined;
  const admin = await publicClient();
  if (passenger) {
    const tokenHash = await hash(passenger[1]);
    const { data: token, error } = await admin.from("passenger_portal_tokens").select("*").eq("token_hash", tokenHash).eq("status", "active").maybeSingle();
    if (error || !token) throw new Error("Passenger portal link is invalid");
    if (new Date(token.expires_at).getTime() < Date.now()) throw new Error("Passenger portal link has expired");
    if (method === "GET") return { ok: true, portal: { id: token.id, label: token.label, expires_at: token.expires_at, organization_id: token.organization_id } };
    const booking = {
      organization_id: token.organization_id,
      customer_id: token.customer_id || null,
      booking_reference: String(body.booking_reference || `PAX-${new Date().toISOString().slice(0, 10).replaceAll("-", "")}-${crypto.randomUUID().slice(0, 6).toUpperCase()}`),
      status: "requested",
      passenger_name: String(body.passenger_name || ""),
      passenger_phone: String(body.passenger_phone || ""),
      passenger_email: String(body.passenger_email || ""),
      pickup: bodyJson(body, "pickup", {}),
      dropoff: bodyJson(body, "dropoff", {}),
      scheduled_at: body.scheduled_at || null,
      duty_type: String(body.duty_type || "local"),
      source: "passenger_portal",
      notes: String(body.notes || ""),
    };
    const { data, error: bookingError } = await admin.from("bookings").insert(booking).select().single();
    if (bookingError) throw new Error(bookingError.message);
    await admin.from("passenger_portal_tokens").update({ last_used_at: new Date().toISOString() }).eq("id", token.id);
    return { ok: true, item: data };
  }
  const tokenHash = await hash(close![1]);
  const { data: job, error } = await admin.from("duty_closure_jobs").select("*").eq("payload->>token_hash", tokenHash).eq("job_type", "sms_close").eq("status", "queued").maybeSingle();
  if (error || !job) throw new Error("Duty closure link is invalid");
  if (method === "GET") return { ok: true, item: { duty_id: job.duty_id, expires_at: (job.payload as Record<string, unknown>)?.expires_at } };
  const start = Number(body.start_odometer); const end = Number(body.end_odometer);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) throw new Error("Valid start and end odometer readings are required");
  const { data: mandatoryItems, error: billingError } = await admin.from("enterprise_billing_items").select("id,code").eq("organization_id", job.organization_id).eq("status", "active").eq("mandatory", true);
  if (billingError) throw new Error(billingError.message);
  const providedItems = new Set((Array.isArray(body.billing_items) ? body.billing_items : []).map((item) => typeof item === "object" ? String(item.id || item.code || item.item_code || "") : String(item)));
  const missingBilling = (mandatoryItems || []).filter((item) => !providedItems.has(item.id) && !providedItems.has(item.code)).map((item) => item.code);
  if (missingBilling.length) throw new Error(`Mandatory billing items are missing: ${missingBilling.join(", ")}`);
  const { data: duty } = await admin.from("duties").select("*").eq("id", job.duty_id).eq("organization_id", job.organization_id).maybeSingle();
  if (!duty) throw new Error("Duty not found");
  const { data: previous } = await admin.from("duty_closures").select("closure_version").eq("organization_id", job.organization_id).eq("duty_id", job.duty_id).order("closure_version", { ascending: false }).limit(1);
  const version = Number(previous?.[0]?.closure_version || 0) + 1;
  const closurePayload = { ...body, source: "sms", start_odometer: start, end_odometer: end };
  const { data: closure, error: closureError } = await admin.from("duty_closures").insert({ organization_id: job.organization_id, duty_id: job.duty_id, status: "completed", closure_version: version, payload: closurePayload, completeness: { start_odometer: true, end_odometer: true, complete: true }, submitted_at: new Date().toISOString() }).select().single();
  if (closureError) throw new Error(closureError.message);
  const evidence = Array.isArray(body.evidence) ? body.evidence : [];
  if (evidence.length) {
    const evidenceRows = evidence.map((item) => ({ organization_id: job.organization_id, closure_id: closure.id, duty_id: job.duty_id, evidence_type: String(item.evidence_type || item.type || "other"), storage_path: String(item.storage_path || ""), sha256: String(item.sha256 || ""), metadata: item.metadata || {}, required: Boolean(item.required), captured_at: item.captured_at || new Date().toISOString() }));
    const { error: evidenceError } = await admin.from("closure_evidence").insert(evidenceRows);
    if (evidenceError) throw new Error(evidenceError.message);
  }
  await admin.from("duties").update({ status: "completed", start_odometer: start, end_odometer: end, completed_at: new Date().toISOString() }).eq("id", job.duty_id);
  await admin.from("duty_closure_jobs").update({ status: "completed", updated_at: new Date().toISOString() }).eq("id", job.id);
  return { ok: true, closure, duty_id: job.duty_id };
}

async function route(supabase: SupabaseClient, user: User, org: string, envelope: Envelope) {
  const path = envelope.path.replace(/\/$/, "") || "/"; const method = (envelope.method || "GET").toUpperCase(); const body = envelope.body || {};
  const collection: Record<string, string> = {
    "/api/enterprise/groups": "enterprise_groups", "/api/enterprise/companies": "enterprise_companies", "/api/enterprise/billing-profiles": "enterprise_billing_profiles", "/api/enterprise/bank-accounts": "enterprise_bank_accounts",
    "/api/enterprise/tax-entities": "enterprise_tax_entities", "/api/enterprise/billing-items": "enterprise_billing_items", "/api/enterprise/custom-fields": "enterprise_custom_fields",
    "/api/enterprise/plans": "enterprise_plan_subscriptions", "/api/enterprise/usage": "enterprise_usage_events", "/api/passenger/portal-links": "passenger_portal_tokens",
    "/api/allotment-exceptions": "allotment_exceptions", "/api/duty-closure-jobs": "duty_closure_jobs",
  };
  if (path === "/api/enterprise/groups/members" && method === "POST") {
    await staff(supabase, user, org, "enterprise.manage");
    const { data, error } = await supabase.from("enterprise_group_members").insert({ organization_id: org, group_id: required(body.group_id, "group_id"), entity_type: required(body.entity_type, "entity_type"), entity_id: required(body.entity_id, "entity_id") }).select().single();
    if (error) throw new Error(error.message);
    return { ok: true, item: data };
  }
  if (collection[path]) {
    const permission = path.includes("allotment") ? "enterprise.booking" : path.includes("duty-closure") ? "enterprise.evidence" : "enterprise.manage";
    await staff(supabase, user, org, permission);
    if (method === "GET") return list(supabase, collection[path], org);
    if (path === "/api/passenger/portal-links") {
      if (body.idempotency_key) { const { data: replay } = await supabase.from("passenger_portal_tokens").select("*").eq("organization_id", org).eq("idempotency_key", String(body.idempotency_key)).maybeSingle(); if (replay) return { ok: true, item: replay, idempotent_replay: true, portal_path: null, token_replay: false }; }
      const raw = crypto.randomUUID() + crypto.randomUUID(); const expires = body.expires_at || new Date(Date.now() + 7 * 86400000).toISOString();
      const result = await insert(supabase, collection[path], org, user, { customer_id: body.customer_id || null, token_hash: await hash(raw), label: String(body.label || "Passenger request portal"), expires_at: expires, status: "active", idempotency_key: body.idempotency_key || null });
      return { ...result, portal_token: raw, portal_path: `/api/passenger/v1/portal/${raw}`, portal_url: `/?passenger_token=${encodeURIComponent(raw)}` };
    }
    return insert(supabase, collection[path], org, user, {
      ...body,
      metadata: body.metadata || {}, options: body.options || [], rules: body.rules || {}, entitlements: body.entitlements || {}, payload: body.payload || {}, resolution: body.resolution || {},
    });
  }
  if (path === "/api/enterprise/company-profile" || path === "/api/enterprise/sso/config" || path === "/api/enterprise/booking-controls") {
    const table = path === "/api/enterprise/company-profile" ? "enterprise_company_profiles" : path === "/api/enterprise/sso/config" ? "enterprise_sso_configs" : "booking_control_rules";
    await staff(supabase, user, org, "enterprise.manage");
    if (method === "GET") return list(supabase, table, org);
    const unique = path === "/api/enterprise/sso/config" ? { provider: String(body.provider || "oidc") } : path === "/api/enterprise/company-profile" ? { company_id: body.company_id || null } : { name: String(body.name || "Default controls") };
    const { data: existing } = await supabase.from(table).select("id").eq("organization_id", org).match(unique).maybeSingle();
    const values: Json = { ...body, ...unique, organization_id: org, created_by: user.id, updated_by: user.id, updated_at: new Date().toISOString() };
    const query = existing ? supabase.from(table).update(values).eq("id", existing.id).select().single() : supabase.from(table).insert(values).select().single();
    const { data, error } = await query; if (error) throw new Error(error.message); return { ok: true, item: data };
  }
  if (path === "/api/availability/calendar") {
    await staff(supabase, user, org, "enterprise.booking");
    const start = envelope.query?.start || new Date().toISOString().slice(0, 10); const end = envelope.query?.end || start;
    const [vehicleResult, driverResult, dutyResult] = await Promise.all([
      supabase.from("vehicles").select("id,registration_number,vehicle_group,city,status").eq("organization_id", org).not("status", "in", "(inactive,archived)"),
      supabase.from("drivers").select("id,full_name,city,status").eq("organization_id", org).not("status", "in", "(inactive,archived)"),
      supabase.from("duties").select("id,driver_id,vehicle_id,reporting_at,status").eq("organization_id", org).gte("reporting_at", `${start}T00:00:00Z`).lte("reporting_at", `${end}T23:59:59Z`).order("reporting_at")
    ]);
    if (vehicleResult.error || driverResult.error || dutyResult.error) throw new Error(vehicleResult.error?.message || driverResult.error?.message || dutyResult.error?.message || "Availability query failed");
    const busyDrivers = new Set((dutyResult.data || []).filter((d) => !["completed", "cancelled"].includes(d.status)).map((d) => d.driver_id)); const busyVehicles = new Set((dutyResult.data || []).filter((d) => !["completed", "cancelled"].includes(d.status)).map((d) => d.vehicle_id));
    return { ok: true, range: { start, end }, resources: { vehicles: (vehicleResult.data || []).map((v) => ({ ...v, available: !busyVehicles.has(v.id) })), drivers: (driverResult.data || []).map((d) => ({ ...d, available: !busyDrivers.has(d.id) })) }, duties: dutyResult.data || [] };
  }
  const quote = path.match(/^\/api\/bookings\/([^/]+)\/quote$/);
  if (quote && method === "POST") { await staff(supabase, user, org, "enterprise.booking"); return supabase.rpc("calculate_enterprise_booking_quote", { p_organization_id: org, p_booking_id: quote[1], p_actor: user.id, p_duration_minutes: Number(body.duration_minutes || 0), p_distance_km: Number(body.distance_km || 0), p_included_km: Number(body.included_km || 0), p_idempotency_key: body.idempotency_key || null }).then(({ data, error }) => { if (error) throw new Error(error.message); return data; }); }
  const request = path.match(/^\/api\/bookings\/([^/]+)\/allotment-requests$/);
  if (request) { await staff(supabase, user, org, "enterprise.booking"); if (method === "GET") { const { data, error } = await supabase.from("allotment_requests").select("*").eq("organization_id", org).eq("booking_id", request[1]).order("created_at", { ascending: false }); if (error) throw new Error(error.message); return { ok: true, items: data || [] }; } const supplierIds = Array.isArray(body.supplier_ids) ? body.supplier_ids : [body.supplier_id]; const rows = supplierIds.filter(Boolean).map((supplier_id) => ({ organization_id: org, booking_id: request[1], supplier_id, request_type: body.request_type || "multi_supplier", status: "requested", idempotency_key: body.idempotency_key ? `${body.idempotency_key}:${supplier_id}` : null, payload: body, expires_at: body.expires_at || null, created_by: user.id })); const { data, error } = await supabase.from("allotment_requests").upsert(rows, { onConflict: "organization_id,idempotency_key" }).select(); if (error) throw new Error(error.message); return { ok: true, items: data || [] }; }
  const response = path.match(/^\/api\/allotment-requests\/([^/]+)\/respond$/);
  if (response && method === "POST") { await staff(supabase, user, org, "enterprise.booking"); const { data, error } = await supabase.from("allotment_responses").insert({ organization_id: org, request_id: response[1], supplier_id: body.supplier_id || null, status: required(body.status, "status"), amount_paise: body.amount_paise || null, eta_minutes: body.eta_minutes || null, reason: body.reason || "", payload: body }).select().single(); if (error) throw new Error(error.message); await supabase.from("allotment_requests").update({ status: body.status, offered_amount_paise: body.amount_paise || null, eta_minutes: body.eta_minutes || null }).eq("id", response[1]).eq("organization_id", org); return { ok: true, item: data }; }
  const duty = path.match(/^\/api\/duties\/([^/]+)\/(execution-profile|otp|otp\/verify|media|evidence-bundle|slip|adjustments|sms-close|network-execution|dco|attached-driver|garage-transfer)$/);
  if (duty) {
    const dutyId = duty[1]; const action = duty[2]; await staff(supabase, user, org, "enterprise.evidence");
    if (action === "execution-profile") { if (method === "GET") { const { data, error } = await supabase.from("duty_execution_profiles").select("*").eq("organization_id", org).eq("duty_id", dutyId).maybeSingle(); if (error) throw new Error(error.message); return { ok: true, item: data }; } const values = { organization_id: org, duty_id: dutyId, source: body.source || "dashboard", driver_mode: body.driver_mode || "assigned", garage_start: body.garage_start || "", garage_end: body.garage_end || "", network_supplier_id: body.network_supplier_id || null, attached_driver_id: body.attached_driver_id || null, dco_user_id: body.dco_user_id || null, config: body.config || {}, created_by: user.id }; const { data, error } = await supabase.from("duty_execution_profiles").upsert(values, { onConflict: "organization_id,duty_id" }).select().single(); if (error) throw new Error(error.message); return { ok: true, item: data }; }
    if (["network-execution", "dco", "attached-driver", "garage-transfer"].includes(action)) { const sourceMap: Record<string, string> = { "network-execution": "network_driver", dco: "dco", "attached-driver": "attached_driver", "garage-transfer": "garage_to_garage" }; return route(supabase, user, org, { ...envelope, path: `/api/duties/${dutyId}/execution-profile`, body: { ...body, source: sourceMap[action] } }); }
    if (action === "otp" && method === "POST") { const raw = String(Math.floor(100000 + Math.random() * 900000)); const { data, error } = await supabase.from("duty_otps").insert({ organization_id: org, duty_id: dutyId, otp_type: body.otp_type || "start", otp_hash: await hash(raw), expires_at: new Date(Date.now() + 15 * 60000).toISOString(), created_by: user.id }).select().single(); if (error) throw new Error(error.message); return { ok: true, item: { id: data.id, duty_id: dutyId, otp_type: data.otp_type, expires_at: data.expires_at }, otp: raw }; }
    if (action === "otp/verify" && method === "POST") { const otpType = String(body.otp_type || "start"); const { data, error } = await supabase.from("duty_otps").select("*").eq("organization_id", org).eq("duty_id", dutyId).eq("otp_type", otpType).eq("status", "issued").order("created_at", { ascending: false }).limit(1).maybeSingle(); if (error || !data) throw new Error("Active OTP not found"); if (new Date(data.expires_at).getTime() < Date.now()) throw new Error("OTP expired"); if (await hash(String(body.otp || "")) !== data.otp_hash) { await supabase.from("duty_otps").update({ attempts: Number(data.attempts || 0) + 1 }).eq("id", data.id); throw new Error("OTP is incorrect"); } const { error: verifyError } = await supabase.from("duty_otps").update({ status: "verified", verified_at: new Date().toISOString() }).eq("id", data.id); if (verifyError) throw new Error(verifyError.message); return { ok: true, verified: true, otp_type: otpType }; }
    if (action === "media" && method === "POST") {
      const bucket = Deno.env.get("AXIOM_DUTY_EVIDENCE_BUCKET") || "duty-evidence";
      let pathValue = String(body.storage_path || `duty/${org}/${dutyId}/${crypto.randomUUID()}`);
      let signedUrl = pathValue;
      let mediaStatus = "ready";
      if (body.base64_content && body.storage_path) {
        const binary = Uint8Array.from(atob(String(body.base64_content)), (character) => character.charCodeAt(0));
        const storageClient = serviceKey ? createClient(url, serviceKey, { auth: { autoRefreshToken: false, persistSession: false } }) : supabase;
        const { error: uploadError } = await storageClient.storage.from(bucket).upload(pathValue, binary, { contentType: String(body.content_type || "application/octet-stream"), upsert: false });
        if (uploadError) throw new Error(uploadError.message);
        const signed = await storageClient.storage.from(bucket).createSignedUrl(pathValue, 60 * 60 * 24);
        if (signed.error) throw new Error(signed.error.message);
        signedUrl = signed.data.signedUrl; mediaStatus = "stored";
      } else if (!body.storage_path) {
        pathValue = `mock://duty/${dutyId}/${crypto.randomUUID()}`;
        signedUrl = `${pathValue}?signed=mock-${crypto.randomUUID()}`;
        mediaStatus = "mock_pending_storage";
      }
      const { data, error } = await supabase.from("duty_media_objects").insert({ organization_id: org, duty_id: dutyId, media_type: body.media_type || "attachment", storage_path: pathValue, signed_url: signedUrl, sha256: body.sha256 || "", metadata: { ...(body.metadata || {}), bucket, storage_mode: mediaStatus }, status: mediaStatus, created_by: user.id }).select().single(); if (error) throw new Error(error.message); return { ok: true, item: data, signed_url: signedUrl, storage_bucket: bucket };
    }
    if (action === "evidence-bundle") {
      const [{ data: dutyRow, error: dutyError }, { data: closure }, { data: evidence }, { data: media }, { data: adjustments }] = await Promise.all([
        supabase.from("duties").select("*").eq("organization_id", org).eq("id", dutyId).maybeSingle(),
        supabase.from("duty_closures").select("*").eq("organization_id", org).eq("duty_id", dutyId).order("closure_version", { ascending: false }).limit(1).maybeSingle(),
        supabase.from("closure_evidence").select("*").eq("organization_id", org).eq("duty_id", dutyId).order("captured_at"),
        supabase.from("duty_media_objects").select("*").eq("organization_id", org).eq("duty_id", dutyId).order("created_at"),
        supabase.from("duty_adjustments").select("*").eq("organization_id", org).eq("duty_id", dutyId).order("created_at"),
      ]);
      if (dutyError) throw new Error(dutyError.message); if (!dutyRow) throw new Error("Duty not found");
      const content = { duty: dutyRow, closure: closure || null, evidence: evidence || [], media: media || [], adjustments: adjustments || [] };
      const canonical = stableJson(content); const bundleHash = await hash(canonical);
      const { data: existing, error: existingError } = await supabase.from("duty_evidence_bundles").select("*").eq("organization_id", org).eq("duty_id", dutyId).eq("bundle_hash", bundleHash).maybeSingle();
      if (existingError) throw new Error(existingError.message);
      if (existing) return { ok: true, item: existing, immutable: true, bundle_hash: bundleHash, replay: true };
      const bucket = Deno.env.get("AXIOM_DUTY_EVIDENCE_BUCKET") || "duty-evidence";
      const storagePath = `bundles/${org}/${dutyId}/${bundleHash}.json`;
      const storageClient = serviceKey ? createClient(url, serviceKey, { auth: { autoRefreshToken: false, persistSession: false } }) : supabase;
      const upload = await storageClient.storage.from(bucket).upload(storagePath, new TextEncoder().encode(canonical), { contentType: "application/json", upsert: false });
      if (upload.error && !/already exists|duplicate/i.test(upload.error.message)) throw new Error(upload.error.message);
      const signed = await storageClient.storage.from(bucket).createSignedUrl(storagePath, 60 * 60 * 24);
      if (signed.error) throw new Error(signed.error.message);
      const { data: created, error: createError } = await supabase.from("duty_evidence_bundles").insert({ organization_id: org, duty_id: dutyId, bundle_hash: bundleHash, content, storage_path: storagePath, signed_url: signed.data.signedUrl, status: "immutable", created_by: user.id }).select().single();
      if (createError) throw new Error(createError.message);
      return { ok: true, item: created, immutable: true, bundle_hash: bundleHash, signed_url: signed.data.signedUrl, storage_bucket: bucket };
    }
    if (action === "slip") { const { data: closure } = await supabase.from("duty_closures").select("*").eq("organization_id", org).eq("duty_id", dutyId).order("closure_version", { ascending: false }).limit(1).maybeSingle(); const { data: evidence } = await supabase.from("closure_evidence").select("*").eq("organization_id", org).eq("duty_id", dutyId).order("captured_at"); const content = { duty_id: dutyId, closure, evidence: evidence || [], generated_at: new Date().toISOString(), format: "combined-duty-slip" }; const printable = escapeHtml(JSON.stringify(content, null, 2)); const printHtml = `<!doctype html><html><head><meta charset="utf-8"><title>Axiom Fleet duty slip ${escapeHtml(dutyId)}</title><style>body{font:14px system-ui;color:#17202b;margin:32px}pre{white-space:pre-wrap;background:#f5f7fa;padding:18px;border-radius:8px}@media print{body{margin:10mm}}</style></head><body><h1>Axiom Fleet · Combined duty slip</h1><pre>${printable}</pre></body></html>`; const { data, error } = await supabase.from("duty_slip_documents").upsert({ organization_id: org, duty_id: dutyId, document_type: "combined_duty_slip", content, storage_path: `mock://duty-slips/${dutyId}.html`, status: "ready", created_by: user.id }, { onConflict: "organization_id,duty_id,document_type" }).select().single(); if (error) throw new Error(error.message); return { ok: true, item: data, format: "html-printable", print_html: printHtml }; }
    if (action === "adjustments" && method === "POST") { const adjustment = required(body.adjustment_type, "adjustment_type"); if (!["credit", "debit"].includes(adjustment)) throw new Error("adjustment_type must be credit or debit"); const { data, error } = await supabase.from("duty_adjustments").insert({ organization_id: org, duty_id: dutyId, adjustment_type: adjustment, amount_paise: Number(body.amount_paise || 0), reason: required(body.reason, "reason"), evidence: body.evidence || {}, created_by: user.id }).select().single(); if (error) throw new Error(error.message); return { ok: true, item: data }; }
    if (action === "sms-close" && method === "POST") { const raw = crypto.randomUUID() + crypto.randomUUID(); const expires = new Date(Date.now() + 24 * 3600000).toISOString(); const { data, error } = await supabase.from("duty_closure_jobs").insert({ organization_id: org, duty_id: dutyId, job_type: "sms_close", status: "queued", next_run_at: expires, payload: { token_hash: await hash(raw), expires_at: expires }, created_by: user.id }).select().single(); if (error) throw new Error(error.message); return { ok: true, item: { job_id: data.id, expires_at: expires }, action_token: raw, action_path: `/api/duty-close/v1/${raw}` }; }
  }
  if (path === "/api/duty-closure-jobs/run" && method === "POST") { await staff(supabase, user, org, "enterprise.evidence"); return supabase.rpc("process_enterprise_closure_jobs", { p_organization_id: org, p_limit: Number(body.limit || 100) }).then(({ data, error }) => { if (error) throw new Error(error.message); return data; }); }
  throw new Error(`Enterprise route not implemented: ${method} ${path}`);
}

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") return new Response("ok", { headers: cors });
  try {
    const envelope = await request.json() as Envelope;
    const publicResult = await publicPassenger(envelope.path, envelope.method || "GET", envelope.body || {});
    if (publicResult !== undefined) return reply(publicResult);
    const { supabase, user } = await authenticated(request);
    const org = await organization(supabase, user, envelope.organization_id);
    return reply(await route(supabase, user, org, envelope));
  } catch (error) {
    return reply({ ok: false, error: error instanceof Error ? error.message : String(error || "Enterprise request failed") }, 400);
  }
});
