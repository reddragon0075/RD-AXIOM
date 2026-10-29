"""Additive finance-control, report-builder, import and public feedback slice.

This module extends the completed supplier-finance, finance-reporting and
feedback foundations without creating a second invoice, supplier-bill or
feedback source of truth. It deliberately skips Tally/Tally Prime exports;
CSV/bank-file and signed download boundaries remain provider-neutral.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

from backend_domain import DomainError, _assert_owned, _audit, _org, _serialize, _text, new_id, now_iso


def initialize_finance_controls_schema(conn) -> None:
    # Older local databases predate the company-level booking selector. Keep
    # the additive migration dependency-free and harmless on fresh databases.
    try:
        conn.execute("ALTER TABLE domain_bookings ADD COLUMN company_id TEXT")
    except sqlite3.OperationalError:
        pass
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS finance_supplier_payment_requests (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, supplier_id TEXT, settlement_id TEXT, advance_id TEXT,
            amount_paise INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'INR', status TEXT NOT NULL DEFAULT 'requested',
            requested_by TEXT, approved_by TEXT, approved_at TEXT, due_at TEXT, payment_reference TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}', idempotency_key TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS finance_supplier_advances (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, supplier_id TEXT, amount_paise INTEGER NOT NULL,
            purpose TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'requested', requested_by TEXT, approved_by TEXT,
            approved_at TEXT, recovered_paise INTEGER NOT NULL DEFAULT 0, evidence_json TEXT NOT NULL DEFAULT '{}',
            idempotency_key TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS finance_payment_executions (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, request_id TEXT NOT NULL, amount_paise INTEGER NOT NULL,
            method TEXT NOT NULL DEFAULT 'mock_bank', status TEXT NOT NULL DEFAULT 'queued', provider_reference TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT, executed_at TEXT, metadata_json TEXT NOT NULL DEFAULT '{}', created_by TEXT, created_at TEXT NOT NULL,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS finance_settlement_approvals (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, settlement_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            comments TEXT NOT NULL DEFAULT '', requested_by TEXT, decided_by TEXT, decided_at TEXT, created_at TEXT NOT NULL,
            UNIQUE(organization_id, settlement_id)
        );
        CREATE TABLE IF NOT EXISTS finance_driver_payouts (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, driver_id TEXT NOT NULL, period_start TEXT NOT NULL,
            period_end TEXT NOT NULL, gross_paise INTEGER NOT NULL DEFAULT 0, deductions_paise INTEGER NOT NULL DEFAULT 0,
            net_paise INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending_approval', bank_reference TEXT NOT NULL DEFAULT '',
            approved_by TEXT, approved_at TEXT, disbursed_at TEXT, idempotency_key TEXT, metadata_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT '', UNIQUE(organization_id, driver_id, period_start, period_end), UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS finance_payroll_exports (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, payroll_run_id TEXT, export_format TEXT NOT NULL DEFAULT 'bank_csv',
            status TEXT NOT NULL DEFAULT 'ready', content TEXT NOT NULL DEFAULT '', download_token_hash TEXT NOT NULL UNIQUE,
            signed_url TEXT NOT NULL DEFAULT '', expires_at TEXT NOT NULL, created_by TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS finance_payroll_compliance_reports (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL,
            report_type TEXT NOT NULL DEFAULT 'statutory_deductions', status TEXT NOT NULL DEFAULT 'ready', deductions_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT, created_at TEXT NOT NULL, UNIQUE(organization_id, period_start, period_end, report_type)
        );
        CREATE TABLE IF NOT EXISTS finance_fuel_stations (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL, city TEXT NOT NULL DEFAULT '',
            address TEXT NOT NULL DEFAULT '', fuel_types_json TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'active',
            created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(organization_id, code)
        );
        CREATE TABLE IF NOT EXISTS finance_fuel_prices (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, station_id TEXT NOT NULL, fuel_type TEXT NOT NULL,
            price_paise INTEGER NOT NULL, effective_from TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'operator', created_by TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS finance_reconciliations (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, reconciliation_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
            period_start TEXT, period_end TEXT, filters_json TEXT NOT NULL DEFAULT '{}', summary_json TEXT NOT NULL DEFAULT '{}',
            unmatched_json TEXT NOT NULL DEFAULT '[]', resolved_count INTEGER NOT NULL DEFAULT 0, created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS report_builder_configs (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, name TEXT NOT NULL, report_type TEXT NOT NULL,
            filters_json TEXT NOT NULL DEFAULT '{}', columns_json TEXT NOT NULL DEFAULT '[]', sort_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'active', created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(organization_id, name)
        );
        CREATE TABLE IF NOT EXISTS report_favorites (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, config_id TEXT NOT NULL, name TEXT NOT NULL, refresh_cadence TEXT NOT NULL DEFAULT 'manual',
            last_run_at TEXT, created_by TEXT, created_at TEXT NOT NULL, UNIQUE(organization_id, name)
        );
        CREATE TABLE IF NOT EXISTS report_export_jobs (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, config_id TEXT, export_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
            row_count INTEGER NOT NULL DEFAULT 0, content TEXT NOT NULL DEFAULT '', storage_path TEXT NOT NULL DEFAULT '', signed_url TEXT NOT NULL DEFAULT '',
            download_token_hash TEXT NOT NULL UNIQUE, expires_at TEXT NOT NULL, error TEXT NOT NULL DEFAULT '', created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS finance_import_templates (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_type TEXT NOT NULL, name TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
            columns_json TEXT NOT NULL DEFAULT '[]', validation_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'active', created_by TEXT, created_at TEXT NOT NULL,
            UNIQUE(organization_id, entity_type, name, version)
        );
        CREATE TABLE IF NOT EXISTS finance_import_jobs (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, template_id TEXT, entity_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'preview',
            rows_json TEXT NOT NULL DEFAULT '[]', errors_json TEXT NOT NULL DEFAULT '[]', corrected_rows_json TEXT NOT NULL DEFAULT '[]',
            total_rows INTEGER NOT NULL DEFAULT 0, valid_rows INTEGER NOT NULL DEFAULT 0, created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS feedback_public_links (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, form_id TEXT, duty_id TEXT, booking_id TEXT, customer_id TEXT,
            token_hash TEXT NOT NULL UNIQUE, label TEXT NOT NULL DEFAULT '', expires_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
            allow_anonymous INTEGER NOT NULL DEFAULT 1, response_id TEXT, created_by TEXT, created_at TEXT NOT NULL, submitted_at TEXT
        );
        CREATE TABLE IF NOT EXISTS feedback_notifications (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, feedback_link_id TEXT, response_id TEXT, channel TEXT NOT NULL DEFAULT 'email',
            recipient TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT,
            provider_reference TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS feedback_analytics_snapshots (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, period_key TEXT NOT NULL, average_rating REAL NOT NULL DEFAULT 0,
            response_count INTEGER NOT NULL DEFAULT 0, positive_count INTEGER NOT NULL DEFAULT 0, negative_count INTEGER NOT NULL DEFAULT 0,
            tags_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, UNIQUE(organization_id, period_key)
        );
        CREATE TABLE IF NOT EXISTS feedback_corrective_actions (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, response_id TEXT, rule_id TEXT, action_type TEXT NOT NULL,
            owner_id TEXT, status TEXT NOT NULL DEFAULT 'open', priority TEXT NOT NULL DEFAULT 'medium', due_at TEXT, notes TEXT NOT NULL DEFAULT '',
            created_by TEXT, created_at TEXT NOT NULL, resolved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS feedback_delivery_policies (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, customer_id TEXT, name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active', trigger_event TEXT NOT NULL DEFAULT 'duty_completed', channels_json TEXT NOT NULL DEFAULT '["sms","email","whatsapp"]',
            fallback_channels_json TEXT NOT NULL DEFAULT '["email"]', delay_minutes INTEGER NOT NULL DEFAULT 0, quiet_hours_json TEXT NOT NULL DEFAULT '{}',
            template_keys_json TEXT NOT NULL DEFAULT '{}', max_attempts INTEGER NOT NULL DEFAULT 5, created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(organization_id, customer_id, name)
        );
        CREATE TABLE IF NOT EXISTS feedback_escalation_policies (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, customer_id TEXT, name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active', conditions_json TEXT NOT NULL DEFAULT '{"rating_lte":2}', action_type TEXT NOT NULL DEFAULT 'investigate',
            priority TEXT NOT NULL DEFAULT 'high', owner_id TEXT, due_minutes INTEGER NOT NULL DEFAULT 60, channels_json TEXT NOT NULL DEFAULT '[]',
            created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(organization_id, customer_id, name)
        );
        CREATE TABLE IF NOT EXISTS feedback_delivery_attempts (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, notification_id TEXT NOT NULL, attempt_number INTEGER NOT NULL,
            provider TEXT NOT NULL DEFAULT 'mock', channel TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued', provider_reference TEXT NOT NULL DEFAULT '',
            provider_event_id TEXT, error_code TEXT NOT NULL DEFAULT '', error_message TEXT NOT NULL DEFAULT '', response_payload_json TEXT NOT NULL DEFAULT '{}',
            next_attempt_at TEXT, created_at TEXT NOT NULL, UNIQUE(notification_id, attempt_number), UNIQUE(provider, provider_event_id)
        );
        CREATE TABLE IF NOT EXISTS feedback_provider_events (
            id TEXT PRIMARY KEY, organization_id TEXT, provider TEXT NOT NULL, external_event_id TEXT NOT NULL, event_type TEXT NOT NULL,
            provider_reference TEXT NOT NULL DEFAULT '', payload_json TEXT NOT NULL DEFAULT '{}', processed_at TEXT, created_at TEXT NOT NULL,
            UNIQUE(provider, external_event_id)
        );
        CREATE INDEX IF NOT EXISTS idx_feedback_delivery_policies_customer ON feedback_delivery_policies(organization_id,customer_id,status);
        CREATE INDEX IF NOT EXISTS idx_feedback_escalation_policies_customer ON feedback_escalation_policies(organization_id,customer_id,status);
        CREATE INDEX IF NOT EXISTS idx_feedback_delivery_attempts_due ON feedback_delivery_attempts(organization_id,status,next_attempt_at);
        CREATE INDEX IF NOT EXISTS idx_feedback_provider_events_reference ON feedback_provider_events(provider,provider_reference);
        CREATE INDEX IF NOT EXISTS idx_payment_requests_org_status ON finance_supplier_payment_requests(organization_id,status,created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_supplier_advances_org_status ON finance_supplier_advances(organization_id,status,created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_payment_exec_org_request ON finance_payment_executions(organization_id,request_id,created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_fuel_prices_station ON finance_fuel_prices(organization_id,station_id,effective_from DESC);
        CREATE INDEX IF NOT EXISTS idx_report_jobs_org_status ON report_export_jobs(organization_id,status,created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_import_jobs_org_status ON finance_import_jobs(organization_id,status,created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_feedback_public_hash ON feedback_public_links(token_hash,status,expires_at);
        CREATE INDEX IF NOT EXISTS idx_feedback_notifications_due ON feedback_notifications(organization_id,status,next_attempt_at);
        CREATE INDEX IF NOT EXISTS idx_feedback_actions_status ON feedback_corrective_actions(organization_id,status,created_at DESC);
        """
    )
    for statement in (
        "ALTER TABLE feedback_public_links ADD COLUMN customer_id TEXT",
        "ALTER TABLE feedback_notifications ADD COLUMN policy_id TEXT",
        "ALTER TABLE feedback_notifications ADD COLUMN attempt_limit INTEGER NOT NULL DEFAULT 5",
        "ALTER TABLE feedback_notifications ADD COLUMN last_provider_event_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE feedback_notifications ADD COLUMN bounce_code TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE feedback_notifications ADD COLUMN dead_lettered_at TEXT",
    ):
        try:
            conn.execute(statement)
        except sqlite3.OperationalError:
            pass
    try:
        conn.execute("ALTER TABLE finance_driver_payouts ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass


def _staff(user):
    if user["role"] not in {"vendor", "corporate"}:
        raise DomainError(403, "This finance or reporting workflow requires an organization operator", "role_forbidden")


def _int(payload, key, default=0):
    try:
        return int(payload.get(key, default) or default)
    except (TypeError, ValueError):
        raise DomainError(400, f"{key} must be an integer", "validation_error")


def _list(conn, table, org, fields=()):
    return [_serialize(row, fields) for row in conn.execute(f"SELECT * FROM {table} WHERE organization_id = ? ORDER BY created_at DESC LIMIT 500", (org,)).fetchall()]


def _owned_optional(conn, table, value, org):
    if value:
        _assert_owned(conn, table, value, org)


def _key(payload):
    return _text(payload, "idempotency_key", maximum=160) or None


def _existing(conn, table, org, key):
    if not key:
        return None
    return conn.execute(f"SELECT * FROM {table} WHERE organization_id = ? AND idempotency_key = ?", (org, key)).fetchone()


def _finance_collection(conn, user, method, route, payload, ip):
    collection = {
        "/api/supplier-payment-requests": ("finance_supplier_payment_requests", ("metadata_json",)),
        "/api/supplier-advances": ("finance_supplier_advances", ("evidence_json",)),
        "/api/driver-payouts/requests": ("finance_driver_payouts", ("metadata_json",)),
        "/api/supplier-settlement-approvals": ("finance_settlement_approvals", ()),
        "/api/petty-cash/reconciliations": ("finance_reconciliations", ("filters_json", "summary_json", "unmatched_json")),
        "/api/payroll/compliance": ("finance_payroll_compliance_reports", ("deductions_json",)),
        "/api/fuel-stations": ("finance_fuel_stations", ("fuel_types_json",)),
        "/api/fuel-prices": ("finance_fuel_prices", ()),
        "/api/finance/reconciliations": ("finance_reconciliations", ("filters_json", "summary_json", "unmatched_json")),
        "/api/reports/builder": ("report_builder_configs", ("filters_json", "columns_json", "sort_json")),
        "/api/reports/favorites": ("report_favorites", ()),
        "/api/reporting/import-templates": ("finance_import_templates", ("columns_json", "validation_json")),
        "/api/feedback/notifications": ("feedback_notifications", ()),
        "/api/feedback/corrective-actions": ("feedback_corrective_actions", ()),
    }
    if route not in collection or method not in {"GET", "POST"}:
        return None
    org = _org(user); _staff(user)
    table, fields = collection[route]
    if method == "GET":
        items = _list(conn, table, org, fields)
        if table == "finance_driver_payouts":
            for item in items:
                drv = conn.execute("SELECT full_name, phone, driver_type FROM domain_drivers WHERE id = ?", (item.get("driver_id"),)).fetchone()
                if drv:
                    item["driver_name"] = drv["full_name"]
                    item["driver_phone"] = drv["phone"]
                    item["driver_type"] = drv["driver_type"]
                meta = _json(item.get("metadata_json", "{}"), {}) if "_json" in globals() else (json.loads(item.get("metadata_json") or "{}") if isinstance(item.get("metadata_json"), str) else (item.get("metadata_json") or {}))
                item["trips_count"] = meta.get("total_duties") or meta.get("trips_count") or len(meta.get("trips") or []) or 0
                item["total_km"] = meta.get("total_km") or 0
                item["trips"] = meta.get("trips") or []
        return {"ok": True, "items": items, "count": len(items)}
    item_id = new_id(table.replace("finance_", "").replace("report_", "").replace("feedback_", ""))
    now = now_iso()
    if table == "finance_supplier_payment_requests":
        amount = _int(payload, "amount_paise")
        if amount <= 0: raise DomainError(400, "amount_paise must be positive", "validation_error")
        supplier = _text(payload, "supplier_id") or None; _owned_optional(conn, "domain_suppliers", supplier, org)
        key = _key(payload); old = _existing(conn, table, org, key)
        if old: return {"ok": True, "item": _serialize(old, fields), "idempotent": True}
        values = (item_id, org, supplier, _text(payload, "settlement_id") or None, _text(payload, "advance_id") or None, amount, _text(payload, "currency", "INR", 10), _text(payload, "status", "requested", 30), user["id"], None, None, _text(payload, "due_at", maximum=40) or None, _text(payload, "payment_reference", maximum=100), json.dumps(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}), key, now, now)
        sql = "INSERT INTO finance_supplier_payment_requests(id,organization_id,supplier_id,settlement_id,advance_id,amount_paise,currency,status,requested_by,approved_by,approved_at,due_at,payment_reference,metadata_json,idempotency_key,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    elif table == "finance_supplier_advances":
        amount = _int(payload, "amount_paise")
        if amount <= 0: raise DomainError(400, "amount_paise must be positive", "validation_error")
        supplier = _text(payload, "supplier_id") or None; _owned_optional(conn, "domain_suppliers", supplier, org); key = _key(payload); old = _existing(conn, table, org, key)
        if old: return {"ok": True, "item": _serialize(old, fields), "idempotent": True}
        values = (item_id, org, supplier, amount, _text(payload, "purpose", maximum=500), _text(payload, "status", "requested", 30), user["id"], None, None, 0, json.dumps(payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}), key, now, now); sql = "INSERT INTO finance_supplier_advances(id,organization_id,supplier_id,amount_paise,purpose,status,requested_by,approved_by,approved_at,recovered_paise,evidence_json,idempotency_key,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    elif table == "finance_driver_payouts":
        driver = _text(payload, "driver_id"); _assert_owned(conn, "domain_drivers", driver, org); key = _key(payload); old = _existing(conn, table, org, key)
        if old: return {"ok": True, "item": _serialize(old, fields), "idempotent": True}
        gross = _int(payload, "gross_paise"); deductions = _int(payload, "deductions_paise"); values = (item_id, org, driver, _text(payload, "period_start", maximum=40), _text(payload, "period_end", maximum=40), gross, deductions, max(0, gross - deductions), _text(payload, "status", "pending_approval", 30), "", None, None, None, key, json.dumps(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}), user["id"], now); sql = "INSERT INTO finance_driver_payouts(id,organization_id,driver_id,period_start,period_end,gross_paise,deductions_paise,net_paise,status,bank_reference,approved_by,approved_at,disbursed_at,idempotency_key,metadata_json,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    elif table == "finance_settlement_approvals":
        settlement_id = _text(payload, "settlement_id"); _assert_owned(conn, "domain_supplier_settlements", settlement_id, org)
        values = (item_id, org, settlement_id, _text(payload, "status", "pending", 30), _text(payload, "comments", maximum=1000), user["id"], None, None, now)
        sql = "INSERT INTO finance_settlement_approvals(id,organization_id,settlement_id,status,comments,requested_by,decided_by,decided_at,created_at) VALUES (?,?,?,?,?,?,?,?,?)"
    elif table == "finance_payroll_compliance_reports":
        values = (item_id, org, _text(payload, "period_start", maximum=40), _text(payload, "period_end", maximum=40), _text(payload, "report_type", "statutory_deductions", 60), "ready", json.dumps(payload.get("deductions") if isinstance(payload.get("deductions"), dict) else {}), user["id"], now); sql = "INSERT INTO finance_payroll_compliance_reports(id,organization_id,period_start,period_end,report_type,status,deductions_json,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?)"
    elif table == "finance_fuel_stations":
        values = (item_id, org, _text(payload, "code", maximum=60), _text(payload, "name", maximum=160), _text(payload, "city", maximum=80), _text(payload, "address", maximum=500), json.dumps(payload.get("fuel_types") if isinstance(payload.get("fuel_types"), list) else []), _text(payload, "status", "active", 20), user["id"], now, now); sql = "INSERT INTO finance_fuel_stations(id,organization_id,code,name,city,address,fuel_types_json,status,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
    elif table == "finance_fuel_prices":
        station = _text(payload, "station_id"); _assert_owned(conn, "finance_fuel_stations", station, org); values = (item_id, org, station, _text(payload, "fuel_type", "diesel", 20).lower(), _int(payload, "price_paise"), _text(payload, "effective_from", now, 40), _text(payload, "source", "operator", 30), user["id"], now); sql = "INSERT INTO finance_fuel_prices(id,organization_id,station_id,fuel_type,price_paise,effective_from,source,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?)"
    elif table == "finance_reconciliations":
        values = (item_id, org, _text(payload, "reconciliation_type", "supplier_customer", 50), _text(payload, "status", "open", 20), _text(payload, "period_start", maximum=40) or None, _text(payload, "period_end", maximum=40) or None, json.dumps(payload.get("filters") if isinstance(payload.get("filters"), dict) else {}), json.dumps(payload.get("summary") if isinstance(payload.get("summary"), dict) else {}), json.dumps(payload.get("unmatched") if isinstance(payload.get("unmatched"), list) else []), _int(payload, "resolved_count"), user["id"], now, now); sql = "INSERT INTO finance_reconciliations(id,organization_id,reconciliation_type,status,period_start,period_end,filters_json,summary_json,unmatched_json,resolved_count,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
    elif table == "report_builder_configs":
        values = (item_id, org, _text(payload, "name", "Operations report", 160), _text(payload, "report_type", "custom", 50), json.dumps(payload.get("filters") if isinstance(payload.get("filters"), dict) else {}), json.dumps(payload.get("columns") if isinstance(payload.get("columns"), list) else []), json.dumps(payload.get("sort") if isinstance(payload.get("sort"), dict) else {}), "active", user["id"], now, now); sql = "INSERT INTO report_builder_configs(id,organization_id,name,report_type,filters_json,columns_json,sort_json,status,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
    elif table == "report_favorites":
        config_id = _text(payload, "config_id"); _assert_owned(conn, "report_builder_configs", config_id, org); values = (item_id, org, config_id, _text(payload, "name", "Saved report", 160), _text(payload, "refresh_cadence", "manual", 30), None, user["id"], now); sql = "INSERT INTO report_favorites(id,organization_id,config_id,name,refresh_cadence,last_run_at,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)"
    elif table == "finance_import_templates":
        values = (item_id, org, _text(payload, "entity_type", "vehicles", 40), _text(payload, "name", "Import template", 120), _int(payload, "version", 1), json.dumps(payload.get("columns") if isinstance(payload.get("columns"), list) else []), json.dumps(payload.get("validation") if isinstance(payload.get("validation"), dict) else {}), "active", user["id"], now); sql = "INSERT INTO finance_import_templates(id,organization_id,entity_type,name,version,columns_json,validation_json,status,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)"
    elif table == "feedback_notifications":
        values = (item_id, org, _text(payload, "feedback_link_id") or None, _text(payload, "response_id") or None, _text(payload, "channel", "email", 20), _text(payload, "recipient", maximum=254), _text(payload, "status", "queued", 20), 0, _text(payload, "next_attempt_at", maximum=40) or now, "", "", now, now); sql = "INSERT INTO feedback_notifications(id,organization_id,feedback_link_id,response_id,channel,recipient,status,attempts,next_attempt_at,provider_reference,error,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
    else:  # corrective actions
        values = (item_id, org, _text(payload, "response_id") or None, _text(payload, "rule_id") or None, _text(payload, "action_type", "investigate", 40), _text(payload, "owner_id") or None, _text(payload, "status", "open", 20), _text(payload, "priority", "medium", 20), _text(payload, "due_at", maximum=40) or None, _text(payload, "notes", maximum=1000), user["id"], now, None); sql = "INSERT INTO feedback_corrective_actions(id,organization_id,response_id,rule_id,action_type,owner_id,status,priority,due_at,notes,created_by,created_at,resolved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
    conn.execute(sql, values); _audit(conn, user, f"{table}.created", table, item_id, ip, {}); return {"ok": True, "item": _serialize(conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone(), fields)}


def _approve_or_execute(conn, user, route, method, payload, ip):
    match = re.match(r"^/api/(supplier-payment-requests|supplier-advances|driver-payouts|supplier-settlement-approvals)/(?:([^/]+)/)?(approve|reject|execute|disburse)$", route)
    if not match or method != "POST": return None
    org = _org(user); _staff(user)
    resource, item_id, action = match.group(1), match.group(2), match.group(3)
    table = {"supplier-payment-requests": "finance_supplier_payment_requests", "supplier-advances": "finance_supplier_advances", "driver-payouts": "finance_driver_payouts", "supplier-settlement-approvals": "finance_settlement_approvals"}[resource]
    if resource == "driver-payouts" and action == "execute": action = "disburse"
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ? AND organization_id = ?", (item_id, org)).fetchone()
    if not row: raise DomainError(404, "Finance item not found", "not_found")
    if resource == "supplier-payment-requests" and action == "execute":
        execution_id = new_id("payment_execution"); key = _key(payload); old = _existing(conn, "finance_payment_executions", org, key)
        if old: return {"ok": True, "item": _serialize(old, ("metadata_json",)), "idempotent": True}
        now = now_iso(); conn.execute("INSERT INTO finance_payment_executions(id,organization_id,request_id,amount_paise,method,status,provider_reference,idempotency_key,executed_at,metadata_json,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (execution_id, org, item_id, row["amount_paise"], _text(payload, "method", "mock_bank", 30), "executed", f"MOCK-{execution_id[-8:]}", key, now, json.dumps(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}), user["id"], now)); conn.execute("UPDATE finance_supplier_payment_requests SET status='paid', payment_reference=? , updated_at=? WHERE id=?", (f"MOCK-{execution_id[-8:]}", now, item_id)); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM finance_payment_executions WHERE id = ?", (execution_id,)).fetchone(), ("metadata_json",)), "provider": "mock_bank"}
    if action in {"approve", "reject"}:
        status = "approved" if action == "approve" else "rejected"
        now = now_iso()
        if table == "finance_driver_payouts":
            conn.execute("UPDATE finance_driver_payouts SET status=?,approved_by=?,approved_at=?,updated_at=? WHERE id=?", (status, user["id"], now, now, item_id))
        elif table == "finance_settlement_approvals":
            conn.execute("UPDATE finance_settlement_approvals SET status=?,decided_by=?,decided_at=?,comments=? WHERE id=?", (status, user["id"], now, _text(payload, "comments", maximum=1000), item_id))
        else:
            conn.execute(f"UPDATE {table} SET status=?,approved_by=?,approved_at=?,updated_at=? WHERE id=?", (status, user["id"], now, now, item_id))
        return {"ok": True, "item": _serialize(conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone(), ("metadata_json", "evidence_json"))}
    if resource == "driver-payouts" and action == "disburse":
        if row["status"] != "approved": raise DomainError(409, "Driver payout must be approved before disbursement", "approval_required")
        now = now_iso(); conn.execute("UPDATE finance_driver_payouts SET status='disbursed',bank_reference=?,disbursed_at=?,updated_at=? WHERE id=?", (f"MOCK-PAYOUT-{item_id[-8:]}", now, now, item_id)); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM finance_driver_payouts WHERE id = ?", (item_id,)).fetchone(), ("metadata_json",)), "provider": "mock_bank"}
    return None


def _payroll_export(conn, user, method, route, payload, ip):
    if route != "/api/payroll/exports" and not re.match(r"^/api/payroll/exports/[^/]+/download$", route):
        return None
    org = _org(user); _staff(user)
    if route == "/api/payroll/exports" and method == "POST":
        run_id = _text(payload, "payroll_run_id") or None; lines = conn.execute("SELECT l.*, d.full_name, d.phone FROM domain_payroll_lines l LEFT JOIN domain_drivers d ON d.id=l.driver_id WHERE l.organization_id = ? AND (? IS NULL OR l.payroll_run_id = ?) ORDER BY l.driver_id", (org, run_id, run_id)).fetchall(); output = io.StringIO(); writer = csv.writer(output); writer.writerow(["employee_id", "employee_name", "amount_paise", "deduction_paise", "net_paise", "bank_reference"])
        for line in lines: writer.writerow([line["driver_id"], line["full_name"] or "", line["gross_paise"], line["deduction_paise"], line["net_paise"], "BANK_DETAILS_REQUIRED"])
        raw = secrets.token_urlsafe(28); export_id = new_id("payroll_export"); now = now_iso(); expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(); conn.execute("INSERT INTO finance_payroll_exports(id,organization_id,payroll_run_id,export_format,status,content,download_token_hash,signed_url,expires_at,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (export_id, org, run_id, _text(payload, "export_format", "bank_csv", 30), "ready", output.getvalue(), hashlib.sha256(raw.encode()).hexdigest(), f"mock://payroll-exports/{export_id}?signed={raw[:12]}", expires, user["id"], now)); return {"ok": True, "item": {"id": export_id, "format": "bank_csv", "status": "ready", "signed_url": f"/api/payroll/exports/{raw}/download", "content": output.getvalue()}}
    if route == "/api/payroll/exports" and method == "GET": return {"ok": True, "items": _list(conn, "finance_payroll_exports", org)}
    download = re.match(r"^/api/payroll/exports/([^/]+)/download$", route)
    if download and method == "GET":
        token = download.group(1)
        row = conn.execute("SELECT * FROM finance_payroll_exports WHERE organization_id=? AND (id=? OR download_token_hash=?)", (org, token, hashlib.sha256(token.encode()).hexdigest())).fetchone()
        if not row: raise DomainError(404, "Payroll export not found", "not_found")
        if datetime.now(timezone.utc) > datetime.fromisoformat(row["expires_at"]): raise DomainError(410, "Payroll export has expired", "export_expired")
        return {"ok": True, "item": {"id": row["id"], "format": row["export_format"], "content": row["content"], "signed_url": row["signed_url"], "expires_at": row["expires_at"]}}
    return None


def _fuel_analytics(conn, user, raw_route):
    org = _org(user); _staff(user); query = parse_qs(urlsplit(raw_route).query); vehicle_id = query.get("vehicle_id", [None])[0]
    params = [org]; where = "f.organization_id = ?"
    if vehicle_id: where += " AND f.vehicle_id = ?"; params.append(vehicle_id)
    rows = conn.execute(f"SELECT f.vehicle_id, v.registration_number, v.vehicle_type, SUM(f.quantity_millilitres) AS litres_millilitres, SUM(f.amount_paise) AS fuel_paise, MIN(f.odometer_km) AS first_odo, MAX(f.odometer_km) AS last_odo, COUNT(*) AS entries FROM domain_fuel_entries f LEFT JOIN domain_vehicles v ON v.id=f.vehicle_id WHERE {where} GROUP BY f.vehicle_id ORDER BY fuel_paise DESC", params).fetchall(); result=[]
    for row in rows:
        distance = max(0, int(row["last_odo"] or 0) - int(row["first_odo"] or 0)); litres = float(row["litres_millilitres"] or 0) / 1000; result.append({**_serialize(row), "distance_km": distance, "litres": litres, "km_per_litre": round(distance / litres, 2) if litres else None, "cost_per_km_paise": round(int(row["fuel_paise"] or 0) / distance, 2) if distance else None})
    prices = [_serialize(row) for row in conn.execute("SELECT p.*, s.name AS station_name FROM finance_fuel_prices p JOIN finance_fuel_stations s ON s.id=p.station_id WHERE p.organization_id=? ORDER BY effective_from DESC LIMIT 200", (org,)).fetchall()]; return {"ok": True, "items": result, "price_history": prices}


def _create_report_job(conn, user, config_id, export_type, rows):
    org = _org(user)
    raw = secrets.token_urlsafe(28)
    job_id = new_id("report_export")
    now = now_iso()
    expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    content = json.dumps(rows, ensure_ascii=False)
    conn.execute(
        "INSERT INTO report_export_jobs(id,organization_id,config_id,export_type,status,row_count,content,storage_path,signed_url,download_token_hash,expires_at,error,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (job_id, org, config_id, export_type, "ready", len(rows), content, f"mock://report-exports/{job_id}.json", f"/api/reports/exports/{raw}/download", hashlib.sha256(raw.encode()).hexdigest(), expires, "", user["id"], now, now),
    )
    return conn.execute("SELECT * FROM report_export_jobs WHERE id=?", (job_id,)).fetchone()


def _report_run(conn, user, route, method, payload, ip, raw_route=None):
    report_route = (route == "/api/reports/profitability" or route in {"/api/reports/exports", "/api/reports/builder"} or route.startswith("/api/reports/exports/") or route.startswith("/api/reports/favorites/") or route.startswith("/api/reports/builder/"))
    if not report_route:
        return None
    org = _org(user); _staff(user)
    if route == "/api/reports/profitability" and method == "GET":
        query = parse_qs(urlsplit(raw_route or route).query)
        filters = {key: values[0] for key, values in query.items() if values}
        rows = _profitability(conn, org, filters, filters.get("report_type", "vehicle_profitability"))
        return {"ok": True, "report_type": filters.get("report_type", "vehicle_profitability"), "rows": rows, "count": len(rows)}
    if route == "/api/reports/exports" and method == "GET":
        return {"ok": True, "items": _list(conn, "report_export_jobs", org)}
    if route == "/api/reports/exports" and method == "POST":
        filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
        rows = _profitability(conn, org, filters, _text(payload, "export_type", "vehicle_profitability", 60))
        job = _create_report_job(conn, user, _text(payload, "config_id") or None, _text(payload, "export_type", "csv", 60), rows)
        return {"ok": True, "async": True, "job": _serialize(job)}
    job_match = re.match(r"^/api/reports/exports/([^/]+)(?:/download)?$", route)
    if job_match and method == "GET":
        token = job_match.group(1)
        job = conn.execute("SELECT * FROM report_export_jobs WHERE organization_id=? AND (id=? OR download_token_hash=?)", (org, token, hashlib.sha256(token.encode()).hexdigest())).fetchone()
        # The legacy /api/reports/export contract is handled by the extended
        # report adapter. Fall through when this newer async-job table has no
        # matching record so both additive report contracts remain reachable.
        if not job: return None
        if datetime.now(timezone.utc) > datetime.fromisoformat(job["expires_at"]): raise DomainError(410, "Report export has expired", "export_expired")
        item = _serialize(job)
        if route.endswith("/download"):
            item["rows"] = json.loads(job["content"] or "[]")
            item["download"] = {"provider": "mock_storage", "content_type": "application/json", "signed_url": job["signed_url"]}
        return {"ok": True, "item": item}
    favorite_match = re.match(r"^/api/reports/favorites/([^/]+)/refresh$", route)
    if favorite_match and method == "POST":
        favorite = conn.execute("SELECT * FROM report_favorites WHERE id=? AND organization_id=?", (favorite_match.group(1), org)).fetchone()
        if not favorite: raise DomainError(404, "Report favourite not found", "not_found")
        config = conn.execute("SELECT * FROM report_builder_configs WHERE id=? AND organization_id=?", (favorite["config_id"], org)).fetchone()
        if not config: raise DomainError(404, "Report builder config not found", "not_found")
        filters = json.loads(config["filters_json"] or "{}"); rows = _profitability(conn, org, filters, config["report_type"]); now = now_iso(); conn.execute("UPDATE report_favorites SET last_run_at=? WHERE id=?", (now, favorite["id"]))
        return {"ok": True, "favorite_id": favorite["id"], "refreshed_at": now, "rows": rows, "count": len(rows)}
    run = re.match(r"^/api/reports/builder/([^/]+)/run$", route)
    if run and method == "POST":
        config = conn.execute("SELECT * FROM report_builder_configs WHERE id=? AND organization_id=?", (run.group(1), org)).fetchone()
        if not config: raise DomainError(404, "Report builder config not found", "not_found")
        filters = json.loads(config["filters_json"] or "{}"); filters.update(payload.get("filters") if isinstance(payload.get("filters"), dict) else {})
        rows = _profitability(conn, org, filters, config["report_type"]); if_async = bool(payload.get("async") or len(rows) > 1000)
        if if_async:
            raw = secrets.token_urlsafe(28); job_id = new_id("report_export"); now = now_iso(); conn.execute("INSERT INTO report_export_jobs(id,organization_id,config_id,export_type,status,row_count,content,storage_path,signed_url,download_token_hash,expires_at,error,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (job_id, org, config["id"], _text(payload, "export_type", "csv", 30), "ready", len(rows), json.dumps(rows), f"mock://report-exports/{job_id}.json", f"/api/reports/exports/{raw}/download", hashlib.sha256(raw.encode()).hexdigest(), (datetime.now(timezone.utc)+timedelta(hours=24)).isoformat(), "", user["id"], now, now)); return {"ok": True, "async": True, "job": _serialize(conn.execute("SELECT * FROM report_export_jobs WHERE id=?", (job_id,)).fetchone())}
        return {"ok": True, "async": False, "report_type": config["report_type"], "rows": rows, "count": len(rows)}
    return None


def _profitability(conn, org, filters, report_type):
    clauses = ["d.organization_id=?"]; params=[org]
    for key, column in (("customer_id", "b.customer_id"), ("vehicle_id", "d.vehicle_id"), ("supplier_id", "s.id"), ("company_id", "b.company_id"), ("vehicle_group", "v.vehicle_group"), ("city", "v.city"), ("branch", "v.branch_name")):
        if filters.get(key): clauses.append(f"{column}=?"); params.append(str(filters[key]))
    rows = conn.execute(f"SELECT d.id AS duty_id, b.booking_reference, b.customer_id, d.vehicle_id, d.driver_id, i.total_paise AS revenue_paise, COALESCE(po.amount_paise,0) AS supplier_cost_paise, COALESCE(fe.amount_paise,0) AS fuel_paise, v.registration_number, s.name AS supplier_name FROM domain_duties d JOIN domain_bookings b ON b.id=d.booking_id LEFT JOIN domain_invoices i ON i.duty_id=d.id AND i.organization_id=d.organization_id LEFT JOIN domain_vehicles v ON v.id=d.vehicle_id LEFT JOIN domain_purchase_orders po ON po.duty_id=d.id AND po.organization_id=d.organization_id LEFT JOIN domain_fuel_entries fe ON fe.duty_id=d.id AND fe.organization_id=d.organization_id LEFT JOIN domain_suppliers s ON s.id=po.supplier_id WHERE {' AND '.join(clauses)} ORDER BY d.updated_at DESC LIMIT 2000", params).fetchall(); result=[]
    for row in rows:
        revenue=int(row["revenue_paise"] or 0); costs=int(row["supplier_cost_paise"] or 0)+int(row["fuel_paise"] or 0); result.append({**_serialize(row), "cost_paise": costs, "profit_paise": revenue-costs, "report_type": report_type})
    return result


def _import_preview(conn, user, method, route, payload, ip):
    if route != "/api/imports/preview" and not re.match(r"^/api/imports/[^/]+/(corrections|commit)$", route):
        return None
    org = _org(user); _staff(user)
    if route == "/api/imports/preview" and method == "POST":
        entity = _text(payload, "entity_type", "vehicles", 40); rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []; required = {"vehicles": ["registration_number"], "drivers": ["full_name"], "customers": ["name"], "suppliers": ["name"], "fuel_stations": ["code", "name"]}.get(entity, [])
        errors=[]; valid=0; seen=set()
        for index, row in enumerate(rows):
            row_errors=[]
            for field in required:
                if not isinstance(row, dict) or not str(row.get(field) or "").strip(): row_errors.append({"field": field, "code": "required", "message": f"{field} is required"})
            key = str((row or {}).get(required[0], "")).strip().lower() if isinstance(row, dict) and required else ""
            if key and key in seen: row_errors.append({"field": required[0], "code": "duplicate", "message": "Duplicate value in import"})
            if key: seen.add(key)
            if row_errors: errors.append({"row": index, "errors": row_errors})
            else: valid += 1
        job_id=new_id("import"); now=now_iso(); conn.execute("INSERT INTO finance_import_jobs(id,organization_id,template_id,entity_type,status,rows_json,errors_json,total_rows,valid_rows,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (job_id,org,_text(payload,"template_id") or None,entity,"preview",json.dumps(rows),json.dumps(errors),len(rows),valid,user["id"],now,now)); return {"ok":True,"item":_serialize(conn.execute("SELECT * FROM finance_import_jobs WHERE id=?",(job_id,)).fetchone(),("rows_json","errors_json")),"row_errors":errors}
    correction = re.match(r"^/api/imports/([^/]+)/corrections$", route)
    if correction and method == "POST":
        job = conn.execute("SELECT * FROM finance_import_jobs WHERE id=? AND organization_id=?", (correction.group(1),org)).fetchone();
        if not job: raise DomainError(404,"Import job not found","not_found")
        corrections = payload.get("corrections") if isinstance(payload.get("corrections"), list) else []; rows=json.loads(job["rows_json"] or "[]")
        for item in corrections:
            try: rows[int(item.get("row"))] = {**rows[int(item.get("row"))], **(item.get("values") if isinstance(item.get("values"),dict) else {})}
            except (TypeError,ValueError,IndexError,KeyError): continue
        return _re_preview(conn,user,job,rows,ip)
    commit = re.match(r"^/api/imports/([^/]+)/commit$", route)
    if commit and method == "POST":
        job=conn.execute("SELECT * FROM finance_import_jobs WHERE id=? AND organization_id=?",(commit.group(1),org)).fetchone();
        if not job: raise DomainError(404,"Import job not found","not_found")
        errors=json.loads(job["errors_json"] or "[]")
        if errors: raise DomainError(409,"Correct import errors before commit","import_errors",{"row_errors":errors})
        conn.execute("UPDATE finance_import_jobs SET status='committed',corrected_rows_json=rows_json,updated_at=? WHERE id=?",(now_iso(),job["id"])); return {"ok":True,"item":_serialize(conn.execute("SELECT * FROM finance_import_jobs WHERE id=?",(job["id"],)).fetchone(),("rows_json","errors_json","corrected_rows_json"))}
    return None


def _re_preview(conn,user,job,rows,ip):
    required={"vehicles":["registration_number"],"drivers":["full_name"],"customers":["name"],"suppliers":["name"],"fuel_stations":["code","name"]}.get(job["entity_type"],[]); errors=[]; valid=0
    for index,row in enumerate(rows):
        row_errors=[{"field":field,"code":"required","message":f"{field} is required"} for field in required if not str((row or {}).get(field) or "").strip()]
        if row_errors: errors.append({"row":index,"errors":row_errors})
        else: valid+=1
    conn.execute("UPDATE finance_import_jobs SET rows_json=?,errors_json=?,valid_rows=?,updated_at=? WHERE id=?",(json.dumps(rows),json.dumps(errors),valid,now_iso(),job["id"])); return {"ok":True,"item":_serialize(conn.execute("SELECT * FROM finance_import_jobs WHERE id=?",(job["id"],)).fetchone(),("rows_json","errors_json")),"row_errors":errors}


def _feedback_policy_rows(conn, table, org):
    fields = ("channels_json", "fallback_channels_json", "quiet_hours_json", "template_keys_json") if table == "feedback_delivery_policies" else ("conditions_json", "channels_json")
    return [_serialize(row, fields) for row in conn.execute(f"SELECT * FROM {table} WHERE organization_id = ? ORDER BY updated_at DESC LIMIT 500", (org,)).fetchall()]


def _feedback_policy_payload(payload, *, escalation=False):
    if escalation:
        conditions = payload.get("conditions") if isinstance(payload.get("conditions"), dict) else {"rating_lte": 2}
        channels = payload.get("channels") if isinstance(payload.get("channels"), list) else []
        return conditions, channels
    channels = payload.get("channels") if isinstance(payload.get("channels"), list) else ["sms", "email", "whatsapp"]
    fallback = payload.get("fallback_channels") if isinstance(payload.get("fallback_channels"), list) else ["email"]
    return channels, fallback


def _feedback_links(conn,user,method,route,payload,ip):
    feedback_route = route.startswith("/api/feedback/")
    if not feedback_route:
        return None
    org=_org(user); _staff(user)
    if route in {"/api/feedback/delivery-policies", "/api/feedback/escalation-policies"}:
        escalation = route.endswith("escalation-policies")
        table = "feedback_escalation_policies" if escalation else "feedback_delivery_policies"
        if method == "GET": return {"ok": True, "items": _feedback_policy_rows(conn, table, org)}
        if method != "POST": raise DomainError(405, "Policy route supports GET or POST", "method_not_allowed")
        name = _text(payload, "name", maximum=160)
        if not name: raise DomainError(400, "Policy name is required", "validation_error")
        _owned_optional(conn, "domain_customers", _text(payload, "customer_id") or None, org)
        now = now_iso(); policy_id = new_id("feedback_policy")
        if escalation:
            conditions, channels = _feedback_policy_payload(payload, escalation=True)
            conn.execute("INSERT INTO feedback_escalation_policies(id,organization_id,customer_id,name,status,conditions_json,action_type,priority,owner_id,due_minutes,channels_json,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (policy_id, org, _text(payload, "customer_id") or None, name, _text(payload, "status", "active", 20), json.dumps(conditions), _text(payload, "action_type", "investigate", 40), _text(payload, "priority", "high", 20), _text(payload, "owner_id") or None, max(1, _int(payload, "due_minutes", 60)), json.dumps(channels), user["id"], now, now))
            item = conn.execute("SELECT * FROM feedback_escalation_policies WHERE id=?", (policy_id,)).fetchone(); fields=("conditions_json", "channels_json")
        else:
            channels, fallback = _feedback_policy_payload(payload)
            conn.execute("INSERT INTO feedback_delivery_policies(id,organization_id,customer_id,name,status,trigger_event,channels_json,fallback_channels_json,delay_minutes,quiet_hours_json,template_keys_json,max_attempts,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (policy_id, org, _text(payload, "customer_id") or None, name, _text(payload, "status", "active", 20), _text(payload, "trigger_event", "duty_completed", 50), json.dumps(channels), json.dumps(fallback), max(0, _int(payload, "delay_minutes", 0)), json.dumps(payload.get("quiet_hours") if isinstance(payload.get("quiet_hours"), dict) else {}), json.dumps(payload.get("template_keys") if isinstance(payload.get("template_keys"), dict) else {}), max(1, _int(payload, "max_attempts", 5)), user["id"], now, now))
            item = conn.execute("SELECT * FROM feedback_delivery_policies WHERE id=?", (policy_id,)).fetchone(); fields=("channels_json", "fallback_channels_json", "quiet_hours_json", "template_keys_json")
        _audit(conn, user, "feedback.policy_created", table, policy_id, ip, {"customer_id": _text(payload, "customer_id") or None})
        return {"ok": True, "item": _serialize(item, fields)}
    policy_action = re.match(r"^/api/feedback/(delivery-policies|escalation-policies)/([^/]+)/(archive|pause|activate)$", route)
    if policy_action and method == "POST":
        table = "feedback_delivery_policies" if policy_action.group(1) == "delivery-policies" else "feedback_escalation_policies"; status_value = {"archive": "archived", "pause": "paused", "activate": "active"}[policy_action.group(3)]
        row = conn.execute(f"SELECT * FROM {table} WHERE id=? AND organization_id=?", (policy_action.group(2), org)).fetchone()
        if not row: raise DomainError(404, "Feedback policy not found", "not_found")
        conn.execute(f"UPDATE {table} SET status=?, updated_at=? WHERE id=?", (status_value, now_iso(), row["id"]))
        return {"ok": True, "item": _serialize(conn.execute(f"SELECT * FROM {table} WHERE id=?", (row["id"],)).fetchone())}
    if route == "/api/feedback/delivery-attempts" and method == "GET":
        rows = conn.execute("SELECT * FROM feedback_delivery_attempts WHERE organization_id=? ORDER BY created_at DESC LIMIT 500", (org,)).fetchall()
        return {"ok": True, "items": [_serialize(row, ("response_payload_json",)) for row in rows]}
    if route == "/api/feedback/notifications" and method == "GET": return {"ok": True, "items": _list(conn, "feedback_notifications", org)}
    if route == "/api/feedback/notifications/run" and method == "POST":
        now = now_iso(); limit = min(max(_int(payload, "limit", 100), 1), 500)
        rows = conn.execute("SELECT * FROM feedback_notifications WHERE organization_id=? AND status IN ('queued','retrying') AND (next_attempt_at IS NULL OR next_attempt_at <= ?) ORDER BY created_at LIMIT ?", (org, now, limit)).fetchall()
        processed = sent = failed = bounced = dead_letter = 0
        for row in rows:
            attempt_number = int(row["attempts"] or 0) + 1; channel = row["channel"] or "email"; provider = f"mock_{channel}"
            ref = f"mock-{channel}-{row['id']}-{attempt_number}"
            recipient = (row["recipient"] or "").lower(); max_attempts = int(row["attempt_limit"] or 5)
            is_bounce = any(token in recipient for token in ("bounce", "invalid", "undeliverable")); is_retry = "retry" in recipient and attempt_number < max_attempts
            if is_bounce:
                delivery_status = "bounced"; notification_status = "bounced"; bounced += 1; error_code = "mock_hard_bounce"; next_at = None
            elif is_retry:
                delivery_status = "retrying"; notification_status = "retrying"; failed += 1; error_code = "mock_transient"; next_at = (datetime.now(timezone.utc) + timedelta(minutes=min(60, 2 ** attempt_number))).isoformat()
            elif attempt_number >= max_attempts and "retry" in recipient:
                delivery_status = "dead_letter"; notification_status = "dead_letter"; dead_letter += 1; error_code = "retry_exhausted"; next_at = None
            else:
                delivery_status = "sent"; notification_status = "sent"; sent += 1; error_code = ""; next_at = None
            conn.execute("INSERT INTO feedback_delivery_attempts(id,organization_id,notification_id,attempt_number,provider,channel,status,provider_reference,error_code,error_message,response_payload_json,next_attempt_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (new_id("feedback_attempt"), org, row["id"], attempt_number, provider, channel, delivery_status, ref, error_code, "", json.dumps({"adapter": "mock", "channel": channel}), next_at, now))
            conn.execute("UPDATE feedback_notifications SET status=?, attempts=?, provider_reference=?, error=?, next_attempt_at=?, dead_lettered_at=?, updated_at=? WHERE id=? AND organization_id=?", (notification_status, attempt_number, ref, error_code, next_at, now if notification_status == "dead_letter" else None, now, row["id"], org)); processed += 1
        return {"ok": True, "processed": processed, "sent": sent, "failed": failed, "bounced": bounced, "dead_letter": dead_letter, "provider": "mock_sms_email_whatsapp_adapter", "retryable": True}
    receipt = re.match(r"^/api/feedback/notifications/([^/]+)/receipt$", route)
    if receipt and method == "POST":
        notification = conn.execute("SELECT * FROM feedback_notifications WHERE id=? AND organization_id=?", (receipt.group(1), org)).fetchone()
        if not notification: raise DomainError(404, "Feedback notification not found", "not_found")
        target = _text(payload, "status", maximum=20)
        if target not in {"delivered", "bounced", "failed", "sent"}: raise DomainError(400, "Unsupported provider delivery status", "validation_error")
        now = now_iso(); provider_ref = _text(payload, "provider_reference", notification["provider_reference"], 200); event_id = _text(payload, "provider_event_id", maximum=200)
        conn.execute("UPDATE feedback_notifications SET status=?, provider_reference=?, last_provider_event_id=?, bounce_code=?, error=?, updated_at=? WHERE id=?", (target, provider_ref, event_id, _text(payload, "bounce_code", maximum=80), _text(payload, "error", maximum=500), now, notification["id"]))
        latest = conn.execute("SELECT id FROM feedback_delivery_attempts WHERE notification_id=? ORDER BY attempt_number DESC LIMIT 1", (notification["id"],)).fetchone()
        if latest: conn.execute("UPDATE feedback_delivery_attempts SET status=?, provider_event_id=?, error_code=?, error_message=?, response_payload_json=? WHERE id=?", (target, event_id, _text(payload, "bounce_code", maximum=80), _text(payload, "error", maximum=500), json.dumps(payload), latest["id"]))
        return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM feedback_notifications WHERE id=?", (notification["id"],)).fetchone())}
    if route == "/api/feedback/public-links" and method == "GET": return {"ok":True,"items":_list(conn,"feedback_public_links",org)}
    if route != "/api/feedback/public-links" or method != "POST": return None
    form_id=_text(payload,"form_id") or None; _owned_optional(conn,"domain_feedback_forms",form_id,org); duty_id=_text(payload,"duty_id") or None; _owned_optional(conn,"domain_duties",duty_id,org); booking_id=_text(payload,"booking_id") or None; _owned_optional(conn,"domain_bookings",booking_id,org); raw=secrets.token_urlsafe(32); link_id=new_id("feedback_link"); now=now_iso(); expires=_text(payload,"expires_at",(datetime.now(timezone.utc)+timedelta(days=7)).isoformat(),40); customer_id=_text(payload,"customer_id") or None
    _owned_optional(conn, "domain_customers", customer_id, org)
    policy_id = _text(payload, "policy_id") or None
    if policy_id:
        policy = conn.execute("SELECT * FROM feedback_delivery_policies WHERE id=? AND organization_id=? AND status='active'", (policy_id, org)).fetchone()
        if not policy: raise DomainError(404, "Feedback delivery policy not found", "not_found")
    else:
        policy = conn.execute("SELECT * FROM feedback_delivery_policies WHERE organization_id=? AND status='active' AND (customer_id=? OR customer_id IS NULL) ORDER BY CASE WHEN customer_id=? THEN 0 ELSE 1 END, updated_at DESC LIMIT 1", (org, customer_id, customer_id)).fetchone()
    channels = json.loads(policy["channels_json"] or "[\"email\"]") if policy else ["email"]; channel = _text(payload, "channel", channels[0] if channels else "email", 20); attempt_limit = int(policy["max_attempts"] if policy else 5)
    conn.execute("INSERT INTO feedback_public_links(id,organization_id,form_id,duty_id,booking_id,customer_id,token_hash,label,expires_at,allow_anonymous,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",(link_id,org,form_id,duty_id,booking_id,customer_id,hashlib.sha256(raw.encode()).hexdigest(),_text(payload,"label","Passenger feedback",160),expires,int(bool(payload.get("allow_anonymous",True))),user["id"],now)); notification_id=new_id("feedback_notification"); conn.execute("INSERT INTO feedback_notifications(id,organization_id,feedback_link_id,channel,recipient,status,attempts,next_attempt_at,policy_id,attempt_limit,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",(notification_id,org,link_id,channel,_text(payload,"recipient",maximum=254),"queued",0,now,policy["id"] if policy else None,attempt_limit,now,now)); return {"ok":True,"item":_serialize(conn.execute("SELECT * FROM feedback_public_links WHERE id=?",(link_id,)).fetchone()),"feedback_token":raw,"feedback_path":f"/api/feedback/v1/{raw}","feedback_url":f"/?feedback_token={raw}","delivery_policy_id":policy["id"] if policy else None}


def _calculate_driver_payout(conn, user, raw_route):
    org = _org(user)
    _staff(user)
    query = parse_qs(urlsplit(raw_route).query)
    driver_id = query.get("driver_id", [None])[0]
    if not driver_id:
        raise DomainError(400, "driver_id query parameter is required", "validation_error")

    driver = _assert_owned(conn, "domain_drivers", driver_id, org)
    period_start = query.get("from", [None])[0] or query.get("period_start", [None])[0]
    period_end = query.get("to", [None])[0] or query.get("period_end", [None])[0]

    # Query completed duties for this driver
    sql = """
        SELECT d.*, b.booking_reference, b.passenger_name, b.passenger_phone,
               b.pickup_json, b.dropoff_json, b.duty_type,
               v.registration_number, v.manufacturer, v.model
        FROM domain_duties d
        JOIN domain_bookings b ON b.id = d.booking_id
        LEFT JOIN domain_vehicles v ON v.id = d.vehicle_id
        WHERE d.organization_id = ? AND d.driver_id = ?
    """
    params = [org, driver_id]
    if period_start:
        sql += " AND (d.reporting_at >= ? OR d.completed_at >= ? OR d.created_at >= ?)"
        params.extend([period_start, period_start, period_start])
    if period_end:
        sql += " AND (d.reporting_at <= ? OR d.completed_at <= ? OR d.created_at <= ?)"
        params.extend([period_end + "T23:59:59", period_end + "T23:59:59", period_end + "T23:59:59"])

    sql += " ORDER BY COALESCE(d.reporting_at, d.created_at) ASC"
    duties = conn.execute(sql, tuple(params)).fetchall()

    trip_items = []
    total_km = 0
    total_gross_paise = 0

    for d in duties:
        dist_km = (d["end_odometer"] - d["start_odometer"]) if d["end_odometer"] and d["start_odometer"] and d["end_odometer"] > d["start_odometer"] else 40
        total_km += dist_km
        dtype = (d["duty_type"] or "local").lower()
        if "airport" in dtype:
            base_paise = 60000
            km_rate_paise = 500
        elif "outstation" in dtype:
            base_paise = 100000
            km_rate_paise = 700
        else:
            base_paise = 45000
            km_rate_paise = 500

        payout_paise = base_paise + (dist_km * km_rate_paise)
        total_gross_paise += payout_paise

        p_json = json.loads(d["pickup_json"]) if d["pickup_json"] and isinstance(d["pickup_json"], str) else (d["pickup_json"] or {})
        d_json = json.loads(d["dropoff_json"]) if d["dropoff_json"] and isinstance(d["dropoff_json"], str) else (d["dropoff_json"] or {})

        trip_items.append({
            "duty_id": d["id"],
            "date": d["reporting_at"] or d["completed_at"] or d["created_at"],
            "duty_type": d["duty_type"] or "local",
            "booking_reference": d["booking_reference"] or "—",
            "passenger_name": d["passenger_name"] or "—",
            "pickup_address": p_json.get("address") or p_json.get("label") or "Pickup location",
            "dropoff_address": d_json.get("address") or d_json.get("label") or "Dropoff location",
            "vehicle_reg": d["registration_number"] or "—",
            "vehicle_model": f"{d['manufacturer'] or ''} {d['model'] or ''}".strip() or "—",
            "start_odometer": d["start_odometer"],
            "end_odometer": d["end_odometer"],
            "distance_km": dist_km,
            "base_paise": base_paise,
            "payout_paise": payout_paise
        })

    driver_cols = {r["name"] for r in conn.execute("PRAGMA table_info(domain_drivers)").fetchall()}
    dtype = driver["driver_type"] if "driver_type" in driver_cols else "own"

    return {
        "ok": True,
        "driver_id": driver["id"],
        "driver_name": driver["full_name"],
        "driver_phone": driver["phone"],
        "driver_type": dtype,
        "period_start": period_start,
        "period_end": period_end,
        "total_duties": len(trip_items),
        "total_km": total_km,
        "gross_paise": total_gross_paise,
        "deductions_paise": 0,
        "net_paise": total_gross_paise,
        "trips": trip_items
    }


def handle_finance_controls(conn,user,method,raw_route,payload,ip):
    route=urlsplit(raw_route).path.rstrip("/") or "/"
    if route == "/api/driver-payouts/calculate" and method == "GET":
        return _calculate_driver_payout(conn, user, raw_route)
    result=_finance_collection(conn,user,method,route,payload,ip)
    if result is not None: return result
    result=_approve_or_execute(conn,user,route,method,payload,ip)
    if result is not None: return result
    result=_payroll_export(conn,user,method,route,payload,ip)
    if result is not None: return result
    if route == "/api/fuel-analytics" and method == "GET": return _fuel_analytics(conn,user,raw_route)
    result=_report_run(conn,user,route,method,payload,ip,raw_route)
    if result is not None: return result
    result=_import_preview(conn,user,method,route,payload,ip)
    if result is not None: return result
    result=_feedback_links(conn,user,method,route,payload,ip)
    if result is not None: return result
    if route == "/api/feedback/analytics" and method == "GET":
        org=_org(user); _staff(user); rows=conn.execute("SELECT substr(created_at,1,7) AS period_key,COUNT(*) AS response_count,COALESCE(AVG(rating),0) AS average_rating,SUM(CASE WHEN sentiment='positive' THEN 1 ELSE 0 END) AS positive_count,SUM(CASE WHEN sentiment='negative' THEN 1 ELSE 0 END) AS negative_count FROM domain_feedback_responses WHERE organization_id=? GROUP BY substr(created_at,1,7) ORDER BY period_key",(org,)).fetchall(); return {"ok":True,"trend":[_serialize(row) for row in rows]}
    return None


def handle_finance_controls_public(conn,method,raw_route,payload,ip):
    route=urlsplit(raw_route).path.rstrip("/") or "/"; match=re.match(r"^/api/feedback/v1/([^/]+)$",route)
    if not match: return None
    raw=match.group(1); token_hash=hashlib.sha256(raw.encode()).hexdigest(); link=conn.execute("SELECT * FROM feedback_public_links WHERE token_hash=? AND status IN ('active','submitted')",(token_hash,)).fetchone()
    if not link: raise DomainError(403,"Feedback link is invalid","invalid_feedback_token")
    if datetime.now(timezone.utc)>datetime.fromisoformat(link["expires_at"]): raise DomainError(410,"Feedback link has expired","feedback_token_expired")
    form=conn.execute("SELECT * FROM domain_feedback_forms WHERE id=?",(link["form_id"],)).fetchone() if link["form_id"] else None
    if method=="GET": return {"ok":True,"feedback":{"id":link["id"],"label":link["label"],"expires_at":link["expires_at"],"allow_anonymous":bool(link["allow_anonymous"]),"questions":json.loads(form["questions_json"] or "[]") if form else [{"key":"rating","label":"How was your trip?","type":"rating","required":True}]}}
    if method!="POST": raise DomainError(405,"Feedback link supports GET or POST","method_not_allowed")
    if link["response_id"]: return {"ok":True,"idempotent":True,"item":_serialize(conn.execute("SELECT * FROM domain_feedback_responses WHERE id=?",(link["response_id"],)).fetchone(),("answers_json","tags_json"))}
    try: rating=int(payload.get("rating"))
    except (TypeError,ValueError): raise DomainError(400,"rating must be an integer from 1 to 5","validation_error")
    if rating<1 or rating>5: raise DomainError(400,"rating must be an integer from 1 to 5","validation_error")
    response_id = new_id("feedback")
    sentiment = "positive" if rating >= 4 else "negative" if rating <= 2 else "neutral"
    now = now_iso()
    answers = payload.get("answers") if isinstance(payload.get("answers"), dict) else {}
    tags = payload.get("tags") if isinstance(payload.get("tags"), list) else []
    conn.execute(
        "INSERT INTO domain_feedback_responses(id,organization_id,request_id,form_id,duty_id,booking_id,rating,answers_json,tags_json,sentiment,comment,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (response_id, link["organization_id"], f"public-{link['id']}", link["form_id"] or "public", link["duty_id"], link["booking_id"], rating, json.dumps(answers), json.dumps(tags[:20]), sentiment, _text(payload, "comment", maximum=2000), now),
    )
    conn.execute("UPDATE feedback_public_links SET status='submitted',response_id=?,submitted_at=? WHERE id=? AND response_id IS NULL", (response_id, now, link["id"]))
    if sentiment == "negative":
        conn.execute(
            "INSERT INTO feedback_corrective_actions(id,organization_id,response_id,action_type,status,priority,notes,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (new_id("corrective"), link["organization_id"], response_id, "investigate", "open", "high", "Automated negative passenger feedback routing", now),
        )
    policies = conn.execute("SELECT * FROM feedback_escalation_policies WHERE organization_id=? AND status='active' AND (customer_id=? OR customer_id IS NULL) ORDER BY CASE WHEN customer_id=? THEN 0 ELSE 1 END, updated_at DESC", (link["organization_id"], link["customer_id"], link["customer_id"])).fetchall()
    for policy in policies:
        conditions = json.loads(policy["conditions_json"] or "{}")
        rating_limit = conditions.get("rating_lte")
        if (rating_limit is None or rating <= int(rating_limit)) and (not conditions.get("sentiment") or conditions.get("sentiment") == sentiment):
            existing_policy_action = conn.execute("SELECT id FROM feedback_corrective_actions WHERE response_id=? AND rule_id=?", (response_id, policy["id"])).fetchone()
            if not existing_policy_action:
                due = (datetime.now(timezone.utc) + timedelta(minutes=int(policy["due_minutes"] or 60))).isoformat()
                conn.execute("INSERT INTO feedback_corrective_actions(id,organization_id,response_id,rule_id,action_type,owner_id,status,priority,due_at,notes,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (new_id("corrective"), link["organization_id"], response_id, policy["id"], policy["action_type"], policy["owner_id"], "open", policy["priority"], due, f"Automated escalation policy: {policy['name']}", now))
    return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_feedback_responses WHERE id=?", (response_id,)).fetchone(), ("answers_json", "tags_json"))}
