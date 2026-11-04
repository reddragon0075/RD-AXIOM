import { createClient, type SupabaseClient, type User } from "https://esm.sh/@supabase/supabase-js@2";

/*
 * Authenticated Phase 3 production boundary.
 *
 * This function deliberately runs with the caller's JWT and the anon key. RLS
 * stays active for every read and write. Derived tables are additive: canonical
 * Fleet duties, GPS, invoices and invite-only Network service orders are read,
 * never replaced. Provider work is deterministic/mock-first until a reviewed
 * provider adapter is configured.
 */
const allowedOrigin = (Deno.env.get("AXIOM_ALLOWED_ORIGIN") || Deno.env.get("AXIOM_ALLOWED_ORIGINS")?.split(",")[0] || "").trim();
const cors = {
  ...(allowedOrigin ? { "Access-Control-Allow-Origin": allowedOrigin, "Vary": "Origin" } : {}),
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
type Json = Record<string, any>;
type Envelope = { path: string; method?: string; organization_id?: string | null; query?: Json; body?: Json };
const REGION_CATALOG = [
  { country_code: "IN", region_code: "IN-MH", name: "India · Maharashtra", currency: "INR", timezone: "Asia/Kolkata", locale: "en-IN", tax_regime: "GST", distance_unit: "km" },
  { country_code: "IN", region_code: "IN-KA", name: "India · Karnataka", currency: "INR", timezone: "Asia/Kolkata", locale: "en-IN", tax_regime: "GST", distance_unit: "km" },
  { country_code: "AE", region_code: "AE-DU", name: "United Arab Emirates · Dubai", currency: "AED", timezone: "Asia/Dubai", locale: "en-AE", tax_regime: "VAT", distance_unit: "km" },
  { country_code: "SG", region_code: "SG-SG", name: "Singapore", currency: "SGD", timezone: "Asia/Singapore", locale: "en-SG", tax_regime: "GST", distance_unit: "km" },
  { country_code: "GB", region_code: "GB-LND", name: "United Kingdom · London", currency: "GBP", timezone: "Europe/London", locale: "en-GB", tax_regime: "VAT", distance_unit: "mi" },
];
const FX: Record<string, number> = { "INR:AED": 0.0435, "INR:SGD": 0.016, "INR:GBP": 0.00935, "AED:INR": 22.9885, "SGD:INR": 62.5, "GBP:INR": 106.9519 };
const FACTORS: Record<string, number> = { petrol: 0.192, diesel: 0.171, cng: 0.13, hybrid: 0.1, ev: 0.05, electric: 0.05 };

function reply(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { ...cors, "Content-Type": "application/json" } }); }
function errorText(error: unknown) { return error instanceof Error ? error.message : String(error || "Phase 3 request failed"); }
function required(value: unknown, name: string) { const result = String(value || "").trim(); if (!result) throw new Error(`${name} is required`); return result; }
function asObject(value: unknown): Json { return value && typeof value === "object" && !Array.isArray(value) ? value as Json : {}; }
function number(value: unknown, fallback = 0) { const result = Number(value); return Number.isFinite(result) ? result : fallback; }
function int(value: unknown, fallback = 0) { return Math.round(number(value, fallback)); }
function now() { return new Date().toISOString(); }
function collection(items: Json[], extra: Json = {}) { return { ok: true, items, count: items.length, ...extra }; }

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
async function organization(supabase: SupabaseClient, user: User, requested: unknown) {
  const requestedId = String(requested || "").trim();
  let query = supabase.from("organization_memberships").select("organization_id").eq("user_id", user.id).eq("status", "active").limit(20);
  if (requestedId) query = query.eq("organization_id", requestedId);
  const { data, error } = await query;
  if (error) throw new Error(error.message);
  if (requestedId && (data || []).some((row) => row.organization_id === requestedId)) return requestedId;
  if (!requestedId && (data || []).length === 1) return String(data![0].organization_id);
  if (requestedId) {
    const { data: owned } = await supabase.from("organizations").select("id").eq("id", requestedId).eq("owner_user_id", user.id).maybeSingle();
    if (owned?.id) return String(owned.id);
  }
  throw new Error("Organization access denied");
}
async function rows(supabase: SupabaseClient, table: string, organizationId: string, query: Json = {}, order = "created_at.desc", limit = 100) {
  let request = supabase.from(table).select("*").eq("organization_id", organizationId).order(order.split(".")[0], { ascending: order.endsWith(".asc") }).limit(Math.min(Math.max(limit, 1), 500));
  const status = String(query.status || "");
  if (status && status !== "all") request = request.eq("status", status);
  const { data, error } = await request;
  if (error) throw new Error(error.message);
  return (data || []) as Json[];
}
function isEffectiveRegion(item: Json) {
  const day = now().slice(0, 10);
  return (!item.effective_from || String(item.effective_from) <= day) && (!item.effective_to || String(item.effective_to) >= day);
}
async function effectiveRegions(supabase: SupabaseClient, organizationId: string, limit = 100) {
  const list = await rows(supabase, "phase3_regions", organizationId, {}, "is_default.desc", limit);
  const current = list.filter(isEffectiveRegion);
  return current.length ? current : list;
}
async function select(supabase: SupabaseClient, path: string) {
  const [table, rawQuery] = path.split("?");
  let request = supabase.from(table).select("*");
  for (const [key, rawValue] of new URLSearchParams(rawQuery || "").entries()) {
    const value = decodeURIComponent(rawValue);
    if (value.startsWith("eq.")) request = request.eq(key, value.slice(3));
    else if (value.startsWith("in.(") && value.endsWith(")")) request = request.in(key, value.slice(4, -1).split(","));
    else if (value.startsWith("not.")) request = request.not(key, "eq", value.slice(4));
  }
  const { data, error } = await request;
  if (error) throw new Error(error.message);
  return (data || []) as Json[];
}
async function insert(supabase: SupabaseClient, table: string, value: Json, conflict = "") {
  const suffix = conflict ? `?on_conflict=${encodeURIComponent(conflict)}` : "";
  const { data, error } = await supabase.from(table).upsert(value, { onConflict: conflict || undefined, ignoreDuplicates: false }).select().single();
  if (error) throw new Error(error.message);
  return data as Json;
}
async function patch(supabase: SupabaseClient, table: string, id: string, organizationId: string, value: Json) {
  const { data, error } = await supabase.from(table).update(value).eq("id", id).eq("organization_id", organizationId).select().single();
  if (error) throw new Error(error.message);
  return data as Json;
}
function simulation(body: Json, region: Json) {
  const demand = Math.max(0, int(body.demand_duties ?? body.trips));
  const distance = Math.max(0, number(body.avg_distance_km, 15));
  const duration = Math.max(0, number(body.avg_duration_minutes, 45));
  const base = Math.max(0, int(body.base_rate_minor, 1800));
  const fuel = Math.max(0, int(body.fuel_cost_per_km_minor, 18));
  const driver = Math.max(0, int(body.driver_cost_per_hour_minor, 320));
  const waiting = Math.max(0, number(body.waiting_minutes, 8));
  const waitRate = Math.max(0, int(body.waiting_cost_per_minute_minor, 6));
  const vendorMix = Array.isArray(body.vendor_mix) ? body.vendor_mix : [];
  const mixTotal = vendorMix.reduce((sum, item) => sum + Math.max(0, number(item?.share)), 0);
  const vendorRate = mixTotal > 0 ? vendorMix.reduce((sum, item) => sum + Math.max(0, number(item?.share)) * Math.max(0, int(item?.cost_per_duty_minor, 1800)), 0) / mixTotal : base;
  const penalty = Math.max(0, number(body.service_penalty_pct, 2.5));
  const capacityPerDuty = Math.max(1, number(body.capacity_per_duty, 4));
  const capacityRequired = Math.max(1, number(body.capacity_required, 1));
  const capacityGap = Math.max(0, capacityRequired - capacityPerDuty);
  const effectivePenalty = penalty + capacityGap * 4;
  const factor = Math.max(0, number(body.emissions_factor_kg_per_km, 0.192));
  const carbon = Math.max(0, int(body.carbon_price_per_kg_minor));
  const baseline = Math.round((base + fuel * distance + driver * duration / 60 + waitRate * waiting) * demand);
  const modeled = Math.round((vendorRate + fuel * distance + driver * duration / 60 + waitRate * waiting + carbon * factor * distance) * demand * (1 + effectivePenalty / 100));
  return { currency: region.currency, unit: "minor", demand_duties: demand, distance_km: Math.round(distance * demand * 100) / 100, baseline_total_minor: baseline, modeled_total_minor: modeled, delta_minor: modeled - baseline, per_duty_minor: demand ? Math.round(modeled / demand) : 0, service_level_pct: Math.round(Math.max(0, 100 - effectivePenalty) * 100) / 100, emissions_kg: Math.round(factor * distance * demand * 1000) / 1000, assumptions: { avg_distance_km: distance, avg_duration_minutes: duration, base_rate_minor: base, vendor_rate_minor: Math.round(vendorRate), vendor_mix: vendorMix, fuel_cost_per_km_minor: fuel, driver_cost_per_hour_minor: driver, waiting_minutes: waiting, service_penalty_pct: penalty, capacity_per_duty: capacityPerDuty, capacity_required: capacityRequired, capacity_gap: capacityGap, effective_service_penalty_pct: effectivePenalty, emissions_factor_kg_per_km: factor, carbon_price_per_kg_minor: carbon }, sensitivity: { low_demand_total_minor: Math.round(modeled * 0.9), high_demand_total_minor: Math.round(modeled * 1.1) } };
}

async function regions(supabase: SupabaseClient, organizationId: string, method: string, path: string, body: Json) {
  if (path === "/api/phase3/regions" && method === "GET") return collection(await rows(supabase, "phase3_regions", organizationId, {}, "is_default.desc", 100), { catalog: REGION_CATALOG });
  if (path === "/api/phase3/regions" && method === "POST") {
    const code = required(body.region_code, "region_code").toUpperCase();
    const profile = REGION_CATALOG.find((item) => item.region_code === code);
    if (!profile) throw new Error("Select a region from the controlled catalog");
    if (body.is_default) await supabase.from("phase3_regions").update({ is_default: false }).eq("organization_id", organizationId);
    const item = await insert(supabase, "phase3_regions", { organization_id: organizationId, catalog_region_code: code, country_code: profile.country_code, name: body.name || profile.name, currency: body.currency || profile.currency, timezone: body.timezone || profile.timezone, locale: body.locale || profile.locale, tax_regime: body.tax_regime || profile.tax_regime, distance_unit: body.distance_unit || profile.distance_unit, effective_from: body.effective_from || null, effective_to: body.effective_to || null, is_default: body.is_default === true, status: "active", metadata: asObject(body.metadata) }, "organization_id,catalog_region_code");
    return { ok: true, item: { ...item, region_code: item.catalog_region_code } };
  }
  const match = path.match(/^\/api\/phase3\/regions\/([^/]+)$/);
  if (match && method === "PATCH") {
    if (body.is_default) await supabase.from("phase3_regions").update({ is_default: false }).eq("organization_id", organizationId);
    const regionPatch = Object.fromEntries(["name", "currency", "timezone", "locale", "tax_regime", "distance_unit", "effective_from", "effective_to", "status"].filter((key) => body[key] !== undefined).map((key) => [key, body[key]]));
    if (body.is_default !== undefined) regionPatch.is_default = body.is_default === true;
    return { ok: true, item: await patch(supabase, "phase3_regions", match[1], organizationId, { ...regionPatch, updated_at: now() }) };
  }
  if (path === "/api/phase3/localization") {
    const list = await effectiveRegions(supabase, organizationId, 100);
    if (method === "GET") return { ok: true, item: list[0] || REGION_CATALOG[0], supported_countries: [...new Set(REGION_CATALOG.map((item) => item.country_code))] };
    const item = required(body.region_id, "region_id");
    await supabase.from("phase3_regions").update({ is_default: false }).eq("organization_id", organizationId);
    return { ok: true, item: await patch(supabase, "phase3_regions", item, organizationId, { is_default: true, updated_at: now() }) };
  }
  if (path === "/api/phase3/fx/rates" && method === "GET") return { ok: true, items: await rows(supabase, "phase3_exchange_rates", organizationId, {}, "effective_at.desc", 100), mock_catalog: Object.entries(FX).map(([pair, rate]) => { const [base_currency, quote_currency] = pair.split(":"); return { base_currency, quote_currency, rate: String(rate), source: "mock_fx" }; }) };
  if (path === "/api/phase3/fx/rates" && method === "POST") return { ok: true, item: await insert(supabase, "phase3_exchange_rates", { organization_id: organizationId, base_currency: required(body.base_currency, "base_currency").toUpperCase(), quote_currency: required(body.quote_currency, "quote_currency").toUpperCase(), rate: String(body.rate), effective_at: body.effective_at || now(), source: body.source || "operator", version: body.version || "fx-v1" }) };
  if (path === "/api/phase3/fx/convert" && method === "POST") {
    const base = required(body.base_currency, "base_currency").toUpperCase(), quote = required(body.quote_currency, "quote_currency").toUpperCase(), amount = Math.max(0, int(body.amount_minor));
    let rate = base === quote ? 1 : FX[`${base}:${quote}`];
    if (!rate) { const saved = (await rows(supabase, "phase3_exchange_rates", organizationId, {}, "effective_at.desc", 500)).find((row) => row.base_currency === base && row.quote_currency === quote); rate = saved ? Number(saved.rate) : 0; }
    if (!rate) throw new Error("No FX rate is configured for that currency pair");
    return { ok: true, base_currency: base, quote_currency: quote, amount_minor: amount, rate: String(rate), converted_minor: Math.round(amount * rate), source: FX[`${base}:${quote}`] ? "mock_fx" : "configured" };
  }
  if (path === "/api/phase3/tax/preview" && method === "POST") {
    const list = await effectiveRegions(supabase, organizationId, 100); const region = list[0] || REGION_CATALOG[0]; const rate = int(body.tax_rate_bps, region.tax_regime === "GST" ? 1800 : 500); const amount = Math.max(0, int(body.amount_minor)); const tax = Math.round(amount * rate / 10000); return { ok: true, region, currency: region.currency, tax_regime: region.tax_regime, tax_rate_bps: rate, tax_minor: tax, total_minor: amount + tax, split: region.tax_regime === "GST" ? "CGST_SGST" : region.tax_regime };
  }
  return undefined;
}

async function predictive(supabase: SupabaseClient, organizationId: string, method: string, path: string, body: Json, query: Json, user: User) {
  if (path === "/api/phase3/predictive-alerts" && method === "GET") return collection(await rows(supabase, "phase3_predictive_alerts", organizationId, query, "risk_score.desc", int(query.limit, 100)));
  if (path === "/api/phase3/predictive-alerts/evaluate" && method === "POST") {
    const duties = await rows(supabase, "duties", organizationId, {}, "reporting_at.asc", 100);
    const active = duties.filter((d) => !["completed", "cancelled"].includes(String(d.status)));
    const model = body.model_version || "predictive-v1"; const suffix = body.idempotency_key || new Date().toISOString().slice(0, 13); const items: Json[] = [];
    for (const duty of active) {
      const factors: Json[] = []; const sources: string[] = [];
      const tracks = await select(supabase, `track_points?organization_id=eq.${organizationId}&duty_id=eq.${duty.id}`); const etas = await select(supabase, `phase12_eta_snapshots?organization_id=eq.${organizationId}&duty_id=eq.${duty.id}`);
      if (!tracks.length) factors.push({ code: "missing_gps", weight: 28, explanation: "No location point is attached to the active duty." }); else sources.push(String(tracks[0].id));
      const deviation = number(etas[0]?.deviation_minutes); if (deviation > 5) { factors.push({ code: "route_deviation", weight: Math.min(35, Math.round(deviation * 1.7)), value: deviation, unit: "minutes" }); sources.push(String(etas[0].id)); }
      const score = Math.min(100, factors.reduce((sum, factor) => sum + number(factor.weight), 0)); if (score < number(body.minimum_risk_score, 30)) continue;
      const primary = factors.sort((a, b) => number(b.weight) - number(a.weight))[0] || { code: "operational_risk" }; const severity = score >= 80 ? "critical" : score >= 60 ? "high" : "medium";
      const item = await insert(supabase, "phase3_predictive_alerts", { organization_id: organizationId, evaluation_key: `${model}:${duty.id}:${primary.code}:${suffix}`, entity_type: "duty", entity_id: duty.id, alert_type: primary.code, severity, risk_score: score, confidence: Math.min(96, 42 + factors.length * 8 + sources.length * 14), lead_time_minutes: severity === "critical" ? 15 : severity === "high" ? 30 : 60, model_version: model, factors, source_event_ids: sources, recommended_action: `Review ${String(primary.code).replaceAll("_", " ")} before the next dispatch checkpoint.`, status: "open", predicted_at: now(), due_at: new Date(Date.now() + 60 * 60_000).toISOString() }, "organization_id,evaluation_key");
      items.push(item);
    }
    return { ok: true, model_version: model, evaluated_at: now(), items, created: items.length };
  }
  const action = path.match(/^\/api\/phase3\/predictive-alerts\/([^/]+)\/(acknowledge|resolve|feedback)$/);
  if (action && method === "POST") {
    if (action[2] === "feedback") { const item = await insert(supabase, "phase3_alert_feedback", { organization_id: organizationId, alert_id: action[1], outcome: required(body.outcome, "outcome"), note: body.note || "", created_by: user.id }); return { ok: true, item }; }
    return { ok: true, item: await patch(supabase, "phase3_predictive_alerts", action[1], organizationId, { status: action[2] === "resolve" ? "resolved" : "acknowledged", acknowledged_by: user.id, acknowledged_at: now(), resolved_at: action[2] === "resolve" ? now() : null, updated_at: now() }) };
  }
  return undefined;
}

async function vendorGraph(supabase: SupabaseClient, organizationId: string, method: string) {
  if (!["GET", "POST"].includes(method)) return undefined;
  const profiles = await rows(supabase, "network_vendor_profiles", organizationId, {}, "vendor_name.asc", 200); const nodes: Json[] = [], edges: Json[] = [], snapshots: Json[] = [];
  for (const profile of profiles) {
    const orders = await select(supabase, `network_service_orders?organization_id=eq.${organizationId}&vendor_profile_id=eq.${profile.id}`); const scorecards = orders.length ? await select(supabase, `network_scorecards?organization_id=eq.${organizationId}&service_order_id=in.(${orders.map((row) => row.id).join(",")})`) : [];
    const metrics = scorecards.flatMap((row) => Object.values(asObject(row.metrics)).map(Number).filter((value) => Number.isFinite(value))).map((value) => Math.max(0, Math.min(100, value))); const serviceScore = metrics.length ? metrics.reduce((a, b) => a + b, 0) / metrics.length : 70; const score = Math.round(Math.min(100, serviceScore * 0.72 + Math.min(100, 35 + scorecards.length * 8) * 0.18 + (orders.length ? 10 : 0)) * 100) / 100; const confidence = scorecards.length >= 12 ? "high" : scorecards.length >= 4 ? "medium" : "cold_start";
    const snapshot = await insert(supabase, "phase3_vendor_quality_snapshots", { organization_id: organizationId, vendor_profile_id: profile.id, vendor_organization_id: profile.vendor_organization_id || null, formula_version: "vendor-quality-v1", score, confidence, sample_size: scorecards.length, metrics: { service_score: serviceScore, coverage: Math.min(100, 35 + scorecards.length * 8) }, source_event_ids: scorecards.map((row) => row.id), computed_at: now() }, "organization_id,vendor_profile_id,formula_version");
    const vendorNode = `vendor:${profile.id}`; nodes.push({ id: vendorNode, type: "vendor", label: profile.vendor_name, score, confidence, sample_size: scorecards.length }); snapshots.push(snapshot);
    for (const order of orders) {
      const orderNode = `service_order:${order.id}`;
      nodes.push({ id: orderNode, type: "service_order", label: order.id, status: order.status });
      edges.push({ from: vendorNode, to: orderNode, type: "serves", weight: 1, evidence: { service_order_id: order.id } });
      if (order.fleet_duty_id) {
        const dutyNode = `duty:${order.fleet_duty_id}`;
        nodes.push({ id: dutyNode, type: "duty", label: order.fleet_duty_id });
        edges.push({ from: orderNode, to: dutyNode, type: "fulfills", weight: 1, evidence: { source: "fleet_handoff" } });
      }
      for (const scorecard of scorecards.filter((row) => row.service_order_id === order.id)) {
        const scorecardNode = `scorecard:${scorecard.id}`;
        nodes.push({ id: scorecardNode, type: "scorecard", label: scorecard.id, status: scorecard.status, metrics: asObject(scorecard.metrics) });
        edges.push({ from: orderNode, to: scorecardNode, type: "measured_by", weight: 1, evidence: { scorecard_id: scorecard.id } });
        const evidenceIds = Array.isArray(asObject(scorecard.evidence).source_event_ids) ? asObject(scorecard.evidence).source_event_ids : [];
        for (const evidenceId of evidenceIds.slice(0, 50)) {
          const evidenceNode = `evidence:${evidenceId}`;
          nodes.push({ id: evidenceNode, type: "evidence", label: String(evidenceId), status: "linked" });
          edges.push({ from: scorecardNode, to: evidenceNode, type: "supported_by", weight: 1, evidence: { source: "scorecard_evidence" } });
        }
      }
    }
  }
  return { ok: true, formula_version: "vendor-quality-v1", nodes: [...new Map(nodes.map((node) => [node.id, node])).values()], edges, snapshots, count: nodes.length, updated_at: now() };
}

async function variance(supabase: SupabaseClient, organizationId: string, method: string, path: string, body: Json) {
  if (path === "/api/phase3/variance/findings" && method === "GET") return collection(await rows(supabase, "phase3_variance_findings", organizationId, body, "created_at.desc", 200), { rule_version: "variance-v1" });
  if (path === "/api/phase3/variance/evaluate" && method === "POST") {
    const duties = await rows(supabase, "duties", organizationId, {}, "created_at.desc", 500); const items: Json[] = [];
    for (const duty of duties) {
      const invoices = await select(supabase, `invoices?organization_id=eq.${organizationId}&duty_id=eq.${duty.id}`);
      const expected = number(asObject(duty.calculation_snapshot).total_paise);
      const observed = number(invoices[0]?.total_paise);
      if (invoices.length && expected && observed !== expected) {
        const pct = (observed - expected) / expected * 100;
        const finding = await insert(supabase, "phase3_variance_findings", { organization_id: organizationId, scan_key: `invoice_calculation:${duty.id}:${new Date().toISOString().slice(0, 10)}`, entity_type: "duty", entity_id: duty.id, variance_type: "invoice_calculation", severity: Math.abs(pct) >= 25 ? "critical" : Math.abs(pct) >= 10 ? "high" : "medium", expected_minor: expected, observed_minor: observed, variance_minor: observed - expected, variance_pct: pct, rule_version: "variance-v1", evidence: { invoice_id: invoices[0].id }, source_event_ids: [duty.id, invoices[0].id], status: "open" }, "organization_id,scan_key");
        items.push(finding);
      }
      const bills = await select(supabase, `supplier_bills?organization_id=eq.${organizationId}&duty_id=eq.${duty.id}`);
      const bill = bills[0];
      if (bill && expected && number(bill.total_paise) !== expected) {
        const billObserved = number(bill.total_paise); const pct = (billObserved - expected) / expected * 100;
        const finding = await insert(supabase, "phase3_variance_findings", { organization_id: organizationId, scan_key: `supplier_bill_rate:${duty.id}:${new Date().toISOString().slice(0, 10)}`, entity_type: "duty", entity_id: duty.id, variance_type: "supplier_bill_rate", severity: Math.abs(pct) >= 25 ? "critical" : Math.abs(pct) >= 10 ? "high" : "medium", expected_minor: expected, observed_minor: billObserved, variance_minor: billObserved - expected, variance_pct: pct, rule_version: "variance-v1", evidence: { supplier_bill_id: bill.id }, source_event_ids: [duty.id, bill.id], status: "open" }, "organization_id,scan_key");
        items.push(finding);
      }
    }
    return { ok: true, rule_version: "variance-v1", evaluated_at: now(), items, created: items.length };
  }
  const action = path.match(/^\/api\/phase3\/variance\/findings\/([^/]+)\/(assign|acknowledge|resolve)$/); if (action && method === "POST") return { ok: true, item: await patch(supabase, "phase3_variance_findings", action[1], organizationId, { status: action[2] === "assign" ? "assigned" : action[2] === "resolve" ? "resolved" : "acknowledged", assigned_to: action[2] === "assign" ? (body.assigned_to || null) : undefined, resolved_at: action[2] === "resolve" ? now() : null, updated_at: now() }) };
  return undefined;
}

async function chargingCandidates(supabase: SupabaseClient, organizationId: string, regionCode: string, connector = "") {
  const { data, error } = await supabase.from("phase3_charging_stations").select("*").eq("organization_id", organizationId).eq("region_code", regionCode).eq("status", "active").order("available_ports", { ascending: false }).order("name", { ascending: true }).limit(100);
  if (error) throw new Error(error.message);
  const stations = (data || []) as Json[];
  if (!connector) return stations;
  return stations.filter((station) => Array.isArray(station.connector_types) && station.connector_types.includes(connector));
}

async function evMetrics(supabase: SupabaseClient, organizationId: string, vehicle: Json, body: Json, distance: number, passengerCount: number, regionCode: string) {
  const fuel = String(vehicle.fuel_type || "petrol").toLowerCase();
  const isEv = Boolean(vehicle.ev_eligible) || ["ev", "electric"].includes(fuel);
  const vehicleStatus = String(vehicle.status || "unknown").toLowerCase();
  if (!isEv) {
    const factor = number(body.factor_kg_per_km, FACTORS[fuel] || FACTORS.petrol);
    const emissions = Math.round(distance * factor * 1000) / 1000;
    return { is_ev: false, vehicle_status: vehicleStatus, operational_constraint: null, eligibility_status: "not_applicable", eligibility_reasons: [], charging_available: false, charging_station_id: null, range_required_km: 0, range_remaining_km: null, energy_kwh: 0, energy_cost_minor: 0, energy_price_per_kwh_minor: 0, emissions_kg: emissions, baseline_emissions_kg: 0, avoided_emissions_kg: 0, emissions_per_passenger_km_g: Math.round(emissions * 1000 / Math.max(0.001, distance * Math.max(1, passengerCount)) * 1000) / 1000, grid_factor_kg_per_kwh: 0, passenger_km: distance * Math.max(1, passengerCount) };
  }
  const connector = String(body.charging_connector || vehicle.charging_connector || "").trim();
  const candidates = await chargingCandidates(supabase, organizationId, regionCode, connector);
  const requestedStationId = String(body.charging_station_id || "").trim();
  const station = requestedStationId ? candidates.find((item) => item.id === requestedStationId) || (await select(supabase, `phase3_charging_stations?organization_id=eq.${organizationId}&id=eq.${requestedStationId}`))[0] : candidates[0];
  const chargingAvailable = Boolean(station && station.status === "active" && number(station.available_ports) > 0 && (!connector || (Array.isArray(station.connector_types) && station.connector_types.includes(connector))));
  const reservePct = Math.max(0, number(body.reserve_pct, 15)); const deadhead = Math.max(0, number(body.deadhead_km, 0));
  const rangeRequired = Math.round((distance + deadhead) * (1 + reservePct / 100) * 1000) / 1000;
  const usableRange = Math.max(0, number(body.usable_range_km, number(vehicle.usable_range_km)));
  const rangeRemaining = Math.max(0, number(body.range_remaining_km, usableRange));
  const capacity = Math.max(0, int(vehicle.seating_capacity));
  const consumption = Math.max(0, number(body.energy_consumption_kwh_per_km, number(vehicle.energy_consumption_kwh_per_km, 0.16)));
  const price = Math.max(0, int(body.energy_price_per_kwh_minor, number(vehicle.energy_price_per_kwh_minor, number(station?.energy_price_per_kwh_minor, 1200))));
  const gridFactor = Math.max(0, number(body.grid_factor_kg_per_kwh, 0.7)); const baselineFactor = Math.max(0, number(body.baseline_factor_kg_per_km, FACTORS.petrol));
  const energy = Math.round(distance * consumption * 1000) / 1000; const energyCost = Math.round(energy * price); const emissions = Math.round(energy * gridFactor * 1000) / 1000; const baseline = Math.round(distance * baselineFactor * 1000) / 1000; const avoided = Math.round(Math.max(0, baseline - emissions) * 1000) / 1000;
  const reasons: string[] = []; let operationalConstraint: string | null = null;
  if (["inactive", "archived", "retired"].includes(vehicleStatus)) { operationalConstraint = "Vehicle is not operationally available"; reasons.push(operationalConstraint); }
  if (capacity < passengerCount) reasons.push(`Vehicle seats ${capacity}; ${passengerCount} passengers requested`);
  const rangeSufficient = rangeRemaining >= rangeRequired;
  if (!rangeSufficient) reasons.push(chargingAvailable ? "A charging stop is required before the duty can complete" : "Usable range is below the duty distance plus reserve");
  if (!chargingAvailable && !rangeSufficient) reasons.push("No active compatible charging station with an available port was found in the selected region");
  if (station && connector && (!Array.isArray(station.connector_types) || !station.connector_types.includes(connector))) reasons.push("Selected charging station does not list the vehicle connector");
  if (rangeSufficient) reasons.push("Range covers the duty distance and reserve");
  const eligibilityStatus = vehicleStatus === "inactive" || vehicleStatus === "archived" || vehicleStatus === "retired" || capacity < passengerCount || (!rangeSufficient && !chargingAvailable) ? "ineligible" : !rangeSufficient && chargingAvailable ? "eligible_with_charge" : "eligible";
  return { is_ev: true, vehicle_status: vehicleStatus, operational_constraint: operationalConstraint, eligibility_status: eligibilityStatus, eligibility_reasons: reasons, charging_available: chargingAvailable, charging_station_id: station?.id || null, charging_station: station || null, range_required_km: rangeRequired, range_remaining_km: rangeRemaining, energy_kwh: energy, energy_cost_minor: energyCost, energy_price_per_kwh_minor: price, emissions_kg: emissions, baseline_emissions_kg: baseline, avoided_emissions_kg: avoided, emissions_per_passenger_km_g: Math.round(emissions * 1000 / Math.max(0.001, distance * Math.max(1, passengerCount)) * 1000) / 1000, grid_factor_kg_per_kwh: gridFactor, consumption_kwh_per_km: consumption, passenger_km: distance * Math.max(1, passengerCount) };
}

async function sustainabilityRows(supabase: SupabaseClient, organizationId: string, query: Json, limit = 5000) {
  let request = supabase.from("phase3_sustainability_trips").select("*").eq("organization_id", organizationId).order("calculated_at", { ascending: false }).limit(Math.min(Math.max(limit, 1), 5000));
  if (query.region_code) request = request.eq("region_code", String(query.region_code));
  if (query.fuel_type) request = request.eq("fuel_type", String(query.fuel_type));
  if (query.period_start) request = request.gte("calculated_at", `${query.period_start}T00:00:00Z`);
  if (query.period_end) request = request.lte("calculated_at", `${query.period_end}T23:59:59Z`);
  const { data, error } = await request; if (error) throw new Error(error.message); return (data || []) as Json[];
}

function sustainabilitySummary(trips: Json[], region: Json, target: Json | null) {
  const distance = trips.reduce((sum, row) => sum + number(row.distance_km), 0); const passengerKm = trips.reduce((sum, row) => sum + number(row.distance_km) * Math.max(1, int(row.passenger_count, 1)), 0); const energy = trips.reduce((sum, row) => sum + number(row.energy_kwh), 0); const energyCost = trips.reduce((sum, row) => sum + int(row.energy_cost_minor), 0); const emissions = trips.reduce((sum, row) => sum + number(row.emissions_kg), 0); const avoided = trips.reduce((sum, row) => sum + number(row.avoided_emissions_kg), 0); const evTrips = trips.filter((row) => ["ev", "electric"].includes(String(row.fuel_type).toLowerCase())); const eligible = trips.filter((row) => ["eligible", "eligible_with_charge"].includes(row.ev_eligibility_status)); const charge = trips.filter((row) => row.charging_available); const range = trips.filter((row) => row.ev_eligibility_status === "eligible_with_charge"); const targetItem = target ? { ...target, progress_pct: Math.round(emissions / Math.max(0.001, number(target.target_kg)) * 10000) / 100 } : null;
  const byRegion = new Map<string, Json>(); for (const trip of trips) { const key = String(trip.region_code || region.region_code || region.catalog_region_code || ""); const bucket = byRegion.get(key) || { region_code: key, distance_km: 0, passenger_km: 0, energy_kwh: 0, energy_cost_minor: 0, emissions_kg: 0, avoided_emissions_kg: 0, trips: 0 }; bucket.distance_km += number(trip.distance_km); bucket.passenger_km += number(trip.distance_km) * Math.max(1, int(trip.passenger_count, 1)); bucket.energy_kwh += number(trip.energy_kwh); bucket.energy_cost_minor += int(trip.energy_cost_minor); bucket.emissions_kg += number(trip.emissions_kg); bucket.avoided_emissions_kg += number(trip.avoided_emissions_kg); bucket.trips += 1; byRegion.set(key, bucket); }
  return { ok: true, region, trips: trips.length, total_distance_km: Math.round(distance * 1000) / 1000, total_passenger_km: Math.round(passengerKm * 1000) / 1000, total_energy_kwh: Math.round(energy * 1000) / 1000, total_energy_cost_minor: energyCost, total_emissions_kg: Math.round(emissions * 1000) / 1000, emissions_per_passenger_km_g: Math.round(emissions * 1000 / Math.max(0.001, passengerKm) * 1000) / 1000, total_avoided_emissions_kg: Math.round(avoided * 1000) / 1000, average_emissions_kg: trips.length ? Math.round(emissions / trips.length * 1000) / 1000 : 0, electric_distance_share_pct: Math.round(evTrips.reduce((sum, row) => sum + number(row.distance_km), 0) / Math.max(0.001, distance) * 10000) / 100, ev_trips: evTrips.length, ev_eligible_trips: eligible.length, charging_available_trips: charge.length, range_constrained_trips: range.length, by_region: [...byRegion.values()].map((row) => ({ ...row, distance_km: Math.round(row.distance_km * 1000) / 1000, passenger_km: Math.round(row.passenger_km * 1000) / 1000, energy_kwh: Math.round(row.energy_kwh * 1000) / 1000, emissions_kg: Math.round(row.emissions_kg * 1000) / 1000, avoided_emissions_kg: Math.round(row.avoided_emissions_kg * 1000) / 1000 })), target: targetItem, factor_version: "factor-v1", reporting_version: "sustainability-report-v2", recommendations: distance && evTrips.length / Math.max(1, trips.length) < 0.2 ? [{ code: "electrify_high_utilization", priority: "medium", message: "Pilot EV allocation on high-distance duty clusters to reduce energy and tailpipe emissions." }] : [] };
}

async function sustainability(supabase: SupabaseClient, organizationId: string, method: string, path: string, body: Json, query: Json, user: User) {
  if (path === "/api/phase3/sustainability/charging-stations" && method === "GET") { const stations = await rows(supabase, "phase3_charging_stations", organizationId, query, "name.asc", int(query.limit, 100)); const regionCode = String(query.region_code || ""); const connector = String(query.connector_type || "").toLowerCase(); const filtered = stations.filter((station) => (!regionCode || String(station.region_code || "") === regionCode) && (!connector || (Array.isArray(station.connector_types) && station.connector_types.some((item: unknown) => String(item).toLowerCase() === connector)))); return collection(filtered); }
  const stationMatch = path.match(/^\/api\/phase3\/sustainability\/charging-stations\/([^/]+)$/);
  if (stationMatch) {
    const current = (await select(supabase, `phase3_charging_stations?organization_id=eq.${organizationId}&id=eq.${stationMatch[1]}`))[0]; if (!current) throw new Error("Charging station not found");
    if (method === "GET") return { ok: true, item: current };
    const update = method === "DELETE" ? { status: "inactive", updated_at: now() } : Object.fromEntries(["name", "location_label", "total_ports", "available_ports", "power_kw", "energy_price_per_kwh_minor", "status", "connector_types", "operating_hours"].filter((key) => body[key] !== undefined).map((key) => [key, body[key]]));
    if (update.total_ports !== undefined && int(update.total_ports) < 0) throw new Error("total_ports cannot be negative"); if (update.available_ports !== undefined && int(update.available_ports) < 0) throw new Error("available_ports cannot be negative"); if (int(update.available_ports ?? current.available_ports) > int(update.total_ports ?? current.total_ports)) throw new Error("available_ports cannot exceed total_ports");
    const item = await patch(supabase, "phase3_charging_stations", stationMatch[1], organizationId, { ...update, updated_at: now() }); const event = await insert(supabase, "phase3_events", { organization_id: organizationId, event_type: "phase3.sustainability.charging_station.updated", entity_type: "charging_station", entity_id: stationMatch[1], payload: { status: item.status }, actor_id: user.id }, ""); return { ok: true, item, audit_reference: event.id };
  }
  if (path === "/api/phase3/sustainability/charging-stations" && method === "POST") {
    const code = required(body.region_code, "region_code").toUpperCase(); if (!REGION_CATALOG.some((item) => item.region_code === code)) throw new Error("Select a region from the controlled catalog");
    const totalPorts = Math.max(1, int(body.total_ports, 1)); const availablePorts = Math.max(0, int(body.available_ports, totalPorts)); if (availablePorts > totalPorts) throw new Error("available_ports cannot exceed total_ports");
    const item = await insert(supabase, "phase3_charging_stations", { organization_id: organizationId, region_code: code, name: required(body.name, "name"), location_label: body.location_label || "", connector_types: Array.isArray(body.connector_types) ? body.connector_types.slice(0, 10) : ["CCS2"], total_ports: totalPorts, available_ports: availablePorts, power_kw: Math.max(0, number(body.power_kw)), energy_price_per_kwh_minor: Math.max(0, int(body.energy_price_per_kwh_minor, 1200)), status: body.status || "active", operating_hours: asObject(body.operating_hours), created_by: user.id }, ""); const event = await insert(supabase, "phase3_events", { organization_id: organizationId, event_type: "phase3.sustainability.charging_station.created", entity_type: "charging_station", entity_id: item.id, payload: { region_code: code }, actor_id: user.id }, ""); return { ok: true, item, audit_reference: event.id };
  }
  if (path === "/api/phase3/sustainability/ev-eligibility" && method === "POST") {
    const vehicleId = required(body.vehicle_id, "vehicle_id"); const vehicle = (await select(supabase, `vehicles?organization_id=eq.${organizationId}&id=eq.${vehicleId}`))[0]; if (!vehicle) throw new Error("Vehicle not found"); const regions = await effectiveRegions(supabase, organizationId, 100); const regionCode = String(body.region_code || regions[0]?.catalog_region_code || "IN-MH"); const metrics = await evMetrics(supabase, organizationId, vehicle, body, Math.max(0, number(body.distance_km)), Math.max(1, int(body.passenger_count, 1)), regionCode); const item = { vehicle_id: vehicleId, registration_number: vehicle.registration_number, region_code: regionCode, distance_km: Math.max(0, number(body.distance_km)), passenger_count: Math.max(1, int(body.passenger_count, 1)), vehicle_capacity: int(vehicle.seating_capacity), ...metrics, formula_version: "sustainability-v2" }; const event = await insert(supabase, "phase3_events", { organization_id: organizationId, event_type: "phase3.sustainability.ev_eligibility", entity_type: "vehicle", entity_id: vehicleId, payload: item, actor_id: user.id }, ""); return { ok: true, item: { ...item, audit_reference: event.id }, audit_reference: event.id };
  }
  if (path === "/api/phase3/sustainability/trips" && method === "GET") return collection(await sustainabilityRows(supabase, organizationId, query, int(query.limit, 100)));
  if (path === "/api/phase3/sustainability/trips" && method === "POST") {
    const ids = Array.isArray(body.duty_ids) ? body.duty_ids : body.duty_id ? [body.duty_id] : []; const items: Json[] = []; const regions = await effectiveRegions(supabase, organizationId, 100); const regionCode = String(body.region_code || regions[0]?.catalog_region_code || "IN-MH");
    for (const dutyId of ids.slice(0, 200)) {
      const duty = (await select(supabase, `duties?organization_id=eq.${organizationId}&id=eq.${dutyId}`))[0]; if (!duty) throw new Error("Duty not found"); const vehicle = duty.vehicle_id ? (await select(supabase, `vehicles?organization_id=eq.${organizationId}&id=eq.${duty.vehicle_id}`))[0] || {} : {}; const distance = Math.max(0, number(body.distance_km, number(asObject(duty.calculation_snapshot).inputs?.distance_km))); const passengerCount = Math.max(1, int(body.passenger_count, 1)); const fuel = String(body.fuel_type || vehicle.fuel_type || "petrol").toLowerCase(); const metrics = await evMetrics(supabase, organizationId, vehicle, body, distance, passengerCount, regionCode); const factor = number(body.factor_kg_per_km, FACTORS[fuel] || FACTORS.petrol); const values = { organization_id: organizationId, duty_id: dutyId, vehicle_id: duty.vehicle_id || null, region_code: regionCode, fuel_type: fuel, distance_km: distance, passenger_count: passengerCount, energy_kwh: metrics.is_ev ? metrics.energy_kwh : number(body.energy_kwh), energy_cost_minor: metrics.is_ev ? metrics.energy_cost_minor : 0, energy_price_per_kwh_minor: metrics.is_ev ? metrics.energy_price_per_kwh_minor : int(body.energy_price_per_kwh_minor), emissions_kg: metrics.is_ev ? metrics.emissions_kg : Math.round(distance * factor * 1000) / 1000, emissions_per_passenger_km_g: metrics.is_ev ? metrics.emissions_per_passenger_km_g : Math.round(distance * factor * 1000 / Math.max(0.001, distance * passengerCount) * 1000) / 1000, baseline_emissions_kg: metrics.is_ev ? metrics.baseline_emissions_kg : 0, avoided_emissions_kg: metrics.is_ev ? metrics.avoided_emissions_kg : 0, factor_kg_per_km: factor, grid_factor_kg_per_kwh: metrics.grid_factor_kg_per_kwh, factor_version: body.factor_version || "factor-v1", range_required_km: metrics.range_required_km, range_remaining_km: metrics.range_remaining_km, charging_station_id: metrics.charging_station_id, charging_available: metrics.charging_available, ev_eligibility_status: metrics.eligibility_status, ev_eligibility_reasons: metrics.eligibility_reasons, source_event_ids: [dutyId], calculated_at: now() };
      const item = await insert(supabase, "phase3_sustainability_trips", values, "organization_id,duty_id,factor_version"); const event = await insert(supabase, "phase3_events", { organization_id: organizationId, event_type: "phase3.sustainability.trip.calculated", entity_type: "sustainability_trip", entity_id: item.id, payload: { duty_id: dutyId, factor_version: item.factor_version }, actor_id: user.id }, ""); items.push({ ...item, audit_reference: event.id });
    }
    return { ok: true, items, count: items.length, factor_version: body.factor_version || "factor-v1", audit_reference: items[0]?.audit_reference || null };
  }
  if (path === "/api/phase3/sustainability/summary" || path === "/api/phase3/sustainability/report") {
    const regions = await effectiveRegions(supabase, organizationId, 100); const region = regions[0] || REGION_CATALOG[0]; const trips = await sustainabilityRows(supabase, organizationId, query, 5000); const targets = await rows(supabase, "phase3_sustainability_targets", organizationId, {}, "period_end.desc", 1); const result: Json = sustainabilitySummary(trips, region, targets[0] || null); result.period_start = query.period_start || null; result.period_end = query.period_end || null; result.generated_at = now();
    if (path.endsWith("/report")) { result.report_type = "fleet_sustainability"; const event = await insert(supabase, "phase3_events", { organization_id: organizationId, event_type: "phase3.sustainability.report.generated", entity_type: "sustainability_report", entity_id: null, payload: { period_start: result.period_start, period_end: result.period_end, region_code: query.region_code || null, trips: trips.length, reporting_version: "sustainability-report-v2" }, actor_id: user.id }, ""); result.audit_reference = event.id; }
    return result;
  }
  if (path === "/api/phase3/sustainability/targets" && method === "GET") return collection(await rows(supabase, "phase3_sustainability_targets", organizationId, {}, "period_end.desc", int(query.limit, 100)));
  if (path === "/api/phase3/sustainability/targets" && method === "POST") { const item = await insert(supabase, "phase3_sustainability_targets", { organization_id: organizationId, scope: body.scope || "fleet", period_start: required(body.period_start, "period_start"), period_end: required(body.period_end, "period_end"), baseline_kg: number(body.baseline_kg), target_kg: number(body.target_kg), status: "active", created_by: user.id }, "organization_id,scope,period_start,period_end"); const event = await insert(supabase, "phase3_events", { organization_id: organizationId, event_type: "phase3.sustainability.target.saved", entity_type: "sustainability_target", entity_id: item.id, payload: { scope: item.scope, period_start: item.period_start, period_end: item.period_end }, actor_id: user.id }, ""); return { ok: true, item, audit_reference: event.id }; }
  return undefined;
}

async function handle(envelope: Envelope, supabase: SupabaseClient, user: User) {
  const path = String(envelope.path || "").replace(/\/$/, "") || "/"; const method = String(envelope.method || "GET").toUpperCase(); const body = asObject(envelope.body); const query = asObject(envelope.query); const organizationId = await organization(supabase, user, envelope.organization_id);
  if (path.startsWith("/api/phase3/regions") || path.startsWith("/api/phase3/localization") || path.startsWith("/api/phase3/fx/") || path === "/api/phase3/tax/preview") return regions(supabase, organizationId, method, path, body);
  if (path.startsWith("/api/phase3/predictive-alerts")) return predictive(supabase, organizationId, method, path, body, query, user);
  if (path === "/api/phase3/vendor-quality/graph") return vendorGraph(supabase, organizationId, method);
  if (path.startsWith("/api/phase3/variance")) return variance(supabase, organizationId, method, path, body);
  if (path.startsWith("/api/phase3/sustainability")) return sustainability(supabase, organizationId, method, path, body, query, user);
  if (path === "/api/phase3/simulations" && method === "GET") return collection(await rows(supabase, "phase3_simulations", organizationId, query, "created_at.desc", int(query.limit, 100)));
  if (path === "/api/phase3/simulations/compare" && method === "POST") {
    const scenarios = Array.isArray(body.scenarios) ? body.scenarios.slice(0, 10) : [];
    if (!scenarios.length) throw new Error("scenarios must contain at least one entry");
const regionRows = await effectiveRegions(supabase, organizationId, 100);
    const region = regionRows[0] || REGION_CATALOG[0];
    return { ok: true, model_version: "cost-service-v1", items: scenarios.map((scenario, index) => ({ scenario_name: scenario.scenario_name || `Scenario ${index + 1}`, outputs: simulation(asObject(scenario), region) })) };
  }
  if ((path === "/api/phase3/simulations" || path === "/api/phase3/simulations/run") && method === "POST") { const key = String(body.idempotency_key || ""); if (key) { const prior = await select(supabase, `phase3_simulations?organization_id=eq.${organizationId}&idempotency_key=eq.${key}`); if (prior[0]) return { ok: true, replayed: true, item: prior[0] }; } const regionRows = await effectiveRegions(supabase, organizationId, 100); const region = regionRows[0] || REGION_CATALOG[0]; const item = await insert(supabase, "phase3_simulations", { organization_id: organizationId, scenario_name: body.scenario_name || "Untitled scenario", status: "completed", model_version: "cost-service-v1", idempotency_key: key || null, inputs: body, outputs: simulation(body, region), created_by: user.id }, "organization_id,idempotency_key"); return { ok: true, replayed: false, item }; }
  const simulationId = path.match(/^\/api\/phase3\/simulations\/([^/]+)$/); if (simulationId && method === "GET") { const items = await select(supabase, `phase3_simulations?organization_id=eq.${organizationId}&id=eq.${simulationId[1]}`); return { ok: true, item: items[0] || null }; }
  throw new Error(`Phase 3 route not implemented: ${method} ${path}`);
}

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (request.method !== "POST") return reply({ ok: false, error: "POST required" }, 405);
  try { const { supabase, user } = await authenticatedClient(request); return reply(await handle(asObject(await request.json()) as Envelope, supabase, user)); }
  catch (error) { const text = errorText(error); const status = /sign in|required|access denied|permission/i.test(text) ? 403 : /not found/i.test(text) ? 404 : 400; return reply({ ok: false, error: text }, status); }
});
