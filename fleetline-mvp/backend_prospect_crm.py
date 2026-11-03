"""Axiom Mobility (Fleetline) - Prospect CRM, SaaS Dunning & Corporate Annexure Portal.

Modules:
1. Prospect Capture CRM & 1-Click Tenant Onboarding Pipeline.
2. Automated SaaS Dunning, Balance Ledger & 3-Stage Blocking Engine.
3. Zero-Login Corporate Proforma Annexure & Trip-Sheet Verification Portal.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import secrets
import sqlite3
from typing import Any, Dict, List, Optional

from backend_domain import DomainError


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ensure_column(conn: sqlite3.Connection, table: str, col: str, col_def: str) -> None:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    cols = {row[1] for row in cursor.fetchall()}
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")


def initialize_prospect_crm_schema(conn: sqlite3.Connection) -> None:
    """Ensure all SQLite tables for Prospect CRM, Dunning, and Corporate Annexure exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sales_prospects (
            id TEXT PRIMARY KEY,
            full_name TEXT NOT NULL,
            company_name TEXT NOT NULL,
            mobile_number TEXT NOT NULL,
            email_id TEXT NOT NULL,
            city TEXT NOT NULL DEFAULT 'Bengaluru',
            fleet_size_estimate INTEGER NOT NULL DEFAULT 5,
            interest_type TEXT NOT NULL DEFAULT 'VENDOR_SAAS',
            lead_source TEXT NOT NULL DEFAULT 'WEBSITE_FORM',
            status TEXT NOT NULL DEFAULT 'NEW_PROSPECT',
            assigned_sales_rep_id TEXT,
            call_notes_jsonb TEXT NOT NULL DEFAULT '[]',
            converted_tenant_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sales_prospects_email ON sales_prospects(email_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sales_prospects_mobile ON sales_prospects(mobile_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sales_prospects_status ON sales_prospects(status)")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS tenant_platform_invoices (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            invoice_number TEXT NOT NULL,
            billing_period TEXT NOT NULL,
            saas_base_fee_inr REAL NOT NULL DEFAULT 0.0,
            trip_overage_fee_inr REAL NOT NULL DEFAULT 0.0,
            total_amount_due_inr REAL NOT NULL DEFAULT 0.0,
            amount_paid_inr REAL NOT NULL DEFAULT 0.0,
            balance_owed_inr REAL NOT NULL DEFAULT 0.0,
            due_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'UNPAID',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tenant_platform_invoices_tenant ON tenant_platform_invoices(tenant_id, status)")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS proforma_annexure_shares (
            id TEXT PRIMARY KEY,
            proforma_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            token TEXT NOT NULL UNIQUE,
            corporate_name TEXT NOT NULL,
            corporate_email TEXT,
            expires_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
            approved_duty_ids_json TEXT NOT NULL DEFAULT '[]',
            flagged_duty_ids_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_proforma_shares_token ON proforma_annexure_shares(token)")

    # Ensure 3-stage access control columns on tenant_billing_accounts if table exists
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tenant_billing_accounts'")
    if cursor.fetchone():
        _ensure_column(conn, "tenant_billing_accounts", "access_control_state", "TEXT NOT NULL DEFAULT 'ACTIVE_GOOD_STANDING'")
        _ensure_column(conn, "tenant_billing_accounts", "saas_balance_owed_inr", "REAL NOT NULL DEFAULT 0.0")
        _ensure_column(conn, "tenant_billing_accounts", "dunning_stage", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "tenant_billing_accounts", "trial_ends_at", "TEXT")
        _ensure_column(conn, "tenant_billing_accounts", "trial_trips_quota", "INTEGER DEFAULT 100")
        _ensure_column(conn, "tenant_billing_accounts", "payout_hold_override", "TEXT DEFAULT 'RELEASE_READY'")


# -----------------------------------------------------------------------------
# Module 2: Prospect Capture & Tenant Onboarding
# -----------------------------------------------------------------------------

def capture_public_prospect(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
    full_name = str(payload.get("full_name") or "").strip()
    company_name = str(payload.get("company_name") or "").strip()
    mobile_number = str(payload.get("mobile_number") or "").strip()
    email_id = str(payload.get("email_id") or "").strip().lower()
    city = str(payload.get("city") or "Bengaluru").strip()
    fleet_size = int(payload.get("fleet_size_estimate") or 5)
    interest_type = str(payload.get("interest_type") or "VENDOR_SAAS").strip()

    if not full_name or not mobile_number or not email_id:
        raise DomainError(422, "full_name, mobile_number, and email_id are required", "validation_error")

    now = utc_now()
    # Check deduplication by mobile or email
    existing = conn.execute(
        "SELECT * FROM sales_prospects WHERE email_id = ? OR mobile_number = ?",
        (email_id, mobile_number),
    ).fetchone()

    if existing:
        existing_dict = dict(existing)
        conn.execute(
            """UPDATE sales_prospects
               SET full_name = ?, company_name = ?, city = ?, fleet_size_estimate = ?, interest_type = ?, updated_at = ?
               WHERE id = ?""",
            (full_name, company_name or existing_dict["company_name"], city, fleet_size, interest_type, now, existing_dict["id"]),
        )
        return {
            "success": True,
            "deduplicated": True,
            "prospect_id": existing_dict["id"],
            "status": existing_dict["status"],
            "message": "Existing prospect record updated with new details.",
        }

    prospect_id = f"pros_{secrets.token_hex(6)}"
    conn.execute(
        """INSERT INTO sales_prospects (
            id, full_name, company_name, mobile_number, email_id, city,
            fleet_size_estimate, interest_type, lead_source, status, call_notes_jsonb, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'WEBSITE_FORM', 'NEW_PROSPECT', '[]', ?, ?)""",
        (prospect_id, full_name, company_name or f"{full_name} Fleet", mobile_number, email_id, city, fleet_size, interest_type, now, now),
    )

    # Sync into prospects table if it exists
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='prospects'")
    if cursor.fetchone():
        try:
            conn.execute(
                """INSERT OR IGNORE INTO prospects (
                    id, company_name, contact_name, email, phone, city, fleet_size, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (prospect_id, company_name or f"{full_name} Fleet", full_name, email_id, mobile_number, city, fleet_size, now, now),
            )
        except Exception:
            pass

    return {
        "success": True,
        "deduplicated": False,
        "prospect_id": prospect_id,
        "status": "NEW_PROSPECT",
        "message": "Prospect lead successfully captured.",
    }


def list_prospects(conn: sqlite3.Connection, query: Optional[str] = None, status: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM sales_prospects WHERE 1=1"
    params: List[Any] = []
    if status:
        sql += " AND status = ?"
        params.append(status)
    if query:
        sql += " AND (full_name LIKE ? OR company_name LIKE ? OR email_id LIKE ? OR mobile_number LIKE ?)"
        q_wild = f"%{query}%"
        params.extend([q_wild, q_wild, q_wild, q_wild])
    sql += " ORDER BY created_at DESC"

    rows = conn.execute(sql, tuple(params)).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        try:
            d["call_notes"] = json.loads(d.get("call_notes_jsonb") or "[]")
        except Exception:
            d["call_notes"] = []
        results.append(d)
    return results


def add_prospect_note(conn: sqlite3.Connection, prospect_id: str, note_text: str, author: str = "Sales Team") -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM sales_prospects WHERE id = ?", (prospect_id,)).fetchone()
    if not row:
        raise DomainError(404, "Prospect not found", "not_found")

    d = dict(row)
    try:
        notes = json.loads(d.get("call_notes_jsonb") or "[]")
    except Exception:
        notes = []

    now = utc_now()
    notes.append({
        "id": f"note_{secrets.token_hex(4)}",
        "author": author,
        "note": note_text,
        "timestamp": now,
    })

    conn.execute(
        "UPDATE sales_prospects SET call_notes_jsonb = ?, status = 'CONTACTED_QUERYING', updated_at = ? WHERE id = ?",
        (json.dumps(notes), now, prospect_id),
    )
    return {"success": True, "notes": notes, "status": "CONTACTED_QUERYING"}


def convert_prospect_to_tenant(conn: sqlite3.Connection, prospect_id: str) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM sales_prospects WHERE id = ?", (prospect_id,)).fetchone()
    if not row:
        raise DomainError(404, "Prospect not found", "not_found")
    p = dict(row)

    if p.get("status") == "ONBOARDED_CONVERTED" and p.get("converted_tenant_id"):
        return {
            "success": True,
            "already_converted": True,
            "tenant_id": p["converted_tenant_id"],
            "company_name": p["company_name"],
            "message": "Prospect already converted into active tenant.",
        }

    now_dt = dt.datetime.now(dt.timezone.utc)
    trial_ends = (now_dt + dt.timedelta(days=14)).isoformat().replace("+00:00", "Z")
    slug = re.sub(r"[^a-z0-9]+", "-", p["company_name"].lower()).strip("-")
    tenant_id = f"org_{slug}_{secrets.token_hex(3)}"

    now = utc_now()

    # 1. Ensure organizations row exists
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='organizations'")
    if cursor.fetchone():
        conn.execute(
            """INSERT OR IGNORE INTO organizations (id, name, slug, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (tenant_id, p["company_name"], slug, now, now),
        )

    # 2. Provision tenant_billing_accounts with 14-day trial & 100 trips quota
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tenant_billing_accounts'")
    if cursor.fetchone():
        conn.execute(
            """INSERT OR REPLACE INTO tenant_billing_accounts (
                tenant_id, tenant_name, account_status, access_control_state, saas_balance_owed_inr,
                dunning_stage, trial_ends_at, trial_trips_quota, payout_hold_override, created_at, updated_at
            ) VALUES (?, ?, 'ACTIVE', 'ACTIVE_GOOD_STANDING', 0.0, 0, ?, 100, 'RELEASE_READY', ?, ?)""",
            (tenant_id, p["company_name"], trial_ends, now, now),
        )

    # 3. Seed default corporate rate card items for the new tenant
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='domain_price_book_items'")
    if cursor.fetchone():
        defaults = [
            ("SEDAN", "LOCAL_4HR_40KM", 1600.0, 14.0, 120.0),
            ("SEDAN", "LOCAL_8HR_80KM", 2800.0, 14.0, 120.0),
            ("SEDAN", "AIRPORT_TRANSFER", 1450.0, 14.0, 120.0),
            ("SUV_CRYSTA", "LOCAL_8HR_80KM", 4200.0, 22.0, 180.0),
        ]
        for v_cat, d_type, base_fare, per_km, per_hr in defaults:
            conn.execute(
                """INSERT OR IGNORE INTO domain_price_book_items (
                    id, organization_id, vehicle_category, duty_type, base_fare, per_km_rate, per_minute_rate, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (f"pbi_{secrets.token_hex(6)}", tenant_id, v_cat, d_type, base_fare, per_km, per_hr / 60.0, now),
            )

    # 4. Update sales_prospects status
    conn.execute(
        """UPDATE sales_prospects
           SET status = 'ONBOARDED_CONVERTED', converted_tenant_id = ?, updated_at = ?
           WHERE id = ?""",
        (tenant_id, now, prospect_id),
    )

    return {
        "success": True,
        "tenant_id": tenant_id,
        "tenant_name": p["company_name"],
        "primary_contact": {
            "name": p["full_name"],
            "email": p["email_id"],
            "mobile": p["mobile_number"],
        },
        "trial_ends_at": trial_ends,
        "trial_trips_quota": 100,
        "access_control_state": "ACTIVE_GOOD_STANDING",
        "message": f"Tenant {p['company_name']} provisioned with 14-day / 100-trip trial.",
    }


# -----------------------------------------------------------------------------
# Module 3: Automated SaaS Dunning & 3-Stage Access Control
# -----------------------------------------------------------------------------

def get_tenant_billing_overview(conn: sqlite3.Connection, tenant_id: str) -> Dict[str, Any]:
    account = conn.execute(
        "SELECT * FROM tenant_billing_accounts WHERE tenant_id = ?",
        (tenant_id,),
    ).fetchone()

    invoices = conn.execute(
        "SELECT * FROM tenant_platform_invoices WHERE tenant_id = ? ORDER BY due_date DESC",
        (tenant_id,),
    ).fetchall()

    acc_dict = dict(account) if account else {
        "tenant_id": tenant_id,
        "access_control_state": "ACTIVE_GOOD_STANDING",
        "saas_balance_owed_inr": 0.0,
        "dunning_stage": 0,
        "payout_hold_override": "RELEASE_READY",
    }

    inv_list = [dict(inv) for inv in invoices]
    total_balance = sum(inv.get("balance_owed_inr", 0.0) for inv in inv_list if inv.get("status") in {"UNPAID", "OVERDUE", "PARTIALLY_PAID"})

    return {
        "tenant_id": tenant_id,
        "tenant_name": acc_dict.get("tenant_name", tenant_id),
        "access_control_state": acc_dict.get("access_control_state", "ACTIVE_GOOD_STANDING"),
        "saas_balance_owed_inr": total_balance or float(acc_dict.get("saas_balance_owed_inr", 0.0)),
        "dunning_stage": acc_dict.get("dunning_stage", 0),
        "payout_hold_override": acc_dict.get("payout_hold_override", "RELEASE_READY"),
        "trial_ends_at": acc_dict.get("trial_ends_at"),
        "trial_trips_quota": acc_dict.get("trial_trips_quota", 100),
        "invoices": inv_list,
    }


def create_tenant_platform_invoice(conn: sqlite3.Connection, tenant_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    saas_base = float(payload.get("saas_base_fee_inr") or 0.0)
    trip_overage = float(payload.get("trip_overage_fee_inr") or 0.0)
    total_due = saas_base + trip_overage
    due_date = str(payload.get("due_date") or "").strip()
    if not due_date:
        due_date = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7)).isoformat().replace("+00:00", "Z")
    billing_period = str(payload.get("billing_period") or dt.datetime.now(dt.timezone.utc).strftime("%b %Y"))

    now = utc_now()
    inv_id = f"pinv_{secrets.token_hex(6)}"
    inv_num = f"AX-SAAS-{secrets.token_hex(4).upper()}"

    conn.execute(
        """INSERT INTO tenant_platform_invoices (
            id, tenant_id, invoice_number, billing_period, saas_base_fee_inr,
            trip_overage_fee_inr, total_amount_due_inr, amount_paid_inr, balance_owed_inr,
            due_date, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0.0, ?, ?, 'UNPAID', ?, ?)""",
        (inv_id, tenant_id, inv_num, billing_period, saas_base, trip_overage, total_due, total_due, due_date, now, now),
    )

    # Update balance on tenant account
    conn.execute(
        """UPDATE tenant_billing_accounts
           SET saas_balance_owed_inr = COALESCE(saas_balance_owed_inr, 0.0) + ?, updated_at = ?
           WHERE tenant_id = ?""",
        (total_due, now, tenant_id),
    )

    return {
        "success": True,
        "invoice_id": inv_id,
        "invoice_number": inv_num,
        "total_amount_due_inr": total_due,
        "balance_owed_inr": total_due,
        "status": "UNPAID",
        "due_date": due_date,
    }


def update_tenant_access_control(conn: sqlite3.Connection, tenant_id: str, access_control_state: str, reason: str = "") -> Dict[str, Any]:
    valid_states = {"ACTIVE_GOOD_STANDING", "SOFT_LOCKED_OVERDUE", "HARD_BLOCKED_NON_PAYMENT"}
    if access_control_state not in valid_states:
        raise DomainError(422, f"Invalid access_control_state. Must be one of {valid_states}", "invalid_state")

    now = utc_now()
    # Map to commercial account_status
    if access_control_state == "ACTIVE_GOOD_STANDING":
        account_status = "ACTIVE"
        payout_override = "RELEASE_READY"
        dunning_stage = 0
    elif access_control_state == "SOFT_LOCKED_OVERDUE":
        account_status = "SOFT_BLOCKED"
        payout_override = "FORCE_HOLD"
        dunning_stage = 1
    else:  # HARD_BLOCKED_NON_PAYMENT
        account_status = "HARD_BLOCKED"
        payout_override = "FORCE_HOLD"
        dunning_stage = 2

    conn.execute(
        """UPDATE tenant_billing_accounts
           SET access_control_state = ?, account_status = ?, payout_hold_override = ?,
               dunning_stage = ?, block_reason = ?, updated_at = ?
           WHERE tenant_id = ?""",
        (access_control_state, account_status, payout_override, dunning_stage, reason or access_control_state, now, tenant_id),
    )

    return {
        "success": True,
        "tenant_id": tenant_id,
        "access_control_state": access_control_state,
        "account_status": account_status,
        "payout_hold_override": payout_override,
        "dunning_stage": dunning_stage,
        "message": f"Tenant {tenant_id} state set to {access_control_state}",
    }


# -----------------------------------------------------------------------------
# Module 4: Zero-Login Corporate Proforma Annexure Portal
# -----------------------------------------------------------------------------

def generate_proforma_share_link(conn: sqlite3.Connection, proforma_id: str, tenant_id: str, corporate_name: str, corporate_email: Optional[str] = None) -> Dict[str, Any]:
    token = secrets.token_urlsafe(24)
    now_dt = dt.datetime.now(dt.timezone.utc)
    expires_at = (now_dt + dt.timedelta(days=30)).isoformat().replace("+00:00", "Z")
    now = utc_now()
    share_id = f"share_{secrets.token_hex(6)}"

    conn.execute(
        """INSERT INTO proforma_annexure_shares (
            id, proforma_id, tenant_id, token, corporate_name, corporate_email,
            expires_at, status, approved_duty_ids_json, flagged_duty_ids_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING_REVIEW', '[]', '[]', ?, ?)""",
        (share_id, proforma_id, tenant_id, token, corporate_name, corporate_email, expires_at, now, now),
    )

    return {
        "success": True,
        "share_id": share_id,
        "token": token,
        "share_url": f"/billing/corporate-review/{token}",
        "expires_at": expires_at,
        "proforma_id": proforma_id,
        "corporate_name": corporate_name,
    }


def get_corporate_review_data(conn: sqlite3.Connection, token: str) -> Dict[str, Any]:
    share = conn.execute("SELECT * FROM proforma_annexure_shares WHERE token = ?", (token,)).fetchone()
    if not share:
        raise DomainError(404, "Invalid or expired annexure review link", "not_found")

    s = dict(share)
    now = utc_now()
    if s["expires_at"] < now:
        raise DomainError(410, "This proforma review link has expired", "link_expired")

    approved_ids = set(json.loads(s.get("approved_duty_ids_json") or "[]"))
    flagged_ids = set(json.loads(s.get("flagged_duty_ids_json") or "[]"))

    # Fetch associated duties for this proforma if duties table exists
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='duties'")
    duties_found = []
    if cursor.fetchone():
        duties = conn.execute(
            """SELECT id, booking_id, duty_date, vehicle_category, passenger_name, route_name,
                      practical_billable_km, practical_start_km, practical_end_km, practical_duration_mins,
                      estimated_distance_km, final_client_fare_inr, estimated_client_fare_inr,
                      closing_source, has_discrepancy, discrepancy_reason, physical_tripsheet_file_url
               FROM duties
               WHERE organization_id = ? OR proforma_id = ?
               LIMIT 25""",
            (s["tenant_id"], s["proforma_id"]),
        ).fetchall()
        duties_found = [dict(d) for d in duties]

    # If no duties linked in DB, provide realistic mock sample items for preview
    if not duties_found:
        duties_found = [
            {
                "id": "DUTY-701",
                "duty_date": "2026-11-01",
                "vehicle_category": "SEDAN",
                "passenger_name": "Rohan Deshmukh",
                "route_name": "Koramangala to Kempegowda Intl Airport (BLR)",
                "practical_billable_km": 42.5,
                "estimated_distance_km": 39.8,
                "practical_duration_mins": 78,
                "final_client_fare_inr": 1850.00,
                "closing_source": "DRIVER_APP_AUTO",
                "has_discrepancy": False,
                "physical_tripsheet_file_url": "https://storage.axiommobility.in/tripsheets/slip_701.png",
            },
            {
                "id": "DUTY-702",
                "duty_date": "2026-11-01",
                "vehicle_category": "SEDAN",
                "passenger_name": "Priya Sharma",
                "route_name": "Whitefield to Manyata Tech Park",
                "practical_billable_km": 28.0,
                "estimated_distance_km": 27.2,
                "practical_duration_mins": 62,
                "final_client_fare_inr": 1280.00,
                "closing_source": "DRIVER_APP_AUTO",
                "has_discrepancy": False,
                "physical_tripsheet_file_url": "https://storage.axiommobility.in/tripsheets/slip_702.png",
            },
            {
                "id": "DUTY-703",
                "duty_date": "2026-11-02",
                "vehicle_category": "SUV_CRYSTA",
                "passenger_name": "Ananya Sen (VIP)",
                "route_name": "Indiranagar to Electronic City Phase 1",
                "practical_billable_km": 34.0,
                "estimated_distance_km": 31.5,
                "practical_duration_mins": 85,
                "final_client_fare_inr": 2400.00,
                "closing_source": "PHYSICAL_TRIPSHEET_OVERRIDE",
                "has_discrepancy": True,
                "discrepancy_reason": "GPS_DROP_IN_BASEMENT",
                "physical_tripsheet_file_url": "https://storage.axiommobility.in/tripsheets/slip_703.png",
            },
            {
                "id": "DUTY-704",
                "duty_date": "2026-11-02",
                "vehicle_category": "SEDAN",
                "passenger_name": "Vikram Malhotra",
                "route_name": "Bellandur Outer Ring Road to BLR Airport",
                "practical_billable_km": 48.0,
                "estimated_distance_km": 46.0,
                "practical_duration_mins": 82,
                "final_client_fare_inr": 1950.00,
                "closing_source": "DRIVER_APP_AUTO",
                "has_discrepancy": False,
                "physical_tripsheet_file_url": "https://storage.axiommobility.in/tripsheets/slip_704.png",
            },
            {
                "id": "DUTY-705",
                "duty_date": "2026-11-03",
                "vehicle_category": "SEDAN",
                "passenger_name": "Karthik Nair",
                "route_name": "JP Nagar to MG Road",
                "practical_billable_km": 19.5,
                "estimated_distance_km": 14.2,
                "practical_duration_mins": 55,
                "final_client_fare_inr": 890.00,
                "closing_source": "DRIVER_APP_AUTO",
                "has_discrepancy": True,
                "discrepancy_reason": "EXTRA_CLIENT_DETOUR",
                "physical_tripsheet_file_url": "https://storage.axiommobility.in/tripsheets/slip_705.png",
            },
        ]

    for d in duties_found:
        d_id = str(d.get("id"))
        if d_id in approved_ids:
            d["review_status"] = "APPROVED"
        elif d_id in flagged_ids:
            d["review_status"] = "FLAGGED"
        else:
            d["review_status"] = "PENDING"

    total_amount = sum(float(d.get("final_client_fare_inr") or 0.0) for d in duties_found)
    total_km = sum(float(d.get("practical_billable_km") or 0.0) for d in duties_found)

    return {
        "proforma_id": s["proforma_id"],
        "token": token,
        "corporate_name": s["corporate_name"],
        "status": s["status"],
        "expires_at": s["expires_at"],
        "summary": {
            "total_duties": len(duties_found),
            "approved_count": len(approved_ids),
            "flagged_count": len(flagged_ids),
            "total_amount_inr": total_amount,
            "total_km": total_km,
        },
        "duties": duties_found,
    }


def decide_corporate_review(conn: sqlite3.Connection, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    share = conn.execute("SELECT * FROM proforma_annexure_shares WHERE token = ?", (token,)).fetchone()
    if not share:
        raise DomainError(404, "Invalid or expired annexure review link", "not_found")
    s = dict(share)

    approved_ids = list(payload.get("approved_duty_ids") or [])
    flagged_items = list(payload.get("flagged_duties") or [])  # list of {duty_id, dispute_reason, proposed_km}

    flagged_ids = [item.get("duty_id") if isinstance(item, dict) else item for item in flagged_items if item]

    now = utc_now()
    # Route flagged items into Maker-Checker / dispute queue
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='audit_events'")
    if cursor.fetchone():
        for item in flagged_items:
            d_id = item.get("duty_id") if isinstance(item, dict) else item
            reason = item.get("dispute_reason", "Corporate reviewer disputed meter reading/rate") if isinstance(item, dict) else "Corporate dispute"
            conn.execute(
                """INSERT INTO audit_events (
                    id, entity_type, entity_id, action, details_json, created_at
                ) VALUES (?, 'duty_dispute', ?, 'FLAGGED_BY_CORPORATE', ?, ?)""",
                (f"audit_{secrets.token_hex(6)}", str(d_id), json.dumps({"reason": reason, "token": token}), now),
            )

    new_status = "APPROVED_LOCKED" if (approved_ids and not flagged_ids) else "PARTIALLY_APPROVED"

    conn.execute(
        """UPDATE proforma_annexure_shares
           SET approved_duty_ids_json = ?, flagged_duty_ids_json = ?, status = ?, updated_at = ?
           WHERE token = ?""",
        (json.dumps(approved_ids), json.dumps(flagged_ids), new_status, now, token),
    )

    return {
        "success": True,
        "token": token,
        "status": new_status,
        "approved_count": len(approved_ids),
        "flagged_count": len(flagged_ids),
        "message": f"Successfully processed review. {len(approved_ids)} approved, {len(flagged_ids)} flagged for dispute review.",
    }


# -----------------------------------------------------------------------------
# API Dispatch Handlers
# -----------------------------------------------------------------------------

def handle_prospect_crm_api(
    conn: sqlite3.Connection,
    user: Optional[Dict[str, Any]],
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]],
    remote_ip: str = "127.0.0.1",
) -> Optional[Dict[str, Any]]:
    """Dispatch public and authenticated endpoints for Prospect CRM, Dunning and Corporate Review."""
    route = path.split("?")[0]
    norm_route = route.replace("/api/v1", "/api") if route.startswith("/api/v1") else route
    payload = payload or {}

    # 1. Public Prospect Capture
    if method == "POST" and (norm_route in {"/api/public/prospect-capture", "/api/public/prospects"}):
        return capture_public_prospect(conn, payload)

    # 2. Public Zero-Login Corporate Proforma Review
    review_match = re.match(r"^/api/billing/corporate-review/([^/]+)(?:/decide)?$", norm_route)
    if review_match:
        token = review_match.group(1)
        if norm_route.endswith("/decide") and method == "POST":
            return decide_corporate_review(conn, token, payload)
        elif method == "GET":
            return get_corporate_review_data(conn, token)

    # 3. Authenticated Admin & Tenant Endpoints
    # Admin Prospects List & Add Note
    if method == "GET" and norm_route in {"/api/admin/prospects"}:
        query = None
        status = None
        if "?" in path:
            from urllib.parse import parse_qs
            qs = parse_qs(path.split("?", 1)[1])
            query = qs.get("q", [None])[0]
            status = qs.get("status", [None])[0]
        return {"prospects": list_prospects(conn, query, status)}

    prospect_note_match = re.match(r"^/api/admin/prospects/([^/]+)/notes$", norm_route)
    if method == "POST" and prospect_note_match:
        return add_prospect_note(conn, prospect_note_match.group(1), str(payload.get("note") or ""), user.get("name", "Sales") if user else "Sales")

    convert_match = re.match(r"^/api/admin/prospects/([^/]+)/convert-to-tenant$", norm_route)
    if method == "POST" and convert_match:
        return convert_prospect_to_tenant(conn, convert_match.group(1))

    # Tenant Billing & Dunning
    billing_ov_match = re.match(r"^/api/admin/tenants/([^/]+)/billing-overview$", norm_route)
    if method == "GET" and billing_ov_match:
        return get_tenant_billing_overview(conn, billing_ov_match.group(1))

    inv_create_match = re.match(r"^/api/admin/tenants/([^/]+)/platform-invoices$", norm_route)
    if method == "POST" and inv_create_match:
        return create_tenant_platform_invoice(conn, inv_create_match.group(1), payload)

    access_ctl_match = re.match(r"^/api/admin/tenants/([^/]+)/access-control$", norm_route)
    if method == "PATCH" and access_ctl_match:
        state = str(payload.get("access_control_state") or "")
        reason = str(payload.get("reason") or "")
        return update_tenant_access_control(conn, access_ctl_match.group(1), state, reason)

    # Share Link Generation for Proforma
    share_link_match = re.match(r"^/api/billing/proforma/([^/]+)/share-link$", norm_route)
    if method == "POST" and share_link_match:
        proforma_id = share_link_match.group(1)
        tenant_id = user.get("organization_id", "org_demo") if user else "org_demo"
        corp_name = str(payload.get("corporate_name") or "Corporate Client")
        corp_email = payload.get("corporate_email")
        return generate_proforma_share_link(conn, proforma_id, tenant_id, corp_name, corp_email)

    return None
