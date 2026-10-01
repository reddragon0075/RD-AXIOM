"""Tenant-managed communication templates and delivery evidence."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from backend_domain import DomainError, _assert_owned, _audit, _org, _serialize, _text, new_id, now_iso
from provider_adapters import DEFAULT_PROVIDERS

ALLOWED_CHANNELS = {"email", "sms", "whatsapp", "push"}
ALLOWED_PLACEHOLDERS = {"booking_reference", "passenger_name", "driver_name", "vehicle_registration", "invoice_number", "total_paise", "duty_id", "organization_name", "action_url"}
PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")


def initialize_communications_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS communication_templates (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            template_key TEXT NOT NULL,
            name TEXT NOT NULL,
            channel TEXT NOT NULL,
            subject TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL,
            placeholders_json TEXT NOT NULL DEFAULT '[]',
            version INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'active',
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, template_key, channel, version)
        );
        CREATE TABLE IF NOT EXISTS communication_suppressions (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            recipient TEXT NOT NULL,
            channel TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            expires_at TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS communication_dispatches (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            template_id TEXT,
            template_key TEXT NOT NULL,
            channel TEXT NOT NULL,
            recipient TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            provider_reference TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            error_message TEXT NOT NULL DEFAULT '',
            scheduled_at TEXT,
            sent_at TEXT,
            idempotency_key TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS communication_webhook_events (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            external_event_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            processed_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(provider, external_event_id)
        );
        CREATE INDEX IF NOT EXISTS idx_comm_templates_org_key ON communication_templates(organization_id, template_key, channel, status);
        CREATE INDEX IF NOT EXISTS idx_comm_suppressions_org_recipient ON communication_suppressions(organization_id, recipient, channel, status);
        CREATE INDEX IF NOT EXISTS idx_comm_dispatches_org_created ON communication_dispatches(organization_id, created_at DESC);
        """
    )


def _staff(user):
    if user["role"] not in {"vendor", "corporate"}:
        raise DomainError(403, "Communication administration is restricted to organization operators", "role_forbidden")


def _validate_template(payload: dict):
    channel = _text(payload, "channel", "email", 20).lower()
    if channel not in ALLOWED_CHANNELS: raise DomainError(400, "Unsupported communication channel", "validation_error")
    body = _text(payload, "body", maximum=10000)
    if not body: raise DomainError(400, "Template body is required", "validation_error")
    placeholders = sorted(set(PLACEHOLDER_PATTERN.findall(body + " " + _text(payload, "subject", maximum=300))))
    unknown = [name for name in placeholders if name not in ALLOWED_PLACEHOLDERS]
    if unknown: raise DomainError(400, f"Unsupported placeholders: {', '.join(unknown)}", "validation_error")
    return channel, placeholders, body


def _latest_template(conn, org, key, channel):
    return conn.execute("SELECT * FROM communication_templates WHERE organization_id = ? AND template_key = ? AND channel = ? AND status = 'active' ORDER BY version DESC LIMIT 1", (org, key, channel)).fetchone()


def _render(template, variables):
    values = {key: str(variables.get(key, ""))[:1000] for key in ALLOWED_PLACEHOLDERS}
    def replace(match): return values.get(match.group(1), "")
    subject = PLACEHOLDER_PATTERN.sub(replace, template["subject"])
    body = PLACEHOLDER_PATTERN.sub(replace, template["body"])
    return subject, body


def _suppressed(conn, org, recipient, channel):
    now = now_iso()
    return conn.execute("SELECT * FROM communication_suppressions WHERE organization_id = ? AND recipient = ? AND channel = ? AND status = 'active' AND (expires_at IS NULL OR expires_at > ?) ORDER BY created_at DESC LIMIT 1", (org, recipient, channel, now)).fetchone()


def _templates(conn, user, method, route, payload, ip):
    match = re.match(r"^/api/communications/templates(?:/([^/]+))?$", route)
    if not match: return None
    org = _org(user); _staff(user)
    if method == "GET":
        rows = conn.execute("SELECT * FROM communication_templates WHERE organization_id = ? AND status = 'active' ORDER BY template_key, channel, version DESC", (org,)).fetchall()
        return {"ok": True, "items": [_serialize(row, ("placeholders_json",)) for row in rows]}
    if method == "POST" and not match.group(1):
        key = _text(payload, "template_key", maximum=100).lower()
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{1,99}", key): raise DomainError(400, "template_key must be a stable lowercase identifier", "validation_error")
        channel, placeholders, body = _validate_template(payload)
        latest = _latest_template(conn, org, key, channel); version = int(latest["version"] if latest else 0) + 1; now = now_iso(); template_id = new_id("template")
        conn.execute("UPDATE communication_templates SET status = 'superseded', updated_at = ? WHERE organization_id = ? AND template_key = ? AND channel = ? AND status = 'active'", (now, org, key, channel))
        conn.execute("INSERT INTO communication_templates(id, organization_id, template_key, name, channel, subject, body, placeholders_json, version, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (template_id, org, key, _text(payload, "name", key, 160), channel, _text(payload, "subject", maximum=300), body, json.dumps(placeholders), version, user["id"], now, now))
        _audit(conn, user, "communication.template_created", "communication_template", template_id, ip, {"template_key": key, "channel": channel, "version": version})
        return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM communication_templates WHERE id = ?", (template_id,)).fetchone(), ("placeholders_json",))}
    if method == "POST" and match.group(1): raise DomainError(405, "Use the collection route to create a new template version", "method_not_allowed")
    raise DomainError(404, "Communication template route not found", "not_found")


def _dispatch(conn, user, payload, ip):
    org = _org(user); _staff(user); key = _text(payload, "template_key", maximum=100).lower(); channel = _text(payload, "channel", "email", 20).lower(); recipient = _text(payload, "recipient", maximum=254)
    if channel not in ALLOWED_CHANNELS or not recipient: raise DomainError(400, "channel and recipient are required", "validation_error")
    idempotency = _text(payload, "idempotency_key", maximum=160) or None
    if idempotency:
        existing = conn.execute("SELECT * FROM communication_dispatches WHERE organization_id = ? AND idempotency_key = ?", (org, idempotency)).fetchone()
        if existing: return {"ok": True, "item": _serialize(existing, ("payload_json",)), "idempotent": True}
    template = _latest_template(conn, org, key, channel)
    if not template: raise DomainError(404, "Active communication template not found", "template_not_found")
    variables = payload.get("variables") if isinstance(payload.get("variables"), dict) else {}
    subject, body = _render(template, variables)
    suppression = _suppressed(conn, org, recipient, channel); now = now_iso(); status = "suppressed" if suppression else "queued"; provider_reference = ""; error_message = ""
    if not suppression:
        result = DEFAULT_PROVIDERS.messaging.send(channel=channel, recipient=recipient, template=key, variables={**variables, "subject": subject, "body": body}, idempotency_key=idempotency or f"communication:{org}:{key}:{recipient}:{now}")
        status = result.status; provider_reference = result.reference; error_message = "" if result.status in {"queued", "sent", "succeeded"} else "provider_delivery_failed"
    dispatch_id = new_id("dispatch")
    conn.execute("INSERT INTO communication_dispatches(id, organization_id, template_id, template_key, channel, recipient, status, provider_reference, payload_json, error_message, scheduled_at, sent_at, idempotency_key, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (dispatch_id, org, template["id"], key, channel, recipient, status, provider_reference, json.dumps({"variables": variables, "subject": subject, "body": body}), error_message, now, now if status in {"sent", "succeeded"} else None, idempotency, user["id"], now))
    _audit(conn, user, "communication.dispatched", "communication_dispatch", dispatch_id, ip, {"template_key": key, "channel": channel, "status": status, "suppressed": bool(suppression)})
    return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM communication_dispatches WHERE id = ?", (dispatch_id,)).fetchone(), ("payload_json",)), "suppressed": bool(suppression)}


def _suppression(conn, user, method, route, payload, ip):
    if route != "/api/communications/suppressions": return None
    org = _org(user); _staff(user)
    if route == "/api/communications/suppressions" and method == "GET":
        rows = conn.execute("SELECT * FROM communication_suppressions WHERE organization_id = ? ORDER BY created_at DESC", (org,)).fetchall(); return {"ok": True, "items": [_serialize(row) for row in rows]}
    if route == "/api/communications/suppressions" and method == "POST":
        recipient = _text(payload, "recipient", maximum=254); channel = _text(payload, "channel", "email", 20)
        if not recipient or channel not in ALLOWED_CHANNELS: raise DomainError(400, "recipient and supported channel are required", "validation_error")
        suppression_id = new_id("suppression"); now = now_iso(); conn.execute("INSERT INTO communication_suppressions(id, organization_id, recipient, channel, reason, expires_at, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (suppression_id, org, recipient, channel, _text(payload, "reason", "user_requested", 200), _text(payload, "expires_at", maximum=40) or None, user["id"], now)); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM communication_suppressions WHERE id = ?", (suppression_id,)).fetchone())}
    return None


def _deliveries(conn, user, method, route):
    if route != "/api/communications/deliveries" or method != "GET": return None
    org = _org(user); _staff(user)
    rows = conn.execute("SELECT * FROM communication_dispatches WHERE organization_id = ? ORDER BY created_at DESC LIMIT 200", (org,)).fetchall(); return {"ok": True, "items": [_serialize(row, ("payload_json",)) for row in rows]}


def handle_communications(conn, user, method: str, raw_route: str, payload: dict, ip: str):
    route = urlsplit(raw_route).path.rstrip("/") or "/"
    if route == "/api/communications/dispatch" and method == "POST": return _dispatch(conn, user, payload, ip)
    result = _templates(conn, user, method, route, payload, ip)
    if result is not None: return result
    result = _suppression(conn, user, method, route, payload, ip)
    if result is not None: return result
    result = _deliveries(conn, user, method, route)
    if result is not None: return result
    return None
