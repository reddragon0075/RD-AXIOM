"""Axiom Mobility Commercial, Revenue & Super-Admin Control Plane.

Implements:
1. Website Prospects & Sales CRM (capture, deduplication, notes logging, 1-click onboarding)
2. Axiom Company-View SaaS Receivables & System Census
3. Delinquent Tenant Blocking ("Kill Switch") & Global Middleware Enforcement
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlsplit
import uuid

from backend_domain import DomainError, _audit, new_id, now_iso


def _is_admin(user: Dict[str, Any]) -> bool:
    """Verifies user has Super-Admin or Axiom HQ staff permissions."""
    role = str(user.get("role") or "").lower()
    email = str(user.get("email") or "").lower()
    return (
        role in {"axiom_super_admin", "axiom_admin", "axiom_staff", "admin", "super_admin"}
        or email.endswith("@axiomfleet.in")
        or str(user.get("organization_id") or "") == "org_axiom_hq"
    )


def initialize_commercial_schema(conn: sqlite3.Connection) -> None:
    """Initializes tables for prospects, tenant billing accounts, and receivables ledger."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS prospects (
            id TEXT PRIMARY KEY,
            contact_name TEXT NOT NULL DEFAULT '',
            company_name TEXT NOT NULL DEFAULT '',
            email TEXT,
            mobile_number TEXT,
            message TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'WEBSITE',
            status TEXT NOT NULL DEFAULT 'NEW' CHECK (status IN ('NEW', 'CONTACTED', 'QUALIFIED', 'ONBOARDED', 'LOST')),
            sales_notes TEXT NOT NULL DEFAULT '[]',
            assigned_sales_rep TEXT NOT NULL DEFAULT '',
            converted_tenant_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tenant_billing_accounts (
            tenant_id TEXT PRIMARY KEY,
            tenant_name TEXT NOT NULL,
            account_status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (account_status IN ('ACTIVE', 'SOFT_BLOCKED', 'HARD_BLOCKED', 'SUSPENDED')),
            block_reason TEXT NOT NULL DEFAULT '',
            blocked_at TEXT,
            blocked_by TEXT NOT NULL DEFAULT '',
            total_billed_paise INTEGER NOT NULL DEFAULT 0,
            total_paid_paise INTEGER NOT NULL DEFAULT 0,
            outstanding_balance_paise INTEGER NOT NULL DEFAULT 0,
            credit_limit_paise INTEGER NOT NULL DEFAULT 10000000,
            next_due_date TEXT,
            days_overdue INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS axiom_receivable_ledger (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            entry_type TEXT NOT NULL CHECK (entry_type IN ('INVOICE', 'PAYMENT', 'CREDIT_NOTE', 'ADJUSTMENT')),
            reference_id TEXT NOT NULL DEFAULT '',
            amount_paise INTEGER NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            payment_method TEXT NOT NULL DEFAULT 'BANK_TRANSFER',
            created_by TEXT NOT NULL DEFAULT 'SYSTEM',
            created_at TEXT NOT NULL
        );
        """
    )

    # Seed baseline prospects and tenant billing accounts if empty
    cur = conn.execute("SELECT count(*) FROM prospects")
    if cur.fetchone()[0] == 0:
        now = now_iso()
        sample_prospects = [
            (
                "prsp_001",
                "Rajesh Sharma",
                "Sharma Corporate Cabs",
                "rajesh@sharmacabs.in",
                "+919820011223",
                "Interested in 50-cab ETS solution for Hinjawadi IT corridor.",
                "WEBSITE",
                "QUALIFIED",
                json.dumps([{"timestamp": now, "author": "sales@axiomfleet.in", "note": "Called Rajesh; qualified 40 sedans + 10 EV fleet requirement."}]),
                "sales@axiomfleet.in",
                None,
                now,
                now,
            ),
            (
                "prsp_002",
                "Vikram Malhotra",
                "Apex Shuttles Pvt Ltd",
                None,
                "+919811234567",
                "Need pricing for daily employee commute tracking.",
                "WEBSITE",
                "NEW",
                "[]",
                "",
                None,
                now,
                now,
            ),
        ]
        conn.executemany(
            """INSERT INTO prospects (id, contact_name, company_name, email, mobile_number, message, source, status, sales_notes, assigned_sales_rep, converted_tenant_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            sample_prospects,
        )

    # Seed or synchronize tenant billing accounts from organizations
    cur = conn.execute("SELECT count(*) FROM tenant_billing_accounts")
    if cur.fetchone()[0] == 0:
        now = now_iso()
        # Look for existing vendor organizations
        orgs = conn.execute("SELECT id, name FROM organizations WHERE kind = 'vendor'").fetchall()
        default_accounts = [
            ("org_vendor_rapid", "RapidFleet Logistics Pvt Ltd", "ACTIVE", "", None, "", 48520000, 35000000, 13520000, 10000000, now, 12),
            ("org_vendor_blueline", "BlueLine Premier Cabs", "ACTIVE", "", None, "", 25000000, 25000000, 0, 10000000, now, 0),
            ("org_vendor_cityfleet", "CityFleet Commercial Transport", "SOFT_BLOCKED", "Overdue invoice > 30 days", now, "sys_billing", 62000000, 30000000, 32000000, 5000000, now, 45),
        ]
        for acc in default_accounts:
            conn.execute(
                """INSERT OR REPLACE INTO tenant_billing_accounts
                   (tenant_id, tenant_name, account_status, block_reason, blocked_at, blocked_by, total_billed_paise, total_paid_paise, outstanding_balance_paise, credit_limit_paise, next_due_date, days_overdue, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (*acc, now, now),
            )
            # Add opening ledger entry
            conn.execute(
                """INSERT OR REPLACE INTO axiom_receivable_ledger
                   (id, tenant_id, entry_type, reference_id, amount_paise, description, payment_method, created_by, created_at)
                   VALUES (?, ?, 'INVOICE', 'INV-INIT-2026', ?, 'Platform SaaS & Commission Fee', 'INVOICE', 'SYSTEM', ?)""",
                (f"rec_init_{acc[0]}", acc[0], acc[6], now),
            )
        conn.commit()


def check_tenant_killswitch(conn: sqlite3.Connection, organization_id: Optional[str], method: str, route: str) -> None:
    """Global middleware guard enforcing delinquent tenant block status on operational endpoints."""
    if not organization_id or organization_id in {"org_axiom_hq", "system"}:
        return

    row = conn.execute(
        "SELECT tenant_id, tenant_name, account_status, block_reason, outstanding_balance_paise FROM tenant_billing_accounts WHERE tenant_id = ?",
        (organization_id,),
    ).fetchone()

    if not row:
        return

    status = row["account_status"]
    if status == "HARD_BLOCKED":
        raise DomainError(
            402,
            f"Account Suspended: Access blocked for {row['tenant_name']} due to overdue balance of ₹{row['outstanding_balance_paise'] / 100:,.2f}. {row['block_reason']}".strip(),
            "TENANT_BLOCKED_NON_PAYMENT",
            {
                "tenant_id": row["tenant_id"],
                "account_status": status,
                "amount_owed_paise": row["outstanding_balance_paise"],
                "block_reason": row["block_reason"],
            },
        )
    elif status == "SOFT_BLOCKED":
        # Disallow new booking or duty creations; allow active duty closings, telemetry, and reads
        is_new_trip_action = (method == "POST" and route in {"/api/bookings", "/api/duties", "/api/trips"}) or (
            method == "POST" and route.startswith("/api/bookings/") and route.endswith("/dispatch")
        )
        if is_new_trip_action:
            raise DomainError(
                402,
                f"Account Restricted: New bookings and dispatches are blocked due to overdue balance of ₹{row['outstanding_balance_paise'] / 100:,.2f}. Active in-flight trips may still be completed.",
                "TENANT_BLOCKED_NON_PAYMENT",
                {
                    "tenant_id": row["tenant_id"],
                    "account_status": status,
                    "amount_owed_paise": row["outstanding_balance_paise"],
                    "block_reason": row["block_reason"],
                },
            )


def handle_public_prospects(conn: sqlite3.Connection, method: str, path: str, payload: Dict[str, Any], ip: str) -> Optional[Dict[str, Any]]:
    """Handles public lead intake (POST /api/public/prospects and /api/v1/public/prospects)."""
    route = urlsplit(path).path.rstrip("/")
    if route not in {"/api/public/prospects", "/api/v1/public/prospects"}:
        return None

    if method != "POST":
        raise DomainError(405, "Method Not Allowed", "method_not_allowed")

    email = str(payload.get("email") or "").strip().lower() or None
    raw_mobile = str(payload.get("mobile_number") or payload.get("phone") or "").strip() or None
    mobile = None
    mobile_last10 = None
    if raw_mobile:
        digits = re.sub(r"\D", "", raw_mobile)
        if len(digits) >= 10:
            mobile_last10 = digits[-10:]
            mobile = f"+91{mobile_last10}"
        else:
            mobile = digits
            mobile_last10 = digits

    if not email and not mobile:
        raise DomainError(400, "Validation Error: Either email ID or mobile number must be provided.", "missing_contact_info")

    contact_name = str(payload.get("contact_name") or payload.get("name") or "").strip()
    company_name = str(payload.get("company_name") or payload.get("company") or "").strip()
    message = str(payload.get("message") or payload.get("notes") or "").strip()
    now = now_iso()

    # Deduplicate against existing prospects
    existing = None
    if email:
        existing = conn.execute("SELECT * FROM prospects WHERE lower(email) = ?", (email,)).fetchone()
    if not existing and mobile_last10:
        existing = conn.execute("SELECT * FROM prospects WHERE mobile_number = ? OR mobile_number LIKE ?", (mobile, f"%{mobile_last10}")).fetchone()

    if existing:
        # Graceful deduplication: append note if message provided
        notes = []
        try:
            notes = json.loads(existing["sales_notes"] or "[]")
        except Exception:
            pass
        if message:
            notes.append({"timestamp": now, "author": "WEBSITE_REPEAT", "note": message})
        conn.execute(
            """UPDATE prospects SET
               contact_name = coalesce(nullif(?, ''), contact_name),
               company_name = coalesce(nullif(?, ''), company_name),
               sales_notes = ?,
               updated_at = ?
               WHERE id = ?""",
            (contact_name, company_name, json.dumps(notes), now, existing["id"]),
        )
        conn.commit()
        return {
            "ok": True,
            "prospect_id": existing["id"],
            "status": existing["status"],
            "message": "Prospect inquiry received and updated.",
            "deduplicated": True,
        }

    # New prospect
    prsp_id = f"prsp_{uuid.uuid4().hex[:10]}"
    notes = []
    if message:
        notes.append({"timestamp": now, "author": "WEBSITE_SUBMISSION", "note": message})

    conn.execute(
        """INSERT INTO prospects (id, contact_name, company_name, email, mobile_number, message, source, status, sales_notes, assigned_sales_rep, converted_tenant_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 'WEBSITE', 'NEW', ?, '', NULL, ?, ?)""",
        (prsp_id, contact_name, company_name, email, mobile, message, json.dumps(notes), now, now),
    )
    conn.commit()

    return {
        "ok": True,
        "prospect_id": prsp_id,
        "status": "NEW",
        "message": "Prospect captured successfully.",
        "deduplicated": False,
    }


def handle_commercial(
    conn: sqlite3.Connection,
    user: Dict[str, Any],
    method: str,
    path: str,
    payload: Dict[str, Any],
    ip: str,
) -> Optional[Dict[str, Any]]:
    """Handles Super-Admin commercial CRM, company overview, receivables, and kill-switch endpoints."""
    parsed = urlsplit(path)
    route = parsed.path.rstrip("/")
    query_params = parse_qs(parsed.query)

    is_prospect_route = route in {"/api/admin/prospects", "/api/v1/admin/prospects"} or route.startswith(
        ("/api/admin/prospects/", "/api/v1/admin/prospects/")
    )
    is_overview_route = route in {"/api/admin/company-overview", "/api/v1/admin/company-overview"}
    is_tenant_payment_route = (route.startswith("/api/admin/tenants/") or route.startswith("/api/v1/admin/tenants/")) and route.endswith("/payment")
    is_tenant_block_route = (route.startswith("/api/admin/tenants/") or route.startswith("/api/v1/admin/tenants/")) and route.endswith("/block")

    if not (is_prospect_route or is_overview_route or is_tenant_payment_route or is_tenant_block_route):
        return None

    if not _is_admin(user):
        raise DomainError(403, "Access Denied: Super-Admin or Axiom HQ Staff privileges required.", "admin_role_required")

    now = now_iso()

    # 1. GET /api/admin/prospects
    if (route in {"/api/admin/prospects", "/api/v1/admin/prospects"}) and method == "GET":
        status_filter = query_params.get("status", [None])[0]
        search_query = query_params.get("search", [None])[0]

        sql = "SELECT * FROM prospects WHERE 1=1"
        params: List[Any] = []
        if status_filter and status_filter.upper() != "ALL":
            sql += " AND status = ?"
            params.append(status_filter.upper())
        if search_query:
            sql += " AND (lower(contact_name) LIKE ? OR lower(company_name) LIKE ? OR lower(email) LIKE ? OR mobile_number LIKE ?)"
            s = f"%{search_query.lower()}%"
            params.extend([s, s, s, f"%{search_query}%"])
        sql += " ORDER BY created_at DESC"

        rows = conn.execute(sql, params).fetchall()
        prospects = []
        for r in rows:
            d = dict(r)
            try:
                d["sales_notes"] = json.loads(d["sales_notes"] or "[]")
            except Exception:
                d["sales_notes"] = []
            prospects.append(d)
        return {"ok": True, "prospects": prospects, "count": len(prospects)}

    # 2. PATCH /api/admin/prospects/{prospect_id}
    patch_match = re.match(r"^/api(?:/v1)?/admin/prospects/([^/]+)$", route)
    if patch_match and method == "PATCH":
        prsp_id = patch_match.group(1)
        row = conn.execute("SELECT * FROM prospects WHERE id = ?", (prsp_id,)).fetchone()
        if not row:
            raise DomainError(404, f"Prospect '{prsp_id}' not found.", "prospect_not_found")

        new_status = payload.get("status")
        sales_rep = payload.get("sales_rep") or payload.get("assigned_sales_rep")
        new_note = payload.get("note") or payload.get("sales_note")

        notes = []
        try:
            notes = json.loads(row["sales_notes"] or "[]")
        except Exception:
            pass

        if new_note:
            notes.append({
                "timestamp": now,
                "author": user.get("email") or "sales_admin",
                "note": str(new_note).strip(),
            })

        status_val = new_status.upper() if new_status else row["status"]
        sales_rep_val = sales_rep if sales_rep is not None else row["assigned_sales_rep"]

        conn.execute(
            """UPDATE prospects SET status = ?, assigned_sales_rep = ?, sales_notes = ?, updated_at = ? WHERE id = ?""",
            (status_val, sales_rep_val, json.dumps(notes), now, prsp_id),
        )
        conn.commit()

        updated = dict(conn.execute("SELECT * FROM prospects WHERE id = ?", (prsp_id,)).fetchone())
        updated["sales_notes"] = notes
        return {"ok": True, "prospect": updated}

    # 3. POST /api/admin/prospects/{prospect_id}/onboard
    onboard_match = re.match(r"^/api(?:/v1)?/admin/prospects/([^/]+)/onboard$", route)
    if onboard_match and method == "POST":
        prsp_id = onboard_match.group(1)
        row = conn.execute("SELECT * FROM prospects WHERE id = ?", (prsp_id,)).fetchone()
        if not row:
            raise DomainError(404, f"Prospect '{prsp_id}' not found.", "prospect_not_found")

        if row["status"] == "ONBOARDED" or row["converted_tenant_id"]:
            raise DomainError(409, f"Prospect '{prsp_id}' has already been onboarded as tenant '{row['converted_tenant_id']}'.", "prospect_already_onboarded")

        # Create Tenant
        tenant_name = row["company_name"] or row["contact_name"] or f"Tenant {prsp_id}"
        tenant_id = f"org_vendor_{uuid.uuid4().hex[:8]}"

        # Insert organization
        conn.execute(
            """INSERT OR REPLACE INTO organizations (id, kind, name, phone, city, gstin, created_at)
               VALUES (?, 'vendor', ?, ?, 'Pune', '', ?)""",
            (tenant_id, tenant_name, row["mobile_number"] or "+919800000000", now),
        )

        # Initialize Tenant Billing Account
        conn.execute(
            """INSERT OR REPLACE INTO tenant_billing_accounts
               (tenant_id, tenant_name, account_status, block_reason, blocked_at, blocked_by, total_billed_paise, total_paid_paise, outstanding_balance_paise, credit_limit_paise, next_due_date, days_overdue, created_at, updated_at)
               VALUES (?, ?, 'ACTIVE', '', NULL, '', 0, 0, 0, 10000000, ?, 0, ?, ?)""",
            (tenant_id, tenant_name, (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)).isoformat(), now, now),
        )

        # Update Prospect
        notes = []
        try:
            notes = json.loads(row["sales_notes"] or "[]")
        except Exception:
            pass
        notes.append({"timestamp": now, "author": user.get("email") or "sales_admin", "note": f"1-Click Onboarded to Tenant ID '{tenant_id}'."})

        conn.execute(
            """UPDATE prospects SET status = 'ONBOARDED', converted_tenant_id = ?, sales_notes = ?, updated_at = ? WHERE id = ?""",
            (tenant_id, json.dumps(notes), now, prsp_id),
        )

        _audit(conn, user, "prospect.onboarded", "prospect", prsp_id, ip, {"tenant_id": tenant_id, "tenant_name": tenant_name})
        conn.commit()

        login_email = row["email"] or f"ops@{tenant_id}.in"
        temp_pwd = f"Axiom@{tenant_id[-4:]}#2026"

        return {
            "ok": True,
            "tenant_id": tenant_id,
            "tenant_name": tenant_name,
            "credentials": {
                "email": login_email,
                "temp_password": temp_pwd,
            },
            "account_status": "ACTIVE",
            "message": f"Successfully onboarded '{tenant_name}' into active tenant.",
        }

    # 4. GET /api/admin/company-overview
    if is_overview_route and method == "GET":
        # System census
        total_users = conn.execute("SELECT count(*) FROM users").fetchone()[0]
        total_drivers = conn.execute("SELECT count(*) FROM domain_drivers").fetchone()[0]
        total_prospects_pending = conn.execute("SELECT count(*) FROM prospects WHERE status != 'ONBOARDED'").fetchone()[0]

        # Tenant breakdown
        tenant_rows = conn.execute("SELECT * FROM tenant_billing_accounts ORDER BY outstanding_balance_paise DESC").fetchall()
        tenants = []
        total_receivables_paise = 0
        overdue_receivables_paise = 0
        active_count = 0
        blocked_count = 0

        for r in tenant_rows:
            d = dict(r)
            tid = d["tenant_id"]
            # Count users and trips for this tenant
            u_count = conn.execute("SELECT count(*) FROM users WHERE organization_id = ?", (tid,)).fetchone()[0]
            trip_count = conn.execute("SELECT count(*) FROM domain_duties WHERE organization_id = ?", (tid,)).fetchone()[0]

            bal = d["outstanding_balance_paise"]
            days_od = d["days_overdue"]
            status = d["account_status"]

            total_receivables_paise += bal
            if days_od > 0 and bal > 0:
                overdue_receivables_paise += bal

            if status == "ACTIVE":
                active_count += 1
            else:
                blocked_count += 1

            tenants.append({
                "tenant_id": tid,
                "tenant_name": d["tenant_name"],
                "user_count": u_count,
                "trip_count": trip_count,
                "total_billed_paise": d["total_billed_paise"],
                "total_paid_paise": d["total_paid_paise"],
                "amount_owed_paise": bal,
                "days_overdue": days_od,
                "account_status": status,
                "block_reason": d["block_reason"],
                "credit_limit_paise": d["credit_limit_paise"],
                "next_due_date": d["next_due_date"],
            })

        return {
            "ok": True,
            "total_tenants": len(tenants),
            "active_tenants": active_count,
            "blocked_tenants": blocked_count,
            "total_users_in_system": total_users,
            "total_drivers": total_drivers,
            "total_prospects_pending": total_prospects_pending,
            "total_receivables_outstanding_paise": total_receivables_paise,
            "overdue_receivables_amount_paise": overdue_receivables_paise,
            "total_receivables_inr": round(total_receivables_paise / 100, 2),
            "overdue_receivables_inr": round(overdue_receivables_paise / 100, 2),
            "tenants": tenants,
        }

    # 5. POST /api/admin/tenants/{tenant_id}/payment
    payment_match = re.match(r"^/api(?:/v1)?/admin/tenants/([^/]+)/payment$", route)
    if payment_match and method == "POST":
        tid = payment_match.group(1)
        row = conn.execute("SELECT * FROM tenant_billing_accounts WHERE tenant_id = ?", (tid,)).fetchone()
        if not row:
            raise DomainError(404, f"Tenant billing account '{tid}' not found.", "tenant_not_found")

        amount_paise = int(payload.get("amount_paise") or 0)
        if amount_paise <= 0:
            raise DomainError(400, "Payment amount must be greater than zero paise.", "invalid_amount")

        payment_method = str(payload.get("payment_method") or "BANK_TRANSFER")
        ref_id = str(payload.get("reference_id") or f"PAY-{uuid.uuid4().hex[:8].upper()}")

        # Record in ledger
        ledger_id = f"rec_pay_{uuid.uuid4().hex[:10]}"
        conn.execute(
            """INSERT INTO axiom_receivable_ledger (id, tenant_id, entry_type, reference_id, amount_paise, description, payment_method, created_by, created_at)
               VALUES (?, ?, 'PAYMENT', ?, ?, 'SaaS invoice settlement payment', ?, ?, ?)""",
            (ledger_id, tid, ref_id, amount_paise, payment_method, user.get("email") or "admin", now),
        )

        new_paid = row["total_paid_paise"] + amount_paise
        new_balance = max(0, row["total_billed_paise"] - new_paid)
        new_status = row["account_status"]
        block_reason = row["block_reason"]
        new_days_overdue = 0 if new_balance == 0 else row["days_overdue"]

        # Auto-unblock if overdue balance is cleared
        if new_balance == 0 and new_status in {"SOFT_BLOCKED", "HARD_BLOCKED"}:
            new_status = "ACTIVE"
            block_reason = "Auto-unblocked: Full overdue balance settled."
            _audit(conn, user, "tenant.auto_unblocked_payment", "tenant_billing_account", tid, ip, {"balance_settled_paise": amount_paise})

        conn.execute(
            """UPDATE tenant_billing_accounts SET
               total_paid_paise = ?,
               outstanding_balance_paise = ?,
               account_status = ?,
               block_reason = ?,
               days_overdue = ?,
               updated_at = ?
               WHERE tenant_id = ?""",
            (new_paid, new_balance, new_status, block_reason, new_days_overdue, now, tid),
        )
        conn.commit()

        return {
            "ok": True,
            "tenant_id": tid,
            "amount_paid_paise": amount_paise,
            "new_amount_owed_paise": new_balance,
            "account_status": new_status,
            "message": f"Payment of ₹{amount_paise / 100:,.2f} recorded for {row['tenant_name']}.",
        }

    # 6. POST /api/admin/tenants/{tenant_id}/block
    block_match = re.match(r"^/api(?:/v1)?/admin/tenants/([^/]+)/block$", route)
    if block_match and method == "POST":
        tid = block_match.group(1)
        row = conn.execute("SELECT * FROM tenant_billing_accounts WHERE tenant_id = ?", (tid,)).fetchone()
        if not row:
            raise DomainError(404, f"Tenant billing account '{tid}' not found.", "tenant_not_found")

        mode = str(payload.get("mode") or "SOFT_BLOCKED").upper()
        if mode not in {"ACTIVE", "SOFT_BLOCKED", "HARD_BLOCKED", "SUSPENDED"}:
            raise DomainError(400, "Invalid block mode. Must be ACTIVE, SOFT_BLOCKED, or HARD_BLOCKED.", "invalid_mode")

        reason = str(payload.get("reason") or "Administrative control action").strip()
        blocked_at = now if mode != "ACTIVE" else None
        blocked_by = user.get("email") or "admin"

        conn.execute(
            """UPDATE tenant_billing_accounts SET
               account_status = ?,
               block_reason = ?,
               blocked_at = ?,
               blocked_by = ?,
               updated_at = ?
               WHERE tenant_id = ?""",
            (mode, reason if mode != "ACTIVE" else "", blocked_at, blocked_by if mode != "ACTIVE" else "", now, tid),
        )

        _audit(conn, user, "tenant.status_changed", "tenant_billing_account", tid, ip, {"previous_status": row["account_status"], "new_status": mode, "reason": reason})
        conn.commit()

        return {
            "ok": True,
            "tenant_id": tid,
            "account_status": mode,
            "reason": reason,
            "message": f"Tenant '{row['tenant_name']}' status updated to '{mode}'.",
        }

    return None
