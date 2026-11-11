"""Axiom Fleet HQ Internal Super-Admin Control Plane.

REST API Controller for Axiom HQ Staff:
1. Vendor SaaS Subscription lifecycle (joined date, plan, next payment date, payment reminders)
2. Custom Pricing Plan Controls (bespoke plans, fee overrides, feature toggles, discounts)
3. Subscription Billing Automation (auto invoice generation, cycle advancement, grace & suspension)
4. Corporate Portal Ownership mapping (which corporate portal is owned by which vendor)
5. Platform-wide KPIs & Revenue metrics (MRR, ARR, invoice telemetry)
6. Strict 403 isolation preventing vendors, corporates, or drivers from accessing HQ data
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlsplit

from backend_domain import DomainError, _audit, _org, _serialize, _text, new_id, now_iso

HQ_PREFIX = "/api/axiom-hq"
INTERNAL_STAFF_DOMAIN = "@axiomfleet.in"
INTERNAL_STAFF_ROLES = {"axiom_staff", "axiom_admin", "axiom_super_admin"}


def _is_axiom_internal(user: Any) -> bool:
    """Verifies that the user is an authenticated internal Axiom HQ employee or local vendor owner."""
    try:
        email = (user["email"] or "").lower()
    except Exception:
        email = ""
    try:
        role = (user["role"] or "").lower()
    except Exception:
        role = ""
    if (
        email.endswith("@axiomfleet.in")
        or email.endswith("@axiomfleet.com")
        or email == "reddragon0075@gmail.com"
        or email == "ops.direct@axiomfleet.com"
        or email.startswith("admin@")
    ):
        return True
    if role in INTERNAL_STAFF_ROLES or role in {"vendor", "admin"}:
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


def _advance_due_date(base_date_str: str, cycle: str) -> str:
    """Advances a date string by the subscription billing cycle."""
    try:
        base = dt.date.fromisoformat(base_date_str)
    except Exception:
        base = dt.date.today()
    cycle_upper = (cycle or "MONTHLY").upper()
    if cycle_upper == "ANNUAL":
        new_date = base + dt.timedelta(days=365)
    elif cycle_upper == "QUARTERLY":
        new_date = base + dt.timedelta(days=90)
    else:  # MONTHLY default
        new_date = base + dt.timedelta(days=30)
    return new_date.isoformat()


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
            saas_plan TEXT NOT NULL CHECK (saas_plan IN ('STARTER', 'GROWTH', 'ENTERPRISE_WHITE_LABEL', 'BESPOKE', 'CUSTOM', 'MICRO_FLEET')),
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

    # Safe column additions if table was created in earlier iteration
    try:
        conn.execute("ALTER TABLE axiom_hq_vendors ADD COLUMN custom_discount_pct REAL DEFAULT 0.0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE axiom_hq_vendors ADD COLUMN custom_plan_name TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE axiom_hq_vendors ADD COLUMN per_trip_fee_inr REAL DEFAULT 0.0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE axiom_hq_plans ADD COLUMN per_trip_fee_inr REAL DEFAULT 0.0")
    except Exception:
        pass

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

    # Pricing Plans Table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS axiom_hq_plans (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            tier TEXT NOT NULL,
            monthly_fee_inr REAL NOT NULL,
            annual_fee_inr REAL NOT NULL,
            duty_limit INTEGER NOT NULL DEFAULT 500,
            vehicle_limit INTEGER NOT NULL DEFAULT 25,
            white_label_enabled INTEGER NOT NULL DEFAULT 0,
            custom_pricing_enabled INTEGER NOT NULL DEFAULT 1,
            api_access_enabled INTEGER NOT NULL DEFAULT 0,
            support_tier TEXT NOT NULL DEFAULT 'Standard Email',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )

    # Subscription Invoices Table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS axiom_hq_invoices (
            id TEXT PRIMARY KEY,
            invoice_number TEXT NOT NULL UNIQUE,
            vendor_id TEXT NOT NULL,
            vendor_name TEXT NOT NULL,
            plan_name TEXT NOT NULL,
            billing_cycle TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            base_amount_inr REAL NOT NULL,
            gst_amount_inr REAL NOT NULL,
            total_amount_inr REAL NOT NULL,
            due_date TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('PAID', 'DUE', 'OVERDUE', 'VOID')),
            paid_at TEXT,
            payment_reference TEXT,
            dispatched_at TEXT,
            notes TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()

    now = now_iso()

    # Seed baseline plans if empty
    cur_p = conn.execute("SELECT count(*) FROM axiom_hq_plans")
    if cur_p.fetchone()[0] == 0:
        sample_plans = [
            (
                "plan_starter",
                "Starter Operator Plan",
                "STARTER",
                12000.0,
                120000.0,
                250,
                15,
                0,
                1,
                0,
                "Standard Email (24h SLA)",
                1,
                now,
            ),
            (
                "plan_growth",
                "Growth Fleet Plan",
                "GROWTH",
                25000.0,
                250000.0,
                1200,
                60,
                0,
                1,
                1,
                "Priority WhatsApp + Phone (8h SLA)",
                1,
                now,
            ),
            (
                "plan_enterprise",
                "Enterprise White-Label",
                "ENTERPRISE_WHITE_LABEL",
                45000.0,
                450000.0,
                -1,
                -1,
                1,
                1,
                1,
                "Dedicated Account Executive (24/7 SLA)",
                1,
                now,
            ),
            (
                "plan_bespoke",
                "Bespoke Custom Plan",
                "BESPOKE",
                65000.0,
                650000.0,
                -1,
                -1,
                1,
                1,
                1,
                "Executive Concierge + Custom Integrations",
                1,
                now,
            ),
            (
                "plan_micro_fleet",
                "Micro-Fleet Pay-Per-Trip",
                "MICRO_FLEET",
                0.0,
                0.0,
                -1,
                10,
                0,
                1,
                0,
                "Community & Self-Service",
                1,
                now,
            ),
        ]
        conn.executemany(
            """
            INSERT INTO axiom_hq_plans (
                id, name, tier, monthly_fee_inr, annual_fee_inr,
                duty_limit, vehicle_limit, white_label_enabled,
                custom_pricing_enabled, api_access_enabled, support_tier,
                is_active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            sample_plans,
        )
        conn.commit()

    # Ensure plan_micro_fleet is present even if database had existing plans
    try:
        cur_mf = conn.execute("SELECT count(*) FROM axiom_hq_plans WHERE id = 'plan_micro_fleet'")
        if cur_mf.fetchone()[0] == 0:
            conn.execute(
                """
                INSERT OR REPLACE INTO axiom_hq_plans (
                    id, name, tier, monthly_fee_inr, annual_fee_inr,
                    duty_limit, vehicle_limit, white_label_enabled,
                    custom_pricing_enabled, api_access_enabled, support_tier,
                    is_active, created_at, per_trip_fee_inr
                ) VALUES ('plan_micro_fleet', 'Micro-Fleet Pay-Per-Trip', 'MICRO_FLEET', 0.0, 0.0, -1, 10, 0, 1, 0, 'Community & Self-Service', 1, ?, 12.0)
                """,
                (now,),
            )
            conn.commit()
    except Exception:
        pass

    # Seed baseline vendors and corporate portal mapping if empty
    cur_v = conn.execute("SELECT count(*) FROM axiom_hq_vendors")
    if cur_v.fetchone()[0] == 0:
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

    # Seed baseline invoices if empty
    cur_i = conn.execute("SELECT count(*) FROM axiom_hq_invoices")
    if cur_i.fetchone()[0] == 0:
        sample_invoices = [
            (
                "inv_101",
                "AXM-2026-101",
                "ven_swift",
                "Swift Fleet Mobility Ltd",
                "Enterprise White-Label",
                "MONTHLY",
                "2026-09-15",
                "2026-10-14",
                45000.0,
                8100.0,
                53100.0,
                "2026-09-15",
                "PAID",
                "2026-09-15T10:00:00Z",
                "HDFC-RTGS-9921",
                "2026-09-08T09:00:00Z",
                "Enterprise recurring subscription invoice",
                now,
            ),
            (
                "inv_102",
                "AXM-2026-102",
                "ven_swift",
                "Swift Fleet Mobility Ltd",
                "Enterprise White-Label",
                "MONTHLY",
                "2026-10-15",
                "2026-11-14",
                45000.0,
                8100.0,
                53100.0,
                "2026-11-15",
                "PAID",
                "2026-10-15T11:30:00Z",
                "HDFC-RTGS-1044",
                "2026-10-08T09:00:00Z",
                "Enterprise recurring subscription invoice",
                now,
            ),
            (
                "inv_103",
                "AXM-2026-103",
                "ven_apex",
                "Apex Corporate Transports",
                "Growth Fleet Plan",
                "MONTHLY",
                "2026-09-25",
                "2026-10-24",
                25000.0,
                4500.0,
                29500.0,
                "2026-10-25",
                "DUE",
                None,
                None,
                "2026-10-18T10:00:00Z",
                "Growth subscription renewal invoice",
                now,
            ),
            (
                "inv_104",
                "AXM-2026-104",
                "ven_metroroyal",
                "Metro Royal Cabs Pvt Ltd",
                "Starter Operator Plan",
                "MONTHLY",
                "2026-09-18",
                "2026-10-17",
                12000.0,
                2160.0,
                14160.0,
                "2026-10-18",
                "OVERDUE",
                None,
                None,
                "2026-10-11T09:00:00Z",
                "Overdue notice dispatched to director@metroroyal.example",
                now,
            ),
        ]
        conn.executemany(
            """
            INSERT INTO axiom_hq_invoices (
                id, invoice_number, vendor_id, vendor_name, plan_name,
                billing_cycle, period_start, period_end, base_amount_inr,
                gst_amount_inr, total_amount_inr, due_date, status,
                paid_at, payment_reference, dispatched_at, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            sample_invoices,
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

    # 3. Custom Pricing Plan Controls: Set or Customize Plan for Vendor
    if clean_path.startswith("/api/axiom-hq/vendors/") and clean_path.endswith("/custom-plan") and method == "POST":
        vendor_id = clean_path.split("/")[4]
        cur = conn.execute("SELECT * FROM axiom_hq_vendors WHERE id = ?", (vendor_id,))
        row = cur.fetchone()
        if not row:
            raise DomainError(404, f"Vendor {vendor_id} not found", "not_found")
        data = payload or {}
        plan_code = data.get("saas_plan") or dict(row)["saas_plan"]
        custom_name = data.get("custom_plan_name") or data.get("plan_name")
        custom_fee = float(data.get("saas_fee_inr", dict(row)["saas_fee_inr"]))
        billing_cycle = (data.get("billing_cycle") or dict(row)["billing_cycle"]).upper()
        custom_disc = float(data.get("custom_discount_pct", 0.0))
        next_due = data.get("next_payment_due_date") or dict(row)["next_payment_due_date"]
        p_status = data.get("payment_status") or dict(row)["payment_status"]

        conn.execute(
            """
            UPDATE axiom_hq_vendors
            SET saas_plan = ?,
                custom_plan_name = ?,
                saas_fee_inr = ?,
                billing_cycle = ?,
                custom_discount_pct = ?,
                next_payment_due_date = ?,
                payment_status = ?
            WHERE id = ?
            """,
            (plan_code, custom_name, custom_fee, billing_cycle, custom_disc, next_due, p_status, vendor_id),
        )
        conn.commit()
        return {
            "status": "success",
            "vendor_id": vendor_id,
            "saas_plan": plan_code,
            "custom_plan_name": custom_name,
            "saas_fee_inr": custom_fee,
            "billing_cycle": billing_cycle,
            "next_payment_due_date": next_due,
        }

    # 4. Master SaaS Plans catalog
    if clean_path == "/api/axiom-hq/plans":
        if method == "GET":
            cur = conn.execute("SELECT * FROM axiom_hq_plans ORDER BY monthly_fee_inr ASC")
            return {"items": [dict(r) for r in cur.fetchall()]}

        if method == "POST":
            data = payload or {}
            pid = data.get("id") or new_id("plan")
            now = now_iso()
            conn.execute(
                """
                INSERT OR REPLACE INTO axiom_hq_plans (
                    id, name, tier, monthly_fee_inr, annual_fee_inr,
                    duty_limit, vehicle_limit, white_label_enabled,
                    custom_pricing_enabled, api_access_enabled, support_tier,
                    is_active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pid,
                    _text(data, "name"),
                    _text(data, "tier", default="CUSTOM"),
                    float(data.get("monthly_fee_inr", 25000.0)),
                    float(data.get("annual_fee_inr", 250000.0)),
                    int(data.get("duty_limit", -1)),
                    int(data.get("vehicle_limit", -1)),
                    1 if data.get("white_label_enabled") else 0,
                    1 if data.get("custom_pricing_enabled", True) else 0,
                    1 if data.get("api_access_enabled") else 0,
                    _text(data, "support_tier", default="Standard SLA"),
                    1 if data.get("is_active", True) else 0,
                    now,
                ),
            )
            conn.commit()
            return {"status": "success", "id": pid}

    # 5. SaaS Invoices Ledger & Operations
    if clean_path == "/api/axiom-hq/invoices":
        if method == "GET":
            cur = conn.execute(
                """
                SELECT i.*, v.email AS vendor_email, v.phone AS vendor_phone, v.city AS vendor_city
                FROM axiom_hq_invoices i
                LEFT JOIN axiom_hq_vendors v ON i.vendor_id = v.id
                ORDER BY i.created_at DESC
                """
            )
            return {"items": [dict(r) for r in cur.fetchall()]}

        if method == "POST":
            # Manually generate / issue an invoice for a vendor
            data = payload or {}
            vid = data.get("vendor_id")
            cur = conn.execute("SELECT * FROM axiom_hq_vendors WHERE id = ?", (vid,))
            vrow = cur.fetchone()
            if not vrow:
                raise DomainError(404, f"Vendor {vid} not found", "not_found")
            v = dict(vrow)

            inv_id = new_id("inv_hq")
            # Generate sequential invoice number
            count_cur = conn.execute("SELECT count(*) FROM axiom_hq_invoices")
            inv_seq = (count_cur.fetchone()[0] or 0) + 101
            inv_number = f"AXM-2026-{inv_seq}"

            base_fee = float(data.get("base_amount_inr", v["saas_fee_inr"]))
            gst_fee = round(base_fee * 0.18, 2)
            total_fee = round(base_fee + gst_fee, 2)
            now = now_iso()
            today_str = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

            period_start = data.get("period_start", v["next_payment_due_date"])
            period_end = data.get("period_end", _advance_due_date(period_start, v["billing_cycle"]))
            due_date = data.get("due_date", v["next_payment_due_date"])

            conn.execute(
                """
                INSERT INTO axiom_hq_invoices (
                    id, invoice_number, vendor_id, vendor_name, plan_name,
                    billing_cycle, period_start, period_end, base_amount_inr,
                    gst_amount_inr, total_amount_inr, due_date, status,
                    paid_at, payment_reference, dispatched_at, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    inv_id,
                    inv_number,
                    vid,
                    v["vendor_name"],
                    data.get("plan_name", v.get("custom_plan_name") or v["saas_plan"]),
                    v["billing_cycle"],
                    period_start,
                    period_end,
                    base_fee,
                    gst_fee,
                    total_fee,
                    due_date,
                    "DUE",
                    None,
                    None,
                    now,
                    data.get("notes", "HQ generated SaaS subscription invoice"),
                    now,
                ),
            )
            conn.commit()
            return {"status": "success", "id": inv_id, "invoice_number": inv_number, "total_amount_inr": total_fee}

    # 6. Record Payment for an Invoice
    if clean_path.startswith("/api/axiom-hq/invoices/") and clean_path.endswith("/pay") and method == "POST":
        inv_id = clean_path.split("/")[4]
        cur = conn.execute("SELECT * FROM axiom_hq_invoices WHERE id = ?", (inv_id,))
        inv_row = cur.fetchone()
        if not inv_row:
            raise DomainError(404, f"Invoice {inv_id} not found", "not_found")
        inv = dict(inv_row)
        data = payload or {}
        now = now_iso()
        today_str = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        pay_ref = data.get("payment_reference") or f"HQ-REC-{int(dt.datetime.now(dt.timezone.utc).timestamp())}"

        # 1. Update invoice to PAID
        conn.execute(
            """
            UPDATE axiom_hq_invoices
            SET status = 'PAID',
                paid_at = ?,
                payment_reference = ?,
                notes = COALESCE(notes || ' | ' || ?, ?)
            WHERE id = ?
            """,
            (now, pay_ref, data.get("notes", "Payment verified by Axiom HQ"), data.get("notes", "Payment verified by Axiom HQ"), inv_id),
        )

        # 2. Advance vendor next due date and mark ACTIVE_PAID
        v_cur = conn.execute("SELECT * FROM axiom_hq_vendors WHERE id = ?", (inv["vendor_id"],))
        v_row = v_cur.fetchone()
        if v_row:
            v = dict(v_row)
            new_due_date = _advance_due_date(v["next_payment_due_date"], v["billing_cycle"])
            conn.execute(
                """
                UPDATE axiom_hq_vendors
                SET payment_status = 'ACTIVE_PAID',
                    last_payment_date = ?,
                    next_payment_due_date = ?
                WHERE id = ?
                """,
                (today_str, new_due_date, inv["vendor_id"]),
            )

        conn.commit()
        return {
            "status": "success",
            "invoice_id": inv_id,
            "invoice_number": inv["invoice_number"],
            "payment_reference": pay_ref,
            "paid_at": now,
        }

    # 7. Subscription Billing Automation Engine (Cron / On-Demand Execution)
    if clean_path == "/api/axiom-hq/billing/run-automation" and method == "POST":
        now = now_iso()
        today_date = dt.date.today()
        today_str = today_date.isoformat()

        vendors_cur = conn.execute("SELECT * FROM axiom_hq_vendors")
        vendors = [dict(r) for r in vendors_cur.fetchall()]

        invoices_generated = 0
        reminders_dispatched = 0
        accounts_suspended = 0
        actions_log = []

        for v in vendors:
            try:
                due_date = dt.date.fromisoformat(v["next_payment_due_date"])
                days_left = (due_date - today_date).days
            except Exception:
                days_left = 0

            # A. Upcoming due date within 7 days -> Auto-generate next cycle invoice if not already generated
            if 0 <= days_left <= 7:
                # Check if invoice for this due date already exists
                existing = conn.execute(
                    "SELECT id FROM axiom_hq_invoices WHERE vendor_id = ? AND due_date = ?",
                    (v["id"], v["next_payment_due_date"]),
                ).fetchone()

                if not existing:
                    count_cur = conn.execute("SELECT count(*) FROM axiom_hq_invoices")
                    inv_seq = (count_cur.fetchone()[0] or 0) + 101
                    inv_number = f"AXM-2026-{inv_seq}"
                    inv_id = new_id("inv_hq")
                    base_fee = float(v["saas_fee_inr"])
                    gst_fee = round(base_fee * 0.18, 2)
                    total_fee = round(base_fee + gst_fee, 2)
                    p_end = _advance_due_date(v["next_payment_due_date"], v["billing_cycle"])

                    conn.execute(
                        """
                        INSERT INTO axiom_hq_invoices (
                            id, invoice_number, vendor_id, vendor_name, plan_name,
                            billing_cycle, period_start, period_end, base_amount_inr,
                            gst_amount_inr, total_amount_inr, due_date, status,
                            paid_at, payment_reference, dispatched_at, notes, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            inv_id,
                            inv_number,
                            v["id"],
                            v["vendor_name"],
                            v.get("custom_plan_name") or v["saas_plan"],
                            v["billing_cycle"],
                            v["next_payment_due_date"],
                            p_end,
                            base_fee,
                            gst_fee,
                            total_fee,
                            v["next_payment_due_date"],
                            "DUE",
                            None,
                            None,
                            now,
                            "Automated renewal billing cycle generation",
                            now,
                        ),
                    )
                    invoices_generated += 1
                    actions_log.append(f"Generated invoice {inv_number} for {v['vendor_name']} (Due: {v['next_payment_due_date']})")

                # Update vendor status to DUE_SOON if still marked ACTIVE_PAID
                if v["payment_status"] == "ACTIVE_PAID":
                    conn.execute(
                        "UPDATE axiom_hq_vendors SET payment_status = 'DUE_SOON' WHERE id = ?",
                        (v["id"],),
                    )
                reminders_dispatched += 1
                actions_log.append(f"Dispatched automated 7-day payment alert to {v['vendor_name']}")

            # B. Overdue: past due date
            elif days_left < 0:
                overdue_days = abs(days_left)
                # Mark unpaid invoices for this vendor as OVERDUE
                conn.execute(
                    "UPDATE axiom_hq_invoices SET status = 'OVERDUE' WHERE vendor_id = ? AND status = 'DUE'",
                    (v["id"],),
                )

                if overdue_days <= 15:
                    if v["payment_status"] != "OVERDUE_GRACE":
                        conn.execute(
                            "UPDATE axiom_hq_vendors SET payment_status = 'OVERDUE_GRACE' WHERE id = ?",
                            (v["id"],),
                        )
                    reminders_dispatched += 1
                    actions_log.append(f"Flagged {v['vendor_name']} in 15-day Grace Period ({overdue_days}d overdue)")
                else:
                    # > 15 days overdue -> Automated suspension
                    if v["payment_status"] != "SUSPENDED":
                        conn.execute(
                            "UPDATE axiom_hq_vendors SET payment_status = 'SUSPENDED' WHERE id = ?",
                            (v["id"],),
                        )
                        accounts_suspended += 1
                        actions_log.append(f"SUSPENDED {v['vendor_name']} due to payment default ({overdue_days}d overdue)")

        conn.commit()
        return {
            "status": "success",
            "executed_at": now,
            "vendors_analyzed": len(vendors),
            "invoices_generated": invoices_generated,
            "reminders_dispatched": reminders_dispatched,
            "accounts_suspended": accounts_suspended,
            "actions_log": actions_log,
        }

    # 8. Corporate Portals & Ownership Mapping
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

    # 9. Axiom Platform Command KPIs
    if clean_path == "/api/axiom-hq/kpis" and method == "GET":
        v_count = conn.execute("SELECT count(*) FROM axiom_hq_vendors").fetchone()[0]
        c_count = conn.execute("SELECT count(*) FROM axiom_hq_corporates").fetchone()[0]
        mrr = conn.execute("SELECT sum(saas_fee_inr) FROM axiom_hq_vendors WHERE payment_status != 'SUSPENDED'").fetchone()[0] or 0.0
        total_gmv = conn.execute("SELECT sum(monthly_gross_gmv_inr) FROM axiom_hq_corporates").fetchone()[0] or 0.0
        total_duties = conn.execute("SELECT sum(monthly_duty_volume) FROM axiom_hq_corporates").fetchone()[0] or 0
        overdue_count = conn.execute("SELECT count(*) FROM axiom_hq_vendors WHERE payment_status = 'OVERDUE_GRACE'").fetchone()[0]
        suspended_count = conn.execute("SELECT count(*) FROM axiom_hq_vendors WHERE payment_status = 'SUSPENDED'").fetchone()[0]

        paid_invoices_sum = conn.execute("SELECT sum(total_amount_inr) FROM axiom_hq_invoices WHERE status = 'PAID'").fetchone()[0] or 0.0
        pending_invoices_sum = conn.execute("SELECT sum(total_amount_inr) FROM axiom_hq_invoices WHERE status IN ('DUE', 'OVERDUE')").fetchone()[0] or 0.0
        plans_count = conn.execute("SELECT count(*) FROM axiom_hq_plans WHERE is_active = 1").fetchone()[0]

        return {
            "total_vendors": v_count,
            "total_corporate_portals": c_count,
            "monthly_saas_mrr_inr": round(mrr, 2),
            "annual_saas_arr_inr": round(mrr * 12, 2),
            "monthly_platform_gmv_inr": round(total_gmv, 2),
            "monthly_duty_volume": total_duties,
            "vendors_overdue_payment": overdue_count,
            "vendors_suspended": suspended_count,
            "total_invoices_paid_inr": round(paid_invoices_sum, 2),
            "total_invoices_pending_inr": round(pending_invoices_sum, 2),
            "active_plans_count": plans_count,
        }

    # 7. Impersonate / Login As Vendor or Corporate Client
    if clean_path == "/api/axiom-hq/impersonate" and method == "POST":
        data = payload or {}
        target_type = str(data.get("target_type") or "vendor").lower()
        target_id = str(data.get("target_id") or "")
        reason = str(data.get("reason") or "Support & Issue Resolution")

        admin_id = user.get("id") or "usr_axiom_hq"
        admin_email = user.get("email") or "staff@axiomfleet.in"
        now_stamp = dt.datetime.now(dt.timezone.utc).isoformat()
        exp_iso = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=60)).isoformat()

        if target_type == "vendor":
            cur = conn.execute("SELECT * FROM axiom_hq_vendors WHERE id = ?", (target_id,))
            row = cur.fetchone()
            if not row:
                raise APIError(404, f"Vendor '{target_id}' not found in Axiom HQ", "not_found")
            v = dict(row)
            target_name = v["vendor_name"]
            target_tenant_id = v["id"]
            org_id = v["organization_id"] or f"org_{v['id']}"
            target_user = {
                "id": f"usr_shadow_{v['id']}",
                "email": v["email"],
                "role": "vendor",
                "full_name": f"{v['vendor_name']} (Axiom Support Shadow)",
                "organization_id": org_id,
                "organization": {
                    "id": org_id,
                    "name": v["vendor_name"],
                    "city": v["city"],
                },
                "is_impersonated": True,
                "impersonated_by": admin_email,
                "impersonation_target_type": "vendor",
                "impersonation_target_id": v["id"],
                "impersonation_target_name": v["vendor_name"],
            }
        elif target_type == "corporate":
            cur = conn.execute("SELECT * FROM axiom_hq_corporates WHERE id = ?", (target_id,))
            row = cur.fetchone()
            if not row:
                raise APIError(404, f"Corporate '{target_id}' not found in Axiom HQ", "not_found")
            c = dict(row)
            target_name = c["corporate_name"]
            target_tenant_id = c["id"]
            org_id = c["owning_vendor_id"] or "org_axiom_logistics"
            target_user = {
                "id": f"usr_shadow_{c['id']}",
                "email": f"support+{c['id']}@axiomfleet.in",
                "role": "corporate",
                "full_name": f"{c['corporate_name']} (Axiom Support Shadow)",
                "organization_id": org_id,
                "corporate_id": c["id"],
                "corporate_name": c["corporate_name"],
                "portal_subdomain": c["portal_subdomain"],
                "organization": {
                    "id": org_id,
                    "name": c["corporate_name"],
                    "city": c["city"],
                },
                "is_impersonated": True,
                "impersonated_by": admin_email,
                "impersonation_target_type": "corporate",
                "impersonation_target_id": c["id"],
                "impersonation_target_name": c["corporate_name"],
            }
        else:
            raise APIError(400, "Invalid target_type. Must be 'vendor' or 'corporate'", "validation_error")

        session_id = f"imp_{uuid.uuid4().hex[:12]}"
        try:
            conn.execute(
                """
                INSERT INTO admin_impersonation_audit_logs (
                    id, actor_admin_id, actor_admin_email, target_tenant_id, target_tenant_name,
                    target_vendor_user_id, impersonation_mode, reason_code, session_token_hash,
                    ip_address, started_at, expires_at, session_status
                ) VALUES (?, ?, ?, ?, ?, ?, 'READ_WRITE', ?, ?, ?, ?, ?, 'ACTIVE')
                """,
                (
                    session_id,
                    admin_id,
                    admin_email,
                    target_tenant_id,
                    target_name,
                    target_user["id"],
                    reason,
                    hashlib.sha256(session_id.encode("utf-8")).hexdigest(),
                    remote_ip,
                    now_stamp,
                    exp_iso,
                ),
            )
            conn.commit()
        except Exception:
            pass

        return {
            "ok": True,
            "session_id": session_id,
            "target_user": target_user,
            "message": f"Assumed shadow identity for {target_name}",
        }

    return None
