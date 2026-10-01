"""Exception-first operating cockpit contracts.

Axiom Fleet should not make an operator scan a wall of KPIs to discover the
one thing that can break today's service.  This additive module projects a
small, explainable queue of next actions from the canonical tenant records.
It deliberately does not create a second booking or duty ledger: every item
points back to an existing source record and can be acknowledged, snoozed or
resolved without changing the underlying business state.

The local implementation is deterministic and dependency-free.  Supabase
uses the same action-state contract behind an authenticated Edge boundary.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

from backend_domain import DomainError, _audit, _org, _text, new_id, now_iso


ACTION_STATUSES = {"acknowledged", "snoozed", "resolved", "reopened"}
PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
TERMINAL_BOOKING_STATUSES = {"cancelled", "completed"}
TERMINAL_DUTY_STATUSES = {"cancelled", "completed", "closed", "settled"}


def initialize_command_center_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS workspace_action_states (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            action_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'acknowledged',
            snooze_until TEXT,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, user_id, action_id)
        );
        CREATE INDEX IF NOT EXISTS idx_workspace_action_states_user
          ON workspace_action_states(organization_id, user_id, status, updated_at);
        """
    )


def _limit(raw_route: str, default: int = 12) -> int:
    try:
        value = int((parse_qs(urlsplit(raw_route).query).get("limit") or [default])[0])
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, 50))


def _as_json(value, fallback=None):
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value) if value else (fallback if fallback is not None else {})
    except (TypeError, ValueError):
        return fallback if fallback is not None else {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _is_stale(value: object, seconds: int = 900) -> bool:
    parsed = _parse_time(value)
    return parsed is None or (_now() - parsed).total_seconds() > seconds


def _action(
    action_id: str,
    *,
    category: str,
    priority: str,
    title: str,
    why: str,
    next_step: str,
    page: str,
    entity_type: str,
    entity_id: str,
    source: str,
    due_at: str | None = None,
    owner_role: str = "operator",
    blocking: bool = False,
    signals: list[str] | None = None,
) -> dict:
    return {
        "id": action_id,
        "category": category,
        "priority": priority,
        "title": title,
        "why": why,
        "next_step": next_step,
        "page": page,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "source": source,
        "due_at": due_at,
        "owner_role": owner_role,
        "blocking": blocking,
        "signals": signals or [],
        "status": "open",
    }


def _driver_ids(conn, user) -> set[str] | None:
    if user["role"] != "driver":
        return None
    return {
        row["id"]
        for row in conn.execute(
            "SELECT id FROM domain_drivers WHERE organization_id = ? AND user_id = ?",
            (_org(user), user["id"]),
        ).fetchall()
    }


def _visible_state_map(conn, user):
    rows = conn.execute(
        "SELECT action_id, status, snooze_until, note, updated_at FROM workspace_action_states WHERE organization_id = ? AND user_id = ?",
        (_org(user), user["id"]),
    ).fetchall()
    return {row["action_id"]: dict(row) for row in rows}


def _append_open_actions(conn, user, actions: list[dict]) -> None:
    """Apply user-level acknowledgement/snooze state without hiding source data."""
    states = _visible_state_map(conn, user)
    current = _now()
    for item in actions:
        state = states.get(item["id"])
        if not state:
            continue
        item["status"] = state["status"]
        item["note"] = state.get("note") or ""
        item["state_updated_at"] = state.get("updated_at")
        snooze_until = _parse_time(state.get("snooze_until"))
        if state["status"] == "snoozed" and snooze_until and snooze_until > current:
            item["snoozed_until"] = state["snooze_until"]
        elif state["status"] == "snoozed":
            item["status"] = "open"
        if state["status"] == "reopened":
            item["status"] = "open"


def _build_actions(conn, user) -> list[dict]:
    org = _org(user)
    driver_ids = _driver_ids(conn, user)
    actions: list[dict] = []

    # Passenger and employee requests: approval is the shortest path to a
    # canonical booking, so it is deliberately the first high-signal item.
    request_rows = conn.execute(
        """SELECT id, passenger_name, scheduled_at, pickup_json, dropoff_json
           FROM gap_passenger_booking_requests
           WHERE organization_id = ? AND status = 'pending'
           ORDER BY scheduled_at ASC, created_at ASC LIMIT 50""",
        (org,),
    ).fetchall()
    for row in request_rows:
        pickup = _as_json(row["pickup_json"], {})
        dropoff = _as_json(row["dropoff_json"], {})
        actions.append(_action(
            f"passenger_request:{row['id']}", category="booking", priority="high",
            title=f"Approve {row['passenger_name'] or 'passenger'}'s booking request",
            why="A passenger request is waiting for an operator decision before it can become a Fleet booking.",
            next_step="Review the route, policy and reporting time, then approve or reject it.", page="bookings",
            entity_type="passenger_booking_request", entity_id=row["id"], source="gap_passenger_booking_requests",
            due_at=row["scheduled_at"], blocking=True,
            signals=["pending_request", str(pickup.get("label") or pickup.get("address") or "pickup not labelled"), str(dropoff.get("label") or dropoff.get("address") or "drop-off not labelled")],
        ))

    # A booking with no active duty is an actionable allotment gap.  The
    # source remains domain_bookings; this view never creates a shadow trip.
    booking_rows = conn.execute(
        """SELECT b.id, b.booking_reference, b.scheduled_at, b.passenger_name, b.pickup_json, b.dropoff_json
           FROM domain_bookings b
           LEFT JOIN domain_duties d
             ON d.booking_id = b.id AND d.organization_id = b.organization_id
            AND d.status NOT IN ('cancelled', 'completed', 'closed', 'settled')
           WHERE b.organization_id = ? AND b.status NOT IN ('cancelled', 'completed') AND d.id IS NULL
           ORDER BY b.scheduled_at ASC, b.created_at ASC LIMIT 50""",
        (org,),
    ).fetchall()
    for row in booking_rows:
        actions.append(_action(
            f"booking_unassigned:{row['id']}", category="dispatch", priority="high",
            title=f"Find a vehicle for {row['booking_reference'] or 'booking'}",
            why="This booking has no active duty assignment, so the service promise is not yet covered.",
            next_step="Run availability and confirm a compliant driver and vehicle.", page="duties",
            entity_type="booking", entity_id=row["id"], source="domain_bookings",
            due_at=row["scheduled_at"], blocking=True,
            signals=["no_active_duty", row["passenger_name"] or "passenger not named"],
        ))

    # Missing driver or vehicle on a duty is distinct from a booking that has
    # not yet reached the duty ledger.  Distinguishing the two makes recovery
    # clear instead of showing a generic 'needs attention' badge.
    duty_rows = conn.execute(
        """SELECT id, booking_id, status, reporting_at, driver_id, vehicle_id
           FROM domain_duties
           WHERE organization_id = ? AND status NOT IN ('cancelled', 'completed', 'closed', 'settled')
           ORDER BY reporting_at ASC, created_at ASC LIMIT 100""",
        (org,),
    ).fetchall()
    for row in duty_rows:
        if driver_ids is not None and row["driver_id"] not in driver_ids:
            continue
        missing = []
        if not row["driver_id"]:
            missing.append("driver")
        if not row["vehicle_id"]:
            missing.append("vehicle")
        if missing:
            actions.append(_action(
                f"duty_assignment:{row['id']}", category="dispatch", priority="high",
                title=f"Assign {' and '.join(missing)} for duty {row['id'].split('_')[-1][:8].upper()}",
                why="The duty exists, but its assignment is incomplete and cannot be safely dispatched.",
                next_step="Open the duty and use availability or a controlled replacement.", page="duties",
                entity_type="duty", entity_id=row["id"], source="domain_duties",
                due_at=row["reporting_at"], blocking=True, signals=[f"missing_{value}" for value in missing],
            ))

    # Driver device readiness is a release and field-operability signal. For a
    # driver account it is private; for an operator it is aggregated to the
    # tenant but still contains no secrets or push tokens.
    readiness_sql = """SELECT id, user_id, device_id, readiness_status, blockers_json, checked_at
                       FROM gap_device_readiness WHERE organization_id = ? AND readiness_status = 'blocked'"""
    readiness_values = [org]
    if driver_ids is not None:
        readiness_sql += " AND user_id = ?"
        readiness_values.append(user["id"])
    readiness_sql += " ORDER BY checked_at DESC LIMIT 50"
    for row in conn.execute(readiness_sql, readiness_values).fetchall():
        blockers = _as_json(row["blockers_json"], [])
        blocker_text = ", ".join(str(value).replace("_", " ") for value in blockers[:3]) or "device permissions"
        actions.append(_action(
            f"device_readiness:{row['id']}", category="field", priority="high",
            title="Finish Driver device readiness",
            why=f"Push, background location or media readiness is blocked by {blocker_text}.",
            next_step="Open the Driver readiness checklist on the physical device and re-check permissions.", page="fleet",
            entity_type="device_readiness", entity_id=row["id"], source="gap_device_readiness",
            blocking=True, signals=blockers,
        ))

    # If an active driver has never checked a device, make that absence
    # visible instead of pretending the rollout is ready.
    if driver_ids is None:
        missing_readiness = conn.execute(
            """SELECT d.id, d.full_name FROM domain_drivers d
               WHERE d.organization_id = ? AND d.status IN ('available', 'active')
                 AND NOT EXISTS (SELECT 1 FROM gap_device_readiness r WHERE r.organization_id = d.organization_id AND r.user_id = d.user_id) 
               ORDER BY d.created_at ASC LIMIT 30""",
            (org,),
        ).fetchall()
        for row in missing_readiness:
            actions.append(_action(
                f"device_readiness_missing:{row['id']}", category="field", priority="medium",
                title=f"Check device readiness for {row['full_name'] or 'a driver'}",
                why="An active driver has no recorded device check, so push and background location cannot be assumed.",
                next_step="Invite the driver to run the readiness checklist before the next live duty.", page="fleet",
                entity_type="driver", entity_id=row["id"], source="domain_drivers", signals=["no_readiness_record"],
            ))

    # Alerts remain source-specific; acknowledgement in this cockpit does not
    # resolve the safety/driver event itself.
    alert_sql = """SELECT id, duty_id, alert_type, severity, occurred_at
                   FROM gap_driver_alert_events
                   WHERE organization_id = ? AND status = 'open'"""
    alert_values = [org]
    if driver_ids is not None:
        placeholders = ",".join("?" for _ in driver_ids) or "''"
        alert_sql += f" AND duty_id IN (SELECT id FROM domain_duties WHERE organization_id = ? AND driver_id IN ({placeholders}))"
        alert_values.extend([org, *sorted(driver_ids)])
    alert_sql += " ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 ELSE 2 END, occurred_at ASC LIMIT 50"
    for row in conn.execute(alert_sql, alert_values).fetchall():
        priority = "critical" if row["severity"] == "critical" else "high" if row["severity"] in {"high", "warning"} else "medium"
        actions.append(_action(
            f"driver_alert:{row['id']}", category="safety", priority=priority,
            title=f"Review {str(row['alert_type']).replace('_', ' ')} alert",
            why=f"A {row['severity']} driver alert is still open for duty {row['duty_id'].split('_')[-1][:8].upper()}.",
            next_step="Open the safety event, acknowledge the operator decision and resolve only after evidence is reviewed.", page="safety",
            entity_type="driver_alert", entity_id=row["id"], source="gap_driver_alert_events",
            due_at=row["occurred_at"], blocking=row["severity"] == "critical", signals=[row["alert_type"], row["severity"]],
        ))

    # GPS freshness is a field-health issue, not a guessed vehicle location.
    gps_sql = """SELECT d.id, d.driver_id, d.status, MAX(tp.recorded_at) AS last_seen
                 FROM domain_duties d LEFT JOIN domain_track_points tp ON tp.organization_id = d.organization_id AND tp.duty_id = d.id
                 WHERE d.organization_id = ? AND d.status IN ('en_route', 'started', 'in_progress', 'paused')"""
    gps_values = [org]
    if driver_ids is not None:
        placeholders = ",".join("?" for _ in driver_ids) or "''"
        gps_sql += f" AND d.driver_id IN ({placeholders})"
        gps_values.extend(sorted(driver_ids))
    gps_sql += " GROUP BY d.id ORDER BY d.reporting_at ASC LIMIT 50"
    for row in conn.execute(gps_sql, gps_values).fetchall():
        if not _is_stale(row["last_seen"]):
            continue
        actions.append(_action(
            f"gps_stale:{row['id']}", category="field", priority="high",
            title=f"Check GPS signal for duty {row['id'].split('_')[-1][:8].upper()}",
            why="The active duty has no location point in the last 15 minutes; Axiom does not infer a live position.",
            next_step="Contact the driver or inspect device readiness before treating the route as live.", page="safety",
            entity_type="duty", entity_id=row["id"], source="domain_track_points",
            blocking=True, signals=["gps_stale", f"last_seen:{row['last_seen'] or 'never'}"],
        ))

    # Finance action: show amount only from the canonical invoice and payment
    # tables; never manufacture an ageing value for an empty tenant.
    invoice_rows = conn.execute(
        """SELECT i.id, i.invoice_number, i.status, i.total_paise,
                  COALESCE((SELECT SUM(p.amount_paise) FROM domain_payments p WHERE p.invoice_id = i.id AND p.organization_id = i.organization_id AND p.status IN ('succeeded', 'paid')), 0) AS paid_paise
           FROM domain_invoices i
           WHERE i.organization_id = ? AND i.status IN ('issued', 'sent', 'overdue')
           ORDER BY i.created_at ASC LIMIT 50""",
        (org,),
    ).fetchall()
    for row in invoice_rows:
        outstanding = int(row["total_paise"] or 0) - int(row["paid_paise"] or 0)
        if outstanding <= 0:
            continue
        actions.append(_action(
            f"invoice_outstanding:{row['id']}", category="finance", priority="medium",
            title=f"Follow up invoice {row['invoice_number'] or row['id']}",
            why="The invoice is issued but the recorded successful payments do not cover its total.",
            next_step="Open Billing to reconcile the source invoice, payment request or approved auto-collect attempt.", page="billing",
            entity_type="invoice", entity_id=row["id"], source="domain_invoices",
            signals=[f"outstanding_paise:{outstanding}", row["status"]],
        ))

    # Evidence gap: a completed duty without any proof should be explicit
    # before finance or passenger close-out relies on it.
    proof_rows = conn.execute(
        """SELECT d.id, d.completed_at FROM domain_duties d
           WHERE d.organization_id = ? AND d.status IN ('completed', 'closed', 'settled')
             AND NOT EXISTS (SELECT 1 FROM domain_duty_proofs p WHERE p.organization_id = d.organization_id AND p.duty_id = d.id)
           ORDER BY d.completed_at DESC LIMIT 50""",
        (org,),
    ).fetchall()
    for row in proof_rows:
        if driver_ids is not None:
            assigned = conn.execute("SELECT driver_id FROM domain_duties WHERE id = ?", (row["id"],)).fetchone()
            if not assigned or assigned["driver_id"] not in driver_ids:
                continue
        actions.append(_action(
            f"duty_proof:{row['id']}", category="evidence", priority="medium",
            title=f"Complete proof for duty {row['id'].split('_')[-1][:8].upper()}",
            why="The duty is closed, but no proof record is attached to the canonical duty ledger.",
            next_step="Add the signed slip, odometer, OTP or receipt evidence before final billing review.", page="duties",
            entity_type="duty", entity_id=row["id"], source="domain_duty_proofs", signals=["no_proof_record"],
        ))

    # Setup action: one concise item replaces a wall of configuration cards.
    onboarding = conn.execute("SELECT completed_at, steps_json FROM domain_onboarding WHERE organization_id = ?", (org,)).fetchone()
    if not onboarding or not onboarding["completed_at"]:
        steps = _as_json(onboarding["steps_json"], {}) if onboarding else {}
        pending_steps = [key for key, value in steps.items() if isinstance(value, dict) and value.get("status") != "complete"]
        actions.append(_action(
            "workspace_setup", category="setup", priority="low",
            title="Finish workspace setup", why="A few tenant configuration steps are still open; policy and readiness decisions may remain unavailable.",
            next_step="Open the guided checklist and complete the next incomplete step.", page="settings",
            entity_type="organization", entity_id=org, source="domain_onboarding", signals=pending_steps or ["onboarding_incomplete"],
        ))

    # Production posture is honest and actionable: a mock-only workspace is
    # usable locally but not yet ready to make a production connectivity claim.
    healthy_providers = conn.execute(
        "SELECT COUNT(*) AS count FROM gap_provider_connections WHERE organization_id = ? AND status IN ('healthy', 'healthy_mock')",
        (org,),
    ).fetchone()["count"]
    if not healthy_providers:
        actions.append(_action(
            "provider_posture", category="readiness", priority="low",
            title="Validate one provider connection", why="No maps, messaging, payment, GPS or e-invoice connection has a recorded health check in this tenant.",
            next_step="Configure a replaceable adapter in mock or sandbox mode, then test it before enabling production traffic.", page="settings",
            entity_type="provider_connection", entity_id=org, source="gap_provider_connections", signals=["no_healthy_provider"],
        ))

    _append_open_actions(conn, user, actions)
    # Resolved actions disappear from the default queue.  Snoozed actions stay
    # hidden only until their explicit time; acknowledgements remain visible so
    # the operator can see ownership and continue the next step.
    actions = [item for item in actions if item["status"] != "resolved" and not item.get("snoozed_until")]
    actions.sort(key=lambda item: (PRIORITY_ORDER.get(item["priority"], 9), item.get("due_at") or "9999", item["title"]))
    return actions


def _summary(actions: list[dict], generated_at: str) -> dict:
    open_items = [item for item in actions if item.get("status") != "resolved"]
    return {
        "open": len(open_items),
        "critical": sum(item["priority"] == "critical" for item in open_items),
        "high": sum(item["priority"] == "high" for item in open_items),
        "blocking": sum(bool(item.get("blocking")) for item in open_items),
        "acknowledged": sum(item.get("status") == "acknowledged" for item in open_items),
        "contract_version": "2026-10-01",
        "generated_at": generated_at,
        "model": "deterministic_exception_projection",
    }


def _action_center(conn, user, method: str, route: str, payload: dict, ip: str):
    if route == "/api/workspace/next-actions" and method == "GET":
        actions = _build_actions(conn, user)
        generated_at = now_iso()
        limit = _limit(payload.get("_raw_route", route))
        return {"ok": True, "items": actions[:limit], "summary": _summary(actions, generated_at), "total_available": len(actions)}

    match = re.match(r"^/api/workspace/next-actions/([^/]+)/status$", route)
    if match and method == "POST":
        action_id = match.group(1)
        status = _text(payload, "status", maximum=20).lower()
        if status not in ACTION_STATUSES:
            raise DomainError(400, "status must be acknowledged, snoozed, resolved or reopened", "validation_error")
        snooze_until = _text(payload, "snooze_until", maximum=40) or None
        if status == "snoozed" and not snooze_until:
            snooze_until = (_now() + timedelta(hours=4)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        if status != "snoozed":
            snooze_until = None
        note = _text(payload, "note", maximum=500)
        state_id = new_id("action_state")
        now = now_iso()
        conn.execute(
            """INSERT INTO workspace_action_states(id, organization_id, user_id, action_id, status, snooze_until, note, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(organization_id, user_id, action_id) DO UPDATE SET status = excluded.status, snooze_until = excluded.snooze_until, note = excluded.note, updated_at = excluded.updated_at""",
            (state_id, _org(user), user["id"], action_id, "open" if status == "reopened" else status, snooze_until, note, now, now),
        )
        _audit(conn, user, f"workspace.action_{status}", "workspace_action", action_id, ip, {"snooze_until": snooze_until, "note": bool(note)})
        row = conn.execute(
            "SELECT action_id, status, snooze_until, note, updated_at FROM workspace_action_states WHERE organization_id = ? AND user_id = ? AND action_id = ?",
            (_org(user), user["id"], action_id),
        ).fetchone()
        return {"ok": True, "item": dict(row), "audit_reference": action_id}
    return None


def handle_command_center(conn, user, method: str, raw_route: str, payload: dict, ip: str):
    route = urlsplit(raw_route).path.rstrip("/") or "/"
    if route != "/api/workspace/next-actions" and not re.match(r"^/api/workspace/next-actions/[^/]+/status$", route):
        return None
    return _action_center(conn, user, method, route, {**payload, "_raw_route": raw_route}, ip)
