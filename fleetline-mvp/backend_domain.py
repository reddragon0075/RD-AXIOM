"""SQLite domain store for the local One Fleet Live backend slice."""

from __future__ import annotations

import json
import math
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from domain_engine import CalculationError, calculate_duty
from provider_adapters import DEFAULT_PROVIDERS


MAX_EXPENSE_PAISE = 100_000_000
EXPENSE_CATEGORIES = {"parking", "toll", "fuel", "other"}
MAX_PROOF_NOTE_LENGTH = 500


class DomainError(Exception):
    def __init__(self, status: int, message: str, code: str = "domain_error", details=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code
        self.details = details


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _derive_corp_code(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9\s]", " ", name or "").strip()
    words = cleaned.split()
    if len(words) >= 2:
        code = "".join(w[0] for w in words if w).upper()
        return code[:6]
    elif len(words) == 1:
        w = words[0].upper()
        return w[:4] if len(w) >= 3 else w
    return "TRIP"


def _generate_trip_id(conn, org: str, corp_code: str) -> str:
    corp_code = re.sub(r"[^A-Za-z0-9]", "", corp_code or "").strip().upper()
    if not corp_code:
        corp_code = "TRIP"
    prefix = corp_code
    rows = conn.execute(
        "SELECT id FROM domain_duties WHERE organization_id = ? AND id LIKE ?",
        (org, f"{prefix}%")
    ).fetchall()
    max_seq = 0
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    for r in rows:
        duty_id = str(r["id"] or "")
        match = pattern.match(duty_id)
        if match:
            try:
                seq = int(match.group(1))
                if seq > max_seq:
                    max_seq = seq
            except ValueError:
                pass
    next_seq = max_seq + 1
    return f"{prefix}{next_seq:04d}"


def initialize_domain_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS domain_customers (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            name TEXT NOT NULL,
            email TEXT NOT NULL DEFAULT '',
            phone TEXT NOT NULL DEFAULT '',
            gstin TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_drivers (
            id TEXT PRIMARY KEY,
            organization_id TEXT,
            user_id TEXT,
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL DEFAULT '',
            license_number TEXT NOT NULL DEFAULT '',
            city TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'available',
            driver_type TEXT NOT NULL DEFAULT 'own',
            vehicle_registration TEXT NOT NULL DEFAULT '',
            vehicle_group TEXT NOT NULL DEFAULT '',
            license_expiry TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_vehicles (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            registration_number TEXT NOT NULL,
            vehicle_type TEXT NOT NULL DEFAULT 'sedan',
            vehicle_group TEXT NOT NULL DEFAULT '',
            make_model TEXT NOT NULL DEFAULT '',
            year INTEGER,
            city TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'available',
            fuel_type TEXT NOT NULL DEFAULT 'petrol',
            ev_eligible INTEGER NOT NULL DEFAULT 0,
            battery_capacity_kwh REAL,
            usable_range_km REAL,
            energy_consumption_kwh_per_km REAL,
            charging_connector TEXT NOT NULL DEFAULT '',
            charging_power_kw REAL,
            charging_status TEXT NOT NULL DEFAULT 'unknown',
            energy_price_per_kwh_minor INTEGER,
            seating_capacity INTEGER NOT NULL DEFAULT 4,
            luggage_capacity INTEGER NOT NULL DEFAULT 0,
            ownership_type TEXT NOT NULL DEFAULT 'owned',
            branch_name TEXT NOT NULL DEFAULT '',
            gps_provider TEXT NOT NULL DEFAULT '',
            rc_expiry TEXT,
            insurance_expiry TEXT,
            puc_expiry TEXT,
            notes TEXT NOT NULL DEFAULT '',
            manufacturer TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, registration_number)
        );
        CREATE TABLE IF NOT EXISTS domain_bookings (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            customer_id TEXT,
            booking_reference TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'requested',
            passenger_name TEXT NOT NULL DEFAULT '',
            passenger_phone TEXT NOT NULL DEFAULT '',
            passenger_email TEXT NOT NULL DEFAULT '',
            pickup_json TEXT NOT NULL DEFAULT '{}',
            dropoff_json TEXT NOT NULL DEFAULT '{}',
            scheduled_at TEXT,
            duty_type TEXT NOT NULL DEFAULT 'local',
            notes TEXT NOT NULL DEFAULT '',
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, booking_reference)
        );
        CREATE TABLE IF NOT EXISTS domain_duties (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            booking_id TEXT NOT NULL,
            driver_id TEXT,
            vehicle_id TEXT,
            supplier_id TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            reporting_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            start_odometer INTEGER,
            end_odometer INTEGER,
            calculation_snapshot_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_duty_events (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            duty_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'web',
            payload_json TEXT NOT NULL DEFAULT '{}',
            idempotency_key TEXT,
            event_at TEXT NOT NULL,
            created_by TEXT,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_duty_proofs (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            duty_id TEXT NOT NULL,
            proof_type TEXT NOT NULL,
            storage_path TEXT NOT NULL DEFAULT '',
            proof_json TEXT NOT NULL DEFAULT '{}',
            idempotency_key TEXT,
            captured_at TEXT NOT NULL,
            captured_by TEXT,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_track_points (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            duty_id TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            accuracy_m REAL,
            battery_pct REAL,
            source TEXT NOT NULL DEFAULT 'driver_app',
            idempotency_key TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_sync_operations (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            device_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT,
            operation TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            client_created_at TEXT,
            server_processed_at TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_expenses (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            duty_id TEXT NOT NULL,
            category TEXT NOT NULL,
            amount_paise INTEGER NOT NULL CHECK(amount_paise >= 0),
            note TEXT NOT NULL DEFAULT '',
            attachment_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'submitted',
            idempotency_key TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_invoices (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            customer_id TEXT,
            duty_id TEXT,
            invoice_number TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            subtotal_paise INTEGER NOT NULL DEFAULT 0,
            tax_paise INTEGER NOT NULL DEFAULT 0,
            total_paise INTEGER NOT NULL DEFAULT 0,
            idempotency_key TEXT,
            issued_at TEXT,
            immutable_snapshot_json TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, invoice_number)
        );
        CREATE TABLE IF NOT EXISTS domain_invoice_lines (
            id TEXT PRIMARY KEY,
            invoice_id TEXT NOT NULL,
            code TEXT NOT NULL,
            label TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            unit_paise INTEGER NOT NULL DEFAULT 0,
            amount_paise INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_payments (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            invoice_id TEXT NOT NULL,
            amount_paise INTEGER NOT NULL CHECK(amount_paise >= 0),
            mode TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'succeeded',
            gateway_reference TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT,
            received_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE INDEX IF NOT EXISTS idx_domain_customers_org ON domain_customers(organization_id, status);
        CREATE INDEX IF NOT EXISTS idx_domain_drivers_org ON domain_drivers(organization_id, status);
        CREATE INDEX IF NOT EXISTS idx_domain_drivers_user_org ON domain_drivers(user_id, organization_id);
        CREATE INDEX IF NOT EXISTS idx_domain_vehicles_org ON domain_vehicles(organization_id, status);
        CREATE INDEX IF NOT EXISTS idx_domain_bookings_org ON domain_bookings(organization_id, status, scheduled_at);
        CREATE INDEX IF NOT EXISTS idx_domain_duties_org ON domain_duties(organization_id, status, reporting_at);
        CREATE INDEX IF NOT EXISTS idx_domain_duties_driver ON domain_duties(driver_id, organization_id, status, reporting_at);
        CREATE INDEX IF NOT EXISTS idx_domain_proofs_duty ON domain_duty_proofs(duty_id, captured_at);
        CREATE INDEX IF NOT EXISTS idx_domain_track_points_duty ON domain_track_points(duty_id, recorded_at);
        CREATE INDEX IF NOT EXISTS idx_domain_sync_org_status ON domain_sync_operations(organization_id, status, created_at);
        CREATE INDEX IF NOT EXISTS idx_domain_expenses_duty ON domain_expenses(duty_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_domain_invoices_org ON domain_invoices(organization_id, status);
        """
    )
    # Additive local migrations keep existing SQLite previews usable while the
    # Supabase vehicles table remains the production source of truth.
    vehicle_columns = {row["name"] for row in conn.execute("PRAGMA table_info(domain_vehicles)").fetchall()}
    booking_columns = {row["name"] for row in conn.execute("PRAGMA table_info(domain_bookings)").fetchall()}
    customer_columns = {row["name"] for row in conn.execute("PRAGMA table_info(domain_customers)").fetchall()}
    if "code" not in customer_columns:
        conn.execute("ALTER TABLE domain_customers ADD COLUMN code TEXT NOT NULL DEFAULT ''")
    if "passenger_email" not in booking_columns:
        conn.execute("ALTER TABLE domain_bookings ADD COLUMN passenger_email TEXT NOT NULL DEFAULT ''")
    for column, definition in {
        "vehicle_group": "TEXT NOT NULL DEFAULT ''",
        "year": "INTEGER",
        "fuel_type": "TEXT NOT NULL DEFAULT 'petrol'",
        "ev_eligible": "INTEGER NOT NULL DEFAULT 0",
        "battery_capacity_kwh": "REAL",
        "usable_range_km": "REAL",
        "energy_consumption_kwh_per_km": "REAL",
        "charging_connector": "TEXT NOT NULL DEFAULT ''",
        "charging_power_kw": "REAL",
        "charging_status": "TEXT NOT NULL DEFAULT 'unknown'",
        "energy_price_per_kwh_minor": "INTEGER",
        "seating_capacity": "INTEGER NOT NULL DEFAULT 4",
        "luggage_capacity": "INTEGER NOT NULL DEFAULT 0",
        "ownership_type": "TEXT NOT NULL DEFAULT 'owned'",
        "supplier_id": "TEXT NOT NULL DEFAULT ''",
        "supplier_name": "TEXT NOT NULL DEFAULT ''",
        "owner_name": "TEXT NOT NULL DEFAULT ''",
        "branch_name": "TEXT NOT NULL DEFAULT ''",
        "gps_provider": "TEXT NOT NULL DEFAULT ''",
        "rc_expiry": "TEXT",
        "insurance_expiry": "TEXT",
        "puc_expiry": "TEXT",
        "notes": "TEXT NOT NULL DEFAULT ''",
        "manufacturer": "TEXT NOT NULL DEFAULT ''",
        "model": "TEXT NOT NULL DEFAULT ''",
    }.items():
        if column not in vehicle_columns:
            conn.execute(f"ALTER TABLE domain_vehicles ADD COLUMN {column} {definition}")
    driver_columns = {row["name"] for row in conn.execute("PRAGMA table_info(domain_drivers)").fetchall()}
    for column, definition in {
        "driver_type": "TEXT NOT NULL DEFAULT 'own'",
        "vehicle_registration": "TEXT NOT NULL DEFAULT ''",
        "vehicle_group": "TEXT NOT NULL DEFAULT ''",
        "license_expiry": "TEXT",
    }.items():
        if column not in driver_columns:
            conn.execute(f"ALTER TABLE domain_drivers ADD COLUMN {column} {definition}")
    inv_columns = {row["name"] for row in conn.execute("PRAGMA table_info(domain_invoices)").fetchall()}
    if "idempotency_key" not in inv_columns:
        conn.execute("ALTER TABLE domain_invoices ADD COLUMN idempotency_key TEXT")
    duty_columns = {row["name"] for row in conn.execute("PRAGMA table_info(domain_duties)").fetchall()}
    if "version_id" not in duty_columns:
        conn.execute("ALTER TABLE domain_duties ADD COLUMN version_id INTEGER NOT NULL DEFAULT 1")


def _json(value, fallback):
    try:
        return json.loads(value) if value else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def _serialize(row, json_fields=()):
    if row is None:
        return None
    item = dict(row)
    for field in json_fields:
        if field in item:
            item[field] = _json(item[field], {})
    return item


def _org(user) -> str:
    organization_id = user["organization_id"]
    if not organization_id:
        raise DomainError(403, "This account is not linked to an organization", "organization_required")
    return organization_id


def _require_role(user, roles=("vendor", "corporate")) -> None:
    if user["role"] not in roles:
        raise DomainError(403, "This workflow is not available for this account role", "role_forbidden")


def _text(payload, key, default="", maximum=400) -> str:
    value = str(payload.get(key, default) or "").strip()
    if len(value) > maximum:
        raise DomainError(400, f"{key} is too long", "validation_error")
    return value


def _int(payload, key, default=0):
    value = payload.get(key, default)
    if value in (None, ""):
        return default
    if isinstance(value, bool) or isinstance(value, float) and not value.is_integer():
        raise DomainError(400, f"{key} must be an integer", "validation_error")
    try:
        value = int(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise DomainError(400, f"{key} must be an integer", "validation_error") from exc
    if value < 0:
        raise DomainError(400, f"{key} cannot be negative", "validation_error")
    return value


def _float(payload, key, default=None):
    value = payload.get(key, default)
    if value in (None, ""):
        return default
    try:
        number = float(value)
    except (ValueError, TypeError) as exc:
        raise DomainError(400, f"{key} must be a number", "validation_error") from exc
    if not math.isfinite(number):
        raise DomainError(400, f"{key} must be finite", "validation_error")
    return number


def _audit(conn, user, action, entity_type, entity_id, ip, metadata=None):
    conn.execute(
        """
        INSERT INTO audit_events(id, user_id, action, entity_type, entity_id, metadata_json, ip_address, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (new_id("audit"), user["id"], action, entity_type, entity_id, json.dumps(metadata or {}), ip, now_iso()),
    )


def _assert_owned(conn, table, entity_id, organization_id):
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ? AND organization_id = ?", (entity_id, organization_id)).fetchone()
    if row is None:
        raise DomainError(404, "Record not found", "not_found")
    return row


def seed_domain_data(conn) -> None:
    """Seed one reviewable operational loop for the existing demo vendor."""
    org = conn.execute("SELECT id FROM organizations WHERE id = 'org_demo_blueorbit'").fetchone()
    if not org:
        return
    now = now_iso()
    customer_id = "cust_demo_northstar"
    driver_id = "drv_demo_mahesh"
    vehicle_id = "veh_demo_ka03mn4821"
    booking_id = "book_demo_airport"
    duty_id = "duty_demo_airport"
    invoice_id = "inv_demo_2026_083"
    conn.execute(
        "INSERT OR IGNORE INTO domain_customers(id, organization_id, name, email, phone, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'active', ?, ?)",
        (customer_id, org["id"], "NorthStar Technologies", "travel@northstar.example", "+91 90000 11111", now, now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO domain_drivers(id, organization_id, full_name, phone, license_number, city, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'on_duty', ?, ?)",
        (driver_id, org["id"], "Mahesh Kumar", "+91 98450 22118", "KA012026000001", "Mumbai", now, now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO domain_vehicles(id, organization_id, registration_number, vehicle_type, make_model, manufacturer, model, city, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'on_duty', ?, ?)",
        (vehicle_id, org["id"], "KA 03 MN 4821", "sedan", "Maruti Suzuki Dzire", "Maruti Suzuki", "Dzire", "Mumbai", now, now),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO domain_bookings(id, organization_id, customer_id, booking_reference, status, passenger_name, passenger_phone, pickup_json, dropoff_json, scheduled_at, duty_type, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'assigned', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (booking_id, org["id"], customer_id, "BK-2026-001", "Rohit Mehta", "+91 90000 22222", json.dumps({"label": "Mumbai Airport T2", "lat": 19.0896, "lng": 72.8656}), json.dumps({"label": "BKC", "lat": 19.0607, "lng": 72.8631}), "2026-09-19T08:30:00Z", "airport", now, now),
    )
    snapshot = calculate_duty({"base_paise": 180000, "distance_km": 32, "per_km_paise": 1800, "duration_minutes": 90, "per_hour_paise": 2400, "tax_rate_bps": 1800})
    conn.execute(
        """
        INSERT OR IGNORE INTO domain_duties(id, organization_id, booking_id, driver_id, vehicle_id, status, reporting_at, calculation_snapshot_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'started', ?, ?, ?, ?)
        """,
        (duty_id, org["id"], booking_id, driver_id, vehicle_id, "2026-09-19T08:15:00Z", json.dumps(snapshot), now, now),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO domain_invoices(id, organization_id, customer_id, duty_id, invoice_number, status, subtotal_paise, tax_paise, total_paise, issued_at, immutable_snapshot_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'issued', ?, ?, ?, ?, ?, ?, ?)
        """,
        (invoice_id, org["id"], customer_id, duty_id, "INV-2026-083", snapshot["subtotal_paise"], snapshot["tax_paise"], snapshot["total_paise"], "2026-09-19T09:00:00Z", json.dumps(snapshot), now, now),
    )
    if not conn.execute("SELECT 1 FROM domain_invoice_lines WHERE invoice_id = ?", (invoice_id,)).fetchone():
        for line in snapshot["lines"]:
            conn.execute(
                "INSERT INTO domain_invoice_lines(id, invoice_id, code, label, quantity, unit_paise, amount_paise, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id("line"), invoice_id, line["code"], line["label"], line["quantity"], line["unit_paise"], line["amount_paise"], now),
            )


def _list(conn, table, org, order="created_at DESC", limit=100):
    return [_serialize(row) for row in conn.execute(f"SELECT * FROM {table} WHERE organization_id = ? ORDER BY {order} LIMIT ?", (org, limit)).fetchall()]


def _booking(conn, booking_id, org):
    row = _assert_owned(conn, "domain_bookings", booking_id, org)
    return _serialize(row, ("pickup_json", "dropoff_json"))


def _duty(conn, duty_id, org):
    row = _assert_owned(conn, "domain_duties", duty_id, org)
    return _serialize(row, ("calculation_snapshot_json",))


def _invoice(conn, invoice_id, org):
    row = _assert_owned(conn, "domain_invoices", invoice_id, org)
    data = _serialize(row, ("immutable_snapshot_json",))
    data["lines"] = [_serialize(x) for x in conn.execute("SELECT * FROM domain_invoice_lines WHERE invoice_id = ? ORDER BY created_at", (invoice_id,)).fetchall()]
    return data


def _update_booking(conn, user, booking_id, payload, ip):
    org = _org(user)
    _require_role(user)
    row = _assert_owned(conn, "domain_bookings", booking_id, org)
    updates = []
    if "customer_id" in payload:
        customer_id = _text(payload, "customer_id") or None
        if customer_id and customer_id in (org, "corp-default"):
            customer_id = None
        elif customer_id:
            _assert_owned(conn, "domain_customers", customer_id, org)
        updates.append(("customer_id", customer_id))
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(domain_bookings)").fetchall()}
    for key in ("passenger_name", "passenger_phone", "passenger_email", "scheduled_at", "duty_type", "notes", "status", "driver_id", "vehicle_id", "supplier_id", "driver_name", "vehicle_number", "supplier_name"):
        if key in payload and (key not in {"driver_id", "vehicle_id", "supplier_id", "driver_name", "vehicle_number", "supplier_name"} or key in cols):
            updates.append((key, _text(payload, key, maximum=500)))
    for key, json_key in (("pickup_json", "pickup"), ("dropoff_json", "dropoff")):
        if json_key in payload and isinstance(payload[json_key], dict):
            updates.append((key, json.dumps(payload[json_key])))
    if not updates:
        raise DomainError(400, "No booking fields supplied", "validation_error")
    updates.append(("updated_at", now_iso()))
    conn.execute(f"UPDATE domain_bookings SET {', '.join(f'{key} = ?' for key, _ in updates)} WHERE id = ?", [value for _, value in updates] + [booking_id])
    _audit(conn, user, "booking.updated", "booking", booking_id, ip, {key: value for key, value in updates if key not in {"pickup_json", "dropoff_json"}})
    return {"ok": True, "item": _booking(conn, booking_id, org)}


def _create_customer(conn, user, payload, ip):
    org = _org(user)
    _require_role(user)
    name = _text(payload, "name")
    if not name:
        raise DomainError(400, "Customer name is required", "validation_error")
    customer_id = new_id("cust")
    now = now_iso()
    raw_code = _text(payload, "code") or _text(payload, "customer_code") or _text(payload, "corp_code") or _derive_corp_code(name)
    code = re.sub(r"[^A-Za-z0-9]", "", raw_code).strip().upper()
    cust_cols = {row["name"] for row in conn.execute("PRAGMA table_info(domain_customers)").fetchall()}
    if "code" in cust_cols:
        conn.execute("INSERT INTO domain_customers(id, organization_id, name, code, email, phone, gstin, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)", (customer_id, org, name, code, _text(payload, "email"), _text(payload, "phone"), _text(payload, "gstin").upper(), now, now))
    else:
        conn.execute("INSERT INTO domain_customers(id, organization_id, name, email, phone, gstin, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)", (customer_id, org, name, _text(payload, "email"), _text(payload, "phone"), _text(payload, "gstin").upper(), now, now))
    _audit(conn, user, "customer.created", "customer", customer_id, ip, {"name": name, "code": code})
    return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_customers WHERE id = ?", (customer_id,)).fetchone())}


def _create_driver(conn, user, payload, ip):
    org = _org(user)
    _require_role(user)
    name = _text(payload, "full_name")
    if not name:
        raise DomainError(400, "Driver name is required", "validation_error")
    linked_user_id = _text(payload, "user_id") or None
    if linked_user_id:
        linked = conn.execute("SELECT id, role, full_name, phone FROM users WHERE id = ?", (linked_user_id,)).fetchone()
        if linked is None or linked["role"] != "driver":
            raise DomainError(400, "user_id must reference a driver account", "validation_error")
        conn.execute("UPDATE users SET organization_id = ? WHERE id = ?", (org, linked_user_id))
    driver_id = new_id("drv")
    now = now_iso()
    raw_type = (_text(payload, "driver_type") or "own").lower()
    driver_type = raw_type if raw_type in ("own", "supplier", "dco") else "own"
    vehicle_registration = _text(payload, "vehicle_registration", maximum=40).upper()
    vehicle_group = _text(payload, "vehicle_group", maximum=60)
    conn.execute(
        "INSERT INTO domain_drivers(id, organization_id, user_id, full_name, phone, license_number, city, status, driver_type, vehicle_registration, vehicle_group, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'available', ?, ?, ?, ?, ?)",
        (driver_id, org, linked_user_id, name, _text(payload, "phone"), _text(payload, "license_number").upper(), _text(payload, "city"), driver_type, vehicle_registration, vehicle_group, now, now)
    )
    _audit(conn, user, "driver.created", "driver", driver_id, ip, {"linked_user_id": linked_user_id, "driver_type": driver_type})
    return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_drivers WHERE id = ?", (driver_id,)).fetchone())}


def _create_vehicle(conn, user, payload, ip):
    org = _org(user)
    _require_role(user)
    registration = _text(payload, "registration_number").upper()
    if not registration:
        raise DomainError(400, "Registration number is required", "validation_error")
    if conn.execute("SELECT 1 FROM domain_vehicles WHERE organization_id = ? AND registration_number = ?", (org, registration)).fetchone():
        raise DomainError(409, "A vehicle with this registration already exists", "duplicate_vehicle")
    vehicle_id = new_id("veh")
    now = now_iso()
    manufacturer = _text(payload, "manufacturer", maximum=80)
    model = _text(payload, "model", maximum=80)
    make_model = _text(payload, "make_model", maximum=120)
    if not make_model and (manufacturer or model):
        make_model = f"{manufacturer} {model}".strip()
    elif make_model and not manufacturer and not model:
        lower = make_model.lower()
        multi_word = ["maruti suzuki", "tata motors", "force motors", "mercedes-benz", "aston martin", "land rover", "rolls-royce"]
        matched = False
        for brand in multi_word:
            if lower.startswith(brand):
                manufacturer = make_model[:len(brand)]
                model = make_model[len(brand):].strip()
                matched = True
                break
        if not matched:
            parts = make_model.split(" ", 1)
            manufacturer = parts[0]
            model = parts[1] if len(parts) > 1 else ""
    if not manufacturer:
        raise DomainError(400, "Manufacturer is a required field and cannot be empty", "validation_error")
    if not model:
        raise DomainError(400, "Model is a required field and cannot be empty", "validation_error")
    values = (
        vehicle_id, org, registration, _text(payload, "vehicle_type", "sedan", 40),
        _text(payload, "vehicle_group", maximum=80), make_model,
        _int(payload, "year", 0) or None, _text(payload, "city", maximum=80),
        _text(payload, "status", "available", 24), _text(payload, "fuel_type", "petrol", 30),
        1 if payload.get("ev_eligible") or str(payload.get("fuel_type", "")).lower() in {"ev", "electric"} else 0,
        _float(payload, "battery_capacity_kwh", None),
        _float(payload, "usable_range_km", None),
        _float(payload, "energy_consumption_kwh_per_km", None),
        _text(payload, "charging_connector", maximum=80),
        _float(payload, "charging_power_kw", None),
        _text(payload, "charging_status", "unknown", 24),
        _int(payload, "energy_price_per_kwh_minor", 0) or None,
        _int(payload, "seating_capacity", 4), _int(payload, "luggage_capacity", 0),
        _text(payload, "ownership_type", "owned", 30),
        _text(payload, "supplier_id", maximum=64),
        _text(payload, "supplier_name", maximum=120),
        _text(payload, "owner_name", maximum=120),
        _text(payload, "branch_name", maximum=100),
        _text(payload, "gps_provider", maximum=80), _text(payload, "rc_expiry", maximum=40) or None,
        _text(payload, "insurance_expiry", maximum=40) or None, _text(payload, "puc_expiry", maximum=40) or None,
        _text(payload, "notes", maximum=500), manufacturer, model, now, now,
    )
    conn.execute("""INSERT INTO domain_vehicles(
        id, organization_id, registration_number, vehicle_type, vehicle_group, make_model, year, city, status,
        fuel_type, ev_eligible, battery_capacity_kwh, usable_range_km, energy_consumption_kwh_per_km,
        charging_connector, charging_power_kw, charging_status, energy_price_per_kwh_minor,
        seating_capacity, luggage_capacity, ownership_type, supplier_id, supplier_name, owner_name, branch_name, gps_provider, rc_expiry,
        insurance_expiry, puc_expiry, notes, manufacturer, model, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", values)
    _audit(conn, user, "vehicle.created", "vehicle", vehicle_id, ip, {"registration_number": registration})
    return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_vehicles WHERE id = ?", (vehicle_id,)).fetchone())}


def _create_booking(conn, user, payload, ip):
    org = _org(user)
    _require_role(user)
    now = now_iso()
    reference = _text(payload, "booking_reference") or f"BK-{datetime.now(timezone.utc):%Y%m}-{uuid.uuid4().hex[:6].upper()}"
    customer_id = _text(payload, "customer_id") or None
    if customer_id and customer_id in (org, "corp-default"):
        customer_id = None
    elif customer_id:
        _assert_owned(conn, "domain_customers", customer_id, org)
    pickup = payload.get("pickup") if isinstance(payload.get("pickup"), dict) else {"label": _text(payload, "pickup")}
    dropoff = payload.get("dropoff") if isinstance(payload.get("dropoff"), dict) else {"label": _text(payload, "dropoff")}
    booking_id = new_id("book")
    conn.execute(
        """
        INSERT INTO domain_bookings(id, organization_id, customer_id, booking_reference, status, passenger_name, passenger_phone, passenger_email, pickup_json, dropoff_json, scheduled_at, duty_type, notes, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'requested', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (booking_id, org, customer_id, reference, _text(payload, "passenger_name"), _text(payload, "passenger_phone"), _text(payload, "passenger_email", maximum=254).lower(), json.dumps(pickup), json.dumps(dropoff), _text(payload, "scheduled_at") or None, _text(payload, "duty_type", "local"), _text(payload, "notes"), user["id"], now, now),
    )
    _audit(conn, user, "booking.created", "booking", booking_id, ip, {"reference": reference})
    return {"ok": True, "item": _booking(conn, booking_id, org)}


def _queue_push_notification(conn, organization_id: str, recipient_id: str | None, template: str, variables: dict) -> str:
    devices = []
    if recipient_id:
        devices = conn.execute("SELECT device_id, push_token FROM domain_device_bindings WHERE organization_id = ? AND user_id = ? AND status = 'active' AND push_token IS NOT NULL AND push_token <> ''", (organization_id, recipient_id)).fetchall()
    targets = [(device["device_id"], device["push_token"]) for device in devices] or [(None, recipient_id or "control-room")]
    first_notification_id = ""
    for device_id, recipient in targets:
        result = DEFAULT_PROVIDERS.messaging.send(channel="push", recipient=recipient, template=template, variables={**variables, "recipient_id": recipient_id, "device_id": device_id}, idempotency_key=f"push:{template}:{recipient}:{variables.get('duty_id', variables.get('alert_id', 'event'))}")
        notification_id = new_id("notification")
        if not first_notification_id:
            first_notification_id = notification_id
        now = now_iso()
        payload = {**result.payload, "device_id": device_id, "recipient_id": recipient_id}
        conn.execute("INSERT INTO domain_notifications(id, organization_id, recipient_id, channel, template_key, status, provider_reference, payload_json, created_at, delivered_at) VALUES (?, ?, ?, 'push', ?, ?, ?, ?, ?, ?)", (notification_id, organization_id, recipient_id, template, result.status, result.reference, json.dumps(payload), now, now if result.status == "sent" else None))
    return first_notification_id


def _create_sos(conn, user, duty_id, payload, ip):
    org = _org(user)
    idempotency_key = _text(payload, "idempotency_key", maximum=160) or None
    if idempotency_key:
        existing = conn.execute("SELECT * FROM domain_sos_events WHERE organization_id = ? AND json_extract(payload_json, '$.idempotency_key') = ?", (org, idempotency_key)).fetchone()
        if existing:
            return _serialize(existing, ("payload_json",))
    event_id = new_id("sos")
    conn.execute("INSERT INTO domain_sos_events(id, organization_id, duty_id, driver_id, latitude, longitude, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (event_id, org, duty_id, payload.get("driver_id") or user["id"], payload.get("latitude"), payload.get("longitude"), json.dumps(payload), now_iso()))
    alert_id = new_id("alert")
    conn.execute("INSERT INTO domain_alerts(id, organization_id, alert_type, severity, entity_type, entity_id, payload_json, created_at) VALUES (?, ?, 'sos', 'critical', 'duty', ?, ?, ?)", (alert_id, org, duty_id, json.dumps(payload), now_iso()))
    _audit(conn, user, "alert.created", "alert", alert_id, ip, {"alert_type": "sos"})
    operator_users = conn.execute("SELECT id FROM users WHERE organization_id = ? AND role IN ('vendor','corporate') AND status = 'active'", (org,)).fetchall()
    for operator in operator_users:
        _queue_push_notification(conn, org, operator["id"], "sos_alert", {"duty_id": duty_id, "alert_id": alert_id, "severity": "critical"})
    _audit(conn, user, "duty.sos_raised", "duty", duty_id, ip, {"alert_id": alert_id})
    return _serialize(conn.execute("SELECT * FROM domain_sos_events WHERE id = ?", (event_id,)).fetchone(), ("payload_json",))


def _create_duty(conn, user, payload, ip):
    org = _org(user)
    _require_role(user)
    booking_id = _text(payload, "booking_id")
    booking = _assert_owned(conn, "domain_bookings", booking_id, org)
    if booking["status"] == "pending_approval":
        raise DomainError(409, "Booking approval is required before a duty can be assigned", "booking_approval_required")
    existing_booking_duty = conn.execute(
        "SELECT id FROM domain_duties WHERE organization_id = ? AND booking_id = ? AND status NOT IN ('cancelled')",
        (org, booking_id),
    ).fetchone()
    if existing_booking_duty:
        raise DomainError(409, f"Booking {booking_id} already has an active duty {existing_booking_duty['id']}", "booking_already_assigned")
    driver_id = _text(payload, "driver_id") or None
    vehicle_id = _text(payload, "vehicle_id") or None
    supplier_id = _text(payload, "supplier_id") or None
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if driver_id:
        driver = _assert_owned(conn, "domain_drivers", driver_id, org)
        if driver["status"] not in ("active", "available", "on_duty"):
            raise DomainError(422, f"Cannot dispatch driver with inactive status '{driver['status']}'", "driver_compliance_inactive")
        if "license_expiry" in driver.keys() and driver["license_expiry"]:
            if str(driver["license_expiry"])[:10] < today_str:
                raise DomainError(422, f"Cannot dispatch driver {driver_id}: Commercial license expired on {driver['license_expiry']}", "driver_compliance_license_expired")
        active_driver_duty = conn.execute(
            "SELECT id FROM domain_duties WHERE organization_id = ? AND driver_id = ? AND status IN ('assigned', 'accepted', 'en_route', 'arrived', 'started', 'active')",
            (org, driver_id),
        ).fetchone()
        if active_driver_duty:
            raise DomainError(409, f"Driver {driver_id} is already assigned to active duty {active_driver_duty['id']}", "driver_concurrent_assignment")
    if vehicle_id:
        vehicle = _assert_owned(conn, "domain_vehicles", vehicle_id, org)
        if vehicle["status"] not in ("active", "available"):
            raise DomainError(422, f"Cannot dispatch vehicle with inactive status '{vehicle['status']}'", "vehicle_compliance_inactive")
        for doc_field in ("insurance_expiry", "puc_expiry", "rc_expiry"):
            if doc_field in vehicle.keys() and vehicle[doc_field]:
                if str(vehicle[doc_field])[:10] < today_str:
                    raise DomainError(422, f"Cannot dispatch vehicle {vehicle_id}: Statutory {doc_field.replace('_expiry', '').upper()} expired on {vehicle[doc_field]}", "vehicle_compliance_document_expired")
        active_veh_duty = conn.execute(
            "SELECT id FROM domain_duties WHERE organization_id = ? AND vehicle_id = ? AND status IN ('assigned', 'accepted', 'en_route', 'arrived', 'started', 'active')",
            (org, vehicle_id),
        ).fetchone()
        if active_veh_duty:
            raise DomainError(409, f"Vehicle {vehicle_id} is already assigned to active duty {active_veh_duty['id']}", "vehicle_concurrent_assignment")
    if supplier_id:
        _assert_owned(conn, "domain_suppliers", supplier_id, org)
    status = "assigned" if driver_id or vehicle_id or supplier_id else "draft"
    duty_id = _text(payload, "id") or _text(payload, "duty_id") or _text(payload, "trip_id")
    if not duty_id:
        corp_code = _text(payload, "corp_code") or _text(payload, "customer_code")
        customer_id = booking["customer_id"] if "customer_id" in booking.keys() else None
        if not corp_code and customer_id:
            cust_cols = {r["name"] for r in conn.execute("PRAGMA table_info(domain_customers)").fetchall()}
            customer = conn.execute("SELECT * FROM domain_customers WHERE id = ? AND organization_id = ?", (customer_id, org)).fetchone()
            if customer:
                if "code" in cust_cols and customer["code"]:
                    corp_code = customer["code"]
                elif customer["name"]:
                    corp_code = _derive_corp_code(customer["name"])
                    if "code" in cust_cols:
                        try:
                            conn.execute("UPDATE domain_customers SET code = ? WHERE id = ?", (corp_code, customer["id"]))
                        except Exception:
                            pass
        if not corp_code:
            corp_code = "TRIP"
        duty_id = _generate_trip_id(conn, org, corp_code)
    now = now_iso()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(domain_duties)").fetchall()}
    if "supplier_id" in cols:
        conn.execute("INSERT INTO domain_duties(id, organization_id, booking_id, driver_id, vehicle_id, supplier_id, status, reporting_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (duty_id, org, booking_id, driver_id, vehicle_id, supplier_id, status, _text(payload, "reporting_at") or None, now, now))
    else:
        conn.execute("INSERT INTO domain_duties(id, organization_id, booking_id, driver_id, vehicle_id, status, reporting_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (duty_id, org, booking_id, driver_id, vehicle_id, status, _text(payload, "reporting_at") or None, now, now))
    conn.execute("UPDATE domain_bookings SET status = ?, updated_at = ? WHERE id = ?", ("assigned" if status == "assigned" else "confirmed", now, booking_id))
    if driver_id:
        driver_user = conn.execute("SELECT user_id FROM domain_drivers WHERE id = ? AND organization_id = ?", (driver_id, org)).fetchone()
        if driver_user and driver_user["user_id"]:
            _queue_push_notification(conn, org, driver_user["user_id"], "duty_assigned", {"duty_id": duty_id, "booking_id": booking_id, "reporting_at": _text(payload, "reporting_at") or ""})
    _audit(conn, user, "duty.created", "duty", duty_id, ip, {"booking_id": booking_id, "status": status})
    return {"ok": True, "item": _duty(conn, duty_id, org)}


def _update_duty(conn, user, duty_id, payload, ip):
    org = _org(user)
    row = _assert_owned(conn, "domain_duties", duty_id, org)
    expected_version = payload.get("expected_version")
    if expected_version is None:
        expected_version = payload.get("version_id")
    if expected_version is not None:
        current_version = row["version_id"] if "version_id" in row.keys() else 1
        if int(expected_version) != int(current_version):
            raise DomainError(
                409,
                f"Duty {duty_id} was modified concurrently (current version {current_version} != expected {expected_version}). Refresh and reconcile.",
                "concurrency_conflict",
                {"duty_id": duty_id, "current_version": current_version, "expected_version": int(expected_version), "current_status": row["status"]},
            )
    driver_actor = user["role"] == "driver"
    if driver_actor:
        assignment = conn.execute("SELECT id FROM domain_drivers WHERE id = ? AND user_id = ? AND organization_id = ?", (row["driver_id"], user["id"], org)).fetchone()
        if assignment is None:
            raise DomainError(403, "This duty is not assigned to the signed-in driver", "duty_assignment_required")
        forbidden = set(payload) - {"status", "start_odometer", "end_odometer", "idempotency_key", "source", "expected_version", "version_id"}
        if forbidden:
            raise DomainError(403, "Drivers can only update execution fields", "driver_field_forbidden")
    else:
        _require_role(user)

    # Support odometer aliases (start_km / end_km)
    if "start_km" in payload and "start_odometer" not in payload:
        payload = {**payload, "start_odometer": payload["start_km"]}
    if "end_km" in payload and "end_odometer" not in payload:
        payload = {**payload, "end_odometer": payload["end_km"]}

    # State Machine Lock: Protect completed, invoiced, or locked duties from unauthorized field modifications
    is_terminal = row["status"] in ("completed", "invoiced", "locked")
    existing_inv = conn.execute("SELECT id, status FROM domain_invoices WHERE duty_id = ? AND organization_id = ? AND status != 'void'", (duty_id, org)).fetchone()
    if (is_terminal or existing_inv) and not payload.get("allow_locked_override"):
        modifying_keys = set(payload) & {"start_odometer", "end_odometer", "driver_id", "vehicle_id", "supplier_id", "reporting_at"}
        if modifying_keys:
            raise DomainError(
                409,
                f"Cannot modify fields {sorted(modifying_keys)} because duty {duty_id} is {row['status']}" + (f" with invoice {existing_inv['id']}" if existing_inv else "") + ". Recalculations and odometer modifications are locked.",
                "duty_locked",
                {"duty_id": duty_id, "status": row["status"], "invoice_id": existing_inv["id"] if existing_inv else None}
            )

    # Validate odometer readings
    candidate_start = payload.get("start_odometer", row["start_odometer"])
    candidate_end = payload.get("end_odometer", row["end_odometer"])
    if candidate_start is not None and candidate_end is not None:
        try:
            s_val = int(candidate_start)
            e_val = int(candidate_end)
            if s_val < 0 or e_val < 0:
                raise DomainError(400, "Odometer readings must be non-negative", "validation_error")
            if e_val < s_val:
                raise DomainError(400, "End odometer must be greater than or equal to start odometer", "validation_error")
        except (TypeError, ValueError) as exc:
            raise DomainError(400, "Odometer readings must be valid integers", "validation_error") from exc

    updates = []
    values = []
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(domain_duties)").fetchall()}
    for key in ("driver_id", "vehicle_id", "supplier_id", "reporting_at", "start_odometer", "end_odometer"):
        if key in payload and (key not in {"supplier_id"} or key in cols):
            value = payload[key]
            if key in ("driver_id", "vehicle_id", "supplier_id"):
                value = _text(payload, key) or None
                if value:
                    table_name = "domain_drivers" if key == "driver_id" else "domain_vehicles" if key == "vehicle_id" else "domain_suppliers"
                    _assert_owned(conn, table_name, value, org)
            elif key in ("start_odometer", "end_odometer"):
                value = _int(payload, key)
            else:
                value = _text(payload, key) or None
            updates.append(f"{key} = ?")
            values.append(value)
    next_status = payload.get("status")
    idempotency_key = _text(payload, "idempotency_key", maximum=160) or None
    if idempotency_key:
        existing_event = conn.execute("SELECT 1 FROM domain_duty_events WHERE organization_id = ? AND idempotency_key = ?", (org, idempotency_key)).fetchone()
        if existing_event:
            return {"ok": True, "item": _duty(conn, duty_id, org), "idempotent": True}
    if next_status and next_status != row["status"]:
        allowed = {
            "draft": {"assigned", "cancelled"}, "assigned": {"accepted", "cancelled", "draft"},
            "accepted": {"en_route", "cancelled", "draft"}, "en_route": {"started", "cancelled"},
            "started": {"paused", "completed", "cancelled"}, "paused": {"started", "completed", "cancelled"},
            "completed": {"disputed"}, "cancelled": set(), "disputed": set()
        }
        if next_status not in allowed.get(row["status"], set()):
            raise DomainError(409, f"Cannot move duty from {row['status']} to {next_status}", "invalid_transition")
        if driver_actor and next_status not in {"accepted", "en_route", "started", "paused", "completed"}:
            raise DomainError(403, "Drivers cannot cancel or dispute duties from execution", "driver_transition_forbidden")
        updates.append("status = ?")
        values.append(next_status)
        if next_status == "started":
            updates.append("started_at = ?"); values.append(now_iso())
        if next_status == "completed":
            updates.append("completed_at = ?"); values.append(now_iso())
    if not updates:
        return {"ok": True, "item": _duty(conn, duty_id, org)}
    updates.append("version_id = COALESCE(version_id, 1) + 1"); updates.append("updated_at = ?"); values.append(now_iso()); values.append(duty_id); values.append(org)
    conn.execute(f"UPDATE domain_duties SET {', '.join(updates)} WHERE id = ? AND organization_id = ?", values)
    if next_status:
        conn.execute("INSERT INTO domain_duty_events(id, organization_id, duty_id, event_type, source, payload_json, idempotency_key, event_at, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (new_id("event"), org, duty_id, "status_changed", _text(payload, "source", "driver_app" if driver_actor else "web", maximum=40), json.dumps({"from": row["status"], "to": next_status, "payload": payload}), idempotency_key, now_iso(), user["id"]))
    _audit(conn, user, "duty.updated", "duty", duty_id, ip, {"status": next_status, "source": "driver" if driver_actor else "console"})
    return {"ok": True, "item": _duty(conn, duty_id, org)}


def _create_expense(conn, user, duty_id, payload, ip):
    org = _org(user)
    duty = _assert_owned(conn, "domain_duties", duty_id, org)
    driver_actor = user["role"] == "driver"
    if driver_actor:
        assignment = conn.execute("SELECT id FROM domain_drivers WHERE id = ? AND user_id = ? AND organization_id = ?", (duty["driver_id"], user["id"], org)).fetchone()
        if assignment is None: raise DomainError(403, "This duty is not assigned to the signed-in driver", "duty_assignment_required")
    else: _require_role(user)
    amount = _int(payload, "amount_paise")
    if amount <= 0: raise DomainError(400, "Expense amount must be greater than zero", "validation_error")
    if amount > MAX_EXPENSE_PAISE: raise DomainError(400, "Expense amount exceeds the allowed business limit", "amount_limit_exceeded")
    category = _text(payload, "category", "other", maximum=40).lower()
    if category not in EXPENSE_CATEGORIES: raise DomainError(400, "Unsupported expense category", "validation_error")
    note = _text(payload, "note", maximum=MAX_PROOF_NOTE_LENGTH)
    key = _text(payload, "idempotency_key", maximum=160) or None
    if key:
        existing = conn.execute("SELECT * FROM domain_expenses WHERE organization_id = ? AND idempotency_key = ?", (org, key)).fetchone()
        if existing: return {"ok": True, "item": _serialize(existing, ("attachment_json",)), "idempotent": True}
    expense_id = new_id("expense"); now = now_iso()
    conn.execute("INSERT INTO domain_expenses(id, organization_id, duty_id, category, amount_paise, note, attachment_json, idempotency_key, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (expense_id, org, duty_id, category, amount, note, json.dumps(payload.get("attachment") if isinstance(payload.get("attachment"), dict) else {}), key, user["id"], now))
    _audit(conn, user, "duty.expense_submitted", "expense", expense_id, ip, {"duty_id": duty_id, "amount_paise": amount, "category": category})
    return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_expenses WHERE id = ?", (expense_id,)).fetchone(), ("attachment_json",))}


def _create_duty_proof(conn, user, duty_id, payload, ip):
    org = _org(user)
    duty = _assert_owned(conn, "domain_duties", duty_id, org)
    driver_actor = user["role"] == "driver"
    if driver_actor:
        assignment = conn.execute("SELECT id FROM domain_drivers WHERE id = ? AND user_id = ? AND organization_id = ?", (duty["driver_id"], user["id"], org)).fetchone()
        if assignment is None:
            raise DomainError(403, "This duty is not assigned to the signed-in driver", "duty_assignment_required")
    else:
        _require_role(user)
    proof_type = _text(payload, "proof_type", maximum=40).lower()
    if proof_type not in {"otp", "signature", "photo", "duty_slip", "note"}:
        raise DomainError(400, "Unsupported proof type", "validation_error")
    idempotency_key = _text(payload, "idempotency_key", maximum=160) or None
    if idempotency_key:
        existing = conn.execute("SELECT * FROM domain_duty_proofs WHERE organization_id = ? AND idempotency_key = ?", (org, idempotency_key)).fetchone()
        if existing:
            return {"ok": True, "item": _serialize(existing, ("proof_json",)), "idempotent": True}
    proof_data = payload.get("proof_data") if isinstance(payload.get("proof_data"), dict) else {}
    if not proof_data:
        proof_data = {key: payload[key] for key in ("otp", "recipient_name", "signature_text", "attachment_name", "attachment_size", "note") if key in payload}
    if proof_type == "otp":
        otp = str(proof_data.get("code") or proof_data.get("otp") or "").strip()
        if not re.fullmatch(r"[0-9]{4,6}", otp):
            raise DomainError(400, "OTP must contain 4 to 6 digits", "validation_error")
        proof_data = {**proof_data, "code": otp}
    if "note" in proof_data and len(str(proof_data.get("note") or "")) > MAX_PROOF_NOTE_LENGTH:
        raise DomainError(400, "Proof note is too long", "validation_error")
    encoded = json.dumps(proof_data, separators=(",", ":"))
    if len(encoded) > 100_000:
        raise DomainError(413, "Proof payload is too large", "payload_too_large")
    captured_at = _text(payload, "captured_at", maximum=40) or now_iso()
    proof_id = new_id("proof")
    storage_path = _text(payload, "storage_path", maximum=500)
    conn.execute("INSERT INTO domain_duty_proofs(id, organization_id, duty_id, proof_type, storage_path, proof_json, idempotency_key, captured_at, captured_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (proof_id, org, duty_id, proof_type, storage_path, encoded, idempotency_key, captured_at, user["id"]))
    _audit(conn, user, "duty.proof_captured", "duty_proof", proof_id, ip, {"duty_id": duty_id, "proof_type": proof_type, "storage_path": storage_path})
    return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_duty_proofs WHERE id = ?", (proof_id,)).fetchone(), ("proof_json",))}


def _create_track_point(conn, user, duty_id, payload, ip):
    org = _org(user)
    duty = _assert_owned(conn, "domain_duties", duty_id, org)
    driver_actor = user["role"] == "driver"
    if driver_actor:
        assignment = conn.execute("SELECT id FROM domain_drivers WHERE id = ? AND user_id = ? AND organization_id = ?", (duty["driver_id"], user["id"], org)).fetchone()
        if assignment is None:
            raise DomainError(403, "This duty is not assigned to the signed-in driver", "duty_assignment_required")
    else:
        _require_role(user)
    latitude = _float(payload, "latitude")
    longitude = _float(payload, "longitude")
    if latitude is None or not -90 <= latitude <= 90 or longitude is None or not -180 <= longitude <= 180:
        raise DomainError(400, "Location coordinates are out of range", "validation_error")
    idempotency_key = _text(payload, "idempotency_key", maximum=160) or None
    if idempotency_key:
        existing = conn.execute("SELECT * FROM domain_track_points WHERE organization_id = ? AND idempotency_key = ?", (org, idempotency_key)).fetchone()
        if existing:
            return {"ok": True, "item": _serialize(existing), "idempotent": True}
    point_id = new_id("track")
    recorded_at = _text(payload, "recorded_at", maximum=40) or now_iso()
    conn.execute("INSERT INTO domain_track_points(id, organization_id, duty_id, recorded_at, latitude, longitude, accuracy_m, battery_pct, source, idempotency_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (point_id, org, duty_id, recorded_at, latitude, longitude, _float(payload, "accuracy_m"), _float(payload, "battery_pct"), _text(payload, "source", "driver_app", maximum=40), idempotency_key, now_iso()))
    return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_track_points WHERE id = ?", (point_id,)).fetchone())}


def _replay_sync(conn, user, payload, ip):
    org = _org(user)
    operations = payload.get("operations") if isinstance(payload.get("operations"), list) else []
    if not operations:
        raise DomainError(400, "At least one sync operation is required", "validation_error")
    if len(operations) > 100:
        raise DomainError(413, "A sync batch may contain at most 100 operations", "batch_too_large")
    device_id = _text(payload, "device_id", maximum=160) or "unknown-device"
    results = []
    for operation in operations:
        if not isinstance(operation, dict):
            results.append({"status": "failed", "error": "Operation must be an object"})
            continue
        key = _text(operation, "idempotency_key", maximum=160)
        if not key:
            results.append({"status": "failed", "error": "idempotency_key is required"})
            continue
        existing = conn.execute("SELECT * FROM domain_sync_operations WHERE user_id = ? AND idempotency_key = ?", (user["id"], key)).fetchone()
        if existing:
            results.append({"idempotency_key": key, "status": existing["status"], "result": _json(existing["result_json"], {}), "error": existing["error_message"] or None, "idempotent": True})
            continue
        entity_type = _text(operation, "entity_type", maximum=60)
        entity_id = _text(operation, "entity_id", maximum=160) or None
        operation_name = _text(operation, "operation", maximum=60)
        operation_payload = operation.get("payload") if isinstance(operation.get("payload"), dict) else {}
        sync_id = new_id("sync")
        now = now_iso()
        conn.execute("INSERT INTO domain_sync_operations(id, organization_id, user_id, device_id, idempotency_key, entity_type, entity_id, operation, status, client_created_at, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'processing', ?, ?, ?)", (sync_id, org, user["id"], device_id, key, entity_type, entity_id, operation_name, _text(operation, "client_created_at", maximum=40) or None, json.dumps(operation_payload), now))
        try:
            if entity_type == "duty" and operation_name == "status_transition" and entity_id:
                result = _update_duty(conn, user, entity_id, {**operation_payload, "idempotency_key": key, "source": "offline_replay"}, ip)
            elif entity_type in {"duty", "duty_proof"} and operation_name in {"proof", "capture_proof"} and entity_id:
                result = _create_duty_proof(conn, user, entity_id, {**operation_payload, "idempotency_key": key}, ip)
            elif entity_type in {"duty", "expense"} and operation_name == "expense" and entity_id:
                result = _create_expense(conn, user, entity_id, {**operation_payload, "idempotency_key": key}, ip)
            elif entity_type == "duty" and operation_name == "sos" and entity_id:
                result = _create_sos(conn, user, entity_id, {**operation_payload, "idempotency_key": key}, ip)
            elif entity_type == "track_point" and entity_id:
                result = _create_track_point(conn, user, entity_id, {**operation_payload, "idempotency_key": key}, ip)
            else:
                raise DomainError(400, "Unsupported sync operation", "unsupported_sync_operation")
            conn.execute("UPDATE domain_sync_operations SET status = 'synced', server_processed_at = ?, result_json = ? WHERE id = ?", (now_iso(), json.dumps(result), sync_id))
            results.append({"idempotency_key": key, "status": "synced", "result": result})
        except DomainError as exc:
            conn.execute("UPDATE domain_sync_operations SET status = 'failed', server_processed_at = ?, error_message = ? WHERE id = ?", (now_iso(), exc.message, sync_id))
            results.append({"idempotency_key": key, "status": "failed", "error": exc.message, "code": exc.code})
        except Exception as exc:
            conn.execute("UPDATE domain_sync_operations SET status = 'failed', server_processed_at = ?, error_message = ? WHERE id = ?", (now_iso(), str(exc)[:500], sync_id))
            results.append({"idempotency_key": key, "status": "failed", "error": "The operation could not be replayed", "code": "internal_error"})
    return {"ok": True, "device_id": device_id, "accepted": sum(1 for item in results if item.get("status") == "synced"), "failed": sum(1 for item in results if item.get("status") == "failed"), "results": results}


def _calculate(conn, user, duty_id, payload, ip):
    org = _org(user)
    row = _assert_owned(conn, "domain_duties", duty_id, org)

    # State Machine Lock: Reject recalculation on invoiced duties unless voided
    existing_invoice = conn.execute("SELECT id, status FROM domain_invoices WHERE duty_id = ? AND organization_id = ? AND status != 'void'", (duty_id, org)).fetchone()
    if existing_invoice and not payload.get("allow_locked_override"):
        raise DomainError(409, f"Cannot recalculate duty {duty_id} because invoice {existing_invoice['id']} has already been created ({existing_invoice['status']}).", "duty_invoiced")

    calculation_payload = dict(payload)
    price_item_id = str(calculation_payload.get("price_book_item_id") or "").strip()
    if price_item_id:
        price_item = conn.execute("SELECT i.* FROM domain_price_book_items i JOIN domain_price_books b ON b.id = i.price_book_id WHERE i.id = ? AND b.organization_id = ?", (price_item_id, org)).fetchone()
        if price_item is None:
            raise DomainError(404, "Price book item not found", "price_book_not_found")
        calculation_payload = {**calculation_payload, "base_paise": price_item["base_paise"], "per_km_paise": price_item["per_km_paise"], "per_hour_paise": price_item["per_hour_paise"], "waiting_paise": price_item["waiting_paise"], "tax_rate_bps": price_item["tax_rate_bps"]}
    try:
        snapshot = calculate_duty(calculation_payload)
    except CalculationError as exc:
        raise DomainError(400, str(exc), "calculation_error") from exc
    conn.execute("UPDATE domain_duties SET calculation_snapshot_json = ?, updated_at = ? WHERE id = ? AND organization_id = ?", (json.dumps(snapshot), now_iso(), duty_id, org))
    _audit(conn, user, "duty.calculated", "duty", duty_id, ip, {"engine_version": snapshot["engine_version"], "total_paise": snapshot["total_paise"]})
    return {"ok": True, "item": _duty(conn, duty_id, org), "calculation": snapshot}


def _create_invoice(conn, user, payload, ip):
    org = _org(user)
    _require_role(user)
    duty_id = _text(payload, "duty_id")
    idempotency_key = _text(payload, "idempotency_key", maximum=160) or None
    inv_cols = {r["name"] for r in conn.execute("PRAGMA table_info(domain_invoices)").fetchall()}
    if idempotency_key and "idempotency_key" in inv_cols:
        existing_run = conn.execute("SELECT id FROM domain_invoices WHERE organization_id = ? AND idempotency_key = ?", (org, idempotency_key)).fetchone()
        if existing_run:
            return {"ok": True, "item": _invoice(conn, existing_run["id"], org), "idempotent": True}
    if duty_id:
        existing_duty_inv = conn.execute("SELECT id FROM domain_invoices WHERE organization_id = ? AND duty_id = ? AND status != 'void'", (org, duty_id)).fetchone()
        if existing_duty_inv:
            return {"ok": True, "item": _invoice(conn, existing_duty_inv["id"], org), "duplicate": True}
    duty = _assert_owned(conn, "domain_duties", duty_id, org)
    try:
        audit = conn.execute("SELECT audit_status, trust_score FROM domain_duty_trust_audits WHERE duty_id = ? AND organization_id = ?", (duty_id, org)).fetchone()
        if audit and audit["audit_status"] == "NEEDS_AUDIT":
            raise DomainError(422, f"Duty {duty_id} has unresolved audit flags (Trust Score: {audit['trust_score']}). Resolve discrepancy before generating invoice.", "audit_resolution_required")
    except sqlite3.OperationalError:
        pass
    snapshot = _json(duty["calculation_snapshot_json"], {})
    if not snapshot or not snapshot.get("total_paise"):
        raise DomainError(422, "Calculate the duty before creating an invoice", "calculation_required")
    booking = _assert_owned(conn, "domain_bookings", duty["booking_id"], org)
    invoice_id = new_id("inv")
    sequence = conn.execute("SELECT COUNT(*) + 1 AS next_number FROM domain_invoices WHERE organization_id = ?", (org,)).fetchone()["next_number"]
    invoice_number = _text(payload, "invoice_number") or f"INV-{datetime.now(timezone.utc):%Y}-{sequence:03d}"
    now = now_iso()
    if "idempotency_key" in inv_cols:
        conn.execute("INSERT INTO domain_invoices(id, organization_id, customer_id, duty_id, invoice_number, status, subtotal_paise, tax_paise, total_paise, idempotency_key, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?)", (invoice_id, org, booking["customer_id"], duty_id, invoice_number, snapshot["subtotal_paise"], snapshot["tax_paise"], snapshot["total_paise"], idempotency_key, user["id"], now, now))
    else:
        conn.execute("INSERT INTO domain_invoices(id, organization_id, customer_id, duty_id, invoice_number, status, subtotal_paise, tax_paise, total_paise, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?)", (invoice_id, org, booking["customer_id"], duty_id, invoice_number, snapshot["subtotal_paise"], snapshot["tax_paise"], snapshot["total_paise"], user["id"], now, now))
    for line in snapshot.get("lines", []):
        conn.execute("INSERT INTO domain_invoice_lines(id, invoice_id, code, label, quantity, unit_paise, amount_paise, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (new_id("line"), invoice_id, line["code"], line["label"], line["quantity"], line["unit_paise"], line["amount_paise"], now))
    conn.execute("UPDATE domain_duties SET status = 'invoiced', updated_at = ? WHERE id = ? AND organization_id = ?", (now, duty_id, org))
    _audit(conn, user, "invoice.created", "invoice", invoice_id, ip, {"duty_id": duty_id, "total_paise": snapshot["total_paise"]})
    return {"ok": True, "item": _invoice(conn, invoice_id, org)}


def _update_invoice(conn, user, invoice_id, payload, ip):
    org = _org(user)
    _require_role(user)
    row = _assert_owned(conn, "domain_invoices", invoice_id, org)
    next_status = _text(payload, "status")
    if next_status not in {"issued", "sent", "void"}:
        raise DomainError(400, "Invoice status must be issued, sent or void", "validation_error")
    if row["status"] == "issued" and next_status != "sent":
        raise DomainError(409, "Issued invoices are immutable except for dispatch state", "immutable_invoice")
    issued_at = row["issued_at"] or (now_iso() if next_status == "issued" else None)
    snapshot = row["immutable_snapshot_json"] or (json.dumps(_invoice(conn, invoice_id, org)) if next_status == "issued" else None)
    conn.execute("UPDATE domain_invoices SET status = ?, issued_at = ?, immutable_snapshot_json = ?, updated_at = ? WHERE id = ? AND organization_id = ?", (next_status, issued_at, snapshot, now_iso(), invoice_id, org))
    _audit(conn, user, "invoice.status_changed", "invoice", invoice_id, ip, {"status": next_status})
    return {"ok": True, "item": _invoice(conn, invoice_id, org)}


def _create_payment(conn, user, payload, ip):
    org = _org(user)
    _require_role(user)
    invoice_id = _text(payload, "invoice_id")
    invoice = _assert_owned(conn, "domain_invoices", invoice_id, org)
    amount = _int(payload, "amount_paise")
    if amount <= 0:
        raise DomainError(400, "Payment amount must be greater than zero", "validation_error")
    idempotency_key = _text(payload, "idempotency_key", maximum=160) or None
    if idempotency_key:
        existing = conn.execute("SELECT * FROM domain_payments WHERE organization_id = ? AND idempotency_key = ?", (org, idempotency_key)).fetchone()
        if existing:
            return {"ok": True, "item": _serialize(existing), "invoice": _invoice(conn, invoice_id, org), "idempotent": True}
    provider_result = DEFAULT_PROVIDERS.payments.create_payment(amount_paise=amount, currency="INR", idempotency_key=idempotency_key, metadata={"invoice_id": invoice_id, "mode": _text(payload, "mode", "manual")})
    payment_id = new_id("pay")
    now = now_iso()
    conn.execute("INSERT INTO domain_payments(id, organization_id, invoice_id, amount_paise, mode, status, gateway_reference, idempotency_key, received_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (payment_id, org, invoice_id, amount, _text(payload, "mode", "manual"), provider_result.status, provider_result.reference, idempotency_key, now, now))
    paid = conn.execute("SELECT COALESCE(SUM(amount_paise), 0) AS paid FROM domain_payments WHERE invoice_id = ? AND status = 'succeeded'", (invoice_id,)).fetchone()["paid"]
    next_status = "paid" if paid >= invoice["total_paise"] else "partially_paid"
    conn.execute("UPDATE domain_invoices SET status = ?, updated_at = ? WHERE id = ?", (next_status, now, invoice_id))
    _audit(conn, user, "payment.recorded", "payment", payment_id, ip, {"invoice_id": invoice_id, "amount_paise": amount})
    return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_payments WHERE id = ?", (payment_id,)).fetchone()), "invoice": _invoice(conn, invoice_id, org)}


def handle_domain(conn, user, method: str, raw_route: str, payload: dict, ip: str):
    route = urlsplit(raw_route).path.rstrip("/") or "/"
    query = parse_qs(urlsplit(raw_route).query)
    limit = min(int(query.get("limit", [100])[0] or 100), 100)
    if route == "/api/overview" and method == "GET":
        org = _org(user)
        duties = conn.execute("SELECT status, COUNT(*) AS count FROM domain_duties WHERE organization_id = ? GROUP BY status", (org,)).fetchall()
        invoices = conn.execute("SELECT status, COUNT(*) AS count, COALESCE(SUM(total_paise),0) AS total_paise FROM domain_invoices WHERE organization_id = ? GROUP BY status", (org,)).fetchall()
        return {"ok": True, "organization_id": org, "duties": {r["status"]: r["count"] for r in duties}, "invoices": {r["status"]: {"count": r["count"], "total_paise": r["total_paise"]} for r in invoices}}
    if route == "/api/sync/replay" and method == "POST":
        return _replay_sync(conn, user, payload, ip)
    collections = {
        "/api/customers": ("domain_customers", ("created_at DESC",)),
        "/api/drivers": ("domain_drivers", ("created_at DESC",)),
        "/api/vehicles": ("domain_vehicles", ("created_at DESC",)),
        "/api/bookings": ("domain_bookings", ("scheduled_at ASC",)),
        "/api/duties": ("domain_duties", ("reporting_at ASC",)),
        "/api/invoices": ("domain_invoices", ("created_at DESC",)),
    }
    if route in collections and method == "GET":
        org = _org(user)
        table, ordering = collections[route]
        if table == "domain_duties" and user["role"] == "driver":
            items = [_serialize(row, ("calculation_snapshot_json",)) for row in conn.execute("SELECT d.* FROM domain_duties d JOIN domain_drivers dr ON dr.id = d.driver_id WHERE d.organization_id = ? AND dr.user_id = ? ORDER BY d.reporting_at ASC LIMIT ?", (org, user["id"], limit)).fetchall()]
        else:
            items = _list(conn, table, org, ordering[0], limit)
        if table == "domain_bookings":
            for item in items:
                item["pickup"] = _json(item.pop("pickup_json", "{}"), {})
                item["dropoff"] = _json(item.pop("dropoff_json", "{}"), {})
        if table == "domain_duties":
            for item in items:
                item["calculation_snapshot"] = _json(item.pop("calculation_snapshot_json", "{}"), {})
        return {"ok": True, "items": items, "count": len(items)}
    if route == "/api/customers" and method == "POST": return _create_customer(conn, user, payload, ip)
    if route == "/api/drivers" and method == "POST": return _create_driver(conn, user, payload, ip)
    if route == "/api/vehicles" and method == "POST": return _create_vehicle(conn, user, payload, ip)
    if route == "/api/bookings" and method == "POST": return _create_booking(conn, user, payload, ip)
    if route == "/api/duties" and method == "POST": return _create_duty(conn, user, payload, ip)
    if route == "/api/invoices" and method == "POST": return _create_invoice(conn, user, payload, ip)
    if route == "/api/payments" and method == "POST": return _create_payment(conn, user, payload, ip)

    parts = route.split("/")
    if len(parts) >= 4 and parts[2] in {"bookings", "duties", "invoices"}:
        if parts[2] == "duties" and len(parts) == 5 and parts[4] == "proof" and method == "POST": return _create_duty_proof(conn, user, parts[3], payload, ip)
        if parts[2] == "duties" and len(parts) == 5 and parts[4] == "track" and method == "POST": return _create_track_point(conn, user, parts[3], payload, ip)
        if parts[2] == "duties" and len(parts) == 5 and parts[4] == "expenses" and method == "POST": return _create_expense(conn, user, parts[3], payload, ip)
        if parts[2] == "duties" and len(parts) == 5 and parts[4] == "expenses" and method == "GET":
            org = _org(user); _assert_owned(conn, "domain_duties", parts[3], org); return {"ok": True, "items": [_serialize(row, ("attachment_json",)) for row in conn.execute("SELECT * FROM domain_expenses WHERE organization_id = ? AND duty_id = ? ORDER BY created_at DESC", (org, parts[3])).fetchall()]}

        resource, entity_id = parts[2], parts[3]
        if resource == "bookings" and method == "GET":
            return {"ok": True, "item": _booking(conn, entity_id, _org(user))}
        if resource == "bookings" and method == "PATCH": return _update_booking(conn, user, entity_id, payload, ip)
        if resource == "duties" and method == "GET": return {"ok": True, "item": _duty(conn, entity_id, _org(user))}
        if resource == "duties" and len(parts) == 5 and parts[4] == "events" and method == "GET":
            org = _org(user); _assert_owned(conn, "domain_duties", entity_id, org); return {"ok": True, "items": [_serialize(row, ("payload_json",)) for row in conn.execute("SELECT * FROM domain_duty_events WHERE organization_id = ? AND duty_id = ? ORDER BY event_at DESC", (org, entity_id)).fetchall()]}
        if resource == "duties" and len(parts) == 5 and parts[4] == "proof" and method == "GET":
            org = _org(user); _assert_owned(conn, "domain_duties", entity_id, org); return {"ok": True, "items": [_serialize(row, ("proof_json",)) for row in conn.execute("SELECT * FROM domain_duty_proofs WHERE organization_id = ? AND duty_id = ? ORDER BY captured_at DESC", (org, entity_id)).fetchall()]}
        if resource == "duties" and len(parts) == 5 and parts[4] == "track" and method == "GET":
            org = _org(user); _assert_owned(conn, "domain_duties", entity_id, org); return {"ok": True, "items": [_serialize(row) for row in conn.execute("SELECT * FROM domain_track_points WHERE organization_id = ? AND duty_id = ? ORDER BY recorded_at ASC", (org, entity_id)).fetchall()]}
        if resource == "duties" and len(parts) == 5 and parts[4] == "calculate" and method == "POST": return _calculate(conn, user, entity_id, payload, ip)
        if resource == "duties" and method == "PATCH": return _update_duty(conn, user, entity_id, payload, ip)
        if resource == "invoices" and len(parts) == 5 and parts[4] == "issue" and method == "POST": return _update_invoice(conn, user, entity_id, {"status": "issued"}, ip)
        if resource == "invoices" and method == "GET": return {"ok": True, "item": _invoice(conn, entity_id, _org(user))}
        if resource == "invoices" and method == "PATCH": return _update_invoice(conn, user, entity_id, payload, ip)
    raise DomainError(404, "Domain API route not found", "not_found")
