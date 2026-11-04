import { createClient, type SupabaseClient, type User } from "https://esm.sh/@supabase/supabase-js@2";

/*
 * Production boundary for the corporate-account foundation.
 *
 * The browser sends a path/method/body envelope.  The function resolves the
 * caller's organization from an active membership and uses the caller's bearer
 * token for every PostgREST query, so table RLS remains in force.  Policy and
 * visibility decisions are intentionally server-side and deterministic; the
 * client only receives reasons and candidates, never an authorization secret.
 */
const allowedOrigin = (Deno.env.get("AXIOM_ALLOWED_ORIGIN") || Deno.env.get("AXIOM_ALLOWED_ORIGINS")?.split(",")[0] || "").trim();
const cors = {
  ...(allowedOrigin ? { "Access-Control-Allow-Origin": allowedOrigin, "Vary": "Origin" } : {}),
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
type Json = Record<string, any>;
const scopeKeys = ["branch_ids", "customer_entity_ids", "sister_company_ids", "cities", "vehicle_group_codes", "duty_type_codes", "company_ids"];
const masterKinds = new Set(["duty_types", "vehicle_groups", "billing_items", "taxes", "company_scopes", "pricing_rules", "document_requirements"]);

function reply(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { ...cors, "Content-Type": "application/json" } }); }
function message(error: unknown) { return error instanceof Error ? error.message : String(error || "Corporate request failed"); }
function text(value: unknown, fallback = "") { return String(value ?? fallback).trim(); }
function object(value: unknown): Json { return value && typeof value === "object" && !Array.isArray(value) ? value as Json : {}; }
function list(value: unknown): string[] { return Array.isArray(value) ? Array.from(new Set(value.map((item) => text(item)).filter(Boolean))) : []; }
function scope(value: unknown): Json { const raw = object(value); return Object.fromEntries(scopeKeys.filter((key) => list(raw[key]).length).map((key) => [key, list(raw[key])])); }
function bool(value: unknown, fallback = false) { if (value === undefined || value === null || value === "") return fallback; return value === true || value === 1 || value === "1" || value === "true"; }
function integer(value: unknown, fallback: number | null = null) { if (value === undefined || value === null || value === "") return fallback; const parsed = Number(value); return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : fallback; }
function now() { return new Date(); }
function iso(value: Date) { return value.toISOString(); }
function reason(code: string, messageText: string, severity = "warn", extra: Json = {}) { return { code, message: messageText, severity, ...extra }; }
function queryValue(query: Json | undefined, key: string, fallback = "") { return text(query?.[key], fallback); }

async function sha256(value: string) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest)).map((part) => part.toString(16).padStart(2, "0")).join("");
}
function token() {
  const bytes = new Uint8Array(32); crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
async function auth(request: Request): Promise<{ supabase: SupabaseClient; user: User }> {
  const authorization = request.headers.get("Authorization");
  const url = Deno.env.get("SUPABASE_URL"); const anonKey = Deno.env.get("SUPABASE_ANON_KEY");
  if (!authorization || !url || !anonKey) throw new Error("Authenticated Supabase configuration is required");
  const bearer = authorization.replace(/^Bearer\s+/i, "");
  const supabase = createClient(url, anonKey, { global: { headers: { Authorization: `Bearer ${bearer}` } } });
  const { data, error } = await supabase.auth.getUser(bearer);
  if (error || !data.user) throw new Error("Sign in required");
  return { supabase, user: data.user };
}
async function organization(supabase: SupabaseClient, user: User, requested: unknown) {
  const id = text(requested);
  let query = supabase.from("organization_memberships").select("organization_id").eq("user_id", user.id).eq("status", "active").limit(20);
  if (id) query = query.eq("organization_id", id);
  const { data, error } = await query; if (error) throw new Error(error.message);
  if (id && (data || []).some((row: any) => row.organization_id === id)) return id;
  if (!id && (data || []).length === 1) return String(data![0].organization_id);
  if (id) {
    const { data: owned } = await supabase.from("organizations").select("id").eq("id", id).eq("owner_user_id", user.id).maybeSingle();
    if (owned?.id) return String(owned.id);
  }
  throw new Error("Organization access denied");
}
async function one(supabase: SupabaseClient, table: string, organizationId: string, id?: string) {
  let query = supabase.from(table).select("*").eq("organization_id", organizationId).limit(1);
  if (id) query = query.eq("id", id);
  const { data, error } = await query.maybeSingle(); if (error) throw new Error(error.message); return data as Json | null;
}
async function account(supabase: SupabaseClient, organizationId: string) { return one(supabase, "corporate_accounts", organizationId); }
async function activePolicy(supabase: SupabaseClient, organizationId: string, accountId: string, policyId = "") {
  let query = supabase.from("corporate_policies").select("*").eq("organization_id", organizationId).eq("account_id", accountId);
  if (policyId) query = query.eq("id", policyId); else query = query.eq("status", "active").order("version", { ascending: false }).limit(1);
  const { data, error } = await query.maybeSingle(); if (error) throw new Error(error.message); return data as Json | null;
}
async function member(supabase: SupabaseClient, organizationId: string, accountId: string, user: User) {
  const { data, error } = await supabase.from("corporate_account_users").select("*").eq("organization_id", organizationId).eq("account_id", accountId).eq("user_id", user.id).eq("status", "active").maybeSingle();
  if (error) throw new Error(error.message); return data as Json | null;
}
async function ensureAdminMember(supabase: SupabaseClient, organizationId: string, accountId: string, user: User) {
  const existing = await member(supabase, organizationId, accountId, user);
  if (existing) return existing;
  const { data, error } = await supabase.from("corporate_account_users").insert({
    organization_id: organizationId, account_id: accountId, user_id: user.id,
    email: user.email || "", full_name: String(user.user_metadata?.full_name || user.email || ""),
    account_type: "admin", permission_profile: "admin", status: "active",
    invited_by: user.id, activated_at: iso(now()), grants: [], denies: [], visibility: {},
  }).select().single();
  if (error) throw new Error(error.message);
  return data as Json;
}
const defaultPermissions: Record<string, string[]> = {
  admin: ["account.read", "account.manage", "people.read", "people.manage", "booking.create", "booking.cancel", "booking.approve", "policy.read", "policy.manage", "allotment.evaluate", "allotment.manage", "duty_slip.read", "duty_slip.approve", "duty_slip.reject", "masters.read", "masters.manage"],
  employee_admin: ["account.read", "people.read", "people.manage", "booking.create", "booking.cancel", "booking.approve", "policy.read", "allotment.evaluate", "duty_slip.approve", "duty_slip.reject", "masters.read"],
  booker_passenger: ["account.read", "booking.create", "booking.cancel", "policy.read", "allotment.evaluate", "duty_slip.approve", "duty_slip.reject"],
};
function can(user: User, accountMember: Json | null, permission: string) {
  // Vendor owners are allowed through table/RLS permissions but still get a
  // local role fallback for accounts created before the account-user row.
  if (!accountMember) return false;
  const base = new Set(defaultPermissions[accountMember.permission_profile || accountMember.account_type] || []);
  for (const value of (accountMember.grants || [])) base.add(String(value));
  for (const value of (accountMember.denies || [])) base.delete(String(value));
  return base.has(permission);
}
function requirePermission(memberRow: Json | null, permission: string) { if (!memberRow || !can({} as User, memberRow, permission)) throw new Error(`Corporate permission denied: ${permission}`); }

function scopeReasons(accountScope: Json, userScope: Json, policyScope: Json, request: Json) {
  const reasons: Json[] = [];
  for (const key of scopeKeys) {
    const requested = text(request[key] || request[key.replace(/_ids$/, "")]); if (!requested) continue;
    for (const [layer, source] of [["account", accountScope], ["user", userScope], ["policy", policyScope]] as [string, Json][]) {
      const values = list(source[key]);
      if (values.length && !values.includes(requested)) reasons.push(reason(`${layer}_scope_denied`, `The requested ${key.replaceAll("_", " ")} is outside the ${layer} visibility scope.`, "block", { field: key }));
    }
  }
  return reasons;
}
async function audit(supabase: SupabaseClient, organizationId: string, _user: User, action: string, entityId: string, metadata: Json) {
  // The RPC is SECURITY DEFINER but re-checks organization membership.  Direct
  // audit table inserts are intentionally not exposed to browser sessions.
  await supabase.rpc("corporate_append_audit_event", { target_org: organizationId, event_action: action, event_entity_type: "corporate", event_entity_id: entityId || null, event_metadata: metadata });
}
async function idempotencyReplay(supabase: SupabaseClient, organizationId: string, route: string, key: string) {
  if (!key) return null;
  const { data, error } = await supabase.from("corporate_idempotency_keys").select("result").eq("organization_id", organizationId).eq("route", route).eq("key", key).maybeSingle();
  if (error) throw new Error(error.message);
  return data?.result ? { ...data.result, idempotent_replay: true } : null;
}
async function rememberIdempotency(supabase: SupabaseClient, organizationId: string, route: string, key: string, result: Json) {
  if (!key) return;
  const { error } = await supabase.from("corporate_idempotency_keys").insert({ organization_id: organizationId, route, key, result });
  if (error && !error.message.toLowerCase().includes("duplicate")) throw new Error(error.message);
}

async function copyPricingEvidence(supabase: SupabaseClient, organizationId: string, sourceIds: string[], copyPricing: boolean) {
  if (!copyPricing || !sourceIds.length) return { books: [] as Json[], items: [] as Json[] };
  const { data: books, error: bookError } = await supabase.from("price_books").select("*").eq("organization_id", organizationId).in("id", sourceIds);
  if (bookError) throw new Error(bookError.message);
  if ((books || []).length !== sourceIds.length) throw new Error("Every source price book must belong to the active organization");
  const { data: items, error: itemError } = await supabase.from("price_book_items").select("*").in("price_book_id", sourceIds);
  if (itemError) throw new Error(itemError.message);
  return { books: books || [], items: items || [] };
}

async function summary(supabase: SupabaseClient, organizationId: string, accountRow: Json) {
  const [snapshots, users, policies, masters, pending] = await Promise.all([
    supabase.from("corporate_account_snapshots").select("*").eq("organization_id", organizationId).eq("account_id", accountRow.id).order("version", { ascending: false }).limit(5),
    supabase.from("corporate_account_users").select("*").eq("organization_id", organizationId).eq("account_id", accountRow.id).order("created_at", { ascending: false }),
    supabase.from("corporate_policies").select("*").eq("organization_id", organizationId).eq("account_id", accountRow.id).order("version", { ascending: false }),
    supabase.from("corporate_masters").select("kind").eq("organization_id", organizationId).eq("status", "active"),
    supabase.from("corporate_duty_slip_approvals").select("id", { count: "exact", head: true }).eq("organization_id", organizationId).eq("account_id", accountRow.id).eq("status", "pending"),
  ]);
  const masterCounts: Json = {}; for (const row of (masters.data || []) as Json[]) masterCounts[row.kind] = (masterCounts[row.kind] || 0) + 1;
  const readiness = { account_connected: true, setup_snapshot: Boolean(accountRow.setup_snapshot_id), active: accountRow.status === "active", active_policy: (policies.data || []).some((row: Json) => row.status === "active"), people: (users.data || []).length > 0, versioned_masters: Object.keys(masterCounts).length > 0, passenger_duty_slip_policy: (policies.data || []).some((row: Json) => row.status === "active" && row.passenger_duty_slip_approval) };
  const completed = Object.values(readiness).filter(Boolean).length;
  return { ok: true, account: accountRow, setup_snapshots: snapshots.data || [], users: users.data || [], policies: policies.data || [], master_counts: masterCounts, pending_duty_slip_approvals: pending.count || 0, readiness: { ...readiness, completed, total: Object.keys(readiness).length, percent: Math.round(completed / Object.keys(readiness).length * 100) } };
}

async function evaluateBooking(supabase: SupabaseClient, organizationId: string, user: User, accountRow: Json, body: Json) {
  const policy = await activePolicy(supabase, organizationId, accountRow.id, text(body.policy_id));
  const accountMember = await member(supabase, organizationId, accountRow.id, user);
  const action = text(body.action, "book").toLowerCase();
  requirePermission(accountMember, ["cancel", "cancellation"].includes(action) ? "booking.cancel" : "booking.create");
  const reasons: Json[] = [];
  if (accountRow.status !== "active") reasons.push(reason("corporate_account_not_active", "The corporate account must be active before a booking can be evaluated.", "block"));
  if (!policy) reasons.push(reason("active_policy_missing", "No active booking policy is configured.", "block"));
  reasons.push(...scopeReasons(accountRow.visibility || {}, accountMember?.visibility || {}, policy?.visibility || {}, body));
  const current = now();
  const scheduled = body.scheduled_at ? new Date(String(body.scheduled_at)) : null;
  if (policy && scheduled && !Number.isNaN(scheduled.getTime())) {
    if (["book", "create", "request"].includes(action) && policy.booking_lead_time_minutes !== null && scheduled.getTime() - current.getTime() < Number(policy.booking_lead_time_minutes) * 60000) reasons.push(reason("booking_lead_time_sla", `Bookings must be made at least ${policy.booking_lead_time_minutes} minutes before pickup.`, "block"));
    if (["cancel", "cancellation"].includes(action) && policy.cancellation_cutoff_minutes !== null && scheduled.getTime() - current.getTime() < Number(policy.cancellation_cutoff_minutes) * 60000) reasons.push(reason("cancellation_cutoff", `Cancellation is inside the ${policy.cancellation_cutoff_minutes}-minute cutoff window.`, "block", { potential_charge: true }));
  }
  if (policy?.approval_required && ["book", "create", "request"].includes(action)) reasons.push(reason("approval_required", "The booking must pass the configured approval route.", "approval", { approval_route: policy.approval_route || [] }));
  const requestedSupplier = text(body.supplier_id);
  const allowedSuppliers = list(policy?.allowed_supplier_ids);
  if (requestedSupplier && allowedSuppliers.length && !allowedSuppliers.includes(requestedSupplier)) reasons.push(reason("supplier_not_allowed", "The requested supplier is outside the active policy allow-list.", "block"));
  let candidates: Json[] = [];
  if (!requestedSupplier && policy?.auto_allotment_enabled) {
    let query = supabase.from("suppliers").select("id,name,supplier_type,cities").eq("organization_id", organizationId).eq("status", "active").order("name", { ascending: true }).limit(100);
    if (allowedSuppliers.length) query = query.in("id", allowedSuppliers);
    const { data, error } = await query; if (error) throw new Error(error.message);
    candidates = (data || []).filter((row: Json) => !text(body.city) || !list(row.cities).length || list(row.cities).map((item) => item.toLowerCase()).includes(text(body.city).toLowerCase())).map((row: Json) => ({ id: row.id, name: row.name, supplier_type: row.supplier_type, match_reason: allowedSuppliers.length ? "allowlisted" : "active_supplier" }));
    if (!candidates.length) reasons.push(reason("no_supplier_candidate", "Automatic allotment is enabled but no eligible supplier is available.", "block"));
    else reasons.push(reason("auto_allotment_candidates", "Eligible suppliers were resolved deterministically; no supplier was assigned by this evaluation.", "info", { candidates: candidates.map((item) => item.id) }));
  }
  const blocking = reasons.some((item) => item.severity === "block"); const approval = reasons.some((item) => item.severity === "approval");
  const outcome = blocking ? "block" : approval ? "needs_approval" : "allow";
  const result = { ok: true, outcome, decision: outcome, allowed: outcome === "allow", policy_id: policy?.id || null, policy_version: policy?.version || null, reasons, supplier_candidates: candidates, deterministic: true, evaluated_at: iso(current) };
  await supabase.from("corporate_policy_evaluations").insert({ organization_id: organizationId, account_id: accountRow.id, policy_id: policy?.id || null, evaluation_type: "booking", outcome, request: body, reasons, result, evaluated_by: user.id });
  await audit(supabase, organizationId, user, "corporate.booking.evaluate", policy?.id || accountRow.id, { outcome });
  return result;
}

async function handle(request: Request) {
  const { supabase, user } = await auth(request);
  const envelope = await request.json() as Json;
  const path = text(envelope.path); const method = text(envelope.method, "GET").toUpperCase(); const body = object(envelope.body); const query = object(envelope.query);
  const organizationId = await organization(supabase, user, envelope.organization_id);
  const accountRow = await account(supabase, organizationId);
  if (path === "/api/corporate/account" || path === "/api/corporate/accounts") {
    if (method === "GET") { if (accountRow) requirePermission(await member(supabase, organizationId, accountRow.id, user), "account.read"); return accountRow ? summary(supabase, organizationId, accountRow) : { ok: true, account: null }; }
    if (method === "POST" || method === "PATCH") {
      if (accountRow) requirePermission(await member(supabase, organizationId, accountRow.id, user), "account.manage");
      const next = { organization_id: organizationId, name: text(body.name, accountRow?.name), connection_type: text(body.connection_type, accountRow?.connection_type || "manual"), external_account_id: text(body.external_account_id, accountRow?.external_account_id || ""), customer_id: body.customer_id || accountRow?.customer_id || null, status: accountRow?.status || "draft", copy_pricing: bool(body.copy_pricing, accountRow?.copy_pricing || false), visibility: scope(body.scope || accountRow?.visibility), pricing_scope: object(body.pricing_scope || accountRow?.pricing_scope), created_by: accountRow?.created_by || user.id };
      const { data, error } = await supabase.from("corporate_accounts").upsert(next, { onConflict: "organization_id" }).select().single(); if (error) throw new Error(error.message);
      await ensureAdminMember(supabase, organizationId, data.id, user);
      await audit(supabase, organizationId, user, "corporate.account.connect", data.id, { connection_type: data.connection_type }); return summary(supabase, organizationId, data);
    }
  }
  if (path === "/api/corporate/account/setup" && method === "POST") {
    const replay = await idempotencyReplay(supabase, organizationId, path, text(body.idempotency_key)); if (replay) return replay;
    if (accountRow) requirePermission(await member(supabase, organizationId, accountRow.id, user), "account.manage");
    const next = { organization_id: organizationId, name: text(body.name, accountRow?.name), connection_type: text(body.connection_type, accountRow?.connection_type || "manual"), external_account_id: text(body.external_account_id, accountRow?.external_account_id || ""), customer_id: body.customer_id || accountRow?.customer_id || null, status: accountRow?.status === "active" ? "active" : "setup", copy_pricing: bool(body.copy_pricing, accountRow?.copy_pricing || false), visibility: scope(body.scope || accountRow?.visibility), pricing_scope: object(body.pricing_scope || accountRow?.pricing_scope), created_by: accountRow?.created_by || user.id };
    const { data: saved, error: saveError } = await supabase.from("corporate_accounts").upsert(next, { onConflict: "organization_id" }).select().single(); if (saveError) throw new Error(saveError.message);
    await ensureAdminMember(supabase, organizationId, saved.id, user);
    const version = Number(saved.setup_version || 0) + 1;
    const sourcePriceBookIds = list(body.source_price_book_ids);
    const pricingEvidence = await copyPricingEvidence(supabase, organizationId, sourcePriceBookIds, Boolean(saved.copy_pricing));
    const copiedIds = pricingEvidence.books.map((row) => row.id);
    const snapshot = { account_id: saved.id, version, connection_type: saved.connection_type, external_account_id: saved.external_account_id, customer_id: saved.customer_id, scope: saved.visibility, pricing_scope: saved.pricing_scope, copy_pricing: saved.copy_pricing, source_price_book_ids: copiedIds, copied_price_books: pricingEvidence.books.map((row) => ({ id: row.id, name: row.name, version: row.version })), copied_price_book_items: pricingEvidence.items.length, captured_at: iso(now()) };
    const { data: snap, error: snapError } = await supabase.from("corporate_account_snapshots").insert({ organization_id: organizationId, account_id: saved.id, version, snapshot, copied_price_book_ids: copiedIds, copied_at: pricingEvidence.books.length ? iso(now()) : null, created_by: user.id }).select().single(); if (snapError) throw new Error(snapError.message);
    if (pricingEvidence.books.length) {
      const copiedBooks = pricingEvidence.books.map((row) => ({ organization_id: organizationId, account_id: saved.id, snapshot_id: snap.id, source_price_book_id: row.id, name: row.name, effective_from: row.effective_from, effective_to: row.effective_to, source_status: row.status, source_version: row.version }));
      const { data: savedBooks, error: copiedBookError } = await supabase.from("corporate_snapshot_price_books").insert(copiedBooks).select(); if (copiedBookError) throw new Error(copiedBookError.message);
      const sourceToCopy = new Map((savedBooks || []).map((row: Json) => [String(row.source_price_book_id), row.id]));
      const copiedItems = pricingEvidence.items.map((row) => ({ organization_id: organizationId, account_id: saved.id, snapshot_price_book_id: sourceToCopy.get(String(row.price_book_id)), source_price_book_item_id: row.id, duty_type: row.duty_type, vehicle_group: row.vehicle_group, base_paise: row.base_paise, per_km_paise: row.per_km_paise, per_hour_paise: row.per_hour_paise, waiting_paise: row.waiting_paise, tax_rate: row.tax_rate, rules: row.rules || {} })).filter((row) => row.snapshot_price_book_id);
      if (copiedItems.length) { const { error: copiedItemError } = await supabase.from("corporate_snapshot_price_book_items").insert(copiedItems); if (copiedItemError) throw new Error(copiedItemError.message); }
    }
    const { data: updated, error: updateError } = await supabase.from("corporate_accounts").update({ setup_snapshot_id: snap.id, setup_version: version }).eq("id", saved.id).eq("organization_id", organizationId).select().single(); if (updateError) throw new Error(updateError.message);
    await audit(supabase, organizationId, user, "corporate.account.setup", saved.id, { version, copied_price_book_count: copiedIds.length, copied_price_book_item_count: pricingEvidence.items.length }); const result = await summary(supabase, organizationId, updated); await rememberIdempotency(supabase, organizationId, path, text(body.idempotency_key), result); return result;
  }
  if (path === "/api/corporate/account/activation-guard" && method === "GET") {
    if (!accountRow) return { ok: true, guard: { eligible: false, reasons: [reason("account_missing", "Connect a corporate account first.", "block")] } };
    requirePermission(await member(supabase, organizationId, accountRow.id, user), "account.read");
    const reasons: Json[] = []; if (!accountRow.name) reasons.push(reason("account_name_missing", "A corporate account name is required.", "block")); if (!accountRow.setup_snapshot_id) reasons.push(reason("setup_snapshot_missing", "Complete the setup snapshot before activation.", "block"));
    return { ok: true, guard: { eligible: reasons.length === 0, reasons } };
  }
  if (path === "/api/corporate/account/activate" && method === "POST") {
    const replay = await idempotencyReplay(supabase, organizationId, path, text(body.idempotency_key)); if (replay) return replay;
    if (!accountRow) throw new Error("Connect a corporate account first");
    requirePermission(await member(supabase, organizationId, accountRow.id, user), "account.manage");
    const reasons: Json[] = []; if (!accountRow.name) reasons.push(reason("account_name_missing", "A corporate account name is required.", "block")); if (!accountRow.setup_snapshot_id) reasons.push(reason("setup_snapshot_missing", "Complete the setup snapshot before activation.", "block"));
    if (reasons.length) return { ok: false, code: "activation_blocked", reasons };
    const { data, error } = await supabase.from("corporate_accounts").update({ status: "active", activated_at: iso(now()) }).eq("id", accountRow.id).eq("organization_id", organizationId).select().single(); if (error) throw new Error(error.message);
    await audit(supabase, organizationId, user, "corporate.account.activate", data.id, {}); const result = await summary(supabase, organizationId, data); await rememberIdempotency(supabase, organizationId, path, text(body.idempotency_key), result); return result;
  }
  if (!accountRow) throw new Error("Connect a corporate account before using this workflow");
  if (path === "/api/corporate/users" && method === "GET") { requirePermission(await member(supabase, organizationId, accountRow.id, user), "people.read"); const { data, error } = await supabase.from("corporate_account_users").select("*").eq("organization_id", organizationId).eq("account_id", accountRow.id).order("created_at", { ascending: false }); if (error) throw new Error(error.message); return { ok: true, items: data || [], count: (data || []).length }; }
  if (path === "/api/corporate/users" && method === "POST") { requirePermission(await member(supabase, organizationId, accountRow.id, user), "people.manage"); const row = { organization_id: organizationId, account_id: accountRow.id, user_id: body.user_id || null, employee_id: body.employee_id || null, email: text(body.email).toLowerCase(), full_name: text(body.full_name), account_type: text(body.account_type, "booker_passenger"), permission_profile: text(body.permission_profile, text(body.account_type, "booker_passenger")), grants: list(body.grants), denies: list(body.denies), visibility: scope(body.visibility), status: text(body.status, "invited"), invited_by: user.id, activated_at: text(body.status, "invited") === "active" ? iso(now()) : null }; const { data, error } = await supabase.from("corporate_account_users").insert(row).select().single(); if (error) throw new Error(error.message); await audit(supabase, organizationId, user, "corporate.user.invite", data.id, { account_type: data.account_type }); return { ok: true, item: data }; }
  const corporateUserMatch = path.match(/^\/api\/corporate\/users\/([^/]+)(?:\/(activate|deactivate))?$/);
  if (corporateUserMatch) {
    const accountMember = await member(supabase, organizationId, accountRow.id, user);
    const targetId = corporateUserMatch[1]; const userAction = corporateUserMatch[2] || "";
    if (userAction) {
      requirePermission(accountMember, "people.manage");
      const nextStatus = userAction === "activate" ? "active" : "suspended";
      const { data, error } = await supabase.from("corporate_account_users").update({ status: nextStatus, activated_at: nextStatus === "active" ? iso(now()) : null }).eq("id", targetId).eq("organization_id", organizationId).eq("account_id", accountRow.id).select().single(); if (error) throw new Error(error.message);
      await audit(supabase, organizationId, user, `corporate.user.${userAction}`, targetId, { status: nextStatus }); return { ok: true, item: data };
    }
    if (method === "GET") { requirePermission(accountMember, "people.read"); const { data, error } = await supabase.from("corporate_account_users").select("*").eq("id", targetId).eq("organization_id", organizationId).eq("account_id", accountRow.id).maybeSingle(); if (error) throw new Error(error.message); if (!data) throw new Error("Corporate account user not found"); return { ok: true, item: data }; }
    if (method === "PATCH") { requirePermission(accountMember, "people.manage"); const changes: Json = {}; if (body.account_type !== undefined) changes.account_type = text(body.account_type, "booker_passenger"); if (body.permission_profile !== undefined) changes.permission_profile = text(body.permission_profile, changes.account_type || "booker_passenger"); if (body.grants !== undefined) changes.grants = list(body.grants); if (body.denies !== undefined) changes.denies = list(body.denies); if (body.visibility !== undefined) changes.visibility = scope(body.visibility); if (body.status !== undefined) changes.status = text(body.status); if (!Object.keys(changes).length) throw new Error("No supported account-user fields supplied"); changes.updated_at = iso(now()); const { data, error } = await supabase.from("corporate_account_users").update(changes).eq("id", targetId).eq("organization_id", organizationId).eq("account_id", accountRow.id).select().single(); if (error) throw new Error(error.message); await audit(supabase, organizationId, user, "corporate.user.update", targetId, { fields: Object.keys(changes) }); return { ok: true, item: data }; }
  }
  if (path === "/api/corporate/policies" && method === "GET") { requirePermission(await member(supabase, organizationId, accountRow.id, user), "policy.read"); const { data, error } = await supabase.from("corporate_policies").select("*").eq("organization_id", organizationId).eq("account_id", accountRow.id).order("version", { ascending: false }); if (error) throw new Error(error.message); return { ok: true, items: data || [], count: (data || []).length }; }
  if (path === "/api/corporate/policies" && method === "POST") { requirePermission(await member(supabase, organizationId, accountRow.id, user), "policy.manage"); const row = { organization_id: organizationId, account_id: accountRow.id, name: text(body.name), status: text(body.status, "draft"), version: integer(body.version, 1), booking_lead_time_minutes: integer(body.booking_lead_time_minutes), cancellation_cutoff_minutes: integer(body.cancellation_cutoff_minutes), approval_required: bool(body.approval_required), approval_route: Array.isArray(body.approval_route) ? body.approval_route : [], supplier_mode: text(body.supplier_mode, "any"), allowed_supplier_ids: list(body.allowed_supplier_ids), auto_allotment_enabled: bool(body.auto_allotment_enabled), allotment_rule_id: body.allotment_rule_id || null, passenger_duty_slip_approval: bool(body.passenger_duty_slip_approval), duty_slip_auto_approval_hours: integer(body.duty_slip_auto_approval_hours, 48), visibility: scope(body.visibility), rules: object(body.rules), created_by: user.id }; const { data, error } = await supabase.from("corporate_policies").insert(row).select().single(); if (error) throw new Error(error.message); await audit(supabase, organizationId, user, "corporate.policy.create", data.id, { version: data.version }); return { ok: true, item: data }; }
  const corporatePolicyMatch = path.match(/^\/api\/corporate\/policies\/([^/]+)$/);
  if (corporatePolicyMatch) {
    const accountMember = await member(supabase, organizationId, accountRow.id, user); const policyId = corporatePolicyMatch[1];
    if (method === "GET") { requirePermission(accountMember, "policy.read"); const { data, error } = await supabase.from("corporate_policies").select("*").eq("id", policyId).eq("organization_id", organizationId).eq("account_id", accountRow.id).maybeSingle(); if (error) throw new Error(error.message); if (!data) throw new Error("Corporate policy not found"); return { ok: true, item: data }; }
    if (method === "PATCH") { requirePermission(accountMember, "policy.manage"); const { data: existing, error: existingError } = await supabase.from("corporate_policies").select("*").eq("id", policyId).eq("organization_id", organizationId).eq("account_id", accountRow.id).maybeSingle(); if (existingError) throw new Error(existingError.message); if (!existing) throw new Error("Corporate policy not found"); const nextVersion = Number(existing.version || 1) + (bool(body.new_version) ? 1 : 0); const row: Json = { organization_id: organizationId, account_id: accountRow.id, name: text(body.name, existing.name), status: text(body.status, existing.status), version: nextVersion, booking_lead_time_minutes: body.booking_lead_time_minutes === undefined ? existing.booking_lead_time_minutes : integer(body.booking_lead_time_minutes), cancellation_cutoff_minutes: body.cancellation_cutoff_minutes === undefined ? existing.cancellation_cutoff_minutes : integer(body.cancellation_cutoff_minutes), approval_required: body.approval_required === undefined ? existing.approval_required : bool(body.approval_required), approval_route: body.approval_route === undefined ? existing.approval_route : (Array.isArray(body.approval_route) ? body.approval_route : []), supplier_mode: text(body.supplier_mode, existing.supplier_mode), allowed_supplier_ids: body.allowed_supplier_ids === undefined ? existing.allowed_supplier_ids : list(body.allowed_supplier_ids), auto_allotment_enabled: body.auto_allotment_enabled === undefined ? existing.auto_allotment_enabled : bool(body.auto_allotment_enabled), allotment_rule_id: body.allotment_rule_id === undefined ? existing.allotment_rule_id : body.allotment_rule_id || null, passenger_duty_slip_approval: body.passenger_duty_slip_approval === undefined ? existing.passenger_duty_slip_approval : bool(body.passenger_duty_slip_approval), duty_slip_auto_approval_hours: body.duty_slip_auto_approval_hours === undefined ? existing.duty_slip_auto_approval_hours : integer(body.duty_slip_auto_approval_hours, 48), visibility: body.visibility === undefined ? existing.visibility : scope(body.visibility), rules: body.rules === undefined ? existing.rules : object(body.rules), updated_at: iso(now()) }; if (bool(body.new_version)) { delete row.updated_at; row.created_by = user.id; const { data, error } = await supabase.from("corporate_policies").insert(row).select().single(); if (error) throw new Error(error.message); await audit(supabase, organizationId, user, "corporate.policy.version", data.id, { from_policy_id: policyId, version: data.version }); return { ok: true, item: data }; } const { data, error } = await supabase.from("corporate_policies").update(row).eq("id", policyId).eq("organization_id", organizationId).eq("account_id", accountRow.id).select().single(); if (error) throw new Error(error.message); await audit(supabase, organizationId, user, "corporate.policy.update", policyId, { fields: Object.keys(body) }); return { ok: true, item: data }; }
  }
  if (path === "/api/corporate/policies/evaluate" && method === "POST") return evaluateBooking(supabase, organizationId, user, accountRow, body);
  if ((path === "/api/corporate/visibility/evaluate" || path === "/api/corporate/permissions/evaluate") && (method === "POST" || method === "GET")) { const accountMember = await member(supabase, organizationId, accountRow.id, user); requirePermission(accountMember, "account.read"); const reasons = scopeReasons(accountRow.visibility || {}, accountMember?.visibility || {}, scope(body.policy_scope), body.resource || body); const permission = text(body.permission); if (permission && !can(user, accountMember, permission)) reasons.push(reason("permission_denied", `The account user does not have ${permission}.`, "block", { permission })); return { ok: true, outcome: reasons.length ? "block" : "allow", allowed: !reasons.length, reasons }; }
  if (path === "/api/corporate/masters" && method === "GET") { requirePermission(await member(supabase, organizationId, accountRow.id, user), "masters.read"); const kind = queryValue(query, "kind"); let request = supabase.from("corporate_masters").select("*").eq("organization_id", organizationId).eq("status", "active").order("kind", { ascending: true }).order("code", { ascending: true }).order("version", { ascending: false }); if (kind) request = request.eq("kind", kind); const { data, error } = await request; if (error) throw new Error(error.message); const seen = new Set<string>(); const latest = (data || []).filter((row: Json) => { const key = `${row.kind}:${row.code}`; if (seen.has(key)) return false; seen.add(key); return true; }); return { ok: true, items: latest, count: latest.length }; }
  if (path === "/api/corporate/masters" && method === "POST") { requirePermission(await member(supabase, organizationId, accountRow.id, user), "masters.manage"); const kind = text(body.kind); if (!masterKinds.has(kind)) throw new Error("Unsupported master kind"); const code = text(body.code).toUpperCase(); const { data: previous } = await supabase.from("corporate_masters").select("version").eq("organization_id", organizationId).eq("kind", kind).eq("code", code).order("version", { ascending: false }).limit(1).maybeSingle(); const row = { organization_id: organizationId, kind, code, name: text(body.name), version: Number(previous?.version || 0) + 1, status: "active", effective_from: body.effective_from || null, effective_to: body.effective_to || null, scope: scope(body.scope), config: object(body.config), created_by: user.id }; const { data, error } = await supabase.from("corporate_masters").insert(row).select().single(); if (error) throw new Error(error.message); await audit(supabase, organizationId, user, "corporate.master.version", data.id, { kind, code, version: data.version }); return { ok: true, item: data }; }
  const corporateMasterMatch = path.match(/^\/api\/corporate\/masters\/([^/]+)$/);
  if (corporateMasterMatch) {
    const accountMember = await member(supabase, organizationId, accountRow.id, user); const masterId = corporateMasterMatch[1];
    const { data: master, error: masterError } = await supabase.from("corporate_masters").select("*").eq("id", masterId).eq("organization_id", organizationId).maybeSingle(); if (masterError) throw new Error(masterError.message); if (!master) throw new Error("Corporate master record not found");
    if (method === "GET") { requirePermission(accountMember, "masters.read"); const { data: versions, error } = await supabase.from("corporate_masters").select("*").eq("organization_id", organizationId).eq("kind", master.kind).eq("code", master.code).order("version", { ascending: false }); if (error) throw new Error(error.message); return { ok: true, item: master, versions: versions || [] }; }
    if (method === "PATCH") { requirePermission(accountMember, "masters.manage"); if (body.status !== "archived") throw new Error("Only archiving an existing master is supported"); const { data, error } = await supabase.from("corporate_masters").update({ status: "archived" }).eq("id", masterId).eq("organization_id", organizationId).select().single(); if (error) throw new Error(error.message); await audit(supabase, organizationId, user, "corporate.master.archive", masterId, {}); return { ok: true, item: data }; }
  }
  if (path === "/api/corporate/duty-slip-approvals" && method === "GET") { requirePermission(await member(supabase, organizationId, accountRow.id, user), "duty_slip.approve"); const { data, error } = await supabase.from("corporate_duty_slip_approvals").select("*").eq("organization_id", organizationId).eq("account_id", accountRow.id).order("created_at", { ascending: false }).limit(200); if (error) throw new Error(error.message); return { ok: true, items: data || [], count: (data || []).length }; }
  if (path === "/api/corporate/duty-slip-approvals" && method === "POST") { requirePermission(await member(supabase, organizationId, accountRow.id, user), "duty_slip.approve"); const policy = await activePolicy(supabase, organizationId, accountRow.id); if (!policy?.passenger_duty_slip_approval) throw new Error("Passenger duty-slip approval is not enabled by the active policy"); const rawToken = token(); const created = now(); const auto = new Date(created.getTime() + Number(policy.duty_slip_auto_approval_hours || 48) * 3600000); const expiry = new Date(created.getTime() + 7 * 86400000); const row = { organization_id: organizationId, account_id: accountRow.id, booking_id: body.booking_id || null, duty_id: body.duty_id || null, passenger_email: text(body.passenger_email).toLowerCase(), passenger_name: text(body.passenger_name), status: "pending", action_token_hash: await sha256(rawToken), token_expires_at: iso(expiry), auto_approve_at: iso(auto), created_by: user.id }; const { data, error } = await supabase.from("corporate_duty_slip_approvals").insert(row).select().single(); if (error) throw new Error(error.message); await audit(supabase, organizationId, user, "corporate.duty_slip.request", data.id, { auto_approve_at: data.auto_approve_at }); const publicBase = String(Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
    return { ok: true, item: { ...data, action_token_hash: undefined, action_token: rawToken }, signed_link: `${publicBase}/functions/v1/corporate-duty-slip-action?approval_id=${data.id}&token=${rawToken}` }; }
  if (path === "/api/corporate/duty-slip-approvals/auto-approve" && method === "POST") { requirePermission(await member(supabase, organizationId, accountRow.id, user), "duty_slip.approve"); const { data, error } = await supabase.rpc("corporate_auto_approve_duty_slips", { target_org: organizationId }); if (error) throw new Error(error.message); return { ok: true, processed: (data || []).length, approval_ids: (data || []).map((row: Json) => row.approval_id), reason: "48_hour_expiry_auto_approval" }; }
  const approvalMatch = path.match(/^\/api\/corporate\/duty-slip-approvals\/([^/]+)\/(approve|reject)$/);
  if (approvalMatch && method === "POST") { requirePermission(await member(supabase, organizationId, accountRow.id, user), approvalMatch[2] === "approve" ? "duty_slip.approve" : "duty_slip.reject"); const next = approvalMatch[2] === "approve" ? "approved" : "rejected"; const { data, error } = await supabase.from("corporate_duty_slip_approvals").update({ status: next, decision_comment: text(body.comment), decision_reason: "passenger_action", decided_by: user.id, decided_at: iso(now()) }).eq("id", approvalMatch[1]).eq("organization_id", organizationId).eq("account_id", accountRow.id).eq("status", "pending").select().single(); if (error) throw new Error(error.message); await audit(supabase, organizationId, user, `corporate.duty_slip.${next}`, approvalMatch[1], {}); return { ok: true, item: data }; }
  if (path === "/api/corporate/allotment/rules" && method === "GET") { requirePermission(await member(supabase, organizationId, accountRow.id, user), "allotment.evaluate"); const { data, error } = await supabase.from("corporate_allotment_rules").select("*").eq("organization_id", organizationId).eq("account_id", accountRow.id).order("priority", { ascending: true }).order("version", { ascending: false }); if (error) throw new Error(error.message); return { ok: true, items: data || [], count: (data || []).length }; }
  if (path === "/api/corporate/allotment/rules" && method === "POST") { requirePermission(await member(supabase, organizationId, accountRow.id, user), "allotment.manage"); const name = text(body.name); if (!name) throw new Error("name is required"); const status = text(body.status, "draft"); if (!["draft", "active", "archived"].includes(status)) throw new Error("Unsupported allotment rule status"); const supplierIds = list(body.supplier_ids); if (supplierIds.length) { const { data: suppliers, error: supplierError } = await supabase.from("suppliers").select("id").eq("organization_id", organizationId).in("id", supplierIds); if (supplierError) throw new Error(supplierError.message); if ((suppliers || []).length !== supplierIds.length) throw new Error("All suppliers must belong to the active organization"); } const fallback = text(body.fallback_supplier_id) || null; if (fallback) { const { data: supplier, error: supplierError } = await supabase.from("suppliers").select("id").eq("organization_id", organizationId).eq("id", fallback).maybeSingle(); if (supplierError) throw new Error(supplierError.message); if (!supplier) throw new Error("Fallback supplier is outside the active organization"); } const row = { organization_id: organizationId, account_id: accountRow.id, name, version: Math.max(1, integer(body.version, 1) || 1), status, priority: Math.max(0, integer(body.priority, 100) || 100), supplier_ids: supplierIds, vehicle_group_codes: list(body.vehicle_group_codes), duty_type_codes: list(body.duty_type_codes), cities: list(body.cities), required_document_types: list(body.required_document_types), auto_allot: bool(body.auto_allot), fallback_supplier_id: fallback, max_attempts: Math.min(20, Math.max(1, integer(body.max_attempts, 1) || 1)), rules: object(body.rules), created_by: user.id }; const { data, error } = await supabase.from("corporate_allotment_rules").insert(row).select().single(); if (error) throw new Error(error.message); await audit(supabase, organizationId, user, "corporate.allotment_rule.create", data.id, { version: data.version }); return { ok: true, item: data }; }
  if (path === "/api/corporate/allotment/evaluate" && method === "POST") { requirePermission(await member(supabase, organizationId, accountRow.id, user), "allotment.evaluate"); const policy = await activePolicy(supabase, organizationId, accountRow.id, text(body.policy_id)); const reasons: Json[] = accountRow.status !== "active" ? [reason("corporate_account_not_active", "The corporate account is not active.", "block")] : []; const accountMember = await member(supabase, organizationId, accountRow.id, user); reasons.push(...scopeReasons(accountRow.visibility || {}, accountMember?.visibility || {}, policy?.visibility || {}, body)); const requiredDocs = list(body.required_document_types); if (requiredDocs.length && !body.vehicle_id) reasons.push(reason("vehicle_required_for_document_guard", "A vehicle is required to verify document validity.", "block")); if (requiredDocs.length && body.vehicle_id) { const { data: docs } = await supabase.from("documents").select("document_type,status,expires_at").eq("organization_id", organizationId).eq("entity_type", "vehicle").eq("entity_id", body.vehicle_id).in("document_type", requiredDocs); for (const type of requiredDocs) { const doc = (docs || []).find((row: Json) => row.document_type === type); if (!doc) reasons.push(reason("document_missing", `Required vehicle document ${type} is missing.`, "block")); else if (!["approved", "valid", "active"].includes(doc.status) || (doc.expires_at && new Date(doc.expires_at) <= now())) reasons.push(reason("document_not_valid", `Vehicle document ${type} is not valid.`, "block")); } } const { data: candidates, error } = await supabase.from("suppliers").select("id,name,supplier_type,cities").eq("organization_id", organizationId).eq("status", "active").order("name", { ascending: true }).limit(100); if (error) throw new Error(error.message); if (!(candidates || []).length) reasons.push(reason("no_eligible_supplier", "No active supplier satisfies the deterministic allotment filters.", "block")); const outcome = reasons.some((item) => item.severity === "block") ? "block" : "allow"; return { ok: true, outcome, eligible: outcome === "allow", candidates: candidates || [], reasons, deterministic: true, evaluated_at: iso(now()) }; }
  throw new Error(`Unsupported corporate route: ${method} ${path}`);
}

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") return new Response("ok", { status: 200, headers: cors });
  try { return reply(await handle(request)); } catch (error) { return reply({ ok: false, message: message(error), code: "corporate_request_failed" }, 400); }
});
