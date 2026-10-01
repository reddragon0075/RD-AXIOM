import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const MAX_BODY_BYTES = 512_000;
const REPLAY_WINDOW_SECONDS = 300;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SECRET_ENV: Record<string, string> = {
  payment: "AXIOM_PAYMENT_WEBHOOK_SECRET",
  sms: "AXIOM_SMS_WEBHOOK_SECRET",
  email: "AXIOM_EMAIL_WEBHOOK_SECRET",
  whatsapp: "AXIOM_WHATSAPP_WEBHOOK_SECRET",
  telephony: "AXIOM_TELEPHONY_WEBHOOK_SECRET",
};
const SIGNATURE_HEADERS: Record<string, string[]> = {
  payment: ["x-axiom-signature", "x-payment-signature", "x-webhook-signature", "x-razorpay-signature"],
  sms: ["x-axiom-signature", "x-sms-signature", "x-webhook-signature"],
  email: ["x-axiom-signature", "x-email-signature", "x-webhook-signature"],
  whatsapp: ["x-axiom-signature", "x-hub-signature-256", "x-whatsapp-signature"],
  telephony: ["x-axiom-signature", "x-telephony-signature", "x-webhook-signature"],
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}

function bytesToHex(bytes: Uint8Array) {
  return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function constantTimeEqual(left: string, right: string) {
  const a = new TextEncoder().encode(left.toLowerCase());
  const b = new TextEncoder().encode(right.toLowerCase());
  if (a.length !== b.length) return false;
  let difference = 0;
  for (let index = 0; index < a.length; index += 1) difference |= a[index] ^ b[index];
  return difference === 0;
}

async function hmacHex(secret: string, message: Uint8Array) {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return bytesToHex(new Uint8Array(await crypto.subtle.sign("HMAC", key, message as BufferSource)));
}

function normalizeSignature(value: string) {
  const trimmed = value.trim();
  if (trimmed.startsWith("sha256=")) return trimmed.slice(7);
  if (trimmed.startsWith("hmac-sha256=")) return trimmed.slice(12);
  return trimmed;
}

function providerFromPath(request: Request) {
  const value = new URL(request.url).pathname.split("/").filter(Boolean).pop()?.toLowerCase() || "";
  return value in SECRET_ENV ? value : "";
}

async function verifiedSignature(request: Request, provider: string, raw: Uint8Array) {
  const secretName = SECRET_ENV[provider];
  const secret = Deno.env.get(secretName) || "";
  if (!secret) throw new Error(`${secretName} is not configured`);
  const timestamp = request.headers.get("x-axiom-timestamp") || request.headers.get("x-webhook-timestamp") || "";
  if (timestamp) {
    const parsed = Number(timestamp);
    if (!Number.isSafeInteger(parsed) || Math.abs(Math.floor(Date.now() / 1000) - parsed) > REPLAY_WINDOW_SECONDS) throw new Error("Webhook timestamp is outside the replay window");
  }
  const signedBody = timestamp ? new TextEncoder().encode(`${timestamp}.${new TextDecoder().decode(raw)}`) : raw;
  const expected = await hmacHex(secret, signedBody);
  const presented = SIGNATURE_HEADERS[provider].map((header) => request.headers.get(header) || "").find(Boolean) || "";
  if (!presented || !constantTimeEqual(normalizeSignature(presented), expected)) throw new Error("Webhook signature is invalid");
  return true;
}

Deno.serve(async (request) => {
  if (request.method !== "POST") return json({ error: "POST required" }, 405);
  const provider = providerFromPath(request);
  if (!provider) return json({ error: "Provider must be payment, sms, email, whatsapp or telephony" }, 404);
  const rawText = await request.text();
  const raw = new TextEncoder().encode(rawText);
  if (raw.length > MAX_BODY_BYTES) return json({ error: "Webhook body is too large" }, 413);
  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(rawText);
  } catch (_) {
    return json({ error: "Webhook body must be valid JSON" }, 400);
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return json({ error: "Webhook payload must be an object" }, 400);
  try {
    await verifiedSignature(request, provider, raw);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Webhook signature is invalid";
    const status = message.includes("not configured") ? 503 : 401;
    return json({ error: message, code: status === 503 ? "webhook_secret_required" : "invalid_webhook_signature" }, status);
  }

  const externalId = String(payload.event_id || payload.id || request.headers.get("x-axiom-event-id") || "").trim();
  const eventType = String(payload.event_type || payload.type || "").trim();
  const organizationId = String(payload.organization_id || request.headers.get("x-axiom-organization-id") || "").trim();
  if (!externalId || externalId.length > 160 || !eventType || eventType.length > 160) return json({ error: "event_id and event_type are required" }, 400);
  if (!organizationId || !UUID_RE.test(organizationId)) return json({ error: "organization_id is required" }, 400);

  const url = Deno.env.get("SUPABASE_URL");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !serviceRoleKey) return json({ error: "Supabase service configuration is required" }, 503);
  const supabase = createClient(url, serviceRoleKey, { auth: { persistSession: false, autoRefreshToken: false } });
  const existing = await supabase.from("webhook_events").select("id, status").eq("provider", provider).eq("external_id", externalId).maybeSingle();
  if (existing.error) return json({ error: "Webhook event lookup failed" }, 500);
  if (existing.data) return json({ ok: true, status: "duplicate", event_id: existing.data.id });
  const inserted = await supabase.from("webhook_events").insert({
    organization_id: organizationId,
    provider,
    event_type: eventType,
    external_id: externalId,
    payload,
    signature_valid: true,
    status: "received",
  }).select("id").single();
  if (inserted.error) {
    const replay = await supabase.from("webhook_events").select("id").eq("provider", provider).eq("external_id", externalId).maybeSingle();
    if (replay.data) return json({ ok: true, status: "duplicate", event_id: replay.data.id });
    return json({ error: "Webhook event could not be recorded" }, 500);
  }
  return json({ ok: true, status: "received", event_id: inserted.data.id });
});
