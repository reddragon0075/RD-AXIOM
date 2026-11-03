"""Axiom Mobility (Fleetline) - Dual-Ledger Fund Release Hold & Treasury Control Service.

Implements:
1. Platform Settings (Global Hold Toggle & Cooling Duration Hours).
2. Per-Vendor Payout Hold Override (INHERIT_GLOBAL, FORCE_HOLD, AUTO_RELEASE).
3. Supplier Payable Ledger State Machine (ESCROW_LOCKED -> AUDIT_HOLD -> FUNDS_HELD_BY_AXIOM -> READY_FOR_RELEASE -> RELEASED_TO_WALLET).
4. Immutable Treasury Release Audit Logs.
5. Batch and Atomic Fund Release Cleared via Payout Gate Resolver.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, ROUND_HALF_UP
import json
import sqlite3
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit
import uuid

from backend_domain import DomainError, _audit, new_id, now_iso


def _is_staff(user: Dict[str, Any]) -> bool:
    """Verifies user has Super-Admin or Axiom HQ staff permissions."""
    role = str(user.get("role") or "").lower()
    email = str(user.get("email") or "").lower()
    return (
        role in {"axiom_super_admin", "axiom_admin", "axiom_staff", "admin", "super_admin"}
        or email.endswith("@axiomfleet.in")
        or str(user.get("organization_id") or "") == "org_axiom_hq"
    )


def initialize_treasury_release_schema(conn: sqlite3.Connection) -> None:
    """Initializes tables for platform treasury settings, supplier payable ledger, and audit logs."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS axiom_treasury_global_holds (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'GLOBAL',
            is_active INTEGER NOT NULL DEFAULT 1,
            reason TEXT,
            set_by TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS platform_settings (
            id TEXT PRIMARY KEY DEFAULT 'global_default',
            global_payout_release_enabled INTEGER NOT NULL DEFAULT 0,
            default_fund_hold_hours INTEGER NOT NULL DEFAULT 72,
            t0_instant_cashout_enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS supplier_payable_ledger (
            id TEXT PRIMARY KEY,
            duty_id TEXT NOT NULL,
            vendor_id TEXT NOT NULL,
            amount_paise INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'ESCROW_LOCKED' CHECK (status IN ('ESCROW_LOCKED', 'AUDIT_HOLD', 'FUNDS_HELD_BY_AXIOM', 'READY_FOR_RELEASE', 'RELEASED_TO_WALLET')),
            audit_passed_at TEXT,
            eligible_for_release_at TEXT,
            staff_hold_locked INTEGER NOT NULL DEFAULT 1,
            released_by_staff_id TEXT,
            released_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_spl_vendor_status ON supplier_payable_ledger(vendor_id, status);
        CREATE INDEX IF NOT EXISTS idx_spl_duty ON supplier_payable_ledger(duty_id);

        CREATE TABLE IF NOT EXISTS treasury_release_audit_logs (
            id TEXT PRIMARY KEY,
            actor_staff_id TEXT NOT NULL,
            action_type TEXT NOT NULL CHECK (action_type IN ('GLOBAL_TOGGLE', 'VENDOR_TOGGLE', 'BATCH_MANUAL_RELEASE', 'FORCE_RELEASE')),
            target_vendor_id TEXT,
            previous_state TEXT,
            new_state TEXT,
            total_amount_affected_inr REAL NOT NULL DEFAULT 0.0,
            reason_note TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_treasury_logs_vendor ON treasury_release_audit_logs(target_vendor_id);
        CREATE INDEX IF NOT EXISTS idx_treasury_logs_action ON treasury_release_audit_logs(action_type, created_at DESC);
        """
    )

    # Seed default platform settings if not present
    now = now_iso()
    cur = conn.execute("SELECT count(*) FROM platform_settings WHERE id = 'global_default'")
    if cur.fetchone()[0] == 0:
        conn.execute(
            """INSERT INTO platform_settings (id, global_payout_release_enabled, default_fund_hold_hours, t0_instant_cashout_enabled, created_at, updated_at)
               VALUES ('global_default', 0, 72, 1, ?, ?)""",
            (now, now),
        )

    # Add vendor hold columns to tenant_billing_accounts if missing
    try:
        tcols = {r["name"] for r in conn.execute("PRAGMA table_info(tenant_billing_accounts)").fetchall()}
        if tcols:
            if "payout_hold_override" not in tcols:
                conn.execute("ALTER TABLE tenant_billing_accounts ADD COLUMN payout_hold_override TEXT NOT NULL DEFAULT 'INHERIT_GLOBAL'")
            if "payout_hold_reason" not in tcols:
                conn.execute("ALTER TABLE tenant_billing_accounts ADD COLUMN payout_hold_reason TEXT DEFAULT ''")
            if "payout_hold_updated_by" not in tcols:
                conn.execute("ALTER TABLE tenant_billing_accounts ADD COLUMN payout_hold_updated_by TEXT DEFAULT ''")
            if "payout_hold_updated_at" not in tcols:
                conn.execute("ALTER TABLE tenant_billing_accounts ADD COLUMN payout_hold_updated_at TEXT")
    except Exception:
        pass


def get_platform_settings(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Retrieves singleton platform settings."""
    row = conn.execute("SELECT * FROM platform_settings WHERE id = 'global_default'").fetchone()
    if not row:
        now = now_iso()
        conn.execute(
            """INSERT OR IGNORE INTO platform_settings (id, global_payout_release_enabled, default_fund_hold_hours, t0_instant_cashout_enabled, created_at, updated_at)
               VALUES ('global_default', 0, 72, 1, ?, ?)""",
            (now, now),
        )
        row = conn.execute("SELECT * FROM platform_settings WHERE id = 'global_default'").fetchone()
    return {
        "id": row["id"],
        "global_payout_release_enabled": bool(row["global_payout_release_enabled"]),
        "default_fund_hold_hours": int(row["default_fund_hold_hours"]),
        "t0_instant_cashout_enabled": bool(row["t0_instant_cashout_enabled"]),
        "updated_at": row["updated_at"],
    }


def compute_release_eligibility(audit_passed_at_iso: str, hold_hours: int) -> str:
    """Computes ISO timestamp when funds become mature for release."""
    try:
        ts = dt.datetime.fromisoformat(audit_passed_at_iso.replace("Z", "+00:00"))
    except Exception:
        ts = dt.datetime.now(dt.timezone.utc)
    eligible = ts + dt.timedelta(hours=hold_hours)
    return eligible.isoformat()


def record_duty_completion_payable(
    conn: sqlite3.Connection,
    duty_id: str,
    vendor_id: str,
    amount_paise: int,
    audit_status: str = "PASSED",
) -> Dict[str, Any]:
    """Records or updates a supplier payable ledger entry upon duty completion."""
    now = now_iso()
    settings = get_platform_settings(conn)
    hold_hours = settings["default_fund_hold_hours"]
    global_enabled = settings["global_payout_release_enabled"]

    # Check vendor override
    vendor_row = conn.execute(
        "SELECT payout_hold_override FROM tenant_billing_accounts WHERE tenant_id = ?",
        (vendor_id,),
    ).fetchone()
    override = vendor_row["payout_hold_override"] if vendor_row and "payout_hold_override" in vendor_row.keys() else "INHERIT_GLOBAL"

    if audit_status == "PASSED":
        status = "FUNDS_HELD_BY_AXIOM"
        audit_passed_at = now
        eligible_for_release_at = compute_release_eligibility(audit_passed_at, hold_hours)
        # Locked if global release is disabled OR vendor is force held
        staff_hold_locked = 1 if (not global_enabled or override == "FORCE_HOLD") else 0
    elif audit_status == "NEEDS_AUDIT":
        status = "AUDIT_HOLD"
        audit_passed_at = None
        eligible_for_release_at = None
        staff_hold_locked = 1
    else:
        status = "ESCROW_LOCKED"
        audit_passed_at = None
        eligible_for_release_at = None
        staff_hold_locked = 1

    entry_id = f"spl_{uuid.uuid4().hex[:12]}"
    conn.execute(
        """INSERT INTO supplier_payable_ledger (
            id, duty_id, vendor_id, amount_paise, status, audit_passed_at, eligible_for_release_at,
            staff_hold_locked, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (entry_id, duty_id, vendor_id, amount_paise, status, audit_passed_at, eligible_for_release_at, staff_hold_locked, now, now),
    )

    return {
        "id": entry_id,
        "duty_id": duty_id,
        "vendor_id": vendor_id,
        "amount_paise": amount_paise,
        "status": status,
        "eligible_for_release_at": eligible_for_release_at,
        "staff_hold_locked": bool(staff_hold_locked),
    }


def can_release_vendor_funds(
    conn: sqlite3.Connection,
    vendor_id: str,
    ledger_entry_id: str,
    is_force_release: bool = False,
) -> Tuple[bool, str, Optional[sqlite3.Row]]:
    """Evaluates whether a specific supplier payable ledger entry is eligible to transition to RELEASED_TO_WALLET.

    Rule 1: duty audit status must be passed.
    Rule 2: vendor owes no overdue platform dues (account not blocked / suspended).
    Rule 3: vendor payout_hold_override != 'FORCE_HOLD'.
    Rule 4: global release enabled AND cooling window elapsed AND staff_hold_locked == False (unless force-release).
    """
    entry = conn.execute(
        "SELECT * FROM supplier_payable_ledger WHERE id = ? AND vendor_id = ?",
        (ledger_entry_id, vendor_id),
    ).fetchone()

    if not entry:
        return False, "Ledger entry not found", None

    if entry["status"] == "RELEASED_TO_WALLET":
        return False, "Funds already released to wallet", entry

    # 1. Audit Check
    if entry["status"] in ("ESCROW_LOCKED", "AUDIT_HOLD") or not entry["audit_passed_at"]:
        return False, "Duty has not passed 3-Way Distance & Compliance Audit", entry

    # 2. Vendor Delinquency Check
    v_row = conn.execute(
        "SELECT account_status, payout_hold_override, payout_hold_reason FROM tenant_billing_accounts WHERE tenant_id = ?",
        (vendor_id,),
    ).fetchone()

    if v_row:
        status_val = str(v_row["account_status"]).upper()
        if status_val in ("SOFT_BLOCKED", "HARD_BLOCKED", "SUSPENDED"):
            return False, f"Vendor account is {status_val} for overdue platform fees", entry

        override_val = str(v_row["payout_hold_override"] or "INHERIT_GLOBAL").upper()
        if override_val == "FORCE_HOLD":
            reason = v_row["payout_hold_reason"] or "Administrative hold active"
            return False, f"Vendor payout is set to FORCE_HOLD: {reason}", entry

    if is_force_release:
        return True, "Force release authorized by Super-Admin", entry

    # 3. Global Setting & Cooling Window
    settings = get_platform_settings(conn)
    if not settings["global_payout_release_enabled"]:
        return False, "Global payout release is currently LOCKED by Axiom Staff", entry

    if entry["staff_hold_locked"]:
        return False, "Entry is marked as staff_hold_locked", entry

    # Cooling window check
    if entry["eligible_for_release_at"]:
        now_ts = dt.datetime.now(dt.timezone.utc)
        elig_ts = dt.datetime.fromisoformat(entry["eligible_for_release_at"].replace("Z", "+00:00"))
        if now_ts < elig_ts:
            remaining_mins = int((elig_ts - now_ts).total_seconds() / 60)
            return False, f"Holding cooling window active ({remaining_mins} minutes remaining)", entry

    return True, "All payout release criteria satisfied", entry


def toggle_global_hold(
    conn: sqlite3.Connection,
    staff_user: Dict[str, Any],
    global_enabled: bool,
    default_hold_hours: Optional[int],
    reason: str,
    ip: str = "127.0.0.1",
) -> Dict[str, Any]:
    """Toggles global payout release switch and updates default holding duration."""
    if not _is_staff(staff_user):
        raise DomainError("Unauthorized: Axiom Staff or Super-Admin role required", 403)

    now = now_iso()
    prev = get_platform_settings(conn)
    new_hours = default_hold_hours if default_hold_hours is not None else prev["default_fund_hold_hours"]

    conn.execute(
        """UPDATE platform_settings
           SET global_payout_release_enabled = ?, default_fund_hold_hours = ?, updated_at = ?
           WHERE id = 'global_default'""",
        (1 if global_enabled else 0, new_hours, now),
    )

    # Update staff_hold_locked flags on held entries accordingly (unless vendor is FORCE_HOLD)
    if global_enabled:
        conn.execute(
            """UPDATE supplier_payable_ledger
               SET staff_hold_locked = 0, updated_at = ?
               WHERE status = 'FUNDS_HELD_BY_AXIOM'
                 AND vendor_id NOT IN (
                     SELECT tenant_id FROM tenant_billing_accounts WHERE payout_hold_override = 'FORCE_HOLD'
                 )""",
            (now,),
        )
    else:
        conn.execute(
            """UPDATE supplier_payable_ledger
               SET staff_hold_locked = 1, updated_at = ?
               WHERE status = 'FUNDS_HELD_BY_AXIOM'""",
            (now,),
        )

    # Count total affected held float
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_paise), 0) AS total_paise FROM supplier_payable_ledger WHERE status = 'FUNDS_HELD_BY_AXIOM'"
    ).fetchone()
    total_inr = round(row["total_paise"] / 100.0, 2)

    log_id = f"tlog_{uuid.uuid4().hex[:12]}"
    conn.execute(
        """INSERT INTO treasury_release_audit_logs (
            id, actor_staff_id, action_type, target_vendor_id, previous_state, new_state,
            total_amount_affected_inr, reason_note, created_at
        ) VALUES (?, ?, 'GLOBAL_TOGGLE', 'ALL', ?, ?, ?, ?, ?)""",
        (
            log_id,
            staff_user.get("id", "staff_admin"),
            f"ENABLED={prev['global_payout_release_enabled']};HOURS={prev['default_fund_hold_hours']}",
            f"ENABLED={global_enabled};HOURS={new_hours}",
            total_inr,
            reason or "Global treasury payout toggle updated",
            now,
        ),
    )

    return {
        "ok": True,
        "global_payout_release_enabled": global_enabled,
        "default_fund_hold_hours": new_hours,
        "total_amount_affected_inr": total_inr,
        "audit_log_id": log_id,
    }


def toggle_vendor_hold(
    conn: sqlite3.Connection,
    staff_user: Dict[str, Any],
    vendor_id: str,
    hold_override: str,
    reason: str,
    ip: str = "127.0.0.1",
) -> Dict[str, Any]:
    """Toggles payout hold override for a specific vendor ('INHERIT_GLOBAL', 'FORCE_HOLD', 'AUTO_RELEASE')."""
    if not _is_staff(staff_user):
        raise DomainError("Unauthorized: Axiom Staff or Super-Admin role required", 403)

    if hold_override not in ("INHERIT_GLOBAL", "FORCE_HOLD", "AUTO_RELEASE"):
        raise DomainError("Invalid payout_hold_override. Must be INHERIT_GLOBAL, FORCE_HOLD, or AUTO_RELEASE", 422)

    now = now_iso()
    v_row = conn.execute(
        "SELECT payout_hold_override FROM tenant_billing_accounts WHERE tenant_id = ?",
        (vendor_id,),
    ).fetchone()
    prev_override = v_row["payout_hold_override"] if v_row and "payout_hold_override" in v_row.keys() else "INHERIT_GLOBAL"

    conn.execute(
        """UPDATE tenant_billing_accounts
           SET payout_hold_override = ?, payout_hold_reason = ?, payout_hold_updated_by = ?, payout_hold_updated_at = ?
           WHERE tenant_id = ?""",
        (hold_override, reason or "", staff_user.get("id", "staff_admin"), now, vendor_id),
    )

    # If FORCE_HOLD, lock all unreleased rows for this vendor
    if hold_override == "FORCE_HOLD":
        conn.execute(
            "UPDATE supplier_payable_ledger SET staff_hold_locked = 1, updated_at = ? WHERE vendor_id = ? AND status = 'FUNDS_HELD_BY_AXIOM'",
            (now, vendor_id),
        )
    elif hold_override == "AUTO_RELEASE":
        conn.execute(
            "UPDATE supplier_payable_ledger SET staff_hold_locked = 0, updated_at = ? WHERE vendor_id = ? AND status = 'FUNDS_HELD_BY_AXIOM'",
            (now, vendor_id),
        )

    # Tally affected vendor funds
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_paise), 0) AS total_paise FROM supplier_payable_ledger WHERE vendor_id = ? AND status = 'FUNDS_HELD_BY_AXIOM'",
        (vendor_id,),
    ).fetchone()
    total_inr = round(row["total_paise"] / 100.0, 2)

    log_id = f"tlog_{uuid.uuid4().hex[:12]}"
    conn.execute(
        """INSERT INTO treasury_release_audit_logs (
            id, actor_staff_id, action_type, target_vendor_id, previous_state, new_state,
            total_amount_affected_inr, reason_note, created_at
        ) VALUES (?, ?, 'VENDOR_TOGGLE', ?, ?, ?, ?, ?, ?)""",
        (
            log_id,
            staff_user.get("id", "staff_admin"),
            vendor_id,
            prev_override,
            hold_override,
            total_inr,
            reason or "Vendor payout hold toggle updated",
            now,
        ),
    )

    return {
        "ok": True,
        "vendor_id": vendor_id,
        "payout_hold_override": hold_override,
        "total_amount_affected_inr": total_inr,
        "audit_log_id": log_id,
    }


def release_batch(
    conn: sqlite3.Connection,
    staff_user: Dict[str, Any],
    vendor_id: Optional[str] = None,
    ledger_entry_ids: Optional[List[str]] = None,
    is_force_release: bool = False,
    reason: str = "Batch release approved by Axiom Staff",
    ip: str = "127.0.0.1",
) -> Dict[str, Any]:
    """Atomically releases eligible or mature held funds to vendor's withdrawable wallet."""
    if not _is_staff(staff_user):
        raise DomainError("Unauthorized: Axiom Staff or Super-Admin role required", 403)

    now = now_iso()
    query = "SELECT * FROM supplier_payable_ledger WHERE status = 'FUNDS_HELD_BY_AXIOM'"
    params = []

    if vendor_id:
        query += " AND vendor_id = ?"
        params.append(vendor_id)

    if ledger_entry_ids:
        placeholders = ",".join("?" for _ in ledger_entry_ids)
        query += f" AND id IN ({placeholders})"
        params.extend(ledger_entry_ids)

    candidate_rows = conn.execute(query, params).fetchall()

    released_entries = []
    total_released_paise = 0

    for row in candidate_rows:
        ok, why, _ = can_release_vendor_funds(conn, row["vendor_id"], row["id"], is_force_release=is_force_release)
        if ok:
            conn.execute(
                """UPDATE supplier_payable_ledger
                   SET status = 'RELEASED_TO_WALLET', released_by_staff_id = ?, released_at = ?, updated_at = ?
                   WHERE id = ?""",
                (staff_user.get("id", "staff_admin"), now, now, row["id"]),
            )
            # Update withdrawable balance in tenant_billing_accounts if available
            try:
                conn.execute(
                    """UPDATE tenant_billing_accounts
                       SET total_paid_paise = total_paid_paise + ?, updated_at = ?
                       WHERE tenant_id = ?""",
                    (row["amount_paise"], now, row["vendor_id"]),
                )
            except Exception:
                pass

            released_entries.append(row["id"])
            total_released_paise += row["amount_paise"]

    total_released_inr = round(Decimal(total_released_paise) / Decimal("100"), 2)

    log_id = f"tlog_{uuid.uuid4().hex[:12]}"
    conn.execute(
        """INSERT INTO treasury_release_audit_logs (
            id, actor_staff_id, action_type, target_vendor_id, previous_state, new_state,
            total_amount_affected_inr, reason_note, created_at
        ) VALUES (?, ?, ?, ?, 'FUNDS_HELD_BY_AXIOM', 'RELEASED_TO_WALLET', ?, ?, ?)""",
        (
            log_id,
            staff_user.get("id", "staff_admin"),
            "FORCE_RELEASE" if is_force_release else "BATCH_MANUAL_RELEASE",
            vendor_id or "MULTIPLE",
            float(total_released_inr),
            reason,
            now,
        ),
    )

    return {
        "ok": True,
        "released_count": len(released_entries),
        "released_entries": released_entries,
        "total_released_paise": total_released_paise,
        "total_released_inr": float(total_released_inr),
        "audit_log_id": log_id,
    }


def get_treasury_summary(conn: sqlite3.Connection, staff_user: Dict[str, Any]) -> Dict[str, Any]:
    """Generates real-time treasury KPIs and vendor payout statuses."""
    if not _is_staff(staff_user):
        raise DomainError("Unauthorized: Axiom Staff or Super-Admin role required", 403)

    settings = get_platform_settings(conn)
    now_ts = dt.datetime.now(dt.timezone.utc)

    # 1. Total funds held across all incomplete/cooling entries
    held_row = conn.execute(
        """SELECT COALESCE(SUM(amount_paise), 0) AS total_paise, COUNT(*) AS count
           FROM supplier_payable_ledger
           WHERE status IN ('FUNDS_HELD_BY_AXIOM', 'AUDIT_HOLD', 'ESCROW_LOCKED')"""
    ).fetchone()
    total_held_paise = int(held_row["total_paise"] or 0)
    held_duties_count = int(held_row["count"] or 0)

    # 2. Mature & ready to release (cooling elapsed and not blocked)
    mature_paise = 0
    mature_count = 0
    active_held_rows = conn.execute(
        "SELECT * FROM supplier_payable_ledger WHERE status = 'FUNDS_HELD_BY_AXIOM'"
    ).fetchall()

    for r in active_held_rows:
        ok, _, _ = can_release_vendor_funds(conn, r["vendor_id"], r["id"], is_force_release=False)
        if ok:
            mature_paise += r["amount_paise"]
            mature_count += 1

    # 3. Vendor Table Statuses
    vendors_list = []
    try:
        tenants = conn.execute("SELECT * FROM tenant_billing_accounts ORDER BY tenant_name ASC").fetchall()
        for t in tenants:
            tid = t["tenant_id"]
            v_held = conn.execute(
                "SELECT COALESCE(SUM(amount_paise), 0) AS s FROM supplier_payable_ledger WHERE vendor_id = ? AND status = 'FUNDS_HELD_BY_AXIOM'",
                (tid,),
            ).fetchone()["s"]

            v_released = conn.execute(
                "SELECT COALESCE(SUM(amount_paise), 0) AS s FROM supplier_payable_ledger WHERE vendor_id = ? AND status = 'RELEASED_TO_WALLET'",
                (tid,),
            ).fetchone()["s"]

            vendors_list.append({
                "tenant_id": tid,
                "tenant_name": t["tenant_name"],
                "account_status": t["account_status"],
                "held_float_paise": int(v_held or 0),
                "held_float_inr": round((v_held or 0) / 100.0, 2),
                "withdrawable_paise": int(v_released or 0),
                "withdrawable_inr": round((v_released or 0) / 100.0, 2),
                "payout_hold_override": t["payout_hold_override"] if "payout_hold_override" in t.keys() and t["payout_hold_override"] else "INHERIT_GLOBAL",
                "payout_hold_reason": t["payout_hold_reason"] if "payout_hold_reason" in t.keys() else "",
            })
    except Exception:
        pass

    return {
        "ok": True,
        "global_payout_release_enabled": settings["global_payout_release_enabled"],
        "default_fund_hold_hours": settings["default_fund_hold_hours"],
        "t0_instant_cashout_enabled": settings["t0_instant_cashout_enabled"],
        "total_funds_held_paise": total_held_paise,
        "total_funds_held_inr": round(total_held_paise / 100.0, 2),
        "total_mature_ready_paise": mature_paise,
        "total_mature_ready_inr": round(mature_paise / 100.0, 2),
        "held_duties_count": held_duties_count,
        "mature_duties_count": mature_count,
        "vendors": vendors_list,
    }


def get_vendor_payout_balance(conn: sqlite3.Connection, user: Dict[str, Any]) -> Dict[str, Any]:
    """Retrieves the caller vendor's dual-ledger payout balances for dashboard display."""
    vendor_id = user.get("organization_id") or user.get("tenant_id")
    if not vendor_id:
        raise DomainError("Vendor tenant ID missing from user context", 400)

    # Total Earned (all payable duties completed)
    earned_row = conn.execute(
        """SELECT COALESCE(SUM(amount_paise), 0) AS total_paise
           FROM supplier_payable_ledger
           WHERE vendor_id = ?""",
        (vendor_id,),
    ).fetchone()
    total_earned_paise = int(earned_row["total_paise"] or 0)

    # Held in Clearing
    held_row = conn.execute(
        """SELECT COALESCE(SUM(amount_paise), 0) AS total_paise
           FROM supplier_payable_ledger
           WHERE vendor_id = ? AND status IN ('FUNDS_HELD_BY_AXIOM', 'AUDIT_HOLD', 'ESCROW_LOCKED')""",
        (vendor_id,),
    ).fetchone()
    in_clearing_held_paise = int(held_row["total_paise"] or 0)

    # Released & Withdrawable
    released_row = conn.execute(
        """SELECT COALESCE(SUM(amount_paise), 0) AS total_paise
           FROM supplier_payable_ledger
           WHERE vendor_id = ? AND status = 'RELEASED_TO_WALLET'""",
        (vendor_id,),
    ).fetchone()
    released_withdrawable_paise = int(released_row["total_paise"] or 0)

    v_row = conn.execute(
        "SELECT payout_hold_override, payout_hold_reason FROM tenant_billing_accounts WHERE tenant_id = ?",
        (vendor_id,),
    ).fetchone()
    override = v_row["payout_hold_override"] if v_row and "payout_hold_override" in v_row.keys() else "INHERIT_GLOBAL"
    reason = v_row["payout_hold_reason"] if v_row and "payout_hold_reason" in v_row.keys() else ""

    return {
        "ok": True,
        "vendor_id": vendor_id,
        "total_earned_paise": total_earned_paise,
        "total_earned_inr": round(total_earned_paise / 100.0, 2),
        "in_clearing_held_paise": in_clearing_held_paise,
        "in_clearing_held_inr": round(in_clearing_held_paise / 100.0, 2),
        "released_withdrawable_paise": released_withdrawable_paise,
        "released_withdrawable_inr": round(released_withdrawable_paise / 100.0, 2),
        "payout_hold_override": override,
        "payout_hold_reason": reason,
    }


def handle_treasury_release(
    conn: sqlite3.Connection,
    user: Dict[str, Any],
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    ip: str = "127.0.0.1",
) -> Dict[str, Any]:
    """Master routing dispatcher for Treasury Fund Release & Hold APIs."""
    payload = payload or {}
    norm_path = path.replace("/api/v1", "/api")

    # 1. Super-Admin Treasury Summary
    if norm_path == "/api/admin/treasury/summary" and method == "GET":
        return get_treasury_summary(conn, user)

    # 2. Super-Admin Global Toggle
    if norm_path == "/api/admin/treasury/global-toggle" and method in ("PATCH", "POST"):
        enabled = bool(payload.get("global_payout_release_enabled", False))
        hold_hours = payload.get("default_fund_hold_hours")
        if hold_hours is not None:
            hold_hours = int(hold_hours)
        reason = str(payload.get("reason", "Global toggle modified"))
        return toggle_global_hold(conn, user, enabled, hold_hours, reason, ip)

    # 3. Super-Admin Per-Vendor Toggle
    if "/api/admin/treasury/vendor-toggle/" in norm_path and method in ("PATCH", "POST"):
        parts = norm_path.split("/api/admin/treasury/vendor-toggle/")
        vendor_id = parts[1].split("/")[0].split("?")[0]
        override = str(payload.get("payout_hold_override", "INHERIT_GLOBAL")).upper()
        reason = str(payload.get("reason", "Vendor hold toggle modified"))
        return toggle_vendor_hold(conn, user, vendor_id, override, reason, ip)

    # 4. Super-Admin Batch Release
    if norm_path == "/api/admin/treasury/release-batch" and method == "POST":
        vendor_id = payload.get("vendor_id")
        entry_ids = payload.get("ledger_entry_ids")
        reason = str(payload.get("reason", "Batch release triggered by Super-Admin"))
        return release_batch(conn, user, vendor_id=vendor_id, ledger_entry_ids=entry_ids, is_force_release=False, reason=reason, ip=ip)

    # 5. Super-Admin Force Release
    if norm_path == "/api/admin/treasury/force-release" and method == "POST":
        entry_id = payload.get("ledger_entry_id")
        if not entry_id:
            raise DomainError("ledger_entry_id is required for force-release", 422)
        row = conn.execute("SELECT vendor_id FROM supplier_payable_ledger WHERE id = ?", (entry_id,)).fetchone()
        if not row:
            raise DomainError("Ledger entry not found", 404)
        reason = str(payload.get("reason", "Super-Admin force-release"))
        return release_batch(conn, user, vendor_id=row["vendor_id"], ledger_entry_ids=[entry_id], is_force_release=True, reason=reason, ip=ip)

    # 6. Vendor Dashboard Payout Balance
    if norm_path == "/api/vendor/payout-balance" and method == "GET":
        return get_vendor_payout_balance(conn, user)

    raise DomainError(f"Treasury endpoint not found: {method} {path}", 404)


def set_global_treasury_payout_hold(
    conn: sqlite3.Connection,
    staff_user: Dict[str, Any],
    is_held: bool,
    reason: str = "",
    ip: str = "127.0.0.1",
) -> Dict[str, Any]:
    """Sets the global Axiom treasury payout hold toggle and records audit log."""
    if not _is_staff(staff_user):
        raise DomainError("Unauthorized: Axiom Staff or Super-Admin role required", 403)
    now = now_iso()
    # 1. Update platform_settings (global_payout_release_enabled is False when is_held is True)
    conn.execute(
        """UPDATE platform_settings
           SET global_payout_release_enabled = ?, updated_at = ?
           WHERE id = 'global_default'""",
        (0 if is_held else 1, now),
    )
    # 2. Maintain axiom_treasury_global_holds table for hyper network / factoring queries
    conn.execute(
        """CREATE TABLE IF NOT EXISTS axiom_treasury_global_holds (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'GLOBAL',
            is_active INTEGER NOT NULL DEFAULT 1,
            reason TEXT,
            set_by TEXT,
            created_at TEXT NOT NULL
        )"""
    )
    hold_id = f"hold_{uuid.uuid4().hex[:10]}"
    conn.execute(
        """INSERT INTO axiom_treasury_global_holds (id, tenant_id, is_active, reason, set_by, created_at)
           VALUES (?, 'GLOBAL', ?, ?, ?, ?)""",
        (hold_id, 1 if is_held else 0, reason, staff_user.get("id", "staff_admin"), now),
    )
    conn.commit()
    return {"ok": True, "is_held": is_held, "reason": reason}
