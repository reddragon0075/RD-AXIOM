import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

/* Unauthenticated, token-only passenger feedback boundary. It returns no
 * organization or recipient data and delegates the single-use write to the
 * security-definer submit_public_feedback RPC. The browser adapter sends an
 * envelope because Supabase Edge Functions are invoked at /functions/v1/*;
 * the envelope path is therefore the public API path, not request.url. */
const allowedOrigin = (Deno.env.get("AXIOM_ALLOWED_ORIGIN") || Deno.env.get("AXIOM_ALLOWED_ORIGINS")?.split(",")[0] || "").trim();
const cors = { ...(allowedOrigin ? { "Access-Control-Allow-Origin": allowedOrigin, "Vary": "Origin" } : {}), "Access-Control-Allow-Headers": "content-type", "Access-Control-Allow-Methods": "GET, POST, OPTIONS" };
type Json = Record<string, any>;
type Envelope = { path?: string; method?: string; body?: Json; query?: Json };
function reply(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { ...cors, "Content-Type": "application/json", "Cache-Control": "no-store" } }); }
async function hash(value: string) { const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)); return Array.from(new Uint8Array(digest)).map((part) => part.toString(16).padStart(2, "0")).join(""); }
function client() { const url = Deno.env.get("SUPABASE_URL"); const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY"); if (!url || !key) throw new Error("Public feedback storage is not configured"); return createClient(url, key); }
Deno.serve(async (request) => {
  if (request.method === "OPTIONS") return new Response("ok", { headers: cors });
  try {
    const envelope = await request.json() as Envelope;
    const route = String(envelope.path || new URL(request.url).pathname).replace(/\/$/, "");
    const method = String(envelope.method || request.method).toUpperCase();
    const match = route.match(/^\/api\/feedback\/v1\/([^/]+)$/); const token = match?.[1] || String(envelope.query?.token || ""); if (!token) return reply({ ok: false, error: "Feedback token is required" }, 400);
    const supabase = client(); const tokenHash = await hash(token);
    const { data: link, error } = await supabase.from("feedback_public_links").select("id,label,form_id,expires_at,status,allow_anonymous").eq("token_hash", tokenHash).in("status", ["active", "submitted"]).maybeSingle(); if (error || !link) return reply({ ok: false, error: "Feedback link is invalid" }, 403); if (new Date(link.expires_at).getTime() < Date.now()) return reply({ ok: false, error: "Feedback link has expired" }, 410);
    if (method === "GET") { const { data: form } = link.form_id ? await supabase.from("feedback_forms").select("questions,status").eq("id", link.form_id).maybeSingle() : { data: null }; return reply({ ok: true, feedback: { id: link.id, label: link.label, expires_at: link.expires_at, allow_anonymous: link.allow_anonymous, questions: form?.questions || [{ key: "rating", label: "How was your trip?", type: "rating", required: true }] } }); }
    if (method !== "POST") return reply({ ok: false, error: "Method not allowed" }, 405);
    const body = envelope.body || {}; const { data, error: submitError } = await supabase.rpc("submit_public_feedback", { p_token_hash: tokenHash, p_rating: Number(body.rating), p_answers: body.answers && typeof body.answers === "object" ? body.answers : {}, p_tags: Array.isArray(body.tags) ? body.tags : [], p_comment: String(body.comment || "").slice(0, 4000) }); if (submitError) return reply({ ok: false, error: submitError.message }, 400); return reply(data || { ok: true });
  } catch (error) { return reply({ ok: false, error: error instanceof Error ? error.message : String(error || "Public feedback request failed") }, 400); }
});
