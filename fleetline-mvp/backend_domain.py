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
    rows_duties = conn.execute(
        "SELECT id FROM domain_duties WHERE id LIKE ?",
        (f"{prefix}%",)
    ).fetchall()
    cols_bookings = {r["name"] for r in conn.execute("PRAGMA table_info(domain_bookings)").fetchall()}
    rows_bookings = []
    if "trip_id" in cols_bookings:
        rows_bookings = conn.execute(
            "SELECT trip_id as id FROM domain_bookings WHERE trip_id LIKE ?",
            (f"{prefix}%",)
        ).fetchall()
    max_seq = 0
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    for r in list(rows_duties) + list(rows_bookings):
        item_id = str(r["id"] or "")
        match = pattern.match(item_id)
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
            invoice_type TEXT NOT NULL DEFAULT 'tax_invoice',
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
        CREATE TABLE IF NOT EXISTS audit_events (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            ip_address TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
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
        CREATE INDEX IF NOT EXISTS idx_domain_duties_org_booking ON domain_duties(organization_id, booking_id);
        CREATE INDEX IF NOT EXISTS idx_domain_duties_vehicle ON domain_duties(organization_id, vehicle_id, status);
        CREATE INDEX IF NOT EXISTS idx_domain_price_book_items_lookup ON domain_price_book_items(price_book_id, duty_type, vehicle_group);
        CREATE INDEX IF NOT EXISTS idx_domain_bookings_org_customer ON domain_bookings(organization_id, customer_id, scheduled_at);
        CREATE INDEX IF NOT EXISTS idx_domain_invoices_org_customer ON domain_invoices(organization_id, customer_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_domain_invoices_duty ON domain_invoices(duty_id);
        CREATE INDEX IF NOT EXISTS idx_audit_events_entity ON audit_events(entity_type, entity_id, created_at DESC);
        """
    )
    # Additive local migrations keep existing SQLite previews usable while the
    # Supabase vehicles table remains the production source of truth.
    def _col_name(r):
        return r["name"] if isinstance(r, sqlite3.Row) or isinstance(r, dict) else r[1]
    vehicle_columns = {_col_name(row) for row in conn.execute("PRAGMA table_info(domain_vehicles)").fetchall()}
    booking_columns = {_col_name(row) for row in conn.execute("PRAGMA table_info(domain_bookings)").fetchall()}
    customer_columns = {_col_name(row) for row in conn.execute("PRAGMA table_info(domain_customers)").fetchall()}
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
        "fitness_expiry": "TEXT",
        "permit_expiry": "TEXT",
        "insurance_policy_number": "TEXT NOT NULL DEFAULT ''",
        "rc_number": "TEXT NOT NULL DEFAULT ''",
        "puc_number": "TEXT NOT NULL DEFAULT ''",
        "fitness_number": "TEXT NOT NULL DEFAULT ''",
        "permit_number": "TEXT NOT NULL DEFAULT ''",
        "permit_type": "TEXT NOT NULL DEFAULT ''",
        "rc_file_name": "TEXT NOT NULL DEFAULT ''",
        "rc_file_data": "TEXT NOT NULL DEFAULT ''",
        "insurance_file_name": "TEXT NOT NULL DEFAULT ''",
        "insurance_file_data": "TEXT NOT NULL DEFAULT ''",
        "puc_file_name": "TEXT NOT NULL DEFAULT ''",
        "puc_file_data": "TEXT NOT NULL DEFAULT ''",
        "fitness_file_name": "TEXT NOT NULL DEFAULT ''",
        "fitness_file_data": "TEXT NOT NULL DEFAULT ''",
        "permit_file_name": "TEXT NOT NULL DEFAULT ''",
        "permit_file_data": "TEXT NOT NULL DEFAULT ''",
        "notes": "TEXT NOT NULL DEFAULT ''",
        "manufacturer": "TEXT NOT NULL DEFAULT ''",
        "model": "TEXT NOT NULL DEFAULT ''",
    }.items():
        if column not in vehicle_columns:
            conn.execute(f"ALTER TABLE domain_vehicles ADD COLUMN {column} {definition}")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS domain_org_settings (
            organization_id TEXT PRIMARY KEY,
            settings_json TEXT NOT NULL DEFAULT '{}',
            updated_by TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
    """)
    driver_columns = {_col_name(row) for row in conn.execute("PRAGMA table_info(domain_drivers)").fetchall()}
    for column, definition in {
        "driver_type": "TEXT NOT NULL DEFAULT 'own'",
        "vehicle_registration": "TEXT NOT NULL DEFAULT ''",
        "vehicle_group": "TEXT NOT NULL DEFAULT ''",
        "license_expiry": "TEXT",
        "badge_number": "TEXT NOT NULL DEFAULT ''",
        "badge_expiry": "TEXT",
        "police_verification_number": "TEXT NOT NULL DEFAULT ''",
        "police_verification_expiry": "TEXT",
        "medical_certificate_number": "TEXT NOT NULL DEFAULT ''",
        "medical_expiry": "TEXT",
        "dl_file_name": "TEXT NOT NULL DEFAULT ''",
        "dl_file_data": "TEXT NOT NULL DEFAULT ''",
        "badge_file_name": "TEXT NOT NULL DEFAULT ''",
        "badge_file_data": "TEXT NOT NULL DEFAULT ''",
        "pcc_file_name": "TEXT NOT NULL DEFAULT ''",
        "pcc_file_data": "TEXT NOT NULL DEFAULT ''",
        "medical_file_name": "TEXT NOT NULL DEFAULT ''",
        "medical_file_data": "TEXT NOT NULL DEFAULT ''",
        "notes": "TEXT NOT NULL DEFAULT ''",
    }.items():
        if column not in driver_columns:
            conn.execute(f"ALTER TABLE domain_drivers ADD COLUMN {column} {definition}")
    inv_columns = {_col_name(row) for row in conn.execute("PRAGMA table_info(domain_invoices)").fetchall()}
    if "idempotency_key" not in inv_columns:
        conn.execute("ALTER TABLE domain_invoices ADD COLUMN idempotency_key TEXT")
    duty_columns = {_col_name(row) for row in conn.execute("PRAGMA table_info(domain_duties)").fetchall()}
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


def _get_org_settings(conn, org: str) -> dict:
    try:
        row = conn.execute("SELECT settings_json FROM domain_org_settings WHERE organization_id = ?", (org,)).fetchone()
        if row and row["settings_json"]:
            return json.loads(row["settings_json"]) if isinstance(row["settings_json"], str) else dict(row["settings_json"])
    except Exception:
        pass
    return {}


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
    data["trip_id"] = row["duty_id"]
    data["lines"] = [_serialize(x) for x in conn.execute("SELECT * FROM domain_invoice_lines WHERE invoice_id = ? ORDER BY created_at", (invoice_id,)).fetchall()]
    if row["customer_id"]:
        cust = conn.execute("SELECT name, code, gstin, email, phone FROM domain_customers WHERE id = ?", (row["customer_id"],)).fetchone()
        if cust:
            data["customer_name"] = cust["name"]
            data["customer_code"] = cust["code"]
            data["customer_gstin"] = cust["gstin"]
            data["customer_email"] = cust["email"]
            data["customer_phone"] = cust["phone"]
    duty_id = row["duty_id"]
    if duty_id:
        duty = conn.execute("SELECT * FROM domain_duties WHERE id = ? AND organization_id = ?", (duty_id, org)).fetchone()
        if duty:
            booking = conn.execute("SELECT * FROM domain_bookings WHERE id = ? AND organization_id = ?", (duty["booking_id"], org)).fetchone()
            veh = conn.execute("SELECT registration_number, manufacturer, model FROM domain_vehicles WHERE id = ?", (duty["vehicle_id"],)).fetchone() if duty["vehicle_id"] else None
            drv = conn.execute("SELECT full_name, phone FROM domain_drivers WHERE id = ?", (duty["driver_id"],)).fetchone() if duty["driver_id"] else None
            p_json = _json(booking["pickup_json"], {}) if booking and booking["pickup_json"] else {}
            d_json = _json(booking["dropoff_json"], {}) if booking and booking["dropoff_json"] else {}
            data["trip_details"] = {
                "trip_id": duty["id"],
                "booking_reference": booking["booking_reference"] if booking else "",
                "duty_type": booking["duty_type"] if booking else "",
                "passenger_name": booking["passenger_name"] if booking else "",
                "passenger_phone": booking["passenger_phone"] if booking else "",
                "pickup_address": p_json.get("address") or p_json.get("label") or "",
                "dropoff_address": d_json.get("address") or d_json.get("label") or "",
                "vehicle_reg": veh["registration_number"] if veh else "",
                "vehicle_model": f"{veh['manufacturer']} {veh['model']}".strip() if veh else "",
                "driver_name": drv["full_name"] if drv else "",
                "driver_phone": drv["phone"] if drv else "",
                "start_odometer": duty["start_odometer"],
                "end_odometer": duty["end_odometer"],
                "distance_km": (duty["end_odometer"] - duty["start_odometer"]) if duty["end_odometer"] and duty["start_odometer"] else None,
                "started_at": duty["started_at"],
                "completed_at": duty["completed_at"],
                "reporting_at": duty["reporting_at"],
                "calculation": _json(duty["calculation_snapshot_json"], {}) if duty["calculation_snapshot_json"] else {}
            }
    return data



def _assign_booking_resources(conn, user, booking_id: str, payload: dict, ip: str):
    org = _org(user)
    _require_role(user)
    booking = _assert_owned(conn, "domain_bookings", booking_id, org)
    if booking["status"] == "pending_approval":
        raise DomainError(409, "Booking approval is required before resources can be assigned", "booking_approval_required")
    try:
        t_id_chk = booking["trip_id"] if "trip_id" in booking.keys() and booking["trip_id"] else booking_id
        gate_row = conn.execute("SELECT approval_status FROM booking_approval_requests WHERE trip_id = ? OR trip_id = ? LIMIT 1", (booking_id, t_id_chk)).fetchone()
        if gate_row and gate_row["approval_status"] != "APPROVED":
            raise DomainError(409, f"Cannot dispatch: Pending Corporate Manager Approval (Current Status: {gate_row['approval_status']})", "corporate_approval_pending")
    except sqlite3.OperationalError:
        pass

    driver_id = _text(payload, "driver_id") or None
    vehicle_id = _text(payload, "vehicle_id") or None
    supplier_id = _text(payload, "supplier_id") or None

    driver_name = None
    if driver_id:
        drv = conn.execute(
            "SELECT id, full_name, phone FROM domain_drivers WHERE id = ? AND (organization_id = ? OR organization_id IS NULL)",
            (driver_id, org),
        ).fetchone()
        if drv:
            driver_name = drv["full_name"]

    vehicle_number = None
    if vehicle_id:
        veh = _assert_owned(conn, "domain_vehicles", vehicle_id, org)
        vehicle_number = veh["registration_number"]
        guardrails = _get_org_settings(conn, org).get("dispatch_guardrails") or {}
        require_mandatory_docs = bool(guardrails.get("require_mandatory_vehicle_docs"))
        block_expired_docs = bool(guardrails.get("block_expired_documents"))
        today_str = now_iso()[:10]
        if require_mandatory_docs:
            mandatory_docs = [
                ("rc_expiry", "Registration Certificate (RC)"),
                ("insurance_expiry", "Commercial Insurance"),
                ("puc_expiry", "Pollution Under Control (PUC)"),
                ("fitness_expiry", "Fitness Certificate (FC)"),
                ("permit_expiry", "Commercial Transport Permit"),
            ]
            for doc_field, doc_label in mandatory_docs:
                val = veh[doc_field] if doc_field in veh.keys() else None
                if not val or not str(val).strip():
                    raise DomainError(422, f"Cannot allot vehicle {vehicle_id}: Mandatory statutory document missing ({doc_label})", "vehicle_compliance_document_missing")
                if str(val)[:10] < today_str:
                    raise DomainError(422, f"Cannot allot vehicle {vehicle_id}: Mandatory statutory document {doc_label} expired on {val}", "vehicle_compliance_document_expired")
        elif block_expired_docs:
            for doc_field in ("insurance_expiry", "puc_expiry", "rc_expiry", "fitness_expiry", "permit_expiry"):
                if doc_field in veh.keys() and veh[doc_field]:
                    if str(veh[doc_field])[:10] < today_str:
                        raise DomainError(422, f"Cannot allot vehicle {vehicle_id}: Statutory {doc_field.replace('_expiry', '').upper()} expired on {veh[doc_field]}", "vehicle_compliance_document_expired")

    supplier_name = None
    if supplier_id and supplier_id != "OWN":
        sup = conn.execute(
            "SELECT id, name FROM domain_suppliers WHERE id = ? AND organization_id = ?",
            (supplier_id, org),
        ).fetchone()
        if sup:
            supplier_name = sup["name"]
    elif supplier_id == "OWN" or (not supplier_id and (driver_id or vehicle_id)):
        supplier_name = "Own Fleet"
        supplier_id = None

    now = now_iso()
    new_status = "assigned" if (driver_id and vehicle_id) else ("confirmed" if (driver_id or vehicle_id) else "requested")

    trip_id = booking["trip_id"] if "trip_id" in booking.keys() and booking["trip_id"] else None
    if not trip_id:
        customer_id = booking["customer_id"] if "customer_id" in booking.keys() else None
        customer = conn.execute("SELECT code, name FROM domain_customers WHERE id = ? AND organization_id = ?", (customer_id, org)).fetchone() if customer_id else None
        corp_code = customer["code"] if customer and customer["code"] else _derive_corp_code(customer["name"] if customer else "TRIP")
        trip_id = _generate_trip_id(conn, org, corp_code)

    # Update domain_bookings
    conn.execute(
        """UPDATE domain_bookings 
           SET driver_id = ?, driver_name = ?, vehicle_id = ?, vehicle_number = ?, 
               supplier_id = ?, supplier_name = ?, status = ?, trip_id = ?, updated_at = ?
           WHERE id = ? AND organization_id = ?""",
        (driver_id, driver_name, vehicle_id, vehicle_number, supplier_id, supplier_name, new_status, trip_id, now, booking_id, org),
    )

    # Check if a duty already exists
    existing_duty = conn.execute(
        "SELECT id FROM domain_duties WHERE organization_id = ? AND booking_id = ?",
        (org, booking_id),
    ).fetchone()
    if existing_duty:
        conn.execute(
            """UPDATE domain_duties 
               SET driver_id = ?, vehicle_id = ?, supplier_id = ?, status = ?, updated_at = ?
               WHERE id = ? AND organization_id = ?""",
            (driver_id, vehicle_id, supplier_id, new_status, now, existing_duty["id"], org),
        )
    else:
        # Create duty
        conn.execute(
            """INSERT INTO domain_duties (
                   id, organization_id, booking_id, driver_id, vehicle_id, supplier_id, 
                   status, reporting_at, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (trip_id, org, booking_id, driver_id, vehicle_id, supplier_id, new_status, booking["scheduled_at"], now, now),
        )

    _audit(conn, user, "booking.allotted", "booking", booking_id, ip, {
        "driver_id": driver_id,
        "driver_name": driver_name,
        "vehicle_id": vehicle_id,
        "vehicle_number": vehicle_number,
        "trip_id": trip_id,
        "status": new_status,
    })

    return {
        "ok": True,
        "status": new_status,
        "trip_id": trip_id,
        "item": _booking(conn, booking_id, org),
    }


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
    license_number = _text(payload, "license_number").upper()
    license_expiry = _text(payload, "license_expiry", maximum=40) or None
    badge_number = _text(payload, "badge_number", maximum=80).upper()
    badge_expiry = _text(payload, "badge_expiry", maximum=40) or None
    police_verification_number = _text(payload, "police_verification_number", maximum=80).upper()
    police_verification_expiry = _text(payload, "police_verification_expiry", maximum=40) or None
    medical_certificate_number = _text(payload, "medical_certificate_number", maximum=80).upper()
    medical_expiry = _text(payload, "medical_expiry", maximum=40) or None
    dl_file_name = _text(payload, "dl_file_name", maximum=255)
    dl_file_data = _text(payload, "dl_file_data")
    badge_file_name = _text(payload, "badge_file_name", maximum=255)
    badge_file_data = _text(payload, "badge_file_data")
    pcc_file_name = _text(payload, "pcc_file_name", maximum=255)
    pcc_file_data = _text(payload, "pcc_file_data")
    medical_file_name = _text(payload, "medical_file_name", maximum=255)
    medical_file_data = _text(payload, "medical_file_data")
    notes = _text(payload, "notes", maximum=500)
    status_val = _text(payload, "status") or "available"
    if status_val not in ("available", "on_duty", "inactive", "suspended"):
        status_val = "available"

    conn.execute("""
        INSERT INTO domain_drivers(
            id, organization_id, user_id, full_name, phone, license_number, city, status,
            driver_type, vehicle_registration, vehicle_group, license_expiry,
            badge_number, badge_expiry, police_verification_number, police_verification_expiry,
            medical_certificate_number, medical_expiry,
            dl_file_name, dl_file_data, badge_file_name, badge_file_data,
            pcc_file_name, pcc_file_data, medical_file_name, medical_file_data,
            notes, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            driver_id, org, linked_user_id, name, _text(payload, "phone"), license_number, _text(payload, "city"), status_val,
            driver_type, vehicle_registration, vehicle_group, license_expiry,
            badge_number, badge_expiry, police_verification_number, police_verification_expiry,
            medical_certificate_number, medical_expiry,
            dl_file_name, dl_file_data, badge_file_name, badge_file_data,
            pcc_file_name, pcc_file_data, medical_file_name, medical_file_data,
            notes, now, now
        )
    )
    _audit(conn, user, "driver.created", "driver", driver_id, ip, {"linked_user_id": linked_user_id, "driver_type": driver_type})
    return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_drivers WHERE id = ?", (driver_id,)).fetchone())}


def _update_driver(conn, user, driver_id: str, payload: dict, ip: str):
    org = _org(user)
    _require_role(user)
    row = _assert_owned(conn, "domain_drivers", driver_id, org)
    now = now_iso()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(domain_drivers)").fetchall()}
    allowed_keys = [
        "full_name", "phone", "license_number", "license_expiry", "city", "status", "driver_type",
        "vehicle_registration", "vehicle_group",
        "badge_number", "badge_expiry",
        "police_verification_number", "police_verification_expiry",
        "medical_certificate_number", "medical_expiry",
        "dl_file_name", "dl_file_data",
        "badge_file_name", "badge_file_data",
        "pcc_file_name", "pcc_file_data",
        "medical_file_name", "medical_file_data",
        "notes"
    ]
    updates = []
    values = []
    for k in allowed_keys:
        if k in payload and k in cols:
            val = payload[k]
            if k == "driver_type":
                raw_type = str(val or "own").lower().strip()
                val = raw_type if raw_type in ("own", "supplier", "dco") else "own"
            elif k in ("license_number", "vehicle_registration", "badge_number", "police_verification_number", "medical_certificate_number"):
                val = str(val or "").strip().upper()
            elif k in ("dl_file_data", "badge_file_data", "pcc_file_data", "medical_file_data"):
                val = str(val or "")
            else:
                val = str(val or "").strip()
            updates.append(f"{k} = ?")
            values.append(val)
    if not updates:
        return {"ok": True, "item": _serialize(row)}
    updates.append("updated_at = ?")
    values.append(now)
    values.append(driver_id)
    values.append(org)
    conn.execute(f"UPDATE domain_drivers SET {', '.join(updates)} WHERE id = ? AND organization_id = ?", values)
    _audit(conn, user, "driver.updated", "driver", driver_id, ip, {"updated_keys": [k for k in allowed_keys if k in payload]})
    return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_drivers WHERE id = ?", (driver_id,)).fetchone())}


def _create_vehicle(conn, user, payload, ip):
    org = _org(user)
    _require_role(user)
    registration = _text(payload, "registration_number").upper()
    if not registration:
        raise DomainError(400, "Registration number is required", "validation_error")
    try:
        vendor_row = conn.execute("SELECT saas_plan FROM axiom_hq_vendors WHERE organization_id = ?", (org,)).fetchone()
        if vendor_row and vendor_row["saas_plan"] == "MICRO_FLEET":
            cur_count = conn.execute("SELECT count(*) FROM domain_vehicles WHERE organization_id = ?", (org,)).fetchone()[0]
            if cur_count >= 10:
                raise DomainError(403, "Micro-Fleet plan is limited to a maximum of 10 vehicles. Upgrade plan to expand fleet.", "micro_fleet_vehicle_limit_exceeded")
    except Exception as e:
        if isinstance(e, DomainError):
            raise
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
    rc_expiry = _text(payload, "rc_expiry", maximum=40) or None
    insurance_expiry = _text(payload, "insurance_expiry", maximum=40) or None
    puc_expiry = _text(payload, "puc_expiry", maximum=40) or None
    fitness_expiry = _text(payload, "fitness_expiry", maximum=40) or None
    permit_expiry = _text(payload, "permit_expiry", maximum=40) or None

    insurance_policy_number = _text(payload, "insurance_policy_number", maximum=80)
    rc_number = _text(payload, "rc_number", maximum=80)
    puc_number = _text(payload, "puc_number", maximum=80)
    fitness_number = _text(payload, "fitness_number", maximum=80)
    permit_number = _text(payload, "permit_number", maximum=80)
    permit_type = _text(payload, "permit_type", maximum=80)

    guardrails = _get_org_settings(conn, org).get("dispatch_guardrails") or {}
    require_mandatory_docs = bool(guardrails.get("require_mandatory_vehicle_docs"))
    block_expired_docs = bool(guardrails.get("block_expired_documents"))
    today_str = now[:10]

    if require_mandatory_docs:
        mandatory_checks = [
            ("rc_expiry", rc_expiry, "Registration Certificate (RC)"),
            ("insurance_expiry", insurance_expiry, "Commercial Insurance"),
            ("puc_expiry", puc_expiry, "Pollution Under Control (PUC)"),
            ("fitness_expiry", fitness_expiry, "Fitness Certificate (FC)"),
            ("permit_expiry", permit_expiry, "Commercial Transport Permit"),
        ]
        for key, val, label in mandatory_checks:
            if not val or not str(val).strip():
                raise DomainError(422, f"Mandatory compliance document missing: {label} expiry date is required", "mandatory_document_missing")
            if str(val)[:10] < today_str:
                raise DomainError(422, f"Mandatory compliance document expired: {label} expired on {val}", "mandatory_document_expired")
    elif block_expired_docs:
        for val, label in [
            (rc_expiry, "Registration Certificate (RC)"),
            (insurance_expiry, "Commercial Insurance"),
            (puc_expiry, "Pollution Under Control (PUC)"),
            (fitness_expiry, "Fitness Certificate (FC)"),
            (permit_expiry, "Commercial Transport Permit"),
        ]:
            if val and str(val)[:10] < today_str:
                raise DomainError(422, f"Statutory document expired: {label} expired on {val}", "vehicle_compliance_document_expired")

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
        _text(payload, "gps_provider", maximum=80),
        rc_expiry, insurance_expiry, puc_expiry, fitness_expiry, permit_expiry,
        insurance_policy_number, rc_number, puc_number, fitness_number, permit_number, permit_type,
        _text(payload, "rc_file_name", maximum=255), _text(payload, "rc_file_data"),
        _text(payload, "insurance_file_name", maximum=255), _text(payload, "insurance_file_data"),
        _text(payload, "puc_file_name", maximum=255), _text(payload, "puc_file_data"),
        _text(payload, "fitness_file_name", maximum=255), _text(payload, "fitness_file_data"),
        _text(payload, "permit_file_name", maximum=255), _text(payload, "permit_file_data"),
        _text(payload, "notes", maximum=500), manufacturer, model, now, now,
    )
    conn.execute("""INSERT INTO domain_vehicles(
        id, organization_id, registration_number, vehicle_type, vehicle_group, make_model, year, city, status,
        fuel_type, ev_eligible, battery_capacity_kwh, usable_range_km, energy_consumption_kwh_per_km,
        charging_connector, charging_power_kw, charging_status, energy_price_per_kwh_minor,
        seating_capacity, luggage_capacity, ownership_type, supplier_id, supplier_name, owner_name, branch_name, gps_provider,
        rc_expiry, insurance_expiry, puc_expiry, fitness_expiry, permit_expiry,
        insurance_policy_number, rc_number, puc_number, fitness_number, permit_number, permit_type,
        rc_file_name, rc_file_data, insurance_file_name, insurance_file_data, puc_file_name, puc_file_data,
        fitness_file_name, fitness_file_data, permit_file_name, permit_file_data,
        notes, manufacturer, model, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", values)
    _audit(conn, user, "vehicle.created", "vehicle", vehicle_id, ip, {"registration_number": registration})
    return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_vehicles WHERE id = ?", (vehicle_id,)).fetchone())}


def _vehicle(conn, vehicle_id: str, org: str):
    row = _assert_owned(conn, "domain_vehicles", vehicle_id, org)
    return _serialize(row)


def _update_vehicle(conn, user, vehicle_id: str, payload: dict, ip: str):
    org = _org(user)
    _require_role(user)
    row = _assert_owned(conn, "domain_vehicles", vehicle_id, org)
    now = now_iso()
    today_str = now[:10]

    guardrails = _get_org_settings(conn, org).get("dispatch_guardrails") or {}
    require_mandatory_docs = bool(guardrails.get("require_mandatory_vehicle_docs"))
    block_expired_docs = bool(guardrails.get("block_expired_documents"))

    target_status = payload.get("status", row["status"])
    if require_mandatory_docs and target_status in ("active", "available"):
        mandatory_checks = [
            ("rc_expiry", "Registration Certificate (RC)"),
            ("insurance_expiry", "Commercial Insurance"),
            ("puc_expiry", "Pollution Under Control (PUC)"),
            ("fitness_expiry", "Fitness Certificate (FC)"),
            ("permit_expiry", "Commercial Transport Permit"),
        ]
        for key, label in mandatory_checks:
            val = payload[key] if key in payload else (row[key] if key in row.keys() else None)
            if not val or not str(val).strip():
                raise DomainError(422, f"Mandatory compliance document missing: {label} expiry date is required", "mandatory_document_missing")
            if str(val)[:10] < today_str:
                raise DomainError(422, f"Mandatory compliance document expired: {label} expired on {val}", "mandatory_document_expired")

    if block_expired_docs:
        for key, label in [
            ("rc_expiry", "Registration Certificate (RC)"),
            ("insurance_expiry", "Commercial Insurance"),
            ("puc_expiry", "Pollution Under Control (PUC)"),
            ("fitness_expiry", "Fitness Certificate (FC)"),
            ("permit_expiry", "Commercial Transport Permit"),
        ]:
            if key in payload and payload[key]:
                if str(payload[key])[:10] < today_str:
                    raise DomainError(422, f"Statutory document expired: {label} expired on {payload[key]}", "vehicle_compliance_document_expired")

    cols = {r["name"] for r in conn.execute("PRAGMA table_info(domain_vehicles)").fetchall()}
    allowed_keys = [
        "registration_number", "vehicle_type", "vehicle_group", "make_model", "year",
        "city", "status", "fuel_type", "ev_eligible", "battery_capacity_kwh", "usable_range_km",
        "energy_consumption_kwh_per_km", "charging_connector", "charging_power_kw", "charging_status",
        "energy_price_per_kwh_minor", "seating_capacity", "luggage_capacity", "ownership_type",
        "supplier_id", "supplier_name", "owner_name", "branch_name", "gps_provider",
        "rc_expiry", "insurance_expiry", "puc_expiry", "fitness_expiry", "permit_expiry",
        "insurance_policy_number", "rc_number", "puc_number", "fitness_number", "permit_number", "permit_type",
        "rc_file_name", "rc_file_data", "insurance_file_name", "insurance_file_data",
        "puc_file_name", "puc_file_data", "fitness_file_name", "fitness_file_data",
        "permit_file_name", "permit_file_data",
        "notes", "manufacturer", "model"
    ]
    updates = []
    values = []
    for k in allowed_keys:
        if k in payload and k in cols:
            val = payload[k]
            if k in ("year", "seating_capacity", "luggage_capacity", "energy_price_per_kwh_minor", "ev_eligible"):
                val = int(val) if val not in (None, "") else None
            elif k in ("battery_capacity_kwh", "usable_range_km", "energy_consumption_kwh_per_km", "charging_power_kw"):
                val = float(val) if val not in (None, "") else None
            else:
                val = str(val).strip() if val is not None else None
            updates.append(f"{k} = ?")
            values.append(val)

    if "make_model" not in payload and ("manufacturer" in payload or "model" in payload):
        mfr = payload.get("manufacturer") or (row["manufacturer"] if "manufacturer" in row.keys() else "")
        mdl = payload.get("model") or (row["model"] if "model" in row.keys() else "")
        if mfr or mdl:
            mm = f"{mfr} {mdl}".strip()
            if "make_model" in cols:
                updates.append("make_model = ?")
                values.append(mm)

    if not updates:
        return {"ok": True, "item": _vehicle(conn, vehicle_id, org)}

    updates.append("updated_at = ?")
    values.append(now)
    values.extend([vehicle_id, org])
    conn.execute(f"UPDATE domain_vehicles SET {', '.join(updates)} WHERE id = ? AND organization_id = ?", values)
    _audit(conn, user, "vehicle.updated", "vehicle", vehicle_id, ip, {"updated_fields": list(payload.keys())})
    return {"ok": True, "item": _vehicle(conn, vehicle_id, org)}


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
    corp_code = _text(payload, "corp_code") or _text(payload, "customer_code")
    if not corp_code and customer_id:
        customer = conn.execute("SELECT * FROM domain_customers WHERE id = ? AND organization_id = ?", (customer_id, org)).fetchone()
        if customer:
            if "code" in customer.keys() and customer["code"]:
                corp_code = customer["code"]
            elif customer["name"]:
                corp_code = _derive_corp_code(customer["name"])
    if not corp_code:
        corp_code = "TRIP"
    trip_id = _text(payload, "trip_id") or _generate_trip_id(conn, org, corp_code)
    pickup = payload.get("pickup") if isinstance(payload.get("pickup"), dict) else {"label": _text(payload, "pickup")}
    dropoff = payload.get("dropoff") if isinstance(payload.get("dropoff"), dict) else {"label": _text(payload, "dropoff")}
    booking_id = new_id("book")
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(domain_bookings)").fetchall()}
    if "trip_id" in cols:
        conn.execute(
            """
            INSERT INTO domain_bookings(id, organization_id, customer_id, booking_reference, trip_id, status, passenger_name, passenger_phone, passenger_email, pickup_json, dropoff_json, scheduled_at, duty_type, notes, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'requested', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (booking_id, org, customer_id, reference, trip_id, _text(payload, "passenger_name"), _text(payload, "passenger_phone"), _text(payload, "passenger_email", maximum=254).lower(), json.dumps(pickup), json.dumps(dropoff), _text(payload, "scheduled_at") or None, _text(payload, "duty_type", "local"), _text(payload, "notes"), user["id"], now, now),
        )
    else:
        conn.execute(
            """
            INSERT INTO domain_bookings(id, organization_id, customer_id, booking_reference, status, passenger_name, passenger_phone, passenger_email, pickup_json, dropoff_json, scheduled_at, duty_type, notes, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'requested', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (booking_id, org, customer_id, reference, _text(payload, "passenger_name"), _text(payload, "passenger_phone"), _text(payload, "passenger_email", maximum=254).lower(), json.dumps(pickup), json.dumps(dropoff), _text(payload, "scheduled_at") or None, _text(payload, "duty_type", "local"), _text(payload, "notes"), user["id"], now, now),
        )
    _audit(conn, user, "booking.created", "booking", booking_id, ip, {"reference": reference, "trip_id": trip_id})
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
    try:
        t_id_chk = booking["trip_id"] if "trip_id" in booking.keys() and booking["trip_id"] else booking_id
        gate_row = conn.execute("SELECT approval_status FROM booking_approval_requests WHERE trip_id = ? OR trip_id = ? LIMIT 1", (booking_id, t_id_chk)).fetchone()
        if gate_row and gate_row["approval_status"] != "APPROVED":
            raise DomainError(409, f"Cannot dispatch: Pending Corporate Manager Approval (Current Status: {gate_row['approval_status']})", "corporate_approval_pending")
    except sqlite3.OperationalError:
        pass
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
        guardrails = _get_org_settings(conn, org).get("dispatch_guardrails") or {}
        require_mandatory_docs = bool(guardrails.get("require_mandatory_vehicle_docs"))
        block_expired_docs = bool(guardrails.get("block_expired_documents"))
        if require_mandatory_docs:
            mandatory_docs = [
                ("rc_expiry", "Registration Certificate (RC)"),
                ("insurance_expiry", "Commercial Insurance"),
                ("puc_expiry", "Pollution Under Control (PUC)"),
                ("fitness_expiry", "Fitness Certificate (FC)"),
                ("permit_expiry", "Commercial Transport Permit"),
            ]
            for doc_field, doc_label in mandatory_docs:
                val = vehicle[doc_field] if doc_field in vehicle.keys() else None
                if not val or not str(val).strip():
                    raise DomainError(422, f"Cannot dispatch vehicle {vehicle_id}: Mandatory statutory document missing ({doc_label})", "vehicle_compliance_document_missing")
                if str(val)[:10] < today_str:
                    raise DomainError(422, f"Cannot dispatch vehicle {vehicle_id}: Mandatory statutory document {doc_label} expired on {val}", "vehicle_compliance_document_expired")
        elif block_expired_docs:
            for doc_field in ("insurance_expiry", "puc_expiry", "rc_expiry", "fitness_expiry", "permit_expiry"):
                if doc_field in vehicle.keys() and vehicle[doc_field]:
                    if str(vehicle[doc_field])[:10] < today_str:
                        raise DomainError(422, f"Cannot dispatch vehicle {vehicle_id}: Statutory {doc_field.replace('_expiry', '').upper()} expired on {vehicle[doc_field]}", "vehicle_compliance_document_expired")
        else:
            if "insurance_expiry" in vehicle.keys() and vehicle["insurance_expiry"]:
                if str(vehicle["insurance_expiry"])[:10] < today_str:
                    raise DomainError(422, f"Cannot dispatch vehicle {vehicle_id}: Commercial insurance expired on {vehicle['insurance_expiry']}", "vehicle_compliance_insurance_expired")
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
    if not duty_id and "trip_id" in booking.keys() and booking["trip_id"]:
        duty_id = booking["trip_id"]
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
    cols_b = {r["name"] for r in conn.execute("PRAGMA table_info(domain_bookings)").fetchall()}
    if "trip_id" in cols_b:
        conn.execute("UPDATE domain_bookings SET status = ?, trip_id = ?, updated_at = ? WHERE id = ?", ("assigned" if status == "assigned" else "confirmed", duty_id, now, booking_id))
    else:
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
    duty_ids_raw = payload.get("duty_ids")
    if isinstance(duty_ids_raw, list) and duty_ids_raw:
        duty_ids = [str(x).strip() for x in duty_ids_raw if str(x).strip()]
    elif payload.get("duty_id"):
        duty_ids = [_text(payload, "duty_id")]
    else:
        duty_ids = []

    if not duty_ids:
        raise DomainError(400, "At least one duty_id is required to create an invoice", "validation_error")

    customer_id = _text(payload, "customer_id") or None
    invoice_type = _text(payload, "invoice_type") or ("consolidated" if len(duty_ids) > 1 else "single")
    period_from = _text(payload, "billing_period_from") or None
    period_to = _text(payload, "billing_period_to") or None
    idempotency_key = _text(payload, "idempotency_key", maximum=160) or None

    inv_cols = {r["name"] for r in conn.execute("PRAGMA table_info(domain_invoices)").fetchall()}
    line_cols_set = {r["name"] for r in conn.execute("PRAGMA table_info(domain_invoice_lines)").fetchall()}

    if idempotency_key and "idempotency_key" in inv_cols:
        existing_run = conn.execute("SELECT id FROM domain_invoices WHERE organization_id = ? AND idempotency_key = ?", (org, idempotency_key)).fetchone()
        if existing_run:
            return {"ok": True, "item": _invoice(conn, existing_run["id"], org), "idempotent": True}

    # Process all duties and gather lines
    total_subtotal_paise = 0
    total_tax_paise = 0
    total_total_paise = 0
    all_lines = []
    resolved_customer_id = customer_id

    for tid in duty_ids:
        duty = _assert_owned(conn, "domain_duties", tid, org)
        booking = _assert_owned(conn, "domain_bookings", duty["booking_id"], org) if duty["booking_id"] else None
        if not resolved_customer_id and booking and booking["customer_id"]:
            resolved_customer_id = booking["customer_id"]

        try:
            audit = conn.execute("SELECT audit_status, trust_score FROM domain_duty_trust_audits WHERE duty_id = ? AND organization_id = ?", (tid, org)).fetchone()
            if audit and audit["audit_status"] == "NEEDS_AUDIT":
                raise DomainError(422, f"Duty {tid} has unresolved audit flags (Trust Score: {audit['trust_score']}). Resolve discrepancy before generating invoice.", "audit_resolution_required")
        except sqlite3.OperationalError:
            pass

        snapshot = _json(duty["calculation_snapshot_json"], {})
        if not snapshot or not snapshot.get("total_paise"):
            # Synthesize fallback standard calculation if not calculated yet
            dist_km = (duty["end_odometer"] - duty["start_odometer"]) if duty["end_odometer"] and duty["start_odometer"] else 40
            base = 250000
            tax = int(base * 0.18)
            snapshot = {
                "subtotal_paise": base,
                "tax_paise": tax,
                "total_paise": base + tax,
                "lines": [
                    {"code": "BASE_FARE", "label": f"{duty['id']} package fare", "quantity": 1, "unit_paise": base, "amount_paise": base}
                ]
            }

        total_subtotal_paise += int(snapshot.get("subtotal_paise", 0))
        total_tax_paise += int(snapshot.get("tax_paise", 0))
        total_total_paise += int(snapshot.get("total_paise", 0))

        for l in snapshot.get("lines", []):
            all_lines.append((tid, l.get("code", "FARE"), l.get("label", "Tariff line"), l.get("quantity", 1), l.get("unit_paise", 0), l.get("amount_paise", 0)))

    invoice_id = new_id("inv")
    sequence = conn.execute("SELECT COUNT(*) + 1 AS next_number FROM domain_invoices WHERE organization_id = ?", (org,)).fetchone()["next_number"]
    invoice_number = _text(payload, "invoice_number") or f"INV-{datetime.now(timezone.utc):%Y}-{sequence:03d}"
    primary_duty_id = duty_ids[0] if len(duty_ids) == 1 else None
    now = now_iso()

    # Build insert query with dynamic columns
    insert_fields = ["id", "organization_id", "customer_id", "duty_id", "invoice_number", "status", "subtotal_paise", "tax_paise", "total_paise", "invoice_type", "created_by", "created_at", "updated_at"]
    insert_values = [invoice_id, org, resolved_customer_id, primary_duty_id, invoice_number, "draft", total_subtotal_paise, total_tax_paise, total_total_paise, invoice_type, user["id"], now, now]

    if "billing_period_from" in inv_cols:
        insert_fields.append("billing_period_from")
        insert_values.append(period_from)
    if "billing_period_to" in inv_cols:
        insert_fields.append("billing_period_to")
        insert_values.append(period_to)
    if "idempotency_key" in inv_cols:
        insert_fields.append("idempotency_key")
        insert_values.append(idempotency_key)

    placeholders = ", ".join(["?"] * len(insert_fields))
    col_str = ", ".join(insert_fields)
    conn.execute(f"INSERT INTO domain_invoices({col_str}) VALUES ({placeholders})", tuple(insert_values))

    # Insert line items
    has_duty_col = "duty_id" in line_cols_set
    for tid, code, label, qty, unit, amt in all_lines:
        lid = new_id("line")
        if has_duty_col:
            conn.execute("INSERT INTO domain_invoice_lines(id, invoice_id, duty_id, code, label, quantity, unit_paise, amount_paise, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (lid, invoice_id, tid, code, label, qty, unit, amt, now))
        else:
            conn.execute("INSERT INTO domain_invoice_lines(id, invoice_id, code, label, quantity, unit_paise, amount_paise, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (lid, invoice_id, code, label, qty, unit, amt, now))

    # Mark all duties as invoiced
    for tid in duty_ids:
        conn.execute("UPDATE domain_duties SET status = 'invoiced', updated_at = ? WHERE id = ? AND organization_id = ?", (now, tid, org))

    _audit(conn, user, "invoice.created", "invoice", invoice_id, ip, {"duty_count": len(duty_ids), "total_paise": total_total_paise})
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
        if table == "domain_invoices":
            line_cols_check = {r["name"] for r in conn.execute("PRAGMA table_info(domain_invoice_lines)").fetchall()}
            has_line_duty = "duty_id" in line_cols_check
            for item in items:
                # Get customer info
                if item.get("customer_id"):
                    cust = conn.execute("SELECT name, code, gstin, email, phone FROM domain_customers WHERE id = ?", (item["customer_id"],)).fetchone()
                    if cust:
                        item["customer_name"] = cust["name"]
                        item["customer_code"] = cust["code"]
                        item["customer_gstin"] = cust["gstin"]
                        item["customer_email"] = cust["email"]
                        item["customer_phone"] = cust["phone"]

                # Get trip count and summary from invoice lines
                if has_line_duty:
                    trip_rows = conn.execute("SELECT DISTINCT duty_id FROM domain_invoice_lines WHERE invoice_id = ? AND duty_id IS NOT NULL", (item["id"],)).fetchall()
                    trip_ids = [r["duty_id"] for r in trip_rows]
                else:
                    trip_ids = [item.get("duty_id")] if item.get("duty_id") else []

                item["trip_count"] = len(trip_ids)
                item["trip_ids"] = trip_ids[:10]  # First 10 for preview

                # Aggregate trip stats
                total_km = 0
                date_min = None
                date_max = None
                for tid in trip_ids:
                    duty = conn.execute("SELECT start_odometer, end_odometer, reporting_at, completed_at FROM domain_duties WHERE id = ? AND organization_id = ?", (tid, org)).fetchone()
                    if duty:
                        if duty["start_odometer"] and duty["end_odometer"]:
                            total_km += (duty["end_odometer"] - duty["start_odometer"])
                        dt = duty["reporting_at"] or duty["completed_at"]
                        if dt:
                            if date_min is None or dt < date_min:
                                date_min = dt
                            if date_max is None or dt > date_max:
                                date_max = dt
                item["total_km"] = total_km
                item["trip_date_from"] = date_min
                item["trip_date_to"] = date_max
        return {"ok": True, "items": items, "count": len(items)}
    if route == "/api/customers" and method == "POST": return _create_customer(conn, user, payload, ip)
    if route == "/api/drivers" and method == "POST": return _create_driver(conn, user, payload, ip)
    if route == "/api/vehicles" and method == "POST": return _create_vehicle(conn, user, payload, ip)
    if route == "/api/bookings/assign-resource" and method == "POST":
        b_id = str(payload.get("booking_id") or "").strip()
        if not b_id:
            raise DomainError(400, "booking_id is required", "validation_error")
        return _assign_booking_resources(conn, user, b_id, payload, ip)

    if assign_match := re.match(r"^/api/bookings/([^/]+)/assign$", route):
        if method == "POST":
            return _assign_booking_resources(conn, user, assign_match.group(1), payload, ip)

    if route == "/api/bookings" and method == "POST": return _create_booking(conn, user, payload, ip)
    if route == "/api/duties" and method == "POST": return _create_duty(conn, user, payload, ip)
    if route == "/api/invoices" and method == "POST": return _create_invoice(conn, user, payload, ip)
    if route == "/api/payments" and method == "POST": return _create_payment(conn, user, payload, ip)

    parts = route.split("/")
    
    # Paginated trips within an invoice
    if route_match := re.match(r"/api/invoices/([^/]+)/trips$", route):
        if method == "GET":
            inv_id = route_match.group(1)
            org = _org(user)
            _assert_owned(conn, "domain_invoices", inv_id, org)
            page = int(query.get("page", [1])[0] or 1)
            per_page = min(int(query.get("limit", [25])[0] or 25), 100)
            offset = (page - 1) * per_page
            search = (query.get("q", [""])[0] or "").strip().lower()

            line_cols_chk = {r["name"] for r in conn.execute("PRAGMA table_info(domain_invoice_lines)").fetchall()}
            has_line_duty = "duty_id" in line_cols_chk

            if has_line_duty:
                all_trip_ids = [r[0] for r in conn.execute("SELECT DISTINCT duty_id FROM domain_invoice_lines WHERE invoice_id = ? AND duty_id IS NOT NULL ORDER BY duty_id", (inv_id,)).fetchall()]
            else:
                inv_row = conn.execute("SELECT duty_id FROM domain_invoices WHERE id = ? AND organization_id = ?", (inv_id, org)).fetchone()
                all_trip_ids = [inv_row["duty_id"]] if inv_row and inv_row["duty_id"] else []

            # Build trip detail objects
            trips = []
            for tid in all_trip_ids:
                duty = conn.execute("SELECT * FROM domain_duties WHERE id = ? AND organization_id = ?", (tid, org)).fetchone()
                if not duty:
                    continue
                booking = conn.execute("SELECT * FROM domain_bookings WHERE id = ? AND organization_id = ?", (duty["booking_id"], org)).fetchone() if duty["booking_id"] else None
                veh = conn.execute("SELECT registration_number, manufacturer, model FROM domain_vehicles WHERE id = ?", (duty["vehicle_id"],)).fetchone() if duty["vehicle_id"] else None
                drv = conn.execute("SELECT full_name, phone FROM domain_drivers WHERE id = ?", (duty["driver_id"],)).fetchone() if duty["driver_id"] else None
                p_json = _json(booking["pickup_json"], {}) if booking and booking["pickup_json"] else {}
                d_json = _json(booking["dropoff_json"], {}) if booking and booking["dropoff_json"] else {}
                calc = _json(duty["calculation_snapshot_json"], {}) if duty["calculation_snapshot_json"] else {}
                dist = (duty["end_odometer"] - duty["start_odometer"]) if duty["end_odometer"] and duty["start_odometer"] else None

                # Lines for this trip
                if has_line_duty:
                    trip_lines = [_serialize(x) for x in conn.execute("SELECT * FROM domain_invoice_lines WHERE invoice_id = ? AND duty_id = ? ORDER BY created_at", (inv_id, tid)).fetchall()]
                else:
                    trip_lines = [_serialize(x) for x in conn.execute("SELECT * FROM domain_invoice_lines WHERE invoice_id = ? ORDER BY created_at", (inv_id,)).fetchall()]

                trip_amount = sum(int(l.get("amount_paise", 0)) for l in trip_lines)

                trip_obj = {
                    "trip_id": tid,
                    "booking_reference": booking["booking_reference"] if booking else "",
                    "duty_type": booking["duty_type"] if booking else "",
                    "passenger_name": booking["passenger_name"] if booking else "",
                    "passenger_phone": booking["passenger_phone"] if booking else "",
                    "pickup_address": p_json.get("address") or p_json.get("label") or "",
                    "dropoff_address": d_json.get("address") or d_json.get("label") or "",
                    "vehicle_reg": veh["registration_number"] if veh else "",
                    "vehicle_model": f"{veh['manufacturer']} {veh['model']}".strip() if veh else "",
                    "driver_name": drv["full_name"] if drv else "",
                    "driver_phone": drv["phone"] if drv else "",
                    "start_odometer": duty["start_odometer"],
                    "end_odometer": duty["end_odometer"],
                    "distance_km": dist,
                    "reporting_at": duty["reporting_at"],
                    "started_at": duty["started_at"],
                    "completed_at": duty["completed_at"],
                    "amount_paise": trip_amount,
                    "lines": trip_lines,
                    "calculation": calc
                }

                # Apply search filter
                if search:
                    searchable = f"{tid} {trip_obj['passenger_name']} {trip_obj['vehicle_reg']} {trip_obj['driver_name']} {trip_obj['pickup_address']} {trip_obj['dropoff_address']}".lower()
                    if search not in searchable:
                        continue

                trips.append(trip_obj)

            total = len(trips)
            paginated = trips[offset:offset + per_page]
            total_km = sum(t["distance_km"] or 0 for t in trips)
            total_amount = sum(t["amount_paise"] for t in trips)

            return {
                "ok": True,
                "invoice_id": inv_id,
                "trips": paginated,
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": max(1, (total + per_page - 1) // per_page),
                "summary": {
                    "total_trips": total,
                    "total_km": total_km,
                    "total_amount_paise": total_amount
                }
            }

    if len(parts) >= 4 and parts[2] in {"bookings", "duties", "invoices", "vehicles", "drivers"}:
        if parts[2] == "duties" and len(parts) == 5 and parts[4] == "proof" and method == "POST": return _create_duty_proof(conn, user, parts[3], payload, ip)
        if parts[2] == "duties" and len(parts) == 5 and parts[4] == "track" and method == "POST": return _create_track_point(conn, user, parts[3], payload, ip)
        if parts[2] == "duties" and len(parts) == 5 and parts[4] == "expenses" and method == "POST": return _create_expense(conn, user, parts[3], payload, ip)
        if parts[2] == "duties" and len(parts) == 5 and parts[4] == "expenses" and method == "GET":
            org = _org(user); _assert_owned(conn, "domain_duties", parts[3], org); return {"ok": True, "items": [_serialize(row, ("attachment_json",)) for row in conn.execute("SELECT * FROM domain_expenses WHERE organization_id = ? AND duty_id = ? ORDER BY created_at DESC", (org, parts[3])).fetchall()]}

        resource, entity_id = parts[2], parts[3]
        if resource == "drivers" and method == "GET":
            return {"ok": True, "item": _serialize(_assert_owned(conn, "domain_drivers", entity_id, _org(user)))}
        if resource == "drivers" and method == "PATCH":
            return _update_driver(conn, user, entity_id, payload, ip)
        if resource == "vehicles" and method == "GET":
            return {"ok": True, "item": _vehicle(conn, entity_id, _org(user))}
            return {"ok": True, "item": _vehicle(conn, entity_id, _org(user))}
        if resource == "vehicles" and method == "PATCH":
            return _update_vehicle(conn, user, entity_id, payload, ip)
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
