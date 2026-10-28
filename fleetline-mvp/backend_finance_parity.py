"""Finance, collection and report parity slice for Axiom Fleet."""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from backend_domain import DomainError, _assert_owned, _audit, _org, _require_role, _serialize, _text, new_id, now_iso
from provider_adapters import DEFAULT_PROVIDERS


INVOICE_MODES = {"per_duty", "monthly", "cover", "proforma"}
REPORT_TYPES = {"ageing", "duty_count", "vehicle_profitability", "customer_summary"}


def initialize_finance_parity_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS domain_invoice_runs (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            mode TEXT NOT NULL,
            period_start TEXT,
            period_end TEXT,
            status TEXT NOT NULL DEFAULT 'processing',
            requested_count INTEGER NOT NULL DEFAULT 0,
            generated_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            idempotency_key TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_dunning_actions (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            invoice_id TEXT NOT NULL,
            stage INTEGER NOT NULL DEFAULT 1,
            channel TEXT NOT NULL DEFAULT 'email',
            status TEXT NOT NULL DEFAULT 'queued',
            provider_reference TEXT NOT NULL DEFAULT '',
            scheduled_at TEXT,
            sent_at TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, invoice_id, stage)
        );
        CREATE TABLE IF NOT EXISTS domain_report_definitions (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            name TEXT NOT NULL,
            report_type TEXT NOT NULL,
            filters_json TEXT NOT NULL DEFAULT '{}',
            columns_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'active',
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, name)
        );
        CREATE TABLE IF NOT EXISTS domain_export_profiles (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            name TEXT NOT NULL,
            target TEXT NOT NULL DEFAULT 'csv',
            mapping_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'active',
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, name)
        );
        CREATE TABLE IF NOT EXISTS domain_finance_exports (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            export_type TEXT NOT NULL,
            profile_id TEXT,
            status TEXT NOT NULL DEFAULT 'ready',
            content TEXT NOT NULL DEFAULT '',
            expires_at TEXT NOT NULL,
            created_by TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_invoice_runs_org ON domain_invoice_runs(organization_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_dunning_org_invoice ON domain_dunning_actions(organization_id, invoice_id, stage);
        CREATE INDEX IF NOT EXISTS idx_report_definitions_org ON domain_report_definitions(organization_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_finance_exports_org ON domain_finance_exports(organization_id, created_at DESC);
        """
    )
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(domain_invoices)").fetchall()}
    for column, definition in {
        "invoice_type": "TEXT NOT NULL DEFAULT 'tax'",
        "due_at": "TEXT",
        "company_id": "TEXT",
        "gst_entity_id": "TEXT",
        "letterhead_id": "TEXT",
    }.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE domain_invoices ADD COLUMN {column} {definition}")


def _staff(user):
    if user["role"] not in {"vendor", "corporate"}:
        raise DomainError(403, "Finance workflows are restricted to organization operators", "role_forbidden")


def _json(row, field, fallback):
    try:
        return json.loads(row[field]) if row and row[field] else fallback
    except (TypeError, ValueError):
        return fallback


def _invoice_payload(conn, invoice_id: str, org: str):
    row = _assert_owned(conn, "domain_invoices", invoice_id, org)
    item = _serialize(row, ("immutable_snapshot_json",))
    item["lines"] = [_serialize(line) for line in conn.execute("SELECT * FROM domain_invoice_lines WHERE invoice_id = ? ORDER BY created_at", (invoice_id,)).fetchall()]
    return item


def _candidate_duties(conn, org: str, payload: dict):
    clauses = ["d.organization_id = ?", "d.status = 'completed'", "i.id IS NULL"]
    values = [org]
    if payload.get("duty_ids") and isinstance(payload["duty_ids"], list):
        marks = ",".join("?" for _ in payload["duty_ids"]); clauses.append(f"d.id IN ({marks})"); values.extend(str(value) for value in payload["duty_ids"])
    if payload.get("period_start"):
        clauses.append("coalesce(d.completed_at, d.updated_at) >= ?"); values.append(str(payload["period_start"]))
    if payload.get("period_end"):
        clauses.append("coalesce(d.completed_at, d.updated_at) <= ?"); values.append(str(payload["period_end"]))
    if payload.get("customer_id"):
        clauses.append("b.customer_id = ?"); values.append(str(payload["customer_id"]))
    return conn.execute(f"SELECT d.*, b.customer_id, b.booking_reference, b.pickup_json, b.vehicle_group_code, b.duty_type FROM domain_duties d JOIN domain_bookings b ON b.id = d.booking_id LEFT JOIN domain_invoices i ON i.duty_id = d.id AND i.organization_id = d.organization_id WHERE {' AND '.join(clauses)} ORDER BY coalesce(d.completed_at, d.updated_at), d.id", values).fetchall()


def _snapshot(conn, duty):
    try:
        return json.loads(duty["calculation_snapshot_json"] or "{}")
    except (TypeError, ValueError):
        return {}


def _create_invoice_for_duties(conn, user, org: str, duties, mode: str, payload: dict, ip: str):
    if not duties:
        raise DomainError(409, "No completed uninvoiced duties match the requested period", "no_billable_duties")
    snapshots = [_snapshot(conn, duty) for duty in duties]
    subtotal = sum(int(snapshot.get("subtotal_paise") or 0) for snapshot in snapshots)
    tax = sum(int(snapshot.get("tax_paise") or 0) for snapshot in snapshots)
    base_total = sum(int(snapshot.get("total_paise") or 0) for snapshot in snapshots)
    if base_total <= 0:
        raise DomainError(409, "Matched duties do not have billable calculation snapshots", "calculation_required")
    # Fuel is a customer contract rule, not an operational fuel expense.  The
    # calculation is kept beside the invoice transaction so replaying an
    # invoice run cannot silently omit or duplicate the surcharge line.
    from backend_booking_parity import calculate_fuel_surcharge
    fuel_by_duty = []
    fuel_surcharge = 0
    for duty, snapshot in zip(duties, snapshots):
        pickup = {}
        try:
            pickup = json.loads(duty["pickup_json"] or "{}")
        except (TypeError, ValueError):
            pickup = {}
        fuel = calculate_fuel_surcharge(conn, org, duty["customer_id"], duty["vehicle_group_code"], {
            **snapshot,
            "distance_km": snapshot.get("distance_km", snapshot.get("distance", 0)),
            "city": pickup.get("city") or pickup.get("label", ""),
            "vehicle_group_code": duty["vehicle_group_code"],
            "duty_type": duty["duty_type"],
            "transport_total_paise": int(snapshot.get("subtotal_paise") or snapshot.get("total_paise") or 0),
        })
        fuel_by_duty.append(fuel)
        fuel_surcharge += int(fuel.get("amount_paise") or 0)
    subtotal += fuel_surcharge
    total = base_total + fuel_surcharge
    try:
        for duty in duties:
            audit = conn.execute("SELECT audit_status, trust_score FROM domain_duty_trust_audits WHERE duty_id = ? AND organization_id = ?", (duty["id"], org)).fetchone()
            if audit and audit["audit_status"] == "NEEDS_AUDIT":
                raise DomainError(422, f"Duty {duty['id']} has unresolved audit flags (Trust Score: {audit['trust_score']}). Resolve discrepancy before generating invoice.", "audit_resolution_required")
    except sqlite3.OperationalError:
        pass
    invoice_id = new_id("inv")
    sequence = conn.execute("SELECT COUNT(*) + 1 AS n FROM domain_invoices WHERE organization_id = ?", (org,)).fetchone()["n"]
    invoice_number = _text(payload, "invoice_number") or f"INV-{datetime.now(timezone.utc):%Y}-{sequence:03d}"
    now = now_iso()
    due_at = _text(payload, "due_at") or None
    conn.execute("INSERT INTO domain_invoices(id, organization_id, customer_id, duty_id, invoice_number, status, subtotal_paise, tax_paise, total_paise, fuel_surcharge_paise, pricing_snapshot_json, invoice_type, due_at, company_id, gst_entity_id, letterhead_id, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (invoice_id, org, duties[0]["customer_id"], duties[0]["id"] if mode == "per_duty" else None, invoice_number, subtotal, tax, total, fuel_surcharge, json.dumps({"fuel_surcharge": fuel_by_duty}), "proforma" if mode == "proforma" else "tax", due_at, payload.get("company_id"), payload.get("gst_entity_id"), payload.get("letterhead_id"), user["id"], now, now))
    if mode == "per_duty":
        line_groups = [(duties[0], snapshots[0], fuel_by_duty[0])]
    else:
        line_groups = [(duty, snapshot, fuel) for duty, snapshot, fuel in zip(duties, snapshots, fuel_by_duty)]
    for duty, snapshot, fuel in line_groups:
        lines = snapshot.get("lines") if isinstance(snapshot.get("lines"), list) else []
        if not lines:
            lines = [{"code": "duty", "label": f"Duty {duty['booking_reference']}", "quantity": 1, "unit_paise": int(snapshot.get("total_paise") or 0), "amount_paise": int(snapshot.get("total_paise") or 0)}]
        for line in lines:
            conn.execute("INSERT INTO domain_invoice_lines(id, invoice_id, code, label, quantity, unit_paise, amount_paise, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (new_id("line"), invoice_id, _text(line, "code", "duty", 60), _text(line, "label", "Duty", 200), int(line.get("quantity") or 1), int(line.get("unit_paise") or 0), int(line.get("amount_paise") or 0), now))
        if int(fuel.get("amount_paise") or 0) > 0:
            conn.execute("INSERT INTO domain_invoice_lines(id, invoice_id, code, label, quantity, unit_paise, amount_paise, created_at) VALUES (?, ?, 'fuel_surcharge', ?, 1, ?, ?, ?)", (new_id("line"), invoice_id, f"Fuel surcharge {duty['booking_reference']}", int(fuel["amount_paise"]), int(fuel["amount_paise"]), now))
    _audit(conn, user, f"invoice.{mode}_generated", "invoice", invoice_id, ip, {"duty_count": len(duties), "total_paise": total, "fuel_surcharge_paise": fuel_surcharge})
    return _invoice_payload(conn, invoice_id, org)


def _generate_invoices(conn, user, payload: dict, ip: str):
    org = _org(user); _staff(user)
    mode = _text(payload, "mode", "per_duty", 20).lower()
    if mode not in INVOICE_MODES:
        raise DomainError(400, "mode must be per_duty, monthly, cover or proforma", "validation_error")
    key = _text(payload, "idempotency_key", maximum=160) or None
    if key:
        existing = conn.execute("SELECT * FROM domain_invoice_runs WHERE organization_id = ? AND idempotency_key = ?", (org, key)).fetchone()
        if existing:
            return {"ok": True, "item": _serialize(existing, ("payload_json",)), "idempotent": True}
    duties = _candidate_duties(conn, org, payload)
    run_id = new_id("invoice_run"); now = now_iso()
    conn.execute("INSERT INTO domain_invoice_runs(id, organization_id, mode, period_start, period_end, status, requested_count, idempotency_key, payload_json, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'processing', ?, ?, ?, ?, ?, ?)", (run_id, org, mode, payload.get("period_start"), payload.get("period_end"), len(duties), key, json.dumps(payload), user["id"], now, now))
    generated = []
    failures = 0
    if mode == "per_duty":
        for duty in duties:
            try:
                generated.append(_create_invoice_for_duties(conn, user, org, [duty], mode, payload, ip))
            except DomainError:
                failures += 1
    else:
        try:
            generated.append(_create_invoice_for_duties(conn, user, org, duties, mode, payload, ip))
        except DomainError:
            failures += 1
    status = "completed" if failures == 0 else "partial" if generated else "failed"
    conn.execute("UPDATE domain_invoice_runs SET status = ?, generated_count = ?, failed_count = ?, updated_at = ? WHERE id = ?", (status, len(generated), failures, now_iso(), run_id))
    return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_invoice_runs WHERE id = ?", (run_id,)).fetchone(), ("payload_json",)), "invoices": generated}


def _run_dunning(conn, user, payload: dict, ip: str):
    org = _org(user); _staff(user)
    now = now_iso(); channel = _text(payload, "channel", "email", 20)
    invoices = conn.execute("SELECT * FROM domain_invoices WHERE organization_id = ? AND status IN ('issued','sent','partially_paid') AND due_at IS NOT NULL AND due_at < ? ORDER BY due_at", (org, now)).fetchall()
    results = []
    for invoice in invoices:
        existing = conn.execute("SELECT COALESCE(MAX(stage), 0) AS stage FROM domain_dunning_actions WHERE organization_id = ? AND invoice_id = ?", (org, invoice["id"])).fetchone()["stage"]
        stage = int(existing) + 1
        message = DEFAULT_PROVIDERS.messaging.send(channel=channel, recipient=_text(payload, "recipient", "finance@customer.local", 254), template=f"overdue_reminder_{stage}", variables={"invoice_number": invoice["invoice_number"], "total_paise": invoice["total_paise"], "stage": stage}, idempotency_key=f"dunning:{invoice['id']}:{stage}")
        action_id = new_id("dunning")
        conn.execute("INSERT INTO domain_dunning_actions(id, organization_id, invoice_id, stage, channel, status, provider_reference, sent_at, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (action_id, org, invoice["id"], stage, channel, message.status, message.reference, now if message.status in {"queued", "sent", "succeeded"} else None, user["id"], now))
        results.append({"invoice_id": invoice["id"], "invoice_number": invoice["invoice_number"], "stage": stage, "status": message.status, "provider_reference": message.reference})
    _audit(conn, user, "collections.dunning_run", "organization", org, ip, {"processed": len(results), "channel": channel})
    return {"ok": True, "processed": len(results), "items": results, "run_at": now}


def _ageing(conn, user, query):
    org = _org(user)
    rows = conn.execute("SELECT i.*, c.name AS customer_name FROM domain_invoices i LEFT JOIN domain_customers c ON c.id = i.customer_id WHERE i.organization_id = ? AND i.status NOT IN ('paid','void') ORDER BY i.due_at", (org,)).fetchall()
    now = datetime.now(timezone.utc)
    buckets = {"current": [], "1_30": [], "31_60": [], "61_90": [], "90_plus": []}
    for row in rows:
        due = row["due_at"]
        age = 0
        if due:
            try:
                parsed = datetime.fromisoformat(str(due).replace("Z", "+00:00")); parsed = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc); age = max(0, (now - parsed).days)
            except ValueError: age = 0
        bucket = "current" if age == 0 else "1_30" if age <= 30 else "31_60" if age <= 60 else "61_90" if age <= 90 else "90_plus"
        buckets[bucket].append({"invoice_id": row["id"], "invoice_number": row["invoice_number"], "customer_name": row["customer_name"], "total_paise": row["total_paise"], "age_days": age})
    return {"ok": True, "period": query.get("period", ["current"])[0], "buckets": {key: {"count": len(value), "total_paise": sum(int(item["total_paise"] or 0) for item in value), "items": value} for key, value in buckets.items()}}


def _report_definition(conn, user, route, method, payload, ip):
    match = re.match(r"^/api/reports/definitions(?:/([^/]+)(?:/run)?)?$", route)
    if not match: return None
    org = _org(user); _staff(user)
    definition_id = match.group(1)
    if method == "GET":
        rows = conn.execute("SELECT * FROM domain_report_definitions WHERE organization_id = ? ORDER BY created_at DESC", (org,)).fetchall(); return {"ok": True, "items": [_serialize(row, ("filters_json", "columns_json")) for row in rows]}
    if not definition_id and method == "POST":
        report_type = _text(payload, "report_type", "ageing", 40)
        if report_type not in REPORT_TYPES: raise DomainError(400, "Unsupported report type", "validation_error")
        report_id = new_id("report"); now = now_iso(); conn.execute("INSERT INTO domain_report_definitions(id, organization_id, name, report_type, filters_json, columns_json, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (report_id, org, _text(payload, "name", report_type, 120), report_type, json.dumps(payload.get("filters") if isinstance(payload.get("filters"), dict) else {}), json.dumps(payload.get("columns") if isinstance(payload.get("columns"), list) else []), user["id"], now, now)); _audit(conn, user, "report.definition_created", "report_definition", report_id, ip, {"report_type": report_type}); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_report_definitions WHERE id = ?", (report_id,)).fetchone(), ("filters_json", "columns_json"))}
    if definition_id and route.endswith("/run") and method == "POST":
        row = conn.execute("SELECT * FROM domain_report_definitions WHERE id = ? AND organization_id = ?", (definition_id, org)).fetchone()
        if not row: raise DomainError(404, "Report definition not found", "not_found")
        report_type = row["report_type"]
        if report_type == "ageing": return _ageing(conn, user, {"period": ["definition"]})
        if report_type == "duty_count":
            data = conn.execute("SELECT status, COUNT(*) AS count FROM domain_duties WHERE organization_id = ? GROUP BY status", (org,)).fetchall(); return {"ok": True, "report_type": report_type, "rows": [_serialize(item) for item in data]}
        if report_type == "customer_summary":
            data = conn.execute("SELECT c.name, COUNT(b.id) AS bookings, COALESCE(SUM(i.total_paise),0) AS invoiced_paise FROM domain_customers c LEFT JOIN domain_bookings b ON b.customer_id = c.id AND b.organization_id = c.organization_id LEFT JOIN domain_invoices i ON i.customer_id = c.id AND i.organization_id = c.organization_id WHERE c.organization_id = ? GROUP BY c.id ORDER BY c.name", (org,)).fetchall(); return {"ok": True, "report_type": report_type, "rows": [_serialize(item) for item in data]}
        data = conn.execute("SELECT v.registration_number, COUNT(d.id) AS duties, COALESCE(SUM(i.total_paise),0) AS revenue_paise FROM domain_vehicles v LEFT JOIN domain_duties d ON d.vehicle_id = v.id AND d.organization_id = v.organization_id LEFT JOIN domain_invoices i ON i.duty_id = d.id AND i.organization_id = d.organization_id WHERE v.organization_id = ? GROUP BY v.id ORDER BY v.registration_number", (org,)).fetchall(); return {"ok": True, "report_type": report_type, "rows": [_serialize(item) for item in data]}
    raise DomainError(404, "Report definition route not found", "not_found")


def _export_profile(conn, user, route, method, payload, ip):
    if route != "/api/export-profiles" and not route.startswith("/api/export-profiles/"):
        return None
    org = _org(user); _staff(user)
    if route == "/api/export-profiles" and method in {"GET", "POST"}:
        if method == "GET": return {"ok": True, "items": [_serialize(row, ("mapping_json",)) for row in conn.execute("SELECT * FROM domain_export_profiles WHERE organization_id = ? ORDER BY created_at DESC", (org,)).fetchall()]}
        target = _text(payload, "target", "csv", 30).lower()
        if target not in {"csv", "json"}: raise DomainError(400, "Only CSV and JSON export profiles are supported", "unsupported_export_format")
        profile_id = new_id("export_profile"); now = now_iso(); conn.execute("INSERT INTO domain_export_profiles(id, organization_id, name, target, mapping_json, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (profile_id, org, _text(payload, "name", "CSV export", 120), target, json.dumps(payload.get("mapping") if isinstance(payload.get("mapping"), dict) else {}), user["id"], now)); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_export_profiles WHERE id = ?", (profile_id,)).fetchone(), ("mapping_json",))}
    run = re.match(r"^/api/export-profiles/([^/]+)/run$", route)
    if run and method == "POST":
        profile = conn.execute("SELECT * FROM domain_export_profiles WHERE id = ? AND organization_id = ?", (run.group(1), org)).fetchone()
        if not profile: raise DomainError(404, "Export profile not found", "not_found")
        output = io.StringIO(); writer = csv.writer(output); writer.writerow(["voucher_number", "invoice_number", "date", "amount_paise", "customer"])
        rows = conn.execute("SELECT i.invoice_number, i.created_at, i.total_paise, c.name FROM domain_invoices i LEFT JOIN domain_customers c ON c.id = i.customer_id WHERE i.organization_id = ? ORDER BY i.created_at", (org,)).fetchall()
        for row in rows: writer.writerow([row["invoice_number"], row["invoice_number"], row["created_at"], row["total_paise"], row["name"] or ""])
        export_id = new_id("finance_export"); expires = f"{datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')}"; conn.execute("INSERT INTO domain_finance_exports(id, organization_id, export_type, profile_id, content, expires_at, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (export_id, org, profile["target"], profile["id"], output.getvalue(), expires, user["id"], now_iso())); return {"ok": True, "item": {"id": export_id, "export_type": profile["target"], "status": "ready", "content": output.getvalue()}}
    return None


def handle_finance_parity(conn, user, method: str, raw_route: str, payload: dict, ip: str):
    route = urlsplit(raw_route).path.rstrip("/") or "/"
    query = parse_qs(urlsplit(raw_route).query)
    if route == "/api/invoices/generate" and method == "POST": return _generate_invoices(conn, user, payload, ip)
    if route == "/api/invoice-runs" and method == "GET":
        org = _org(user); rows = conn.execute("SELECT * FROM domain_invoice_runs WHERE organization_id = ? ORDER BY created_at DESC LIMIT 100", (org,)).fetchall(); return {"ok": True, "items": [_serialize(row, ("payload_json",)) for row in rows]}
    if route == "/api/collections/dunning" and method == "GET":
        org = _org(user); rows = conn.execute("SELECT * FROM domain_dunning_actions WHERE organization_id = ? ORDER BY created_at DESC LIMIT 200", (org,)).fetchall(); return {"ok": True, "items": [_serialize(row) for row in rows]}
    if route == "/api/collections/dunning/run" and method == "POST": return _run_dunning(conn, user, payload, ip)
    if route == "/api/reports/ageing" and method == "GET": return _ageing(conn, user, query)
    result = _report_definition(conn, user, route, method, payload, ip)
    if result is not None: return result
    result = _export_profile(conn, user, route, method, payload, ip)
    if result is not None: return result
    return None
