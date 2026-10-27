"""Additional local product features used to make the Axiom Fleet preview operable.

This module keeps the dependency-free local fallback broad enough to exercise the
PRD workflows while the same contracts are moved to Supabase/RPCs in production.
It deliberately uses the domain module's organization and audit helpers so every
feature stays tenant-scoped and testable.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

from backend_domain import (
    DomainError,
    DEFAULT_PROVIDERS,
    _assert_owned,
    _audit,
    _create_booking,
    _create_duty,
    _duty,
    _json,
    _org,
    _require_role,
    _serialize,
    _text,
    now_iso,
    new_id,
)


FEATURE_PREFIXES = (
    "/api/branches",
    "/api/manufacturers",
    "/api/bookings",
    "/api/invoices",
    "/api/suppliers",
    "/api/price-books",
    "/api/documents",
    "/api/invitations",
    "/api/employees",
    "/api/policies",
    "/api/approvals",
    "/api/notifications",
    "/api/reports",
    "/api/audit",
    "/api/tickets",
    "/api/privacy",
    "/api/integrations",
    "/api/organization",
    "/api/settings",
)


def initialize_feature_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS domain_branches (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            city TEXT NOT NULL DEFAULT '',
            address_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, code)
        );
        CREATE TABLE IF NOT EXISTS domain_suppliers (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            name TEXT NOT NULL,
            supplier_type TEXT NOT NULL DEFAULT 'company',
            email TEXT NOT NULL DEFAULT '',
            phone TEXT NOT NULL DEFAULT '',
            gstin TEXT NOT NULL DEFAULT '',
            cities_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_price_books (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            branch_id TEXT,
            name TEXT NOT NULL,
            effective_from TEXT NOT NULL,
            effective_to TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            version INTEGER NOT NULL DEFAULT 1,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_price_book_items (
            id TEXT PRIMARY KEY,
            price_book_id TEXT NOT NULL,
            duty_type TEXT NOT NULL,
            vehicle_group TEXT NOT NULL DEFAULT '',
            base_paise INTEGER NOT NULL DEFAULT 0,
            per_km_paise INTEGER NOT NULL DEFAULT 0,
            per_hour_paise INTEGER NOT NULL DEFAULT 0,
            waiting_paise INTEGER NOT NULL DEFAULT 0,
            tax_rate_bps INTEGER NOT NULL DEFAULT 0,
            rules_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_documents (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            document_type TEXT NOT NULL,
            file_name TEXT NOT NULL,
            storage_path TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending_review',
            expires_at TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            uploaded_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_invitations (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            email TEXT NOT NULL,
            role TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'pending',
            expires_at TEXT NOT NULL,
            invited_by TEXT,
            accepted_by TEXT,
            created_at TEXT NOT NULL,
            accepted_at TEXT
        );
        CREATE TABLE IF NOT EXISTS domain_employees (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            employee_code TEXT NOT NULL,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL DEFAULT '',
            phone TEXT NOT NULL DEFAULT '',
            department TEXT NOT NULL DEFAULT '',
            cost_center TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, employee_code)
        );
        CREATE TABLE IF NOT EXISTS domain_policies (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            rules_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_booking_approvals (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            booking_id TEXT NOT NULL,
            approver_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            comment TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, booking_id, approver_id)
        );
        CREATE TABLE IF NOT EXISTS domain_notifications (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            recipient_id TEXT,
            channel TEXT NOT NULL,
            template_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            provider_reference TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            delivered_at TEXT,
            read_at TEXT
        );
        CREATE TABLE IF NOT EXISTS domain_tickets (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            opened_by TEXT,
            subject TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            priority TEXT NOT NULL DEFAULT 'normal',
            status TEXT NOT NULL DEFAULT 'open',
            assignee_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_privacy_requests (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            requester_id TEXT,
            request_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS domain_org_settings (
            organization_id TEXT PRIMARY KEY,
            settings_json TEXT NOT NULL DEFAULT '{}',
            updated_by TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_einvoice_records (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            invoice_id TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT 'mock_einvoice',
            status TEXT NOT NULL DEFAULT 'issued',
            irn TEXT NOT NULL,
            qr_payload TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, invoice_id)
        );
        CREATE TABLE IF NOT EXISTS domain_collection_actions (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            invoice_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            channel TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            provider_reference TEXT NOT NULL DEFAULT '',
            scheduled_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_feature_branches_org ON domain_branches(organization_id, status);
        CREATE INDEX IF NOT EXISTS idx_feature_suppliers_org ON domain_suppliers(organization_id, status);
        CREATE TABLE IF NOT EXISTS domain_manufacturers (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            code TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL,
            country TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, name)
        );
        CREATE INDEX IF NOT EXISTS idx_feature_manufacturers_org ON domain_manufacturers(organization_id, status);
        CREATE INDEX IF NOT EXISTS idx_feature_price_books_org ON domain_price_books(organization_id, status, effective_from);
        CREATE INDEX IF NOT EXISTS idx_feature_documents_entity ON domain_documents(organization_id, entity_type, entity_id);
        CREATE INDEX IF NOT EXISTS idx_feature_invitations_org ON domain_invitations(organization_id, status, expires_at);
        CREATE INDEX IF NOT EXISTS idx_feature_employees_org ON domain_employees(organization_id, status);
        CREATE INDEX IF NOT EXISTS idx_feature_approvals_booking ON domain_booking_approvals(booking_id, status);
        CREATE INDEX IF NOT EXISTS idx_feature_notifications_recipient ON domain_notifications(organization_id, recipient_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_feature_tickets_org ON domain_tickets(organization_id, status, created_at);
        """
    )


def seed_feature_data(conn) -> None:
    org = conn.execute("SELECT id FROM organizations WHERE id = 'org_demo_blueorbit'").fetchone()
    if not org:
        return
    now = now_iso()
    _ensure_default_manufacturers(conn, org["id"])
    conn.execute(
        "INSERT OR IGNORE INTO domain_branches(id, organization_id, code, name, city, address_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("branch_demo_mumbai", org["id"], "MUM", "Mumbai control room", "Mumbai", json.dumps({"line1": "BKC Fleet Hub"}), now, now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO domain_suppliers(id, organization_id, name, supplier_type, email, phone, gstin, cities_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("supplier_demo_network", org["id"], "BlueOrbit Network Partner", "associate_fleet", "ops@partner.example", "+91 90000 33333", "27ABCDE1234F1Z5", json.dumps(["Mumbai", "Pune"]), now, now),
    )
    price_book = "pricebook_demo_september"
    conn.execute(
        "INSERT OR IGNORE INTO domain_price_books(id, organization_id, branch_id, name, effective_from, status, version, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'active', 1, ?, ?, ?)",
        (price_book, org["id"], "branch_demo_mumbai", "September 2026 enterprise rates", "2026-09-01", "usr_demo_admin", now, now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO domain_price_book_items(id, price_book_id, duty_type, vehicle_group, base_paise, per_km_paise, per_hour_paise, waiting_paise, tax_rate_bps, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("priceitem_demo_airport", price_book, "airport", "executive_sedan", 180000, 1800, 2400, 1800, 1800, now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO domain_employees(id, organization_id, employee_code, full_name, email, phone, department, cost_center, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("employee_demo_rohit", org["id"], "EMP-001", "Rohit Mehta", "rohit@blueorbit.example", "+91 90000 22222", "Technology", "CC-100", now, now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO domain_policies(id, organization_id, name, status, rules_json, created_by, created_at, updated_at) VALUES (?, ?, ?, 'active', ?, ?, ?, ?)",
        ("policy_demo_travel", org["id"], "Standard India travel policy", json.dumps({"approval_required_above_paise": 500000, "allowed_vehicle_groups": ["standard_sedan", "executive_sedan", "suv"]}), "usr_demo_admin", now, now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO domain_org_settings(organization_id, settings_json, updated_by, updated_at) VALUES (?, ?, ?, ?)",
        (org["id"], json.dumps({"timezone": "Asia/Calcutta", "currency": "INR", "default_tax_rate_bps": 1800, "notifications": {"email": True, "sms": False}}), "usr_demo_admin", now),
    )


def _feature_org(user) -> str:
    organization_id = user["organization_id"]
    if not organization_id:
        raise DomainError(403, "An organization-linked account is required", "organization_required")
    return organization_id


def _staff(user) -> None:
    if user["role"] not in {"vendor", "corporate"}:
        raise DomainError(403, "This workflow is restricted to organization operators", "role_forbidden")


def _parse(raw_route: str):
    parsed = urlsplit(raw_route)
    return parsed.path.rstrip("/") or "/", parse_qs(parsed.query)


def _limit(query: dict) -> int:
    try:
        return min(max(int(query.get("limit", [100])[0] or 100), 1), 500)
    except (ValueError, TypeError):
        return 100


def _feature_list(conn, table: str, org: str, order: str = "created_at DESC", limit: int = 100):
    rows = conn.execute(f"SELECT * FROM {table} WHERE organization_id = ? ORDER BY {order} LIMIT ?", (org, limit)).fetchall()
    return [_serialize(row) for row in rows]


def _feature_item(conn, table: str, entity_id: str, org: str):
    row = _assert_owned(conn, table, entity_id, org)
    return _serialize(row)


def _json_body(payload, key, default):
    value = payload.get(key, default)
    return value if isinstance(value, (dict, list)) else default


DEFAULT_MANUFACTURERS = [
    ("Maruti Suzuki", "MSUZ", "India / Japan"),
    ("Suzuki", "SUZ", "Japan"),
    ("Toyota", "TOY", "Japan"),
    ("Hyundai", "HYU", "South Korea"),
    ("Tata Motors", "TATA", "India"),
    ("Mahindra", "MAH", "India"),
    ("Honda", "HON", "Japan"),
    ("Kia", "KIA", "South Korea"),
    ("MG Motor", "MG", "UK / China"),
    ("BYD", "BYD", "China"),
    ("Volkswagen", "VW", "Germany"),
    ("Skoda", "SKO", "Czech Republic"),
    ("Force Motors", "FRC", "India"),
    ("Mercedes-Benz", "MB", "Germany"),
    ("BMW", "BMW", "Germany"),
]


def _ensure_default_manufacturers(conn, org: str) -> None:
    count = conn.execute("SELECT COUNT(*) n FROM domain_manufacturers WHERE organization_id = ?", (org,)).fetchone()["n"]
    if count == 0:
        now = now_iso()
        for name, code, country in DEFAULT_MANUFACTURERS:
            conn.execute(
                "INSERT OR IGNORE INTO domain_manufacturers(id, organization_id, code, name, country, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'active', ?, ?)",
                (new_id("mfr"), org, code, name, country, now, now),
            )


def _create_manufacturer(conn, user, payload, ip):
    org = _feature_org(user); _staff(user)
    name = _text(payload, "name", maximum=160)
    if not name: raise DomainError(400, "Manufacturer name is required", "validation_error")
    code = _text(payload, "code", maximum=24).upper() or uuid.uuid4().hex[:6].upper()
    country = _text(payload, "country", maximum=80)
    status = _text(payload, "status", "active", maximum=20)
    existing = conn.execute("SELECT id FROM domain_manufacturers WHERE organization_id = ? AND lower(name) = lower(?)", (org, name)).fetchone()
    if existing:
        raise DomainError(409, "A manufacturer with this name already exists", "duplicate_manufacturer")
    now = now_iso(); m_id = new_id("mfr")
    conn.execute("INSERT INTO domain_manufacturers(id, organization_id, code, name, country, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (m_id, org, code, name, country, status, now, now))
    _audit(conn, user, "manufacturer.created", "manufacturer", m_id, ip, {"name": name, "code": code})
    return {"ok": True, "item": _feature_item(conn, "domain_manufacturers", m_id, org)}


def _create_branch(conn, user, payload, ip):
    org = _feature_org(user); _staff(user)
    code = _text(payload, "code", maximum=24).upper() or uuid.uuid4().hex[:6].upper()
    name = _text(payload, "name", maximum=160)
    if not name: raise DomainError(400, "Branch name is required", "validation_error")
    now = now_iso(); branch_id = new_id("branch")
    conn.execute("INSERT INTO domain_branches(id, organization_id, code, name, city, address_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (branch_id, org, code, name, _text(payload, "city", maximum=80), json.dumps(_json_body(payload, "address", {})), now, now))
    _audit(conn, user, "branch.created", "branch", branch_id, ip, {"code": code})
    return {"ok": True, "item": _feature_item(conn, "domain_branches", branch_id, org)}


def _create_supplier(conn, user, payload, ip):
    org = _feature_org(user); _staff(user)
    name = _text(payload, "name", maximum=160)
    if not name: raise DomainError(400, "Supplier name is required", "validation_error")
    supplier_id = new_id("supplier"); now = now_iso()
    conn.execute("INSERT INTO domain_suppliers(id, organization_id, name, supplier_type, email, phone, gstin, cities_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (supplier_id, org, name, _text(payload, "supplier_type", "company", maximum=40), _text(payload, "email"), _text(payload, "phone"), _text(payload, "gstin").upper(), json.dumps(_json_body(payload, "cities", [])), now, now))
    _audit(conn, user, "supplier.created", "supplier", supplier_id, ip, {})
    return {"ok": True, "item": _feature_item(conn, "domain_suppliers", supplier_id, org)}


def _create_price_book(conn, user, payload, ip):
    org = _feature_org(user); _staff(user)
    name = _text(payload, "name", maximum=160)
    if not name: raise DomainError(400, "Price book name is required", "validation_error")
    price_book_id = new_id("pricebook"); now = now_iso()
    conn.execute("INSERT INTO domain_price_books(id, organization_id, branch_id, name, effective_from, effective_to, status, version, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (price_book_id, org, _text(payload, "branch_id") or None, name, _text(payload, "effective_from") or now[:10], _text(payload, "effective_to") or None, _text(payload, "status", "draft", maximum=20), 1, user["id"], now, now))
    for item in payload.get("items", []) if isinstance(payload.get("items"), list) else []:
        _create_price_item(conn, user, price_book_id, item, ip, audit=False)
    _audit(conn, user, "price_book.created", "price_book", price_book_id, ip, {})
    result = _feature_item(conn, "domain_price_books", price_book_id, org)
    result["items"] = [_serialize(row, ("rules_json",)) for row in conn.execute("SELECT * FROM domain_price_book_items WHERE price_book_id = ? ORDER BY created_at", (price_book_id,)).fetchall()]
    return {"ok": True, "item": result}


def _create_price_item(conn, user, price_book_id, payload, ip, audit=True):
    org = _feature_org(user); _staff(user)
    book = _assert_owned(conn, "domain_price_books", price_book_id, org)
    item_id = new_id("priceitem"); now = now_iso()
    values = (item_id, price_book_id, _text(payload, "duty_type", "local", maximum=40), _text(payload, "vehicle_group", maximum=60), int(payload.get("base_paise") or 0), int(payload.get("per_km_paise") or 0), int(payload.get("per_hour_paise") or 0), int(payload.get("waiting_paise") or 0), int(payload.get("tax_rate_bps") or 0), json.dumps(_json_body(payload, "rules", {})), now)
    if any(value < 0 for value in values[4:9]) or values[8] > 10000: raise DomainError(400, "Price values are invalid", "validation_error")
    conn.execute("INSERT INTO domain_price_book_items(id, price_book_id, duty_type, vehicle_group, base_paise, per_km_paise, per_hour_paise, waiting_paise, tax_rate_bps, rules_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
    if audit: _audit(conn, user, "price_item.created", "price_book_item", item_id, ip, {"price_book_id": book["id"]})
    return _serialize(conn.execute("SELECT * FROM domain_price_book_items WHERE id = ?", (item_id,)).fetchone(), ("rules_json",))


def _create_document(conn, user, payload, ip):
    org = _feature_org(user)
    entity_type = _text(payload, "entity_type", maximum=40)
    entity_id = _text(payload, "entity_id", maximum=160)
    document_type = _text(payload, "document_type", maximum=60)
    if not entity_type or not entity_id or not document_type: raise DomainError(400, "Document entity and type are required", "validation_error")
    file_name = _text(payload, "file_name", maximum=200) or "attachment"
    provider = DEFAULT_PROVIDERS.storage.register_attachment(organization_id=org, entity_type=entity_type, entity_id=entity_id, filename=file_name, content_type=_text(payload, "content_type", "application/octet-stream", maximum=100), size_bytes=int(payload.get("size_bytes") or 0))
    document_id = new_id("doc"); now = now_iso()
    conn.execute("INSERT INTO domain_documents(id, organization_id, entity_type, entity_id, document_type, file_name, storage_path, status, expires_at, metadata_json, uploaded_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (document_id, org, entity_type, entity_id, document_type, file_name, provider.reference, _text(payload, "status", "pending_review", maximum=30), _text(payload, "expires_at", maximum=40) or None, json.dumps({**_json_body(payload, "metadata", {}), "provider": provider.payload}), user["id"], now, now))
    _audit(conn, user, "document.uploaded", "document", document_id, ip, {"entity_type": entity_type, "entity_id": entity_id})
    return {"ok": True, "item": _feature_item(conn, "domain_documents", document_id, org)}


def _create_invitation(conn, user, payload, ip):
    org = _feature_org(user); _staff(user)
    email = _text(payload, "email", maximum=254).lower()
    role = _text(payload, "role", "driver", maximum=30)
    if not email or role not in {"driver", "corporate", "vendor_ops", "vendor_finance", "corporate_travel"}: raise DomainError(400, "A valid invitation email and role are required", "validation_error")
    try: expires_days = int(payload.get("expires_days") or 7)
    except (TypeError, ValueError) as exc: raise DomainError(400, "Invitation expiry must be a whole number of days", "validation_error") from exc
    if expires_days < 1 or expires_days > 30: raise DomainError(400, "Invitation expiry must be between 1 and 30 days", "validation_error")
    raw_token = uuid.uuid4().hex + uuid.uuid4().hex
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest(); now = datetime.now(timezone.utc); expires = (now + timedelta(days=expires_days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    invitation_id = new_id("invite")
    conn.execute("INSERT INTO domain_invitations(id, organization_id, email, role, token_hash, expires_at, invited_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (invitation_id, org, email, role, token_hash, expires, user["id"], now_iso()))
    message = DEFAULT_PROVIDERS.messaging.send(channel="email", recipient=email, template="organization_invitation", variables={"role": role, "expires_at": expires}, idempotency_key=invitation_id)
    _audit(conn, user, "invitation.created", "invitation", invitation_id, ip, {"email": email, "role": role})
    return {"ok": True, "item": {**_feature_item(conn, "domain_invitations", invitation_id, org), "invite_token": raw_token, "message_reference": message.reference}}


def _accept_invitation(conn, user, payload, ip):
    raw_token = _text(payload, "token", maximum=200)
    row = conn.execute("SELECT * FROM domain_invitations WHERE token_hash = ? AND status = 'pending'", (hashlib.sha256(raw_token.encode()).hexdigest(),)).fetchone()
    if row is None: raise DomainError(404, "Invitation is invalid or already used", "invitation_not_found")
    if row["expires_at"] <= now_iso(): raise DomainError(410, "Invitation has expired", "invitation_expired")
    if user["email"].lower() != row["email"].lower(): raise DomainError(403, "Sign in with the invited email address", "invitation_email_mismatch")
    conn.execute("UPDATE users SET organization_id = ? WHERE id = ?", (row["organization_id"], user["id"]))
    conn.execute("UPDATE domain_invitations SET status = 'accepted', accepted_by = ?, accepted_at = ? WHERE id = ?", (user["id"], now_iso(), row["id"]))
    if user["role"] == "driver":
        existing = conn.execute("SELECT id FROM domain_drivers WHERE user_id = ?", (user["id"],)).fetchone()
        if not existing:
            conn.execute("INSERT INTO domain_drivers(id, organization_id, user_id, full_name, phone, city, status, created_at, updated_at) SELECT ?, ?, id, full_name, phone, '', 'available', ?, ? FROM users WHERE id = ?", (new_id("drv"), row["organization_id"], now_iso(), now_iso(), user["id"]))
    _audit(conn, user, "invitation.accepted", "invitation", row["id"], ip, {})
    return {"ok": True, "organization_id": row["organization_id"], "role": row["role"]}


def _create_employee(conn, user, payload, ip):
    org = _feature_org(user); _staff(user)
    full_name = _text(payload, "full_name", maximum=120)
    if not full_name: raise DomainError(400, "Employee name is required", "validation_error")
    employee_id = new_id("employee"); now = now_iso()
    code = _text(payload, "employee_code", maximum=50) or f"EMP-{conn.execute('SELECT COUNT(*) + 1 AS n FROM domain_employees WHERE organization_id = ?', (org,)).fetchone()['n']:04d}"
    conn.execute("INSERT INTO domain_employees(id, organization_id, employee_code, full_name, email, phone, department, cost_center, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (employee_id, org, code, full_name, _text(payload, "email"), _text(payload, "phone"), _text(payload, "department"), _text(payload, "cost_center"), now, now))
    _audit(conn, user, "employee.created", "employee", employee_id, ip, {"employee_code": code})
    return {"ok": True, "item": _feature_item(conn, "domain_employees", employee_id, org)}


def _import_employees(conn, user, payload, ip):
    employees = payload.get("employees") if isinstance(payload.get("employees"), list) else []
    if not employees or len(employees) > 5000: raise DomainError(400, "Provide between 1 and 5,000 employee rows", "validation_error")
    results = []; imported = 0
    for index, employee in enumerate(employees, start=1):
        try:
            result = _create_employee(conn, user, employee if isinstance(employee, dict) else {}, ip)
            imported += 1; results.append({"row": index, "status": "imported", "item": result["item"]})
        except DomainError as exc:
            results.append({"row": index, "status": "error", "code": exc.code, "error": exc.message})
    return {"ok": True, "imported": imported, "failed": len(results) - imported, "rows": results}


def _import_bookings(conn, user, payload, ip):
    bookings = payload.get("bookings") if isinstance(payload.get("bookings"), list) else []
    if not bookings or len(bookings) > 1000:
        raise DomainError(400, "Provide between 1 and 1,000 booking rows", "validation_error")
    rows = []; imported = 0
    for index, booking in enumerate(bookings, start=1):
        try:
            result = _create_booking(conn, user, booking if isinstance(booking, dict) else {}, ip)
            imported += 1; rows.append({"row": index, "status": "imported", "item": result["item"]})
        except DomainError as exc:
            rows.append({"row": index, "status": "error", "code": exc.code, "error": exc.message})
    return {"ok": True, "imported": imported, "failed": len(rows) - imported, "rows": rows}


def _create_policy(conn, user, payload, ip):
    org = _feature_org(user); _staff(user)
    policy_id = new_id("policy"); now = now_iso(); name = _text(payload, "name", maximum=160)
    if not name: raise DomainError(400, "Policy name is required", "validation_error")
    conn.execute("INSERT INTO domain_policies(id, organization_id, name, status, rules_json, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (policy_id, org, name, _text(payload, "status", "draft", maximum=20), json.dumps(_json_body(payload, "rules", {})), user["id"], now, now))
    _audit(conn, user, "policy.created", "policy", policy_id, ip, {})
    return {"ok": True, "item": _feature_item(conn, "domain_policies", policy_id, org)}


def _booking_action(conn, user, booking_id, action, payload, ip):
    org = _feature_org(user); _staff(user)
    booking = _assert_owned(conn, "domain_bookings", booking_id, org); now = now_iso()
    transitions = {"approve": "approved", "confirm": "confirmed", "reject": "disputed", "cancel": "cancelled"}
    if action == "assign":
        driver_id = payload.get("driver_id") or None
        vehicle_id = payload.get("vehicle_id") or None
        supplier_id = payload.get("supplier_id") or None
        existing = conn.execute("SELECT id FROM domain_duties WHERE booking_id = ? AND organization_id = ? ORDER BY created_at DESC LIMIT 1", (booking_id, org)).fetchone()
        duty_status = "assigned" if (driver_id or vehicle_id or supplier_id) else "draft"
        duty_payload = {"driver_id": driver_id, "vehicle_id": vehicle_id, "supplier_id": supplier_id, "status": duty_status}
        if payload.get("reporting_at"):
            duty_payload["reporting_at"] = payload["reporting_at"]
        if existing:
            from backend_domain import _update_duty
            result = _update_duty(conn, user, existing["id"], duty_payload, ip)
        else:
            duty_payload["booking_id"] = booking_id
            result = _create_duty(conn, user, duty_payload, ip)
        booking_status = "assigned" if (driver_id and vehicle_id and supplier_id) else "confirmed" if (driver_id or vehicle_id or supplier_id) else "requested"
        booking_cols = {row["name"] for row in conn.execute("PRAGMA table_info(domain_bookings)").fetchall()}
        booking_updates = ["status = ?", "updated_at = ?"]
        booking_params = [booking_status, now]
        if "driver_id" in booking_cols:
            booking_updates.append("driver_id = ?")
            booking_params.append(driver_id)
        if "vehicle_id" in booking_cols:
            booking_updates.append("vehicle_id = ?")
            booking_params.append(vehicle_id)
        if "supplier_id" in booking_cols:
            booking_updates.append("supplier_id = ?")
            booking_params.append(supplier_id)
        if "driver_name" in booking_cols:
            d_name = None
            if driver_id:
                d_row = conn.execute("SELECT full_name FROM domain_drivers WHERE id = ? AND organization_id = ?", (driver_id, org)).fetchone()
                d_name = d_row["full_name"] if d_row else None
            booking_updates.append("driver_name = ?")
            booking_params.append(d_name)
        if "vehicle_number" in booking_cols:
            v_num = None
            if vehicle_id:
                v_row = conn.execute("SELECT registration_number FROM domain_vehicles WHERE id = ? AND organization_id = ?", (vehicle_id, org)).fetchone()
                v_num = v_row["registration_number"] if v_row else None
            booking_updates.append("vehicle_number = ?")
            booking_params.append(v_num)
        if "supplier_name" in booking_cols:
            s_name = None
            if supplier_id:
                s_row = conn.execute("SELECT name FROM domain_suppliers WHERE id = ? AND organization_id = ?", (supplier_id, org)).fetchone()
                s_name = s_row["name"] if s_row else None
            booking_updates.append("supplier_name = ?")
            booking_params.append(s_name)
        booking_params.append(booking_id)
        booking_params.append(org)
        conn.execute(f"UPDATE domain_bookings SET {', '.join(booking_updates)} WHERE id = ? AND organization_id = ?", booking_params)
        return {"ok": True, "booking": _serialize(conn.execute("SELECT * FROM domain_bookings WHERE id = ?", (booking_id,)).fetchone()), "duty": result["item"]}
    if action not in transitions: raise DomainError(404, "Booking action not found", "not_found")
    next_status = transitions[action]
    conn.execute("UPDATE domain_bookings SET status = ?, updated_at = ? WHERE id = ? AND organization_id = ?", (next_status, now, booking_id, org))
    approval_status = "approved" if action in {"approve", "confirm"} else "rejected" if action == "reject" else "cancelled"
    pending_corporate = conn.execute("SELECT id FROM domain_booking_approvals WHERE organization_id = ? AND booking_id = ? AND approver_id IS NULL AND status = 'pending' ORDER BY created_at ASC LIMIT 1", (org, booking_id)).fetchone()
    if pending_corporate:
        conn.execute("UPDATE domain_booking_approvals SET approver_id = ?, status = ?, comment = ?, updated_at = ? WHERE id = ?", (user["id"], approval_status, _text(payload, "comment"), now, pending_corporate["id"]))
    else:
        conn.execute("INSERT INTO domain_booking_approvals(id, organization_id, booking_id, approver_id, status, comment, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(organization_id, booking_id, approver_id) DO UPDATE SET status = excluded.status, comment = excluded.comment, updated_at = excluded.updated_at", (new_id("approval"), org, booking_id, user["id"], approval_status, _text(payload, "comment"), now, now))
    _audit(conn, user, f"booking.{action}", "booking", booking_id, ip, {"status": next_status})
    return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_bookings WHERE id = ?", (booking_id,)).fetchone()), "status": next_status}


def _send_notification(conn, user, payload, ip):
    org = _feature_org(user)
    recipient_id = _text(payload, "recipient_id") or None
    channel = _text(payload, "channel", "email", maximum=20)
    template = _text(payload, "template_key", "operational_update", maximum=80)
    recipient = _text(payload, "recipient", "operations@axiomfleet.local", maximum=254)
    message = DEFAULT_PROVIDERS.messaging.send(channel=channel, recipient=recipient, template=template, variables=_json_body(payload, "variables", {}), idempotency_key=_text(payload, "idempotency_key") or None)
    notification_id = new_id("notification"); now = now_iso()
    status = "sent" if message.status in {"queued", "succeeded"} else "failed"
    conn.execute("INSERT INTO domain_notifications(id, organization_id, recipient_id, channel, template_key, status, provider_reference, payload_json, created_at, delivered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (notification_id, org, recipient_id, channel, template, status, message.reference, json.dumps(message.payload), now, now if status == "sent" else None))
    _audit(conn, user, "notification.sent", "notification", notification_id, ip, {"channel": channel, "template": template})
    return {"ok": True, "item": _feature_item(conn, "domain_notifications", notification_id, org)}


def _invoice_einvoice(conn, user, invoice_id, payload, ip):
    org = _feature_org(user); _staff(user)
    invoice = _assert_owned(conn, "domain_invoices", invoice_id, org)
    existing = conn.execute("SELECT * FROM domain_einvoice_records WHERE organization_id = ? AND invoice_id = ?", (org, invoice_id)).fetchone()
    if existing:
        return {"ok": True, "item": _serialize(existing, ("payload_json",)), "idempotent": True}
    result = DEFAULT_PROVIDERS.einvoice.issue(invoice_number=invoice["invoice_number"], total_paise=invoice["total_paise"], idempotency_key=_text(payload, "idempotency_key") or invoice_id)
    record_id = new_id("einvoice"); now = now_iso()
    conn.execute("INSERT INTO domain_einvoice_records(id, organization_id, invoice_id, provider, status, irn, qr_payload, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (record_id, org, invoice_id, result.provider, result.status, result.reference, result.payload.get("qr_payload", ""), json.dumps(result.payload), now))
    _audit(conn, user, "invoice.einvoice_issued", "invoice", invoice_id, ip, {"irn": result.reference})
    return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_einvoice_records WHERE id = ?", (record_id,)).fetchone(), ("payload_json",))}


def _dispatch_invoice(conn, user, invoice_id, payload, ip):
    org = _feature_org(user); _staff(user)
    invoice = _assert_owned(conn, "domain_invoices", invoice_id, org)
    channel = _text(payload, "channel", "email", maximum=20)
    recipient = _text(payload, "recipient", "finance@customer.local", maximum=254)
    result = DEFAULT_PROVIDERS.messaging.send(channel=channel, recipient=recipient, template="invoice_dispatch", variables={"invoice_number": invoice["invoice_number"], "total_paise": invoice["total_paise"]}, idempotency_key=_text(payload, "idempotency_key") or f"dispatch:{invoice_id}:{channel}")
    action_id = new_id("collection"); now = now_iso()
    conn.execute("INSERT INTO domain_collection_actions(id, organization_id, invoice_id, action_type, channel, status, provider_reference, scheduled_at, created_at) VALUES (?, ?, ?, 'dispatch', ?, ?, ?, ?, ?)", (action_id, org, invoice_id, channel, result.status, result.reference, _text(payload, "scheduled_at") or now, now))
    conn.execute("INSERT INTO domain_notifications(id, organization_id, channel, template_key, status, provider_reference, payload_json, created_at, delivered_at) VALUES (?, ?, ?, 'invoice_dispatch', ?, ?, ?, ?, ?)", (new_id("notification"), org, channel, result.status, result.reference, json.dumps(result.payload), now, now if result.status == "queued" else None))
    _audit(conn, user, "invoice.dispatched", "invoice", invoice_id, ip, {"channel": channel, "provider_reference": result.reference})
    return {"ok": True, "invoice": _serialize(invoice), "dispatch": {"status": result.status, "reference": result.reference, "action_id": action_id}}


def _report_summary(conn, user, query):
    org = _feature_org(user)
    duties = conn.execute("SELECT status, COUNT(*) count FROM domain_duties WHERE organization_id = ? GROUP BY status", (org,)).fetchall()
    invoices = conn.execute("SELECT status, COUNT(*) count, COALESCE(SUM(total_paise),0) total_paise FROM domain_invoices WHERE organization_id = ? GROUP BY status", (org,)).fetchall()
    customers = conn.execute("SELECT COUNT(*) count FROM domain_customers WHERE organization_id = ? AND status = 'active'", (org,)).fetchone()["count"]
    drivers = conn.execute("SELECT status, COUNT(*) count FROM domain_drivers WHERE organization_id = ? GROUP BY status", (org,)).fetchall()
    payments = conn.execute("SELECT COUNT(*) count, COALESCE(SUM(amount_paise),0) total_paise FROM domain_payments WHERE organization_id = ? AND status = 'succeeded'", (org,)).fetchone()
    return {"ok": True, "period": query.get("period", ["current"])[0], "summary": {"customers": customers, "duties": {row["status"]: row["count"] for row in duties}, "drivers": {row["status"]: row["count"] for row in drivers}, "invoices": {row["status"]: {"count": row["count"], "total_paise": row["total_paise"]} for row in invoices}, "payments": {"count": payments["count"], "total_paise": payments["total_paise"]}}}


def _create_ticket(conn, user, payload, ip):
    org = _feature_org(user); subject = _text(payload, "subject", maximum=200)
    if not subject: raise DomainError(400, "Ticket subject is required", "validation_error")
    ticket_id = new_id("ticket"); now = now_iso()
    conn.execute("INSERT INTO domain_tickets(id, organization_id, opened_by, subject, description, priority, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (ticket_id, org, user["id"], subject, _text(payload, "description", maximum=5000), _text(payload, "priority", "normal", maximum=20), now, now))
    _audit(conn, user, "ticket.created", "ticket", ticket_id, ip, {})
    return {"ok": True, "item": _feature_item(conn, "domain_tickets", ticket_id, org)}


def _create_privacy_request(conn, user, payload, ip):
    org = _feature_org(user); request_type = _text(payload, "request_type", maximum=30)
    if request_type not in {"access", "correction", "deletion", "export", "withdraw_consent"}: raise DomainError(400, "Unsupported privacy request", "validation_error")
    request_id = new_id("privacy"); now = now_iso()
    conn.execute("INSERT INTO domain_privacy_requests(id, organization_id, requester_id, request_type, notes, created_at) VALUES (?, ?, ?, ?, ?, ?)", (request_id, org, user["id"], request_type, _text(payload, "notes", maximum=2000), now))
    _audit(conn, user, "privacy.requested", "privacy_request", request_id, ip, {"request_type": request_type})
    return {"ok": True, "item": _feature_item(conn, "domain_privacy_requests", request_id, org)}


def handle_feature(conn, user, method: str, raw_route: str, payload: dict, ip: str):
    route, query = _parse(raw_route)
    if not route.startswith(FEATURE_PREFIXES):
        return None
    org = user["organization_id"] if route in {"/api/invitations/accept", "/api/integrations"} and (route == "/api/invitations/accept" or method == "GET") else _feature_org(user)
    limit = _limit(query)

    if route == "/api/organization/checklist" and method == "GET":
        counts = {
            "branch": conn.execute("SELECT COUNT(*) n FROM domain_branches WHERE organization_id = ?", (org,)).fetchone()["n"],
            "customer": conn.execute("SELECT COUNT(*) n FROM domain_customers WHERE organization_id = ?", (org,)).fetchone()["n"],
            "driver": conn.execute("SELECT COUNT(*) n FROM domain_drivers WHERE organization_id = ?", (org,)).fetchone()["n"],
            "vehicle": conn.execute("SELECT COUNT(*) n FROM domain_vehicles WHERE organization_id = ?", (org,)).fetchone()["n"],
            "price_book": conn.execute("SELECT COUNT(*) n FROM domain_price_books WHERE organization_id = ? AND status = 'active'", (org,)).fetchone()["n"],
            "booking": conn.execute("SELECT COUNT(*) n FROM domain_bookings WHERE organization_id = ?", (org,)).fetchone()["n"],
        }
        items = [{"key": key, "label": label, "complete": counts[key] > 0} for key, label in (("branch", "Add a branch"), ("customer", "Add a customer"), ("driver", "Add a driver"), ("vehicle", "Add a vehicle"), ("price_book", "Publish a price book"), ("booking", "Create the first booking"))]
        return {"ok": True, "completed": sum(item["complete"] for item in items), "total": len(items), "items": items}
    if route == "/api/organization" and method == "GET":
        row = conn.execute("SELECT * FROM organizations WHERE id = ?", (org,)).fetchone()
        return {"ok": True, "item": _serialize(row)}
    if route == "/api/settings" and method == "GET":
        row = conn.execute("SELECT * FROM domain_org_settings WHERE organization_id = ?", (org,)).fetchone()
        return {"ok": True, "item": {"organization_id": org, "settings": _json(row["settings_json"], {}) if row else {}}}
    if route == "/api/settings" and method == "PATCH":
        _staff(user); now = now_iso(); current = conn.execute("SELECT settings_json FROM domain_org_settings WHERE organization_id = ?", (org,)).fetchone(); settings = _json(current["settings_json"], {}) if current else {}
        settings.update(_json_body(payload, "settings", payload)); conn.execute("INSERT INTO domain_org_settings(organization_id, settings_json, updated_by, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT(organization_id) DO UPDATE SET settings_json = excluded.settings_json, updated_by = excluded.updated_by, updated_at = excluded.updated_at", (org, json.dumps(settings), user["id"], now)); _audit(conn, user, "settings.updated", "organization", org, ip, {"keys": sorted(settings.keys())}); return {"ok": True, "item": {"organization_id": org, "settings": settings}}

    collections = {
        "/api/branches": ("domain_branches", "created_at DESC"),
        "/api/manufacturers": ("domain_manufacturers", "name ASC"),
        "/api/suppliers": ("domain_suppliers", "created_at DESC"),
        "/api/price-books": ("domain_price_books", "created_at DESC"),
        "/api/employees": ("domain_employees", "created_at DESC"),
        "/api/policies": ("domain_policies", "created_at DESC"),
        "/api/tickets": ("domain_tickets", "created_at DESC"),
        "/api/documents": ("domain_documents", "created_at DESC"),
        "/api/invitations": ("domain_invitations", "created_at DESC"),
        "/api/notifications": ("domain_notifications", "created_at DESC"),
        "/api/approvals": ("domain_booking_approvals", "created_at DESC"),
        "/api/privacy/requests": ("domain_privacy_requests", "created_at DESC"),
    }
    if route in collections and method == "GET":
        table, order = collections[route]
        if table == "domain_manufacturers":
            _ensure_default_manufacturers(conn, org)
        items = _feature_list(conn, table, org, order, limit)
        for item in items:
            for field in ("address_json", "cities_json", "rules_json", "metadata_json", "payload_json"):
                if field in item: item[field[:-5] if field.endswith("_json") else field] = _json(item.pop(field), {})
        return {"ok": True, "items": items, "count": len(items)}
    if route == "/api/branches" and method == "POST": return _create_branch(conn, user, payload, ip)
    if route == "/api/manufacturers" and method == "POST": return _create_manufacturer(conn, user, payload, ip)
    if route == "/api/bookings/import" and method == "POST": return _import_bookings(conn, user, payload, ip)
    if route == "/api/suppliers" and method == "POST": return _create_supplier(conn, user, payload, ip)
    if route == "/api/price-books" and method == "POST": return _create_price_book(conn, user, payload, ip)
    if route == "/api/employees" and method == "POST": return _create_employee(conn, user, payload, ip)
    if route == "/api/employees/import" and method == "POST": return _import_employees(conn, user, payload, ip)
    if route == "/api/policies" and method == "POST": return _create_policy(conn, user, payload, ip)
    if route == "/api/documents" and method == "POST": return _create_document(conn, user, payload, ip)
    if route == "/api/invitations" and method == "POST": return _create_invitation(conn, user, payload, ip)
    if route == "/api/invitations/accept" and method == "POST": return _accept_invitation(conn, user, payload, ip)
    if route == "/api/notifications" and method == "POST": return _send_notification(conn, user, payload, ip)
    if route == "/api/tickets" and method == "POST": return _create_ticket(conn, user, payload, ip)
    if route == "/api/privacy/requests" and method == "POST": return _create_privacy_request(conn, user, payload, ip)
    if route == "/api/integrations" and method == "GET":
        return {"ok": True, "items": [{"key": key, "provider": name, "mode": "mock", "status": "available", "credentials_configured": False} for key, name in (("payments", "Mock Payment"), ("messaging", "Mock Messaging"), ("telephony", "Mock Telephony"), ("maps", "Mock Maps"), ("einvoice", "Mock E-Invoice"), ("storage", "Mock Storage"))]}
    if route == "/api/integrations/test" and method == "POST":
        _staff(user); provider = _text(payload, "provider", "messaging", maximum=30)
        if provider == "payments": result = DEFAULT_PROVIDERS.payments.create_payment(amount_paise=100, idempotency_key=new_id("test"))
        elif provider == "maps": result = DEFAULT_PROVIDERS.maps.geocode(_text(payload, "query", "Mumbai Airport"))
        elif provider == "telephony": result = DEFAULT_PROVIDERS.telephony.create_masked_call(from_number="mock", to_number="mock", context="integration-test")
        elif provider == "einvoice": result = DEFAULT_PROVIDERS.einvoice.issue(invoice_number="TEST", total_paise=100)
        else: result = DEFAULT_PROVIDERS.messaging.send(channel="email", recipient="test@axiomfleet.local", template="integration_test")
        _audit(conn, user, "integration.tested", "integration", provider, ip, {"reference": result.reference}); return {"ok": True, "provider": provider, "result": {"status": result.status, "reference": result.reference, "payload": result.payload}}
    if route == "/api/reports/summary" and method == "GET": return _report_summary(conn, user, query)
    if route == "/api/audit" and method == "GET":
        rows = conn.execute("SELECT * FROM audit_events WHERE user_id IN (SELECT id FROM users WHERE organization_id = ?) ORDER BY created_at DESC LIMIT ?", (org, limit)).fetchall()
        return {"ok": True, "items": [_serialize(row, ("metadata_json",)) for row in rows], "count": len(rows)}

    parts = route.split("?")[0].split("/")
    if len(parts) >= 4:
        resource, entity_id = parts[2], parts[3]
        if resource == "invoices" and len(parts) == 5 and parts[4] == "e-invoice" and method == "POST": return _invoice_einvoice(conn, user, entity_id, payload, ip)
        if resource == "invoices" and len(parts) == 5 and parts[4] == "dispatch" and method == "POST": return _dispatch_invoice(conn, user, entity_id, payload, ip)
        if resource == "invoices" and len(parts) == 5 and parts[4] == "e-invoice" and method == "GET":
            _feature_org(user); row = conn.execute("SELECT * FROM domain_einvoice_records WHERE organization_id = ? AND invoice_id = ?", (org, entity_id)).fetchone(); return {"ok": True, "item": _serialize(row, ("payload_json",)) if row else None}
        if resource == "price-books" and method == "GET":
            book = _feature_item(conn, "domain_price_books", entity_id, org); book["items"] = [_serialize(row, ("rules_json",)) for row in conn.execute("SELECT * FROM domain_price_book_items WHERE price_book_id = ? ORDER BY created_at", (entity_id,)).fetchall()]; return {"ok": True, "item": book}
        if resource == "price-books" and len(parts) == 5 and parts[4] == "items" and method == "POST": return {"ok": True, "item": _create_price_item(conn, user, entity_id, payload, ip)}
        if resource == "bookings" and len(parts) == 5 and parts[4] in {"approve", "confirm", "reject", "cancel", "assign"} and method == "POST": return _booking_action(conn, user, entity_id, parts[4], payload, ip)
        if resource == "notifications" and len(parts) == 5 and parts[4] == "read" and method == "POST":
            _staff(user); _assert_owned(conn, "domain_notifications", entity_id, org); conn.execute("UPDATE domain_notifications SET read_at = ? WHERE id = ?", (now_iso(), entity_id)); return {"ok": True, "item": _feature_item(conn, "domain_notifications", entity_id, org)}
        if resource == "tickets" and method == "PATCH":
            _staff(user); _assert_owned(conn, "domain_tickets", entity_id, org); allowed = {"status", "priority", "assignee_id"}; updates = [(key, payload[key]) for key in allowed if key in payload]; updates.append(("updated_at", now_iso())); conn.execute(f"UPDATE domain_tickets SET {', '.join(f'{key} = ?' for key, _ in updates)} WHERE id = ?", [value for _, value in updates] + [entity_id]); _audit(conn, user, "ticket.updated", "ticket", entity_id, ip, {key: value for key, value in updates}); return {"ok": True, "item": _feature_item(conn, "domain_tickets", entity_id, org)}
    return None
