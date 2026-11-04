import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const allowedOrigin = (Deno.env.get("AXIOM_ALLOWED_ORIGIN") || Deno.env.get("AXIOM_ALLOWED_ORIGINS")?.split(",")[0] || "").trim();
const cors = {
  ...(allowedOrigin ? { "Access-Control-Allow-Origin": allowedOrigin, "Vary": "Origin" } : {}),
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};
function reply(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { ...cors, "Content-Type": "application/json" } }); }
function text(value: unknown) { return String(value || "").trim(); }

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") return new Response("ok", { status: 200, headers: cors });
  try {
    const url = new URL(request.url);
    const body = request.method === "POST" ? await request.json().catch(() => ({})) : {};
    const rawToken = text((body as Record<string, unknown>).action_token || url.searchParams.get("token"));
    const approvalId = text((body as Record<string, unknown>).approval_id || url.searchParams.get("approval_id")) || null;
    const decision = text((body as Record<string, unknown>).decision) || null;
    const comment = text((body as Record<string, unknown>).comment);
    if (!rawToken) return reply({ ok: false, code: "invalid_action_token", message: "A signed action token is required." }, 403);
    const supabase = createClient(String(Deno.env.get("SUPABASE_URL") || ""), String(Deno.env.get("SUPABASE_ANON_KEY") || ""));
    const { data, error } = await supabase.rpc("corporate_signed_duty_slip_action", { raw_token: rawToken, target_approval: approvalId, decision, decision_comment: comment });
    if (error) return reply({ ok: false, code: "signed_action_failed", message: error.message }, error.message.toLowerCase().includes("expired") ? 410 : 403);
    return reply({ ok: true, item: data, allowed_actions: data?.status === "pending" ? ["approve", "reject"] : [] });
  } catch (error) {
    return reply({ ok: false, code: "signed_action_failed", message: error instanceof Error ? error.message : String(error) }, 400);
  }
});
