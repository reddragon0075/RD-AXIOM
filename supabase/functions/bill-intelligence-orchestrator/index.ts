import { createClient, type SupabaseClient, type User } from "https://esm.sh/@supabase/supabase-js@2";

/* Authenticated production boundary for bill extraction and review. The local
 * fallback has the same routes and adds deterministic regex extraction. A
 * production deployment should replace extractFields with the configured
 * vision/OCR worker and keep posting inside a reviewed transaction/RPC. */
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
function number(value: unknown) { const result = Number(String(value ?? "").replace(/[^0-9.\-]/g, "")); return Number.isFinite(result) ? result : null; }
function now() { return new Date().toISOString(); }
function amountMinor(value: unknown) { const numeric = number(value) || 0; return Math.round(numeric * 100); }
function valueFrom(text: string, labels: string[]) { const match = text.match(new RegExp(`(?:${labels.map((item) => item.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})\\s*[:=#-]?\\s*([^\\n\\r|]+)`, "i")); return match?.[1]?.trim() || ""; }
function numberFrom(text: string, labels: string[]) { return number(valueFrom(text, labels)); }
function registration(text: string) { return text.match(/\b[A-Z]{2}[\s-]?\d{1,2}[\s-]?[A-Z]{1,3}[\s-]?\d{4}\b/i)?.[0]?.replace(/-/g, " ").replace(/\s+/g, " ").trim() || ""; }
function billType(text: string) { const lower = text.toLowerCase(); if (/fuel|petrol|diesel|cng|litre|liter|pump/.test(lower)) return "fuel"; if (/toll|fastag|plaza/.test(lower)) return "toll"; if (/insurance|premium|policy/.test(lower)) return "insurance"; if (/service|maintenance|repair|labour|labor/.test(lower)) return "maintenance"; return "other"; }
function extractFields(body: Json) {
  const text = String(body.ocr_text || ""); const supplied = body.extracted && typeof body.extracted === "object" ? body.extracted : {};
  const fields: Json = {
    bill_type: supplied.bill_type || billType(text),
    vendor_name: supplied.vendor_name || valueFrom(text, ["vendor", "supplier", "petrol pump", "service centre"]),
    vendor_gstin: String(supplied.vendor_gstin || valueFrom(text, ["gstin", "gst no"])).toUpperCase(),
    invoice_number: supplied.invoice_number || valueFrom(text, ["invoice no", "invoice number", "bill no", "bill number"]),
    invoice_date: supplied.invoice_date || valueFrom(text, ["invoice date", "bill date", "date"]),
    vehicle_regd_no_raw: supplied.vehicle_regd_no_raw || registration(text),
    odometer_km: supplied.odometer_km ?? numberFrom(text, ["odometer", "odo", "speedo"]),
    fuel_type: supplied.fuel_type || valueFrom(text, ["fuel type", "fuel"]),
    quantity: supplied.quantity ?? numberFrom(text, ["quantity", "qty", "litres", "liters", "kwh"]),
    unit: supplied.unit || "L",
    rate_per_unit: supplied.rate_per_unit ?? numberFrom(text, ["rate", "rate per litre", "rate per unit"]),
    amount_fuel: supplied.amount_fuel ?? numberFrom(text, ["fuel amount", "amount fuel"]),
    policy_number: supplied.policy_number || valueFrom(text, ["policy no", "policy number"]),
    policy_expiry: supplied.policy_expiry || valueFrom(text, ["policy expiry", "expiry", "valid till"]),
    total_amount: supplied.total_amount ?? numberFrom(text, ["grand total", "total amount", "invoice total", "total", "amount payable"]),
    payment_mode: supplied.payment_mode || valueFrom(text, ["payment mode", "paid by"]),
  };
  if (fields.total_amount == null) fields.total_amount = fields.amount_fuel;
  if (fields.amount_fuel == null && fields.bill_type === "fuel") fields.amount_fuel = fields.total_amount;
  const confidence: Json = {};
  Object.entries(fields).forEach(([key, value]) => { confidence[key] = supplied[key] != null ? 0.96 : value !== "" && value != null ? 0.88 : 0; });
  fields.confidence = { ...confidence, ...(supplied.confidence || {}) }; fields.needs_review = true;
  return fields;
}

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
async function rows(supabase: SupabaseClient, table: string, organizationId: string, query: Json = {}) { let request = supabase.from(table).select("*").eq("organization_id", organizationId).order("created_at", { ascending: false }).limit(Math.min(Math.max(Number(query.limit || 100), 1), 500)); if (query.status && query.status !== "all") request = request.eq("status", query.status); const { data, error } = await request; if (error) throw new Error(error.message); return (data || []) as Json[]; }
async function insert(supabase: SupabaseClient, table: string, value: Json, conflict = "") { const { data, error } = await supabase.from(table).upsert(value, { onConflict: conflict || undefined }).select().single(); if (error) throw new Error(error.message); return data as Json; }
async function audit(supabase: SupabaseClient, organizationId: string, user: User, action: string, entityId: string, afterData: Json) { const { error } = await supabase.rpc('append_bill_intelligence_audit', { p_organization_id: organizationId, p_action: action, p_entity_type: 'bill', p_entity_id: entityId, p_after_data: afterData, p_metadata: { source: 'bill_intelligence', actor_id: user.id } }); if (error) throw new Error(error.message); }

async function postRecord(supabase: SupabaseClient, user: User, organizationId: string, existing: Json, body: Json) {
  if (existing.status === 'posted') return { item: existing, posted: existing.posting || {}, replayed: true };
  if (existing.status === 'reversed') throw new Error('A reversed bill cannot be posted again');
  const overrides = body.overrides && typeof body.overrides === 'object' ? body.overrides : {};
  const extracted = { ...(existing.extracted || {}), ...overrides };
  const vehicleId = body.vehicle_id || existing.vehicle_id || extracted.vehicle_id || null;
  const total = number(extracted.total_amount) || 0;
  if (!vehicleId) throw new Error('Select the vehicle that this bill belongs to');
  if (total <= 0) throw new Error('A positive total amount is required before posting');
  const { data: vehicle, error: vehicleError } = await supabase.from('vehicles').select('*').eq('id', vehicleId).eq('organization_id', organizationId).maybeSingle();
  if (vehicleError) throw new Error(vehicleError.message); if (!vehicle) throw new Error('Vehicle not found in this tenant');
  const invoiceNumber = String(extracted.invoice_number || `AI-${String(existing.id).slice(-10).toUpperCase()}`);
  const duplicate = await supabase.from('supplier_bills').select('id').eq('organization_id', organizationId).eq('bill_number', invoiceNumber).maybeSingle();
  if (duplicate.error) throw new Error(duplicate.error.message); if (duplicate.data) throw new Error('A supplier bill with this invoice number already exists');
  const tax = (number(extracted.cgst) || 0) + (number(extracted.sgst) || 0) + (number(extracted.igst) || 0);
  const attachment = { source: 'ocr_bill', bill_id: existing.id, filename: existing.filename, storage_reference: existing.storage_reference, file_sha256: existing.file_sha256, confidence: existing.confidence || {} };
  const supplierBill = await insert(supabase, 'supplier_bills', { organization_id: organizationId, supplier_id: existing.supplier_id || null, bill_number: invoiceNumber, subtotal_paise: amountMinor((number(extracted.taxable_value) || total - tax)), tax_paise: amountMinor(tax), total_paise: amountMinor(total), status: 'approved', duty_id: existing.duty_id || null, attachment, validation: { source: 'bill_intelligence', validation: existing.validation || {} }, created_by: user.id });
  const category = ({ fuel: 'fuel', maintenance: 'maintenance', toll: 'toll', insurance: 'insurance', tyre: 'tyre' } as Json)[extracted.bill_type] || 'other';
  const cost = await insert(supabase, 'cost_entries', { organization_id: organizationId, cost_type: 'vehicle', category, amount_paise: amountMinor(total), vehicle_id: vehicleId, duty_id: existing.duty_id || null, supplier_bill_id: supplierBill.id, status: 'approved', attachment, notes: `Auto-posted from bill ${existing.id}`, created_by: user.id });
  const postingRows: Json[] = [{ organization_id: organizationId, bill_id: existing.id, posting_type: 'supplier_bill', entity_type: 'supplier_bill', entity_id: supplierBill.id, payload: { status: 'approved' } }, { organization_id: organizationId, bill_id: existing.id, posting_type: 'cost_entry', entity_type: 'cost_entry', entity_id: cost.id, payload: { status: 'approved', category } }];
  let fuelEntry: Json | null = null;
  if (extracted.bill_type === 'fuel') {
    const quantity = number(extracted.quantity) || 0; if (quantity <= 0) throw new Error('Fuel quantity is required for a fuel bill');
    const odometer = number(extracted.odometer_km); const previous = number(vehicle.current_odometer_km) || 0; const mileage = odometer != null && previous > 0 ? (odometer - previous) / quantity : null; const anomaly = mileage != null && mileage <= 0 ? 'odometer_rollback' : mileage != null && mileage > 200 ? 'mileage_outlier' : '';
    fuelEntry = await insert(supabase, 'bill_intelligence_fuel_entries', { organization_id: organizationId, bill_id: existing.id, vehicle_id: vehicleId, duty_id: existing.duty_id || null, fuel_type: extracted.fuel_type || '', quantity, unit: extracted.unit || 'L', rate_per_unit: number(extracted.rate_per_unit), amount_paise: amountMinor(total), odometer_km: odometer, station: extracted.vendor_name || '', invoice_date: extracted.invoice_date || null, mileage_km_per_unit: mileage, anomaly_code: anomaly, status: 'posted' });
    postingRows.push({ organization_id: organizationId, bill_id: existing.id, posting_type: 'fuel_entry', entity_type: 'fuel_entry', entity_id: fuelEntry.id, payload: { status: 'posted', anomaly_code: anomaly, previous_odo: previous } });
    await insert(supabase, 'bill_intelligence_timeline', { organization_id: organizationId, vehicle_id: vehicleId, bill_id: existing.id, event_type: 'fuel_posted', source: 'ocr_bill', payload: { fuel_entry_id: fuelEntry.id, quantity, amount_paise: amountMinor(total), mileage_km_per_unit: mileage, anomaly_code: anomaly }, created_by: user.id });
  }
  const priorVehicle: Json = { current_odometer_km: vehicle.current_odometer_km, odometer_updated_at: vehicle.odometer_updated_at, insurance_policy_number: vehicle.insurance_policy_number, next_service_due_km: vehicle.next_service_due_km, next_service_due_date: vehicle.next_service_due_date, compliance: vehicle.compliance || {} };
  const vehiclePatch: Json = {}; const odometer = number(extracted.odometer_km); if (odometer != null && odometer > (number(vehicle.current_odometer_km) || 0)) { vehiclePatch.current_odometer_km = odometer; vehiclePatch.odometer_updated_at = now(); }
  if (extracted.bill_type === 'insurance' && extracted.policy_number) vehiclePatch.insurance_policy_number = extracted.policy_number;
  if (extracted.next_service_due_km != null) vehiclePatch.next_service_due_km = number(extracted.next_service_due_km);
  if (extracted.next_service_due_date) vehiclePatch.next_service_due_date = extracted.next_service_due_date;
  if (Object.keys(vehiclePatch).length || extracted.policy_expiry) {
    if (extracted.policy_expiry) vehiclePatch.compliance = { ...(vehicle.compliance || {}), insurance_expiry: extracted.policy_expiry, bill_source_id: existing.id };
    const updatedVehicle = await supabase.from('vehicles').update(vehiclePatch).eq('id', vehicleId).eq('organization_id', organizationId).select().single(); if (updatedVehicle.error) throw new Error(updatedVehicle.error.message);
    postingRows.push({ organization_id: organizationId, bill_id: existing.id, posting_type: 'vehicle_update', entity_type: 'vehicle', entity_id: vehicleId, payload: { prior: priorVehicle, new: vehiclePatch } });
    await insert(supabase, 'bill_intelligence_timeline', { organization_id: organizationId, vehicle_id: vehicleId, bill_id: existing.id, event_type: 'vehicle_master_updated', source: 'ocr_bill', payload: { updated_fields: Object.keys(vehiclePatch), source: 'ocr_bill' }, created_by: user.id });
    if (odometer != null) await insert(supabase, 'bill_intelligence_timeline', { organization_id: organizationId, vehicle_id: vehicleId, bill_id: existing.id, event_type: 'odometer_recorded', source: 'ocr_bill', payload: { odometer_km: odometer, source: 'ocr_bill' }, created_by: user.id });
  }
  for (const posting of postingRows) await insert(supabase, 'bill_intelligence_postings', posting, 'bill_id,posting_type,entity_id');
  const posting = { supplier_bill_id: supplierBill.id, cost_entry_id: cost.id, fuel_entry_id: fuelEntry?.id || null, vehicle_id: vehicleId, posting_types: postingRows.map(row => row.posting_type) };
  const updated = await supabase.from('bill_intelligence_records').update({ status: 'posted', vehicle_id: vehicleId, extracted, posting, reviewed_by: user.id, posted_at: now(), updated_at: now(), review_note: body.note || '' }).eq('id', existing.id).eq('organization_id', organizationId).select().single(); if (updated.error) throw new Error(updated.error.message);
  await audit(supabase, organizationId, user, 'bill_intelligence.posted', existing.id, posting);
  return { item: updated.data, posted: posting, replayed: false };
}

async function route(supabase: SupabaseClient, user: User, organizationId: string, envelope: Envelope) {
  const path = envelope.path.replace(/\/$/, "") || "/"; const method = envelope.method || "GET"; const body = envelope.body || {}; const query = envelope.query || {};
  if (path === "/api/bill-intelligence/summary" && method === "GET") { const items = await rows(supabase, "bill_intelligence_records", organizationId, { limit: 500 }); const posted = items.filter((item) => item.status === "posted"); return { ok: true, summary: { review_count: items.filter((item) => ["needs_review", "draft"].includes(item.status)).length, posted_count: posted.length, rejected_count: items.filter((item) => item.status === "rejected").length, reversed_count: items.filter((item) => item.status === "reversed").length, total_count: items.length, posted_amount: posted.reduce((sum, item) => sum + Number(item.extracted?.total_amount || 0), 0), auto_match_rate: items.length ? Math.round(items.filter((item) => item.vehicle_id).length / items.length * 1000) / 10 : 0 } }; }
  if (path === "/api/bill-intelligence" && method === "GET") { const items = await rows(supabase, "bill_intelligence_records", organizationId, query); return { ok: true, items, count: items.length }; }
  if (path === "/api/bill-intelligence" && method === "POST") {
    const extracted = extractFields(body);
    if (body.idempotency_key) { const replay = await supabase.from("bill_intelligence_records").select("*").eq("organization_id", organizationId).eq("idempotency_key", body.idempotency_key).maybeSingle(); if (replay.error) throw new Error(replay.error.message); if (replay.data) return { ok: true, item: replay.data, replayed: true }; }
    const record = await insert(supabase, "bill_intelligence_records", { organization_id: organizationId, source: body.source || "vendor_portal", filename: body.filename || "bill-upload", content_type: body.content_type || "application/octet-stream", storage_reference: body.storage_reference || `pending/${organizationId}/${Date.now()}`, file_sha256: body.file_sha256 || "", ocr_text: body.ocr_text || "", bill_type: extracted.bill_type || "other", vehicle_id: body.vehicle_id || null, duty_id: body.duty_id || null, supplier_id: body.supplier_id || null, status: "needs_review", extracted, confidence: extracted.confidence || {}, validation: { errors: extracted.total_amount > 0 ? [] : [{ code: "total_missing", message: "A positive total amount is required." }], warnings: [], vehicle_candidates: [], auto_post_eligible: Boolean(extracted.total_amount && body.vehicle_id), review_required: true }, idempotency_key: body.idempotency_key || null, created_by: user.id }, "organization_id,idempotency_key"); return { ok: true, item: record, replayed: false }; }
  const detail = path.match(/^\/api\/bill-intelligence\/([^/]+)(?:\/(review|approve|reject|undo))?$/);
  if (detail) {
    const id = detail[1]; const action = detail[2]; const detailResult = await supabase.from("bill_intelligence_records").select("*").eq("id", id).eq("organization_id", organizationId).maybeSingle(); if (detailResult.error) throw new Error(detailResult.error.message); const existing = detailResult.data; if (!existing) throw new Error("Bill record not found");
    if (method === "GET" && !action) { if (existing.vehicle_id) { const timelineResult = await supabase.from("bill_intelligence_timeline").select("*").eq("organization_id", organizationId).eq("vehicle_id", existing.vehicle_id).eq("bill_id", id).order("event_at", { ascending: true }); if (timelineResult.error) throw new Error(timelineResult.error.message); existing.timeline = timelineResult.data || []; } const postingsResult = await supabase.from("bill_intelligence_postings").select("*").eq("organization_id", organizationId).eq("bill_id", id).order("created_at", { ascending: true }); if (postingsResult.error) throw new Error(postingsResult.error.message); existing.postings = postingsResult.data || []; return { ok: true, item: existing }; }
    if (method === "POST" && action === "review") { const fields = body.fields && typeof body.fields === "object" ? body.fields : {}; const next = { ...existing.extracted, ...fields }; const updated = await supabase.from("bill_intelligence_records").update({ extracted: next, confidence: next.confidence || existing.confidence, vehicle_id: body.vehicle_id || existing.vehicle_id, validation: { ...(existing.validation || {}), review_required: true }, review_note: body.note || "", reviewed_by: user.id, updated_at: now() }).eq("id", id).eq("organization_id", organizationId).select().single(); if (updated.error) throw new Error(updated.error.message); return { ok: true, item: updated.data }; }
    if (method === "POST" && action === "approve") return { ok: true, ...(await postRecord(supabase, user, organizationId, existing, body)) };
    if (method === "POST" && action === "reject") { const updated = await supabase.from("bill_intelligence_records").update({ status: "rejected", review_note: body.note || "", reviewed_by: user.id, updated_at: now() }).eq("id", id).eq("organization_id", organizationId).select().single(); if (updated.error) throw new Error(updated.error.message); return { ok: true, item: updated.data }; }
    if (method === "POST" && action === "undo") {
      if (existing.status === "reversed") return { ok: true, item: existing, replayed: true };
      if (existing.status !== "posted") throw new Error("Only a posted bill can be undone");
      const postingsResult = await supabase.from("bill_intelligence_postings").select("*").eq("organization_id", organizationId).eq("bill_id", id);
      if (postingsResult.error) throw new Error(postingsResult.error.message);
      for (const posting of postingsResult.data || []) {
        if (posting.posting_type === "cost_entry") { const result = await supabase.from("cost_entries").update({ status: "reversed", notes: `Reversed from bill ${id}` }).eq("id", posting.entity_id).eq("organization_id", organizationId); if (result.error) throw new Error(result.error.message); }
        if (posting.posting_type === "supplier_bill") { const result = await supabase.from("supplier_bills").update({ status: "cancelled", updated_at: now() }).eq("id", posting.entity_id).eq("organization_id", organizationId); if (result.error) throw new Error(result.error.message); }
        if (posting.posting_type === "fuel_entry") { const result = await supabase.from("bill_intelligence_fuel_entries").update({ status: "reversed", reversed_at: now() }).eq("id", posting.entity_id).eq("organization_id", organizationId); if (result.error) throw new Error(result.error.message); }
        if (posting.posting_type === "vehicle_update" && existing.vehicle_id) { const prior = posting.payload?.prior || {}; if (Object.keys(prior).length) { const result = await supabase.from("vehicles").update(prior).eq("id", existing.vehicle_id).eq("organization_id", organizationId); if (result.error) throw new Error(result.error.message); } }
      }
      const updated = await supabase.from("bill_intelligence_records").update({ status: "reversed", review_note: body.note || "Reversed by reviewer", reviewed_by: user.id, updated_at: now() }).eq("id", id).eq("organization_id", organizationId).select().single(); if (updated.error) throw new Error(updated.error.message);
      if (existing.vehicle_id) await insert(supabase, "bill_intelligence_timeline", { organization_id: organizationId, vehicle_id: existing.vehicle_id, bill_id: id, event_type: "bill_reversed", source: "reviewer", payload: { reason: body.note || "Reversed by reviewer" }, created_by: user.id });
      await audit(supabase, organizationId, user, "bill_intelligence.reversed", id, { reason: body.note || "Reversed by reviewer" });
      return { ok: true, item: updated.data };
    }
  }
  const timeline = path.match(/^\/api\/bill-intelligence\/vehicles\/([^/]+)\/timeline$/); if (timeline && method === "GET") { const { data, error } = await supabase.from("bill_intelligence_timeline").select("*").eq("organization_id", organizationId).eq("vehicle_id", timeline[1]).order("event_at", { ascending: false }).limit(Number(query.limit || 100)); if (error) throw new Error(error.message); return { ok: true, items: data || [], count: (data || []).length }; }
  throw new Error("Bill intelligence route not found");
}

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") return new Response("ok", { headers: cors });
  try { const { supabase, user } = await authenticated(request); const envelope = await request.json() as Envelope; const organizationId = await organization(supabase, user, envelope.organization_id); return reply(await route(supabase, user, organizationId, envelope)); }
  catch (error) { return reply({ ok: false, error: error instanceof Error ? error.message : String(error || "Bill intelligence request failed") }, 400); }
});
