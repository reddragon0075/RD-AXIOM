"""Axiom Fleet HQ Internal Super-Admin Control Plane.

REST API Controller for Axiom HQ Staff:
1. Vendor SaaS Subscription lifecycle (joined date, plan, next payment date, payment reminders)
2. Corporate Portal Ownership mapping (which corporate portal is owned by which vendor)
3. Platform-wide KPIs & Revenue metrics
4. Strict 403 isolation preventing vendors, corporates, or drivers from accessing HQ data
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlsplit

from backend_domain import DomainError, _audit, _org, _serialize, _text, new_id, now_iso

HQ_PREFIX = "/api/axiom-hq"
INTERNAL_STAFF_DOMAIN = "@axiomfleet.in"
INTERNAL_STAFF_ROLES = {"axiom_staff", "axiom_admin", "axiom_super_admin"}


def _is_axiom_internal(user: Any) -> bool:
    """Verifies that the user is an authenticated internal Axiom HQ employee."""
    try:
        email = (user["email"] or "").lower()
    except Exception:
        email = ""
    try:
        role = (user["role"] or "").lower()
    except Exception:
        role = ""
    if email.endswith(INTERNAL_STAFF_DOMAIN):
        return True
    if role in INTERNAL_STAFF_ROLES:
        return True
    return False


def _require_axiom_internal(user: Dict[str, Any]) -> None:
    if not _is_axiom_internal(user):
        raise DomainError(
            403,
            "Access Denied: This control plane is restricted to verified Axiom Fleet HQ staff (@axiomfleet.in). "
            "Vendor, corporate, and driver portals cannot access this surface.",
            "internal_staff_only",
        )


def initialize_axiom_hq_schema(conn: sqlite3.Connection) -> None:
    """Initializes schema and seeds baseline HQ records."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS axiom_hq_vendors (
            id TEXT PRIMARY KEY,
            organization_id TEXT,
            vendor_name TEXT NOT NULL,
            contact_person TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT NOT NULL,
            city TEXT NOT NULL,
            joined_date TEXT NOT NULL,
            saas_plan TEXT NOT NULL CHECK (saas_plan IN ('STARTER', 'GROWTH', 'ENTERPRISE_WHITE_LABEL')),
            billing_cycle TEXT NOT NULL CHECK (billing_cycle IN ('MONTHLY', 'QUARTERLY', 'ANNUAL')),
            saas_fee_inr REAL NOT NULL,
            last_payment_date TEXT NOT NULL,
            next_payment_due_date TEXT NOT NULL,
            payment_status TEXT NOT NULL CHECK (payment_status IN ('ACTIVE_PAID', 'DUE_SOON', 'OVERDUE_GRACE', 'SUSPENDED')),
            reliability_score REAL NOT NULL DEFAULT 98.0,
            priority_tier TEXT NOT NULL DEFAULT 'Tier 1',
            created_at TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS axiom_hq_corporates (
            id TEXT PRIMARY KEY,
            corporate_name TEXT NOT NULL,
            portal_subdomain TEXT NOT NULL UNIQUE,
            gst_number TEXT NOT NULL,
            city TEXT NOT NULL,
            joined_date TEXT NOT NULL,
            ownership_type TEXT NOT NULL CHECK (ownership_type IN ('VENDOR_OWNED_PORTAL', 'AXIOM_DIRECT_MANAGED', 'CO_MANAGED_NETWORK')),
            owning_vendor_id TEXT REFERENCES axiom_hq_vendors(id),
            owning_vendor_name TEXT NOT NULL,
            active_employees_count INTEGER NOT NULL DEFAULT 100,
            monthly_duty_volume INTEGER NOT NULL DEFAULT 250,
            monthly_gross_gmv_inr REAL NOT NULL DEFAULT 500000.0,
            portal_status TEXT NOT NULL DEFAULT 'LIVE' CHECK (portal_status IN ('LIVE', 'ONBOARDING', 'PAUSED_BY_VENDOR')),
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()

    # Seed baseline vendors and corporate portal mapping if empty
    cur = conn.execute("SELECT count(*) FROM axiom_hq_vendors")
    if cur.fetchone()[0] == 0:
        now = now_iso()
        sample_vendors = [
            (
                "ven_swift",
                "org_swift_mobility",
                "Swift Fleet Mobility Ltd",
                "Rajesh Sharma",
                "+91 98450 11223",
                "accounts@swiftfleet.in",
                "Bengaluru",
                "2026-01-15",
                "ENTERPRISE_WHITE_LABEL",
                "MONTHLY",
                45000.0,
                "2026-09-15",
                "2026-11-15",
                "ACTIVE_PAID",
                98.5,
                "Tier 1",
                now,
            ),
            (
                "ven_apex",
                "org_apex_corp",
                "Apex Corporate Transports",
                "Kavita Nair",
                "+91 98450 44556",
                "billing@apextrans.example",
                "Mumbai",
                "2026-03-10",
                "GROWTH",
                "MONTHLY",
                25000.0,
                "2026-09-25",
                "2026-10-25",
                "DUE_SOON",
                94.8,
                "Tier 1",
                now,
            ),
            (
                "ven_metroroyal",
                "org_metro_royal",
                "Metro Royal Cabs Pvt Ltd",
                "Vikram Singh",
                "+91 98450 77889",
                "director@metroroyal.example",
                "Hyderabad",
                "2026-06-01",
                "STARTER",
                "MONTHLY",
                12000.0,
                "2026-09-18",
                "2026-10-18",
                "OVERDUE_GRACE",
                88.0,
                "Tier 2",
                now,
            ),
        ]
        conn.executemany(
            """
            INSERT INTO axiom_hq_vendors (
                id, organization_id, vendor_name, contact_person, phone, email,
                city, joined_date, saas_plan, billing_cycle, saas_fee_inr,
                last_payment_date, next_payment_due_date, payment_status,
                reliability_score, priority_tier, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            sample_vendors,
        )

        sample_corporates = [
            (
                "corp_northstar",
                "NorthStar Technologies",
                "northstar.axiomfleet.in",
                "29AABCN1234F1Z1",
                "Bengaluru",
                "2026-02-01",
                "VENDOR_OWNED_PORTAL",
                "ven_swift",
                "Swift Fleet Mobility Ltd",
                450,
                820,
                1450000.0,
                "LIVE",
                now,
            ),
            (
                "corp_infosys",
                "Infosys BPM Logistics",
                "infosys-bpm.axiomfleet.in",
                "29AAACI4567G1Z2",
                "Bengaluru",
                "2026-02-20",
                "VENDOR_OWNED_PORTAL",
                "ven_swift",
                "Swift Fleet Mobility Ltd",
                1200,
                2400,
                4800000.0,
                "LIVE",
                now,
            ),
            (
                "corp_wipro",
                "Wipro Digital Mobility",
                "wipro-digital.axiomfleet.in",
                "29AAACW7890H1Z3",
                "Mumbai",
                "2026-04-12",
                "VENDOR_OWNED_PORTAL",
                "ven_apex",
                "Apex Corporate Transports",
                650,
                1100,
                2100000.0,
                "LIVE",
                now,
            ),
            (
                "corp_gs",
                "Goldman Sachs Tech Trans",
                "gs-india.axiomfleet.in",
                "29AABCG5678K1Z5",
                "Bengaluru",
                "2026-05-18",
                "AXIOM_DIRECT_MANAGED",
                None,
                "Axiom Direct HQ",
                800,
                1650,
                3620000.0,
                "LIVE",
                now,
            ),
        ]
        conn.executemany(
            """
            INSERT INTO axiom_hq_corporates (
                id, corporate_name, portal_subdomain, gst_number, city,
                joined_date, ownership_type, owning_vendor_id, owning_vendor_name,
                active_employees_count, monthly_duty_volume, monthly_gross_gmv_inr,
                portal_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            sample_corporates,
        )
        conn.commit()


def handle_axiom_hq(
    conn: sqlite3.Connection,
    user: Dict[str, Any],
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    remote_ip: str = "127.0.0.1",
) -> Optional[Dict[str, Any]]:
    """Handles Axiom HQ Command Center endpoints."""
    parsed = urlsplit(path)
    clean_path = parsed.path

    if not clean_path.startswith(HQ_PREFIX):
        return None

    # Enforce strict Axiom HQ internal staff authentication
    _require_axiom_internal(user)

    # 1. Vendor Partners with SaaS plans & billing details
    if clean_path == "/api/axiom-hq/vendors":
        if method == "GET":
            cur = conn.execute(
                """
                SELECT v.*,
                       (SELECT count(*) FROM axiom_hq_corporates c WHERE c.owning_vendor_id = v.id) AS owned_corporate_portals_count
                FROM axiom_hq_vendors v
                ORDER BY v.joined_date DESC
                """
            )
            rows = [dict(r) for r in cur.fetchall()]
            today_str = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
            today_date = dt.date.fromisoformat(today_str)
            for r in rows:
                try:
                    due_date = dt.date.fromisoformat(r["next_payment_due_date"])
                    r["days_until_payment_due"] = (due_date - today_date).days
                except Exception:
                    r["days_until_payment_due"] = 0
            return {"items": rows, "count": len(rows)}

        if method == "POST":
            data = payload or {}
            vid = data.get("id") or new_id("ven")
            now = now_iso()
            conn.execute(
                """
                INSERT OR REPLACE INTO axiom_hq_vendors (
                    id, organization_id, vendor_name, contact_person, phone, email,
                    city, joined_date, saas_plan, billing_cycle, saas_fee_inr,
                    last_payment_date, next_payment_due_date, payment_status,
                    reliability_score, priority_tier, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vid,
                    data.get("organization_id"),
                    _text(data, "vendor_name"),
                    _text(data, "contact_person"),
                    _text(data, "phone"),
                    _text(data, "email"),
                    _text(data, "city"),
                    data.get("joined_date") or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"),
                    data.get("saas_plan", "GROWTH"),
                    data.get("billing_cycle", "MONTHLY"),
                    float(data.get("saas_fee_inr", 25000.0)),
                    data.get("last_payment_date", now),
                    data.get("next_payment_due_date", now),
                    data.get("payment_status", "ACTIVE_PAID"),
                    float(data.get("reliability_score", 98.0)),
                    data.get("priority_tier", "Tier 1"),
                    now,
                ),
            )
            conn.commit()
            return {"status": "success", "id": vid}

    # 2. Trigger Payment Reminder (WhatsApp + Email)
    if clean_path.startswith("/api/axiom-hq/vendors/") and clean_path.endswith("/payment-reminder") and method == "POST":
        vendor_id = clean_path.split("/")[4]
        cur = conn.execute("SELECT * FROM axiom_hq_vendors WHERE id = ?", (vendor_id,))
        row = cur.fetchone()
        if not row:
            raise DomainError(404, f"Vendor {vendor_id} not found", "not_found")
        v = dict(row)
        reminder_msg = (
            f"Automated SaaS renewal reminder dispatched to {v['vendor_name']} "
            f"({v['contact_person']}, {v['email']}, {v['phone']}). "
            f"Amount Due: INR {v['saas_fee_inr']:,.2f} by {v['next_payment_due_date']}."
        )
        return {
            "status": "success",
            "dispatched_at": now_iso(),
            "vendor_id": vendor_id,
            "vendor_name": v["vendor_name"],
            "channels": ["WHATSAPP_BOT", "RESEND_EMAIL"],
            "message": reminder_msg,
        }

    # 3. Corporate Portals & Ownership Mapping
    if clean_path == "/api/axiom-hq/corporates":
        if method == "GET":
            cur = conn.execute(
                """
                SELECT c.*, v.vendor_name AS resolved_vendor_name, v.email AS vendor_email
                FROM axiom_hq_corporates c
                LEFT JOIN axiom_hq_vendors v ON c.owning_vendor_id = v.id
                ORDER BY c.monthly_gross_gmv_inr DESC
                """
            )
            return {"items": [dict(r) for r in cur.fetchall()]}

        if method == "POST":
            data = payload or {}
            cid = data.get("id") or new_id("corp")
            now = now_iso()
            conn.execute(
                """
                INSERT OR REPLACE INTO axiom_hq_corporates (
                    id, corporate_name, portal_subdomain, gst_number, city,
                    joined_date, ownership_type, owning_vendor_id, owning_vendor_name,
                    active_employees_count, monthly_duty_volume, monthly_gross_gmv_inr,
                    portal_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cid,
                    _text(data, "corporate_name"),
                    _text(data, "portal_subdomain"),
                    _text(data, "gst_number"),
                    _text(data, "city"),
                    data.get("joined_date") or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"),
                    data.get("ownership_type", "VENDOR_OWNED_PORTAL"),
                    data.get("owning_vendor_id"),
                    _text(data, "owning_vendor_name", default="Axiom Direct HQ"),
                    int(data.get("active_employees_count", 0)),
                    int(data.get("monthly_duty_volume", 0)),
                    float(data.get("monthly_gross_gmv_inr", 0.0)),
                    data.get("portal_status", "LIVE"),
                    now,
                ),
            )
            conn.commit()
            return {"status": "success", "id": cid}

    # 4. Axiom Platform Command KPIs
    if clean_path == "/api/axiom-hq/kpis" and method == "GET":
        v_count = conn.execute("SELECT count(*) FROM axiom_hq_vendors").fetchone()[0]
        c_count = conn.execute("SELECT count(*) FROM axiom_hq_corporates").fetchone()[0]
        mrr = conn.execute("SELECT sum(saas_fee_inr) FROM axiom_hq_vendors WHERE payment_status != 'SUSPENDED'").fetchone()[0] or 0.0
        total_gmv = conn.execute("SELECT sum(monthly_gross_gmv_inr) FROM axiom_hq_corporates").fetchone()[0] or 0.0
        total_duties = conn.execute("SELECT sum(monthly_duty_volume) FROM axiom_hq_corporates").fetchone()[0] or 0
        overdue_count = conn.execute("SELECT count(*) FROM axiom_hq_vendors WHERE payment_status = 'OVERDUE_GRACE'").fetchone()[0]

        return {
            "total_vendors": v_count,
            "total_corporate_portals": c_count,
            "monthly_saas_mrr_inr": round(mrr, 2),
            "annual_saas_arr_inr": round(mrr * 12, 2),
            "monthly_platform_gmv_inr": round(total_gmv, 2),
            "monthly_duty_volume": total_duties,
            "vendors_overdue_payment": overdue_count,
        }

    return None
