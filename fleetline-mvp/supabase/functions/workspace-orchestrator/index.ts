import { createClient, type SupabaseClient, type User } from "https://esm.sh/@supabase/supabase-js@2";

/*
 * Axiom Fleet exception-first workspace boundary.  The action list is a
 * projection over canonical bookings, duties, evidence and finance rows.  It
 * never creates a second trip ledger and it never exposes provider secrets.
 */
const url = Deno.env.get("SUPABASE_URL") || "";
const anon = Deno.env.get("SUPABASE_ANON_KEY") || "";
const allowedOrigin = (Deno.env.get("AXIOM_ALLOWED_ORIGIN") || Deno.env.get("AXIOM_ALLOWED_ORIGINS")?.split(",")[0] || "").trim();
const cors = {
  ...(allowedOrigin ? { "Access-Control-Allow-Origin": allowedOrigin, "Vary": "Origin" } : {}),
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info, x-request-id",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};
type Json = Record<string, any>;
type Envelope = { path: string; method?: string; organization_id?: string; query?: Json; body?: Json };
const reply = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { ...cors, "Content-Type": "application/json" } });
const object = (value: unknown): Json => value && typeof value === "object" && !Array.isArray(value) ? value as Json : {};
const required = (value: unknown, name: string) => { const text = String(value || "").trim(); if (!text) throw new Error(`${name} is required`); return text; };
const limitOf = (query: Json) => Math.max(1, Math.min(Number(query.limit || 12), 50));
const priorityOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
const terminalDuty = new Set(["cancelled", "completed", "closed", "settled"]);
const terminalBooking = new Set(["cancelled", "completed"]);

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
async function staff(supabase: SupabaseClient, org: string) {
  const { data, error } = await supabase.rpc("has_permission", { target_org: org, permission_key: "operations.action_center" });
  if (error || data !== true) throw new Error("operations.action_center permission required");
}
async function rows(supabase: SupabaseClient, table: string, org: string, select = "*"): Promise<Json[]> {
  const result = await supabase.from(table).select(select).eq("organization_id", org);
  if (result.error) throw new Error(result.error.message);
  return (result.data || []) as Json[];
}
function action(id: string, values: Json): Json { return { id, status: "open", blocking: false, ...values }; }
function dateValue(value: unknown) { return value ? new Date(String(value)).getTime() : Number.MAX_SAFE_INTEGER; }
function stale(value: unknown) { const time = value ? new Date(String(value)).getTime() : 0; return !time || Date.now() - time > 15 * 60 * 1000; }

async function nextActions(supabase: SupabaseClient, user: User, org: string, query: Json) {
  await staff(supabase, org);
  const [requests, bookings, duties, drivers, readiness, alerts, points, invoices, payments, proofs, states] = await Promise.all([
    rows(supabase, "gap_passenger_booking_requests", org, "id,status,passenger_name,scheduled_at,pickup,dropoff").then((items) => items.filter((item: Json) => item.status === "pending")),
    rows(supabase, "bookings", org, "id,booking_reference,status,passenger_name,scheduled_at,pickup,dropoff"),
    rows(supabase, "duties", org, "id,booking_id,driver_id,vehicle_id,status,reporting_at"),
    rows(supabase, "drivers", org, "id,user_id,full_name,status"),
    rows(supabase, "gap_device_readiness", org, "id,user_id,readiness_status,blockers,checked_at").then((items) => items.filter((item: Json) => item.readiness_status === "blocked")),
    rows(supabase, "gap_driver_alert_events", org, "id,duty_id,alert_type,severity,occurred_at,status").then((items) => items.filter((item: Json) => item.status === "open")),
    rows(supabase, "track_points", org, "duty_id,recorded_at"),
    rows(supabase, "invoices", org, "id,invoice_number,status,total_paise"),
    rows(supabase, "payments", org, "invoice_id,amount_paise,status"),
    rows(supabase, "duty_proofs", org, "duty_id"),
    rows(supabase, "workspace_action_states", org, "user_id,action_id,status,snooze_until,note,updated_at").then((items) => items.filter((item: Json) => item.user_id === user.id)),
  ]);
  const driverMatches = drivers.filter((item: Json) => item.user_id === user.id);
  const driverIds = driverMatches.length ? new Set(driverMatches.map((item: Json) => item.id)) : null;
  const visibleDuties = driverIds && driverIds.size ? duties.filter((item: Json) => driverIds.has(item.driver_id)) : duties;
  const activeDuties = visibleDuties.filter((item: Json) => !terminalDuty.has(String(item.status)));
  const activeBookingIds = new Set(activeDuties.map((item: Json) => item.booking_id));
  const result: Json[] = [];

  for (const item of requests.slice(0, 50)) result.push(action(`passenger_request:${item.id}`, {
    category: "booking", priority: "high", title: `Approve ${item.passenger_name || "passenger"}'s booking request`,
    why: "A passenger request is waiting for an operator decision before it can become a Fleet booking.", next_step: "Review the route, policy and reporting time, then approve or reject it.", page: "bookings", entity_type: "passenger_booking_request", entity_id: item.id, source: "gap_passenger_booking_requests", due_at: item.scheduled_at, blocking: true,
    signals: ["pending_request", item.pickup?.label || "pickup not labelled", item.dropoff?.label || "drop-off not labelled"],
  }));
  for (const item of bookings.filter((row: Json) => !terminalBooking.has(String(row.status)) && !activeBookingIds.has(row.id)).slice(0, 50)) result.push(action(`booking_unassigned:${item.id}`, {
    category: "dispatch", priority: "high", title: `Find a vehicle for ${item.booking_reference || "booking"}`,
    why: "This booking has no active duty assignment, so the service promise is not yet covered.", next_step: "Run availability and confirm a compliant driver and vehicle.", page: "duties", entity_type: "booking", entity_id: item.id, source: "bookings", due_at: item.scheduled_at, blocking: true, signals: ["no_active_duty", item.passenger_name || "passenger not named"],
  }));
  for (const item of activeDuties) {
    const missing = [!item.driver_id ? "driver" : "", !item.vehicle_id ? "vehicle" : ""].filter(Boolean);
    if (!missing.length) continue;
    result.push(action(`duty_assignment:${item.id}`, {
      category: "dispatch", priority: "high", title: `Assign ${missing.join(" and ")} for duty ${String(item.id).slice(0, 8).toUpperCase()}`,
      why: "The duty exists, but its assignment is incomplete and cannot be safely dispatched.", next_step: "Open the duty and use availability or a controlled replacement.", page: "duties", entity_type: "duty", entity_id: item.id, source: "duties", due_at: item.reporting_at, blocking: true, signals: missing.map((value) => `missing_${value}`),
    }));
  }
  for (const item of readiness) {
    if (driverIds && driverIds.size && !driverIds.has(item.user_id)) continue;
    const blockers = Array.isArray(item.blockers) ? item.blockers : [];
    result.push(action(`device_readiness:${item.id}`, {
      category: "field", priority: "high", title: "Finish Driver device readiness", why: `Field readiness is blocked by ${blockers.slice(0, 3).join(", ") || "device permissions"}.`, next_step: "Open the Driver readiness checklist on the physical device and re-check permissions.", page: "fleet", entity_type: "device_readiness", entity_id: item.id, source: "gap_device_readiness", blocking: true, signals: blockers,
    }));
  }
  for (const item of alerts) {
    const duty = visibleDuties.find((row: Json) => row.id === item.duty_id);
    if (driverIds && driverIds.size && !duty) continue;
    const priority = item.severity === "critical" ? "critical" : item.severity === "high" || item.severity === "warning" ? "high" : "medium";
    result.push(action(`driver_alert:${item.id}`, {
      category: "safety", priority, title: `Review ${String(item.alert_type || "operational").replaceAll("_", " ")} alert`, why: `A ${item.severity || "warning"} driver alert is still open for a duty.`, next_step: "Open the safety event, acknowledge the operator decision and resolve only after evidence is reviewed.", page: "safety", entity_type: "driver_alert", entity_id: item.id, source: "gap_driver_alert_events", due_at: item.occurred_at, blocking: priority === "critical", signals: [item.alert_type, item.severity],
    }));
  }
  for (const item of activeDuties) {
    const last = points.filter((point: Json) => point.duty_id === item.id).sort((a: Json, b: Json) => dateValue(b.recorded_at) - dateValue(a.recorded_at))[0];
    if (!stale(last?.recorded_at)) continue;
    result.push(action(`gps_stale:${item.id}`, {
      category: "field", priority: "high", title: `Check GPS signal for duty ${String(item.id).slice(0, 8).toUpperCase()}`, why: "The active duty has no location point in the last 15 minutes; Axiom does not infer a live position.", next_step: "Contact the driver or inspect device readiness before treating the route as live.", page: "safety", entity_type: "duty", entity_id: item.id, source: "track_points", blocking: true, signals: ["gps_stale", `last_seen:${last?.recorded_at || "never"}`],
    }));
  }
  const paid = new Map<string, number>();
  for (const payment of payments) if (["succeeded", "paid"].includes(String(payment.status))) paid.set(payment.invoice_id, (paid.get(payment.invoice_id) || 0) + Number(payment.amount_paise || 0));
  for (const invoice of invoices.filter((item: Json) => ["issued", "sent", "overdue"].includes(String(item.status)))) {
    const outstanding = Number(invoice.total_paise || 0) - (paid.get(invoice.id) || 0);
    if (outstanding <= 0) continue;
    result.push(action(`invoice_outstanding:${invoice.id}`, {
      category: "finance", priority: "medium", title: `Follow up invoice ${invoice.invoice_number || invoice.id}`, why: "The invoice is issued but recorded successful payments do not cover its total.", next_step: "Open Billing to reconcile the source invoice, payment request or approved auto-collect attempt.", page: "billing", entity_type: "invoice", entity_id: invoice.id, source: "invoices", signals: [`outstanding_paise:${outstanding}`, invoice.status],
    }));
  }
  for (const item of visibleDuties.filter((row: Json) => ["completed", "closed", "settled"].includes(String(row.status)))) {
    if (!proofs.some((proof: Json) => proof.duty_id === item.id)) result.push(action(`duty_proof:${item.id}`, {
      category: "evidence", priority: "medium", title: `Complete proof for duty ${String(item.id).slice(0, 8).toUpperCase()}`, why: "The duty is closed, but no proof record is attached to the canonical duty ledger.", next_step: "Add the signed slip, odometer, OTP or receipt evidence before final billing review.", page: "duties", entity_type: "duty", entity_id: item.id, source: "duty_proofs", signals: ["no_proof_record"],
    }));
  }

  for (const state of states) {
    const found = result.find((item) => item.id === state.action_id);
    if (found) {
      found.status = state.status === "open" ? "open" : state.status;
      found.note = state.note || "";
      if (state.status === "snoozed" && state.snooze_until && new Date(state.snooze_until).getTime() > Date.now()) found.snoozed_until = state.snooze_until;
      if (state.status === "snoozed" && (!state.snooze_until || new Date(state.snooze_until).getTime() <= Date.now())) found.status = "open";
    }
  }
  const visible = result.filter((item) => item.status !== "resolved" && !item.snoozed_until).sort((a, b) => (priorityOrder[a.priority] - priorityOrder[b.priority]) || (dateValue(a.due_at) - dateValue(b.due_at)) || String(a.title).localeCompare(String(b.title)));
  const now = new Date().toISOString();
  return {
    ok: true, items: visible.slice(0, limitOf(query)), total_available: visible.length,
    summary: { open: visible.length, critical: visible.filter((item) => item.priority === "critical").length, high: visible.filter((item) => item.priority === "high").length, blocking: visible.filter((item) => item.blocking).length, acknowledged: visible.filter((item) => item.status === "acknowledged").length, contract_version: "2026-10-01", generated_at: now, model: "deterministic_exception_projection" },
  };
}

async function route(supabase: SupabaseClient, user: User, org: string, envelope: Envelope) {
  const path = String(envelope.path || "").replace(/\/$/, "") || "/";
  const method = String(envelope.method || "GET").toUpperCase();
  const body = object(envelope.body);
  if (path === "/api/workspace/next-actions" && method === "GET") return nextActions(supabase, user, org, object(envelope.query));
  const statusRoute = path.match(/^\/api\/workspace\/next-actions\/([^/]+)\/status$/);
  if (statusRoute && method === "POST") {
    await staff(supabase, org);
    const status = required(body.status, "status");
    if (!["acknowledged", "snoozed", "resolved", "reopened"].includes(status)) throw new Error("status must be acknowledged, snoozed, resolved or reopened");
    const snoozeUntil = status === "snoozed" ? body.snooze_until || new Date(Date.now() + 4 * 60 * 60 * 1000).toISOString() : null;
    const saved = await supabase.from("workspace_action_states").upsert({ organization_id: org, user_id: user.id, action_id: statusRoute[1], status: status === "reopened" ? "open" : status, snooze_until: snoozeUntil, note: body.note || "", updated_at: new Date().toISOString() }, { onConflict: "organization_id,user_id,action_id" }).select("action_id,status,snooze_until,note,updated_at").single();
    if (saved.error) throw new Error(saved.error.message);
    return { ok: true, item: saved.data, audit_reference: statusRoute[1] };
  }
  throw new Error(`Workspace route not found: ${method} ${path}`);
}

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") return new Response("ok", { headers: cors });
  try {
    const envelope = object(await request.json().catch(() => ({}))) as Envelope;
    const { supabase, user } = await authenticated(request);
    const org = await organization(supabase, user, envelope.organization_id);
    return reply(await route(supabase, user, org, envelope));
  } catch (error) {
    return reply({ error: error instanceof Error ? error.message : "Workspace request failed", code: "workspace_boundary_error" }, 400);
  }
});
