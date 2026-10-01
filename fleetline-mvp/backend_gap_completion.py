"""Additive Indecab-parity completion contracts.

This module contains the small pieces that were still missing from the local
Axiom Fleet contract surface: employee/passenger booking requests, resource
availability decisions, route/location evidence, device readiness and alert
policies, provider connection health, tokenized auto-collect, expense
forecasting, HRMS/passenger sync and closed-network supplier exchange.

All external calls remain behind ``provider_adapters.DEFAULT_PROVIDERS``.  The
local implementation is deliberately deterministic and mock-first; a
production adapter can replace each provider without changing the tenant,
idempotency or audit contract.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs, urlsplit

from backend_domain import (
    DomainError,
    DEFAULT_PROVIDERS,
    _assert_owned,
    _audit,
    _create_booking,
    _create_duty,
    _json,
    _org,
    _serialize,
    _text,
    new_id,
    now_iso,
)


CHANNELS = {"sms", "whatsapp", "email", "push"}
PROVIDER_TYPES = {"maps", "messaging", "telephony", "payments", "einvoice", "hrms", "gps", "storage"}
SYNC_TYPES = {"hrms", "passenger_lifecycle", "corporate_provisioning"}


def initialize_gap_completion_schema(conn) -> None:
    """Create only additive tables; safe to run on an existing local database."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS gap_passenger_booking_requests (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, requester_user_id TEXT NOT NULL,
            passenger_name TEXT NOT NULL, passenger_phone TEXT NOT NULL DEFAULT '', passenger_email TEXT NOT NULL DEFAULT '',
            customer_id TEXT, scheduled_at TEXT NOT NULL, pickup_json TEXT NOT NULL DEFAULT '{}', dropoff_json TEXT NOT NULL DEFAULT '{}',
            duty_type TEXT NOT NULL DEFAULT 'local', notes TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending',
            booking_id TEXT, decision_note TEXT NOT NULL DEFAULT '', decision_by TEXT, decision_at TEXT,
            idempotency_key TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE INDEX IF NOT EXISTS idx_gap_booking_requests_org_status ON gap_passenger_booking_requests(organization_id, status, scheduled_at);

        CREATE TABLE IF NOT EXISTS gap_route_logs (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, duty_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'recording', tracking_mode TEXT NOT NULL DEFAULT 'background',
            provider TEXT NOT NULL DEFAULT 'mock_gps', started_at TEXT NOT NULL, stopped_at TEXT,
            summary_json TEXT NOT NULL DEFAULT '{}', idempotency_key TEXT, created_by TEXT, created_at TEXT NOT NULL,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS gap_route_points (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, route_log_id TEXT NOT NULL, duty_id TEXT NOT NULL,
            recorded_at TEXT NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL, accuracy_m REAL,
            speed_kph REAL, heading REAL, battery_pct REAL, source TEXT NOT NULL DEFAULT 'driver_background',
            idempotency_key TEXT, created_at TEXT NOT NULL, UNIQUE(organization_id, idempotency_key)
        );
        CREATE INDEX IF NOT EXISTS idx_gap_route_points_duty ON gap_route_points(organization_id, duty_id, recorded_at);

        CREATE TABLE IF NOT EXISTS gap_location_shares (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, duty_id TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE, recipient TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
            expires_at TEXT NOT NULL, last_accessed_at TEXT, created_by TEXT, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_gap_location_shares_duty ON gap_location_shares(organization_id, duty_id, status);

        CREATE TABLE IF NOT EXISTS gap_driver_alert_policies (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, name TEXT NOT NULL, alert_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'warning', threshold_json TEXT NOT NULL DEFAULT '{}', channels_json TEXT NOT NULL DEFAULT '["push"]',
            locale_json TEXT NOT NULL DEFAULT '{}', enabled INTEGER NOT NULL DEFAULT 1, created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(organization_id, name)
        );
        CREATE TABLE IF NOT EXISTS gap_driver_alert_events (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, duty_id TEXT NOT NULL, policy_id TEXT,
            alert_type TEXT NOT NULL, severity TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
            payload_json TEXT NOT NULL DEFAULT '{}', occurred_at TEXT NOT NULL, acknowledged_by TEXT, acknowledged_at TEXT,
            resolved_by TEXT, resolved_at TEXT, idempotency_key TEXT, created_by TEXT, UNIQUE(organization_id, idempotency_key)
        );
        CREATE INDEX IF NOT EXISTS idx_gap_alerts_duty_status ON gap_driver_alert_events(organization_id, duty_id, status, occurred_at);

        CREATE TABLE IF NOT EXISTS gap_device_readiness (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, user_id TEXT NOT NULL, device_id TEXT NOT NULL,
            platform TEXT NOT NULL DEFAULT 'android', app_version TEXT NOT NULL DEFAULT '', os_version TEXT NOT NULL DEFAULT '',
            permissions_json TEXT NOT NULL DEFAULT '{}', readiness_status TEXT NOT NULL DEFAULT 'blocked', blockers_json TEXT NOT NULL DEFAULT '[]',
            push_token_present INTEGER NOT NULL DEFAULT 0, checked_at TEXT NOT NULL, UNIQUE(organization_id, user_id, device_id)
        );
        CREATE TABLE IF NOT EXISTS gap_provider_connections (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, provider_type TEXT NOT NULL, name TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'mock', status TEXT NOT NULL DEFAULT 'draft', credential_ref TEXT NOT NULL DEFAULT '',
            config_json TEXT NOT NULL DEFAULT '{}', capabilities_json TEXT NOT NULL DEFAULT '[]', last_tested_at TEXT,
            last_error TEXT NOT NULL DEFAULT '', created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(organization_id, provider_type, name)
        );
        CREATE INDEX IF NOT EXISTS idx_gap_provider_connections_org ON gap_provider_connections(organization_id, provider_type, status);

        CREATE TABLE IF NOT EXISTS gap_payment_authorizations (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, customer_id TEXT, payer_email TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT 'mock_payment', token_fingerprint TEXT NOT NULL, token_last4 TEXT NOT NULL DEFAULT '',
            max_amount_paise INTEGER NOT NULL DEFAULT 0, currency TEXT NOT NULL DEFAULT 'INR', status TEXT NOT NULL DEFAULT 'active',
            authorized_at TEXT NOT NULL, expires_at TEXT, idempotency_key TEXT, created_by TEXT, created_at TEXT NOT NULL,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS gap_auto_collect_attempts (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, authorization_id TEXT NOT NULL, invoice_id TEXT NOT NULL,
            amount_paise INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'queued', provider_reference TEXT NOT NULL DEFAULT '',
            provider_payload_json TEXT NOT NULL DEFAULT '{}', error_message TEXT NOT NULL DEFAULT '', idempotency_key TEXT,
            attempted_at TEXT NOT NULL, created_by TEXT, UNIQUE(organization_id, idempotency_key)
        );
        CREATE INDEX IF NOT EXISTS idx_gap_collect_org_status ON gap_auto_collect_attempts(organization_id, status, attempted_at);

        CREATE TABLE IF NOT EXISTS gap_invoice_automation_policies (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, name TEXT NOT NULL, customer_id TEXT,
            trigger_event TEXT NOT NULL DEFAULT 'duty_completed', issue_einvoice INTEGER NOT NULL DEFAULT 0,
            collect_payment INTEGER NOT NULL DEFAULT 0, send_channel TEXT NOT NULL DEFAULT 'email', payment_terms_days INTEGER NOT NULL DEFAULT 7,
            enabled INTEGER NOT NULL DEFAULT 1, created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(organization_id, name)
        );
        CREATE TABLE IF NOT EXISTS gap_invoice_automation_runs (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, policy_id TEXT, duty_id TEXT NOT NULL,
            invoice_id TEXT, status TEXT NOT NULL DEFAULT 'queued', result_json TEXT NOT NULL DEFAULT '{}',
            idempotency_key TEXT, created_by TEXT, created_at TEXT NOT NULL, UNIQUE(organization_id, idempotency_key)
        );

        CREATE TABLE IF NOT EXISTS gap_custom_field_values (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, field_id TEXT NOT NULL, entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL, value_json TEXT NOT NULL DEFAULT 'null', updated_by TEXT, updated_at TEXT NOT NULL,
            UNIQUE(organization_id, field_id, entity_type, entity_id)
        );
        CREATE TABLE IF NOT EXISTS gap_sync_runs (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, sync_type TEXT NOT NULL, provider TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'accepted', records_received INTEGER NOT NULL DEFAULT 0, records_applied INTEGER NOT NULL DEFAULT 0,
            provider_reference TEXT NOT NULL DEFAULT '', result_json TEXT NOT NULL DEFAULT '{}', idempotency_key TEXT,
            created_by TEXT, created_at TEXT NOT NULL, UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS gap_supplier_exchange_jobs (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, network_program_id TEXT NOT NULL, supplier_id TEXT NOT NULL,
            direction TEXT NOT NULL DEFAULT 'outbound', visibility TEXT NOT NULL DEFAULT 'invite_only', status TEXT NOT NULL DEFAULT 'queued',
            qualification_json TEXT NOT NULL DEFAULT '{}', contract_json TEXT NOT NULL DEFAULT '{}', rate_card_json TEXT NOT NULL DEFAULT '{}',
            payload_json TEXT NOT NULL DEFAULT '{}', idempotency_key TEXT, created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE INDEX IF NOT EXISTS idx_gap_exchange_org_status ON gap_supplier_exchange_jobs(organization_id, network_program_id, status);

        CREATE TABLE IF NOT EXISTS gap_expense_budgets (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, period_key TEXT NOT NULL, customer_id TEXT,
            budget_paise INTEGER NOT NULL CHECK(budget_paise >= 0), alert_threshold_bps INTEGER NOT NULL DEFAULT 8000,
            status TEXT NOT NULL DEFAULT 'active', created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(organization_id, period_key, customer_id)
        );
        """
    )


def _staff(user) -> None:
    if user["role"] not in {"vendor", "corporate"}:
        raise DomainError(403, "This action requires an organization operator", "role_forbidden")


def _json_value(value, fallback):
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError):
        return fallback


def _limit(raw_route: str, default: int = 100) -> int:
    try:
        value = int((parse_qs(urlsplit(raw_route).query).get("limit") or [default])[0])
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, 500))


def _idem(payload: dict) -> str | None:
    value = _text(payload, "idempotency_key", maximum=160).strip()
    return value or None


def _owned_duty(conn, user, duty_id):
    return _assert_owned(conn, "domain_duties", duty_id, _org(user))


def _driver_or_operator(conn, user, duty_id):
    duty = _owned_duty(conn, user, duty_id)
    if user["role"] == "driver":
        match = conn.execute(
            "SELECT id FROM domain_drivers WHERE id = ? AND user_id = ? AND organization_id = ?",
            (duty["driver_id"], user["id"], _org(user)),
        ).fetchone()
        if not match:
            raise DomainError(403, "This duty is not assigned to the signed-in driver", "duty_assignment_required")
    return duty


def _location(value, key, required=True):
    try:
        number = float(value)
    except (TypeError, ValueError):
        if required:
            raise DomainError(400, f"{key} must be a number", "validation_error")
        return None
    if key == "latitude" and not -90 <= number <= 90:
        raise DomainError(400, "latitude must be between -90 and 90", "validation_error")
    if key == "longitude" and not -180 <= number <= 180:
        raise DomainError(400, "longitude must be between -180 and 180", "validation_error")
    return number


def _request_payload(row):
    return {
        **_serialize(row, ("pickup_json", "dropoff_json")),
        "pickup": _json_value(row["pickup_json"], {}),
        "dropoff": _json_value(row["dropoff_json"], {}),
    }


def _safe_authorization(row):
    item = _serialize(row)
    item.pop("token_fingerprint", None)
    return item


def _booking_requests(conn, user, method, route, payload, ip):
    org = _org(user)
    if route in {"/api/passenger/booking-requests", "/api/passenger/book-for-others"}:
        if method == "GET":
            rows = conn.execute(
                "SELECT * FROM gap_passenger_booking_requests WHERE organization_id = ? ORDER BY created_at DESC LIMIT ?",
                (org, _limit(route)),
            ).fetchall()
            return {"ok": True, "items": [_request_payload(row) for row in rows]}
        if method != "POST":
            raise DomainError(405, "Use GET or POST for booking requests", "method_not_allowed")
        _staff(user)
        passenger_name = _text(payload, "passenger_name", maximum=160)
        scheduled_at = _text(payload, "scheduled_at", maximum=40)
        pickup = payload.get("pickup") if isinstance(payload.get("pickup"), dict) else {"label": _text(payload, "pickup", maximum=300)}
        dropoff = payload.get("dropoff") if isinstance(payload.get("dropoff"), dict) else {"label": _text(payload, "dropoff", maximum=300)}
        if not passenger_name or not scheduled_at or not pickup.get("label") and not pickup.get("latitude"):
            raise DomainError(400, "passenger_name, scheduled_at and pickup are required", "validation_error")
        if not dropoff.get("label") and not dropoff.get("latitude"):
            raise DomainError(400, "dropoff is required", "validation_error")
        key = _idem(payload)
        if key:
            existing = conn.execute(
                "SELECT * FROM gap_passenger_booking_requests WHERE organization_id = ? AND idempotency_key = ?",
                (org, key),
            ).fetchone()
            if existing:
                return {"ok": True, "item": _request_payload(existing), "idempotent": True}
        request_id = new_id("passenger_request")
        now = now_iso()
        conn.execute(
            """INSERT INTO gap_passenger_booking_requests(
                id, organization_id, requester_user_id, passenger_name, passenger_phone, passenger_email, customer_id,
                scheduled_at, pickup_json, dropoff_json, duty_type, notes, idempotency_key, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                request_id, org, user["id"], passenger_name, _text(payload, "passenger_phone", maximum=40),
                _text(payload, "passenger_email", maximum=254).lower(), _text(payload, "customer_id") or None,
                scheduled_at, json.dumps(pickup), json.dumps(dropoff), _text(payload, "duty_type", "local", 40),
                _text(payload, "notes", maximum=1000), key, now, now,
            ),
        )
        _audit(conn, user, "passenger.booking_requested", "passenger_booking_request", request_id, ip, {"idempotency_key": key})
        return {"ok": True, "item": _request_payload(conn.execute("SELECT * FROM gap_passenger_booking_requests WHERE id = ?", (request_id,)).fetchone())}
    action = re.match(r"^/api/passenger/booking-requests/([^/]+)/(approve|reject|cancel)$", route)
    if action and method == "POST":
        _staff(user)
        row = conn.execute("SELECT * FROM gap_passenger_booking_requests WHERE id = ? AND organization_id = ?", (action.group(1), org)).fetchone()
        if not row:
            raise DomainError(404, "Passenger booking request not found", "not_found")
        operation = action.group(2)
        if row["status"] != "pending":
            return {"ok": True, "item": _request_payload(row), "idempotent": True}
        booking_id = row["booking_id"]
        if operation == "approve":
            result = _create_booking(
                conn,
                user,
                {
                    "customer_id": row["customer_id"] or "",
                    "passenger_name": row["passenger_name"],
                    "passenger_phone": row["passenger_phone"],
                    "passenger_email": row["passenger_email"],
                    "scheduled_at": row["scheduled_at"],
                    "pickup": _json_value(row["pickup_json"], {}),
                    "dropoff": _json_value(row["dropoff_json"], {}),
                    "duty_type": row["duty_type"],
                    "notes": row["notes"],
                    "booking_reference": _text(payload, "booking_reference", f"PASS-{request_id_short(row['id'])}", 80),
                },
                ip,
            )
            booking_id = result["item"]["id"]
        status = "approved" if operation == "approve" else operation + "d"
        now = now_iso()
        conn.execute(
            "UPDATE gap_passenger_booking_requests SET status = ?, booking_id = ?, decision_note = ?, decision_by = ?, decision_at = ?, updated_at = ? WHERE id = ?",
            (status, booking_id, _text(payload, "decision_note", maximum=500), user["id"], now, now, row["id"]),
        )
        _audit(conn, user, f"passenger.booking_request_{operation}d", "passenger_booking_request", row["id"], ip, {"booking_id": booking_id})
        return {"ok": True, "item": _request_payload(conn.execute("SELECT * FROM gap_passenger_booking_requests WHERE id = ?", (row["id"],)).fetchone()), "booking_id": booking_id}
    return None


def request_id_short(value: str) -> str:
    return value.split("_")[-1][:8].upper()


def _availability(conn, user, method, route, payload, ip):
    if route != "/api/availability/optimize":
        return None
    _staff(user)
    if method != "POST":
        raise DomainError(405, "Use POST to evaluate availability", "method_not_allowed")
    org = _org(user)
    booking_id = _text(payload, "booking_id")
    booking = _assert_owned(conn, "domain_bookings", booking_id, org) if booking_id else None
    requested_type = _text(payload, "vehicle_type", "", 40).lower()
    city = _text(payload, "city", "", 120).lower()
    seats = int(payload.get("passenger_count") or 1)
    vehicle_query = "SELECT * FROM domain_vehicles WHERE organization_id = ? AND status IN ('available', 'active')"
    values = [org]
    if requested_type:
        vehicle_query += " AND lower(vehicle_type) = ?"; values.append(requested_type)
    if city:
        vehicle_query += " AND (lower(city) = ? OR city = '')"; values.append(city)
    vehicles = conn.execute(vehicle_query, values).fetchall()
    drivers = conn.execute("SELECT * FROM domain_drivers WHERE organization_id = ? AND status IN ('available', 'active')", (org,)).fetchall()
    candidates = []
    for vehicle in vehicles:
        if int(vehicle["seating_capacity"] or 0) < seats:
            continue
        for driver in drivers:
            score = 100
            reasons = []
            if city and driver["city"] and driver["city"].lower() != city:
                score -= 20; reasons.append("driver_city_mismatch")
            if vehicle["city"] and city and vehicle["city"].lower() == city:
                score += 10; reasons.append("vehicle_city_match")
            lock_conflict = False
            if booking and booking["scheduled_at"]:
                lock_conflict = bool(conn.execute(
                    "SELECT 1 FROM domain_capacity_locks WHERE organization_id = ? AND status = 'held' AND resource_type = 'vehicle' AND resource_id = ? AND starts_at <= ? AND ends_at >= ? LIMIT 1",
                    (org, vehicle["id"], booking["scheduled_at"], booking["scheduled_at"]),
                ).fetchone())
            if lock_conflict:
                continue
            candidates.append({"driver_id": driver["id"], "driver_name": driver["full_name"], "vehicle_id": vehicle["id"], "registration_number": vehicle["registration_number"], "vehicle_type": vehicle["vehicle_type"], "score": score, "reasons": reasons})
    candidates.sort(key=lambda item: (-item["score"], item["registration_number"]))
    selected = candidates[0] if candidates else None
    result = {"ok": True, "booking_id": booking_id, "candidates": candidates[:50], "selected": selected, "status": "available" if selected else "unavailable", "contract": {"provider": "local_capacity", "mock": True}}
    if selected and payload.get("auto_assign") and booking:
        existing = conn.execute("SELECT id FROM domain_duties WHERE organization_id = ? AND booking_id = ? AND status NOT IN ('cancelled', 'completed')", (org, booking_id)).fetchone()
        if existing:
            result["duty_id"] = existing["id"]; result["auto_assigned"] = False; result["reason"] = "duty_already_exists"
        else:
            duty = _create_duty(conn, user, {"booking_id": booking_id, "driver_id": selected["driver_id"], "vehicle_id": selected["vehicle_id"], "reporting_at": booking["scheduled_at"] or ""}, ip)
            result["duty_id"] = duty["item"]["id"]; result["auto_assigned"] = True
    return result


def _haversine(a, b):
    radius = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = math.radians(b[0] - a[0]); dl = math.radians(b[1] - a[1])
    value = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * (2 * math.atan2(math.sqrt(value), math.sqrt(max(0, 1 - value))))


def _route_logs(conn, user, method, route, payload, ip):
    match = re.match(r"^/api/duties/([^/]+)/route-log(?:/(start|stop))?$", route)
    if not match:
        return None
    duty_id, action = match.group(1), match.group(2)
    duty = _driver_or_operator(conn, user, duty_id)
    org = _org(user)
    if method == "GET":
        log = conn.execute("SELECT * FROM gap_route_logs WHERE organization_id = ? AND duty_id = ? ORDER BY created_at DESC LIMIT 1", (org, duty_id)).fetchone()
        points = conn.execute("SELECT * FROM gap_route_points WHERE organization_id = ? AND duty_id = ? ORDER BY recorded_at", (org, duty_id)).fetchall()
        return {"ok": True, "item": _serialize(log, ("summary_json",)) if log else None, "points": [_serialize(point) for point in points]}
    if method != "POST":
        raise DomainError(405, "Use GET or POST for route logs", "method_not_allowed")
    if action == "start" or (not action and not payload.get("points")):
        existing = conn.execute("SELECT * FROM gap_route_logs WHERE organization_id = ? AND duty_id = ? AND status = 'recording' ORDER BY created_at DESC LIMIT 1", (org, duty_id)).fetchone()
        if existing:
            return {"ok": True, "item": _serialize(existing, ("summary_json",)), "idempotent": True}
        log_id = new_id("route_log"); now = now_iso()
        conn.execute("INSERT INTO gap_route_logs(id, organization_id, duty_id, tracking_mode, provider, started_at, idempotency_key, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (log_id, org, duty_id, _text(payload, "tracking_mode", "background", 30), _text(payload, "provider", "mock_gps", 50), _text(payload, "started_at", now, 40), _idem(payload), user["id"], now))
        _audit(conn, user, "route_log.started", "route_log", log_id, ip, {"duty_id": duty_id})
        return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM gap_route_logs WHERE id = ?", (log_id,)).fetchone(), ("summary_json",))}
    log = conn.execute("SELECT * FROM gap_route_logs WHERE organization_id = ? AND duty_id = ? AND status = 'recording' ORDER BY created_at DESC LIMIT 1", (org, duty_id)).fetchone()
    if not log:
        raise DomainError(409, "Start a route log before sending points", "route_log_not_started")
    points = payload.get("points") if isinstance(payload.get("points"), list) else [payload]
    inserted = 0
    for point in points:
        if not isinstance(point, dict):
            raise DomainError(400, "Each route point must be an object", "validation_error")
        lat = _location(point.get("latitude"), "latitude"); lon = _location(point.get("longitude"), "longitude")
        key = _text(point, "idempotency_key", maximum=160) or None
        if key and conn.execute("SELECT id FROM gap_route_points WHERE organization_id = ? AND idempotency_key = ?", (org, key)).fetchone():
            continue
        point_id = new_id("route_point")
        conn.execute("INSERT INTO gap_route_points(id, organization_id, route_log_id, duty_id, recorded_at, latitude, longitude, accuracy_m, speed_kph, heading, battery_pct, source, idempotency_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (point_id, org, log["id"], duty_id, _text(point, "recorded_at", now_iso(), 40), lat, lon, point.get("accuracy_m"), point.get("speed_kph"), point.get("heading"), point.get("battery_pct"), _text(point, "source", "driver_background", 40), key, now_iso()))
        inserted += 1
        # Keep the established duty tracking table populated for existing map and audit consumers.
        track_key = f"gap:{log['id']}:{key or point_id}"
        if not conn.execute("SELECT 1 FROM domain_track_points WHERE organization_id = ? AND idempotency_key = ?", (org, track_key)).fetchone():
            conn.execute("INSERT INTO domain_track_points(id, organization_id, duty_id, recorded_at, latitude, longitude, accuracy_m, battery_pct, source, idempotency_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (new_id("track"), org, duty_id, _text(point, "recorded_at", now_iso(), 40), lat, lon, point.get("accuracy_m"), point.get("battery_pct"), _text(point, "source", "driver_background", 40), track_key, now_iso()))
    if action == "stop" or payload.get("stop"):
        all_points = conn.execute("SELECT latitude, longitude FROM gap_route_points WHERE route_log_id = ? ORDER BY recorded_at", (log["id"],)).fetchall()
        distance = sum(_haversine((all_points[index - 1]["latitude"], all_points[index - 1]["longitude"]), (row["latitude"], row["longitude"])) for index, row in enumerate(all_points) if index)
        summary = {"point_count": len(all_points), "distance_km": round(distance, 3), "last_point": dict(all_points[-1]) if all_points else None, "provider": log["provider"], "mock": log["provider"].startswith("mock")}
        conn.execute("UPDATE gap_route_logs SET status = 'completed', stopped_at = ?, summary_json = ? WHERE id = ?", (now_iso(), json.dumps(summary), log["id"]))
        _audit(conn, user, "route_log.stopped", "route_log", log["id"], ip, summary)
    item = conn.execute("SELECT * FROM gap_route_logs WHERE id = ?", (log["id"],)).fetchone()
    return {"ok": True, "item": _serialize(item, ("summary_json",)), "inserted_points": inserted}


def _location_share(conn, user, method, route, payload, ip):
    match = re.match(r"^/api/duties/([^/]+)/location-share$", route)
    if not match:
        return None
    if method == "GET":
        _driver_or_operator(conn, user, match.group(1))
        rows = conn.execute("SELECT * FROM gap_location_shares WHERE organization_id = ? AND duty_id = ? ORDER BY created_at DESC", (_org(user), match.group(1))).fetchall()
        return {"ok": True, "items": [_serialize(row) for row in rows]}
    if method != "POST":
        raise DomainError(405, "Use POST to create a passenger location share", "method_not_allowed")
    _driver_or_operator(conn, user, match.group(1))
    raw = secrets.token_urlsafe(26); token_hash = hashlib.sha256(raw.encode()).hexdigest(); now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=max(1, min(int(payload.get("expires_hours") or 12), 72)))
    share_id = new_id("location_share")
    conn.execute("INSERT INTO gap_location_shares(id, organization_id, duty_id, token_hash, recipient, expires_at, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (share_id, _org(user), match.group(1), token_hash, _text(payload, "recipient", maximum=254), expires.replace(microsecond=0).isoformat().replace("+00:00", "Z"), user["id"], now_iso()))
    _audit(conn, user, "passenger.location_share_created", "location_share", share_id, ip, {"duty_id": match.group(1)})
    return {"ok": True, "item": {"id": share_id, "url": f"/api/location-shares/{raw}", "expires_at": expires.replace(microsecond=0).isoformat().replace("+00:00", "Z"), "status": "active"}}


def handle_gap_public(conn, method, raw_route, payload, ip):
    route = urlsplit(raw_route).path.rstrip("/") or "/"
    match = re.match(r"^/api/location-shares/([^/]+)$", route)
    if not match or method != "GET":
        return None
    token_hash = hashlib.sha256(match.group(1).encode()).hexdigest()
    row = conn.execute("SELECT * FROM gap_location_shares WHERE token_hash = ? AND status = 'active' AND expires_at > ?", (token_hash, now_iso())).fetchone()
    if not row:
        raise DomainError(404, "Location share is invalid or expired", "not_found")
    conn.execute("UPDATE gap_location_shares SET last_accessed_at = ? WHERE id = ?", (now_iso(), row["id"]))
    duty = conn.execute("SELECT * FROM domain_duties WHERE id = ? AND organization_id = ?", (row["duty_id"], row["organization_id"])).fetchone()
    booking = conn.execute("SELECT * FROM domain_bookings WHERE id = ? AND organization_id = ?", (duty["booking_id"], row["organization_id"])).fetchone() if duty else None
    point = conn.execute("SELECT * FROM gap_route_points WHERE organization_id = ? AND duty_id = ? ORDER BY recorded_at DESC LIMIT 1", (row["organization_id"], row["duty_id"])).fetchone()
    return {"ok": True, "share": {"id": row["id"], "duty_id": row["duty_id"], "expires_at": row["expires_at"], "status": row["status"]}, "trip": {"duty_status": duty["status"] if duty else "unknown", "booking_reference": booking["booking_reference"] if booking else "", "passenger_name": booking["passenger_name"] if booking else "", "last_location": _serialize(point) if point else None}}


def _alerts_and_readiness(conn, user, method, route, payload, ip):
    org = _org(user)
    policy_match = re.match(r"^/api/driver-alert-policies(?:/([^/]+))?$", route)
    if policy_match:
        _staff(user)
        if method == "GET":
            rows = conn.execute("SELECT * FROM gap_driver_alert_policies WHERE organization_id = ? ORDER BY name", (org,)).fetchall()
            return {"ok": True, "items": [_serialize(row, ("threshold_json", "channels_json", "locale_json")) for row in rows]}
        if method != "POST": raise DomainError(405, "Use GET or POST for driver alert policies", "method_not_allowed")
        name = _text(payload, "name", maximum=120); alert_type = _text(payload, "alert_type", maximum=60)
        if not name or not alert_type: raise DomainError(400, "name and alert_type are required", "validation_error")
        policy_id = new_id("alert_policy"); now = now_iso()
        conn.execute("INSERT INTO gap_driver_alert_policies(id, organization_id, name, alert_type, severity, threshold_json, channels_json, locale_json, enabled, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (policy_id, org, name, alert_type, _text(payload, "severity", "warning", 20), json.dumps(payload.get("threshold") if isinstance(payload.get("threshold"), dict) else {}), json.dumps(payload.get("channels") if isinstance(payload.get("channels"), list) else ["push"]), json.dumps(payload.get("localized_guidance") if isinstance(payload.get("localized_guidance"), dict) else {}), 1 if payload.get("enabled", True) else 0, user["id"], now, now))
        _audit(conn, user, "driver.alert_policy_created", "driver_alert_policy", policy_id, ip, {})
        return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM gap_driver_alert_policies WHERE id = ?", (policy_id,)).fetchone(), ("threshold_json", "channels_json", "locale_json"))}
    alert_match = re.match(r"^/api/duties/([^/]+)/driver-alerts(?:/(acknowledge|resolve))?$", route)
    if alert_match:
        duty = _driver_or_operator(conn, user, alert_match.group(1)); duty_id = duty["id"]; action = alert_match.group(2)
        if method == "GET":
            rows = conn.execute("SELECT * FROM gap_driver_alert_events WHERE organization_id = ? AND duty_id = ? ORDER BY occurred_at DESC", (org, duty_id)).fetchall()
            return {"ok": True, "items": [_serialize(row, ("payload_json",)) for row in rows]}
        if method != "POST": raise DomainError(405, "Use GET or POST for driver alerts", "method_not_allowed")
        if action:
            alert_id = _text(payload, "alert_id")
            row = conn.execute("SELECT * FROM gap_driver_alert_events WHERE id = ? AND organization_id = ? AND duty_id = ?", (alert_id, org, duty_id)).fetchone()
            if not row: raise DomainError(404, "Driver alert not found", "not_found")
            if action == "acknowledge":
                conn.execute("UPDATE gap_driver_alert_events SET status = 'acknowledged', acknowledged_by = ?, acknowledged_at = ? WHERE id = ?", (user["id"], now_iso(), alert_id))
            else:
                conn.execute("UPDATE gap_driver_alert_events SET status = 'resolved', resolved_by = ?, resolved_at = ? WHERE id = ?", (user["id"], now_iso(), alert_id))
            _audit(conn, user, f"driver.alert_{action}d", "driver_alert", alert_id, ip, {})
            return {"ok": True, "status": "acknowledged" if action == "acknowledge" else "resolved", "id": alert_id}
        alert_type = _text(payload, "alert_type", "operational", 60); key = _idem(payload)
        if key:
            existing = conn.execute("SELECT * FROM gap_driver_alert_events WHERE organization_id = ? AND idempotency_key = ?", (org, key)).fetchone()
            if existing: return {"ok": True, "item": _serialize(existing, ("payload_json",)), "idempotent": True}
        policy = conn.execute("SELECT * FROM gap_driver_alert_policies WHERE organization_id = ? AND alert_type = ? AND enabled = 1 ORDER BY created_at DESC LIMIT 1", (org, alert_type)).fetchone()
        severity = _text(payload, "severity", policy["severity"] if policy else "warning", 20)
        alert_id = new_id("driver_alert"); now = now_iso()
        conn.execute("INSERT INTO gap_driver_alert_events(id, organization_id, duty_id, policy_id, alert_type, severity, payload_json, occurred_at, idempotency_key, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (alert_id, org, duty_id, policy["id"] if policy else None, alert_type, severity, json.dumps(payload), now, key, user["id"]))
        # The established push queue is the durable local representation of a push notification.
        driver = conn.execute("SELECT user_id FROM domain_drivers WHERE id = ? AND organization_id = ?", (duty["driver_id"], org)).fetchone() if duty["driver_id"] else None
        if driver and driver["user_id"]:
            from backend_domain import _queue_push_notification
            _queue_push_notification(conn, org, driver["user_id"], "driver_alert", {"duty_id": duty_id, "alert_id": alert_id, "severity": severity, "alert_type": alert_type})
        _audit(conn, user, "driver.alert_created", "driver_alert", alert_id, ip, {"duty_id": duty_id, "severity": severity})
        return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM gap_driver_alert_events WHERE id = ?", (alert_id,)).fetchone(), ("payload_json",))}
    if route == "/api/driver/device-readiness":
        if method == "GET":
            rows = conn.execute("SELECT * FROM gap_device_readiness WHERE organization_id = ? AND user_id = ? ORDER BY checked_at DESC", (org, user["id"])).fetchall()
            return {"ok": True, "items": [_serialize(row, ("permissions_json", "blockers_json")) for row in rows]}
        if method != "POST": raise DomainError(405, "Use GET or POST for device readiness", "method_not_allowed")
        device_id = _text(payload, "device_id", maximum=160)
        if not device_id: raise DomainError(400, "device_id is required", "validation_error")
        permissions = payload.get("permissions") if isinstance(payload.get("permissions"), dict) else {}
        requirements = {"push": bool(permissions.get("push")), "background_location": bool(permissions.get("background_location")), "media": bool(permissions.get("media")), "notifications": bool(permissions.get("notifications"))}
        blockers = [key for key, ready in requirements.items() if not ready]
        readiness = "ready" if not blockers else "blocked"
        now = now_iso(); readiness_id = new_id("device_readiness")
        conn.execute("INSERT INTO gap_device_readiness(id, organization_id, user_id, device_id, platform, app_version, os_version, permissions_json, readiness_status, blockers_json, push_token_present, checked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(organization_id, user_id, device_id) DO UPDATE SET platform = excluded.platform, app_version = excluded.app_version, os_version = excluded.os_version, permissions_json = excluded.permissions_json, readiness_status = excluded.readiness_status, blockers_json = excluded.blockers_json, push_token_present = excluded.push_token_present, checked_at = excluded.checked_at", (readiness_id, org, user["id"], device_id, _text(payload, "platform", "android", 30), _text(payload, "app_version", maximum=40), _text(payload, "os_version", maximum=40), json.dumps(requirements), readiness, json.dumps(blockers), 1 if payload.get("push_token") else 0, now))
        _audit(conn, user, "driver.device_readiness_checked", "device", device_id, ip, {"status": readiness, "blockers": blockers})
        return {"ok": True, "status": readiness, "blockers": blockers, "item": _serialize(conn.execute("SELECT * FROM gap_device_readiness WHERE organization_id = ? AND user_id = ? AND device_id = ?", (org, user["id"], device_id)).fetchone(), ("permissions_json", "blockers_json"))}
    return None


def _provider_connections(conn, user, method, route, payload, ip):
    org = _org(user)
    match = re.match(r"^/api/provider-connections(?:/([^/]+)(?:/(test))?)?$", route)
    if not match: return None
    _staff(user)
    connection_id, action = match.group(1), match.group(2)
    if method == "GET":
        rows = conn.execute("SELECT * FROM gap_provider_connections WHERE organization_id = ? ORDER BY provider_type, name", (org,)).fetchall()
        return {"ok": True, "items": [_serialize(row, ("config_json", "capabilities_json")) for row in rows]}
    if action == "test" and method == "POST":
        row = conn.execute("SELECT * FROM gap_provider_connections WHERE id = ? AND organization_id = ?", (connection_id, org)).fetchone()
        if not row: raise DomainError(404, "Provider connection not found", "not_found")
        if row["mode"] == "production" and not row["credential_ref"]:
            conn.execute("UPDATE gap_provider_connections SET status = 'blocked_missing_credentials', last_tested_at = ?, last_error = ?, updated_at = ? WHERE id = ?", (now_iso(), "credential_ref is required before production validation", now_iso(), row["id"]))
            return {"ok": True, "status": "blocked_missing_credentials", "production_validated": False, "item": _serialize(conn.execute("SELECT * FROM gap_provider_connections WHERE id = ?", (row["id"],)).fetchone(), ("config_json", "capabilities_json"))}
        conn.execute("UPDATE gap_provider_connections SET status = CASE WHEN mode = 'mock' THEN 'healthy_mock' ELSE 'healthy' END, last_tested_at = ?, last_error = '', updated_at = ? WHERE id = ?", (now_iso(), now_iso(), row["id"]))
        _audit(conn, user, "provider.connection_tested", "provider_connection", row["id"], ip, {"mode": row["mode"], "production_validated": row["mode"] == "production"})
        return {"ok": True, "status": "healthy_mock" if row["mode"] == "mock" else "healthy", "production_validated": row["mode"] == "production", "item": _serialize(conn.execute("SELECT * FROM gap_provider_connections WHERE id = ?", (row["id"],)).fetchone(), ("config_json", "capabilities_json"))}
    if method != "POST": raise DomainError(405, "Use GET or POST for provider connections", "method_not_allowed")
    provider_type = _text(payload, "provider_type", maximum=30).lower(); name = _text(payload, "name", provider_type, 80)
    if provider_type not in PROVIDER_TYPES: raise DomainError(400, "Unsupported provider_type", "validation_error")
    mode = _text(payload, "mode", "mock", 20).lower()
    if mode not in {"mock", "sandbox", "production"}: raise DomainError(400, "mode must be mock, sandbox or production", "validation_error")
    # Store references and non-secret configuration only. Raw keys/tokens are never persisted.
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    safe_config = {str(key): value for key, value in config.items() if str(key).lower() not in {"secret", "api_key", "token", "password", "private_key", "access_token"}}
    connection_id = new_id("provider"); now = now_iso()
    conn.execute("INSERT INTO gap_provider_connections(id, organization_id, provider_type, name, mode, status, credential_ref, config_json, capabilities_json, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'configured', ?, ?, ?, ?, ?, ?) ON CONFLICT(organization_id, provider_type, name) DO UPDATE SET mode = excluded.mode, status = 'configured', credential_ref = excluded.credential_ref, config_json = excluded.config_json, capabilities_json = excluded.capabilities_json, updated_at = excluded.updated_at", (connection_id, org, provider_type, name, mode, _text(payload, "credential_ref", maximum=160), json.dumps(safe_config), json.dumps(payload.get("capabilities") if isinstance(payload.get("capabilities"), list) else []), user["id"], now, now))
    item = conn.execute("SELECT * FROM gap_provider_connections WHERE organization_id = ? AND provider_type = ? AND name = ?", (org, provider_type, name)).fetchone()
    _audit(conn, user, "provider.connection_configured", "provider_connection", item["id"], ip, {"provider_type": provider_type, "mode": mode})
    return {"ok": True, "item": _serialize(item, ("config_json", "capabilities_json")), "production_validated": False}


def _maps_and_call(conn, user, method, route, payload, ip):
    org = _org(user)
    if route == "/api/maps/places" and method == "GET":
        _staff(user); query = (parse_qs(urlsplit(route if "?" in route else "").query).get("q") or [""])[0] or _text(payload, "query", maximum=300)
        # The API helper normally receives the raw route; recover the query from it.
        query = (parse_qs(urlsplit(payload.get("_raw_route", "")).query).get("q") or [query])[0]
        if not query: raise DomainError(400, "q is required", "validation_error")
        result = DEFAULT_PROVIDERS.maps.places(query=query)
        return {"ok": True, "provider": result.provider, "production_validated": False, "item": result.payload}
    if route == "/api/maps/navigation" and method == "POST":
        _staff(user); pickup = payload.get("pickup") if isinstance(payload.get("pickup"), dict) else {}; dropoff = payload.get("dropoff") if isinstance(payload.get("dropoff"), dict) else {}
        if not pickup or not dropoff: raise DomainError(400, "pickup and dropoff are required", "validation_error")
        result = DEFAULT_PROVIDERS.maps.navigation(pickup=pickup, dropoff=dropoff, waypoints=payload.get("waypoints") if isinstance(payload.get("waypoints"), list) else [], mode=_text(payload, "mode", "driving", 30))
        return {"ok": True, "provider": result.provider, "production_validated": False, "item": result.payload}
    if route == "/api/communications/click-to-call" and method == "POST":
        _staff(user); to_number = _text(payload, "to_number", maximum=40); from_number = _text(payload, "from_number", maximum=40)
        if not to_number: raise DomainError(400, "to_number is required", "validation_error")
        result = DEFAULT_PROVIDERS.telephony.create_masked_call(from_number=from_number, to_number=to_number, context=_text(payload, "context", "duty", 80), idempotency_key=_idem(payload) or f"call:{org}:{to_number}")
        _audit(conn, user, "communication.click_to_call_requested", "call", result.reference, ip, {"provider": result.provider})
        return {"ok": True, "provider": result.provider, "item": {"reference": result.reference, **result.payload}, "production_validated": False}
    return None


def _payment_and_invoice(conn, user, method, route, payload, ip):
    org = _org(user)
    if route == "/api/payment-authorizations":
        _staff(user)
        if method == "GET":
            rows = conn.execute("SELECT * FROM gap_payment_authorizations WHERE organization_id = ? ORDER BY created_at DESC", (org,)).fetchall(); return {"ok": True, "items": [_safe_authorization(row) for row in rows]}
        if method != "POST": raise DomainError(405, "Use GET or POST for payment authorizations", "method_not_allowed")
        raw_token = _text(payload, "payment_method_token", maximum=500)
        if not raw_token: raise DomainError(400, "payment_method_token is required; raw card data is not accepted", "token_required")
        key = _idem(payload)
        if key:
            existing = conn.execute("SELECT * FROM gap_payment_authorizations WHERE organization_id = ? AND idempotency_key = ?", (org, key)).fetchone()
            if existing: return {"ok": True, "item": _safe_authorization(existing), "idempotent": True}
        fingerprint = hashlib.sha256(raw_token.encode()).hexdigest(); last4 = raw_token[-4:]
        auth_id = new_id("payment_auth"); now = now_iso()
        conn.execute("INSERT INTO gap_payment_authorizations(id, organization_id, customer_id, payer_email, provider, token_fingerprint, token_last4, max_amount_paise, currency, status, authorized_at, expires_at, idempotency_key, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)", (auth_id, org, _text(payload, "customer_id") or None, _text(payload, "payer_email", maximum=254).lower(), _text(payload, "provider", "mock_payment", 60), fingerprint, last4, int(payload.get("max_amount_paise") or 0), _text(payload, "currency", "INR", 8), now, _text(payload, "expires_at", maximum=40) or None, key, user["id"], now))
        _audit(conn, user, "payment.authorization_created", "payment_authorization", auth_id, ip, {"provider": _text(payload, "provider", "mock_payment", 60), "tokenized": True})
        return {"ok": True, "item": _safe_authorization(conn.execute("SELECT * FROM gap_payment_authorizations WHERE id = ?", (auth_id,)).fetchone())}
    collect_match = re.match(r"^/api/invoices/([^/]+)/auto-collect$", route)
    if collect_match and method == "POST":
        _staff(user); invoice = _assert_owned(conn, "domain_invoices", collect_match.group(1), org); auth_id = _text(payload, "authorization_id")
        auth = conn.execute("SELECT * FROM gap_payment_authorizations WHERE id = ? AND organization_id = ? AND status = 'active'", (auth_id, org)).fetchone()
        if not auth: raise DomainError(404, "Active payment authorization not found", "authorization_not_found")
        amount = int(payload.get("amount_paise") or invoice["total_paise"] or 0)
        if amount <= 0: raise DomainError(400, "amount_paise must be positive", "validation_error")
        if auth["max_amount_paise"] and amount > auth["max_amount_paise"]: raise DomainError(409, "Amount exceeds the authorization limit", "authorization_limit")
        key = _idem(payload) or f"auto_collect:{org}:{invoice['id']}:{auth['id']}"
        existing = conn.execute("SELECT * FROM gap_auto_collect_attempts WHERE organization_id = ? AND idempotency_key = ?", (org, key)).fetchone()
        if existing: return {"ok": True, "item": _serialize(existing, ("provider_payload_json",)), "idempotent": True}
        result = DEFAULT_PROVIDERS.payments.create_payment(amount_paise=amount, currency=auth["currency"], idempotency_key=key, metadata={"invoice_id": invoice["id"], "authorization_id": auth["id"]})
        attempt_id = new_id("collect"); now = now_iso()
        conn.execute("INSERT INTO gap_auto_collect_attempts(id, organization_id, authorization_id, invoice_id, amount_paise, status, provider_reference, provider_payload_json, idempotency_key, attempted_at, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (attempt_id, org, auth["id"], invoice["id"], amount, result.status, result.reference, json.dumps(result.payload), key, now, user["id"]))
        if result.ok:
            conn.execute("INSERT INTO domain_payments(id, organization_id, invoice_id, amount_paise, mode, status, gateway_reference, idempotency_key, received_at, created_at) VALUES (?, ?, ?, ?, 'auto_collect', ?, ?, ?, ?, ?) ON CONFLICT(organization_id, idempotency_key) DO NOTHING", (new_id("payment"), org, invoice["id"], amount, result.status, result.reference, key, now, now))
            conn.execute("UPDATE domain_invoices SET status = 'paid', updated_at = ? WHERE id = ? AND organization_id = ? AND status IN ('issued', 'sent', 'draft')", (now, invoice["id"], org))
        _audit(conn, user, "payment.auto_collect_attempted", "invoice", invoice["id"], ip, {"status": result.status, "provider": result.provider})
        return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM gap_auto_collect_attempts WHERE id = ?", (attempt_id,)).fetchone(), ("provider_payload_json",)), "provider": result.provider, "production_validated": False}
    if route == "/api/auto-collect/runs" and method == "GET":
        _staff(user); rows = conn.execute("SELECT * FROM gap_auto_collect_attempts WHERE organization_id = ? ORDER BY attempted_at DESC LIMIT ?", (org, _limit(route))).fetchall(); return {"ok": True, "items": [_serialize(row, ("provider_payload_json",)) for row in rows]}
    if route == "/api/invoice-automation/policies":
        _staff(user)
        if method == "GET":
            rows = conn.execute("SELECT * FROM gap_invoice_automation_policies WHERE organization_id = ? ORDER BY name", (org,)).fetchall(); return {"ok": True, "items": [_serialize(row) for row in rows]}
        if method != "POST": raise DomainError(405, "Use GET or POST for invoice automation policies", "method_not_allowed")
        policy_id = new_id("invoice_policy"); now = now_iso()
        conn.execute("INSERT INTO gap_invoice_automation_policies(id, organization_id, name, customer_id, trigger_event, issue_einvoice, collect_payment, send_channel, payment_terms_days, enabled, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(organization_id, name) DO UPDATE SET customer_id = excluded.customer_id, trigger_event = excluded.trigger_event, issue_einvoice = excluded.issue_einvoice, collect_payment = excluded.collect_payment, send_channel = excluded.send_channel, payment_terms_days = excluded.payment_terms_days, enabled = excluded.enabled, updated_at = excluded.updated_at", (policy_id, org, _text(payload, "name", "Default duty completion", 120), _text(payload, "customer_id") or None, _text(payload, "trigger_event", "duty_completed", 40), 1 if payload.get("issue_einvoice") else 0, 1 if payload.get("collect_payment") else 0, _text(payload, "send_channel", "email", 20), int(payload.get("payment_terms_days") or 7), 1 if payload.get("enabled", True) else 0, user["id"], now, now))
        item = conn.execute("SELECT * FROM gap_invoice_automation_policies WHERE organization_id = ? AND name = ?", (org, _text(payload, "name", "Default duty completion", 120))).fetchone()
        return {"ok": True, "item": _serialize(item)}
    run_match = re.match(r"^/api/invoice-automation/run$", route)
    if run_match and method == "POST":
        _staff(user); duty_id = _text(payload, "duty_id"); duty = _owned_duty(conn, user, duty_id)
        if duty["status"] not in {"completed", "closed", "settled"} and not payload.get("allow_uncompleted"):
            raise DomainError(409, "Duty must be completed before invoice automation runs", "duty_not_completed")
        key = _idem(payload) or f"invoice_automation:{org}:{duty_id}"
        existing = conn.execute("SELECT * FROM gap_invoice_automation_runs WHERE organization_id = ? AND idempotency_key = ?", (org, key)).fetchone()
        if existing: return {"ok": True, "item": _serialize(existing, ("result_json",)), "idempotent": True}
        # Reuse the finance parity invoice generator so rate cards, tax and fuel snapshots stay in one code path.
        from backend_finance_parity import handle_finance_parity
        generated = handle_finance_parity(conn, user, "POST", "/api/invoices/generate", {"mode": "per_duty", "duty_ids": [duty_id], "idempotency_key": key}, ip)
        invoice_item = (generated.get("invoices") or [{}])[0] if isinstance(generated, dict) else {}
        invoice_id = invoice_item.get("id") if isinstance(invoice_item, dict) else None
        run_id = new_id("invoice_run"); now = now_iso()
        conn.execute("INSERT INTO gap_invoice_automation_runs(id, organization_id, duty_id, invoice_id, status, result_json, idempotency_key, created_by, created_at) VALUES (?, ?, ?, ?, 'completed', ?, ?, ?, ?)", (run_id, org, duty_id, invoice_id, json.dumps(generated), key, user["id"], now))
        _audit(conn, user, "invoice.automation_completed", "invoice_automation_run", run_id, ip, {"duty_id": duty_id, "invoice_id": invoice_id})
        return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM gap_invoice_automation_runs WHERE id = ?", (run_id,)).fetchone(), ("result_json",)), "invoice": invoice_item}
    return None


def _custom_fields(conn, user, method, route, payload, ip):
    if route != "/api/enterprise/custom-field-values": return None
    _staff(user); org = _org(user)
    if method == "GET":
        query = parse_qs(urlsplit(payload.get("_raw_route", "")).query)
        entity_type = (query.get("entity_type") or [""])[0]; entity_id = (query.get("entity_id") or [""])[0]
        sql = "SELECT * FROM gap_custom_field_values WHERE organization_id = ?"; values = [org]
        if entity_type: sql += " AND entity_type = ?"; values.append(entity_type)
        if entity_id: sql += " AND entity_id = ?"; values.append(entity_id)
        rows = conn.execute(sql + " ORDER BY updated_at DESC", values).fetchall(); return {"ok": True, "items": [_serialize(row, ("value_json",)) for row in rows]}
    if method != "POST": raise DomainError(405, "Use GET or POST for custom field values", "method_not_allowed")
    values = payload.get("values") if isinstance(payload.get("values"), list) else [payload]
    saved = []
    for value in values:
        field_id = _text(value, "field_id"); entity_type = _text(value, "entity_type", maximum=50); entity_id = _text(value, "entity_id")
        if not field_id or not entity_type or not entity_id: raise DomainError(400, "field_id, entity_type and entity_id are required", "validation_error")
        field = conn.execute("SELECT id FROM enterprise_custom_fields WHERE id = ? AND organization_id = ? AND status = 'active'", (field_id, org)).fetchone()
        if not field: raise DomainError(404, "Custom field not found", "custom_field_not_found")
        value_id = new_id("custom_value"); now = now_iso()
        conn.execute("INSERT INTO gap_custom_field_values(id, organization_id, field_id, entity_type, entity_id, value_json, updated_by, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(organization_id, field_id, entity_type, entity_id) DO UPDATE SET value_json = excluded.value_json, updated_by = excluded.updated_by, updated_at = excluded.updated_at", (value_id, org, field_id, entity_type, entity_id, json.dumps(value.get("value")), user["id"], now))
        saved.append(_serialize(conn.execute("SELECT * FROM gap_custom_field_values WHERE organization_id = ? AND field_id = ? AND entity_type = ? AND entity_id = ?", (org, field_id, entity_type, entity_id)).fetchone(), ("value_json",)))
    _audit(conn, user, "enterprise.custom_field_values_saved", "custom_field_value", saved[0]["id"] if saved else "", ip, {"count": len(saved)})
    return {"ok": True, "items": saved}


def _sync_and_network(conn, user, method, route, payload, ip):
    org = _org(user)
    if route == "/api/integrations/sync":
        _staff(user)
        if method == "GET":
            rows = conn.execute("SELECT * FROM gap_sync_runs WHERE organization_id = ? ORDER BY created_at DESC LIMIT ?", (org, _limit(route))).fetchall(); return {"ok": True, "items": [_serialize(row, ("result_json",)) for row in rows]}
        if method != "POST": raise DomainError(405, "Use GET or POST for integration sync", "method_not_allowed")
        sync_type = _text(payload, "sync_type", maximum=40)
        if sync_type not in SYNC_TYPES: raise DomainError(400, "sync_type must be hrms, passenger_lifecycle or corporate_provisioning", "validation_error")
        records = payload.get("records") if isinstance(payload.get("records"), list) else []
        key = _idem(payload)
        if key:
            existing = conn.execute("SELECT * FROM gap_sync_runs WHERE organization_id = ? AND idempotency_key = ?", (org, key)).fetchone()
            if existing: return {"ok": True, "item": _serialize(existing, ("result_json",)), "idempotent": True}
        if sync_type == "hrms":
            result = DEFAULT_PROVIDERS.hrms.sync(records=records, idempotency_key=key)
        elif sync_type == "passenger_lifecycle":
            result = DEFAULT_PROVIDERS.hrms.sync(records=records, idempotency_key=key or "passenger_lifecycle")
        else:
            result = DEFAULT_PROVIDERS.hrms.sync(records=records, idempotency_key=key or "corporate_provisioning")
        sync_id = new_id("sync"); now = now_iso()
        conn.execute("INSERT INTO gap_sync_runs(id, organization_id, sync_type, provider, status, records_received, records_applied, provider_reference, result_json, idempotency_key, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (sync_id, org, sync_type, result.provider, result.status, len(records), len(records) if result.ok else 0, result.reference, json.dumps(result.payload), key, user["id"], now))
        _audit(conn, user, "integration.sync_accepted", "sync_run", sync_id, ip, {"sync_type": sync_type, "records": len(records), "provider": result.provider})
        return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM gap_sync_runs WHERE id = ?", (sync_id,)).fetchone(), ("result_json",)), "production_validated": False}
    if route == "/api/network/supplier-exchange":
        _staff(user)
        if method == "GET":
            rows = conn.execute("SELECT * FROM gap_supplier_exchange_jobs WHERE organization_id = ? ORDER BY created_at DESC LIMIT ?", (org, _limit(route))).fetchall(); return {"ok": True, "items": [_serialize(row, ("qualification_json", "contract_json", "rate_card_json", "payload_json")) for row in rows]}
        if method != "POST": raise DomainError(405, "Use POST for closed-network supplier exchange", "method_not_allowed")
        visibility = _text(payload, "visibility", "invite_only", 30)
        if visibility not in {"invite_only", "closed_b2b"}: raise DomainError(400, "Network supplier exchange is invite-only and closed-B2B", "closed_network_required")
        program = _text(payload, "network_program_id"); supplier = _text(payload, "supplier_id")
        if not program or not supplier: raise DomainError(400, "network_program_id and supplier_id are required", "validation_error")
        key = _idem(payload)
        if key:
            existing = conn.execute("SELECT * FROM gap_supplier_exchange_jobs WHERE organization_id = ? AND idempotency_key = ?", (org, key)).fetchone()
            if existing: return {"ok": True, "item": _serialize(existing, ("qualification_json", "contract_json", "rate_card_json", "payload_json")), "idempotent": True}
        job_id = new_id("supplier_exchange"); now = now_iso()
        conn.execute("INSERT INTO gap_supplier_exchange_jobs(id, organization_id, network_program_id, supplier_id, direction, visibility, status, qualification_json, contract_json, rate_card_json, payload_json, idempotency_key, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)", (job_id, org, program, supplier, _text(payload, "direction", "outbound", 20), visibility, json.dumps(payload.get("qualification") if isinstance(payload.get("qualification"), dict) else {}), json.dumps(payload.get("contract") if isinstance(payload.get("contract"), dict) else {}), json.dumps(payload.get("rate_card") if isinstance(payload.get("rate_card"), dict) else {}), json.dumps(payload.get("payload") if isinstance(payload.get("payload"), dict) else {}), key, user["id"], now, now))
        _audit(conn, user, "network.supplier_exchange_queued", "supplier_exchange", job_id, ip, {"program_id": program, "supplier_id": supplier, "visibility": visibility})
        return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM gap_supplier_exchange_jobs WHERE id = ?", (job_id,)).fetchone(), ("qualification_json", "contract_json", "rate_card_json", "payload_json"))}
    return None


def _budgets_and_forecast(conn, user, method, route, payload, ip):
    if route == "/api/finance/budgets":
        _staff(user); org = _org(user)
        if method == "GET":
            rows = conn.execute("SELECT * FROM gap_expense_budgets WHERE organization_id = ? ORDER BY period_key DESC", (org,)).fetchall(); return {"ok": True, "items": [_serialize(row) for row in rows]}
        if method != "POST": raise DomainError(405, "Use GET or POST for budgets", "method_not_allowed")
        period = _text(payload, "period_key", maximum=20); amount = int(payload.get("budget_paise") or 0)
        if not re.fullmatch(r"\d{4}-\d{2}", period) or amount < 0: raise DomainError(400, "period_key must be YYYY-MM and budget_paise cannot be negative", "validation_error")
        budget_id = new_id("budget"); now = now_iso()
        conn.execute("INSERT INTO gap_expense_budgets(id, organization_id, period_key, customer_id, budget_paise, alert_threshold_bps, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(organization_id, period_key, customer_id) DO UPDATE SET budget_paise = excluded.budget_paise, alert_threshold_bps = excluded.alert_threshold_bps, updated_at = excluded.updated_at", (budget_id, _org(user), period, _text(payload, "customer_id") or None, amount, int(payload.get("alert_threshold_bps") or 8000), user["id"], now, now))
        item = conn.execute("SELECT * FROM gap_expense_budgets WHERE organization_id = ? AND period_key = ? AND customer_id IS ?", (org, period, _text(payload, "customer_id") or None)).fetchone()
        _audit(conn, user, "finance.expense_budget_saved", "expense_budget", item["id"], ip, {"period_key": period})
        return {"ok": True, "item": _serialize(item)}
    if route != "/api/finance/expense-forecast" or method not in {"GET", "POST"}:
        return None
    _staff(user); org = _org(user)
    customer_id = _text(payload, "customer_id") or None
    current = datetime.now(timezone.utc)
    months = []
    for offset in range(3, 0, -1):
        month = current.month - offset; year = current.year
        while month <= 0: month += 12; year -= 1
        months.append(f"{year:04d}-{month:02d}")
    totals = []
    for period in months:
        sql = "SELECT coalesce(sum(total_paise), 0) AS total FROM domain_invoices WHERE organization_id = ? AND substr(created_at, 1, 7) = ?"
        values = [org, period]
        if customer_id: sql += " AND customer_id = ?"; values.append(customer_id)
        totals.append(int(conn.execute(sql, values).fetchone()["total"] or 0))
    average = round(sum(totals) / len(totals)) if totals else 0
    target_month = f"{current.year:04d}-{current.month:02d}"
    budget = conn.execute("SELECT * FROM gap_expense_budgets WHERE organization_id = ? AND period_key = ? AND customer_id IS ?", (org, target_month, customer_id)).fetchone()
    forecast = {"period_key": target_month, "history_periods": months, "history_totals_paise": totals, "average_monthly_paise": average, "forecast_paise": average, "budget_paise": budget["budget_paise"] if budget else None, "variance_paise": average - budget["budget_paise"] if budget else None, "method": "three_month_invoice_average", "model": "deterministic_local", "production_validated": False}
    return {"ok": True, "item": forecast}


def handle_gap_completion(conn, user, method: str, raw_route: str, payload: dict, ip: str):
    """Dispatch new local parity routes; return None for all existing routes."""
    route = urlsplit(raw_route).path.rstrip("/") or "/"
    supported = (
        route in {
            "/api/passenger/booking-requests", "/api/passenger/book-for-others", "/api/availability/optimize",
            "/api/driver-alert-policies", "/api/driver/device-readiness", "/api/provider-connections",
            "/api/maps/places", "/api/maps/navigation", "/api/communications/click-to-call",
            "/api/payment-authorizations", "/api/auto-collect/runs", "/api/invoice-automation/policies",
            "/api/invoice-automation/run", "/api/enterprise/custom-field-values", "/api/integrations/sync",
            "/api/network/supplier-exchange", "/api/finance/budgets", "/api/finance/expense-forecast",
        }
        or re.match(r"^/api/passenger/booking-requests/[^/]+/(approve|reject|cancel)$", route)
        or re.match(r"^/api/duties/[^/]+/route-log(?:/(start|stop))?$", route)
        or re.match(r"^/api/duties/[^/]+/location-share$", route)
        or re.match(r"^/api/duties/[^/]+/driver-alerts(?:/(acknowledge|resolve))?$", route)
        or re.match(r"^/api/driver-alert-policies(?:/[^/]+)?$", route)
        or re.match(r"^/api/provider-connections(?:/[^/]+(?:/test)?)?$", route)
        or re.match(r"^/api/invoices/[^/]+/auto-collect$", route)
    )
    if not supported:
        return None
    payload = {**payload, "_raw_route": raw_route}
    for handler in (
        _booking_requests,
        _availability,
        _route_logs,
        _location_share,
        _alerts_and_readiness,
        _provider_connections,
        _maps_and_call,
        _payment_and_invoice,
        _custom_fields,
        _sync_and_network,
        _budgets_and_forecast,
    ):
        result = handler(conn, user, method, route, payload, ip)
        if result is not None:
            return result
    return None
