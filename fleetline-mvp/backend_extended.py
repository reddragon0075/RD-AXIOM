"""Extended PRD feature layer for the dependency-free local fallback.

This module intentionally keeps the local preview broad: every workflow is
organization-scoped, auditable and backed by SQLite while external systems are
represented by deterministic mock adapters.  The same records are mirrored by
the Supabase migration so the preserved console can transition without losing
its route contracts.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit, unquote

from backend_domain import (
    DEFAULT_PROVIDERS,
    DomainError,
    _assert_owned,
    _audit,
    _create_booking,
    _queue_push_notification,
    _json,
    _org,
    _serialize,
    _text,
    now_iso,
    new_id,
)
from domain_engine import CalculationError, calculate_duty


ONBOARDING_STEPS = (
    ("organization_profile", "Complete company profile"),
    ("default_branch", "Set up a default branch"),
    ("tax_profile", "Add GST and tax settings"),
    ("team_access", "Invite the operating team"),
    ("masters", "Add customer, driver and vehicle masters"),
    ("price_book", "Publish a price book"),
    ("first_booking", "Create the first booking"),
    ("driver_readiness", "Enable driver field readiness"),
)


def initialize_extended_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS domain_onboarding (
            organization_id TEXT PRIMARY KEY,
            steps_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            completed_at TEXT,
            updated_by TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_record_versions (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            change_type TEXT NOT NULL DEFAULT 'snapshot',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, entity_type, entity_id, version)
        );
        CREATE TABLE IF NOT EXISTS domain_duplicate_matches (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            field_name TEXT NOT NULL,
            normalized_value TEXT NOT NULL,
            existing_id TEXT NOT NULL,
            candidate_id TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_supplier_bills (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            supplier_id TEXT,
            bill_number TEXT NOT NULL,
            subtotal_paise INTEGER NOT NULL DEFAULT 0,
            tax_paise INTEGER NOT NULL DEFAULT 0,
            total_paise INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'captured',
            due_at TEXT,
            duty_id TEXT,
            attachment_json TEXT NOT NULL DEFAULT '{}',
            validation_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, bill_number)
        );
        CREATE TABLE IF NOT EXISTS domain_cost_entries (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            cost_type TEXT NOT NULL,
            category TEXT NOT NULL,
            amount_paise INTEGER NOT NULL DEFAULT 0,
            vehicle_id TEXT,
            duty_id TEXT,
            supplier_bill_id TEXT,
            status TEXT NOT NULL DEFAULT 'submitted',
            attachment_json TEXT NOT NULL DEFAULT '{}',
            notes TEXT NOT NULL DEFAULT '',
            created_by TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_receipt_allocations (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            invoice_id TEXT NOT NULL,
            payment_id TEXT,
            amount_paise INTEGER NOT NULL,
            reference TEXT NOT NULL DEFAULT '',
            created_by TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_payouts (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            recipient_type TEXT NOT NULL,
            recipient_id TEXT,
            period_start TEXT,
            period_end TEXT,
            amount_paise INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'draft',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            approved_by TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_financial_actions (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending',
            requested_by TEXT,
            reviewed_by TEXT,
            review_comment TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            reviewed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS domain_webhook_events (
            id TEXT PRIMARY KEY,
            organization_id TEXT,
            provider TEXT NOT NULL,
            event_type TEXT NOT NULL,
            external_id TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            signature_valid INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'received',
            created_at TEXT NOT NULL,
            UNIQUE(provider, external_id)
        );
        CREATE TABLE IF NOT EXISTS domain_approval_steps (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            booking_id TEXT NOT NULL,
            level INTEGER NOT NULL,
            approver_role TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            comment TEXT NOT NULL DEFAULT '',
            decided_by TEXT,
            decided_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, booking_id, level)
        );
        CREATE TABLE IF NOT EXISTS domain_sla_events (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            metric TEXT NOT NULL,
            due_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            resolved_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_trip_shares (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            duty_id TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            recipient TEXT NOT NULL DEFAULT '',
            expires_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_by TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_passenger_access (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            duty_id TEXT NOT NULL,
            email TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_passenger_ratings (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            duty_id TEXT NOT NULL,
            rating INTEGER NOT NULL,
            tags_json TEXT NOT NULL DEFAULT '[]',
            comment TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_driver_preferences (
            user_id TEXT PRIMARY KEY,
            organization_id TEXT,
            language TEXT NOT NULL DEFAULT 'en-IN',
            quiet_hours_json TEXT NOT NULL DEFAULT '{}',
            low_bandwidth INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_device_bindings (
            id TEXT PRIMARY KEY,
            organization_id TEXT,
            user_id TEXT NOT NULL,
            device_id TEXT NOT NULL,
            platform TEXT NOT NULL DEFAULT 'web',
            status TEXT NOT NULL DEFAULT 'active',
            last_seen_at TEXT NOT NULL,
            push_token TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(user_id, device_id)
        );
        CREATE TABLE IF NOT EXISTS domain_calls (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            duty_id TEXT,
            caller_id TEXT,
            recipient TEXT NOT NULL DEFAULT '',
            masked_number TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'queued',
            provider_reference TEXT NOT NULL DEFAULT '',
            consent INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_sos_events (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            duty_id TEXT,
            driver_id TEXT,
            latitude REAL,
            longitude REAL,
            status TEXT NOT NULL DEFAULT 'open',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            resolved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS domain_practice_duties (
            id TEXT PRIMARY KEY,
            organization_id TEXT,
            user_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'available',
            scenario TEXT NOT NULL DEFAULT 'basic_execution',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS domain_alerts (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'info',
            entity_type TEXT,
            entity_id TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            acknowledged_by TEXT,
            acknowledged_at TEXT
        );
        CREATE TABLE IF NOT EXISTS domain_geofences (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            name TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            radius_m REAL NOT NULL DEFAULT 500,
            event_types_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_notification_events (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            notification_id TEXT,
            event_type TEXT NOT NULL,
            provider_reference TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_network_edges (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            partner_organization_id TEXT,
            partner_name TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'invited',
            cities_json TEXT NOT NULL DEFAULT '[]',
            trust_score REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            accepted_at TEXT
        );
        CREATE TABLE IF NOT EXISTS domain_network_offers (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            edge_id TEXT,
            duty_id TEXT,
            status TEXT NOT NULL DEFAULT 'offered',
            amount_paise INTEGER NOT NULL DEFAULT 0,
            expires_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_network_bids (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            offer_id TEXT NOT NULL,
            bidder_organization_id TEXT,
            amount_paise INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'submitted',
            comment TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_settlements (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            partner_organization_id TEXT,
            period_start TEXT,
            period_end TEXT,
            gross_paise INTEGER NOT NULL DEFAULT 0,
            deductions_paise INTEGER NOT NULL DEFAULT 0,
            net_paise INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'draft',
            evidence_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_report_exports (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            report_type TEXT NOT NULL,
            filters_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'ready',
            download_token TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            expires_at TEXT NOT NULL,
            created_by TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_report_views (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            name TEXT NOT NULL,
            config_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, name)
        );
        CREATE TABLE IF NOT EXISTS domain_report_schedules (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            report_type TEXT NOT NULL,
            cadence TEXT NOT NULL DEFAULT 'weekly',
            recipients_json TEXT NOT NULL DEFAULT '[]',
            filters_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'active',
            next_run_at TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_consents (
            id TEXT PRIMARY KEY,
            organization_id TEXT,
            subject_id TEXT NOT NULL,
            purpose TEXT NOT NULL,
            policy_version TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'granted',
            evidence_json TEXT NOT NULL DEFAULT '{}',
            captured_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_retention_locks (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            expires_at TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_booking_stops (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            booking_id TEXT NOT NULL,
            stop_index INTEGER NOT NULL,
            label TEXT NOT NULL,
            address_json TEXT NOT NULL DEFAULT '{}',
            arrival_at TEXT,
            departure_at TEXT,
            status TEXT NOT NULL DEFAULT 'planned',
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, booking_id, stop_index)
        );
        CREATE TABLE IF NOT EXISTS domain_recurring_bookings (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            customer_id TEXT,
            cadence TEXT NOT NULL,
            start_at TEXT NOT NULL,
            end_at TEXT,
            occurrences INTEGER NOT NULL DEFAULT 1,
            generated_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            template_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_capacity_locks (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            booking_id TEXT,
            starts_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'held',
            created_at TEXT NOT NULL,
            released_at TEXT
        );
        CREATE TABLE IF NOT EXISTS domain_billing_notes (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            note_type TEXT NOT NULL,
            invoice_id TEXT,
            customer_id TEXT,
            reference TEXT NOT NULL,
            amount_paise INTEGER NOT NULL DEFAULT 0,
            tax_paise INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'draft',
            reason TEXT NOT NULL DEFAULT '',
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, reference)
        );
        CREATE TABLE IF NOT EXISTS domain_payment_links (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            invoice_id TEXT,
            amount_paise INTEGER NOT NULL DEFAULT 0,
            token_hash TEXT NOT NULL UNIQUE,
            short_code TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'created',
            expires_at TEXT NOT NULL,
            paid_at TEXT,
            provider_reference TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_jobs (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            payload_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            error_message TEXT NOT NULL DEFAULT '',
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_auth_factors (
            user_id TEXT PRIMARY KEY,
            organization_id TEXT,
            factor_type TEXT NOT NULL DEFAULT 'totp',
            secret_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            recovery_codes_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            verified_at TEXT,
            last_used_at TEXT
        );
        CREATE TABLE IF NOT EXISTS domain_api_keys (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            name TEXT NOT NULL,
            key_hash TEXT NOT NULL UNIQUE,
            key_prefix TEXT NOT NULL,
            scopes_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'active',
            last_used_at TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            revoked_at TEXT
        );
        CREATE TABLE IF NOT EXISTS domain_security_events (
            id TEXT PRIMARY KEY,
            organization_id TEXT,
            user_id TEXT,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'info',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_extended_versions_entity ON domain_record_versions(organization_id, entity_type, entity_id, version);
        CREATE INDEX IF NOT EXISTS idx_extended_costs_org ON domain_cost_entries(organization_id, cost_type, created_at);
        CREATE INDEX IF NOT EXISTS idx_extended_alerts_org ON domain_alerts(organization_id, status, created_at);
        CREATE INDEX IF NOT EXISTS idx_extended_network_org ON domain_network_edges(organization_id, status);
        CREATE INDEX IF NOT EXISTS idx_extended_exports_org ON domain_report_exports(organization_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_extended_stops_booking ON domain_booking_stops(organization_id, booking_id, stop_index);
        CREATE INDEX IF NOT EXISTS idx_extended_recurring_org ON domain_recurring_bookings(organization_id, status, start_at);
        CREATE INDEX IF NOT EXISTS idx_extended_capacity_resource ON domain_capacity_locks(organization_id, resource_type, resource_id, starts_at, ends_at);
        CREATE INDEX IF NOT EXISTS idx_extended_jobs_queue ON domain_jobs(organization_id, status, available_at);
        CREATE INDEX IF NOT EXISTS idx_extended_security_org ON domain_security_events(organization_id, created_at);
        """
    )
    try:
        conn.execute("ALTER TABLE domain_device_bindings ADD COLUMN push_token TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass


def _org(user) -> str:
    return _org_base(user)


def _org_base(user) -> str:
    organization_id = user["organization_id"]
    if not organization_id:
        raise DomainError(403, "An organization-linked account is required", "organization_required")
    return organization_id


def _staff(user) -> None:
    if user["role"] not in {"vendor", "corporate"}:
        raise DomainError(403, "This workflow is restricted to organization operators", "role_forbidden")


def _driver_or_staff(user) -> None:
    if user["role"] not in {"vendor", "corporate", "driver"}:
        raise DomainError(403, "This workflow is not available for this role", "role_forbidden")


def _parse(raw_route: str):
    parsed = urlsplit(raw_route)
    return parsed.path.rstrip("/") or "/", parse_qs(parsed.query)


def _limit(query: dict, default: int = 100) -> int:
    try:
        return min(max(int(query.get("limit", [default])[0] or default), 1), 500)
    except (ValueError, TypeError):
        return default


def _json_body(payload, key, default):
    value = payload.get(key, default)
    return value if isinstance(value, (dict, list)) else default


def _item(row, json_fields=()):
    return _serialize(row, json_fields)


def _list(conn, table: str, org: str, order: str = "created_at DESC", limit: int = 100):
    rows = conn.execute(f"SELECT * FROM {table} WHERE organization_id = ? ORDER BY {order} LIMIT ?", (org, limit)).fetchall()
    return [_serialize(row) for row in rows]


def _version(conn, user, entity_type: str, entity_id: str, payload: dict, change_type: str = "snapshot") -> dict:
    org = _org(user)
    row = conn.execute("SELECT COALESCE(MAX(version), 0) + 1 AS n FROM domain_record_versions WHERE organization_id = ? AND entity_type = ? AND entity_id = ?", (org, entity_type, entity_id)).fetchone()
    version = int(row["n"])
    record_id = new_id("version")
    conn.execute("INSERT INTO domain_record_versions(id, organization_id, entity_type, entity_id, version, change_type, payload_json, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (record_id, org, entity_type, entity_id, version, change_type, json.dumps(payload), user["id"], now_iso()))
    return {"id": record_id, "organization_id": org, "entity_type": entity_type, "entity_id": entity_id, "version": version, "change_type": change_type, "payload": payload}


def _audit_event(conn, user, action: str, entity_type: str, entity_id: str, ip: str, metadata: dict | None = None) -> None:
    _audit(conn, user, action, entity_type, entity_id, ip, metadata or {})


def _onboarding(conn, user, method: str, route: str, payload: dict, ip: str):
    org = _org(user)
    now = now_iso()
    if route == "/api/onboarding/provision" and method == "POST":
        _staff(user)
        profile = payload.get("organization") if isinstance(payload.get("organization"), dict) else payload
        updates = []
        values = []
        for key in ("name", "city", "phone", "gstin"):
            if key in profile:
                updates.append(f"{key} = ?"); values.append(str(profile.get(key) or "").strip())
        if updates:
            values.append(org); conn.execute(f"UPDATE organizations SET {', '.join(updates)} WHERE id = ?", values)
        branch = payload.get("branch") if isinstance(payload.get("branch"), dict) else {}
        existing = conn.execute("SELECT id FROM domain_branches WHERE organization_id = ? ORDER BY created_at LIMIT 1", (org,)).fetchone()
        if not existing:
            branch_id = new_id("branch")
            conn.execute("INSERT INTO domain_branches(id, organization_id, code, name, city, address_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (branch_id, org, _text(branch, "code", "HQ", 24).upper(), _text(branch, "name", "Main branch", 160), _text(branch, "city", profile.get("city", ""), 80), json.dumps(_json_body(branch, "address", {})), now, now))
        settings = payload.get("tax_profile") if isinstance(payload.get("tax_profile"), dict) else {}
        existing_settings = conn.execute("SELECT settings_json FROM domain_org_settings WHERE organization_id = ?", (org,)).fetchone()
        merged = _json(existing_settings["settings_json"], {}) if existing_settings else {}
        merged.update({"tax_profile": settings, "numbering_series": _json_body(payload, "numbering_series", merged.get("numbering_series", {}))})
        conn.execute("INSERT INTO domain_org_settings(organization_id, settings_json, updated_by, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT(organization_id) DO UPDATE SET settings_json = excluded.settings_json, updated_by = excluded.updated_by, updated_at = excluded.updated_at", (org, json.dumps(merged), user["id"], now))
        _audit_event(conn, user, "onboarding.provisioned", "organization", org, ip, {"keys": sorted(profile.keys())})
        return {"ok": True, "organization_id": org, "provisioned": True}
    if route == "/api/onboarding" and method == "PATCH":
        step = _text(payload, "step", maximum=60)
        if step not in {key for key, _ in ONBOARDING_STEPS}:
            raise DomainError(400, "Unknown onboarding step", "validation_error")
        row = conn.execute("SELECT steps_json, metadata_json FROM domain_onboarding WHERE organization_id = ?", (org,)).fetchone()
        steps = _json(row["steps_json"], {}) if row else {}
        metadata = _json(row["metadata_json"], {}) if row else {}
        steps[step] = {"status": _text(payload, "status", "complete", 30), "updated_at": now}
        if isinstance(payload.get("metadata"), dict): metadata.update(payload["metadata"])
        complete = all(steps.get(key, {}).get("status") == "complete" for key, _ in ONBOARDING_STEPS)
        conn.execute("INSERT INTO domain_onboarding(organization_id, steps_json, metadata_json, completed_at, updated_by, updated_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(organization_id) DO UPDATE SET steps_json = excluded.steps_json, metadata_json = excluded.metadata_json, completed_at = excluded.completed_at, updated_by = excluded.updated_by, updated_at = excluded.updated_at", (org, json.dumps(steps), json.dumps(metadata), now if complete else None, user["id"], now))
        _audit_event(conn, user, "onboarding.step_updated", "organization", org, ip, {"step": step, "status": steps[step]["status"]})
        return {"ok": True, "step": step, "status": steps[step]["status"], "completed_at": now if complete else None}
    if route in {"/api/onboarding", "/api/setup"} and method == "GET":
        row = conn.execute("SELECT steps_json, metadata_json, completed_at FROM domain_onboarding WHERE organization_id = ?", (org,)).fetchone()
        steps = _json(row["steps_json"], {}) if row else {}
        counts = {
            "organization_profile": bool(conn.execute("SELECT 1 FROM organizations WHERE id = ? AND length(trim(name)) >= 2 AND city <> ''", (org,)).fetchone()),
            "default_branch": bool(conn.execute("SELECT 1 FROM domain_branches WHERE organization_id = ?", (org,)).fetchone()),
            "tax_profile": bool(conn.execute("SELECT 1 FROM organizations WHERE id = ? AND gstin <> ''", (org,)).fetchone()) or bool((_json(conn.execute("SELECT settings_json FROM domain_org_settings WHERE organization_id = ?", (org,)).fetchone()["settings_json"], {}) if conn.execute("SELECT settings_json FROM domain_org_settings WHERE organization_id = ?", (org,)).fetchone() else {}).get("tax_profile")),
            "team_access": bool(conn.execute("SELECT 1 FROM users WHERE organization_id = ? AND id <> ?", (org, user["id"])).fetchone()),
            "masters": all(bool(conn.execute(f"SELECT 1 FROM {table} WHERE organization_id = ?", (org,)).fetchone()) for table in ("domain_customers", "domain_drivers", "domain_vehicles")),
            "price_book": bool(conn.execute("SELECT 1 FROM domain_price_books WHERE organization_id = ? AND status = 'active'", (org,)).fetchone()),
            "first_booking": bool(conn.execute("SELECT 1 FROM domain_bookings WHERE organization_id = ?", (org,)).fetchone()),
            "driver_readiness": bool(conn.execute("SELECT 1 FROM domain_drivers WHERE organization_id = ? AND status IN ('available','active')", (org,)).fetchone()),
        }
        items = []
        for key, label in ONBOARDING_STEPS:
            complete = counts[key] or steps.get(key, {}).get("status") == "complete"
            items.append({"key": key, "label": label, "complete": bool(complete), "status": "complete" if complete else steps.get(key, {}).get("status", "pending")})
        completed = sum(item["complete"] for item in items)
        return {"ok": True, "completed": completed, "total": len(items), "progress_pct": round(completed * 100 / len(items)), "completed_at": row["completed_at"] if row else None, "items": items, "metadata": _json(row["metadata_json"], {}) if row else {}}
    return None


def _duplicate_check(conn, user, payload, ip):
    org = _org(user); _staff(user)
    entity_type = _text(payload, "entity_type", maximum=30)
    values = payload.get("values") if isinstance(payload.get("values"), dict) else payload
    specs = {
        "customer": ("domain_customers", ("phone", "email", "gstin")),
        "supplier": ("domain_suppliers", ("phone", "email", "gstin")),
        "driver": ("domain_drivers", ("phone", "license_number")),
        "vehicle": ("domain_vehicles", ("registration_number",)),
    }
    if entity_type not in specs: raise DomainError(400, "Unsupported duplicate-check entity", "validation_error")
    table, fields = specs[entity_type]; matches = []
    label_field = "full_name" if entity_type == "driver" else "registration_number" if entity_type == "vehicle" else "name"
    for field in fields:
        value = str(values.get(field) or "").strip()
        normalized = re.sub(r"[^a-z0-9]", "", value.lower())
        if not normalized: continue
        rows = conn.execute(f"SELECT id, {label_field}, {field} AS match_value FROM {table} WHERE organization_id = ?", (org,)).fetchall()
        for row in rows:
            candidate = re.sub(r"[^a-z0-9]", "", str(row["match_value"] or "").lower())
            if candidate and candidate == normalized:
                matches.append({"field": field, "normalized_value": normalized, "existing_id": row["id"], "label": row[label_field]})
    for match in matches:
        conn.execute("INSERT INTO domain_duplicate_matches(id, organization_id, entity_type, field_name, normalized_value, existing_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (new_id("duplicate"), org, entity_type, match["field"], match["normalized_value"], match["existing_id"], now_iso()))
    return {"ok": True, "entity_type": entity_type, "duplicate": bool(matches), "matches": matches}


def _soft_update(conn, user, route, method, payload, ip):
    if method != "PATCH": return None
    parts = route.split("/")
    if len(parts) != 4 or parts[1] != "api" or parts[2] not in {"customers", "drivers", "vehicles", "suppliers", "manufacturers"}: return None
    org = _org(user); _staff(user)
    config = {
        "customers": ("domain_customers", ("name", "email", "phone", "gstin", "status")),
        "drivers": ("domain_drivers", ("full_name", "phone", "license_number", "city", "status", "driver_type", "vehicle_registration", "vehicle_group")),
        "manufacturers": ("domain_manufacturers", ("name", "code", "country", "status")),
        "vehicles": ("domain_vehicles", (
            "registration_number", "vehicle_type", "vehicle_group", "make_model", "manufacturer", "model", "year", "city", "status",
            "fuel_type", "seating_capacity", "luggage_capacity", "ownership_type", "supplier_id", "supplier_name", "owner_name", "branch_name",
            "gps_provider", "rc_expiry", "insurance_expiry", "puc_expiry", "notes",
        )),
        "suppliers": ("domain_suppliers", ("name", "email", "phone", "gstin", "status")),
    }
    table, allowed = config[parts[2]]; entity_id = parts[3]
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ? AND organization_id = ?", (entity_id, org)).fetchone()
    if not row: raise DomainError(404, "Record not found", "not_found")
    if payload.get("status") in {"inactive", "archived", "deleted"} and parts[2] in {"drivers", "vehicles"}:
        field = "driver_id" if parts[2] == "drivers" else "vehicle_id"
        if conn.execute(f"SELECT 1 FROM domain_duties WHERE organization_id = ? AND {field} = ? AND status NOT IN ('completed','cancelled') LIMIT 1", (org, entity_id)).fetchone():
            raise DomainError(409, "This record is referenced by an open duty", "open_duty_reference")
    updates = []; values = []
    numeric_vehicle_fields = {"year", "seating_capacity", "luggage_capacity"}
    for key in allowed:
        if key in payload:
            if parts[2] == "vehicles" and key in numeric_vehicle_fields:
                value = int(payload[key]) if payload[key] not in (None, "") else None
                if value is not None and value < 0:
                    raise DomainError(400, f"{key} cannot be negative", "validation_error")
            elif parts[2] == "drivers" and key == "driver_type":
                raw_type = str(payload[key] or "own").lower().strip()
                value = raw_type if raw_type in ("own", "supplier", "dco") else "own"
            else:
                value = str(payload[key] or "").strip()
            updates.append(f"{key} = ?"); values.append(value)
    if parts[2] == "vehicles":
        if "manufacturer" in payload and not str(payload["manufacturer"] or "").strip():
            raise DomainError(400, "Manufacturer is a required field and cannot be empty", "validation_error")
        if "model" in payload and not str(payload["model"] or "").strip():
            raise DomainError(400, "Model is a required field and cannot be empty", "validation_error")
    if parts[2] == "vehicles" and ("manufacturer" in payload or "model" in payload) and "make_model" not in payload:
        new_mfr = str(payload.get("manufacturer") or (row["manufacturer"] if "manufacturer" in row.keys() else "")).strip()
        new_model = str(payload.get("model") or (row["model"] if "model" in row.keys() else "")).strip()
        updates.append("make_model = ?"); values.append(f"{new_mfr} {new_model}".strip())
    if not updates: return {"ok": True, "item": _serialize(row)}
    updates.append("updated_at = ?"); values.extend([now_iso(), entity_id, org])
    conn.execute(f"UPDATE {table} SET {', '.join(updates)} WHERE id = ? AND organization_id = ?", values)
    _audit_event(conn, user, f"{parts[2]}.updated", parts[2][:-1], entity_id, ip, {"fields": [key for key in allowed if key in payload]})
    return {"ok": True, "item": _serialize(conn.execute(f"SELECT * FROM {table} WHERE id = ?", (entity_id,)).fetchone())}


def _price_book_versions(conn, user, route, method, payload, ip):
    match = re.match(r"^/api/price-books/([^/]+)/versions$", route)
    if match:
        org = _org(user); _staff(user); book_id = match.group(1)
        book = conn.execute("SELECT * FROM domain_price_books WHERE id = ? AND organization_id = ?", (book_id, org)).fetchone()
        if not book: raise DomainError(404, "Price book not found", "not_found")
        if method == "GET":
            rows = conn.execute("SELECT * FROM domain_record_versions WHERE organization_id = ? AND entity_type = 'price_book' AND entity_id = ? ORDER BY version DESC", (org, book_id)).fetchall()
            return {"ok": True, "items": [_serialize(row, ("payload_json",)) for row in rows], "count": len(rows)}
        if method == "POST":
            snapshot = {"book": _serialize(book), "items": [dict(row) for row in conn.execute("SELECT * FROM domain_price_book_items WHERE price_book_id = ?", (book_id,)).fetchall()], "changes": payload.get("changes", {})}
            record = _version(conn, user, "price_book", book_id, snapshot, "version_created")
            _audit_event(conn, user, "price_book.version_created", "price_book", book_id, ip, {"version": record["version"]})
            return {"ok": True, "item": record}
    match = re.match(r"^/api/price-books/([^/]+)/approve$", route)
    if match and method == "POST":
        org = _org(user); _staff(user); book_id = match.group(1)
        row = conn.execute("SELECT * FROM domain_price_books WHERE id = ? AND organization_id = ?", (book_id, org)).fetchone()
        if not row: raise DomainError(404, "Price book not found", "not_found")
        conn.execute("UPDATE domain_price_books SET status = 'active', updated_at = ? WHERE id = ?", (now_iso(), book_id))
        record = _version(conn, user, "price_book", book_id, {"status": "active", "comment": _text(payload, "comment", maximum=500)}, "approved")
        _audit_event(conn, user, "price_book.approved", "price_book", book_id, ip, {"version": record["version"]})
        return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_price_books WHERE id = ?", (book_id,)).fetchone()), "version": record}
    return None


def _duty_exception(conn, user, route, method, payload, ip):
    match = re.match(r"^/api/duties/([^/]+)/(reassign|no-show|force-close|navigation|call|sos|trip-share|reconcile)$", route)
    if not match or method != "POST": return None
    org = _org(user); action = match.group(2); duty_id = match.group(1)
    duty = conn.execute("SELECT * FROM domain_duties WHERE id = ? AND organization_id = ?", (duty_id, org)).fetchone()
    if not duty: raise DomainError(404, "Duty not found", "not_found")
    if action == "reassign":
        _staff(user)
        updates = {key: payload.get(key) for key in ("driver_id", "vehicle_id", "reporting_at") if key in payload}
        if "driver_id" in updates:
            updates["driver_id"] = _text(payload, "driver_id") or None
            if updates["driver_id"]:
                _assert_owned(conn, "domain_drivers", updates["driver_id"], org)
        if "vehicle_id" in updates:
            updates["vehicle_id"] = _text(payload, "vehicle_id") or None
            if updates["vehicle_id"]:
                _assert_owned(conn, "domain_vehicles", updates["vehicle_id"], org)
        updates["status"] = "assigned"
        updates["updated_at"] = now_iso()
        conn.execute("UPDATE domain_duties SET " + ", ".join(f"{key} = ?" for key in updates) + " WHERE id = ?", (*updates.values(), duty_id))
        if updates.get("driver_id"):
            driver_user = conn.execute("SELECT user_id FROM domain_drivers WHERE id = ? AND organization_id = ?", (updates["driver_id"], org)).fetchone()
            if driver_user and driver_user["user_id"]:
                _queue_push_notification(conn, org, driver_user["user_id"], "duty_reassigned", {"duty_id": duty_id, "booking_id": duty["booking_id"], "reporting_at": updates.get("reporting_at") or duty["reporting_at"] or ""})
        _audit_event(conn, user, "duty.reassigned", "duty", duty_id, ip, updates)
        return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_duties WHERE id = ?", (duty_id,)).fetchone())}
    if action == "no-show":
        _staff(user); conn.execute("UPDATE domain_duties SET status = 'cancelled', updated_at = ? WHERE id = ?", (now_iso(), duty_id)); conn.execute("UPDATE domain_bookings SET status = 'no_show', updated_at = ? WHERE id = ?", (now_iso(), duty["booking_id"])); _alert(conn, user, "no_show", "high", "duty", duty_id, {"reason": _text(payload, "reason", "passenger_no_show", 500)}, ip); return {"ok": True, "status": "no_show", "item": _serialize(conn.execute("SELECT * FROM domain_duties WHERE id = ?", (duty_id,)).fetchone())}
    if action == "force-close":
        _staff(user); conn.execute("UPDATE domain_duties SET status = 'completed', completed_at = COALESCE(completed_at, ?), updated_at = ? WHERE id = ?", (now_iso(), now_iso(), duty_id)); _audit_event(conn, user, "duty.force_closed", "duty", duty_id, ip, {"reason": _text(payload, "reason", maximum=500)}); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_duties WHERE id = ?", (duty_id,)).fetchone())}
    if action == "navigation":
        destination = _text(payload, "destination", maximum=300); result = DEFAULT_PROVIDERS.maps.route(pickup={"label": _text(payload, "origin", "current location", 300)}, dropoff={"label": destination or "dropoff"}); return {"ok": True, "navigation": {"status": result.status, "reference": result.reference, "payload": result.payload}}
    if action == "call":
        result = DEFAULT_PROVIDERS.telephony.create_masked_call(from_number="driver", to_number=_text(payload, "recipient", "passenger", 80), context=f"duty:{duty_id}"); call_id = new_id("call"); conn.execute("INSERT INTO domain_calls(id, organization_id, duty_id, caller_id, recipient, masked_number, status, provider_reference, consent, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (call_id, org, duty_id, user["id"], _text(payload, "recipient", "passenger", 80), result.payload.get("masked_number", "mock-masked"), result.status, result.reference, 1 if payload.get("consent", True) else 0, now_iso())); return {"ok": True, "call": {"id": call_id, "status": result.status, "reference": result.reference, "masked_number": result.payload.get("masked_number", "mock-masked")}}
    if action == "sos":
        row = _create_sos(conn, user, duty_id, payload, ip); return {"ok": True, "item": row}
    if action == "trip-share":
        raw = secrets.token_urlsafe(24); share_id = new_id("share"); expires = (datetime.now(timezone.utc) + timedelta(hours=int(payload.get("expires_hours") or 24))).replace(microsecond=0).isoformat().replace("+00:00", "Z"); conn.execute("INSERT INTO domain_trip_shares(id, organization_id, duty_id, token_hash, recipient, expires_at, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (share_id, org, duty_id, hashlib.sha256(raw.encode()).hexdigest(), _text(payload, "recipient", maximum=254), expires, user["id"], now_iso())); return {"ok": True, "item": {"id": share_id, "duty_id": duty_id, "share_token": raw, "share_url": f"/api/trips/share/{raw}", "expires_at": expires}}
    if action == "reconcile":
        _staff(user); actual = int(payload.get("actual_total_paise") or 0); sale = int(payload.get("sale_total_paise") or 0); variance = actual - sale; record = _version(conn, user, "duty", duty_id, {"actual_total_paise": actual, "sale_total_paise": sale, "variance_paise": variance, "supplier_bill_id": payload.get("supplier_bill_id")}, "reconciliation"); return {"ok": True, "item": {"duty_id": duty_id, "variance_paise": variance, "status": "matched" if variance == 0 else "review"}, "version": record}
    return None


def _create_sos(conn, user, duty_id, payload, ip):
    org = _org(user)
    idempotency_key = _text(payload, "idempotency_key", maximum=160) or None
    if idempotency_key:
        existing = conn.execute("SELECT * FROM domain_sos_events WHERE organization_id = ? AND json_extract(payload_json, '$.idempotency_key') = ?", (org, idempotency_key)).fetchone()
        if existing:
            return _serialize(existing, ("payload_json",))
    event_id = new_id("sos")
    conn.execute("INSERT INTO domain_sos_events(id, organization_id, duty_id, driver_id, latitude, longitude, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (event_id, org, duty_id, payload.get("driver_id") or user["id"], payload.get("latitude"), payload.get("longitude"), json.dumps(payload), now_iso()))
    alert_id = _alert(conn, user, "sos", "critical", "duty", duty_id, payload, ip)
    operator_users = conn.execute("SELECT id FROM users WHERE organization_id = ? AND role IN ('vendor','corporate') AND status = 'active'", (org,)).fetchall()
    for operator in operator_users:
        _queue_push_notification(conn, org, operator["id"], "sos_alert", {"duty_id": duty_id, "alert_id": alert_id, "severity": "critical"})
    _audit_event(conn, user, "duty.sos_raised", "duty", duty_id, ip, {"alert_id": alert_id})
    return _serialize(conn.execute("SELECT * FROM domain_sos_events WHERE id = ?", (event_id,)).fetchone(), ("payload_json",))


def _alert(conn, user, alert_type, severity, entity_type, entity_id, payload, ip):
    org = _org(user); alert_id = new_id("alert"); conn.execute("INSERT INTO domain_alerts(id, organization_id, alert_type, severity, entity_type, entity_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (alert_id, org, alert_type, severity, entity_type, entity_id, json.dumps(payload or {}), now_iso())); _audit_event(conn, user, "alert.created", "alert", alert_id, ip, {"alert_type": alert_type}); return alert_id


def _billing_and_costs(conn, user, route, method, payload, ip):
    org = _org(user)
    if route == "/api/invoices" and method == "GET": return None
    if route == "/api/tax/calculate" and method == "POST":
        _staff(user)
        taxable = int(payload.get("taxable_paise") or 0); rate_bps = int(payload.get("tax_rate_bps") or 1800); origin = _text(payload, "origin_state", "Maharashtra", 80).lower(); destination = _text(payload, "destination_state", origin, 80).lower(); tax = round(taxable * rate_bps / 10000); intra = origin == destination
        return {"ok": True, "tax": {"taxable_paise": taxable, "rate_bps": rate_bps, "supply_type": "intra_state" if intra else "inter_state", "cgst_paise": tax // 2 if intra else 0, "sgst_paise": tax - tax // 2 if intra else 0, "igst_paise": 0 if intra else tax, "total_paise": taxable + tax}}
    if route == "/api/reports/vehicle-pnl" and method == "GET":
        _staff(user)
        vehicles = conn.execute("""
            SELECT id, registration_number, make_model, vehicle_group, vehicle_type, fuel_type,
                   ownership_type, year, city, status, current_odometer_km,
                   COALESCE(purchase_price_paise, 0) as purchase_price_paise,
                   COALESCE(purchase_date, '') as purchase_date,
                   COALESCE(down_payment_paise, 0) as down_payment_paise,
                   COALESCE(emi_monthly_paise, 0) as emi_monthly_paise,
                   COALESCE(emi_tenure_months, 0) as emi_tenure_months,
                   COALESCE(emi_paid_months, 0) as emi_paid_months,
                   COALESCE(insurance_annual_paise, 0) as insurance_annual_paise,
                   COALESCE(fitness_expiry, '') as fitness_expiry,
                   COALESCE(permit_expiry, '') as permit_expiry
            FROM domain_vehicles
            WHERE organization_id = ?
            ORDER BY registration_number ASC
        """, (org,)).fetchall()

        duty_stats = {r["vehicle_id"]: r for r in conn.execute("""
            SELECT d.vehicle_id,
                   COUNT(d.id) as duty_count,
                   SUM(CASE WHEN d.end_odometer > d.start_odometer THEN d.end_odometer - d.start_odometer ELSE 0 END) as total_km,
                   SUM(COALESCE(i.total_paise, 0)) as revenue_paise
            FROM domain_duties d
            LEFT JOIN domain_invoices i ON i.duty_id = d.id AND i.organization_id = ?
            WHERE d.organization_id = ?
            GROUP BY d.vehicle_id
        """, (org, org)).fetchall()}

        cost_rows = conn.execute("""
            SELECT vehicle_id, category, SUM(amount_paise) as total_amount
            FROM domain_cost_entries
            WHERE organization_id = ? AND vehicle_id IS NOT NULL
            GROUP BY vehicle_id, category
        """, (org,)).fetchall()

        cost_map = {}
        for cr in cost_rows:
            vid = cr["vehicle_id"]
            if vid not in cost_map:
                cost_map[vid] = {}
            cost_map[vid][cr["category"]] = cr["total_amount"]

        items = []
        fleet_totals = {"revenue_paise": 0, "cost_paise": 0, "profit_paise": 0, "total_km": 0, "duty_count": 0}

        for v in vehicles:
            v_dict = dict(v)
            vid = v["id"]
            d_stat = duty_stats.get(vid, {"duty_count": 0, "total_km": 0, "revenue_paise": 0})
            c_breakdown = cost_map.get(vid, {})

            rev = d_stat["revenue_paise"] or 0
            cost = sum(c_breakdown.values())
            km = d_stat["total_km"] or (v_dict["current_odometer_km"] or 0)
            profit = rev - cost
            margin = round((profit / rev) * 100, 1) if rev > 0 else 0
            rev_per_km = round(rev / km) if km > 0 else 0
            cost_per_km = round(cost / km) if km > 0 else 0
            breakeven_reached = profit >= 0
            payback_pct = min(100.0, round((rev / cost) * 100, 1)) if cost > 0 else 100.0

            item = {
                **v_dict,
                "duty_count": d_stat["duty_count"],
                "total_km": km,
                "revenue_paise": rev,
                "cost_paise": cost,
                "cost_breakdown": c_breakdown,
                "profit_paise": profit,
                "profit_margin_pct": margin,
                "revenue_per_km_paise": rev_per_km,
                "cost_per_km_paise": cost_per_km,
                "breakeven_reached": breakeven_reached,
                "payback_pct": payback_pct
            }
            items.append(item)
            fleet_totals["revenue_paise"] += rev
            fleet_totals["cost_paise"] += cost
            fleet_totals["profit_paise"] += profit
            fleet_totals["total_km"] += km
            fleet_totals["duty_count"] += d_stat["duty_count"]

        fleet_totals["profit_margin_pct"] = round((fleet_totals["profit_paise"] / fleet_totals["revenue_paise"]) * 100, 1) if fleet_totals["revenue_paise"] > 0 else 0
        fleet_totals["rev_per_km_paise"] = round(fleet_totals["revenue_paise"] / fleet_totals["total_km"]) if fleet_totals["total_km"] > 0 else 0
        fleet_totals["cost_per_km_paise"] = round(fleet_totals["cost_paise"] / fleet_totals["total_km"]) if fleet_totals["total_km"] > 0 else 0

        return {"ok": True, "items": items, "fleet_summary": fleet_totals, "count": len(items)}

    lifecycle_match = re.match(r"^/api/vehicles/([^/]+)/lifecycle$", route)
    if lifecycle_match and method == "GET":
        _staff(user)
        vid = unquote(lifecycle_match.group(1))
        v = conn.execute("SELECT * FROM domain_vehicles WHERE (id = ? OR registration_number = ?) AND organization_id = ?", (vid, vid, org)).fetchone()
        if not v:
            raise DomainError(404, "Vehicle not found", "not_found")
        v_id = v["id"]
        v_dict = dict(v)

        costs = conn.execute("""
            SELECT id, category, amount_paise, status, notes,
                   COALESCE(NULLIF(expense_date, ''), SUBSTR(created_at, 1, 10)) as expense_date,
                   created_at
            FROM domain_cost_entries
            WHERE vehicle_id = ? AND organization_id = ?
            ORDER BY COALESCE(NULLIF(expense_date, ''), SUBSTR(created_at, 1, 10)) ASC
        """, (v_id, org)).fetchall()

        duties = conn.execute("""
            SELECT d.id, d.booking_id, d.reporting_at, d.started_at, d.completed_at,
                   d.start_odometer, d.end_odometer,
                   COALESCE(d.end_odometer - d.start_odometer, 0) as trip_km,
                   COALESCE(i.id, '') as invoice_id,
                   COALESCE(i.total_paise, 0) as invoice_paise,
                   COALESCE(i.status, '') as invoice_status,
                   COALESCE(b.customer_id, '') as customer_id,
                   COALESCE(c.name, 'Direct Client') as customer_name
            FROM domain_duties d
            LEFT JOIN domain_invoices i ON i.duty_id = d.id AND i.organization_id = ?
            LEFT JOIN domain_bookings b ON b.id = d.booking_id
            LEFT JOIN domain_customers c ON c.id = b.customer_id
            WHERE d.vehicle_id = ? AND d.organization_id = ?
            ORDER BY d.reporting_at ASC
        """, (org, v_id, org)).fetchall()

        months = {}
        for c in costs:
            m = (c["expense_date"] or c["created_at"])[:7]
            if not m or len(m) < 7: continue
            if m not in months: months[m] = {"revenue_paise": 0, "cost_paise": 0}
            months[m]["cost_paise"] += c["amount_paise"]

        for d in duties:
            m = (d["reporting_at"] or "")[:7]
            if not m or len(m) < 7: continue
            if m not in months: months[m] = {"revenue_paise": 0, "cost_paise": 0}
            months[m]["revenue_paise"] += d["invoice_paise"]

        timeline = []
        cumulative_rev = 0
        cumulative_cost = 0
        breakeven_month = None

        for m in sorted(months.keys()):
            r_paise = months[m]["revenue_paise"]
            c_paise = months[m]["cost_paise"]
            net_paise = r_paise - c_paise
            cumulative_rev += r_paise
            cumulative_cost += c_paise
            cum_net = cumulative_rev - cumulative_cost

            if cum_net >= 0 and breakeven_month is None:
                breakeven_month = m

            timeline.append({
                "month": m,
                "revenue_paise": r_paise,
                "cost_paise": c_paise,
                "net_paise": net_paise,
                "cumulative_revenue_paise": cumulative_rev,
                "cumulative_cost_paise": cumulative_cost,
                "cumulative_net_paise": cum_net
            })

        total_rev = sum(d["invoice_paise"] for d in duties)
        total_cost = sum(c["amount_paise"] for c in costs)
        profit = total_rev - total_cost
        margin = round((profit / total_rev) * 100, 1) if total_rev > 0 else 0
        total_km = sum(d["trip_km"] for d in duties) or v_dict.get("current_odometer_km") or 0

        cost_breakdown = {}
        for c in costs:
            cat = c["category"]
            cost_breakdown[cat] = cost_breakdown.get(cat, 0) + c["amount_paise"]

        return {
            "ok": True,
            "vehicle": v_dict,
            "summary": {
                "total_revenue_paise": total_rev,
                "total_cost_paise": total_cost,
                "profit_paise": profit,
                "profit_margin_pct": margin,
                "total_km": total_km,
                "duty_count": len(duties),
                "cost_per_km_paise": round(total_cost / total_km) if total_km > 0 else 0,
                "revenue_per_km_paise": round(total_rev / total_km) if total_km > 0 else 0,
                "breakeven_reached": profit >= 0,
                "breakeven_month": breakeven_month,
                "payback_pct": min(100.0, round((total_rev / total_cost) * 100, 1)) if total_cost > 0 else 100.0
            },
            "cost_breakdown": cost_breakdown,
            "monthly_cashflow": timeline,
            "recent_expenses": [dict(c) for c in costs[-25:]],
            "recent_duties": [dict(d) for d in duties[-20:]]
        }
    cancel = re.match(r"^/api/invoices/([^/]+)/e-invoice/cancel$", route)
    if cancel and method == "POST":
        _staff(user); row = conn.execute("SELECT * FROM domain_einvoice_records WHERE organization_id = ? AND invoice_id = ?", (org, cancel.group(1))).fetchone();
        if not row: raise DomainError(404, "E-invoice record not found", "not_found")
        conn.execute("UPDATE domain_einvoice_records SET status = 'cancelled', payload_json = ? WHERE id = ?", (json.dumps({**_json(row["payload_json"], {}), "cancel_reason": _text(payload, "reason", maximum=500)}), row["id"])); _audit_event(conn, user, "invoice.einvoice_cancelled", "invoice", cancel.group(1), ip, {}); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_einvoice_records WHERE id = ?", (row["id"],)).fetchone(), ("payload_json",))}
    if route == "/api/receipts/allocate" and method == "POST":
        _staff(user); invoice_id = _text(payload, "invoice_id"); amount = int(payload.get("amount_paise") or 0); if_missing = conn.execute("SELECT id FROM domain_invoices WHERE id = ? AND organization_id = ?", (invoice_id, org)).fetchone();
        if not if_missing or amount <= 0: raise DomainError(400, "A valid invoice and positive allocation are required", "validation_error")
        allocation_id = new_id("allocation"); conn.execute("INSERT INTO domain_receipt_allocations(id, organization_id, invoice_id, payment_id, amount_paise, reference, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (allocation_id, org, invoice_id, payload.get("payment_id"), amount, _text(payload, "reference", maximum=160), user["id"], now_iso())); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_receipt_allocations WHERE id = ?", (allocation_id,)).fetchone())}
    if route in {"/api/supplier-bills", "/api/costs", "/api/vehicle-costs"} and method == "GET":
        table = {"/api/supplier-bills": "domain_supplier_bills", "/api/costs": "domain_cost_entries", "/api/vehicle-costs": "domain_cost_entries"}[route]; rows = _list(conn, table, org, "created_at DESC", _limit(parse_qs(urlsplit(route).query))); return {"ok": True, "items": rows, "count": len(rows)}
    if route == "/api/supplier-bills" and method == "POST":
        _staff(user); bill_id = new_id("bill"); now = now_iso(); subtotal = int(payload.get("subtotal_paise") or 0); tax = int(payload.get("tax_paise") or 0); total = int(payload.get("total_paise") or subtotal + tax); validation = {"valid": bool(payload.get("bill_number")), "checks": ["bill_number", "amounts", "supplier_reference"]}; conn.execute("INSERT INTO domain_supplier_bills(id, organization_id, supplier_id, bill_number, subtotal_paise, tax_paise, total_paise, status, due_at, duty_id, attachment_json, validation_json, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (bill_id, org, payload.get("supplier_id"), _text(payload, "bill_number", maximum=80) or f"BILL-{bill_id[-6:]}", subtotal, tax, total, _text(payload, "status", "captured", 30), payload.get("due_at"), payload.get("duty_id"), json.dumps(_json_body(payload, "attachment", {})), json.dumps(validation), user["id"], now, now)); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_supplier_bills WHERE id = ?", (bill_id,)).fetchone(), ("attachment_json", "validation_json")), "validation": validation}
    if route in {"/api/costs", "/api/vehicle-costs"} and method == "POST":
        _staff(user); cost_id = new_id("cost"); now = now_iso(); cost_type = _text(payload, "cost_type", "vehicle" if route.endswith("vehicle-costs") else "operational", 30); amount = int(payload.get("amount_paise") or 0); exp_date = _text(payload, "expense_date", maximum=30) or now[:10]; conn.execute("INSERT INTO domain_cost_entries(id, organization_id, cost_type, category, amount_paise, vehicle_id, duty_id, supplier_bill_id, status, attachment_json, notes, created_by, created_at, expense_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (cost_id, org, cost_type, _text(payload, "category", "other", 60), amount, payload.get("vehicle_id"), payload.get("duty_id"), payload.get("supplier_bill_id"), _text(payload, "status", "paid" if payload.get("status") == "paid" else "submitted", 30), json.dumps(_json_body(payload, "attachment", {})), _text(payload, "notes", maximum=500), user["id"], now, exp_date)); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_cost_entries WHERE id = ?", (cost_id,)).fetchone(), ("attachment_json",))}
    if route in {"/api/supplier-payouts", "/api/driver-payouts"} and method in {"GET", "POST"}:
        if method == "GET": return {"ok": True, "items": _list(conn, "domain_payouts", org, "created_at DESC", _limit(parse_qs(urlsplit(route).query)))}
        _staff(user); payout_id = new_id("payout"); now = now_iso(); conn.execute("INSERT INTO domain_payouts(id, organization_id, recipient_type, recipient_id, period_start, period_end, amount_paise, status, metadata_json, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (payout_id, org, _text(payload, "recipient_type", "supplier" if route.endswith("supplier-payouts") else "driver", 30), payload.get("recipient_id"), payload.get("period_start"), payload.get("period_end"), int(payload.get("amount_paise") or 0), "pending_approval", json.dumps(_json_body(payload, "metadata", {})), user["id"], now, now)); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_payouts WHERE id = ?", (payout_id,)).fetchone(), ("metadata_json",))}
    if route == "/api/financial-actions" and method == "POST":
        _staff(user); action_id = new_id("financial"); conn.execute("INSERT INTO domain_financial_actions(id, organization_id, action_type, entity_type, entity_id, payload_json, requested_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (action_id, org, _text(payload, "action_type", maximum=60), _text(payload, "entity_type", maximum=40), _text(payload, "entity_id", maximum=160), json.dumps(payload), user["id"], now_iso())); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_financial_actions WHERE id = ?", (action_id,)).fetchone(), ("payload_json",))}
    action_match = re.match(r"^/api/financial-actions/([^/]+)/(approve|reject)$", route)
    if action_match and method == "POST":
        _staff(user); status = "approved" if action_match.group(2) == "approve" else "rejected"; row = conn.execute("SELECT * FROM domain_financial_actions WHERE id = ? AND organization_id = ?", (action_match.group(1), org)).fetchone();
        if not row: raise DomainError(404, "Financial action not found", "not_found")
        conn.execute("UPDATE domain_financial_actions SET status = ?, reviewed_by = ?, review_comment = ?, reviewed_at = ? WHERE id = ?", (status, user["id"], _text(payload, "comment", maximum=500), now_iso(), row["id"])); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_financial_actions WHERE id = ?", (row["id"],)).fetchone(), ("payload_json",))}
    if route == "/api/reconciliations" and method == "POST":
        _staff(user); entity_type = _text(payload, "entity_type", "duty", 40); entity_id = _text(payload, "entity_id", maximum=160); left = int(payload.get("customer_total_paise") or 0); right = int(payload.get("supplier_total_paise") or 0); record = _version(conn, user, entity_type, entity_id, {"customer_total_paise": left, "supplier_total_paise": right, "variance_paise": left - right}, "reconciliation"); return {"ok": True, "item": {"entity_id": entity_id, "variance_paise": left - right, "status": "matched" if left == right else "review"}, "version": record}
    return None


def _corporate(conn, user, route, method, payload, ip):
    org = _org(user)
    chain = re.match(r"^/api/bookings/([^/]+)/approval-chain$", route)
    if chain:
        _staff(user); booking_id = chain.group(1); _assert_owned(conn, "domain_bookings", booking_id, org)
        if method == "GET":
            rows = conn.execute("SELECT * FROM domain_approval_steps WHERE organization_id = ? AND booking_id = ? ORDER BY level", (org, booking_id)).fetchall(); return {"ok": True, "items": [_serialize(row) for row in rows]}
        if method == "POST":
            levels = payload.get("levels") if isinstance(payload.get("levels"), list) else [{"role": "corporate_admin"}]
            for index, level in enumerate(levels, 1):
                conn.execute("INSERT INTO domain_approval_steps(id, organization_id, booking_id, level, approver_role, status, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?) ON CONFLICT(organization_id, booking_id, level) DO UPDATE SET approver_role = excluded.approver_role, status = 'pending'", (new_id("approvalstep"), org, booking_id, index, _text(level, "role", "corporate_admin", 50), now_iso()))
            return {"ok": True, "items": [_serialize(row) for row in conn.execute("SELECT * FROM domain_approval_steps WHERE organization_id = ? AND booking_id = ? ORDER BY level", (org, booking_id)).fetchall()]}
    decision = re.match(r"^/api/approval-steps/([^/]+)/decision$", route)
    if decision and method == "POST":
        _staff(user); status = _text(payload, "status", maximum=20); 
        if status not in {"approved", "rejected"}: raise DomainError(400, "Approval status must be approved or rejected", "validation_error")
        row = conn.execute("SELECT * FROM domain_approval_steps WHERE id = ? AND organization_id = ?", (decision.group(1), org)).fetchone();
        if not row: raise DomainError(404, "Approval step not found", "not_found")
        conn.execute("UPDATE domain_approval_steps SET status = ?, comment = ?, decided_by = ?, decided_at = ? WHERE id = ?", (status, _text(payload, "comment", maximum=500), user["id"], now_iso(), row["id"]))
        if status == "rejected": conn.execute("UPDATE domain_bookings SET status = 'disputed', updated_at = ? WHERE id = ?", (now_iso(), row["booking_id"]))
        elif not conn.execute("SELECT 1 FROM domain_approval_steps WHERE organization_id = ? AND booking_id = ? AND status <> 'approved'", (org, row["booking_id"])).fetchone(): conn.execute("UPDATE domain_bookings SET status = 'approved', updated_at = ? WHERE id = ?", (now_iso(), row["booking_id"]))
        return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_approval_steps WHERE id = ?", (row["id"],)).fetchone())}
    invoice_verify = re.match(r"^/api/invoices/([^/]+)/verify$", route)
    if invoice_verify and method == "POST":
        _staff(user); invoice_id = invoice_verify.group(1); row = conn.execute("SELECT * FROM domain_invoices WHERE id = ? AND organization_id = ?", (invoice_id, org)).fetchone();
        if not row: raise DomainError(404, "Invoice not found", "not_found")
        record = _version(conn, user, "invoice", invoice_id, {"verification": payload.get("verification", "accepted"), "comment": _text(payload, "comment", maximum=500)}, "invoice_verified"); return {"ok": True, "item": {"invoice_id": invoice_id, "status": "verified", "verification": payload.get("verification", "accepted")}, "version": record}
    if route == "/api/sla" and method in {"GET", "POST"}:
        _staff(user)
        if method == "GET":
            rows = conn.execute("SELECT * FROM domain_sla_events WHERE organization_id = ? ORDER BY created_at DESC", (org,)).fetchall(); return {"ok": True, "items": [_serialize(row) for row in rows]}
        event_id = new_id("sla"); conn.execute("INSERT INTO domain_sla_events(id, organization_id, entity_type, entity_id, metric, due_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (event_id, org, _text(payload, "entity_type", maximum=40), _text(payload, "entity_id", maximum=160), _text(payload, "metric", maximum=80), _text(payload, "due_at", maximum=40) or now_iso(), now_iso())); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_sla_events WHERE id = ?", (event_id,)).fetchone())}
    sla_resolve = re.match(r"^/api/sla/([^/]+)/resolve$", route)
    if sla_resolve and method == "POST":
        _staff(user); row = conn.execute("SELECT * FROM domain_sla_events WHERE id = ? AND organization_id = ?", (sla_resolve.group(1), org)).fetchone();
        if not row: raise DomainError(404, "SLA event not found", "not_found")
        conn.execute("UPDATE domain_sla_events SET status = 'resolved', resolved_at = ? WHERE id = ?", (now_iso(), row["id"])); return {"ok": True, "status": "resolved"}
    if route == "/api/reports/supplier-scorecards" and method == "GET":
        _staff(user); rows = conn.execute("SELECT supplier_id, COUNT(*) AS bills, COALESCE(SUM(total_paise),0) AS total_paise FROM domain_supplier_bills WHERE organization_id = ? GROUP BY supplier_id", (org,)).fetchall(); return {"ok": True, "items": [_serialize(row) for row in rows]}
    if route == "/api/integrations/hrms/sync" and method == "POST":
        _staff(user); return {"ok": True, "provider": "mock_hrms", "status": "queued", "reference": f"mock_hrms_{uuid.uuid4().hex[:12]}", "imported": int(payload.get("employee_count") or 0)}
    return None


def _driver_features(conn, user, route, method, payload, ip):
    if route == "/api/drivers/preferences":
        org = user["organization_id"]
        if method == "GET":
            row = conn.execute("SELECT * FROM domain_driver_preferences WHERE user_id = ?", (user["id"],)).fetchone(); return {"ok": True, "item": _serialize(row, ("quiet_hours_json",)) if row else {"user_id": user["id"], "language": "en-IN", "quiet_hours": {}, "low_bandwidth": True}}
        if method == "PATCH":
            language = _text(payload, "language", "en-IN", 20); quiet = _json_body(payload, "quiet_hours", {}); conn.execute("INSERT INTO domain_driver_preferences(user_id, organization_id, language, quiet_hours_json, low_bandwidth, updated_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET language = excluded.language, quiet_hours_json = excluded.quiet_hours_json, low_bandwidth = excluded.low_bandwidth, updated_at = excluded.updated_at", (user["id"], org, language, json.dumps(quiet), 1 if payload.get("low_bandwidth", True) else 0, now_iso())); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_driver_preferences WHERE user_id = ?", (user["id"],)).fetchone(), ("quiet_hours_json",))}
    if route == "/api/devices" and method in {"GET", "POST"}:
        org = user["organization_id"]
        if method == "GET": rows = conn.execute("SELECT * FROM domain_device_bindings WHERE user_id = ? ORDER BY last_seen_at DESC", (user["id"],)).fetchall(); return {"ok": True, "items": [_serialize(row) for row in rows]}
        device_id = _text(payload, "device_id", maximum=160)
        if not device_id: raise DomainError(400, "device_id is required", "validation_error")
        count = conn.execute("SELECT COUNT(*) AS n FROM domain_device_bindings WHERE user_id = ? AND status = 'active'", (user["id"],)).fetchone()["n"]
        existing = conn.execute("SELECT id FROM domain_device_bindings WHERE user_id = ? AND device_id = ?", (user["id"], device_id)).fetchone()
        if not existing and count >= int(payload.get("max_devices") or 3): raise DomainError(409, "Maximum active device limit reached", "device_limit")
        push_token = _text(payload, "push_token", maximum=512)
        device_pk = existing["id"] if existing else new_id("device"); conn.execute("INSERT INTO domain_device_bindings(id, organization_id, user_id, device_id, platform, status, last_seen_at, push_token, created_at) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?) ON CONFLICT(user_id, device_id) DO UPDATE SET last_seen_at = excluded.last_seen_at, status = 'active', platform = excluded.platform, push_token = excluded.push_token", (device_pk, org, user["id"], device_id, _text(payload, "platform", "web", 30), now_iso(), push_token, now_iso())); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_device_bindings WHERE id = ?", (device_pk,)).fetchone())}
    device_revoke = re.match(r"^/api/devices/([^/]+)/revoke$", route)
    if device_revoke and method == "POST":
        row = conn.execute("SELECT * FROM domain_device_bindings WHERE id = ? AND user_id = ?", (device_revoke.group(1), user["id"])).fetchone();
        if not row: raise DomainError(404, "Device not found", "not_found")
        conn.execute("UPDATE domain_device_bindings SET status = 'revoked', last_seen_at = ? WHERE id = ?", (now_iso(), row["id"])); return {"ok": True, "status": "revoked"}
    if route == "/api/practice-duties" and method in {"GET", "POST"}:
        if method == "GET": rows = conn.execute("SELECT * FROM domain_practice_duties WHERE user_id = ? ORDER BY created_at DESC", (user["id"],)).fetchall(); return {"ok": True, "items": [_serialize(row, ("payload_json",)) for row in rows]}
        practice_id = new_id("practice"); conn.execute("INSERT INTO domain_practice_duties(id, organization_id, user_id, scenario, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (practice_id, user["organization_id"], user["id"], _text(payload, "scenario", "basic_execution", 60), json.dumps(payload), now_iso())); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_practice_duties WHERE id = ?", (practice_id,)).fetchone(), ("payload_json",))}
    return None


def _passenger(conn, user, route, method, payload, ip):
    org = _org(user)
    if route == "/api/passenger/access" and method == "POST":
        duty_id = _text(payload, "duty_id"); _assert_owned(conn, "domain_duties", duty_id, org); raw = secrets.token_urlsafe(24); access_id = new_id("passenger"); expires = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0).isoformat().replace("+00:00", "Z"); conn.execute("INSERT INTO domain_passenger_access(id, organization_id, duty_id, email, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (access_id, org, duty_id, _text(payload, "email", maximum=254), hashlib.sha256(raw.encode()).hexdigest(), expires, now_iso())); return {"ok": True, "item": {"id": access_id, "access_token": raw, "expires_at": expires, "url": f"/api/passenger/trips/{raw}"}}
    public_trip = re.match(r"^/api/passenger/trips/([^/]+)$", route)
    if public_trip and method == "GET":
        token_hash = hashlib.sha256(public_trip.group(1).encode()).hexdigest(); row = conn.execute("SELECT * FROM domain_passenger_access WHERE token_hash = ? AND expires_at > ?", (token_hash, now_iso())).fetchone();
        if not row: raise DomainError(404, "Passenger link is invalid or expired", "not_found")
        duty = conn.execute("SELECT * FROM domain_duties WHERE id = ?", (row["duty_id"],)).fetchone(); booking = conn.execute("SELECT * FROM domain_bookings WHERE id = ?", (duty["booking_id"],)).fetchone() if duty else None; return {"ok": True, "trip": {"duty": _serialize(duty), "booking": _serialize(booking, ("pickup_json", "dropoff_json")), "share": _serialize(row)}}
    if route == "/api/passenger/trips" and method == "GET":
        rows = conn.execute("SELECT d.*, b.booking_reference, b.passenger_name FROM domain_duties d JOIN domain_bookings b ON b.id = d.booking_id WHERE d.organization_id = ? ORDER BY d.reporting_at DESC LIMIT ?", (org, _limit(parse_qs(urlsplit(route).query)))).fetchall(); return {"ok": True, "items": [_serialize(row) for row in rows]}
    rating = re.match(r"^/api/passenger/duties/([^/]+)/rating$", route)
    if rating and method == "POST":
        duty_id = rating.group(1); _assert_owned(conn, "domain_duties", duty_id, org); score = int(payload.get("rating") or 0)
        if score < 1 or score > 5: raise DomainError(400, "Rating must be between 1 and 5", "validation_error")
        rating_id = new_id("rating"); conn.execute("INSERT INTO domain_passenger_ratings(id, organization_id, duty_id, rating, tags_json, comment, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (rating_id, org, duty_id, score, json.dumps(payload.get("tags") if isinstance(payload.get("tags"), list) else []), _text(payload, "comment", maximum=1000), now_iso())); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_passenger_ratings WHERE id = ?", (rating_id,)).fetchone(), ("tags_json",))}
    if route == "/api/passenger/bookings" and method == "POST":
        return _create_booking(conn, user, payload, ip)
    return None



def handle_verified_payment_webhook(conn, payload: dict, organization_id: str | None, ip: str) -> dict:
    """Persist a provider webhook only after the HTTP boundary verifies HMAC.

    The server owns signature verification because it has access to the raw
    request bytes and provider secret. This helper only handles replay-safe
    persistence and optional payment-link reconciliation.
    """
    event_id = _text(payload, "event_id", maximum=160) or _text(payload, "id", maximum=160)
    if not event_id:
        raise DomainError(400, "event_id is required", "validation_error")
    provider = _text(payload, "provider", "payment_provider", 40)
    if not organization_id:
        raise DomainError(400, "organization_id is required for a payment webhook", "organization_required")
    organization = conn.execute("SELECT id FROM organizations WHERE id = ?", (organization_id,)).fetchone()
    if not organization:
        raise DomainError(400, "Webhook organization is not recognized", "organization_not_found")
    existing = conn.execute("SELECT * FROM domain_webhook_events WHERE provider = ? AND external_id = ?", (provider, event_id)).fetchone()
    if existing:
        if existing["organization_id"] and existing["organization_id"] != organization_id:
            raise DomainError(409, "Webhook replay belongs to another organization", "webhook_tenant_conflict")
        return {"ok": True, "status": "duplicate", "item": _serialize(existing, ("payload_json",)), "replayed": True}
    clean_payload = {key: value for key, value in payload.items() if not str(key).startswith("_") and key not in {"signature", "webhook_signature"}}
    webhook_id = new_id("webhook")
    conn.execute("INSERT INTO domain_webhook_events(id, organization_id, provider, event_type, external_id, payload_json, signature_valid, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, 'processed', ?)", (webhook_id, organization_id, provider, _text(payload, "event_type", "payment.succeeded", 80), event_id, json.dumps(clean_payload), now_iso()))
    payment_link_id = _text(payload, "payment_link_id", maximum=160)
    if payment_link_id and _text(payload, "event_type", "payment.succeeded", 80) in {"payment.succeeded", "payment.captured"}:
        conn.execute("UPDATE domain_payment_links SET status = 'paid', paid_at = ?, provider_reference = ? WHERE id = ? AND organization_id = ?", (now_iso(), _text(payload, "provider_reference", event_id, 160), payment_link_id, organization_id))
    item = conn.execute("SELECT * FROM domain_webhook_events WHERE id = ?", (webhook_id,)).fetchone()
    return {"ok": True, "status": "processed", "item": _serialize(item, ("payload_json",)), "replayed": False}

def _communications(conn, user, route, method, payload, ip):
    org = _org(user)
    if route == "/api/updates" and method == "GET":
        _staff(user)
        duties = conn.execute("SELECT id, status, driver_id, vehicle_id, updated_at FROM domain_duties WHERE organization_id = ? ORDER BY updated_at DESC LIMIT 100", (org,)).fetchall()
        alerts = conn.execute("SELECT id, alert_type, severity, status, created_at FROM domain_alerts WHERE organization_id = ? ORDER BY created_at DESC LIMIT 100", (org,)).fetchall()
        return {"ok": True, "cursor": now_iso(), "events": [{"type": "duty.changed", **dict(row)} for row in duties] + [{"type": "alert.created", **dict(row)} for row in alerts]}
    alert_ack = re.match(r"^/api/alerts/([^/]+)/ack$", route)
    if route == "/api/alerts" and method in {"GET", "POST"}:
        if method == "GET": return {"ok": True, "items": _list(conn, "domain_alerts", org, "created_at DESC", _limit(parse_qs(urlsplit(route).query)))}
        alert_id = _alert(conn, user, _text(payload, "alert_type", "operational", 60), _text(payload, "severity", "info", 20), _text(payload, "entity_type", maximum=30), _text(payload, "entity_id", maximum=160), payload, ip); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_alerts WHERE id = ?", (alert_id,)).fetchone(), ("payload_json",))}
    if alert_ack and method == "POST":
        row = conn.execute("SELECT * FROM domain_alerts WHERE id = ? AND organization_id = ?", (alert_ack.group(1), org)).fetchone();
        if not row: raise DomainError(404, "Alert not found", "not_found")
        conn.execute("UPDATE domain_alerts SET status = 'acknowledged', acknowledged_by = ?, acknowledged_at = ? WHERE id = ?", (user["id"], now_iso(), row["id"])); return {"ok": True, "status": "acknowledged"}
    if route == "/api/geofences" and method in {"GET", "POST"}:
        if method == "GET": return {"ok": True, "items": _list(conn, "domain_geofences", org, "created_at DESC", _limit(parse_qs(urlsplit(route).query)))}
        fence_id = new_id("geofence"); conn.execute("INSERT INTO domain_geofences(id, organization_id, name, latitude, longitude, radius_m, event_types_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (fence_id, org, _text(payload, "name", maximum=120), float(payload.get("latitude") or 0), float(payload.get("longitude") or 0), float(payload.get("radius_m") or 500), json.dumps(payload.get("event_types") if isinstance(payload.get("event_types"), list) else []), now_iso())); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_geofences WHERE id = ?", (fence_id,)).fetchone(), ("event_types_json",))}
    event_match = re.match(r"^/api/notifications/([^/]+)/events$", route)
    if event_match and method == "POST":
        event_id = new_id("notification_event"); conn.execute("INSERT INTO domain_notification_events(id, organization_id, notification_id, event_type, provider_reference, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (event_id, org, event_match.group(1), _text(payload, "event_type", "delivered", 40), _text(payload, "provider_reference", maximum=160), json.dumps(payload), now_iso())); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_notification_events WHERE id = ?", (event_id,)).fetchone(), ("payload_json",))}
    webhook = route == "/api/webhooks/payments" and method == "POST"
    if webhook:
        if not payload.get("_signature_verified"):
            raise DomainError(401, "Webhook signature verification required", "invalid_webhook_signature")
        return handle_verified_payment_webhook(conn, payload, org, ip)
    return None


def _network(conn, user, route, method, payload, ip):
    if not route.startswith("/api/network"):
        return None
    org = _org(user); _staff(user)
    if route == "/api/network/edges" and method in {"GET", "POST"}:
        if method == "GET": return {"ok": True, "items": _list(conn, "domain_network_edges", org, "created_at DESC", _limit(parse_qs(urlsplit(route).query)))}
        edge_id = new_id("edge"); conn.execute("INSERT INTO domain_network_edges(id, organization_id, partner_organization_id, partner_name, status, cities_json, created_at) VALUES (?, ?, ?, ?, 'invited', ?, ?)", (edge_id, org, payload.get("partner_organization_id"), _text(payload, "partner_name", maximum=160), json.dumps(payload.get("cities") if isinstance(payload.get("cities"), list) else []), now_iso())); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_network_edges WHERE id = ?", (edge_id,)).fetchone(), ("cities_json",))}
    if route == "/api/network/edges/accept" and method == "POST":
        edge_id = _text(payload, "edge_id"); row = conn.execute("SELECT * FROM domain_network_edges WHERE id = ? AND organization_id = ?", (edge_id, org)).fetchone();
        if not row: raise DomainError(404, "Network edge not found", "not_found")
        conn.execute("UPDATE domain_network_edges SET status = 'active', accepted_at = ? WHERE id = ?", (now_iso(), edge_id)); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_network_edges WHERE id = ?", (edge_id,)).fetchone(), ("cities_json",))}
    offer_match = re.match(r"^/api/network/offers(?:/([^/]+)/bids)?$", route)
    if offer_match and method in {"GET", "POST"}:
        if offer_match.group(1):
            offer_id = offer_match.group(1)
            if method == "GET": rows = conn.execute("SELECT * FROM domain_network_bids WHERE organization_id = ? AND offer_id = ? ORDER BY created_at DESC", (org, offer_id)).fetchall(); return {"ok": True, "items": [_serialize(row) for row in rows]}
            bid_id = new_id("bid"); conn.execute("INSERT INTO domain_network_bids(id, organization_id, offer_id, bidder_organization_id, amount_paise, comment, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (bid_id, org, offer_id, payload.get("bidder_organization_id"), int(payload.get("amount_paise") or 0), _text(payload, "comment", maximum=500), now_iso())); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_network_bids WHERE id = ?", (bid_id,)).fetchone())}
        if method == "GET": return {"ok": True, "items": _list(conn, "domain_network_offers", org, "created_at DESC", _limit(parse_qs(urlsplit(route).query)))}
        offer_id = new_id("offer"); conn.execute("INSERT INTO domain_network_offers(id, organization_id, edge_id, duty_id, amount_paise, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (offer_id, org, payload.get("edge_id"), payload.get("duty_id"), int(payload.get("amount_paise") or 0), payload.get("expires_at"), now_iso())); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_network_offers WHERE id = ?", (offer_id,)).fetchone())}
    if route == "/api/network/settlements" and method in {"GET", "POST"}:
        if method == "GET": return {"ok": True, "items": _list(conn, "domain_settlements", org, "created_at DESC", _limit(parse_qs(urlsplit(route).query)))}
        settlement_id = new_id("settlement"); gross = int(payload.get("gross_paise") or 0); deductions = int(payload.get("deductions_paise") or 0); conn.execute("INSERT INTO domain_settlements(id, organization_id, partner_organization_id, period_start, period_end, gross_paise, deductions_paise, net_paise, evidence_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (settlement_id, org, payload.get("partner_organization_id"), payload.get("period_start"), payload.get("period_end"), gross, deductions, gross - deductions, json.dumps(_json_body(payload, "evidence", {})), now_iso())); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_settlements WHERE id = ?", (settlement_id,)).fetchone(), ("evidence_json",))}
    return None


def _reports(conn, user, route, method, payload, ip):
    org = _org(user)
    if route == "/api/reports/export" and method == "POST":
        _staff(user); report_type = _text(payload, "report_type", "operations", 60); output = io.StringIO(); writer = csv.writer(output); writer.writerow(["Axiom Fleet", report_type, "generated_at", now_iso()]);
        if report_type in {"bookings", "operations"}:
            writer.writerow(["booking_reference", "status", "passenger", "scheduled_at"])
            for row in conn.execute("SELECT booking_reference,status,passenger_name,scheduled_at FROM domain_bookings WHERE organization_id = ? ORDER BY scheduled_at", (org,)): writer.writerow(list(row))
        elif report_type == "invoices":
            writer.writerow(["invoice_number", "status", "total_paise"])
            for row in conn.execute("SELECT invoice_number,status,total_paise FROM domain_invoices WHERE organization_id = ?", (org,)): writer.writerow(list(row))
        export_id = new_id("export"); expires = (datetime.now(timezone.utc) + timedelta(days=7)).replace(microsecond=0).isoformat().replace("+00:00", "Z"); token = secrets.token_urlsafe(20); conn.execute("INSERT INTO domain_report_exports(id, organization_id, report_type, filters_json, download_token, content, expires_at, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (export_id, org, report_type, json.dumps(_json_body(payload, "filters", {})), token, output.getvalue(), expires, user["id"], now_iso())); return {"ok": True, "item": {"id": export_id, "status": "ready", "download_token": token, "expires_at": expires, "download_url": f"/api/reports/exports/{export_id}"}}
    export_match = re.match(r"^/api/reports/exports/([^/]+)$", route)
    if export_match and method == "GET":
        row = conn.execute("SELECT * FROM domain_report_exports WHERE id = ? AND organization_id = ?", (export_match.group(1), org)).fetchone();
        if not row: raise DomainError(404, "Export not found", "not_found")
        if row["expires_at"] <= now_iso(): raise DomainError(410, "Export has expired", "export_expired")
        return {"ok": True, "item": {**_serialize(row), "content": row["content"]}}
    if route == "/api/reports/views" and method in {"GET", "POST"}:
        if method == "GET": return {"ok": True, "items": _list(conn, "domain_report_views", org, "created_at DESC", _limit(parse_qs(urlsplit(route).query)))}
        view_id = new_id("view"); conn.execute("INSERT INTO domain_report_views(id, organization_id, name, config_json, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)", (view_id, org, _text(payload, "name", maximum=100), json.dumps(_json_body(payload, "config", {})), user["id"], now_iso())); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_report_views WHERE id = ?", (view_id,)).fetchone(), ("config_json",))}
    if route == "/api/reports/schedules" and method in {"GET", "POST"}:
        if method == "GET": return {"ok": True, "items": _list(conn, "domain_report_schedules", org, "created_at DESC", _limit(parse_qs(urlsplit(route).query)))}
        schedule_id = new_id("schedule"); conn.execute("INSERT INTO domain_report_schedules(id, organization_id, report_type, cadence, recipients_json, filters_json, next_run_at, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (schedule_id, org, _text(payload, "report_type", "operations", 60), _text(payload, "cadence", "weekly", 30), json.dumps(payload.get("recipients") if isinstance(payload.get("recipients"), list) else []), json.dumps(_json_body(payload, "filters", {})), payload.get("next_run_at"), user["id"], now_iso())); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_report_schedules WHERE id = ?", (schedule_id,)).fetchone(), ("recipients_json", "filters_json"))}
    if route == "/api/reports/drilldown" and method == "GET":
        metric = parse_qs(urlsplit(route).query).get("metric", ["bookings"])[0]
        if metric == "invoices": rows = conn.execute("SELECT * FROM domain_invoices WHERE organization_id = ? ORDER BY created_at DESC LIMIT 500", (org,)).fetchall()
        elif metric == "expenses": rows = conn.execute("SELECT * FROM domain_expenses WHERE organization_id = ? ORDER BY created_at DESC LIMIT 500", (org,)).fetchall()
        else: rows = conn.execute("SELECT * FROM domain_bookings WHERE organization_id = ? ORDER BY created_at DESC LIMIT 500", (org,)).fetchall()
        return {"ok": True, "metric": metric, "items": [_serialize(row) for row in rows], "count": len(rows)}
    return None


def _parse_datetime(value: object, field: str = "datetime") -> datetime:
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


def _iso_dt(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _remaining_prd(conn, user, route, method, payload, ip):
    """Local contracts for the remaining operational/commercial PRD edges.

    These workflows deliberately use mock-safe records. They give the console
    stable contracts now and can move behind Supabase RPCs or job workers
    without changing the browser-facing API.
    """
    org = _org(user)
    if route == "/api/bookings/recurring" and method in {"GET", "POST"}:
        _staff(user)
        if method == "GET":
            rows = conn.execute("SELECT * FROM domain_recurring_bookings WHERE organization_id = ? ORDER BY created_at DESC", (org,)).fetchall()
            return {"ok": True, "items": [_serialize(row, ("template_json",)) for row in rows], "count": len(rows)}
        cadence = _text(payload, "cadence", "weekly", 30).lower()
        if cadence not in {"daily", "weekly", "monthly", "business_days"}:
            raise DomainError(400, "Cadence must be daily, weekly, monthly or business_days", "validation_error")
        start = _parse_datetime(payload.get("start_at"), "start_at")
        end = _parse_datetime(payload["end_at"], "end_at") if payload.get("end_at") else None
        try:
            occurrences = int(payload.get("occurrences") or 1)
        except (TypeError, ValueError) as exc:
            raise DomainError(400, "occurrences must be an integer", "validation_error") from exc
        if not 1 <= occurrences <= 365:
            raise DomainError(400, "occurrences must be between 1 and 365", "validation_error")
        template = payload.get("template") if isinstance(payload.get("template"), dict) else {key: value for key, value in payload.items() if key not in {"cadence", "start_at", "end_at", "occurrences"}}
        customer_id = _text(template, "customer_id") or None
        if customer_id:
            _assert_owned(conn, "domain_customers", customer_id, org)
        recurring_id = new_id("recurring"); now = now_iso()
        conn.execute("INSERT INTO domain_recurring_bookings(id, organization_id, customer_id, cadence, start_at, end_at, occurrences, template_json, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (recurring_id, org, customer_id, cadence, _iso_dt(start), _iso_dt(end) if end else None, occurrences, json.dumps(template), user["id"], now, now))
        generated = []
        for index in range(occurrences):
            scheduled = start
            if cadence == "daily": scheduled = start + timedelta(days=index)
            elif cadence == "weekly": scheduled = start + timedelta(days=index * 7)
            elif cadence == "monthly": scheduled = start + timedelta(days=index * 30)
            else:
                scheduled = start; business_seen = 0
                while business_seen < index:
                    scheduled += timedelta(days=1)
                    if scheduled.weekday() < 5: business_seen += 1
            if end and scheduled > end: break
            booking_payload = dict(template)
            booking_payload["scheduled_at"] = _iso_dt(scheduled)
            booking_payload["booking_reference"] = f"REC-{recurring_id[-8:].upper()}-{index + 1:03d}"
            result = _create_booking(conn, user, booking_payload, ip)
            booking = result["item"]; generated.append(booking)
            stops = booking_payload.get("stops") if isinstance(booking_payload.get("stops"), list) else []
            for stop_index, stop in enumerate(stops, 1):
                stop_data = stop if isinstance(stop, dict) else {"label": str(stop)}
                conn.execute("INSERT OR REPLACE INTO domain_booking_stops(id, organization_id, booking_id, stop_index, label, address_json, arrival_at, departure_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (new_id("stop"), org, booking["id"], stop_index, _text(stop_data, "label", f"Stop {stop_index}", 180), json.dumps(stop_data.get("address") if isinstance(stop_data.get("address"), dict) else stop_data), stop_data.get("arrival_at"), stop_data.get("departure_at"), now_iso()))
        conn.execute("UPDATE domain_recurring_bookings SET generated_count = ?, updated_at = ? WHERE id = ?", (len(generated), now_iso(), recurring_id))
        _audit_event(conn, user, "booking.recurring_created", "recurring_booking", recurring_id, ip, {"generated": len(generated), "cadence": cadence})
        row = conn.execute("SELECT * FROM domain_recurring_bookings WHERE id = ?", (recurring_id,)).fetchone()
        return {"ok": True, "item": _serialize(row, ("template_json",)), "generated": generated}
    recurring_cancel = re.match(r"^/api/bookings/recurring/([^/]+)/cancel$", route)
    if recurring_cancel and method == "POST":
        _staff(user); row = conn.execute("SELECT * FROM domain_recurring_bookings WHERE id = ? AND organization_id = ?", (recurring_cancel.group(1), org)).fetchone()
        if not row: raise DomainError(404, "Recurring booking not found", "not_found")
        conn.execute("UPDATE domain_recurring_bookings SET status = 'cancelled', updated_at = ? WHERE id = ?", (now_iso(), row["id"]))
        _audit_event(conn, user, "booking.recurring_cancelled", "recurring_booking", row["id"], ip, {})
        return {"ok": True, "status": "cancelled", "id": row["id"]}
    stops_match = re.match(r"^/api/bookings/([^/]+)/stops$", route)
    if stops_match and method in {"GET", "POST"}:
        booking = _assert_owned(conn, "domain_bookings", stops_match.group(1), org)
        if method == "GET":
            rows = conn.execute("SELECT * FROM domain_booking_stops WHERE organization_id = ? AND booking_id = ? ORDER BY stop_index", (org, booking["id"])).fetchall()
            return {"ok": True, "items": [_serialize(row, ("address_json",)) for row in rows]}
        _staff(user); stops = payload.get("stops") if isinstance(payload.get("stops"), list) else [payload]
        conn.execute("DELETE FROM domain_booking_stops WHERE organization_id = ? AND booking_id = ?", (org, booking["id"]))
        for index, stop in enumerate(stops, 1):
            data = stop if isinstance(stop, dict) else {"label": str(stop)}
            label = _text(data, "label", f"Stop {index}", 180)
            if not label: raise DomainError(400, "Each stop needs a label", "validation_error")
            conn.execute("INSERT INTO domain_booking_stops(id, organization_id, booking_id, stop_index, label, address_json, arrival_at, departure_at, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (new_id("stop"), org, booking["id"], index, label, json.dumps(data.get("address") if isinstance(data.get("address"), dict) else data), data.get("arrival_at"), data.get("departure_at"), _text(data, "status", "planned", 20), now_iso()))
        _audit_event(conn, user, "booking.stops_updated", "booking", booking["id"], ip, {"count": len(stops)})
        return {"ok": True, "items": [_serialize(row, ("address_json",)) for row in conn.execute("SELECT * FROM domain_booking_stops WHERE booking_id = ? ORDER BY stop_index", (booking["id"],)).fetchall()]}
    if route == "/api/capacity/locks" and method in {"GET", "POST"}:
        _staff(user)
        if method == "GET":
            rows = conn.execute("SELECT * FROM domain_capacity_locks WHERE organization_id = ? ORDER BY starts_at", (org,)).fetchall(); return {"ok": True, "items": [_serialize(row) for row in rows]}
        resource_type = _text(payload, "resource_type", maximum=20); resource_id = _text(payload, "resource_id", maximum=160)
        if resource_type not in {"driver", "vehicle"}: raise DomainError(400, "resource_type must be driver or vehicle", "validation_error")
        _assert_owned(conn, "domain_drivers" if resource_type == "driver" else "domain_vehicles", resource_id, org)
        starts = _parse_datetime(payload.get("starts_at"), "starts_at"); ends = _parse_datetime(payload.get("ends_at"), "ends_at")
        if ends <= starts: raise DomainError(400, "ends_at must be after starts_at", "validation_error")
        conflict = conn.execute("SELECT id FROM domain_capacity_locks WHERE organization_id = ? AND resource_type = ? AND resource_id = ? AND status = 'held' AND starts_at < ? AND ends_at > ?", (org, resource_type, resource_id, _iso_dt(ends), _iso_dt(starts))).fetchone()
        if conflict: raise DomainError(409, "Resource is already held for that time window", "capacity_conflict")
        lock_id = new_id("capacity"); conn.execute("INSERT INTO domain_capacity_locks(id, organization_id, resource_type, resource_id, booking_id, starts_at, ends_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (lock_id, org, resource_type, resource_id, payload.get("booking_id"), _iso_dt(starts), _iso_dt(ends), now_iso())); _audit_event(conn, user, "capacity.locked", resource_type, resource_id, ip, {"booking_id": payload.get("booking_id")}); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_capacity_locks WHERE id = ?", (lock_id,)).fetchone())}
    capacity_release = re.match(r"^/api/capacity/locks/([^/]+)/release$", route)
    if capacity_release and method == "POST":
        _staff(user); row = conn.execute("SELECT * FROM domain_capacity_locks WHERE id = ? AND organization_id = ?", (capacity_release.group(1), org)).fetchone()
        if not row: raise DomainError(404, "Capacity lock not found", "not_found")
        conn.execute("UPDATE domain_capacity_locks SET status = 'released', released_at = ? WHERE id = ?", (now_iso(), row["id"])); return {"ok": True, "status": "released"}
    if route == "/api/billing-notes" and method in {"GET", "POST"}:
        _staff(user)
        if method == "GET": rows = conn.execute("SELECT * FROM domain_billing_notes WHERE organization_id = ? ORDER BY created_at DESC", (org,)).fetchall(); return {"ok": True, "items": [_serialize(row) for row in rows]}
        note_type = _text(payload, "note_type", maximum=20).lower()
        if note_type not in {"proforma", "credit", "debit"}: raise DomainError(400, "note_type must be proforma, credit or debit", "validation_error")
        note_id = new_id("note"); reference = _text(payload, "reference", f"{note_type.upper()}-{note_id[-8:].upper()}", 80); amount = int(payload.get("amount_paise") or 0); tax = int(payload.get("tax_paise") or 0)
        conn.execute("INSERT INTO domain_billing_notes(id, organization_id, note_type, invoice_id, customer_id, reference, amount_paise, tax_paise, status, reason, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)", (note_id, org, note_type, payload.get("invoice_id"), payload.get("customer_id"), reference, amount, tax, _text(payload, "reason", maximum=500), user["id"], now_iso())); _audit_event(conn, user, f"billing.{note_type}_created", "billing_note", note_id, ip, {}); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_billing_notes WHERE id = ?", (note_id,)).fetchone())}
    if route == "/api/payment-links" and method in {"GET", "POST"}:
        _staff(user)
        if method == "GET": rows = conn.execute("SELECT * FROM domain_payment_links WHERE organization_id = ? ORDER BY created_at DESC", (org,)).fetchall(); return {"ok": True, "items": [_serialize(row) for row in rows]}
        raw = secrets.token_urlsafe(24); link_id = new_id("plink"); short_code = raw[:10].upper(); expires = _iso_dt(datetime.now(timezone.utc) + timedelta(days=int(payload.get("expires_days") or 7))); conn.execute("INSERT INTO domain_payment_links(id, organization_id, invoice_id, amount_paise, token_hash, short_code, expires_at, provider_reference, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (link_id, org, payload.get("invoice_id"), int(payload.get("amount_paise") or 0), hashlib.sha256(raw.encode()).hexdigest(), short_code, expires, f"mock_link_{link_id[-8:]}", user["id"], now_iso())); return {"ok": True, "item": {**_serialize(conn.execute("SELECT * FROM domain_payment_links WHERE id = ?", (link_id,)).fetchone()), "url": f"/pay/{short_code}", "token": raw}}
    payment_capture = re.match(r"^/api/payment-links/([^/]+)/capture$", route)
    if payment_capture and method == "POST":
        _staff(user); row = conn.execute("SELECT * FROM domain_payment_links WHERE id = ? AND organization_id = ?", (payment_capture.group(1), org)).fetchone()
        if not row: raise DomainError(404, "Payment link not found", "not_found")
        conn.execute("UPDATE domain_payment_links SET status = 'paid', paid_at = ?, provider_reference = ? WHERE id = ?", (now_iso(), f"mock_payment_{row['id'][-8:]}", row["id"])); return {"ok": True, "status": "paid", "reference": f"mock_payment_{row['id'][-8:]}"}
    if route == "/api/jobs" and method in {"GET", "POST"}:
        _staff(user)
        if method == "GET": rows = conn.execute("SELECT * FROM domain_jobs WHERE organization_id = ? ORDER BY created_at DESC LIMIT 100", (org,)).fetchall(); return {"ok": True, "items": [_serialize(row, ("payload_json", "result_json",)) for row in rows]}
        job_id = new_id("job"); conn.execute("INSERT INTO domain_jobs(id, organization_id, job_type, payload_json, available_at, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (job_id, org, _text(payload, "job_type", maximum=60), json.dumps(payload.get("payload") if isinstance(payload.get("payload"), dict) else {}), _text(payload, "available_at", maximum=40) or now_iso(), user["id"], now_iso())); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_jobs WHERE id = ?", (job_id,)).fetchone(), ("payload_json", "result_json"))}
    job_run = re.match(r"^/api/jobs/([^/]+)/run$", route)
    if job_run and method == "POST":
        _staff(user); row = conn.execute("SELECT * FROM domain_jobs WHERE id = ? AND organization_id = ?", (job_run.group(1), org)).fetchone()
        if not row: raise DomainError(404, "Job not found", "not_found")
        conn.execute("UPDATE domain_jobs SET status = 'running', attempts = attempts + 1, started_at = ? WHERE id = ?", (now_iso(), row["id"]))
        result = {"mode": "mock_worker", "job_type": row["job_type"], "processed_at": now_iso()}
        conn.execute("UPDATE domain_jobs SET status = 'completed', result_json = ?, completed_at = ? WHERE id = ?", (json.dumps(result), now_iso(), row["id"]))
        return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_jobs WHERE id = ?", (row["id"],)).fetchone(), ("payload_json", "result_json"))}
    if route in {"/api/security/2fa", "/api/security/2fa/setup", "/api/security/2fa/verify", "/api/security/2fa/disable"}:
        if route == "/api/security/2fa" and method == "GET":
            row = conn.execute("SELECT factor_type, status, created_at, verified_at, last_used_at FROM domain_auth_factors WHERE user_id = ?", (user["id"],)).fetchone(); return {"ok": True, "enabled": bool(row and row["status"] == "enabled"), "factor": _serialize(row) if row else None}
        if route == "/api/security/2fa/setup" and method == "POST":
            secret = secrets.token_urlsafe(18); recovery = [secrets.token_hex(4).upper() for _ in range(8)]; conn.execute("INSERT INTO domain_auth_factors(user_id, organization_id, secret_hash, status, recovery_codes_json, created_at) VALUES (?, ?, ?, 'pending', ?, ?) ON CONFLICT(user_id) DO UPDATE SET secret_hash = excluded.secret_hash, status = 'pending', recovery_codes_json = excluded.recovery_codes_json, created_at = excluded.created_at", (user["id"], org, hashlib.sha256(secret.encode()).hexdigest(), json.dumps(recovery), now_iso())); return {"ok": True, "factor_type": "totp", "otpauth_url": f"otpauth://totp/AxiomFleet:{user['email']}?secret={secret}&issuer=AxiomFleet", "mock_verification_code": "246810", "recovery_codes": recovery}
        if route == "/api/security/2fa/verify" and method == "POST":
            factor = conn.execute("SELECT * FROM domain_auth_factors WHERE user_id = ?", (user["id"],)).fetchone()
            if not factor: raise DomainError(400, "Set up two-factor authentication first", "factor_missing")
            if _text(payload, "code", maximum=12) not in {"246810", "000000"}: raise DomainError(400, "The authenticator code is invalid", "factor_invalid")
            conn.execute("UPDATE domain_auth_factors SET status = 'enabled', verified_at = ? WHERE user_id = ?", (now_iso(), user["id"])); conn.execute("INSERT INTO domain_security_events(id, organization_id, user_id, event_type, severity, metadata_json, created_at) VALUES (?, ?, ?, '2fa.enabled', 'info', ?, ?)", (new_id("security"), org, user["id"], json.dumps({}), now_iso())); return {"ok": True, "enabled": True}
        if route == "/api/security/2fa/disable" and method == "POST":
            conn.execute("UPDATE domain_auth_factors SET status = 'disabled' WHERE user_id = ?", (user["id"],)); return {"ok": True, "enabled": False}
    if route == "/api/security/api-keys" and method in {"GET", "POST"}:
        _staff(user)
        if method == "GET": rows = conn.execute("SELECT id, name, key_prefix, scopes_json, status, last_used_at, created_by, created_at, revoked_at FROM domain_api_keys WHERE organization_id = ? ORDER BY created_at DESC", (org,)).fetchall(); return {"ok": True, "items": [_serialize(row, ("scopes_json",)) for row in rows]}
        raw = "af_live_" + secrets.token_urlsafe(30); key_id = new_id("apikey"); conn.execute("INSERT INTO domain_api_keys(id, organization_id, name, key_hash, key_prefix, scopes_json, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (key_id, org, _text(payload, "name", "API key", 80), hashlib.sha256(raw.encode()).hexdigest(), raw[:12], json.dumps(payload.get("scopes") if isinstance(payload.get("scopes"), list) else ["bookings:read"]), user["id"], now_iso())); return {"ok": True, "item": {"id": key_id, "name": _text(payload, "name", "API key", 80), "key": raw, "key_prefix": raw[:12], "status": "active"}}
    api_key_revoke = re.match(r"^/api/security/api-keys/([^/]+)/revoke$", route)
    if api_key_revoke and method == "POST":
        _staff(user); row = conn.execute("SELECT id FROM domain_api_keys WHERE id = ? AND organization_id = ?", (api_key_revoke.group(1), org)).fetchone()
        if not row: raise DomainError(404, "API key not found", "not_found")
        conn.execute("UPDATE domain_api_keys SET status = 'revoked', revoked_at = ? WHERE id = ?", (now_iso(), row["id"])); return {"ok": True, "status": "revoked"}
    if route == "/api/security/sessions" and method == "GET":
        rows = conn.execute("SELECT token_hash, created_at, expires_at, user_agent, ip_address FROM sessions WHERE user_id = ? ORDER BY created_at DESC", (user["id"],)).fetchall(); return {"ok": True, "items": [{"id": row["token_hash"][:12], "created_at": row["created_at"], "expires_at": row["expires_at"], "user_agent": row["user_agent"], "ip_address": row["ip_address"]} for row in rows]}
    session_revoke = re.match(r"^/api/security/sessions/([^/]+)/revoke$", route)
    if session_revoke and method == "POST":
        prefix = session_revoke.group(1); rows = conn.execute("SELECT token_hash FROM sessions WHERE user_id = ? AND token_hash LIKE ?", (user["id"], prefix + "%")).fetchall();
        for row in rows: conn.execute("DELETE FROM sessions WHERE token_hash = ?", (row["token_hash"],))
        return {"ok": True, "revoked": len(rows)}
    if route == "/api/security/events" and method == "GET":
        rows = conn.execute("SELECT * FROM domain_security_events WHERE organization_id = ? OR user_id = ? ORDER BY created_at DESC LIMIT 100", (org, user["id"])).fetchall(); return {"ok": True, "items": [_serialize(row, ("metadata_json",)) for row in rows]}
    if route == "/api/privacy/requests" and method == "GET":
        rows = conn.execute("SELECT * FROM domain_privacy_requests WHERE organization_id = ? ORDER BY created_at DESC", (org,)).fetchall(); return {"ok": True, "items": [_serialize(row) for row in rows]}
    privacy_fulfill = re.match(r"^/api/privacy/requests/([^/]+)/fulfill$", route)
    if privacy_fulfill and method == "POST":
        _staff(user); row = conn.execute("SELECT * FROM domain_privacy_requests WHERE id = ? AND organization_id = ?", (privacy_fulfill.group(1), org)).fetchone()
        if not row: raise DomainError(404, "Privacy request not found", "not_found")
        conn.execute("UPDATE domain_privacy_requests SET status = 'completed', completed_at = ? WHERE id = ?", (now_iso(), row["id"])); _audit_event(conn, user, "privacy.fulfilled", "privacy_request", row["id"], ip, {"request_type": row["request_type"]}); return {"ok": True, "status": "completed"}
    employee_status = re.match(r"^/api/employees/([^/]+)/(deactivate|reactivate)$", route)
    if employee_status and method == "POST":
        _staff(user); status = "inactive" if employee_status.group(2) == "deactivate" else "active"; row = conn.execute("SELECT * FROM domain_employees WHERE id = ? AND organization_id = ?", (employee_status.group(1), org)).fetchone()
        if not row: raise DomainError(404, "Employee not found", "not_found")
        conn.execute("UPDATE domain_employees SET status = ?, updated_at = ? WHERE id = ?", (status, now_iso(), row["id"])); return {"ok": True, "status": status, "item": _serialize(conn.execute("SELECT * FROM domain_employees WHERE id = ?", (row["id"],)).fetchone())}
    return None


def _privacy_and_admin(conn, user, route, method, payload, ip):
    org = _org(user)
    if route == "/api/privacy/consents" and method in {"GET", "POST"}:
        if method == "GET": rows = conn.execute("SELECT * FROM domain_consents WHERE organization_id = ? ORDER BY captured_at DESC", (org,)).fetchall(); return {"ok": True, "items": [_serialize(row, ("evidence_json",)) for row in rows]}
        consent_id = new_id("consent"); conn.execute("INSERT INTO domain_consents(id, organization_id, subject_id, purpose, policy_version, status, evidence_json, captured_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (consent_id, org, _text(payload, "subject_id", maximum=160), _text(payload, "purpose", maximum=100), _text(payload, "policy_version", "v1", 40), _text(payload, "status", "granted", 20), json.dumps(_json_body(payload, "evidence", {})), now_iso())); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_consents WHERE id = ?", (consent_id,)).fetchone(), ("evidence_json",))}
    if route == "/api/privacy/retention" and method in {"GET", "POST"}:
        if method == "GET": return {"ok": True, "items": _list(conn, "domain_retention_locks", org, "created_at DESC", _limit(parse_qs(urlsplit(route).query)))}
        lock_id = new_id("retention"); conn.execute("INSERT INTO domain_retention_locks(id, organization_id, entity_type, entity_id, reason, expires_at, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (lock_id, org, _text(payload, "entity_type", maximum=40), _text(payload, "entity_id", maximum=160), _text(payload, "reason", maximum=500), payload.get("expires_at"), user["id"], now_iso())); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_retention_locks WHERE id = ?", (lock_id,)).fetchone())}
    if route == "/api/admin/clients" and method == "GET":
        _staff(user); rows = conn.execute("SELECT o.id,o.kind,o.name,o.city,o.created_at,COUNT(u.id) AS users FROM organizations o LEFT JOIN users u ON u.organization_id=o.id GROUP BY o.id ORDER BY o.created_at DESC").fetchall(); return {"ok": True, "items": [_serialize(row) for row in rows]}
    if route == "/api/admin/kpis" and method == "GET":
        _staff(user); return {"ok": True, "kpis": {"organizations": conn.execute("SELECT COUNT(*) n FROM organizations").fetchone()["n"], "users": conn.execute("SELECT COUNT(*) n FROM users").fetchone()["n"], "bookings": conn.execute("SELECT COUNT(*) n FROM domain_bookings").fetchone()["n"], "duties": conn.execute("SELECT COUNT(*) n FROM domain_duties").fetchone()["n"], "open_alerts": conn.execute("SELECT COUNT(*) n FROM domain_alerts WHERE status='open'").fetchone()["n"]}}
    if route == "/api/admin/feature-flags" and method in {"GET", "POST"}:
        if method == "GET": return {"ok": True, "flags": {"offline_driver_shell": True, "mock_providers": True, "passenger_links": True, "network_settlements": True}}
        _staff(user); return {"ok": True, "flag": _text(payload, "key", maximum=80), "enabled": bool(payload.get("enabled", True)), "updated_at": now_iso()}
    return None


def handle_extended(conn, user, method: str, raw_route: str, payload: dict, ip: str):
    route, _query = _parse(raw_route)
    # Dispatch only to the feature family that owns the route. This is
    # important for organization-free driver accounts accepting invitations:
    # unrelated tenant handlers must not reject the request before the core
    # invitation service sees it.
    if route in {"/api/onboarding", "/api/onboarding/provision", "/api/setup"}:
        return _onboarding(conn, user, method, route, payload, ip)
    if (route == "/api/bookings/recurring" or route.startswith("/api/bookings/recurring/") or route.startswith("/api/bookings/") and route.endswith("/stops")
            or route == "/api/capacity/locks" or route.startswith("/api/capacity/locks/")
            or route == "/api/billing-notes" or route == "/api/payment-links" or route.startswith("/api/payment-links/")
            or route == "/api/jobs" or route.startswith("/api/jobs/") or route.startswith("/api/security/")
            or route == "/api/privacy/requests" or route.startswith("/api/privacy/requests/")
            or route.startswith("/api/employees/") and method != "GET"):
        result = _remaining_prd(conn, user, route, method, payload, ip)
        if result is not None:
            return result
    if route == "/api/duplicates/check" and method == "POST":
        return _duplicate_check(conn, user, payload, ip)
    if method == "PATCH" and route != "/api/drivers/preferences" and re.match(r"^/api/(customers|drivers|vehicles|suppliers|manufacturers)/[^/]+$", route):
        return _soft_update(conn, user, route, method, payload, ip)
    if route.startswith("/api/price-books/") and (route.endswith("/versions") or route.endswith("/approve")):
        return _price_book_versions(conn, user, route, method, payload, ip)
    if route.startswith("/api/duties/") and re.search(r"/(reassign|no-show|force-close|navigation|call|sos|trip-share|reconcile)$", route):
        return _duty_exception(conn, user, route, method, payload, ip)
    if (route in {"/api/receipts/allocate", "/api/supplier-bills", "/api/costs", "/api/vehicle-costs", "/api/supplier-payouts", "/api/driver-payouts", "/api/financial-actions", "/api/reconciliations", "/api/tax/calculate", "/api/reports/vehicle-pnl"} or re.match(r"^/api/vehicles/[^/]+/lifecycle$", route)
            or route.startswith("/api/invoices/") and route.endswith("/e-invoice/cancel")
            or route.startswith("/api/financial-actions/")):
        return _billing_and_costs(conn, user, route, method, payload, ip)
    if route.startswith("/api/bookings/") and route.endswith("/approval-chain") or route.startswith("/api/approval-steps/") or route.startswith("/api/invoices/") and route.endswith("/verify") or route == "/api/reports/supplier-scorecards" or route == "/api/integrations/hrms/sync" or route == "/api/sla" or route.startswith("/api/sla/"):
        return _corporate(conn, user, route, method, payload, ip)
    if route in {"/api/drivers/preferences", "/api/devices", "/api/practice-duties"} or route.startswith("/api/devices/"):
        return _driver_features(conn, user, route, method, payload, ip)
    if route == "/api/passenger/access" or route == "/api/passenger/trips" or route.startswith("/api/passenger/trips/") or route.startswith("/api/passenger/duties/") or route == "/api/passenger/bookings":
        return _passenger(conn, user, route, method, payload, ip)
    if route == "/api/updates" or route == "/api/alerts" or route.startswith("/api/alerts/") or route == "/api/geofences" or route.startswith("/api/notifications/") and route.endswith("/events") or route == "/api/webhooks/payments":
        return _communications(conn, user, route, method, payload, ip)
    if route.startswith("/api/network/"):
        return _network(conn, user, route, method, payload, ip)
    if route == "/api/reports/export" or route.startswith("/api/reports/exports/") or route in {"/api/reports/views", "/api/reports/schedules", "/api/reports/drilldown"}:
        return _reports(conn, user, route, method, payload, ip)
    if route in {"/api/privacy/consents", "/api/privacy/retention", "/api/admin/clients", "/api/admin/kpis", "/api/admin/feature-flags"}:
        return _privacy_and_admin(conn, user, route, method, payload, ip)
    return None
