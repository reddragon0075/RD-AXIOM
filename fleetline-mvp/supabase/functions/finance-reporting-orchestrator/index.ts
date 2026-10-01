import { createClient, type SupabaseClient, type User } from "https://esm.sh/@supabase/supabase-js@2";

/* Authenticated finance/reporting boundary. Multi-write invoice generation and
 * dunning are database RPCs so browser callers never construct partial ledgers. */
const allowedOrigin = (Deno.env.get("AXIOM_ALLOWED_ORIGIN") || Deno.env.get("AXIOM_ALLOWED_ORIGINS")?.split(",")[0] || "").trim();
const cors = {
  ...(allowedOrigin ? { "Access-Control-Allow-Origin": allowedOrigin, "Vary": "Origin" } : {}),
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
type Json = Record<string, any>;
type Envelope = { path: string; method?: string; organization_id?: string | null; query?: Json; body?: Json };
function reply(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { ...cors, "Content-Type": "application/json" } }); }
function required(value: unknown, name: string) { const result = String(value || "").trim(); if (!result) throw new Error(`${name} is required`); return result; }
function asObject(value: unknown): Json { return value && typeof value === "object" && !Array.isArray(value) ? value as Json : {}; }
function queryValue(query: Json | undefined, key: string, fallback = "") { return String(query?.[key] ?? fallback); }
function now() { return new Date().toISOString(); }

async function authenticated(request: Request) {
  const authorization = request.headers.get("Authorization"); const url = Deno.env.get("SUPABASE_URL"); const anonKey = Deno.env.get("SUPABASE_ANON_KEY");
  if (!authorization || !url || !anonKey) throw new Error("Authenticated Supabase configuration is required");
  const token = authorization.replace(/^Bearer\s+/i, ""); const supabase = createClient(url, anonKey, { global: { headers: { Authorization: `Bearer ${token}` } } });
  const { data, error } = await supabase.auth.getUser(token); if (error || !data.user) throw new Error("Sign in required");
  return { supabase, user: data.user as User };
}
async function organization(supabase: SupabaseClient, user: User, requested: unknown) {
  const value = String(requested || "").trim(); let query = supabase.from("organization_memberships").select("organization_id").eq("user_id", user.id).eq("status", "active").limit(20); if (value) query = query.eq("organization_id", value);
  const { data, error } = await query; if (error) throw new Error(error.message); const memberships = data || [];
  if (value && memberships.some((row) => row.organization_id === value)) return value; if (!value && memberships.length === 1) return String(memberships[0].organization_id); throw new Error("Organization access denied");
}
async function list(supabase: SupabaseClient, table: string, organizationId: string, query: Json = {}) { let request = supabase.from(table).select("*").eq("organization_id", organizationId).order("created_at", { ascending: false }).limit(Math.min(Math.max(Number(query.limit || 100), 1), 500)); if (query.status && query.status !== "all") request = request.eq("status", query.status); const { data, error } = await request; if (error) throw new Error(error.message); return data || []; }
async function ageing(supabase: SupabaseClient, organizationId: string) {
  const { data, error } = await supabase.from("invoices").select("id, invoice_number, customer_id, total_paise, due_at, status, customers(name)").eq("organization_id", organizationId).not("status", "in", "(paid,void)").order("due_at", { ascending: true }).limit(5000);
  if (error) throw new Error(error.message);
  const buckets: Json = { current: [], "1_30": [], "31_60": [], "61_90": [], "90_plus": [] }; const timestamp = Date.now();
  for (const invoice of data || []) { const due = invoice.due_at ? new Date(invoice.due_at).getTime() : timestamp; const age = Math.max(0, Math.floor((timestamp - due) / 86400000)); const bucket = age === 0 ? "current" : age <= 30 ? "1_30" : age <= 60 ? "31_60" : age <= 90 ? "61_90" : "90_plus"; buckets[bucket].push({ ...invoice, age_days: age }); }
  return { ok: true, buckets: Object.fromEntries(Object.entries(buckets).map(([key, items]) => [key, { count: (items as Json[]).length, total_paise: (items as Json[]).reduce((sum, item) => sum + Number(item.total_paise || 0), 0), items }])), generated_at: now() };
}
async function runReport(supabase: SupabaseClient, organizationId: string, definition: Json) {
  const type = String(definition.report_type || "ageing"); if (type === "ageing") return ageing(supabase, organizationId);
  if (type === "duty_count") { const { data, error } = await supabase.from("duties").select("status").eq("organization_id", organizationId).limit(5000); if (error) throw new Error(error.message); const counts: Json = {}; for (const row of data || []) counts[row.status] = Number(counts[row.status] || 0) + 1; return { ok: true, report_type: type, rows: Object.entries(counts).map(([status, count]) => ({ status, count })) }; }
  if (type === "customer_summary") { const { data, error } = await supabase.from("invoices").select("customer_id, total_paise, customers(name)").eq("organization_id", organizationId).limit(5000); if (error) throw new Error(error.message); const grouped: Json = {}; for (const row of data || []) { const customer = Array.isArray(row.customers) ? row.customers[0] : row.customers; const id = row.customer_id || "unassigned"; grouped[id] ||= { customer_id: id, customer_name: customer?.name || "Unassigned", invoiced_paise: 0, invoices: 0 }; grouped[id].invoiced_paise += Number(row.total_paise || 0); grouped[id].invoices += 1; } return { ok: true, report_type: type, rows: Object.values(grouped) }; }
  const { data, error } = await supabase.from("duties").select("vehicle_id, vehicles(registration_number), calculation_snapshot").eq("organization_id", organizationId).limit(5000); if (error) throw new Error(error.message); const grouped: Json = {}; for (const row of data || []) { const vehicle = Array.isArray(row.vehicles) ? row.vehicles[0] : row.vehicles; const id = row.vehicle_id || "unassigned"; const snapshot = asObject(row.calculation_snapshot); grouped[id] ||= { vehicle_id: id, registration_number: vehicle?.registration_number || "Unassigned", duties: 0, revenue_paise: 0 }; grouped[id].duties += 1; grouped[id].revenue_paise += Number(snapshot.total_paise || 0); } return { ok: true, report_type: type, rows: Object.values(grouped) };
}
async function route(supabase: SupabaseClient, user: User, organizationId: string, envelope: Envelope) {
  const path = String(envelope.path || "").replace(/\/$/, "") || "/"; const method = String(envelope.method || "GET").toUpperCase(); const body = asObject(envelope.body); const query = asObject(envelope.query);
  if (path === "/api/invoices/generate" && method === "POST") { const { data, error } = await supabase.rpc("generate_invoice_run", { p_organization_id: organizationId, p_actor: user.id, p_mode: required(body.mode || "per_duty", "mode"), p_payload: body, p_idempotency_key: body.idempotency_key || null }); if (error) throw new Error(error.message); return data; }
  if (path === "/api/invoice-runs" && method === "GET") return { ok: true, items: await list(supabase, "invoice_runs", organizationId, query) };
  if (path === "/api/collections/dunning" && method === "GET") return { ok: true, items: await list(supabase, "dunning_actions", organizationId, query) };
  if (path === "/api/collections/dunning/run" && method === "POST") { const { data, error } = await supabase.rpc("run_dunning_run", { p_organization_id: organizationId, p_actor: user.id, p_channel: body.channel || "email" }); if (error) throw new Error(error.message); return data; }
  if (path === "/api/reports/ageing" || path === "/api/finance/ageing") { if (method !== "GET") throw new Error("Ageing is read-only"); return ageing(supabase, organizationId); }
  const definitionMatch = path.match(/^\/api\/reports\/definitions(?:\/([^/]+)(\/run)?)?$/);
  if (definitionMatch) {
    const id = definitionMatch[1];
    if (method === "GET") return { ok: true, items: await list(supabase, "report_definitions", organizationId, query) };
    if (!id && method === "POST") { const reportType = required(body.report_type || "ageing", "report_type"); if (!["ageing", "duty_count", "vehicle_profitability", "customer_summary"].includes(reportType)) throw new Error("Unsupported report type"); const { data, error } = await supabase.from("report_definitions").insert({ organization_id: organizationId, name: required(body.name || reportType, "name"), report_type: reportType, filters: asObject(body.filters), columns: Array.isArray(body.columns) ? body.columns : [], created_by: user.id }).select().single(); if (error) throw new Error(error.message); return { ok: true, item: data }; }
    if (id && definitionMatch[2] === "/run" && method === "POST") { const { data, error } = await supabase.from("report_definitions").select("*").eq("id", id).eq("organization_id", organizationId).maybeSingle(); if (error) throw new Error(error.message); if (!data) throw new Error("Report definition not found"); return runReport(supabase, organizationId, data); }
  }
  if (path === "/api/export-profiles" && method === "GET") return { ok: true, items: await list(supabase, "export_profiles", organizationId, query) };
  if (path === "/api/export-profiles" && method === "POST") { const target = String(body.target || "csv").toLowerCase(); if (!["csv", "json"].includes(target)) throw new Error("Only CSV and JSON export profiles are supported"); const { data, error } = await supabase.from("export_profiles").insert({ organization_id: organizationId, name: required(body.name || "CSV export", "name"), target, mapping: asObject(body.mapping), created_by: user.id }).select().single(); if (error) throw new Error(error.message); return { ok: true, item: data }; }
  throw new Error(`Finance/reporting route not found: ${method} ${path}`);
}
Deno.serve(async (request) => { if (request.method === "OPTIONS") return new Response("ok", { headers: cors }); try { const { supabase, user } = await authenticated(request); const envelope = await request.json() as Envelope; const organizationId = await organization(supabase, user, envelope.organization_id); return reply(await route(supabase, user, organizationId, envelope)); } catch (error) { return reply({ ok: false, error: error instanceof Error ? error.message : String(error || "Finance request failed") }, 400); } });
