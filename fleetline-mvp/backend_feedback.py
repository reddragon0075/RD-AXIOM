"""Configurable post-duty feedback and service-recovery parity slice."""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from backend_domain import DomainError, _assert_owned, _audit, _org, _serialize, _text, new_id, now_iso


ALLOWED_ACTIONS = {"call_customer", "coach_driver", "investigate", "refund_review", "supplier_review", "close_loop"}


def initialize_feedback_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS domain_feedback_forms (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            name TEXT NOT NULL,
            trigger_event TEXT NOT NULL DEFAULT 'duty_completed',
            status TEXT NOT NULL DEFAULT 'draft',
            version INTEGER NOT NULL DEFAULT 1,
            questions_json TEXT NOT NULL DEFAULT '[]',
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, name, version)
        );
        CREATE TABLE IF NOT EXISTS domain_feedback_requests (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            form_id TEXT NOT NULL,
            duty_id TEXT,
            booking_id TEXT,
            recipient TEXT NOT NULL DEFAULT '',
            token_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'sent',
            expires_at TEXT,
            sent_at TEXT,
            submitted_at TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, token_hash)
        );
        CREATE TABLE IF NOT EXISTS domain_feedback_responses (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            request_id TEXT NOT NULL,
            form_id TEXT NOT NULL,
            duty_id TEXT,
            booking_id TEXT,
            rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            answers_json TEXT NOT NULL DEFAULT '{}',
            tags_json TEXT NOT NULL DEFAULT '[]',
            sentiment TEXT NOT NULL DEFAULT 'neutral',
            comment TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, request_id)
        );
        CREATE TABLE IF NOT EXISTS domain_service_recovery_actions (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            response_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            owner_id TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            due_at TEXT,
            notes TEXT NOT NULL DEFAULT '',
            resolved_at TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_feedback_forms_org_status ON domain_feedback_forms(organization_id, status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_feedback_requests_org_status ON domain_feedback_requests(organization_id, status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_feedback_responses_org_created ON domain_feedback_responses(organization_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_recovery_actions_org_status ON domain_service_recovery_actions(organization_id, status, created_at DESC);
        """
    )


def _staff(user):
    if user["role"] not in {"vendor", "corporate"}:
        raise DomainError(403, "Feedback administration is restricted to organization operators", "role_forbidden")


def _questions(payload):
    questions = payload.get("questions") if isinstance(payload.get("questions"), list) else []
    if not questions: raise DomainError(400, "At least one feedback question is required", "validation_error")
    clean = []
    for index, question in enumerate(questions):
        if not isinstance(question, dict): raise DomainError(400, "Each question must be an object", "validation_error")
        key = _text(question, "key", maximum=60).lower()
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,59}", key): raise DomainError(400, "Question keys must be stable identifiers", "validation_error")
        kind = _text(question, "type", "text", 20)
        if kind not in {"rating", "text", "choice", "boolean"}: raise DomainError(400, "Unsupported feedback question type", "validation_error")
        clean.append({"key": key, "label": _text(question, "label", key, 200), "type": kind, "required": bool(question.get("required", False)), "options": question.get("options") if isinstance(question.get("options"), list) else []})
    return clean


def _forms(conn, user, method, route, payload, ip):
    match = re.match(r"^/api/feedback/forms(?:/([^/]+)(?:/(publish|archive))?)?$", route)
    if not match: return None
    org = _org(user); _staff(user)
    form_id, action = match.group(1), match.group(2)
    if method == "GET":
        rows = conn.execute("SELECT * FROM domain_feedback_forms WHERE organization_id = ? ORDER BY created_at DESC", (org,)).fetchall(); return {"ok": True, "items": [_serialize(row, ("questions_json",)) for row in rows]}
    if method == "POST" and not form_id:
        name = _text(payload, "name", maximum=160)
        if not name: raise DomainError(400, "Form name is required", "validation_error")
        questions = _questions(payload); form_id = new_id("feedback_form"); now = now_iso(); version = conn.execute("SELECT COALESCE(MAX(version),0)+1 AS next_version FROM domain_feedback_forms WHERE organization_id = ? AND name = ?", (org, name)).fetchone()["next_version"]
        conn.execute("INSERT INTO domain_feedback_forms(id, organization_id, name, trigger_event, status, version, questions_json, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?)", (form_id, org, name, _text(payload, "trigger_event", "duty_completed", 50), version, json.dumps(questions), user["id"], now, now)); _audit(conn, user, "feedback.form_created", "feedback_form", form_id, ip, {"version": version}); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_feedback_forms WHERE id = ?", (form_id,)).fetchone(), ("questions_json",))}
    if form_id and action and method == "POST":
        row = _assert_owned(conn, "domain_feedback_forms", form_id, org); status = "active" if action == "publish" else "archived"; conn.execute("UPDATE domain_feedback_forms SET status = ?, updated_at = ? WHERE id = ?", (status, now_iso(), form_id)); _audit(conn, user, f"feedback.form_{action}d", "feedback_form", form_id, ip, {"status": status}); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_feedback_forms WHERE id = ?", (row["id"],)).fetchone(), ("questions_json",))}
    raise DomainError(404, "Feedback form route not found", "not_found")


def _create_request(conn, user, payload, ip):
    org = _org(user); _staff(user); form_id = _text(payload, "form_id")
    form = _assert_owned(conn, "domain_feedback_forms", form_id, org)
    if form["status"] != "active": raise DomainError(409, "Feedback form must be published before requesting responses", "form_not_active")
    duty_id = _text(payload, "duty_id") or None
    if duty_id: _assert_owned(conn, "domain_duties", duty_id, org)
    booking_id = _text(payload, "booking_id") or None
    if booking_id: _assert_owned(conn, "domain_bookings", booking_id, org)
    token = new_id("feedback_token"); import hashlib; token_hash = hashlib.sha256(token.encode()).hexdigest(); request_id = new_id("feedback_request"); now = now_iso(); conn.execute("INSERT INTO domain_feedback_requests(id, organization_id, form_id, duty_id, booking_id, recipient, token_hash, expires_at, sent_at, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (request_id, org, form_id, duty_id, booking_id, _text(payload, "recipient", maximum=254), token_hash, _text(payload, "expires_at", maximum=40) or None, now, user["id"], now)); _audit(conn, user, "feedback.request_created", "feedback_request", request_id, ip, {"form_id": form_id, "duty_id": duty_id}); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_feedback_requests WHERE id = ?", (request_id,)).fetchone()), "action_token": token}


def _submit(conn, user, request_id, payload, ip):
    org = _org(user); request = _assert_owned(conn, "domain_feedback_requests", request_id, org)
    if request["status"] == "submitted": return {"ok": True, "idempotent": True, "item": _serialize(conn.execute("SELECT * FROM domain_feedback_responses WHERE request_id = ?", (request_id,)).fetchone(), ("answers_json", "tags_json"))}
    form = _assert_owned(conn, "domain_feedback_forms", request["form_id"], org)
    try: rating = int(payload.get("rating"))
    except (TypeError, ValueError): raise DomainError(400, "rating must be an integer from 1 to 5", "validation_error")
    if rating < 1 or rating > 5: raise DomainError(400, "rating must be an integer from 1 to 5", "validation_error")
    answers = payload.get("answers") if isinstance(payload.get("answers"), dict) else {}; questions = json.loads(form["questions_json"] or "[]")
    missing = [question["key"] for question in questions if question.get("required") and not str(answers.get(question["key"], "")).strip()]
    if missing: raise DomainError(400, f"Required feedback answers are missing: {', '.join(missing)}", "validation_error")
    sentiment = "positive" if rating >= 4 else "negative" if rating <= 2 else "neutral"; response_id = new_id("feedback"); now = now_iso(); tags = payload.get("tags") if isinstance(payload.get("tags"), list) else []
    conn.execute("INSERT INTO domain_feedback_responses(id, organization_id, request_id, form_id, duty_id, booking_id, rating, answers_json, tags_json, sentiment, comment, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (response_id, org, request_id, form["id"], request["duty_id"], request["booking_id"], rating, json.dumps(answers), json.dumps([str(tag)[:60] for tag in tags[:20]]), sentiment, _text(payload, "comment", maximum=4000), now)); conn.execute("UPDATE domain_feedback_requests SET status = 'submitted', submitted_at = ? WHERE id = ?", (now, request_id)); _audit(conn, user, "feedback.submitted", "feedback_response", response_id, ip, {"rating": rating, "sentiment": sentiment}); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_feedback_responses WHERE id = ?", (response_id,)).fetchone(), ("answers_json", "tags_json"))}


def _recovery(conn, user, method, route, payload, ip):
    if route != "/api/feedback/recovery" and not re.match(r"^/api/feedback/recovery/[^/]+/resolve$", route):
        return None
    org = _org(user); _staff(user)
    if route == "/api/feedback/recovery" and method == "GET":
        rows = conn.execute("SELECT * FROM domain_service_recovery_actions WHERE organization_id = ? ORDER BY created_at DESC", (org,)).fetchall(); return {"ok": True, "items": [_serialize(row) for row in rows]}
    if route == "/api/feedback/recovery" and method == "POST":
        response_id = _text(payload, "response_id"); _assert_owned(conn, "domain_feedback_responses", response_id, org); action_type = _text(payload, "action_type", "investigate", 40)
        if action_type not in ALLOWED_ACTIONS: raise DomainError(400, "Unsupported recovery action", "validation_error")
        action_id = new_id("recovery"); now = now_iso(); conn.execute("INSERT INTO domain_service_recovery_actions(id, organization_id, response_id, action_type, owner_id, status, due_at, notes, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?)", (action_id, org, response_id, action_type, _text(payload, "owner_id") or None, _text(payload, "due_at", maximum=40) or None, _text(payload, "notes", maximum=2000), user["id"], now, now)); _audit(conn, user, "feedback.recovery_created", "service_recovery_action", action_id, ip, {"response_id": response_id, "action_type": action_type}); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_service_recovery_actions WHERE id = ?", (action_id,)).fetchone())}
    recovery_match = re.match(r"^/api/feedback/recovery/([^/]+)/resolve$", route)
    if recovery_match and method == "POST":
        row = _assert_owned(conn, "domain_service_recovery_actions", recovery_match.group(1), org); conn.execute("UPDATE domain_service_recovery_actions SET status = 'resolved', resolved_at = ?, notes = ?, updated_at = ? WHERE id = ?", (now_iso(), _text(payload, "notes", maximum=2000), now_iso(), row["id"])); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_service_recovery_actions WHERE id = ?", (row["id"],)).fetchone())}
    return None


def handle_feedback(conn, user, method: str, raw_route: str, payload: dict, ip: str):
    route = urlsplit(raw_route).path.rstrip("/") or "/"
    result = _forms(conn, user, method, route, payload, ip)
    if result is not None: return result
    if route == "/api/feedback/requests" and method == "POST": return _create_request(conn, user, payload, ip)
    submit_match = re.match(r"^/api/feedback/requests/([^/]+)/submit$", route)
    if submit_match and method == "POST": return _submit(conn, user, submit_match.group(1), payload, ip)
    if route == "/api/feedback/responses" and method == "GET":
        org = _org(user); _staff(user); rows = conn.execute("SELECT * FROM domain_feedback_responses WHERE organization_id = ? ORDER BY created_at DESC", (org,)).fetchall(); return {"ok": True, "items": [_serialize(row, ("answers_json", "tags_json")) for row in rows]}
    if route == "/api/feedback/summary" and method == "GET":
        org = _org(user); _staff(user); row = conn.execute("SELECT COUNT(*) AS responses, COALESCE(AVG(rating),0) AS average_rating, SUM(CASE WHEN sentiment = 'negative' THEN 1 ELSE 0 END) AS negative_count FROM domain_feedback_responses WHERE organization_id = ?", (org,)).fetchone(); return {"ok": True, "summary": _serialize(row)}
    result = _recovery(conn, user, method, route, payload, ip)
    if result is not None: return result
    return None
