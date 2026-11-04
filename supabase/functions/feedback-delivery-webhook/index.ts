import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

type Json = Record<string, any>;

const MAX_BODY_BYTES = 512_000;
const REPLAY_WINDOW_SECONDS = 300;
const SECRET_ENV: Record<string, string> = {
  sms: "AXIOM_SMS_WEBHOOK_SECRET",
  email: "AXIOM_EMAIL_WEBHOOK_SECRET",
  whatsapp: "AXIOM_WHATSAPP_WEBHOOK_SECRET",
};

function reply(body: unknown, status = 200) {
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

function channelOf(value: unknown) {
  const channel = String(value || "").trim().toLowerCase();
  if (channel === "sms" || channel === "email" || channel === "whatsapp") return channel;
  if (["mail", "sendgrid", "ses"].includes(channel)) return "email";
  if (["wa", "meta", "gupshup"].includes(channel)) return "whatsapp";
  if (["text", "twilio", "msg91"].includes(channel)) return "sms";
  return "";
}

function eventValue(payload: Json, ...keys: string[]) {
  for (const key of keys) {
    const value = payload[key];
    if (value !== undefined && value !== null && String(value).trim()) return String(value).trim();
  }
  return "";
}

async function verifySignature(request: Request, channel: string, raw: Uint8Array) {
  const secret = (Deno.env.get(SECRET_ENV[channel]) || Deno.env.get("AXIOM_PROVIDER_WEBHOOK_SECRET") || "").trim();
  if (!secret) throw new Error(`${SECRET_ENV[channel]} is not configured`);
  const timestamp = (request.headers.get("x-axiom-timestamp") || request.headers.get("x-webhook-timestamp") || "").trim();
  const parsedTimestamp = Number(timestamp);
  if (!timestamp || !Number.isSafeInteger(parsedTimestamp) || Math.abs(Math.floor(Date.now() / 1000) - parsedTimestamp) > REPLAY_WINDOW_SECONDS) {
    throw new Error("Webhook timestamp is outside the replay window");
  }
  const signature = [
    request.headers.get("x-axiom-signature"),
    request.headers.get("x-webhook-signature"),
    request.headers.get(`x-${channel}-signature`),
    request.headers.get("x-hub-signature-256"),
  ].map((value) => value || "").find(Boolean) || "";
  const expected = await hmacHex(secret, new TextEncoder().encode(`${timestamp}.${new TextDecoder().decode(raw)}`));
  if (!signature || !constantTimeEqual(normalizeSignature(signature), expected)) throw new Error("Webhook signature is invalid");
}

function normalizeDeliveryStatus(payload: Json) {
  const value = `${eventValue(payload, "status", "event_type", "type").toLowerCase()} ${eventValue(payload, "reason", "error", "bounce_code", "reason_code").toLowerCase()}`;
  if (value.includes("bounce") || value.includes("undeliver") || value.includes("invalid recipient")) return "bounced";
  if (value.includes("deliver") || value.includes("read") || value.includes("opened")) return "delivered";
  if (value.includes("fail") || value.includes("reject") || value.includes("error") || value.includes("expired")) return "failed";
  return "sent";
}

function retryAt(attemptNumber: number) {
  return new Date(Date.now() + Math.min(3_600_000, 60_000 * 2 ** Math.max(1, attemptNumber))).toISOString();
}

async function notificationFor(supabase: any, payload: Json) {
  const notificationId = eventValue(payload, "notification_id", "feedback_notification_id");
  const providerReference = eventValue(payload, "provider_reference", "message_id", "provider_message_id");
  if (notificationId) {
    const result = await supabase.from("feedback_notifications").select("*").eq("id", notificationId).maybeSingle();
    if (result.error) throw new Error(result.error.message);
    return result.data;
  }
  if (providerReference) {
    const result = await supabase.from("feedback_notifications").select("*").eq("provider_reference", providerReference).maybeSingle();
    if (result.error) throw new Error(result.error.message);
    return result.data;
  }
  return null;
}

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") return new Response("ok", { headers: { "Cache-Control": "no-store" } });
  if (request.method !== "POST") return reply({ ok: false, error: "POST required" }, 405);
  const rawText = await request.text();
  const raw = new TextEncoder().encode(rawText);
  if (raw.length > MAX_BODY_BYTES) return reply({ ok: false, error: "Webhook body is too large" }, 413);

  try {
    const payload = JSON.parse(rawText) as Json;
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return reply({ ok: false, error: "Webhook payload must be an object" }, 400);
    const channel = channelOf(payload.channel || payload.provider || request.headers.get("x-axiom-provider"));
    if (!channel) return reply({ ok: false, error: "channel must be sms, email or whatsapp" }, 400);
    await verifySignature(request, channel, raw);

    const externalEventId = eventValue(payload, "external_event_id", "event_id", "id", "message_id", "provider_event_id") || request.headers.get("x-axiom-event-id")?.trim() || "";
    if (!externalEventId || externalEventId.length > 160) return reply({ ok: false, error: "external_event_id is required" }, 400);
    const provider = eventValue(payload, "provider") || channel;
    const url = Deno.env.get("SUPABASE_URL");
    const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
    if (!url || !serviceRoleKey) return reply({ ok: false, error: "Supabase service configuration is required", code: "service_configuration_required" }, 503);
    const supabase = createClient(url, serviceRoleKey, { auth: { persistSession: false, autoRefreshToken: false } });
    const notification = await notificationFor(supabase, payload);
    if (!notification) return reply({ ok: true, ignored: true, reason: "notification_not_found" });

    const existing = await supabase.from("feedback_provider_events").select("id, processed_at").eq("provider", provider).eq("external_event_id", externalEventId).maybeSingle();
    if (existing.error) throw new Error(existing.error.message);
    if (existing.data?.processed_at) return reply({ ok: true, status: "duplicate", event_id: existing.data.id });

    let eventId = existing.data?.id;
    if (!eventId) {
      const event = await supabase.from("feedback_provider_events").insert({ organization_id: notification.organization_id, provider, external_event_id: externalEventId, event_type: eventValue(payload, "event_type", "type", "status") || "delivery.receipt", provider_reference: eventValue(payload, "provider_reference", "message_id", "provider_message_id"), payload }).select("id").single();
      if (event.error) {
        if (event.error.code !== "23505") throw new Error(event.error.message);
        const replay = await supabase.from("feedback_provider_events").select("id, processed_at").eq("provider", provider).eq("external_event_id", externalEventId).maybeSingle();
        if (replay.error) throw new Error(replay.error.message);
        if (replay.data?.processed_at) return reply({ ok: true, status: "duplicate", event_id: replay.data.id });
        eventId = replay.data?.id;
      } else {
        eventId = event.data.id;
      }
    }

    const normalized = normalizeDeliveryStatus(payload);
    const latestAttempt = await supabase.from("feedback_delivery_attempts").select("id, attempt_number").eq("notification_id", notification.id).order("attempt_number", { ascending: false }).limit(1).maybeSingle();
    if (latestAttempt.error) throw new Error(latestAttempt.error.message);
    const attemptNumber = Number(latestAttempt.data?.attempt_number || notification.attempts || 1);
    const maxAttempts = Math.max(1, Number(notification.attempt_limit || 5));
    const retryable = normalized === "failed" && payload.retryable !== false && attemptNumber < maxAttempts;
    const nextAttemptAt = retryable ? retryAt(attemptNumber) : null;
    const finalStatus = retryable ? "retrying" : normalized === "failed" ? "dead_letter" : normalized;
    const now = new Date().toISOString();
    const errorCode = eventValue(payload, "bounce_code", "reason_code", "error_code") || (normalized === "failed" ? "provider_delivery_failed" : normalized === "bounced" ? "provider_hard_bounce" : "");
    const errorMessage = eventValue(payload, "error", "reason", "error_message");

    const updated = await supabase.from("feedback_notifications").update({ status: finalStatus, provider_reference: eventValue(payload, "provider_reference", "message_id", "provider_message_id") || notification.provider_reference, last_provider_event_id: externalEventId, bounce_code: normalized === "bounced" ? errorCode : notification.bounce_code || "", error: errorMessage || errorCode, next_attempt_at: nextAttemptAt, dead_lettered_at: finalStatus === "dead_letter" ? now : notification.dead_lettered_at || null, updated_at: now }).eq("id", notification.id).select().single();
    if (updated.error) throw new Error(updated.error.message);

    if (latestAttempt.data?.id) {
      const attempt = await supabase.from("feedback_delivery_attempts").update({ status: finalStatus, provider_event_id: externalEventId, error_code: errorCode, error_message: errorMessage, response_payload: payload, next_attempt_at: nextAttemptAt }).eq("id", latestAttempt.data.id).select().single();
      if (attempt.error) throw new Error(attempt.error.message);
    }
    if (eventId) {
      const marked = await supabase.from("feedback_provider_events").update({ processed_at: now }).eq("id", eventId);
      if (marked.error) throw new Error(marked.error.message);
    }
    return reply({ ok: true, item: updated.data, provider, channel, event_id: externalEventId, status: finalStatus, retry_scheduled: retryable });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error || "Delivery webhook failed");
    const status = message.includes("not configured") ? 503 : message.includes("signature") || message.includes("timestamp") ? 401 : 400;
    return reply({ ok: false, error: message, code: status === 503 ? "webhook_secret_required" : status === 401 ? "invalid_webhook_signature" : "feedback_delivery_webhook_failed" }, status);
  }
});
