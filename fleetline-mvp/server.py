#!/usr/bin/env python3
"""Axiom Fleet local backend and optimized static server.

The project intentionally stays dependency-free for the prototype. This server
provides a small, real SQLite-backed identity API for vendor, driver and
corporate accounts while continuing to serve the single-file frontend with
cache headers and gzip compression.

Production handoff: replace the local SQLite/session implementation with the
platform's PostgreSQL, Redis, OIDC/OTP and rotating-token services described in
the technical PRD before handling real customer data.
"""

from __future__ import annotations

import datetime as dt
import email.utils
import gzip
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from http import cookies
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from functools import lru_cache, partial
from urllib.parse import urlsplit
from zoneinfo import available_timezones

from backend_domain import DEFAULT_PROVIDERS, DomainError, handle_domain, initialize_domain_schema, seed_domain_data
from backend_features import handle_feature, initialize_feature_schema, seed_feature_data
from backend_extended import handle_extended, handle_verified_payment_webhook, initialize_extended_schema
from backend_network import handle_network, initialize_network_schema
from backend_p0 import handle_p0, initialize_p0_schema
from backend_phase12 import handle_phase12, initialize_phase12_schema
from backend_phase3 import handle_phase3, initialize_phase3_schema
from backend_bill_intelligence import handle_bill_intelligence, initialize_bill_intelligence_schema
from backend_operations_parity import handle_operations_parity, initialize_operations_parity_schema
from backend_finance_parity import handle_finance_parity, initialize_finance_parity_schema
from backend_communications import handle_communications, initialize_communications_schema
from backend_supplier_finance import handle_supplier_finance, initialize_supplier_finance_schema
from backend_feedback import handle_feedback, initialize_feedback_schema
from backend_finance_controls import handle_finance_controls, handle_finance_controls_public, initialize_finance_controls_schema
from backend_corporate import apply_corporate_booking_decision, evaluate_corporate_booking_write, handle_corporate, handle_corporate_public, initialize_corporate_schema, maybe_create_duty_slip_approval, require_corporate_booking_permission
from backend_enterprise_controls import handle_enterprise_controls, handle_enterprise_public, initialize_enterprise_controls_schema
from backend_booking_parity import handle_booking_parity, initialize_booking_parity_schema
from backend_gap_completion import handle_gap_completion, handle_gap_public, initialize_gap_completion_schema
from backend_command_center import handle_command_center, initialize_command_center_schema

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("AXIOM_DATA_DIR", ROOT / "data"))
DB_PATH = Path(os.environ.get("AXIOM_DB_PATH", DATA_DIR / "axiom_fleet.sqlite3"))
COMPRESSIBLE = {".css", ".html", ".js", ".json", ".svg", ".txt", ".xml"}
PUBLIC_FILES = {
    "index.html", "axiom-fleet-logo.png", "driver-sw.js", "driver-manifest.json",
    "supabase/config.js", "supabase/client.js",
}
PUBLIC_PREFIXES = {"driver-app"}
PUBLIC_EXTENSIONS = {".html", ".js", ".css", ".png", ".svg", ".ico", ".webmanifest", ".json"}
ROLES = {"vendor", "driver", "corporate"}
SESSION_COOKIE = "axiom_session"
SESSION_DAYS = 30
PASSWORD_ITERATIONS = 180_000
MAX_BODY_BYTES = 1_048_576
LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW = 15 * 60
IANA_TIMEZONES = frozenset(available_timezones()) | {"UTC"}

# Small in-process guard for the local prototype. Production should use Redis.
LOGIN_FAILURES: dict[str, list[float]] = {}
LOGIN_FAILURE_LOCK = threading.Lock()
DB_PRAGMA_LOCK = threading.Lock()
WAL_DATABASES: set[str] = set()


def is_production() -> bool:
    return os.environ.get("AXIOM_ENV", "development").strip().lower() in {"production", "prod", "staging"}


def demo_account_allowed() -> bool:
    return os.environ.get("AXIOM_ALLOW_DEMO_ACCOUNT", "0") == "1" or not is_production()


def test_fixtures_enabled() -> bool:
    """Keep deterministic records available only to explicit test processes."""
    return os.environ.get("AXIOM_TEST_FIXTURES", "0") == "1" and not is_production()


def configured_origins() -> set[str]:
    values = os.environ.get("AXIOM_ALLOWED_ORIGINS", "").split(",")
    return {value.strip().rstrip("/") for value in values if value.strip()}


class APIError(Exception):
    def __init__(self, status: int, message: str, code: str = "bad_request"):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_after_days(days: int) -> str:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_after_seconds(seconds: int) -> str:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=seconds)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def db_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    database_key = str(DB_PATH.resolve())
    if database_key not in WAL_DATABASES:
        with DB_PRAGMA_LOCK:
            if database_key not in WAL_DATABASES:
                conn.execute("PRAGMA journal_mode = WAL")
                WAL_DATABASES.add(database_key)
    return conn


def hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt_hex = salt_hex or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        PASSWORD_ITERATIONS,
    ).hex()
    return salt_hex, digest


def verify_password(password: str, salt_hex: str, expected_hash: str) -> bool:
    _, actual_hash = hash_password(password, salt_hex)
    return hmac.compare_digest(actual_hash, expected_hash)


def normalize_email(value: object) -> str:
    return str(value or "").strip().lower()


def clean_text(value: object, field: str, *, required: bool = False, maximum: int = 160) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise APIError(400, f"{field} is required", "validation_error")
    if len(text) > maximum:
        raise APIError(400, f"{field} is too long", "validation_error")
    return text


def optional_int(value: object, field: str, *, maximum: int = 10_000_000) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise APIError(400, f"{field} must be a number", "validation_error") from exc
    if number < 0 or number > maximum:
        raise APIError(400, f"{field} is outside the allowed range", "validation_error")
    return number


def validate_email(email: str) -> None:
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise APIError(400, "Enter a valid email address", "validation_error")


def validate_timezone(value: object, field: str = "timezone", *, required: bool = False) -> str:
    timezone_name = clean_text(value, field, maximum=80)
    if not timezone_name:
        if required:
            raise APIError(400, f"{field} is required", "validation_error")
        return "UTC"
    if timezone_name not in IANA_TIMEZONES:
        raise APIError(400, f"Choose a valid IANA time zone for {field}", "validation_error")
    return timezone_name


def validate_signup(data: dict) -> dict:
    role = clean_text(data.get("role"), "role", required=True, maximum=20).lower()
    if role not in ROLES:
        raise APIError(400, "Choose vendor, driver or corporate", "validation_error")

    email = normalize_email(data.get("email"))
    validate_email(email)
    password = str(data.get("password") or "")
    if len(password) < 8:
        raise APIError(400, "Password must be at least 8 characters", "validation_error")
    if len(password) > 128:
        raise APIError(400, "Password is too long", "validation_error")

    full_name = clean_text(data.get("full_name"), "full_name", required=True, maximum=120)
    if len(full_name) < 2:
        raise APIError(400, "Enter your full name", "validation_error")
    phone = clean_text(data.get("phone"), "phone", maximum=32)
    city = clean_text(data.get("city"), "city", maximum=80)
    organization_name = clean_text(data.get("organization_name"), "organization_name", maximum=160)
    if role in {"vendor", "corporate"} and not organization_name:
        label = "Fleet or business name" if role == "vendor" else "Company name"
        raise APIError(400, f"{label} is required", "validation_error")

    return {
        "role": role,
        "email": email,
        "password": password,
        "full_name": full_name,
        "phone": phone,
        "city": city,
        "timezone": validate_timezone(data.get("timezone")),
        "organization_name": organization_name,
        "gstin": clean_text(data.get("gstin"), "gstin", maximum=32).upper(),
        "license_number": clean_text(data.get("license_number"), "license_number", maximum=80).upper(),
        "fleet_size": optional_int(data.get("fleet_size"), "fleet_size"),
        "employee_count": optional_int(data.get("employee_count"), "employee_count"),
    }


def initialize_database() -> None:
    with db_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL CHECK (kind IN ('vendor', 'corporate')),
                name TEXT NOT NULL,
                phone TEXT NOT NULL DEFAULT '',
                city TEXT NOT NULL DEFAULT '',
                gstin TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('vendor', 'driver', 'corporate')),
                full_name TEXT NOT NULL,
                phone TEXT NOT NULL DEFAULT '',
                organization_id TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                last_login_at TEXT,
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS profiles (
                user_id TEXT PRIMARY KEY,
                city TEXT NOT NULL DEFAULT '',
                timezone TEXT NOT NULL DEFAULT 'UTC',
                license_number TEXT NOT NULL DEFAULT '',
                fleet_size INTEGER,
                employee_count INTEGER,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                user_agent TEXT NOT NULL DEFAULT '',
                ip_address TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS password_resets (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used_at TEXT,
                request_ip TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS rate_limit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bucket TEXT NOT NULL,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_events (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                ip_address TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
            CREATE INDEX IF NOT EXISTS idx_password_resets_user ON password_resets(user_id, expires_at);
            CREATE INDEX IF NOT EXISTS idx_rate_limit_bucket ON rate_limit_events(bucket, created_at);
            CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_events(user_id, created_at);
            """
        )
        # Keep the local fallback compatible with databases created before
        # per-user timezone preferences were introduced.
        try:
            conn.execute("ALTER TABLE profiles ADD COLUMN timezone TEXT NOT NULL DEFAULT 'UTC'")
        except sqlite3.OperationalError as error:
            if "duplicate column name" not in str(error).lower():
                raise
        initialize_domain_schema(conn)
        initialize_feature_schema(conn)
        if test_fixtures_enabled():
            # Test fixtures are opt-in and never run in a normal workspace.
            seed_demo_account(conn)
            seed_domain_data(conn)
            seed_feature_data(conn)
        initialize_extended_schema(conn)
        initialize_network_schema(conn)
        initialize_p0_schema(conn)
        initialize_phase12_schema(conn)
        initialize_phase3_schema(conn)
        initialize_bill_intelligence_schema(conn)
        initialize_corporate_schema(conn)
        initialize_operations_parity_schema(conn)
        initialize_finance_parity_schema(conn)
        initialize_communications_schema(conn)
        initialize_supplier_finance_schema(conn)
        initialize_feedback_schema(conn)
        initialize_finance_controls_schema(conn)
        initialize_enterprise_controls_schema(conn)
        initialize_booking_parity_schema(conn)
        initialize_gap_completion_schema(conn)
        initialize_command_center_schema(conn)
        if not test_fixtures_enabled():
            purge_demo_records(conn)
        now = utc_now()
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        conn.execute("DELETE FROM password_resets WHERE expires_at <= ? OR used_at IS NOT NULL", (now,))
        conn.execute("DELETE FROM rate_limit_events WHERE created_at < ?", (time.time() - 24 * 60 * 60,))


def purge_demo_records(conn: sqlite3.Connection) -> None:
    """Remove legacy review fixtures when a database is opened normally.

    Fixture data is useful to explicit smoke tests, but a copied local database
    must not make a new operator believe that another organisation is theirs.
    Only the historical fixture identifiers are targeted; user-created tenants
    are left untouched.
    """
    target_ids = {
        "org_demo_blueorbit",
        "usr_demo_admin",
        "cust_demo_northstar",
        "drv_demo_mahesh",
        "veh_demo_ka03mn4821",
        "book_demo_airport",
        "duty_demo_airport",
        "inv_demo_2026_083",
        "branch_demo_mumbai",
        "supplier_demo_network",
        "pricebook_demo_september",
        "priceitem_demo_airport",
        "employee_demo_rohit",
        "policy_demo_travel",
    }
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        tables = [row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()]
        for table in tables:
            if table.startswith("sqlite_"):
                continue
            columns = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            column_names = {row["name"] for row in columns}
            predicates = []
            values: list[str] = []
            for column in column_names & {"organization_id", "org_id", "company_id", "tenant_id", "user_id", "created_by", "updated_by"}:
                predicates.append(f'"{column}" IN ({",".join("?" for _ in target_ids)})')
                values.extend(sorted(target_ids))
            text_columns = [row["name"] for row in columns if str(row["type"] or "").upper().startswith("TEXT")]
            for column in text_columns:
                predicates.append(f'"{column}" IN ({",".join("?" for _ in target_ids)})')
                values.extend(sorted(target_ids))
            if predicates:
                conn.execute(f'DELETE FROM "{table}" WHERE {" OR ".join(predicates)}', values)
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def seed_demo_account(conn: sqlite3.Connection) -> None:
    if not demo_account_allowed():
        # A database copied from development must not retain the known demo login.
        conn.execute("UPDATE users SET status = 'disabled' WHERE email = ?", ("admin@blueorbit.in",))
        return
    existing = conn.execute("SELECT id FROM users WHERE email = ?", ("admin@blueorbit.in",)).fetchone()
    if existing:
        return
    organization_id = "org_demo_blueorbit"
    user_id = "usr_demo_admin"
    now = utc_now()
    conn.execute(
        "INSERT OR IGNORE INTO organizations(id, kind, name, phone, city, gstin, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (organization_id, "vendor", "BlueOrbit Mobility", "+91 90000 00000", "Mumbai", "", now),
    )
    salt, password_hash = hash_password("motion2026")
    conn.execute(
        """
        INSERT INTO users(id, email, password_hash, password_salt, role, full_name, phone, organization_id, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
        """,
        (user_id, "admin@blueorbit.in", password_hash, salt, "vendor", "Aditi Rao", "+91 90000 00000", organization_id, now),
    )
    conn.execute(
        "INSERT INTO profiles(user_id, city, timezone, fleet_size, metadata_json) VALUES (?, ?, ?, ?, ?)",
        (user_id, "Mumbai", "Asia/Kolkata", 120, json.dumps({"seed": True})),
    )


def user_select_sql(include_password: bool = False) -> str:
    password_columns = ", u.password_hash, u.password_salt" if include_password else ""
    return f"""
        SELECT u.id, u.email, u.role, u.full_name, u.phone, u.status,
               u.organization_id, u.created_at, u.last_login_at,
               o.kind AS organization_type, o.name AS organization_name,
               o.phone AS organization_phone, o.city AS organization_city, o.gstin AS organization_gstin,
               p.city AS profile_city, p.timezone AS profile_timezone, p.license_number, p.fleet_size, p.employee_count
               {password_columns}
        FROM users u
        LEFT JOIN organizations o ON o.id = u.organization_id
        LEFT JOIN profiles p ON p.user_id = u.id
    """


def serialize_user(row: sqlite3.Row) -> dict:
    organization = None
    if row["organization_id"]:
        organization = {
            "id": row["organization_id"],
            "type": row["organization_type"],
            "name": row["organization_name"],
            "phone": row["organization_phone"] or "",
            "city": row["organization_city"] or "",
            "gstin": row["organization_gstin"] or "",
        }
    return {
        "id": row["id"],
        "email": row["email"],
        "role": row["role"],
        "full_name": row["full_name"],
        "phone": row["phone"],
        "status": row["status"],
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
        "organization": organization,
        "profile": {
            "city": row["profile_city"] or "",
            "timezone": row["profile_timezone"] or "UTC",
            "license_number": row["license_number"] or "",
            "fleet_size": row["fleet_size"],
            "employee_count": row["employee_count"],
        },
    }


def audit(conn: sqlite3.Connection, user_id: str | None, action: str, entity_type: str, entity_id: str | None, ip: str, metadata: dict | None = None) -> None:
    conn.execute(
        """
        INSERT INTO audit_events(id, user_id, action, entity_type, entity_id, metadata_json, ip_address, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (new_id("audit"), user_id, action, entity_type, entity_id, json.dumps(metadata or {}), ip, utc_now()),
    )


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def request_token(handler: SimpleHTTPRequestHandler) -> str | None:
    authorization = handler.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            return token
    jar = cookies.SimpleCookie()
    try:
        jar.load(handler.headers.get("Cookie", ""))
    except cookies.CookieError:
        return None
    morsel = jar.get(SESSION_COOKIE)
    return morsel.value if morsel else None


def secure_cookie_enabled() -> bool:
    return os.environ.get("AXIOM_COOKIE_SECURE") == "1" or is_production()


def make_cookie(token: str, max_age: int = SESSION_DAYS * 24 * 60 * 60) -> str:
    secure = "; Secure" if secure_cookie_enabled() else ""
    return f"{SESSION_COOKIE}={token}; Max-Age={max_age}; Path=/; HttpOnly; SameSite=Lax{secure}"


def clear_cookie() -> str:
    secure = "; Secure" if secure_cookie_enabled() else ""
    return f"{SESSION_COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax{secure}"


def current_user(conn: sqlite3.Connection, handler: SimpleHTTPRequestHandler) -> sqlite3.Row | None:
    token = request_token(handler)
    if not token:
        return None
    row = conn.execute(
        user_select_sql() + " JOIN sessions s ON s.user_id = u.id WHERE s.token_hash = ? AND s.expires_at > ?",
        (token_hash(token), utc_now()),
    ).fetchone()
    if row is None:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
    return row


def create_session(conn: sqlite3.Connection, user_id: str, handler: SimpleHTTPRequestHandler) -> str:
    raw_token = secrets.token_urlsafe(32)
    client_ip = handler.client_address[0] if handler.client_address else ""
    conn.execute(
        """
        INSERT INTO sessions(token_hash, user_id, created_at, expires_at, user_agent, ip_address)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            token_hash(raw_token),
            user_id,
            utc_now(),
            utc_after_days(SESSION_DAYS),
            handler.headers.get("User-Agent", "")[:300],
            client_ip[:64],
        ),
    )
    return raw_token


def login_key(email: str, handler: SimpleHTTPRequestHandler) -> str:
    return f"{email}|{client_ip(handler)}"


def login_keys(email: str, handler: SimpleHTTPRequestHandler) -> tuple[str, str, str]:
    ip = client_ip(handler)
    return login_key(email, handler), f"email:{email}", f"ip:{ip}"


def locked_out(key: str) -> bool:
    now = time.time()
    with LOGIN_FAILURE_LOCK:
        attempts = [stamp for stamp in LOGIN_FAILURES.get(key, []) if now - stamp < LOGIN_FAILURE_WINDOW]
        LOGIN_FAILURES[key] = attempts
        return len(attempts) >= LOGIN_FAILURE_LIMIT


def record_login_failure(key: str) -> None:
    now = time.time()
    with LOGIN_FAILURE_LOCK:
        attempts = [stamp for stamp in LOGIN_FAILURES.get(key, []) if now - stamp < LOGIN_FAILURE_WINDOW]
        attempts.append(now)
        LOGIN_FAILURES[key] = attempts[-LOGIN_FAILURE_LIMIT:]


def clear_login_failures(key: str) -> None:
    with LOGIN_FAILURE_LOCK:
        LOGIN_FAILURES.pop(key, None)


def client_ip(handler: SimpleHTTPRequestHandler) -> str:
    return (handler.client_address[0] if handler.client_address else "unknown")[:64]


def enforce_rate_limit(conn: sqlite3.Connection, bucket: str, limit: int, window_seconds: int) -> None:
    now = time.time()
    cutoff = now - window_seconds
    conn.execute("DELETE FROM rate_limit_events WHERE created_at < ?", (cutoff,))
    count = conn.execute("SELECT COUNT(*) AS count FROM rate_limit_events WHERE bucket = ? AND created_at >= ?", (bucket, cutoff)).fetchone()["count"]
    if count >= limit:
        raise APIError(429, "Too many requests. Try again later.", "rate_limited")
    conn.execute("INSERT INTO rate_limit_events(bucket, created_at) VALUES (?, ?)", (bucket, now))


def clear_rate_limit(conn: sqlite3.Connection, bucket: str) -> None:
    conn.execute("DELETE FROM rate_limit_events WHERE bucket = ?", (bucket,))


@lru_cache(maxsize=64)
def static_body(path_name: str, mtime_ns: int, size: int, use_gzip: bool) -> bytes:
    """Cache static payloads by file version and encoding.

    The dependency-free server previously reread and recompressed the 350KB
    console HTML on every request. The mtime/size key invalidates the cache
    automatically when a file changes during local development.
    """
    raw = Path(path_name).read_bytes()
    return gzip.compress(raw, compresslevel=9, mtime=0) if use_gzip else raw


class AxiomFleetHandler(SimpleHTTPRequestHandler):
    server_version = "AxiomFleetBackend/1.0"

    def _is_api(self) -> bool:
        return urlsplit(self.path).path.startswith("/api/")

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise APIError(400, "Invalid request length", "bad_request") from exc
        if length > MAX_BODY_BYTES:
            raise APIError(413, "Request body is too large", "payload_too_large")
        raw = self.rfile.read(length) if length else b"{}"
        self._raw_request_body = raw
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise APIError(400, "Request body must be valid JSON", "bad_json") from exc
        if not isinstance(data, dict):
            raise APIError(400, "Request body must be a JSON object", "bad_json")
        return data

    def _check_origin(self) -> None:
        origin = self.headers.get("Origin", "").strip().rstrip("/")
        referer = self.headers.get("Referer", "").strip()
        candidate = origin or (f"{urlsplit(referer).scheme}://{urlsplit(referer).netloc}" if referer else "")
        if not candidate:
            return
        allowed = configured_origins()
        host_origin = f"{urlsplit(candidate).scheme}://{self.headers.get('Host', '')}".rstrip("/")
        if candidate == host_origin or candidate in allowed:
            return
        raise APIError(403, "Cross-site request origin is not allowed", "csrf_origin_denied")

    def _common_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(self)")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self' https://*.supabase.co https://*.supabase.in; worker-src 'self' blob:")
        if secure_cookie_enabled():
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        self.send_header("X-Request-ID", self.headers.get("X-Request-ID", new_id("req"))[:100])

    def _json(self, status: int, payload: dict, *, cookie: str | None = None) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self._common_headers()
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(raw)

    def _error(self, error: APIError) -> None:
        payload = {"ok": False, "error": error.message, "code": error.code}
        details = getattr(error, "details", None)
        if details is not None:
            payload["details"] = details
        self._json(error.status, payload)

    def _require_user(self, conn: sqlite3.Connection) -> sqlite3.Row:
        row = current_user(conn, self)
        if row is None:
            raise APIError(401, "Sign in required", "unauthorized")
        return row

    def _api_health(self) -> None:
        self._json(200, {"ok": True, "service": "axiom-fleet-backend", "storage": "sqlite", "time": utc_now()})

    def _api_public_payment_link(self, method: str, route: str) -> None:
        code = route.rsplit('/', 1)[-1]
        data = self._read_json() if method == 'POST' else {}
        with db_connection() as conn:
            row = conn.execute("SELECT id, amount_paise, invoice_id, status, expires_at, provider_reference FROM domain_payment_links WHERE short_code = ?", (code,)).fetchone()
            if row is None:
                raise APIError(404, "Payment link not found", "not_found")
            if row["expires_at"] <= utc_now() and row["status"] != "paid":
                raise APIError(410, "Payment link has expired", "payment_link_expired")
            if method == "GET":
                self._json(200, {"ok": True, "item": {"id": row["id"], "amount_paise": row["amount_paise"], "invoice_id": row["invoice_id"], "status": row["status"], "expires_at": row["expires_at"]}})
                return
            if method != "POST" or data.get("action", "pay") != "pay":
                raise APIError(400, "Use action=pay to complete this link", "validation_error")
            if is_production() and os.environ.get("AXIOM_ALLOW_MOCK_PAYMENTS") != "1":
                raise APIError(503, "Payment provider is not configured", "payment_provider_required")
            if row["status"] != "paid":
                reference = f"mock_public_payment_{row['id'][-8:]}"
                conn.execute("UPDATE domain_payment_links SET status = 'paid', paid_at = ?, provider_reference = ? WHERE id = ?", (utc_now(), reference, row["id"]))
            else:
                reference = row["provider_reference"]
            self._json(200, {"ok": True, "status": "paid", "reference": reference})

    def _api_payment_webhook(self) -> None:
        payload = self._read_json()
        provider = clean_text(payload.get("provider"), "provider", maximum=40) or "payment_provider"
        raw = getattr(self, "_raw_request_body", b"{}")
        signature = self.headers.get("X-Payment-Signature") or self.headers.get("X-Webhook-Signature") or self.headers.get("X-Razorpay-Signature")
        timestamp = self.headers.get("X-Payment-Timestamp", "").strip()
        verified = False
        if not is_production() and provider == "mock_payment" and payload.get("signature") == "mock-signature":
            verified = True
        else:
            secret = os.environ.get("AXIOM_PAYMENT_WEBHOOK_SECRET", "")
            if not secret:
                raise APIError(503, "Payment webhook secret is not configured", "webhook_secret_required")
            if not signature:
                raise APIError(401, "Payment webhook signature is required", "invalid_webhook_signature")
            signed = f"{timestamp}.".encode("utf-8") + raw if timestamp else raw
            expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
            presented = signature.strip()
            if presented.startswith("sha256="):
                presented = presented[7:]
            elif "=" in presented:
                presented = presented.rsplit("=", 1)[-1]
            if timestamp:
                try:
                    if abs(int(timestamp) - int(time.time())) > 300:
                        raise APIError(401, "Payment webhook timestamp is outside the replay window", "stale_webhook")
                except ValueError as exc:
                    raise APIError(401, "Payment webhook timestamp is invalid", "invalid_webhook_timestamp") from exc
            verified = hmac.compare_digest(presented.lower(), expected.lower())
        if not verified:
            raise APIError(401, "Payment webhook signature is invalid", "invalid_webhook_signature")
        with db_connection() as conn:
            organization_id = clean_text(payload.get("organization_id"), "organization_id", maximum=160) or None
            if not organization_id and not is_production():
                session_user = current_user(conn, self)
                organization_id = session_user["organization_id"] if session_user else None
            if not organization_id:
                raise APIError(400, "organization_id is required for a payment webhook", "organization_required")
            payload["_signature_verified"] = True
            payload["provider"] = provider
            result = handle_verified_payment_webhook(conn, payload, organization_id, client_ip(self))
            self._json(200, result)

    def _api_password_reset(self) -> None:
        data = self._read_json()
        email = normalize_email(data.get("email"))
        if email:
            validate_email(email)
        with db_connection() as conn:
            enforce_rate_limit(conn, f"password-reset-ip:{client_ip(self)}", 10, LOGIN_FAILURE_WINDOW)
            if email:
                enforce_rate_limit(conn, f"password-reset-email:{email}", 5, LOGIN_FAILURE_WINDOW)
            row = conn.execute("SELECT id FROM users WHERE email = ? AND status = 'active'", (email,)).fetchone() if email else None
            if row:
                raw_token = secrets.token_urlsafe(32)
                conn.execute("UPDATE password_resets SET used_at = ? WHERE user_id = ? AND used_at IS NULL", (utc_now(), row["id"]))
                conn.execute("INSERT INTO password_resets(token_hash, user_id, created_at, expires_at, request_ip) VALUES (?, ?, ?, ?, ?)", (token_hash(raw_token), row["id"], utc_now(), utc_after_seconds(15 * 60), client_ip(self)))
                message = DEFAULT_PROVIDERS.messaging.send(channel="email", recipient=email, template="password_reset", variables={"reset_token": raw_token, "expires_minutes": 15}, idempotency_key=f"reset:{email}:{raw_token[:12]}")
                audit(conn, row["id"], "auth.password_reset_requested", "user", row["id"], client_ip(self), {"provider_reference": message.reference, "expires_minutes": 15})
                response = {"ok": True, "message": "If that address exists, a reset link will be sent shortly."}
                if os.environ.get("AXIOM_EXPOSE_RESET_TOKEN") == "1" and not is_production():
                    response["debug_token"] = raw_token
            else:
                response = {"ok": True, "message": "If that address exists, a reset link will be sent shortly."}
        self._json(202, response)

    def _api_password_reset_confirm(self) -> None:
        data = self._read_json()
        token = clean_text(data.get("token"), "token", required=True, maximum=256)
        password = str(data.get("password") or "")
        if len(password) < 8 or len(password) > 128:
            raise APIError(400, "Password must be between 8 and 128 characters", "validation_error")
        with db_connection() as conn:
            row = conn.execute("SELECT user_id FROM password_resets WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?", (token_hash(token), utc_now())).fetchone()
            if not row:
                raise APIError(400, "Reset link is invalid or expired", "invalid_reset_token")
            salt, password_digest = hash_password(password)
            conn.execute("UPDATE users SET password_hash = ?, password_salt = ?, last_login_at = NULL WHERE id = ?", (password_digest, salt, row["user_id"]))
            conn.execute("UPDATE password_resets SET used_at = ? WHERE token_hash = ?", (utc_now(), token_hash(token)))
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))
            audit(conn, row["user_id"], "auth.password_reset_confirmed", "user", row["user_id"], client_ip(self), {})
        self._json(200, {"ok": True, "message": "Password updated. Sign in with the new password."})

    def _api_signup(self) -> None:
        data = validate_signup(self._read_json())
        with db_connection() as conn:
            enforce_rate_limit(conn, f"signup-ip:{client_ip(self)}", 20, 60 * 60)
            if conn.execute("SELECT 1 FROM users WHERE email = ?", (data["email"],)).fetchone():
                raise APIError(409, "An account with this email already exists", "email_in_use")

            now = utc_now()
            organization_id = None
            if data["role"] in {"vendor", "corporate"}:
                organization_id = new_id("org")
                conn.execute(
                    """
                    INSERT INTO organizations(id, kind, name, phone, city, gstin, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (organization_id, data["role"], data["organization_name"], data["phone"], data["city"], data["gstin"], now),
                )

            user_id = new_id("usr")
            salt, password_digest = hash_password(data["password"])
            conn.execute(
                """
                INSERT INTO users(id, email, password_hash, password_salt, role, full_name, phone, organization_id, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (user_id, data["email"], password_digest, salt, data["role"], data["full_name"], data["phone"], organization_id, now),
            )
            conn.execute(
                """
                INSERT INTO profiles(user_id, city, timezone, license_number, fleet_size, employee_count, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, '{}')
                """,
                (user_id, data["city"], data["timezone"], data["license_number"], data["fleet_size"], data["employee_count"]),
            )
            audit(conn, user_id, "auth.signup", "user", user_id, self.client_address[0], {"role": data["role"]})
            session = create_session(conn, user_id, self)
            row = conn.execute(user_select_sql() + " WHERE u.id = ?", (user_id,)).fetchone()
            self._json(201, {"ok": True, "user": serialize_user(row), "access_token": session}, cookie=make_cookie(session))

    def _api_login(self) -> None:
        data = self._read_json()
        email = normalize_email(data.get("email"))
        password = str(data.get("password") or "")
        validate_email(email)
        if not password:
            raise APIError(400, "Password is required", "validation_error")
        failure_keys = login_keys(email, self)
        if any(locked_out(key) for key in failure_keys):
            raise APIError(429, "Too many failed attempts. Try again in 15 minutes.", "login_locked")

        with db_connection() as conn:
            enforce_rate_limit(conn, f"login-ip:{client_ip(self)}", 30, LOGIN_FAILURE_WINDOW)
            enforce_rate_limit(conn, f"login-email:{email}", 15, LOGIN_FAILURE_WINDOW)
            row = conn.execute(user_select_sql(include_password=True) + " WHERE u.email = ?", (email,)).fetchone()
            role = clean_text(data.get("role"), "role", maximum=20).lower() if data.get("role") else ""
            valid_role = not role or role in ROLES
            valid = row is not None and valid_role and verify_password(password, row["password_salt"], row["password_hash"])
            if not valid:
                for failure_key in failure_keys:
                    record_login_failure(failure_key)
                audit(conn, row["id"] if row else None, "auth.login_failed", "user", row["id"] if row else None, client_ip(self), {})
                raise APIError(401, "Email or password is incorrect", "invalid_credentials")

            for failure_key in failure_keys:
                clear_login_failures(failure_key)
            clear_rate_limit(conn, f"login-email:{email}")
            clear_rate_limit(conn, f"login-ip:{client_ip(self)}")
            now = utc_now()
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, row["id"]))
            audit(conn, row["id"], "auth.login", "user", row["id"], self.client_address[0], {"method": "password"})
            session = create_session(conn, row["id"], self)
            fresh = conn.execute(user_select_sql() + " WHERE u.id = ?", (row["id"],)).fetchone()
            self._json(200, {"ok": True, "user": serialize_user(fresh), "access_token": session}, cookie=make_cookie(session))

    def _api_me(self) -> None:
        with db_connection() as conn:
            row = self._require_user(conn)
            self._json(200, {"ok": True, "user": serialize_user(row)})

    def _api_update_me(self) -> None:
        data = self._read_json()
        with db_connection() as conn:
            row = self._require_user(conn)
            user_id = row["id"]
            user_updates: list[str] = []
            user_values: list[object] = []
            if "full_name" in data:
                user_updates.append("full_name = ?")
                user_values.append(clean_text(data.get("full_name"), "full_name", required=True, maximum=120))
            if "phone" in data:
                user_updates.append("phone = ?")
                user_values.append(clean_text(data.get("phone"), "phone", maximum=32))
            if user_updates:
                user_values.append(user_id)
                conn.execute(f"UPDATE users SET {', '.join(user_updates)} WHERE id = ?", user_values)

            profile_values = {
                "city": clean_text(data.get("city"), "city", maximum=80) if "city" in data else None,
                "timezone": validate_timezone(data.get("timezone"), required=True) if "timezone" in data else None,
                "license_number": clean_text(data.get("license_number"), "license_number", maximum=80).upper() if "license_number" in data else None,
                "fleet_size": optional_int(data.get("fleet_size"), "fleet_size") if "fleet_size" in data else None,
                "employee_count": optional_int(data.get("employee_count"), "employee_count") if "employee_count" in data else None,
            }
            if any(value is not None for value in profile_values.values()):
                conn.execute("INSERT OR IGNORE INTO profiles(user_id) VALUES (?)", (user_id,))
                assignments = []
                values: list[object] = []
                for key, value in profile_values.items():
                    if value is not None:
                        assignments.append(f"{key} = ?")
                        values.append(value)
                values.append(user_id)
                conn.execute(f"UPDATE profiles SET {', '.join(assignments)} WHERE user_id = ?", values)

            if row["organization_id"] and any(key in data for key in ("organization_name", "gstin", "organization_city")):
                org_updates = []
                org_values: list[object] = []
                if "organization_name" in data:
                    org_updates.append("name = ?")
                    org_values.append(clean_text(data.get("organization_name"), "organization_name", required=True, maximum=160))
                if "gstin" in data:
                    org_updates.append("gstin = ?")
                    org_values.append(clean_text(data.get("gstin"), "gstin", maximum=32).upper())
                if "organization_city" in data:
                    org_updates.append("city = ?")
                    org_values.append(clean_text(data.get("organization_city"), "organization_city", maximum=80))
                if org_updates:
                    org_values.append(row["organization_id"])
                    conn.execute(f"UPDATE organizations SET {', '.join(org_updates)} WHERE id = ?", org_values)

            audit(conn, user_id, "profile.update", "user", user_id, self.client_address[0], {"fields": sorted(data.keys())})
            fresh = conn.execute(user_select_sql() + " WHERE u.id = ?", (user_id,)).fetchone()
            self._json(200, {"ok": True, "user": serialize_user(fresh)})

    def _api_logout(self) -> None:
        token = request_token(self)
        with db_connection() as conn:
            row = current_user(conn, self)
            if token:
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
            if row:
                audit(conn, row["id"], "auth.logout", "user", row["id"], self.client_address[0], {})
            self._json(200, {"ok": True}, cookie=clear_cookie())

    def _api_public_corporate_duty_slip(self, method: str) -> None:
        payload = self._read_json() if method == "POST" else {}
        try:
            with db_connection() as conn:
                result = handle_corporate_public(conn, method, self.path, payload, self.client_address[0])
                if result is None:
                    raise APIError(404, "Signed duty-slip action not found", "not_found")
                self._json(200, result)
        except (APIError, DomainError) as error:
            self._error(error)
        except Exception:
            self._error(APIError(500, "The signed action could not be completed", "server_error"))

    def _api_public_enterprise(self, method: str) -> None:
        payload = self._read_json() if method in {"POST", "PATCH"} else {}
        try:
            with db_connection() as conn:
                result = handle_enterprise_public(conn, method, self.path, payload, self.client_address[0])
                if result is None:
                    raise APIError(404, "Public enterprise route not found", "not_found")
                self._json(200, result)
        except (APIError, DomainError) as error:
            self._error(error)
        except sqlite3.IntegrityError:
            self._error(APIError(409, "This public request conflicts with an existing booking", "conflict"))
        except Exception:
            self._error(APIError(500, "The public workflow could not be completed", "server_error"))

    def _api_public_gap(self, method: str) -> None:
        payload = self._read_json() if method in {"POST", "PATCH"} else {}
        try:
            with db_connection() as conn:
                result = handle_gap_public(conn, method, self.path, payload, self.client_address[0])
                if result is None:
                    raise APIError(404, "Public location-share route not found", "not_found")
                self._json(200, result)
        except (APIError, DomainError) as error:
            self._error(error)
        except Exception:
            self._error(APIError(500, "The public location workflow could not be completed", "server_error"))

    def _api_public_feedback(self, method: str) -> None:
        payload = self._read_json() if method in {"POST", "PATCH"} else {}
        try:
            with db_connection() as conn:
                result = handle_finance_controls_public(conn, method, self.path, payload, self.client_address[0])
                if result is None:
                    raise APIError(404, "Public feedback route not found", "not_found")
                self._json(200, result)
        except (APIError, DomainError) as error:
            self._error(error)
        except sqlite3.IntegrityError:
            self._error(APIError(409, "Feedback has already been submitted", "conflict"))
        except Exception:
            self._error(APIError(500, "The public feedback workflow could not be completed", "server_error"))

    def _api_domain(self, method: str) -> None:
        payload = self._read_json() if method in {"POST", "PATCH", "DELETE"} else {}
        with db_connection() as conn:
            user = self._require_user(conn)
            route = urlsplit(self.path).path.rstrip("/") or "/"
            mutation = method in {"POST", "PATCH", "DELETE"}
            before_audit = conn.execute("SELECT id FROM audit_events WHERE user_id = ? ORDER BY rowid DESC LIMIT 1", (user["id"],)).fetchone() if mutation else None
            corporate_evaluation = None
            if method == "POST" and route == "/api/bookings":
                corporate_evaluation = evaluate_corporate_booking_write(conn, user, payload, "book", self.client_address[0])
            else:
                cancel_match = re.match(r"^/api/bookings/([^/]+)/cancel$", route)
                if method == "POST" and cancel_match:
                    booking_for_cancel = conn.execute("SELECT * FROM domain_bookings WHERE id = ? AND organization_id = ?", (cancel_match.group(1), user["organization_id"])).fetchone()
                    if booking_for_cancel:
                        corporate_evaluation = evaluate_corporate_booking_write(conn, user, payload, "cancel", self.client_address[0], booking_for_cancel)
                decision_match = re.match(r"^/api/bookings/([^/]+)/(approve|confirm|reject)$", route)
                if method == "POST" and decision_match:
                    require_corporate_booking_permission(conn, user, "booking.approve")
            if corporate_evaluation and corporate_evaluation.get("outcome") == "block":
                raise DomainError(409, "Corporate booking policy blocked this request", "corporate_policy_blocked", corporate_evaluation)
            booking_approval_route = re.match(r"^/api/bookings/([^/]+)/approve$", route)
            booking_approval_created = bool(booking_approval_route and conn.execute("SELECT 1 FROM domain_booking_approvals WHERE organization_id = ? AND booking_id = ? AND status = 'pending' LIMIT 1", (user["organization_id"], booking_approval_route.group(1))).fetchone()) if user["organization_id"] else False
            # Network owns its role guard before generic domain handlers. This
            # keeps a driver account from being misreported as organization-
            # missing when it attempts a closed Network route.
            result = handle_network(conn, user, method, self.path, payload, self.client_address[0]) if route.startswith("/api/network/v1") else None
            result = result if result is not None else handle_bill_intelligence(conn, user, method, self.path, payload, self.client_address[0])
            if result is None:
                result = handle_corporate(conn, user, method, self.path, payload, self.client_address[0])
            if result is None:
                result = handle_enterprise_controls(conn, user, method, self.path, payload, self.client_address[0])
            if result is None:
                result = handle_command_center(conn, user, method, self.path, payload, self.client_address[0])
            if result is None:
                result = handle_gap_completion(conn, user, method, self.path, payload, self.client_address[0])
            if result is None:
                result = handle_booking_parity(conn, user, method, self.path, payload, self.client_address[0])
            if result is None:
                result = handle_finance_controls(conn, user, method, self.path, payload, self.client_address[0])
            if result is None:
                result = handle_operations_parity(conn, user, method, self.path, payload, self.client_address[0])
            if result is None:
                result = handle_finance_parity(conn, user, method, self.path, payload, self.client_address[0])
            if result is None:
                result = handle_communications(conn, user, method, self.path, payload, self.client_address[0])
            if result is None:
                result = handle_supplier_finance(conn, user, method, self.path, payload, self.client_address[0])
            if result is None:
                result = handle_feedback(conn, user, method, self.path, payload, self.client_address[0])
            if result is None:
                result = handle_phase3(conn, user, method, self.path, payload, self.client_address[0])
            if result is None:
                result = handle_phase12(conn, user, method, self.path, payload, self.client_address[0])
            if result is None:
                result = handle_p0(conn, user, method, self.path, payload, self.client_address[0])
            if result is None:
                result = handle_network(conn, user, method, self.path, payload, self.client_address[0])
            if result is None:
                result = handle_extended(conn, user, method, self.path, payload, self.client_address[0])
            if result is None:
                result = handle_feature(conn, user, method, self.path, payload, self.client_address[0])
            if result is None:
                result = handle_domain(conn, user, method, self.path, payload, self.client_address[0])
            if result is not None and corporate_evaluation and route == "/api/bookings" and method == "POST" and corporate_evaluation.get("outcome") == "needs_approval":
                created_booking_id = (result.get("item") or {}).get("id") if isinstance(result, dict) else None
                if created_booking_id:
                    applied_evaluation = apply_corporate_booking_decision(conn, user, created_booking_id, corporate_evaluation, self.client_address[0])
                    result = {**result, "item": {**result["item"], "status": "pending_approval"}, "corporate_evaluation": applied_evaluation}
            if result is not None and method == "PATCH" and route.startswith("/api/duties/") and route.count("/") == 3 and str(payload.get("status") or "").lower() == "completed":
                duty_id = route.split("/")[3]
                slip = maybe_create_duty_slip_approval(conn, user, duty_id, self.client_address[0])
                if slip:
                    result = {**result, "duty_slip_approval": slip}
            if mutation and isinstance(result, dict):
                latest = conn.execute("SELECT id FROM audit_events WHERE user_id = ? ORDER BY rowid DESC LIMIT 1", (user["id"],)).fetchone()
                if latest is None or (before_audit and latest["id"] == before_audit["id"]):
                    audit(conn, user["id"], "mutation.completed", "http_mutation", route, self.client_address[0], {"method": method})
                    latest = conn.execute("SELECT id FROM audit_events WHERE user_id = ? ORDER BY rowid DESC LIMIT 1", (user["id"],)).fetchone()
                result = {**result, "audit_reference": result.get("audit_reference") or (latest["id"] if latest else None), "request_reference": self.headers.get("X-Request-ID") or new_id("req")}
            created = method == "POST" and not route.startswith("/api/network/v1") and (route in {"/api/customers", "/api/drivers", "/api/vehicles", "/api/bookings", "/api/bookings/batches", "/api/duties", "/api/invoices", "/api/payments", "/api/branches", "/api/suppliers", "/api/price-books", "/api/employees", "/api/policies", "/api/documents", "/api/invitations", "/api/notifications", "/api/tickets", "/api/privacy/requests", "/api/bill-intelligence", "/api/availability", "/api/corporate/account", "/api/corporate/account/setup", "/api/corporate/account/activate", "/api/corporate/users", "/api/corporate/policies", "/api/corporate/duty-slip-approvals", "/api/corporate/masters", "/api/corporate/allotment/rules", "/api/supplier-payment-requests", "/api/supplier-advances", "/api/supplier-settlement-approvals", "/api/driver-payouts/requests", "/api/payroll/exports", "/api/payroll/compliance", "/api/fuel-stations", "/api/fuel-prices", "/api/petty-cash/reconciliations", "/api/finance/reconciliations", "/api/reports/builder", "/api/reports/favorites", "/api/reports/exports", "/api/reporting/import-templates", "/api/imports/preview", "/api/feedback/public-links", "/api/feedback/notifications", "/api/feedback/corrective-actions"} or route.endswith(("/proof", "/track", "/expenses", "/items", "/allot")) or (route.startswith("/api/duties/") and route.endswith("/close")) or booking_approval_created)
            self._json(201 if created else 200, result)

    def _handle_api(self, method: str) -> None:
        route = urlsplit(self.path).path.rstrip("/") or "/"
        try:
            self._check_origin()
        except APIError as error:
            self._error(error)
            return
        if method == "OPTIONS":
            self.send_response(204)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Request-ID")
            self.send_header("Content-Length", "0")
            self._common_headers()
            self.end_headers()
            return

        try:
            if route == "/api/health" and method == "GET":
                self._api_health()
            elif route == "/api/auth/signup" and method == "POST":
                self._api_signup()
            elif route == "/api/auth/login" and method == "POST":
                self._api_login()
            elif route == "/api/auth/password-reset" and method == "POST":
                self._api_password_reset()
            elif route == "/api/auth/password-reset/confirm" and method == "POST":
                self._api_password_reset_confirm()
            elif route == "/api/auth/me" and method == "GET":
                self._api_me()
            elif route == "/api/auth/me" and method == "PATCH":
                self._api_update_me()
            elif route == "/api/auth/logout" and method == "POST":
                self._api_logout()
            elif route == "/api/webhooks/payments" and method == "POST":
                self._api_payment_webhook()
            elif route.startswith("/api/public/payment-links/") and method in {"GET", "POST"}:
                self._api_public_payment_link(method, route)
            elif re.match(r"^/api/corporate/duty-slip-approvals/[^/]+/action$", route) and method in {"GET", "POST"}:
                self._api_public_corporate_duty_slip(method)
            elif re.match(r"^/api/passenger/v1/portal/[^/]+$", route) or re.match(r"^/api/duty-close/v1/[^/]+$", route):
                self._api_public_enterprise(method)
            elif re.match(r"^/api/location-shares/[^/]+$", route):
                self._api_public_gap(method)
            elif re.match(r"^/api/feedback/v1/[^/]+$", route):
                self._api_public_feedback(method)
            elif route.startswith(("/api/overview",  "/api/customers", "/api/drivers", "/api/vehicles", "/api/bookings", "/api/duties", "/api/invoices", "/api/payments", "/api/sync", "/api/branches", "/api/suppliers", "/api/price-books", "/api/documents", "/api/invitations", "/api/employees", "/api/policies", "/api/approvals", "/api/notifications", "/api/reports", "/api/audit", "/api/tickets", "/api/privacy", "/api/integrations", "/api/organization", "/api/settings", "/api/onboarding", "/api/setup", "/api/duplicates", "/api/receipts", "/api/supplier-bills", "/api/costs", "/api/vehicle-costs", "/api/supplier-payouts", "/api/driver-payouts", "/api/financial-actions", "/api/reconciliations", "/api/approval-steps", "/api/admin", "/api/network", "/api/alerts", "/api/geofences", "/api/passenger", "/api/devices", "/api/practice-duties", "/api/webhooks", "/api/trips", "/api/updates", "/api/sla", "/api/tax", "/api/capacity", "/api/availability", "/api/allotment", "/api/billing-notes", "/api/payment-links", "/api/payment-authorizations", "/api/auto-collect", "/api/invoice-automation", "/api/provider-connections", "/api/maps", "/api/driver", "/api/driver-alert-policies", "/api/jobs", "/api/security", "/api/masters", "/api/operations", "/api/safety", "/api/permissions", "/api/mobile", "/api/views", "/api/bill-intelligence", "/api/corporate", "/api/enterprise", "/api/duty-closure-jobs", "/api/phase3", "/api/invoice-runs", "/api/collections", "/api/export-profiles", "/api/workspace", "/api/finance", "/api/communications", "/api/supplier-purchases", "/api/supplier-ageing", "/api/supplier-settlements", "/api/supplier-payment-requests", "/api/supplier-advances", "/api/supplier-settlement-approvals", "/api/fuel-entries", "/api/fuel-stations", "/api/fuel-prices", "/api/fuel-analytics", "/api/petty-cash", "/api/driver-allowances", "/api/payroll", "/api/reporting", "/api/imports", "/api/feedback")):
                self._api_domain(method)
            else:
                raise APIError(404, "API route not found", "not_found")
        except (APIError, DomainError) as error:
            self._error(error)
        except sqlite3.IntegrityError:
            self._error(APIError(409, "That account information is already in use", "conflict"))
        except Exception:
            # Do not expose implementation details or credential material.
            self._error(APIError(500, "The backend could not complete that request", "server_error"))

    def _public_path(self) -> Path | None:
        requested = urlsplit(self.path).path
        raw_path = Path(self.translate_path(requested)).resolve()
        try:
            relative = raw_path.relative_to(ROOT.resolve()).as_posix()
        except ValueError:
            return None
        if raw_path.is_dir():
            relative = "" if relative == "." else relative
            relative = f"{relative.rstrip('/')}/index.html" if relative else "index.html"
            raw_path = (ROOT / relative).resolve()
        if relative in PUBLIC_FILES:
            return raw_path
        parts = relative.split("/")
        if parts and parts[0] in PUBLIC_PREFIXES and raw_path.suffix.lower() in PUBLIC_EXTENSIONS:
            return raw_path
        return None

    def list_directory(self, path: str):  # noqa: N802 - stdlib handler API
        self.send_error(404, "Directory listing is disabled")
        return None

    def _serve_file(self, head_only: bool = False) -> None:
        path = self._public_path()
        if path is None or not path.is_file():
            self.send_error(404, "File not found")
            return

        stat_result = path.stat()
        mtime_ns = stat_result.st_mtime_ns
        size = stat_result.st_size
        etag = f'"{mtime_ns:x}-{size:x}"'
        accepts_gzip = "gzip" in self.headers.get("Accept-Encoding", "").lower()
        use_gzip = accepts_gzip and path.suffix.lower() in COMPRESSIBLE
        last_modified = email.utils.formatdate(stat_result.st_mtime, usegmt=True)

        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Last-Modified", last_modified)
            self.send_header("Cache-Control", "public, max-age=3600")
            self._common_headers()
            if use_gzip:
                self.send_header("Vary", "Accept-Encoding")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        body = static_body(str(path), mtime_ns, size, use_gzip)
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(str(path)))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", etag)
        self.send_header("Last-Modified", last_modified)
        self.send_header("Cache-Control", "public, max-age=3600")
        self._common_headers()
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self._is_api():
            self._handle_api("GET")
        else:
            self._serve_file(head_only=False)

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler API
        if self._is_api():
            self._handle_api("GET")
        else:
            self._serve_file(head_only=True)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if self._is_api():
            self._handle_api("POST")
        else:
            self.send_error(405, "Method Not Allowed")

    def do_PATCH(self) -> None:  # noqa: N802 - stdlib handler API
        if self._is_api():
            self._handle_api("PATCH")
        else:
            self.send_error(405, "Method Not Allowed")

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib handler API
        if self._is_api():
            self._handle_api("DELETE")
        else:
            self.send_error(405, "Method Not Allowed")

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler API
        if self._is_api():
            self._handle_api("OPTIONS")
        else:
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()


class AxiomFleetHTTPServer(ThreadingHTTPServer):
    """Threaded local server with enough accept backlog for dashboard bursts."""

    allow_reuse_address = True
    request_queue_size = 128


def main() -> None:
    initialize_database()
    port = int(os.environ.get("PORT", "4173"))
    handler = partial(AxiomFleetHandler, directory=str(ROOT))
    server = AxiomFleetHTTPServer(("0.0.0.0", port), handler)
    print(f"Axiom Fleet backend listening on 0.0.0.0:{port} · SQLite at {DB_PATH}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
