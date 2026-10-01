"""Enterprise administration, booking-control and duty-execution parity slice.

The slice is additive to the existing corporate, operations and domain modules.
It provides first-class administrative records, passenger/token boundaries,
resource-control rules and evidence-safe execution helpers for the local
fallback. Supabase mirrors these records and transactions in the companion
migration and Edge function.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

from backend_domain import DomainError, _assert_owned, _audit, _org, _serialize, _text, new_id, now_iso
from backend_operations_parity import _close_duty


COLLECTIONS = {
    "groups": ("enterprise_groups", ("metadata_json",)),
    "companies": ("enterprise_companies", ("billing_json",)),
    "billing-profiles": ("enterprise_billing_profiles", ("metadata_json",)),
    "bank-accounts": ("enterprise_bank_accounts", ("metadata_json",)),
    "tax-entities": ("enterprise_tax_entities", ("metadata_json",)),
    "billing-items": ("enterprise_billing_items", ("rules_json",)),
    "custom-fields": ("enterprise_custom_fields", ("options_json",)),
    "plans": ("enterprise_plan_subscriptions", ("entitlements_json",)),
}


def initialize_enterprise_controls_schema(conn) -> None:
    # Older local databases predate booking provenance; extend them in place.
    booking_columns = {row["name"] for row in conn.execute("PRAGMA table_info(domain_bookings)").fetchall()}
    if "source" not in booking_columns:
        conn.execute("ALTER TABLE domain_bookings ADD COLUMN source TEXT NOT NULL DEFAULT 'web'")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS enterprise_groups (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, group_type TEXT NOT NULL,
            code TEXT NOT NULL, name TEXT NOT NULL, parent_id TEXT, status TEXT NOT NULL DEFAULT 'active',
            metadata_json TEXT NOT NULL DEFAULT '{}', created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(organization_id, group_type, code)
        );
        CREATE TABLE IF NOT EXISTS enterprise_group_members (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, group_id TEXT NOT NULL,
            entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(group_id, entity_type, entity_id)
        );
        CREATE TABLE IF NOT EXISTS enterprise_companies (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, code TEXT NOT NULL, legal_name TEXT NOT NULL,
            trading_name TEXT NOT NULL DEFAULT '', gstin TEXT NOT NULL DEFAULT '', pan TEXT NOT NULL DEFAULT '',
            is_sister_company INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active',
            billing_json TEXT NOT NULL DEFAULT '{}', created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(organization_id, code)
        );
        CREATE TABLE IF NOT EXISTS enterprise_billing_profiles (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, company_id TEXT, tax_entity_id TEXT, bank_account_id TEXT,
            invoice_series TEXT NOT NULL DEFAULT '', currency TEXT NOT NULL DEFAULT 'INR', bill_to_mode TEXT NOT NULL DEFAULT 'company',
            status TEXT NOT NULL DEFAULT 'active', metadata_json TEXT NOT NULL DEFAULT '{}', created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(organization_id, company_id)
        );
        CREATE TABLE IF NOT EXISTS enterprise_bank_accounts (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, company_id TEXT, account_name TEXT NOT NULL,
            masked_account TEXT NOT NULL DEFAULT '', ifsc TEXT NOT NULL DEFAULT '', bank_name TEXT NOT NULL DEFAULT '',
            account_type TEXT NOT NULL DEFAULT 'current', status TEXT NOT NULL DEFAULT 'active',
            metadata_json TEXT NOT NULL DEFAULT '{}', created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS enterprise_tax_entities (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, company_id TEXT, name TEXT NOT NULL,
            gstin TEXT NOT NULL DEFAULT '', state_code TEXT NOT NULL DEFAULT '', registration_type TEXT NOT NULL DEFAULT 'regular',
            status TEXT NOT NULL DEFAULT 'active', metadata_json TEXT NOT NULL DEFAULT '{}', created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS enterprise_billing_items (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL,
            item_type TEXT NOT NULL DEFAULT 'charge', unit TEXT NOT NULL DEFAULT 'unit', tax_code TEXT NOT NULL DEFAULT '',
            mandatory INTEGER NOT NULL DEFAULT 0, rules_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'active',
            created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(organization_id, code)
        );
        CREATE TABLE IF NOT EXISTS enterprise_custom_fields (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_type TEXT NOT NULL, field_key TEXT NOT NULL,
            label TEXT NOT NULL, field_type TEXT NOT NULL DEFAULT 'text', required INTEGER NOT NULL DEFAULT 0,
            options_json TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'active', created_by TEXT, created_at TEXT NOT NULL,
            UNIQUE(organization_id, entity_type, field_key)
        );
        CREATE TABLE IF NOT EXISTS enterprise_company_profiles (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, company_id TEXT,
            display_name TEXT NOT NULL DEFAULT '', logo_path TEXT NOT NULL DEFAULT '', signature_path TEXT NOT NULL DEFAULT '',
            invoice_letterhead_path TEXT NOT NULL DEFAULT '', footer TEXT NOT NULL DEFAULT '', metadata_json TEXT NOT NULL DEFAULT '{}',
            updated_by TEXT, updated_at TEXT NOT NULL, UNIQUE(organization_id, company_id)
        );
        CREATE TABLE IF NOT EXISTS enterprise_plan_subscriptions (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, plan_code TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
            starts_at TEXT NOT NULL, ends_at TEXT, entitlements_json TEXT NOT NULL DEFAULT '{}', created_by TEXT, created_at TEXT NOT NULL,
            UNIQUE(organization_id, plan_code)
        );
        CREATE TABLE IF NOT EXISTS enterprise_usage_events (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, feature_key TEXT NOT NULL, quantity INTEGER NOT NULL DEFAULT 1,
            period_key TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}', created_by TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS enterprise_sso_configs (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, provider TEXT NOT NULL DEFAULT 'oidc',
            issuer_url TEXT NOT NULL DEFAULT '', client_id TEXT NOT NULL DEFAULT '', domains_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'draft', metadata_json TEXT NOT NULL DEFAULT '{}', created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(organization_id, provider)
        );
        CREATE TABLE IF NOT EXISTS passenger_portal_tokens (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, customer_id TEXT, created_by TEXT,
            token_hash TEXT NOT NULL UNIQUE, idempotency_key TEXT, label TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
            expires_at TEXT NOT NULL, created_at TEXT NOT NULL, last_used_at TEXT, UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS booking_control_rules (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
            package_minutes INTEGER NOT NULL DEFAULT 30, package_base_paise INTEGER NOT NULL DEFAULT 0,
            extra_km_paise INTEGER NOT NULL DEFAULT 0, extra_half_hour_paise INTEGER NOT NULL DEFAULT 0,
            auto_switch_json TEXT NOT NULL DEFAULT '{}', supplier_city_json TEXT NOT NULL DEFAULT '{}',
            eta_guard_minutes INTEGER NOT NULL DEFAULT 60, price_guard_paise INTEGER NOT NULL DEFAULT 0,
            customer_controlled_allotment INTEGER NOT NULL DEFAULT 0, temporary_allotment INTEGER NOT NULL DEFAULT 0,
            created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(organization_id, name)
        );
        CREATE TABLE IF NOT EXISTS booking_quotes (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, booking_id TEXT NOT NULL, rule_id TEXT,
            status TEXT NOT NULL DEFAULT 'draft', duration_minutes INTEGER NOT NULL DEFAULT 0, distance_km REAL NOT NULL DEFAULT 0,
            package_minutes INTEGER NOT NULL DEFAULT 30, base_paise INTEGER NOT NULL DEFAULT 0, extra_km_paise INTEGER NOT NULL DEFAULT 0,
            extra_time_paise INTEGER NOT NULL DEFAULT 0, total_paise INTEGER NOT NULL DEFAULT 0, breakdown_json TEXT NOT NULL DEFAULT '{}',
            idempotency_key TEXT, created_by TEXT, created_at TEXT NOT NULL, UNIQUE(organization_id, booking_id, status), UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS allotment_requests (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, booking_id TEXT NOT NULL, supplier_id TEXT,
            request_type TEXT NOT NULL DEFAULT 'multi_supplier', status TEXT NOT NULL DEFAULT 'requested',
            idempotency_key TEXT, offered_amount_paise INTEGER, eta_minutes INTEGER, payload_json TEXT NOT NULL DEFAULT '{}',
            expires_at TEXT, created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS allotment_responses (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, request_id TEXT NOT NULL, supplier_id TEXT,
            status TEXT NOT NULL, amount_paise INTEGER, eta_minutes INTEGER, reason TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS allotment_exceptions (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, booking_id TEXT NOT NULL, duty_id TEXT,
            exception_type TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'medium', status TEXT NOT NULL DEFAULT 'open',
            reason TEXT NOT NULL, resolution_json TEXT NOT NULL DEFAULT '{}', created_by TEXT, created_at TEXT NOT NULL, resolved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS duty_execution_profiles (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, duty_id TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'dashboard',
            driver_mode TEXT NOT NULL DEFAULT 'assigned', garage_start TEXT NOT NULL DEFAULT '', garage_end TEXT NOT NULL DEFAULT '',
            network_supplier_id TEXT, attached_driver_id TEXT, dco_user_id TEXT, config_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(organization_id, duty_id)
        );
        CREATE TABLE IF NOT EXISTS duty_otps (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, duty_id TEXT NOT NULL, otp_type TEXT NOT NULL,
            otp_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'issued', attempts INTEGER NOT NULL DEFAULT 0,
            expires_at TEXT NOT NULL, verified_at TEXT, created_by TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS duty_media_objects (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, duty_id TEXT NOT NULL, media_type TEXT NOT NULL,
            storage_path TEXT NOT NULL, signed_url TEXT NOT NULL DEFAULT '', sha256 TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'pending', created_by TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS duty_slip_documents (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, duty_id TEXT NOT NULL, document_type TEXT NOT NULL DEFAULT 'combined_duty_slip',
            content TEXT NOT NULL DEFAULT '', storage_path TEXT NOT NULL DEFAULT '', download_token_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'ready', created_by TEXT, created_at TEXT NOT NULL, UNIQUE(organization_id, duty_id, document_type)
        );
        CREATE TABLE IF NOT EXISTS duty_evidence_bundles (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, duty_id TEXT NOT NULL, bundle_hash TEXT NOT NULL,
            content_json TEXT NOT NULL DEFAULT '{}', storage_path TEXT NOT NULL, download_token_hash TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'immutable', created_by TEXT, created_at TEXT NOT NULL,
            UNIQUE(organization_id, duty_id, bundle_hash)
        );
        CREATE TABLE IF NOT EXISTS duty_adjustments (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, duty_id TEXT NOT NULL, adjustment_type TEXT NOT NULL,
            amount_paise INTEGER NOT NULL CHECK(amount_paise > 0), reason TEXT NOT NULL, evidence_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending', created_by TEXT, created_at TEXT NOT NULL, approved_by TEXT, approved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS duty_closure_jobs (
            id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, duty_id TEXT NOT NULL, job_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0, notification_attempts INTEGER NOT NULL DEFAULT 0, next_run_at TEXT NOT NULL,
            next_notification_at TEXT, last_error TEXT NOT NULL DEFAULT '', payload_json TEXT NOT NULL DEFAULT '{}', created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_enterprise_groups_org ON enterprise_groups(organization_id, group_type, status);
        CREATE INDEX IF NOT EXISTS idx_enterprise_usage_org_period ON enterprise_usage_events(organization_id, period_key, feature_key);
        CREATE INDEX IF NOT EXISTS idx_passenger_tokens_hash ON passenger_portal_tokens(token_hash, status, expires_at);
        CREATE INDEX IF NOT EXISTS idx_booking_quotes_booking ON booking_quotes(organization_id, booking_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_allotment_requests_booking ON allotment_requests(organization_id, booking_id, status);
        CREATE INDEX IF NOT EXISTS idx_execution_profiles_duty ON duty_execution_profiles(organization_id, duty_id);
        CREATE INDEX IF NOT EXISTS idx_duty_otps_duty ON duty_otps(organization_id, duty_id, otp_type, status);
        CREATE INDEX IF NOT EXISTS idx_duty_media_duty ON duty_media_objects(organization_id, duty_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_duty_adjustments_duty ON duty_adjustments(organization_id, duty_id, status);
        CREATE INDEX IF NOT EXISTS idx_closure_jobs_due ON duty_closure_jobs(organization_id, status, next_run_at);
        """
    )
    portal_columns = {row["name"] for row in conn.execute("PRAGMA table_info(passenger_portal_tokens)").fetchall()}
    if "idempotency_key" not in portal_columns:
        conn.execute("ALTER TABLE passenger_portal_tokens ADD COLUMN idempotency_key TEXT")
    quote_columns = {row["name"] for row in conn.execute("PRAGMA table_info(booking_quotes)").fetchall()}
    if "idempotency_key" not in quote_columns:
        conn.execute("ALTER TABLE booking_quotes ADD COLUMN idempotency_key TEXT")
    request_columns = {row["name"] for row in conn.execute("PRAGMA table_info(allotment_requests)").fetchall()}
    if "idempotency_key" not in request_columns:
        conn.execute("ALTER TABLE allotment_requests ADD COLUMN idempotency_key TEXT")
    job_columns = {row["name"] for row in conn.execute("PRAGMA table_info(duty_closure_jobs)").fetchall()}
    if "notification_attempts" not in job_columns:
        conn.execute("ALTER TABLE duty_closure_jobs ADD COLUMN notification_attempts INTEGER NOT NULL DEFAULT 0")
    if "next_notification_at" not in job_columns:
        conn.execute("ALTER TABLE duty_closure_jobs ADD COLUMN next_notification_at TEXT")


def _staff(user):
    if user["role"] not in {"vendor", "corporate"}:
        raise DomainError(403, "This enterprise control requires an organization operator", "role_forbidden")


def _json_value(value, fallback):
    if isinstance(value, (dict, list)): return value
    try: return json.loads(value) if value else fallback
    except (TypeError, ValueError): return fallback


def _int(payload, key, default=0):
    try: return int(payload.get(key, default) or default)
    except (TypeError, ValueError): raise DomainError(400, f"{key} must be an integer", "validation_error")


def _owned_optional(conn, table, entity_id, org):
    if entity_id: _assert_owned(conn, table, entity_id, org)


def _mandatory_billing_missing(conn, org, payload):
    required = conn.execute("SELECT id, code FROM enterprise_billing_items WHERE organization_id = ? AND status = 'active' AND mandatory = 1", (org,)).fetchall()
    provided = payload.get("billing_items") if isinstance(payload.get("billing_items"), list) else []
    provided_values = {str(item.get("id") or item.get("code") or item.get("item_code") or "").strip() if isinstance(item, dict) else str(item).strip() for item in provided}
    return [row["code"] for row in required if row["id"] not in provided_values and row["code"] not in provided_values]


def _list(conn, table, org, json_fields=()):
    order_column = "updated_at" if table == "enterprise_company_profiles" else "created_at"
    return [_serialize(row, json_fields) for row in conn.execute(f"SELECT * FROM {table} WHERE organization_id = ? ORDER BY {order_column} DESC LIMIT 500", (org,)).fetchall()]


def _collection_route(conn, user, method, route, payload, ip):
    match = re.match(r"^/api/enterprise/(groups|companies|billing-profiles|bank-accounts|tax-entities|billing-items|custom-fields|plans)$", route)
    if not match: return None
    org = _org(user); _staff(user)
    key = match.group(1); table, json_fields = COLLECTIONS[key]
    if method == "GET": return {"ok": True, "items": _list(conn, table, org, json_fields)}
    if method != "POST": raise DomainError(405, "Collection supports GET or POST", "method_not_allowed")
    item_id = new_id(f"enterprise_{key.replace('-', '_')}"); now = now_iso()
    if key == "groups":
        name = _text(payload, "name", maximum=160); code = _text(payload, "code", maximum=80) or name.upper().replace(" ", "_"); group_type = _text(payload, "group_type", "customer", 30); parent = _text(payload, "parent_id") or None; values = (item_id, org, group_type, code, name, parent, _text(payload, "status", "active", 20), json.dumps(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}), user["id"], now, now); sql = "INSERT INTO enterprise_groups(id,organization_id,group_type,code,name,parent_id,status,metadata_json,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
    elif key == "companies":
        name = _text(payload, "legal_name", maximum=200); values = (item_id, org, _text(payload, "code", name[:20].upper(), 60), name, _text(payload, "trading_name", maximum=200), _text(payload, "gstin", maximum=40).upper(), _text(payload, "pan", maximum=20).upper(), int(bool(payload.get("is_sister_company"))), _text(payload, "status", "active", 20), json.dumps(payload.get("billing") if isinstance(payload.get("billing"), dict) else {}), user["id"], now, now); sql = "INSERT INTO enterprise_companies(id,organization_id,code,legal_name,trading_name,gstin,pan,is_sister_company,status,billing_json,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
    elif key == "bank-accounts":
        values = (item_id, org, _text(payload, "company_id") or None, _text(payload, "account_name", maximum=160), _text(payload, "masked_account", maximum=40), _text(payload, "ifsc", maximum=20).upper(), _text(payload, "bank_name", maximum=120), _text(payload, "account_type", "current", 30), _text(payload, "status", "active", 20), json.dumps(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}), user["id"], now, now); sql = "INSERT INTO enterprise_bank_accounts(id,organization_id,company_id,account_name,masked_account,ifsc,bank_name,account_type,status,metadata_json,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
    elif key == "tax-entities":
        values = (item_id, org, _text(payload, "company_id") or None, _text(payload, "name", maximum=160), _text(payload, "gstin", maximum=40).upper(), _text(payload, "state_code", maximum=10), _text(payload, "registration_type", "regular", 30), _text(payload, "status", "active", 20), json.dumps(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}), user["id"], now, now); sql = "INSERT INTO enterprise_tax_entities(id,organization_id,company_id,name,gstin,state_code,registration_type,status,metadata_json,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
    elif key == "billing-items":
        values = (item_id, org, _text(payload, "code", maximum=80), _text(payload, "name", maximum=160), _text(payload, "item_type", "charge", 30), _text(payload, "unit", "unit", 30), _text(payload, "tax_code", maximum=40), int(bool(payload.get("mandatory"))), json.dumps(payload.get("rules") if isinstance(payload.get("rules"), dict) else {}), _text(payload, "status", "active", 20), user["id"], now, now); sql = "INSERT INTO enterprise_billing_items(id,organization_id,code,name,item_type,unit,tax_code,mandatory,rules_json,status,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?, ?,?)"
    elif key == "custom-fields":
        field_key = _text(payload, "field_key", maximum=80).lower(); values = (item_id, org, _text(payload, "entity_type", "booking", 40), field_key, _text(payload, "label", field_key, 160), _text(payload, "field_type", "text", 30), int(bool(payload.get("required"))), json.dumps(payload.get("options") if isinstance(payload.get("options"), list) else []), _text(payload, "status", "active", 20), user["id"], now); sql = "INSERT INTO enterprise_custom_fields(id,organization_id,entity_type,field_key,label,field_type,required,options_json,status,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
    elif key == "billing-profiles":
        values = (item_id, org, _text(payload, "company_id") or None, _text(payload, "tax_entity_id") or None, _text(payload, "bank_account_id") or None, _text(payload, "invoice_series", maximum=80), _text(payload, "currency", "INR", 10).upper(), _text(payload, "bill_to_mode", "company", 30), _text(payload, "status", "active", 20), json.dumps(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}), user["id"], now, now); sql = "INSERT INTO enterprise_billing_profiles(id,organization_id,company_id,tax_entity_id,bank_account_id,invoice_series,currency,bill_to_mode,status,metadata_json,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
    else:  # plans
        values = (item_id, org, _text(payload, "plan_code", maximum=80), _text(payload, "status", "active", 20), _text(payload, "starts_at", now, 40), _text(payload, "ends_at", maximum=40) or None, json.dumps(payload.get("entitlements") if isinstance(payload.get("entitlements"), dict) else {}), user["id"], now); sql = "INSERT INTO enterprise_plan_subscriptions(id,organization_id,plan_code,status,starts_at,ends_at,entitlements_json,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?)"
    conn.execute(sql, values); _audit(conn, user, f"enterprise.{key}.created", table, item_id, ip, {"id": item_id}); return {"ok": True, "item": _serialize(conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone(), json_fields)}


def _enterprise_misc(conn, user, method, route, payload, ip):
    if not route.startswith("/api/enterprise/"):
        return None
    org = _org(user); _staff(user)
    if route == "/api/enterprise/company-profile" and method in {"GET", "POST", "PATCH"}:
        if method == "GET": return {"ok": True, "items": _list(conn, "enterprise_company_profiles", org, ("metadata_json",))}
        company_id = _text(payload, "company_id") or None; now = now_iso(); existing = conn.execute("SELECT id FROM enterprise_company_profiles WHERE organization_id = ? AND company_id IS ?", (org, company_id)).fetchone(); profile_id = existing["id"] if existing else new_id("company_profile"); values = (profile_id, org, company_id, _text(payload, "display_name", maximum=200), _text(payload, "logo_path", maximum=500), _text(payload, "signature_path", maximum=500), _text(payload, "invoice_letterhead_path", maximum=500), _text(payload, "footer", maximum=2000), json.dumps(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}), user["id"], now); conn.execute("INSERT INTO enterprise_company_profiles(id,organization_id,company_id,display_name,logo_path,signature_path,invoice_letterhead_path,footer,metadata_json,updated_by,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(organization_id,company_id) DO UPDATE SET display_name=excluded.display_name,logo_path=excluded.logo_path,signature_path=excluded.signature_path,invoice_letterhead_path=excluded.invoice_letterhead_path,footer=excluded.footer,metadata_json=excluded.metadata_json,updated_by=excluded.updated_by,updated_at=excluded.updated_at", values); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM enterprise_company_profiles WHERE id = ?", (profile_id,)).fetchone(), ("metadata_json",))}
    if route == "/api/enterprise/sso/config" and method in {"GET", "POST", "PATCH"}:
        if method == "GET": return {"ok": True, "items": _list(conn, "enterprise_sso_configs", org, ("domains_json", "metadata_json"))}
        now = now_iso(); provider = _text(payload, "provider", "oidc", 30); existing = conn.execute("SELECT id FROM enterprise_sso_configs WHERE organization_id = ? AND provider = ?", (org, provider)).fetchone(); config_id = existing["id"] if existing else new_id("sso"); conn.execute("INSERT INTO enterprise_sso_configs(id,organization_id,provider,issuer_url,client_id,domains_json,status,metadata_json,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(organization_id,provider) DO UPDATE SET issuer_url=excluded.issuer_url,client_id=excluded.client_id,domains_json=excluded.domains_json,status=excluded.status,metadata_json=excluded.metadata_json,updated_at=excluded.updated_at", (config_id, org, provider, _text(payload, "issuer_url", maximum=500), _text(payload, "client_id", maximum=200), json.dumps(payload.get("domains") if isinstance(payload.get("domains"), list) else []), _text(payload, "status", "draft", 20), json.dumps(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}), user["id"], now, now)); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM enterprise_sso_configs WHERE id = ?", (config_id,)).fetchone(), ("domains_json", "metadata_json"))}
    if route == "/api/enterprise/usage" and method in {"GET", "POST"}:
        if method == "GET": return {"ok": True, "items": _list(conn, "enterprise_usage_events", org, ("metadata_json",))}
        event_id = new_id("usage"); conn.execute("INSERT INTO enterprise_usage_events(id,organization_id,feature_key,quantity,period_key,metadata_json,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)", (event_id, org, _text(payload, "feature_key", maximum=100), _int(payload, "quantity", 1), _text(payload, "period_key", datetime.now(timezone.utc).strftime("%Y-%m"), 20), json.dumps(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}), user["id"], now_iso())); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM enterprise_usage_events WHERE id = ?", (event_id,)).fetchone(), ("metadata_json",))}
    if route == "/api/enterprise/groups/members" and method == "POST":
        group_id = _text(payload, "group_id"); _assert_owned(conn, "enterprise_groups", group_id, org); member_id = new_id("groupmember"); conn.execute("INSERT INTO enterprise_group_members(id,organization_id,group_id,entity_type,entity_id,created_at) VALUES (?,?,?,?,?,?)", (member_id, org, group_id, _text(payload, "entity_type", "customer", 30), _text(payload, "entity_id"), now_iso())); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM enterprise_group_members WHERE id = ?", (member_id,)).fetchone())}
    if route == "/api/enterprise/booking-controls" and method in {"GET", "POST", "PATCH"}:
        if method == "GET": return {"ok": True, "items": _list(conn, "booking_control_rules", org)}
        rule_id = _text(payload, "id") or new_id("bookingrule"); now = now_iso(); conn.execute("INSERT INTO booking_control_rules(id,organization_id,name,status,package_minutes,package_base_paise,extra_km_paise,extra_half_hour_paise,auto_switch_json,supplier_city_json,eta_guard_minutes,price_guard_paise,customer_controlled_allotment,temporary_allotment,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, ?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,status=excluded.status,package_minutes=excluded.package_minutes,package_base_paise=excluded.package_base_paise,extra_km_paise=excluded.extra_km_paise,extra_half_hour_paise=excluded.extra_half_hour_paise,auto_switch_json=excluded.auto_switch_json,supplier_city_json=excluded.supplier_city_json,eta_guard_minutes=excluded.eta_guard_minutes,price_guard_paise=excluded.price_guard_paise,customer_controlled_allotment=excluded.customer_controlled_allotment,temporary_allotment=excluded.temporary_allotment,updated_at=excluded.updated_at", (rule_id, org, _text(payload, "name", "Default half-hour controls", 160), _text(payload, "status", "active", 20), _int(payload, "package_minutes", 30), _int(payload, "package_base_paise"), _int(payload, "extra_km_paise"), _int(payload, "extra_half_hour_paise"), json.dumps(payload.get("auto_switch") if isinstance(payload.get("auto_switch"), dict) else {}), json.dumps(payload.get("supplier_city") if isinstance(payload.get("supplier_city"), dict) else {}), _int(payload, "eta_guard_minutes", 60), _int(payload, "price_guard_paise"), int(bool(payload.get("customer_controlled_allotment"))), int(bool(payload.get("temporary_allotment"))), user["id"], now, now)); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM booking_control_rules WHERE id = ?", (rule_id,)).fetchone(), ("auto_switch_json", "supplier_city_json"))}
    return None


def _passenger_link(conn, user, method, route, payload, ip):
    if route != "/api/passenger/portal-links":
        return None
    org = _org(user); _staff(user)
    if route == "/api/passenger/portal-links" and method == "POST":
        idempotency_key = _text(payload, "idempotency_key", maximum=160) or None
        if idempotency_key:
            replay = conn.execute("SELECT * FROM passenger_portal_tokens WHERE organization_id = ? AND idempotency_key = ?", (org, idempotency_key)).fetchone()
            if replay:
                return {"ok": True, "item": _serialize(replay), "idempotent_replay": True, "portal_path": None, "token_replay": False}
        raw = secrets.token_urlsafe(32); token_hash = hashlib.sha256(raw.encode()).hexdigest(); link_id = new_id("passenger_link"); now = now_iso(); expires = _text(payload, "expires_at", (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(), 40); customer_id = _text(payload, "customer_id") or None; _owned_optional(conn, "domain_customers", customer_id, org); conn.execute("INSERT INTO passenger_portal_tokens(id,organization_id,customer_id,created_by,token_hash,idempotency_key,label,expires_at,created_at) VALUES (?,?,?,?,?,?,?,?,?)", (link_id, org, customer_id, user["id"], token_hash, idempotency_key, _text(payload, "label", "Passenger request portal", 160), expires, now)); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM passenger_portal_tokens WHERE id = ?", (link_id,)).fetchone()), "portal_token": raw, "portal_path": f"/api/passenger/v1/portal/{raw}", "portal_url": f"/?passenger_token={raw}"}
    if route == "/api/passenger/portal-links" and method == "GET": return {"ok": True, "items": _list(conn, "passenger_portal_tokens", org)}
    return None


def _availability_calendar(conn, user, raw_route):
    org = _org(user); _staff(user); query = parse_qs(urlsplit(raw_route).query); start = query.get("start", [now_iso()[:10]])[0]; end = query.get("end", [start])[0]; vehicles = conn.execute("SELECT id, registration_number, vehicle_group, city, status FROM domain_vehicles WHERE organization_id = ? AND status NOT IN ('inactive','archived')", (org,)).fetchall(); drivers = conn.execute("SELECT id, full_name, city, status FROM domain_drivers WHERE organization_id = ? AND status NOT IN ('inactive','archived')", (org,)).fetchall(); duties = conn.execute("SELECT id, driver_id, vehicle_id, reporting_at, status FROM domain_duties WHERE organization_id = ? AND reporting_at >= ? AND reporting_at <= ? ORDER BY reporting_at", (org, start, end + "T23:59:59Z")).fetchall(); busy_driver = {row["driver_id"] for row in duties if row["status"] not in {"completed", "cancelled"}}; busy_vehicle = {row["vehicle_id"] for row in duties if row["status"] not in {"completed", "cancelled"}}; return {"ok": True, "range": {"start": start, "end": end}, "resources": {"vehicles": [_serialize(row) | {"available": row["id"] not in busy_vehicle} for row in vehicles], "drivers": [_serialize(row) | {"available": row["id"] not in busy_driver} for row in drivers]}, "duties": [_serialize(row) for row in duties]}


def _quote(conn, user, booking_id, payload, ip):
    org = _org(user); _staff(user); booking = _assert_owned(conn, "domain_bookings", booking_id, org)
    idempotency_key = _text(payload, "idempotency_key", maximum=160) or None
    if idempotency_key:
        replay = conn.execute("SELECT * FROM booking_quotes WHERE organization_id = ? AND idempotency_key = ?", (org, idempotency_key)).fetchone()
        if replay:
            return {"ok": True, "item": _serialize(replay, ("breakdown_json",)), "booking_id": booking["id"], "idempotent_replay": True}
    rule = conn.execute("SELECT * FROM booking_control_rules WHERE organization_id = ? AND status = 'active' ORDER BY updated_at DESC LIMIT 1", (org,)).fetchone(); duration = max(0, _int(payload, "duration_minutes")); distance = float(payload.get("distance_km") or 0); package = _int(payload, "package_minutes", int(rule["package_minutes"] if rule else 30)); base = _int(payload, "base_paise", int(rule["package_base_paise"] if rule else 0)); extra_km_rate = _int(payload, "extra_km_paise", int(rule["extra_km_paise"] if rule else 0)); extra_half = _int(payload, "extra_half_hour_paise", int(rule["extra_half_hour_paise"] if rule else 0)); included_km = float(payload.get("included_km") or 0); extra_km = max(0, distance - included_km); extra_blocks = max(0, (max(0, duration - package) + 29) // 30); extra_km_total = round(extra_km * extra_km_rate); extra_time_total = extra_blocks * extra_half; total = base + extra_km_total + extra_time_total; quote_id = new_id("quote"); now = now_iso(); breakdown = {"package_minutes": package, "duration_minutes": duration, "distance_km": distance, "included_km": included_km, "extra_km": extra_km, "extra_blocks": extra_blocks, "automatic_switch": bool(rule and _json_value(rule["auto_switch_json"], {})), "rule_id": rule["id"] if rule else None}; conn.execute("INSERT INTO booking_quotes(id,organization_id,booking_id,rule_id,status,duration_minutes,distance_km,package_minutes,base_paise,extra_km_paise,extra_time_paise,total_paise,breakdown_json,idempotency_key,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (quote_id, org, booking_id, rule["id"] if rule else None, "draft", duration, distance, package, base, extra_km_total, extra_time_total, total, json.dumps(breakdown), idempotency_key, user["id"], now)); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM booking_quotes WHERE id = ?", (quote_id,)).fetchone(), ("breakdown_json",)), "booking_id": booking["id"]}


def _allotment_controls(conn, user, method, route, payload, ip):
    request_match = re.match(r"^/api/bookings/([^/]+)/allotment-requests$", route)
    response_match = re.match(r"^/api/allotment-requests/([^/]+)/respond$", route)
    if not request_match and not response_match and route != "/api/allotment-exceptions":
        return None
    org = _org(user); _staff(user)
    if request_match and method in {"GET", "POST"}:
        booking_id = request_match.group(1); _assert_owned(conn, "domain_bookings", booking_id, org)
        if method == "GET": rows = conn.execute("SELECT * FROM allotment_requests WHERE organization_id = ? AND booking_id = ? ORDER BY created_at DESC", (org, booking_id)).fetchall(); return {"ok": True, "items": [_serialize(row, ("payload_json",)) for row in rows]}
        supplier_ids = payload.get("supplier_ids") if isinstance(payload.get("supplier_ids"), list) else [payload.get("supplier_id")]
        created = []
        for supplier_id in [str(item) for item in supplier_ids if item]:
            _assert_owned(conn, "domain_suppliers", supplier_id, org)
            request_key = _text(payload, "idempotency_key", maximum=160) or None
            if request_key:
                request_key = f"{request_key}:{supplier_id}"
            replay = conn.execute("SELECT * FROM allotment_requests WHERE organization_id = ? AND idempotency_key = ?", (org, request_key)).fetchone() if request_key else None
            if replay:
                created.append(_serialize(replay, ("payload_json",)))
                continue
            request_id = new_id("allot_request"); now = now_iso(); conn.execute("INSERT INTO allotment_requests(id,organization_id,booking_id,supplier_id,request_type,status,idempotency_key,payload_json,expires_at,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (request_id, org, booking_id, supplier_id, _text(payload, "request_type", "multi_supplier", 30), "requested", request_key, json.dumps(payload), _text(payload, "expires_at", maximum=40) or None, user["id"], now, now)); created.append(_serialize(conn.execute("SELECT * FROM allotment_requests WHERE id = ?", (request_id,)).fetchone(), ("payload_json",)))
        return {"ok": True, "items": created}
    response_match = re.match(r"^/api/allotment-requests/([^/]+)/respond$", route)
    if response_match and method == "POST":
        request = conn.execute("SELECT * FROM allotment_requests WHERE id = ? AND organization_id = ?", (response_match.group(1), org)).fetchone()
        if not request: raise DomainError(404, "Allotment request not found", "not_found")
        status = _text(payload, "status", maximum=30)
        if status not in {"accepted", "declined", "expired"}: raise DomainError(400, "Unsupported allotment response", "validation_error")
        response_id = new_id("allot_response"); conn.execute("INSERT INTO allotment_responses(id,organization_id,request_id,supplier_id,status,amount_paise,eta_minutes,reason,payload_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (response_id, org, request["id"], request["supplier_id"], status, _int(payload, "amount_paise") if payload.get("amount_paise") is not None else None, _int(payload, "eta_minutes") if payload.get("eta_minutes") is not None else None, _text(payload, "reason", maximum=300), json.dumps(payload), now_iso())); conn.execute("UPDATE allotment_requests SET status = ?, offered_amount_paise = ?, eta_minutes = ?, updated_at = ? WHERE id = ?", (status, payload.get("amount_paise"), payload.get("eta_minutes"), now_iso(), request["id"])); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM allotment_responses WHERE id = ?", (response_id,)).fetchone(), ("payload_json",))}
    if route == "/api/allotment-exceptions" and method in {"GET", "POST"}:
        if method == "GET": return {"ok": True, "items": _list(conn, "allotment_exceptions", org, ("resolution_json",))}
        booking_id = _text(payload, "booking_id"); _assert_owned(conn, "domain_bookings", booking_id, org); exception_id = new_id("allot_exception"); conn.execute("INSERT INTO allotment_exceptions(id,organization_id,booking_id,duty_id,exception_type,severity,status,reason,resolution_json,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (exception_id, org, booking_id, _text(payload, "duty_id") or None, _text(payload, "exception_type", "no_capacity", 50), _text(payload, "severity", "medium", 20), "open", _text(payload, "reason", maximum=1000), "{}", user["id"], now_iso())); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM allotment_exceptions WHERE id = ?", (exception_id,)).fetchone(), ("resolution_json",))}
    return None


def _evidence_bundle(conn, user, duty_id, ip):
    org = _org(user); _staff(user); duty = _assert_owned(conn, "domain_duties", duty_id, org)
    closure = conn.execute("SELECT * FROM domain_duty_closures WHERE organization_id = ? AND duty_id = ? ORDER BY closure_version DESC LIMIT 1", (org, duty_id)).fetchone()
    evidence = conn.execute("SELECT * FROM domain_closure_evidence WHERE organization_id = ? AND duty_id = ? ORDER BY captured_at", (org, duty_id)).fetchall()
    media = conn.execute("SELECT * FROM duty_media_objects WHERE organization_id = ? AND duty_id = ? ORDER BY created_at", (org, duty_id)).fetchall()
    adjustments = conn.execute("SELECT * FROM duty_adjustments WHERE organization_id = ? AND duty_id = ? ORDER BY created_at", (org, duty_id)).fetchall()
    payload = {"duty": _serialize(duty, ("calculation_snapshot_json",)), "closure": _serialize(closure, ("payload_json", "completeness_json")), "evidence": [_serialize(item, ("metadata_json",)) for item in evidence], "media": [_serialize(item, ("metadata_json",)) for item in media], "adjustments": [_serialize(item, ("evidence_json",)) for item in adjustments]}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")); bundle_hash = hashlib.sha256(canonical.encode()).hexdigest(); existing = conn.execute("SELECT * FROM duty_evidence_bundles WHERE organization_id = ? AND duty_id = ? AND bundle_hash = ?", (org, duty_id, bundle_hash)).fetchone()
    if existing:
        return {"ok": True, "item": _serialize(existing, ("content_json",)), "immutable": True, "bundle_hash": bundle_hash, "download_token": None}
    raw = secrets.token_urlsafe(32); bundle_id = new_id("evidence_bundle"); now = now_iso(); conn.execute("INSERT INTO duty_evidence_bundles(id,organization_id,duty_id,bundle_hash,content_json,storage_path,download_token_hash,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?)", (bundle_id, org, duty_id, bundle_hash, canonical, f"mock://evidence-bundles/{duty_id}/{bundle_hash}.json", hashlib.sha256(raw.encode()).hexdigest(), user["id"], now)); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM duty_evidence_bundles WHERE id = ?", (bundle_id,)).fetchone(), ("content_json",)), "immutable": True, "bundle_hash": bundle_hash, "download_token": raw, "download_path": f"/api/duty-evidence/v1/{raw}"}


def _duty_controls(conn, user, method, route, payload, ip):
    match = re.match(r"^/api/duties/([^/]+)/(execution-profile|otp|otp/verify|media|slip|evidence-bundle|adjustments|sms-close|network-execution|dco|attached-driver|garage-transfer)$", route)
    if not match: return None
    org = _org(user); _staff(user)
    duty_id, action = match.group(1), match.group(2); duty = _assert_owned(conn, "domain_duties", duty_id, org)
    if action == "execution-profile" and method in {"GET", "POST", "PATCH"}:
        if method == "GET": return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM duty_execution_profiles WHERE organization_id = ? AND duty_id = ?", (org, duty_id)).fetchone(), ("config_json",))}
        now = now_iso(); profile_id = new_id("execution_profile"); conn.execute("INSERT INTO duty_execution_profiles(id,organization_id,duty_id,source,driver_mode,garage_start,garage_end,network_supplier_id,attached_driver_id,dco_user_id,config_json,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(organization_id,duty_id) DO UPDATE SET source=excluded.source,driver_mode=excluded.driver_mode,garage_start=excluded.garage_start,garage_end=excluded.garage_end,network_supplier_id=excluded.network_supplier_id,attached_driver_id=excluded.attached_driver_id,dco_user_id=excluded.dco_user_id,config_json=excluded.config_json,updated_at=excluded.updated_at", (profile_id, org, duty_id, _text(payload, "source", "dashboard", 30), _text(payload, "driver_mode", "assigned", 30), _text(payload, "garage_start", maximum=200), _text(payload, "garage_end", maximum=200), _text(payload, "network_supplier_id") or None, _text(payload, "attached_driver_id") or None, _text(payload, "dco_user_id") or None, json.dumps(payload.get("config") if isinstance(payload.get("config"), dict) else {}), user["id"], now, now)); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM duty_execution_profiles WHERE organization_id = ? AND duty_id = ?", (org, duty_id)).fetchone(), ("config_json",))}
    if action in {"network-execution", "dco", "attached-driver", "garage-transfer"} and method == "POST":
        payload = {**payload, "source": {"network-execution": "network_driver", "dco": "dco", "attached-driver": "attached_driver", "garage-transfer": "garage_to_garage"}[action]}; return _duty_controls(conn, user, "POST", f"/api/duties/{duty_id}/execution-profile", payload, ip)
    if action == "otp" and method == "POST":
        otp_type = _text(payload, "otp_type", "start", 10); if_expiry = datetime.now(timezone.utc) + timedelta(minutes=15); raw = f"{secrets.randbelow(900000)+100000}"; otp_id = new_id("otp"); conn.execute("INSERT INTO duty_otps(id,organization_id,duty_id,otp_type,otp_hash,status,expires_at,created_by,created_at) VALUES (?,?,?,?,?,'issued',?,?,?)", (otp_id, org, duty_id, otp_type, hashlib.sha256(raw.encode()).hexdigest(), if_expiry.isoformat(), user["id"], now_iso())); return {"ok": True, "item": {"id": otp_id, "duty_id": duty_id, "otp_type": otp_type, "expires_at": if_expiry.isoformat()}, "otp": raw}
    if action == "otp/verify" and method == "POST":
        otp_type = _text(payload, "otp_type", "start", 10)
        row = conn.execute("SELECT * FROM duty_otps WHERE organization_id = ? AND duty_id = ? AND otp_type = ? AND status = 'issued' ORDER BY created_at DESC LIMIT 1", (org, duty_id, otp_type)).fetchone()
        if not row:
            raise DomainError(404, "Active OTP not found", "otp_not_found")
        if datetime.now(timezone.utc) > datetime.fromisoformat(row["expires_at"]):
            raise DomainError(410, "OTP expired", "otp_expired")
        supplied = _text(payload, "otp", maximum=12)
        if hashlib.sha256(supplied.encode()).hexdigest() != row["otp_hash"]:
            conn.execute("UPDATE duty_otps SET attempts = attempts + 1 WHERE id = ?", (row["id"],))
            raise DomainError(401, "OTP is incorrect", "otp_invalid")
        conn.execute("UPDATE duty_otps SET status = 'verified', verified_at = ? WHERE id = ?", (now_iso(), row["id"]))
        return {"ok": True, "verified": True, "otp_type": otp_type}
    if action == "media" and method in {"GET", "POST"}:
        if method == "GET": return {"ok": True, "items": _list(conn, "duty_media_objects", org, ("metadata_json",))}
        media_id = new_id("media"); path = _text(payload, "storage_path", f"mock://duty/{duty_id}/{media_id}", 500); signed = f"{path}?signed=local-{secrets.token_urlsafe(12)}"; conn.execute("INSERT INTO duty_media_objects(id,organization_id,duty_id,media_type,storage_path,signed_url,sha256,metadata_json,status,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (media_id, org, duty_id, _text(payload, "media_type", "attachment", 40), path, signed, _text(payload, "sha256", maximum=128), json.dumps(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}), "ready", user["id"], now_iso())); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM duty_media_objects WHERE id = ?", (media_id,)).fetchone(), ("metadata_json",)), "signed_url": signed}
    if action == "evidence-bundle" and method in {"GET", "POST"}:
        return _evidence_bundle(conn, user, duty_id, ip)
    if action == "slip" and method in {"GET", "POST"}:
        existing = conn.execute("SELECT * FROM duty_slip_documents WHERE organization_id = ? AND duty_id = ? AND document_type = 'combined_duty_slip'", (org, duty_id)).fetchone()
        if method == "GET" and existing: return {"ok": True, "item": _serialize(existing)}
        closure = conn.execute("SELECT * FROM domain_duty_closures WHERE organization_id = ? AND duty_id = ? ORDER BY closure_version DESC LIMIT 1", (org, duty_id)).fetchone(); evidence = conn.execute("SELECT * FROM domain_closure_evidence WHERE organization_id = ? AND duty_id = ? ORDER BY captured_at", (org, duty_id)).fetchall(); content = json.dumps({"duty": _serialize(duty, ("calculation_snapshot_json",)), "closure": _serialize(closure, ("payload_json", "completeness_json")), "evidence": [_serialize(item, ("metadata_json",)) for item in evidence]}, indent=2); print_html = f"<!doctype html><html><head><meta charset='utf-8'><title>Axiom Fleet duty slip {html.escape(duty_id)}</title><style>body{{font:14px system-ui;color:#17202b;margin:32px}}pre{{white-space:pre-wrap;background:#f5f7fa;padding:18px;border-radius:8px}}@media print{{body{{margin:10mm}}}}</style></head><body><h1>Axiom Fleet · Combined duty slip</h1><p>Duty {html.escape(duty_id)} · generated {html.escape(now_iso())}</p><pre>{html.escape(content)}</pre></body></html>"; doc_id = existing["id"] if existing else new_id("duty_slip"); token = secrets.token_urlsafe(24); now = now_iso(); conn.execute("INSERT INTO duty_slip_documents(id,organization_id,duty_id,document_type,content,storage_path,download_token_hash,status,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(organization_id,duty_id,document_type) DO UPDATE SET content=excluded.content,download_token_hash=excluded.download_token_hash,status='ready',created_at=excluded.created_at", (doc_id, org, duty_id, "combined_duty_slip", content, f"mock://duty-slips/{duty_id}.html", hashlib.sha256(token.encode()).hexdigest(), "ready", user["id"], now)); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM duty_slip_documents WHERE id = ?", (doc_id,)).fetchone()), "download_token": token, "format": "html-printable", "print_html": print_html}
    if action == "adjustments" and method in {"GET", "POST"}:
        if method == "GET":
            return {"ok": True, "items": [_serialize(row, ("evidence_json",)) for row in conn.execute("SELECT * FROM duty_adjustments WHERE organization_id = ? AND duty_id = ? ORDER BY created_at DESC", (org, duty_id)).fetchall()]}
        adjustment = _text(payload, "adjustment_type", maximum=20)
        if adjustment not in {"credit", "debit"}:
            raise DomainError(400, "adjustment_type must be credit or debit", "validation_error")
        amount = _int(payload, "amount_paise")
        if amount <= 0:
            raise DomainError(400, "Adjustment amount must be positive", "validation_error")
        adj_id = new_id("adjustment")
        conn.execute("INSERT INTO duty_adjustments(id,organization_id,duty_id,adjustment_type,amount_paise,reason,evidence_json,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?)", (adj_id, org, duty_id, adjustment, amount, _text(payload, "reason", maximum=1000), json.dumps(payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}), user["id"], now_iso()))
        return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM duty_adjustments WHERE id = ?", (adj_id,)).fetchone(), ("evidence_json",))}
    if action == "sms-close" and method == "POST":
        raw = secrets.token_urlsafe(28); token_hash = hashlib.sha256(raw.encode()).hexdigest(); job_id = new_id("sms_close"); expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(); conn.execute("INSERT INTO duty_closure_jobs(id,organization_id,duty_id,job_type,status,attempts,next_run_at,payload_json,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (job_id, org, duty_id, "sms_close", "queued", 0, expires, json.dumps({"token_hash": token_hash, "expires_at": expires}), user["id"], now_iso(), now_iso())); return {"ok": True, "item": {"job_id": job_id, "expires_at": expires}, "action_token": raw, "action_path": f"/api/duty-close/v1/{raw}"}
    return None


def _admin_route(conn, user, method, raw_route, payload, ip):
    route = urlsplit(raw_route).path.rstrip("/") or "/"
    result = _collection_route(conn, user, method, route, payload, ip)
    if result is not None: return result
    result = _enterprise_misc(conn, user, method, route, payload, ip)
    if result is not None: return result
    result = _passenger_link(conn, user, method, route, payload, ip)
    if result is not None: return result
    if route == "/api/availability/calendar" and method == "GET": return _availability_calendar(conn, user, raw_route)
    quote_match = re.match(r"^/api/bookings/([^/]+)/quote$", route)
    if quote_match and method == "POST": return _quote(conn, user, quote_match.group(1), payload, ip)
    close_match = re.match(r"^/api/duties/([^/]+)/close$", route)
    if close_match and method == "POST":
        org = _org(user)
        duty_id = close_match.group(1); _assert_owned(conn, "domain_duties", duty_id, org)
        missing_billing = _mandatory_billing_missing(conn, org, payload)
        if missing_billing:
            raise DomainError(409, "Mandatory billing items are missing", "billing_items_required", {"missing_billing_items": missing_billing})
        return _close_duty(conn, user, duty_id, payload, ip)
    result = _allotment_controls(conn, user, method, route, payload, ip)
    if result is not None: return result
    result = _duty_controls(conn, user, method, route, payload, ip)
    if result is not None: return result
    if route == "/api/duty-closure-jobs" and method == "GET": return {"ok": True, "items": _list(conn, "duty_closure_jobs", _org(user), ("payload_json",))}
    if route == "/api/duty-closure-jobs/run" and method == "POST":
        org = _org(user); _staff(user); now = now_iso(); jobs = conn.execute("SELECT * FROM duty_closure_jobs WHERE organization_id = ? AND status = 'queued' AND next_run_at <= ?", (org, now)).fetchall(); processed = 0
        for job in jobs:
            conn.execute("UPDATE duty_closure_jobs SET status='processing',attempts=attempts+1,updated_at=? WHERE id=?", (now, job["id"])); processed += 1
        retry_count = conn.execute("UPDATE duty_closure_jobs SET notification_attempts=notification_attempts+1,next_notification_at=? WHERE organization_id=? AND status IN ('queued','processing') AND next_notification_at IS NOT NULL AND next_notification_at <= ?", (now, org, now)).rowcount
        approvals = conn.execute("SELECT id FROM corporate_duty_slip_approvals WHERE organization_id = ? AND status = 'pending' AND auto_approve_at <= ?", (org, now)).fetchall()
        for approval in approvals:
            conn.execute("UPDATE corporate_duty_slip_approvals SET status='auto_approved', decision_reason='48_hour_expiry_auto_approval', decided_at=? WHERE id=? AND status='pending'", (now, approval["id"]))
        return {"ok": True, "processed": processed, "notification_retries": retry_count, "auto_approved": len(approvals), "approval_window_hours": 48, "items": [_serialize(row, ("payload_json",)) for row in jobs]}
    return None


def handle_enterprise_controls(conn, user, method: str, raw_route: str, payload: dict, ip: str):
    return _admin_route(conn, user, method, raw_route, payload, ip)


def handle_enterprise_public(conn, method: str, raw_route: str, payload: dict, ip: str):
    route = urlsplit(raw_route).path.rstrip("/") or "/"; match = re.match(r"^/api/passenger/v1/portal/([^/]+)$", route); close_match = re.match(r"^/api/duty-close/v1/([^/]+)$", route)
    if match:
        token = match.group(1)
        row = conn.execute("SELECT * FROM passenger_portal_tokens WHERE token_hash = ? AND status = 'active'", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if row is None:
            raise DomainError(403, "Passenger portal link is invalid", "invalid_portal_token")
        if datetime.now(timezone.utc) > datetime.fromisoformat(row["expires_at"]):
            raise DomainError(410, "Passenger portal link has expired", "portal_token_expired")
        if method == "GET":
            return {"ok": True, "portal": {"id": row["id"], "label": row["label"], "expires_at": row["expires_at"], "organization_id": row["organization_id"]}}
        if method != "POST":
            raise DomainError(405, "Passenger portal supports GET or POST", "method_not_allowed")
        booking_id = new_id("booking")
        booking_ref = _text(payload, "booking_reference", f"PAX-{datetime.now(timezone.utc):%Y%m%d}-{booking_id[-6:]}", 100)
        now = now_iso()
        customer_id = row["customer_id"] or None
        conn.execute("INSERT INTO domain_bookings(id,organization_id,customer_id,booking_reference,status,passenger_name,passenger_phone,passenger_email,pickup_json,dropoff_json,scheduled_at,duty_type,source,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (booking_id, row["organization_id"], customer_id, booking_ref, "requested", _text(payload, "passenger_name", maximum=160), _text(payload, "passenger_phone", maximum=40), _text(payload, "passenger_email", maximum=254), json.dumps(payload.get("pickup") if isinstance(payload.get("pickup"), dict) else {}), json.dumps(payload.get("dropoff") if isinstance(payload.get("dropoff"), dict) else {}), _text(payload, "scheduled_at", maximum=40), _text(payload, "duty_type", "airport", 60), "passenger_portal", _text(payload, "notes", maximum=1000), now, now))
        conn.execute("UPDATE passenger_portal_tokens SET last_used_at = ? WHERE id = ?", (now, row["id"]))
        conn.execute("INSERT INTO audit_events(id,user_id,action,entity_type,entity_id,metadata_json,ip_address,created_at) VALUES (?,?,?,?,?,?,?,?)", (new_id("audit"), None, "passenger.booking_requested", "booking", booking_id, json.dumps({"portal_id": row["id"], "source": "passenger_portal"}), ip, now))
        return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_bookings WHERE id = ?", (booking_id,)).fetchone(), ("pickup_json", "dropoff_json"))}
    if close_match:
        token = close_match.group(1)
        row = conn.execute("SELECT * FROM duty_closure_jobs WHERE json_extract(payload_json,'$.token_hash') = ? AND job_type = 'sms_close' AND status = 'queued'", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if row is None:
            raise DomainError(403, "Duty closure link is invalid", "invalid_close_token")
        if method == "GET":
            return {"ok": True, "item": {"duty_id": row["duty_id"], "expires_at": _json_value(row["payload_json"], {}).get("expires_at")}}
        service_user = {"id": None, "role": "vendor", "organization_id": row["organization_id"], "email": "sms-close@system", "full_name": "SMS closure"}
        close_payload = {**payload, "source": "sms"}
        missing_billing = _mandatory_billing_missing(conn, row["organization_id"], close_payload)
        if missing_billing:
            raise DomainError(409, "Mandatory billing items are missing", "billing_items_required", {"missing_billing_items": missing_billing})
        result = _close_duty(conn, service_user, row["duty_id"], close_payload, ip)
        conn.execute("UPDATE duty_closure_jobs SET status = 'completed', updated_at = ? WHERE id = ?", (now_iso(), row["id"]))
        return result
    return None
