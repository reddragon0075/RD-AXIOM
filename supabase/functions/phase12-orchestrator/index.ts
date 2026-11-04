import { createClient, type SupabaseClient, type User } from "https://esm.sh/@supabase/supabase-js@2";

/*
 * Axiom Fleet Phase 1/2 production boundary.
 *
 * The browser sends an inner method/path envelope from supabase/client.js.  This
 * function deliberately uses the caller's bearer token with the anon key: RLS
 * and has_permission remain active for every collection read/write.  A future
 * high-volume deployment may move the deterministic provider work to a queue,
 * but it must preserve the idempotency and organization checks below.
 */

const allowedOrigin = (Deno.env.get("AXIOM_ALLOWED_ORIGIN") || Deno.env.get("AXIOM_ALLOWED_ORIGINS")?.split(",")[0] || "").trim();
const cors = {
  ...(allowedOrigin ? { "Access-Control-Allow-Origin": allowedOrigin, "Vary": "Origin" } : {}),
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const MASTER_KINDS = new Set([
  "duty_types", "vehicle_groups", "taxes", "billing_items", "documents", "labels",
  "employees", "passengers", "feedback_forms", "branches", "operating_regions",
  "suppliers", "drivers", "vehicles", "rate_cards", "sites", "shifts",
]);
const INTEGRATIONS = [
  { provider_type: "hrms", provider_name: "mock_hrms", mode: "mock", status: "available" },
  { provider_type: "gps", provider_name: "mock_gps", mode: "mock", status: "available" },
  { provider_type: "maps", provider_name: "mock_maps", mode: "mock", status: "available" },
  { provider_type: "messaging", provider_name: "mock_messaging", mode: "mock", status: "available" },
  { provider_type: "storage", provider_name: "mock_storage", mode: "mock", status: "available" },
];

type Json = Record<string, unknown>;
type Envelope = { path: string; method?: string; organization_id?: string | null; query?: Json; body?: Json };

function reply(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { ...cors, "Content-Type": "application/json" } });
}
function message(error: unknown) { return error instanceof Error ? error.message : String(error || "Phase 1/2 request failed"); }
function required(value: unknown, name: string): string {
  const result = String(value || "").trim();
  if (!result) throw new Error(`${name} is required`);
  return result;
}
function asObject(value: unknown): Json { return value && typeof value === "object" && !Array.isArray(value) ? value as Json : {}; }
function safeInt(value: unknown, fallback = 0): number {
  const number = Number(value);
  return Number.isSafeInteger(number) ? number : fallback;
}
function cleanSearch(value: unknown): string {
  return String(value || "").replace(/[(),.*]/g, " ").trim().slice(0, 80);
}
function queryValue(query: Json | undefined, key: string, fallback = "") { return String(query?.[key] ?? fallback); }
function now() { return new Date().toISOString(); }

async function sha256(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest)).map((part) => part.toString(16).padStart(2, "0")).join("");
}

async function authenticatedClient(request: Request): Promise<{ supabase: SupabaseClient; user: User }> {
  const authorization = request.headers.get("Authorization");
  const url = Deno.env.get("SUPABASE_URL");
  const anonKey = Deno.env.get("SUPABASE_ANON_KEY");
  if (!authorization || !url || !anonKey) throw new Error("Authenticated Supabase configuration is required");
  const token = authorization.replace(/^Bearer\s+/i, "");
  const supabase = createClient(url, anonKey, { global: { headers: { Authorization: `Bearer ${token}` } } });
  const { data, error } = await supabase.auth.getUser(token);
  if (error || !data.user) throw new Error("Sign in required");
  return { supabase, user: data.user };
}

async function resolveOrganization(supabase: SupabaseClient, user: User, requested: unknown): Promise<string> {
  const requestedId = String(requested || "").trim();
  let membershipQuery = supabase.from("organization_memberships").select("organization_id, status").eq("user_id", user.id).eq("status", "active").limit(20);
  if (requestedId) membershipQuery = membershipQuery.eq("organization_id", requestedId);
  const { data: memberships, error } = await membershipQuery;
  if (error) throw new Error(error.message);
  const rows = memberships || [];
  if (requestedId && rows.some((row) => row.organization_id === requestedId)) return requestedId;
  if (!requestedId && rows.length === 1) return String(rows[0].organization_id);
  if (!requestedId && rows.length > 1) throw new Error("An active organization is required");
  if (requestedId) {
    const { data: owned, error: ownerError } = await supabase.from("organizations").select("id").eq("id", requestedId).eq("owner_user_id", user.id).maybeSingle();
    if (!ownerError && owned?.id) return String(owned.id);
  }
  throw new Error("Organization access denied");
}

async function driverOrganization(supabase: SupabaseClient, user: User): Promise<string | null> {
  const { data, error } = await supabase.from("drivers").select("organization_id").eq("user_id", user.id).limit(1).maybeSingle();
  if (error) return null;
  return data?.organization_id ? String(data.organization_id) : null;
}

async function insertRow(supabase: SupabaseClient, table: string, row: Json): Promise<Json> {
  const { data, error } = await supabase.from(table).insert(row).select().single();
  if (error) throw new Error(error.message);
  return data as Json;
}
async function updateRow(supabase: SupabaseClient, table: string, id: string, organizationId: string, patch: Json): Promise<Json> {
  const { data, error } = await supabase.from(table).update(patch).eq("id", id).eq("organization_id", organizationId).select().single();
  if (error) throw new Error(error.message);
  return data as Json;
}
async function listRows(supabase: SupabaseClient, table: string, organizationId: string, query: Json | undefined, order = "created_at.desc", limit = 100): Promise<Json[]> {
  let request = supabase.from(table).select("*").eq("organization_id", organizationId).order(order.split(".")[0], { ascending: order.endsWith(".asc") }).limit(Math.min(Math.max(limit, 1), 200));
  const status = queryValue(query, "status");
  if (status && status !== "all") request = request.eq("status", status);
  const { data, error } = await request;
  if (error) throw new Error(error.message);
  return (data || []) as Json[];
}
function collection(items: Json[], extra: Json = {}) { return { ok: true, items, count: items.length, ...extra }; }

async function mobileHome(supabase: SupabaseClient, user: User, organizationId: string | null) {
  if (!organizationId) return { ok: true, summary: { open_duties: 0, in_progress: 0, open_alerts: 0, stale_locations: 0 }, next_duty: null, duties: [], alerts: [], updated_at: now() };
  const driver = await supabase.from("drivers").select("id").eq("organization_id", organizationId).eq("user_id", user.id).limit(1).maybeSingle();
  if (driver.error || !driver.data?.id) return { ok: true, summary: { open_duties: 0, in_progress: 0, open_alerts: 0, stale_locations: 0 }, next_duty: null, duties: [], alerts: [], updated_at: now() };
  const { data: duties, error: dutyError } = await supabase.from("duties").select("*").eq("organization_id", organizationId).eq("driver_id", driver.data.id).not("status", "in", "(completed,cancelled)").order("reporting_at", { ascending: true }).limit(20);
  if (dutyError) throw new Error(dutyError.message);
  const { data: alerts } = await supabase.from("alerts").select("*").eq("organization_id", organizationId).eq("status", "open").order("created_at", { ascending: false }).limit(20);
  const rows = (duties || []) as Json[];
  return {
    ok: true,
    summary: {
      open_duties: rows.length,
      in_progress: rows.filter((d) => ["started", "en_route", "in_progress"].includes(String(d.status))).length,
      open_alerts: (alerts || []).length,
      stale_locations: (alerts || []).filter((a) => String(a.alert_type || "").includes("stale")).length,
    },
    next_duty: rows[0] || null,
    duties: rows,
    alerts: (alerts || []) as Json[],
    updated_at: now(),
  };
}

async function masters(supabase: SupabaseClient, organizationId: string, method: string, path: string, query: Json, body: Json, user: User) {
  const match = path.match(/^\/api\/masters\/registry(?:\/([^/]+)(?:\/(archive|restore))?)?$/);
  if (!match) throw new Error("Unsupported master registry path");
  const id = match[1];
  const action = match[2];
  if (id === "export" && method === "GET") {
    const { data, error } = await supabase.from("phase12_master_records").select("kind,code,name,status,version,effective_from,effective_to,metadata").eq("organization_id", organizationId).order("kind", { ascending: true }).order("name", { ascending: true }).limit(5000);
    if (error) throw new Error(error.message);
    const quote = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
    const rows = [["kind", "code", "name", "status", "version", "effective_from", "effective_to", "metadata"], ...(data || []).map((item) => [item.kind, item.code, item.name, item.status, item.version, item.effective_from, item.effective_to, JSON.stringify(item.metadata || {})])];
    return { ok: true, format: "csv", content: rows.map((row) => row.map(quote).join(",")).join("\\n"), count: rows.length - 1 };
  }
  if (id === "import" && method === "POST") {
    const records = Array.isArray(body.records) ? body.records.slice(0, 500) : [];
    if (!records.length) throw new Error("records are required");
    const results: Json[] = [];
    for (const record of records) {
      try {
        const kind = required(record.kind, "kind");
        if (!MASTER_KINDS.has(kind)) throw new Error("Unsupported master kind");
        const item = await insertRow(supabase, "phase12_master_records", { organization_id: organizationId, kind, code: required(record.code, "code").toUpperCase(), name: required(record.name, "name"), status: record.status || "active", version: 1, effective_from: record.effective_from || null, effective_to: record.effective_to || null, metadata: asObject(record.metadata), created_by: user.id });
        await insertRow(supabase, "phase12_versions", { organization_id: organizationId, entity_type: `master:${kind}`, entity_id: item.id, version: 1, change_type: "import", snapshot: item, created_by: user.id });
        results.push({ ok: true, code: item.code, item });
      } catch (error) {
        results.push({ ok: false, code: String(record.code || ""), error: message(error) });
      }
    }
    return { ok: true, imported: results.filter((result) => result.ok).length, failed: results.filter((result) => !result.ok).length, results };
  }
  if (!id && method === "GET") {
    const kind = queryValue(query, "kind");
    if (kind && !MASTER_KINDS.has(kind)) throw new Error("Unsupported master kind");
    let request = supabase.from("phase12_master_records").select("*").eq("organization_id", organizationId).order("kind", { ascending: true }).order("name", { ascending: true }).limit(200);
    if (kind) request = request.eq("kind", kind);
    const status = queryValue(query, "status", "active");
    const q = cleanSearch(queryValue(query, "q"));
    if (status !== "all") request = request.eq("status", status);
    if (q) request = request.or(`code.ilike.*${q}*,name.ilike.*${q}*`);
    const { data, error } = await request;
    if (error) throw new Error(error.message);
    return collection((data || []) as Json[], { kind: kind || null, kinds: Array.from(MASTER_KINDS).sort() });
  }
  if (!id && method === "POST") {
    const kind = required(body.kind, "kind");
    if (!MASTER_KINDS.has(kind)) throw new Error("Unsupported master kind");
    const item = await insertRow(supabase, "phase12_master_records", { organization_id: organizationId, kind, code: required(body.code, "code").toUpperCase(), name: required(body.name, "name"), status: body.status || "active", version: 1, effective_from: body.effective_from || null, effective_to: body.effective_to || null, metadata: asObject(body.metadata), created_by: user.id });
    await insertRow(supabase, "phase12_versions", { organization_id: organizationId, entity_type: `master:${kind}`, entity_id: item.id, version: 1, change_type: "create", snapshot: item, created_by: user.id });
    return { ok: true, item };
  }
  if (!id) throw new Error("A master record id is required");
  const { data: current, error: currentError } = await supabase.from("phase12_master_records").select("*").eq("id", id).eq("organization_id", organizationId).maybeSingle();
  if (currentError) throw new Error(currentError.message);
  if (!current) throw new Error("Master record not found");
  if (method === "GET") {
    const { data: versions, error } = await supabase.from("phase12_versions").select("*").eq("organization_id", organizationId).eq("entity_id", id).order("version", { ascending: false });
    if (error) throw new Error(error.message);
    return { ok: true, item: { ...current, versions: versions || [] } };
  }
  if (method !== "PATCH" && method !== "POST") throw new Error("Unsupported master method");
  const nextVersion = safeInt(current.version, 1) + 1;
  const patch: Json = { version: nextVersion, updated_at: now() };
  if (action === "archive") patch.status = "archived";
  else if (action === "restore") patch.status = "active";
  else Object.assign(patch, { code: body.code ? String(body.code).toUpperCase() : current.code, name: body.name || current.name, status: body.status || current.status, effective_from: body.effective_from ?? current.effective_from, effective_to: body.effective_to ?? current.effective_to, metadata: body.metadata ?? current.metadata });
  const item = await updateRow(supabase, "phase12_master_records", id, organizationId, patch);
  await insertRow(supabase, "phase12_versions", { organization_id: organizationId, entity_type: `master:${current.kind}`, entity_id: id, version: nextVersion, change_type: action || "update", snapshot: item, created_by: user.id });
  return { ok: true, item };
}

async function operations(supabase: SupabaseClient, organizationId: string, method: string, path: string, query: Json, body: Json, user: User) {
  if (path === "/api/operations/rosters") {
    if (method === "GET") return collection(await listRows(supabase, "phase12_roster_versions", organizationId, query, "plan_date.desc"));
    if (method === "POST") {
      const routePlanId = required(body.route_plan_id, "route_plan_id");
      const { data: prior } = await supabase.from("phase12_roster_versions").select("version").eq("organization_id", organizationId).eq("route_plan_id", routePlanId).order("version", { ascending: false }).limit(1).maybeSingle();
      const version = safeInt(prior?.version, 0) + 1;
      const item = await insertRow(supabase, "phase12_roster_versions", { organization_id: organizationId, route_plan_id: routePlanId, plan_date: required(body.plan_date, "plan_date"), version, status: body.status || "draft", assignments: Array.isArray(body.assignments) ? body.assignments : [], constraints: asObject(body.constraints), created_by: user.id });
      return { ok: true, item };
    }
  }
  if (path === "/api/operations/live-board" && method === "GET") {
    const duties = await listRows(supabase, "duties", organizationId, query, "reporting_at.asc");
    const ids = duties.map((d) => d.id).filter(Boolean);
    const bookingIds = duties.map((d) => d.booking_id).filter(Boolean);
    const bookings = bookingIds.length ? await supabase.from("bookings").select("id,booking_reference,passenger_name,pickup,dropoff,scheduled_at").eq("organization_id", organizationId).in("id", bookingIds) : { data: [], error: null };
    if (bookings.error) throw new Error(bookings.error.message);
    const bookingMap = new Map(((bookings.data || []) as Json[]).map((booking) => [String(booking.id), booking]));
    let etas: Json[] = [], tracks: Json[] = [], assignments: Json[] = [];
    if (ids.length) {
      const [etaResult, trackResult, assignmentResult] = await Promise.all([
        supabase.from("phase12_eta_snapshots").select("*").eq("organization_id", organizationId).in("duty_id", ids).order("created_at", { ascending: false }).limit(200),
        supabase.from("track_points").select("*").eq("organization_id", organizationId).in("duty_id", ids).order("recorded_at", { ascending: false }).limit(200),
        supabase.from("p0_roster_assignments").select("*").eq("organization_id", organizationId).in("duty_id", ids).order("offered_at", { ascending: false }).limit(200),
      ]);
      if (etaResult.error) throw new Error(etaResult.error.message);
      if (trackResult.error) throw new Error(trackResult.error.message);
      if (assignmentResult.error) throw new Error(assignmentResult.error.message);
      etas = (etaResult.data || []) as Json[]; tracks = (trackResult.data || []) as Json[]; assignments = (assignmentResult.data || []) as Json[];
    }
    const latest = (rows: Json[], key: string) => { const map = new Map<string, Json>(); rows.forEach((row) => { if (!map.has(String(row[key]))) map.set(String(row[key]), row); }); return map; };
    const latestEta = latest(etas, "duty_id"), latestTrack = latest(tracks, "duty_id"), latestAssignment = latest(assignments, "duty_id");
    const items = duties.map((duty) => { const booking = bookingMap.get(String(duty.booking_id)) || {}; return { duty_id: duty.id, booking_reference: booking.booking_reference || null, passenger_name: booking.passenger_name || null, status: duty.status, reporting_at: duty.reporting_at, scheduled_at: booking.scheduled_at || null, driver_id: duty.driver_id, vehicle_id: duty.vehicle_id, assignment_status: latestAssignment.get(String(duty.id))?.status || null, last_gps: latestTrack.get(String(duty.id)) || null, eta: latestEta.get(String(duty.id)) || null }; });
    return collection(items, { updated_at: now() });
  }
  const etaMatch = path.match(/^\/api\/operations\/duties\/([^/]+)\/eta$/);
  if (etaMatch && method === "POST") {
    const dutyId = etaMatch[1];
    const { data: duty, error: dutyError } = await supabase.from("duties").select("id").eq("organization_id", organizationId).eq("id", dutyId).maybeSingle();
    if (dutyError) throw new Error(dutyError.message);
    if (!duty) throw new Error("Duty not found");
    const seed = [...dutyId].reduce((sum, char) => sum + char.charCodeAt(0), 0);
    const duration = safeInt(body.duration_minutes, 18 + (seed % 28));
    const distance = Number(body.distance_km || (3 + (seed % 19))).toFixed(2);
    const item = await insertRow(supabase, "phase12_eta_snapshots", { organization_id: organizationId, duty_id: dutyId, source: body.source || "mock_maps", latitude: body.latitude ?? null, longitude: body.longitude ?? null, distance_km: Number(distance), duration_minutes: duration, eta_at: new Date(Date.now() + duration * 60_000).toISOString(), deviation_minutes: safeInt(body.deviation_minutes, seed % 7), status: body.status || "estimated", payload: { ...body, deterministic: true }, });
    return { ok: true, item, provider: "mock_maps" };
  }
  if (path === "/api/operations/bulk" && method === "POST") {
    const operation = required(body.operation || body.action, "operation");
    const idempotencyKey = required(body.idempotency_key || body.idempotencyKey, "idempotency_key");
    const existing = await supabase.from("phase12_bulk_jobs").select("*").eq("organization_id", organizationId).eq("idempotency_key", idempotencyKey).maybeSingle();
    if (existing.error) throw new Error(existing.error.message);
    if (existing.data) return { ok: true, replayed: true, item: existing.data, results: existing.data.result || [] };
    const ids = Array.isArray(body.entity_ids) ? body.entity_ids.map(String) : Array.isArray(body.ids) ? body.ids.map(String) : [];
    const entityType = String(body.entity_type || "duty");
    const job = await insertRow(supabase, "phase12_bulk_jobs", { organization_id: organizationId, idempotency_key: idempotencyKey, operation, entity_type: entityType, entity_ids: ids, payload: asObject(body), status: "running", result: [], created_by: user.id });
    const results: Json[] = [];
    if (operation === "refresh_eta") {
      for (const dutyId of ids.slice(0, 100)) {
        const result = await operations(supabase, organizationId, "POST", `/api/operations/duties/${dutyId}/eta`, {}, { source: "mock_maps", bulk_job_id: job.id }, user);
        results.push({ id: dutyId, status: "updated", item: asObject(result).item || asObject(result) });
      }
    } else if (entityType === "duty" && ["bulk_assign", "assign", "bulk_edit", "edit", "archive", "restore"].includes(operation)) {
      const patch = asObject(body.patch);
      for (const dutyId of ids.slice(0, 200)) {
        const { data: duty, error: dutyError } = await supabase.from("duties").select("id,status").eq("organization_id", organizationId).eq("id", dutyId).maybeSingle();
        if (dutyError) throw new Error(dutyError.message);
        if (!duty) { results.push({ id: dutyId, status: "error", error: "Duty not found" }); continue; }
        let updates: Json = {};
        if (["bulk_assign", "assign"].includes(operation)) {
          const driverId = required(body.driver_id, "driver_id");
          const { data: driver } = await supabase.from("drivers").select("id,status").eq("organization_id", organizationId).eq("id", driverId).maybeSingle();
          if (!driver || ["inactive", "archived"].includes(String(driver.status || "").toLowerCase())) throw new Error("Active driver is required");
          updates = { driver_id: driverId, status: "assigned" };
          if (body.vehicle_id) {
            const { data: vehicle } = await supabase.from("vehicles").select("id").eq("organization_id", organizationId).eq("id", String(body.vehicle_id)).maybeSingle();
            if (!vehicle) throw new Error("Vehicle is not in this tenant");
            updates.vehicle_id = String(body.vehicle_id);
          }
        } else if (["archive", "restore"].includes(operation)) {
          updates = { status: operation === "archive" ? "archived" : "draft" };
        } else {
          const status = patch.status === undefined ? undefined : String(patch.status).toLowerCase();
          if (status !== undefined) updates.status = status;
          if (patch.reporting_at !== undefined) updates.reporting_at = patch.reporting_at || null;
          if (!Object.keys(updates).length) { results.push({ id: dutyId, status: "error", error: "A duty patch is required" }); continue; }
        }
        const updated = await updateRow(supabase, "duties", dutyId, organizationId, { ...updates, updated_at: now() });
        const event = await insertRow(supabase, "phase12_events", { organization_id: organizationId, event_type: `duty.bulk.${operation}`, entity_type: "duty", entity_id: dutyId, payload: { operation, updates }, actor_id: user.id });
        results.push({ id: dutyId, status: "updated", item: updated, audit_reference: event.id });
      }
    }
    const completed = await updateRow(supabase, "phase12_bulk_jobs", String(job.id), organizationId, { status: "completed", result: results, completed_at: now() });
    const auditEvent = await insertRow(supabase, "phase12_events", { organization_id: organizationId, event_type: `bulk.${operation}.completed`, entity_type: entityType, entity_id: null, payload: { ids, result_count: results.length }, actor_id: user.id });
    return { ok: true, replayed: false, item: completed, results, audit_reference: auditEvent.id };
  }
  throw new Error("Unsupported operations path");
}

async function safety(supabase: SupabaseClient, organizationId: string, method: string, path: string, query: Json, body: Json, user: User) {
  if (path === "/api/safety/monitor" && method === "GET") {
    const incidents = await listRows(supabase, "p0_safety_incidents", organizationId, query, "opened_at.desc");
    const { data: alerts, error } = await supabase.from("alerts").select("*").eq("organization_id", organizationId).eq("status", "open").order("created_at", { ascending: false }).limit(200);
    if (error) throw new Error(error.message);
    return { ok: true, alerts: (alerts || []) as Json[], incidents, items: incidents, stale_gps: (alerts || []).filter((item) => String(item.alert_type || "").includes("stale")).length, updated_at: now() };
  }
  if (path === "/api/safety/monitor/evaluate" && method === "POST") {
    const items = await listRows(supabase, "p0_safety_incidents", organizationId, { status: "open" }, "opened_at.desc");
    return { ok: true, evaluated_at: now(), alerts: items, count: items.length };
  }
  const evidence = path.match(/^\/api\/safety\/incidents\/([^/]+)\/evidence$/);
  if (evidence && method === "GET") {
    const { data, error } = await supabase.from("phase12_safety_evidence").select("*").eq("organization_id", organizationId).eq("incident_id", evidence[1]).order("captured_at", { ascending: false });
    if (error) throw new Error(error.message);
    return collection((data || []) as Json[]);
  }
  if (evidence && method === "POST") {
    const payload = asObject(body.payload || body);
    const item = await insertRow(supabase, "phase12_safety_evidence", { organization_id: organizationId, incident_id: evidence[1], evidence_type: required(body.evidence_type || body.type, "evidence_type"), storage_path: String(body.storage_path || body.path || ""), source_event_id: body.source_event_id || null, sha256: String(body.sha256 || await sha256(payload)), metadata: payload, captured_by: user.id });
    return { ok: true, item, storage: { provider: "mock_storage", path: item.storage_path } };
  }
  const closure = path.match(/^\/api\/safety\/incidents\/([^/]+)\/closure-approval(?:\/([^/]+)\/decision)?$/);
  if (closure && method === "GET") {
    const { data, error } = await supabase.from("phase12_closure_approvals").select("*").eq("organization_id", organizationId).eq("incident_id", closure[1]).order("created_at", { ascending: false });
    if (error) throw new Error(error.message);
    return collection((data || []) as Json[]);
  }
  if (closure && method === "POST") {
    const incidentId = closure[1], requestedApprovalId = closure[2];
    const decision = String(body.decision || body.status || "request");
    if (!requestedApprovalId && (decision === "request" || decision === "pending")) {
      const item = await insertRow(supabase, "phase12_closure_approvals", { organization_id: organizationId, incident_id: incidentId, status: "pending", requested_by: user.id, review_note: String(body.note || "") });
      return { ok: true, item };
    }
    if (! ["approved", "rejected"].includes(decision)) throw new Error("Closure decision must be approved or rejected");
    let approvalId = requestedApprovalId;
    if (!approvalId) {
      const { data: pending, error } = await supabase.from("phase12_closure_approvals").select("id").eq("organization_id", organizationId).eq("incident_id", incidentId).eq("status", "pending").order("created_at", { ascending: false }).limit(1).maybeSingle();
      if (error) throw new Error(error.message);
      approvalId = pending?.id ? String(pending.id) : "";
    }
    if (!approvalId) throw new Error("A pending closure approval is required");
    const item = await updateRow(supabase, "phase12_closure_approvals", approvalId, organizationId, { status: decision, reviewed_by: user.id, review_note: String(body.note || ""), reviewed_at: now() });
    if (decision === "approved") await updateRow(supabase, "p0_safety_incidents", incidentId, organizationId, { status: "closed", closed_by: user.id, closed_at: now() });
    return { ok: true, item };
  }
  throw new Error("Unsupported safety path");
}

async function network(supabase: SupabaseClient, organizationId: string, method: string, path: string, query: Json, body: Json, user: User) {
  if (path === "/api/network/v1/scorecard-formulas" || path === "/api/network/v1/scorecard-formulas/active") {
    if (method === "GET") {
      const rows = await listRows(supabase, "phase12_scorecard_formulas", organizationId, { status: path.endsWith("/active") ? "active" : queryValue(query, "status", "all") }, "created_at.desc");
      return path.endsWith("/active") ? { ok: true, item: rows[0] || null, items: rows } : collection(rows);
    }
    if (method === "POST") return { ok: true, item: await insertRow(supabase, "phase12_scorecard_formulas", { organization_id: organizationId, code: required(body.code, "code"), version: safeInt(body.version, 1), status: body.status || "active", weights: asObject(body.weights), thresholds: asObject(body.thresholds), created_by: user.id }) };
  }
  if (path === "/api/network/v1/scorecard-disputes") {
    if (method === "GET") return collection(await listRows(supabase, "phase12_scorecard_disputes", organizationId, query, "created_at.desc"));
    if (method === "POST") return { ok: true, item: await insertRow(supabase, "phase12_scorecard_disputes", { organization_id: organizationId, scorecard_run_id: required(body.scorecard_run_id, "scorecard_run_id"), reason: required(body.reason, "reason"), status: "open", evidence: asObject(body.evidence), created_by: user.id }) };
  }
  const serviceOrder = path.match(/^\/api\/network\/v1\/service-orders\/([^/]+)\/(activation|replacements|scorecard|reconciliation)$/);
  if (!serviceOrder) throw new Error("Unsupported Network path");
  const serviceOrderId = serviceOrder[1];
  const operation = serviceOrder[2];
  if (operation === "activation") {
    const { data: existing, error: existingError } = await supabase.from("network_service_orders").select("*").eq("organization_id", organizationId).eq("id", serviceOrderId).maybeSingle();
    if (existingError) throw new Error(existingError.message);
    const awardId = body.award_id || existing?.award_id || serviceOrderId;
    const { data: checks, error: checksError } = await supabase.from("network_activation_checks").select("*").eq("organization_id", organizationId).eq("award_id", awardId);
    if (checksError) throw new Error(checksError.message);
    const blocking = (checks || []).filter((check) => check.blocking && !["passed", "complete", "completed"].includes(String(check.status)));
    if (method === "GET") return { ok: true, service_order_id: serviceOrderId, ready: !blocking.length, checks: checks || [], blocking_checks: blocking, item: existing || null };
    if (method === "POST") {
      if (existing) return { ok: true, replayed: true, item: existing };
      if (blocking.length && body.force !== true) return { ok: false, error: "Activation gates are incomplete", blocking_checks: blocking };
      const item = await insertRow(supabase, "network_service_orders", { id: serviceOrderId, organization_id: organizationId, award_id: required(body.award_id, "award_id"), contract_id: required(body.contract_id, "contract_id"), requirement_id: required(body.requirement_id, "requirement_id"), vendor_profile_id: required(body.vendor_profile_id, "vendor_profile_id"), status: "active", fleet_booking_id: body.fleet_booking_id || null, fleet_duty_id: body.fleet_duty_id || null, config: asObject(body.config), activated_by: user.id, activated_at: now(), idempotency_key: body.idempotency_key || null });
      return { ok: true, item };
    }
  }
  if (operation === "replacements") {
    if (method === "GET") {
      const { data, error } = await supabase.from("phase12_network_replacements").select("*").eq("organization_id", organizationId).eq("service_order_id", serviceOrderId).order("created_at", { ascending: false }).limit(200);
      if (error) throw new Error(error.message);
      return collection((data || []) as Json[]);
    }
    if (method === "POST") return { ok: true, item: await insertRow(supabase, "phase12_network_replacements", { organization_id: organizationId, service_order_id: serviceOrderId, duty_id: body.duty_id || null, reason: required(body.reason, "reason"), status: "open", replacement_driver_id: body.replacement_driver_id || null, replacement_vehicle_id: body.replacement_vehicle_id || null, due_at: body.due_at || null, evidence: asObject(body.evidence), created_by: user.id }) };
  }
  if (operation === "scorecard" && method === "POST") {
    const periodStart = required(body.period_start, "period_start");
    const periodEnd = required(body.period_end, "period_end");
    const score = Number(body.score || 0);
    const item = await insertRow(supabase, "p0_network_scorecard_runs", { organization_id: organizationId, service_order_id: serviceOrderId, period_start: periodStart, period_end: periodEnd, formula_version: String(body.formula_version || "v1"), sample_size: safeInt(body.sample_size), confidence: String(body.confidence || "cold_start"), score: Number.isFinite(score) ? score : 0, metrics: asObject(body.metrics), status: "computed", created_by: user.id });
    return { ok: true, scorecard_run: item, item };
  }
  if (operation === "reconciliation" && method === "GET") {
    const { data, error } = await supabase.from("phase12_reconciliations").select("*").eq("organization_id", organizationId).eq("service_order_id", serviceOrderId).order("created_at", { ascending: false }).limit(200);
    if (error) throw new Error(error.message);
    return collection((data || []) as Json[]);
  }
  if (operation === "reconciliation" && method === "POST") {
    const expected = safeInt(body.expected_paise), observed = safeInt(body.observed_paise);
    const item = await insertRow(supabase, "phase12_reconciliations", { organization_id: organizationId, service_order_id: serviceOrderId, scorecard_run_id: body.scorecard_run_id || null, statement_id: body.statement_id || null, expected_paise: expected, observed_paise: observed, variance_paise: observed - expected, status: observed === expected ? "matched" : "review", evidence: asObject(body.evidence), created_by: user.id });
    return { ok: true, item, variance_paise: observed - expected };
  }
  throw new Error(`Unsupported Network operation: ${operation}`);
}

async function viewsAndPermissions(supabase: SupabaseClient, organizationId: string, method: string, path: string, query: Json, body: Json, user: User) {
  if (path === "/api/views" || path.startsWith("/api/views/")) {
    const id = path.split("/")[3];
    if (!id && method === "GET") return collection(await listRows(supabase, "phase12_saved_views", organizationId, query, "updated_at.desc"));
    if (!id && method === "POST") return { ok: true, item: await insertRow(supabase, "phase12_saved_views", { organization_id: organizationId, scope: required(body.scope, "scope"), name: required(body.name, "name"), filters: asObject(body.filters), columns: Array.isArray(body.columns) ? body.columns : [], sort: asObject(body.sort), shared: body.shared === true, created_by: user.id }) };
    if (id && method === "PATCH") return { ok: true, item: await updateRow(supabase, "phase12_saved_views", id, organizationId, { name: body.name, filters: asObject(body.filters), columns: Array.isArray(body.columns) ? body.columns : [], sort: asObject(body.sort), shared: body.shared === true, updated_at: now() }) };
  }
  if (path === "/api/permissions/bundles") {
    if (method === "GET") return collection(await listRows(supabase, "phase12_permission_bundles", organizationId, query, "created_at.desc"));
    if (method === "POST") return { ok: true, item: await insertRow(supabase, "phase12_permission_bundles", { organization_id: organizationId, role: required(body.role, "role"), name: required(body.name, "name"), description: String(body.description || ""), permissions: Array.isArray(body.permissions) ? body.permissions : [], version: safeInt(body.version, 1), status: body.status || "active", created_by: user.id }) };
  }
  throw new Error("Unsupported views or permissions path");
}

async function integrations(supabase: SupabaseClient, organizationId: string, method: string, path: string, body: Json, user: User) {
  if (path === "/api/integrations/catalog" && method === "GET") return { ok: true, providers: INTEGRATIONS };
  if (path === "/api/integrations/config") {
    if (method === "GET") return collection(await listRows(supabase, "phase12_integrations", organizationId, {}, "provider_type.asc"));
    if (method === "POST" || method === "PATCH") {
      const providerType = required(body.provider_type, "provider_type");
      const existing = await supabase.from("phase12_integrations").select("id").eq("organization_id", organizationId).eq("provider_type", providerType).maybeSingle();
      if (existing.error) throw new Error(existing.error.message);
      if (existing.data?.id) return { ok: true, item: await updateRow(supabase, "phase12_integrations", String(existing.data.id), organizationId, { provider_name: body.provider_name || providerType, mode: body.mode || "mock", status: body.status || "available", config: asObject(body.config), updated_at: now() }) };
      return { ok: true, item: await insertRow(supabase, "phase12_integrations", { organization_id: organizationId, provider_type: providerType, provider_name: body.provider_name || providerType, mode: body.mode || "mock", status: body.status || "available", config: asObject(body.config), created_by: user.id }) };
    }
  }
  if (path === "/api/integrations/sync" && method === "POST") {
    const providerType = required(body.provider_type, "provider_type");
    const provider = INTEGRATIONS.find((item) => item.provider_type === providerType);
    if (!provider) throw new Error("Unsupported provider boundary");
    const idempotencyKey = body.idempotency_key ? String(body.idempotency_key) : null;
    if (idempotencyKey) {
      const replay = await supabase.from("phase12_integration_events").select("payload,status,external_id").eq("organization_id", organizationId).eq("external_id", idempotencyKey).maybeSingle();
      if (replay.error) throw new Error(replay.error.message);
      if (replay.data) return { ok: true, replayed: true, result: replay.data.payload, idempotency_key: idempotencyKey };
    }
    const reference = idempotencyKey || `phase12-${providerType}-${Date.now()}`;
    const result = { provider_type: providerType, provider_name: provider.provider_name, mode: provider.mode, received: safeInt(body.received, Array.isArray(body.records) ? body.records.length : 0), synced: safeInt(body.synced, Array.isArray(body.records) ? body.records.length : 0), reference };
    const integrationUpsert = await supabase.from("phase12_integrations").upsert({ organization_id: organizationId, provider_type: providerType, provider_name: provider.provider_name, mode: provider.mode, status: "available", config: {}, last_sync_at: now(), created_by: user.id }, { onConflict: "organization_id,provider_type" });
    if (integrationUpsert.error) throw new Error(integrationUpsert.error.message);
    await insertRow(supabase, "phase12_events", { organization_id: organizationId, event_type: `${providerType}.sync`, entity_type: "integration", entity_id: null, payload: result, actor_id: user.id });
    if (idempotencyKey) await insertRow(supabase, "phase12_integration_events", { organization_id: organizationId, provider_type: providerType, event_type: "sync_requested", external_id: idempotencyKey, signature_valid: true, status: "accepted", payload: result });
    return { ok: true, result, idempotency_key: idempotencyKey };
  }
  if (path === "/api/integrations/events" && method === "GET") return collection(await listRows(supabase, "phase12_integration_events", organizationId, {}, "created_at.desc"));
  if (path === "/api/integrations/events" && method === "POST") {
    const providerType = required(body.provider_type, "provider_type"), externalId = required(body.external_id, "external_id");
    const replay = await supabase.from("phase12_integration_events").select("*").eq("organization_id", organizationId).eq("external_id", externalId).maybeSingle();
    if (replay.error) throw new Error(replay.error.message);
    if (replay.data) return { ok: true, replayed: true, item: replay.data, replay_safe: true };
    const item = await insertRow(supabase, "phase12_integration_events", { organization_id: organizationId, provider_type: providerType, event_type: required(body.event_type, "event_type"), external_id: externalId, signature_valid: body.signature_valid === true, status: body.status || "received", payload: asObject(body.payload) });
    return { ok: true, item, replay_safe: true };
  }
  throw new Error("Unsupported integration path");
}

async function handle(envelope: Envelope, supabase: SupabaseClient, user: User) {
  const path = String(envelope.path || "").replace(/\/$/, "") || "/";
  const method = String(envelope.method || "GET").toUpperCase();
  const query = asObject(envelope.query);
  const body = asObject(envelope.body);
  if (path === "/api/mobile/home") {
    let organizationId: string | null = null;
    try { organizationId = await resolveOrganization(supabase, user, envelope.organization_id); } catch (_) { organizationId = await driverOrganization(supabase, user); }
    return mobileHome(supabase, user, organizationId);
  }
  const organizationId = await resolveOrganization(supabase, user, envelope.organization_id);
  if (path.startsWith("/api/masters/registry")) return masters(supabase, organizationId, method, path, query, body, user);
  if (path.startsWith("/api/operations/")) return operations(supabase, organizationId, method, path, query, body, user);
  if (path.startsWith("/api/safety/")) return safety(supabase, organizationId, method, path, query, body, user);
  if (path.startsWith("/api/network/v1/")) return network(supabase, organizationId, method, path, query, body, user);
  if (path.startsWith("/api/views") || path === "/api/permissions/bundles") return viewsAndPermissions(supabase, organizationId, method, path, query, body, user);
  if (path.startsWith("/api/integrations/")) return integrations(supabase, organizationId, method, path, body, user);
  throw new Error(`Phase 1/2 route not implemented: ${method} ${path}`);
}

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (request.method !== "POST") return reply({ error: "POST required" }, 405);
  try {
    const { supabase, user } = await authenticatedClient(request);
    const envelope = asObject(await request.json()) as Envelope;
    const result = await handle(envelope, supabase, user);
    return reply(result);
  } catch (error) {
    const text = message(error);
    const status = /sign in|required|access denied|permission/i.test(text) ? 403 : /not found/i.test(text) ? 404 : 400;
    return reply({ ok: false, error: text }, status);
  }
});
