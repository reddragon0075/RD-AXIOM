"""Operational parity slice for Axiom Fleet.

This module adds the next car-rental operating layer after the corporate
account foundation: batch/itinerary/monthly booking intake, deterministic
availability and allotment, and a unified duty-closure/evidence boundary.
It intentionally stays dependency-free for the local preview and mirrors the
Supabase Edge contract in operations-orchestrator.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

from backend_domain import (
    DomainError,
    _assert_owned,
    _audit,
    _create_booking,
    _create_duty,
    _org,
    _require_role,
    _serialize,
    _text,
    new_id,
    now_iso,
)


BATCH_MODES = {"bulk", "itinerary", "monthly"}
BATCH_STATUSES = {"processing", "completed", "partial", "failed", "cancelled"}
ALLOTMENT_STATUSES = {"assigned", "blocked", "released"}
EVIDENCE_TYPES = {"signature", "duty_slip", "photo", "otp", "toll", "parking", "receipt", "other"}


def initialize_operations_parity_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS domain_booking_batches (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            mode TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'processing',
            requested_count INTEGER NOT NULL DEFAULT 0,
            generated_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            start_at TEXT,
            end_at TEXT,
            idempotency_key TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_booking_batch_rows (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            row_number INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            source_json TEXT NOT NULL DEFAULT '{}',
            booking_id TEXT,
            error_code TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(batch_id, row_number)
        );
        CREATE TABLE IF NOT EXISTS domain_allotment_decisions (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            booking_id TEXT NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL,
            supplier_id TEXT,
            driver_id TEXT,
            vehicle_id TEXT,
            score INTEGER NOT NULL DEFAULT 0,
            rationale_json TEXT NOT NULL DEFAULT '{}',
            idempotency_key TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, booking_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_duty_closures (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            duty_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'submitted',
            closure_version INTEGER NOT NULL DEFAULT 1,
            payload_json TEXT NOT NULL DEFAULT '{}',
            completeness_json TEXT NOT NULL DEFAULT '{}',
            submitted_by TEXT,
            submitted_at TEXT NOT NULL,
            approved_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, duty_id, closure_version)
        );
        CREATE TABLE IF NOT EXISTS domain_closure_evidence (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            closure_id TEXT NOT NULL,
            duty_id TEXT NOT NULL,
            evidence_type TEXT NOT NULL,
            storage_path TEXT NOT NULL DEFAULT '',
            sha256 TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            required INTEGER NOT NULL DEFAULT 0,
            captured_by TEXT,
            captured_at TEXT NOT NULL,
            UNIQUE(organization_id, duty_id, evidence_type, sha256)
        );
        CREATE INDEX IF NOT EXISTS idx_booking_batches_org_created
          ON domain_booking_batches(organization_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_booking_batch_rows_batch
          ON domain_booking_batch_rows(organization_id, batch_id, row_number);
        CREATE INDEX IF NOT EXISTS idx_allotment_decisions_booking
          ON domain_allotment_decisions(organization_id, booking_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_duty_closures_duty
          ON domain_duty_closures(organization_id, duty_id, closure_version DESC);
        CREATE INDEX IF NOT EXISTS idx_closure_evidence_duty
          ON domain_closure_evidence(organization_id, duty_id, captured_at DESC);
        """
    )


def _staff(user) -> None:
    if user["role"] not in {"vendor", "corporate"}:
        raise DomainError(403, "This workflow is restricted to organization operators", "role_forbidden")


def _parse_datetime(value: object, field: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise DomainError(400, f"{field} is required", "validation_error")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DomainError(400, f"{field} must be an ISO datetime", "validation_error") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _month_add(value: datetime, months: int) -> datetime:
    month_index = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _json_value(row, field: str, fallback):
    try:
        return json.loads(row[field]) if row and row[field] else fallback
    except (TypeError, ValueError):
        return fallback


def _batch_row(row):
    item = _serialize(row, ("source_json",))
    item["source"] = item.pop("source_json", {})
    return item


def _batch_item(conn, batch_id: str, org: str):
    batch = conn.execute(
        "SELECT * FROM domain_booking_batches WHERE id = ? AND organization_id = ?",
        (batch_id, org),
    ).fetchone()
    if not batch:
        raise DomainError(404, "Booking batch not found", "not_found")
    item = _serialize(batch, ("payload_json",))
    item["payload"] = item.pop("payload_json", {})
    item["rows"] = [
        _batch_row(row)
        for row in conn.execute(
            "SELECT * FROM domain_booking_batch_rows WHERE batch_id = ? AND organization_id = ? ORDER BY row_number",
            (batch_id, org),
        ).fetchall()
    ]
    return item


def _batch_inputs(payload: dict, mode: str) -> list[dict]:
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else None
    if mode == "bulk":
        return [row if isinstance(row, dict) else {} for row in (rows or [])]
    if mode == "itinerary":
        segments = payload.get("segments") if isinstance(payload.get("segments"), list) else rows
        if not segments:
            raise DomainError(400, "An itinerary needs at least one segment", "validation_error")
        base = {key: value for key, value in payload.items() if key not in {"mode", "segments", "rows", "idempotency_key"}}
        result = []
        for index, segment in enumerate(segments, 1):
            data = segment if isinstance(segment, dict) else {"dropoff": segment}
            result.append({**base, **data, "source": data.get("source", "itinerary"), "itinerary_segment": index})
        return result
    if mode == "monthly":
        template = payload.get("template") if isinstance(payload.get("template"), dict) else {}
        start = _parse_datetime(payload.get("start_at"), "start_at")
        end = _parse_datetime(payload["end_at"], "end_at") if payload.get("end_at") else None
        try:
            occurrences = int(payload.get("occurrences") or 1)
        except (TypeError, ValueError) as exc:
            raise DomainError(400, "occurrences must be an integer", "validation_error") from exc
        if not 1 <= occurrences <= 365:
            raise DomainError(400, "occurrences must be between 1 and 365", "validation_error")
        result = []
        for index in range(occurrences):
            scheduled = _month_add(start, index)
            if end and scheduled > end:
                break
            result.append({**template, "scheduled_at": _iso(scheduled), "monthly_occurrence": index + 1})
        return result
    raise DomainError(400, "mode must be bulk, itinerary or monthly", "validation_error")


def _store_stops(conn, org: str, booking_id: str, stops: object) -> None:
    if not isinstance(stops, list):
        return
    for index, stop in enumerate(stops, 1):
        data = stop if isinstance(stop, dict) else {"label": str(stop)}
        label = str(data.get("label") or f"Stop {index}").strip()[:180]
        conn.execute(
            "INSERT OR REPLACE INTO domain_booking_stops(id, organization_id, booking_id, stop_index, label, address_json, arrival_at, departure_at, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id("stop"), org, booking_id, index, label,
                json.dumps(data.get("address") if isinstance(data.get("address"), dict) else data),
                data.get("arrival_at"), data.get("departure_at"),
                str(data.get("status") or "planned")[:20], now_iso(),
            ),
        )


def _create_batch(conn, user, payload: dict, ip: str):
    org = _org(user)
    _staff(user)
    mode = str(payload.get("mode") or "bulk").strip().lower()
    if mode not in BATCH_MODES:
        raise DomainError(400, "mode must be bulk, itinerary or monthly", "validation_error")
    key = str(payload.get("idempotency_key") or "").strip() or None
    if key:
        existing = conn.execute(
            "SELECT id FROM domain_booking_batches WHERE organization_id = ? AND idempotency_key = ?",
            (org, key),
        ).fetchone()
        if existing:
            return {"ok": True, "item": _batch_item(conn, existing["id"], org), "idempotent": True}
    inputs = _batch_inputs(payload, mode)
    if not inputs or len(inputs) > 500:
        raise DomainError(400, "Provide between 1 and 500 booking rows", "batch_too_large")
    batch_id = new_id("batch")
    now = now_iso()
    conn.execute(
        "INSERT INTO domain_booking_batches(id, organization_id, mode, status, requested_count, start_at, end_at, idempotency_key, payload_json, created_by, created_at, updated_at) VALUES (?, ?, ?, 'processing', ?, ?, ?, ?, ?, ?, ?, ?)",
        (batch_id, org, mode, len(inputs), payload.get("start_at"), payload.get("end_at"), key, json.dumps({"mode": mode}), user["id"], now, now),
    )
    for index, source in enumerate(inputs, 1):
        conn.execute(
            "INSERT INTO domain_booking_batch_rows(id, organization_id, batch_id, row_number, source_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (new_id("batchrow"), org, batch_id, index, json.dumps(source), now, now),
        )
    generated = 0
    failures = 0
    results = []
    # Importing here avoids a module cycle: the corporate evaluator itself is
    # initialized by server.py alongside this module.
    from backend_corporate import apply_corporate_booking_decision, evaluate_corporate_booking_write

    for index, source in enumerate(inputs, 1):
        savepoint = f"batch_row_{index}"
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            evaluation = evaluate_corporate_booking_write(conn, user, source, "book", ip)
            if evaluation and evaluation.get("outcome") == "block":
                raise DomainError(409, "Corporate booking policy blocked this row", "corporate_policy_blocked", evaluation)
            result = _create_booking(conn, user, source, ip)
            booking = result["item"]
            # Keep the original batch contract while adding a durable booking
            # group/type for the lifecycle and allotment parity layer.
            batch_booking_type = str(source.get("booking_type") or ("monthly" if mode == "monthly" else "multi_day" if mode == "itinerary" else "single")).lower()
            if batch_booking_type in {"flat", "flat-rate", "flat_rate"}:
                batch_booking_type = "flat_rate"
            if batch_booking_type not in {"single", "flat_rate", "monthly", "multi_day", "parent", "child"}:
                batch_booking_type = "single"
            conn.execute("UPDATE domain_bookings SET booking_type = ?, booking_group_id = ?, child_sequence = ?, flat_rate_paise = ?, start_at = COALESCE(?, scheduled_at), end_at = ?, recurrence_rule = ?, vehicle_group_code = ?, allotment_mode = ? WHERE id = ? AND organization_id = ?", (batch_booking_type, batch_id, index, int(source.get("flat_rate_paise") or source.get("flat_rate") or 0), source.get("start_at") or source.get("scheduled_at"), source.get("end_at"), str(source.get("recurrence_rule") or source.get("recurrence") or ""), str(source.get("vehicle_group_code") or source.get("vehicle_group") or ""), str(source.get("allotment_mode") or "owned"), booking["id"], org))
            booking = dict(conn.execute("SELECT * FROM domain_bookings WHERE id = ?", (booking["id"],)).fetchone())
            _store_stops(conn, org, booking["id"], source.get("stops"))
            if evaluation and evaluation.get("outcome") == "needs_approval":
                applied = apply_corporate_booking_decision(conn, user, booking["id"], evaluation, ip)
                booking["status"] = "pending_approval"
                booking["corporate_evaluation"] = applied
            conn.execute(f"RELEASE {savepoint}")
            conn.execute("UPDATE domain_booking_batch_rows SET status = 'created', booking_id = ?, updated_at = ? WHERE batch_id = ? AND row_number = ?", (booking["id"], now_iso(), batch_id, index))
            generated += 1
            results.append({"row": index, "status": "created", "item": booking})
        except DomainError as exc:
            conn.execute(f"ROLLBACK TO {savepoint}")
            conn.execute(f"RELEASE {savepoint}")
            conn.execute("UPDATE domain_booking_batch_rows SET status = 'error', error_code = ?, error_message = ?, updated_at = ? WHERE batch_id = ? AND row_number = ?", (exc.code, exc.message, now_iso(), batch_id, index))
            failures += 1
            results.append({"row": index, "status": "error", "code": exc.code, "error": exc.message, "details": exc.details})
        except Exception:
            conn.execute(f"ROLLBACK TO {savepoint}")
            conn.execute(f"RELEASE {savepoint}")
            conn.execute("UPDATE domain_booking_batch_rows SET status = 'error', error_code = 'row_error', error_message = ?, updated_at = ? WHERE batch_id = ? AND row_number = ?", ("The row could not be created", now_iso(), batch_id, index))
            failures += 1
            results.append({"row": index, "status": "error", "code": "row_error", "error": "The row could not be created"})
    status = "completed" if failures == 0 else "partial" if generated else "failed"
    conn.execute("UPDATE domain_booking_batches SET status = ?, generated_count = ?, failed_count = ?, updated_at = ? WHERE id = ?", (status, generated, failures, now_iso(), batch_id))
    _audit(conn, user, f"booking.batch_{mode}", "booking_batch", batch_id, ip, {"requested": len(inputs), "generated": generated, "failed": failures})
    return {"ok": True, "item": _batch_item(conn, batch_id, org), "results": results}


def _resource_available(conn, org: str, resource_type: str, resource_id: str, starts: datetime, ends: datetime, exclude_booking: str | None = None) -> bool:
    lock = conn.execute(
        "SELECT id FROM domain_capacity_locks WHERE organization_id = ? AND resource_type = ? AND resource_id = ? AND status = 'held' AND starts_at < ? AND ends_at > ? LIMIT 1",
        (org, resource_type, resource_id, _iso(ends), _iso(starts)),
    ).fetchone()
    if lock:
        return False
    if resource_type == "driver":
        rows = conn.execute(
            "SELECT d.reporting_at, b.scheduled_at FROM domain_duties d JOIN domain_bookings b ON b.id = d.booking_id WHERE d.organization_id = ? AND d.driver_id = ? AND d.status NOT IN ('completed','cancelled','disputed')",
            (org, resource_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT d.reporting_at, b.scheduled_at FROM domain_duties d JOIN domain_bookings b ON b.id = d.booking_id WHERE d.organization_id = ? AND d.vehicle_id = ? AND d.status NOT IN ('completed','cancelled','disputed')",
            (org, resource_id),
        ).fetchall()
    for row in rows:
        raw = row["reporting_at"] or row["scheduled_at"]
        if not raw:
            continue
        try:
            point = _parse_datetime(raw, "scheduled_at")
        except DomainError:
            continue
        if point < ends and point + timedelta(hours=2) > starts:
            return False
    return True


def _availability(conn, user, payload: dict):
    org = _org(user)
    starts = _parse_datetime(payload.get("starts_at") or payload.get("scheduled_at"), "starts_at")
    ends = _parse_datetime(payload.get("ends_at"), "ends_at") if payload.get("ends_at") else starts + timedelta(hours=float(payload.get("duration_hours") or 2))
    if ends <= starts:
        raise DomainError(400, "ends_at must be after starts_at", "validation_error")
    city = str(payload.get("city") or "").strip().lower()
    vehicle_group = str(payload.get("vehicle_group") or payload.get("vehicle_group_code") or "").strip().lower()
    drivers = []
    for row in conn.execute("SELECT * FROM domain_drivers WHERE organization_id = ? AND status IN ('available','active') ORDER BY full_name ASC, id ASC", (org,)).fetchall():
        if _resource_available(conn, org, "driver", row["id"], starts, ends, payload.get("booking_id")):
            score = 0 if city and str(row["city"] or "").strip().lower() == city else 1
            drivers.append({"id": row["id"], "full_name": row["full_name"], "city": row["city"], "score": score})
    vehicles = []
    for row in conn.execute("SELECT * FROM domain_vehicles WHERE organization_id = ? AND status IN ('available','active') ORDER BY registration_number ASC, id ASC", (org,)).fetchall():
        group = str(row["vehicle_group"] or "").strip().lower()
        if vehicle_group and group and group != vehicle_group:
            continue
        if _resource_available(conn, org, "vehicle", row["id"], starts, ends, payload.get("booking_id")):
            score = 0 if city and str(row["city"] or "").strip().lower() == city else 1
            vehicles.append({"id": row["id"], "registration_number": row["registration_number"], "vehicle_group": row["vehicle_group"], "city": row["city"], "score": score})
    drivers.sort(key=lambda item: (item["score"], item["full_name"].lower(), item["id"]))
    vehicles.sort(key=lambda item: (item["score"], item["registration_number"].lower(), item["id"]))
    reasons = []
    if not drivers:
        reasons.append({"code": "no_available_driver", "severity": "block", "message": "No driver is available for the requested window."})
    if not vehicles:
        reasons.append({"code": "no_available_vehicle", "severity": "block", "message": "No vehicle is available for the requested window."})
    return {"starts_at": _iso(starts), "ends_at": _iso(ends), "drivers": drivers, "vehicles": vehicles, "eligible": not reasons, "reasons": reasons, "deterministic": True}


def _allot(conn, user, booking_id: str, payload: dict, ip: str):
    org = _org(user)
    _staff(user)
    booking = _assert_owned(conn, "domain_bookings", booking_id, org)
    if booking["status"] == "pending_approval":
        raise DomainError(409, "Booking approval is required before allotment", "booking_approval_required")
    key = str(payload.get("idempotency_key") or "").strip() or None
    if key:
        existing = conn.execute("SELECT * FROM domain_allotment_decisions WHERE organization_id = ? AND booking_id = ? AND idempotency_key = ?", (org, booking_id, key)).fetchone()
        if existing:
            return {"ok": True, "item": _serialize(existing, ("rationale_json",)), "idempotent": True}
    starts = _parse_datetime(booking["scheduled_at"], "scheduled_at")
    availability = _availability(conn, user, {**payload, "booking_id": booking_id, "scheduled_at": booking["scheduled_at"], "city": (json.loads(booking["pickup_json"] or "{}").get("city") if booking["pickup_json"] else "")})
    if not availability["eligible"]:
        decision_id = new_id("allot")
        conn.execute("INSERT INTO domain_allotment_decisions(id, organization_id, booking_id, status, score, rationale_json, idempotency_key, created_by, created_at) VALUES (?, ?, ?, 'blocked', 0, ?, ?, ?, ?)", (decision_id, org, booking_id, json.dumps(availability), key, user["id"], now_iso()))
        _audit(conn, user, "booking.allotment_blocked", "booking", booking_id, ip, {"reasons": availability["reasons"]})
        raise DomainError(409, "No eligible driver and vehicle are available", "allotment_blocked", availability)
    driver_id = str(payload.get("driver_id") or availability["drivers"][0]["id"])
    vehicle_id = str(payload.get("vehicle_id") or availability["vehicles"][0]["id"])
    if not any(row["id"] == driver_id for row in availability["drivers"]):
        raise DomainError(409, "Selected driver is not available for the requested window", "capacity_conflict")
    if not any(row["id"] == vehicle_id for row in availability["vehicles"]):
        raise DomainError(409, "Selected vehicle is not available for the requested window", "capacity_conflict")
    duty_result = _create_duty(conn, user, {"booking_id": booking_id, "driver_id": driver_id, "vehicle_id": vehicle_id, "reporting_at": booking["scheduled_at"]}, ip)
    duty = duty_result["item"]
    ends = _parse_datetime(availability["ends_at"], "ends_at")
    for resource_type, resource_id in (("driver", driver_id), ("vehicle", vehicle_id)):
        conn.execute("INSERT INTO domain_capacity_locks(id, organization_id, resource_type, resource_id, booking_id, starts_at, ends_at, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'held', ?)", (new_id("capacity"), org, resource_type, resource_id, booking_id, _iso(starts), _iso(ends), now_iso()))
    decision_id = new_id("allot")
    rationale = {"availability": availability, "selection": {"driver_id": driver_id, "vehicle_id": vehicle_id}, "duty_id": duty["id"]}
    conn.execute("INSERT INTO domain_allotment_decisions(id, organization_id, booking_id, status, driver_id, vehicle_id, score, rationale_json, idempotency_key, created_by, created_at) VALUES (?, ?, ?, 'assigned', ?, ?, ?, ?, ?, ?, ?)", (decision_id, org, booking_id, driver_id, vehicle_id, 0, json.dumps(rationale), key, user["id"], now_iso()))
    _audit(conn, user, "booking.allotted", "booking", booking_id, ip, {"duty_id": duty["id"], "driver_id": driver_id, "vehicle_id": vehicle_id})
    return {"ok": True, "booking": {**_serialize(booking, ("pickup_json", "dropoff_json")), "status": "assigned"}, "duty": duty, "decision": _serialize(conn.execute("SELECT * FROM domain_allotment_decisions WHERE id = ?", (decision_id,)).fetchone(), ("rationale_json",)), "availability": availability}


def _closure_item(conn, duty_id: str, org: str):
    closure = conn.execute("SELECT * FROM domain_duty_closures WHERE organization_id = ? AND duty_id = ? ORDER BY closure_version DESC LIMIT 1", (org, duty_id)).fetchone()
    if not closure:
        return None
    item = _serialize(closure, ("payload_json", "completeness_json"))
    item["payload"] = item.pop("payload_json", {})
    item["completeness"] = item.pop("completeness_json", {})
    item["evidence"] = [_serialize(row, ("metadata_json",)) for row in conn.execute("SELECT * FROM domain_closure_evidence WHERE organization_id = ? AND duty_id = ? ORDER BY captured_at", (org, duty_id)).fetchall()]
    return item


def _close_duty(conn, user, duty_id: str, payload: dict, ip: str):
    org = _org(user)
    duty = _assert_owned(conn, "domain_duties", duty_id, org)
    if user["role"] == "driver":
        assignment = conn.execute("SELECT id FROM domain_drivers WHERE id = ? AND user_id = ? AND organization_id = ?", (duty["driver_id"], user["id"], org)).fetchone()
        if assignment is None:
            raise DomainError(403, "This duty is not assigned to the signed-in driver", "duty_assignment_required")
    else:
        _require_role(user)
    start_odo = payload.get("start_odometer", duty["start_odometer"])
    end_odo = payload.get("end_odometer", duty["end_odometer"])
    if start_odo in (None, "") or end_odo in (None, ""):
        raise DomainError(400, "Start and end odometer readings are required", "closure_incomplete")
    try:
        start_odo = int(start_odo); end_odo = int(end_odo)
    except (TypeError, ValueError) as exc:
        raise DomainError(400, "Odometer readings must be integers", "validation_error") from exc
    if start_odo < 0 or end_odo < start_odo:
        raise DomainError(400, "End odometer must be greater than or equal to start odometer", "validation_error")
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), list) else []
    required = [str(value).strip().lower() for value in (payload.get("required_evidence") if isinstance(payload.get("required_evidence"), list) else []) if str(value).strip()]
    evidence_types = {str(item.get("evidence_type") or item.get("type") or "").strip().lower() for item in evidence if isinstance(item, dict)}
    missing = [item for item in required if item not in evidence_types]
    if missing:
        raise DomainError(409, "Required closure evidence is missing", "closure_incomplete", {"missing_evidence": missing})
    version = int(conn.execute("SELECT COALESCE(MAX(closure_version), 0) + 1 AS next_version FROM domain_duty_closures WHERE organization_id = ? AND duty_id = ?", (org, duty_id)).fetchone()["next_version"])
    closure_id = new_id("closure")
    now = now_iso()
    payload_copy = {key: value for key, value in payload.items() if key not in {"evidence", "required_evidence"}}
    completeness = {"start_odometer": True, "end_odometer": True, "required_evidence": required, "missing_evidence": missing, "evidence_count": len(evidence), "complete": not missing}
    conn.execute("INSERT INTO domain_duty_closures(id, organization_id, duty_id, status, closure_version, payload_json, completeness_json, submitted_by, submitted_at, created_at, updated_at) VALUES (?, ?, ?, 'completed', ?, ?, ?, ?, ?, ?, ?)", (closure_id, org, duty_id, version, json.dumps(payload_copy), json.dumps(completeness), user["id"], now, now, now))
    for item in evidence:
        if not isinstance(item, dict):
            continue
        evidence_type = str(item.get("evidence_type") or item.get("type") or "other").strip().lower()
        if evidence_type not in EVIDENCE_TYPES:
            raise DomainError(400, f"Unsupported evidence type: {evidence_type}", "validation_error")
        raw_hash = str(item.get("sha256") or "").strip().lower()
        if not raw_hash and item.get("content"):
            raw_hash = hashlib.sha256(str(item["content"]).encode("utf-8")).hexdigest()
        conn.execute("INSERT OR IGNORE INTO domain_closure_evidence(id, organization_id, closure_id, duty_id, evidence_type, storage_path, sha256, metadata_json, required, captured_by, captured_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (new_id("evidence"), org, closure_id, duty_id, evidence_type, str(item.get("storage_path") or "")[:500], raw_hash, json.dumps(item.get("metadata") if isinstance(item.get("metadata"), dict) else {}), 1 if evidence_type in required else 0, user["id"], str(item.get("captured_at") or now_iso())))
    conn.execute("UPDATE domain_duties SET status = 'completed', start_odometer = ?, end_odometer = ?, completed_at = COALESCE(completed_at, ?), updated_at = ? WHERE id = ? AND organization_id = ?", (start_odo, end_odo, now, now, duty_id, org))
    if duty.get("booking_id"):
        conn.execute("UPDATE domain_bookings SET status = 'completed', updated_at = ? WHERE id = ? AND organization_id = ?", (now, duty["booking_id"], org))
    conn.execute("INSERT INTO domain_duty_events(id, organization_id, duty_id, event_type, source, payload_json, event_at, created_by) VALUES (?, ?, ?, 'closed', ?, ?, ?, ?)", (new_id("event"), org, duty_id, str(payload.get("source") or ("driver_app" if user["role"] == "driver" else "web"))[:40], json.dumps({"closure_id": closure_id, "closure_version": version, "completeness": completeness}), now, user["id"]))
    _audit(conn, user, "duty.closed", "duty", duty_id, ip, {"closure_id": closure_id, "closure_version": version, "evidence_count": len(evidence)})
    return {"ok": True, "item": _closure_item(conn, duty_id, org), "duty": _serialize(conn.execute("SELECT * FROM domain_duties WHERE id = ?", (duty_id,)).fetchone(), ("calculation_snapshot_json",))}


def handle_operations_parity(conn, user, method: str, raw_route: str, payload: dict, ip: str):
    route = urlsplit(raw_route).path.rstrip("/") or "/"
    query = parse_qs(urlsplit(raw_route).query)
    owned_route = (
        route == "/api/bookings/batches"
        or route.startswith("/api/bookings/batches/")
        or route in {"/api/availability", "/api/availability/evaluate", "/api/allotment/decisions"}
        or re.match(r"^/api/bookings/[^/]+/allot$", route)
        or re.match(r"^/api/duties/[^/]+/(close|closure|closure/evidence)$", route)
    )
    if not owned_route:
        return None
    org = _org(user)
    if route == "/api/bookings/batches" and method in {"GET", "POST"}:
        if method == "POST":
            return _create_batch(conn, user, payload, ip)
        rows = conn.execute("SELECT * FROM domain_booking_batches WHERE organization_id = ? ORDER BY created_at DESC LIMIT ?", (org, min(int(query.get("limit", [100])[0] or 100), 500))).fetchall()
        return {"ok": True, "items": [_batch_item(conn, row["id"], org) for row in rows], "count": len(rows)}
    batch_match = re.match(r"^/api/bookings/batches/([^/]+)(?:/(cancel|rows))?$", route)
    if batch_match:
        batch_id, action = batch_match.group(1), batch_match.group(2)
        batch = conn.execute("SELECT * FROM domain_booking_batches WHERE id = ? AND organization_id = ?", (batch_id, org)).fetchone()
        if not batch:
            raise DomainError(404, "Booking batch not found", "not_found")
        if method == "GET":
            return {"ok": True, "item": _batch_item(conn, batch_id, org)}
        if action == "cancel" and method == "POST":
            _staff(user)
            conn.execute("UPDATE domain_booking_batches SET status = 'cancelled', updated_at = ? WHERE id = ? AND status IN ('processing','partial')", (now_iso(), batch_id))
            _audit(conn, user, "booking.batch_cancelled", "booking_batch", batch_id, ip, {})
            return {"ok": True, "item": _batch_item(conn, batch_id, org)}
        if action == "rows" and method == "GET":
            return {"ok": True, "items": [_batch_row(row) for row in conn.execute("SELECT * FROM domain_booking_batch_rows WHERE batch_id = ? AND organization_id = ? ORDER BY row_number", (batch_id, org)).fetchall()]}
    if route in {"/api/availability", "/api/availability/evaluate"} and method in {"GET", "POST"}:
        return {"ok": True, **_availability(conn, user, payload if method == "POST" else {key: values[0] for key, values in query.items()})}
    allot_match = re.match(r"^/api/bookings/([^/]+)/allot$", route)
    if allot_match and method == "POST":
        return _allot(conn, user, allot_match.group(1), payload, ip)
    if route == "/api/allotment/decisions" and method == "GET":
        rows = conn.execute("SELECT * FROM domain_allotment_decisions WHERE organization_id = ? ORDER BY created_at DESC LIMIT ?", (org, min(int(query.get("limit", [100])[0] or 100), 500))).fetchall()
        return {"ok": True, "items": [_serialize(row, ("rationale_json",)) for row in rows], "count": len(rows)}
    close_match = re.match(r"^/api/duties/([^/]+)/close$", route)
    if close_match and method == "POST":
        return _close_duty(conn, user, close_match.group(1), payload, ip)
    closure_match = re.match(r"^/api/duties/([^/]+)/closure(?:/evidence)?$", route)
    if closure_match and method == "GET":
        return {"ok": True, "item": _closure_item(conn, closure_match.group(1), org)}
    if closure_match and method == "POST":
        duty_id = closure_match.group(1)
        if not route.endswith("/evidence"):
            return _close_duty(conn, user, duty_id, payload, ip)
        _require_role(user)
        duty = _assert_owned(conn, "domain_duties", duty_id, org)
        closure = conn.execute("SELECT * FROM domain_duty_closures WHERE organization_id = ? AND duty_id = ? ORDER BY closure_version DESC LIMIT 1", (org, duty_id)).fetchone()
        if not closure:
            raise DomainError(409, "Close the duty before adding closure evidence", "closure_required")
        evidence = payload if isinstance(payload, dict) else {}
        evidence_type = str(evidence.get("evidence_type") or evidence.get("type") or "other").strip().lower()
        if evidence_type not in EVIDENCE_TYPES:
            raise DomainError(400, "Unsupported evidence type", "validation_error")
        raw_hash = str(evidence.get("sha256") or "").strip().lower() or hashlib.sha256(str(evidence.get("content") or "").encode()).hexdigest()
        conn.execute("INSERT OR IGNORE INTO domain_closure_evidence(id, organization_id, closure_id, duty_id, evidence_type, storage_path, sha256, metadata_json, required, captured_by, captured_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (new_id("evidence"), org, closure["id"], duty_id, evidence_type, str(evidence.get("storage_path") or "")[:500], raw_hash, json.dumps(evidence.get("metadata") if isinstance(evidence.get("metadata"), dict) else {}), 0, user["id"], str(evidence.get("captured_at") or now_iso())))
        _audit(conn, user, "duty.closure_evidence_added", "duty", duty_id, ip, {"evidence_type": evidence_type})
        return {"ok": True, "item": _closure_item(conn, duty_id, org)}
    return None
