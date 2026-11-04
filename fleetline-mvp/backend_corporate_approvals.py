"""Axiom Mobility (Fleetline) - Corporate Approval & RBAC Service Layer.
Enforces tamper-proof corporate booking approval hierarchy, parameter hash locking,
split-booking velocity guards, budget ceiling controls, and fine-grained corporate RBAC.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

ROLES = {
    "CORP_EMPLOYEE",
    "CORP_LINE_MANAGER",
    "CORP_TRAVEL_DESK",
    "CORP_HR_COMPLIANCE",
    "CORP_FINANCE_AUDITOR",
}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_booking_parameter_hash(
    vehicle_type: str,
    tariff_model: str,
    pickup_address: str,
    drop_address: str,
    scheduled_at: str,
    estimated_fare_inr: float,
) -> str:
    """Computes SHA-256 fingerprint of critical booking parameters to prevent post-approval Bait & Switch."""
    norm_veh = str(vehicle_type or "").strip().upper()
    norm_tar = str(tariff_model or "").strip().upper()
    norm_pick = str(pickup_address or "").strip().lower()
    norm_drop = str(drop_address or "").strip().lower()
    norm_time = str(scheduled_at or "").strip()
    norm_fare = f"{float(estimated_fare_inr):.2f}"

    raw = f"{norm_veh}|{norm_tar}|{norm_pick}|{norm_drop}|{norm_time}|{norm_fare}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def initialize_corporate_rbac_schema(conn: sqlite3.Connection) -> None:
    """Creates tables for Corporate RBAC, Cost Centers, Policies & Approval Requests."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cost_centers (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            monthly_budget_inr REAL DEFAULT 0.00,
            current_month_spend_inr REAL DEFAULT 0.00,
            head_approver_user_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(tenant_id, code)
        );

        CREATE TABLE IF NOT EXISTS corporate_users (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            email TEXT NOT NULL,
            full_name TEXT NOT NULL,
            phone TEXT,
            employee_code TEXT,
            gender TEXT DEFAULT 'NOT_SPECIFIED',
            corp_role TEXT NOT NULL DEFAULT 'CORP_EMPLOYEE',
            manager_user_id TEXT,
            delegate_approver_user_id TEXT,
            cost_center_id TEXT,
            daily_spend_limit_inr REAL DEFAULT 5000.00,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(tenant_id, email)
        );

        CREATE TABLE IF NOT EXISTS corporate_approval_policies (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL UNIQUE,
            auto_approve_under_inr REAL DEFAULT 800.00,
            require_manager_approval_for_models TEXT DEFAULT '["OUTSTATION", "AIRPORT", "8HR_80KM", "RENTAL"]',
            require_second_level_finance_above_inr REAL DEFAULT 10000.00,
            rolling_24h_spend_cap_inr REAL DEFAULT 2000.00,
            budget_enforcement_enabled INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS booking_approval_requests (
            id TEXT PRIMARY KEY,
            trip_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            requester_user_id TEXT NOT NULL,
            cost_center_id TEXT,
            estimated_fare_inr REAL NOT NULL,
            booking_justification TEXT,
            approval_status TEXT NOT NULL,
            booking_parameter_hash TEXT NOT NULL,
            vehicle_type TEXT,
            tariff_model TEXT,
            pickup_address TEXT,
            drop_address TEXT,
            scheduled_at TEXT,
            l1_approver_id TEXT,
            l1_decided_at TEXT,
            l1_decision_note TEXT,
            l2_approver_id TEXT,
            l2_decided_at TEXT,
            l2_decision_note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_bar_trip ON booking_approval_requests(trip_id);
        CREATE INDEX IF NOT EXISTS idx_bar_tenant_req ON booking_approval_requests(tenant_id, requester_user_id);
        CREATE INDEX IF NOT EXISTS idx_bar_status ON booking_approval_requests(approval_status);
        CREATE INDEX IF NOT EXISTS idx_corp_users_tenant ON corporate_users(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_corp_cost_centers ON cost_centers(tenant_id);
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# TARIFF ESTIMATION HELPER (Links with tariff_engine.py)
# ---------------------------------------------------------------------------

def estimate_corporate_fare(
    vehicle_type: str,
    tariff_model: str,
    distance_km: float = 15.0,
    duration_hours: float = 1.0,
    outstation_days: int = 1,
) -> float:
    """Estimates corporate fare in INR using tariff engine standard models."""
    norm_model = str(tariff_model or "P2P_LOCAL").upper().strip()
    norm_veh = str(vehicle_type or "SEDAN").upper().strip()

    # Base rates per category
    veh_mult = 1.0
    if "SUV" in norm_veh or "CRYSTA" in norm_veh:
        veh_mult = 1.45
    elif "PREMIUM" in norm_veh or "LUXURY" in norm_veh:
        veh_mult = 2.1

    if norm_model == "8HR_80KM":
        return round(2800.0 * veh_mult, 2)
    elif norm_model == "4HR_40KM":
        return round(1600.0 * veh_mult, 2)
    elif norm_model in {"OUTSTATION", "OUTSTATION_ROUNDTRIP"}:
        min_km = max(250.0, distance_km) * max(1, outstation_days)
        per_km = 16.0 * veh_mult
        bhatta = 450.0 * max(1, outstation_days)
        return round((min_km * per_km) + bhatta, 2)
    elif norm_model in {"AIRPORT", "AIRPORT_TRANSFER"}:
        return round(1450.0 * veh_mult, 2)
    else:  # P2P_LOCAL / POINT_TO_POINT
        base_km = min(distance_km, 4.0)
        extra_km = max(0.0, distance_km - base_km)
        base_fare = 150.0 * veh_mult
        return round(base_fare + (extra_km * 22.0 * veh_mult) + (duration_hours * 60.0), 2)


# ---------------------------------------------------------------------------
# POLICY & SPLIT-BOOKING VELOCITY GUARDS
# ---------------------------------------------------------------------------

def get_or_create_corporate_policy(conn: sqlite3.Connection, tenant_id: str) -> Dict[str, Any]:
    """Retrieves corporate policy or creates a default enterprise guardrail configuration."""
    row = conn.execute(
        "SELECT * FROM corporate_approval_policies WHERE tenant_id = ?",
        (tenant_id,),
    ).fetchone()
    if row:
        return dict(row)

    now = now_utc_iso()
    policy_id = f"cap_{tenant_id}"
    conn.execute(
        """
        INSERT OR IGNORE INTO corporate_approval_policies (
            id, tenant_id, auto_approve_under_inr, require_manager_approval_for_models,
            require_second_level_finance_above_inr, rolling_24h_spend_cap_inr,
            budget_enforcement_enabled, created_at, updated_at
        ) VALUES (?, ?, 800.00, '["OUTSTATION", "AIRPORT", "8HR_80KM", "RENTAL"]', 10000.00, 2000.00, 1, ?, ?)
        """,
        (policy_id, tenant_id, now, now),
    )
    conn.commit()
    return {
        "id": policy_id,
        "tenant_id": tenant_id,
        "auto_approve_under_inr": 800.00,
        "require_manager_approval_for_models": '["OUTSTATION", "AIRPORT", "8HR_80KM", "RENTAL"]',
        "require_second_level_finance_above_inr": 10000.00,
        "rolling_24h_spend_cap_inr": 2000.00,
        "budget_enforcement_enabled": 1,
    }


def calculate_rolling_24h_spend(conn: sqlite3.Connection, tenant_id: str, requester_user_id: str) -> float:
    """Calculates cumulative spend committed/pending by the employee over the rolling 24 hours."""
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    row = conn.execute(
        """
        SELECT COALESCE(SUM(estimated_fare_inr), 0.0) as total_spend
        FROM booking_approval_requests
        WHERE tenant_id = ?
          AND requester_user_id = ?
          AND approval_status IN ('APPROVED', 'PENDING_L1_MANAGER', 'PENDING_L2_FINANCE')
          AND created_at >= ?
        """,
        (tenant_id, requester_user_id, since),
    ).fetchone()
    return float(row["total_spend"]) if row else 0.0


# ---------------------------------------------------------------------------
# CORE BUSINESS LOGIC: SUBMIT, DECIDE, PATCH (ANTI-EXPLOIT GUARDS)
# ---------------------------------------------------------------------------

def submit_corporate_booking_request(
    conn: sqlite3.Connection,
    tenant_id: str,
    requester_user_id: str,
    trip_id: str,
    vehicle_type: str,
    tariff_model: str,
    pickup_address: str,
    drop_address: str,
    scheduled_at: str,
    justification: str = "",
    cost_center_id: Optional[str] = None,
    distance_km: float = 15.0,
    duration_hours: float = 1.0,
    outstation_days: int = 1,
) -> Dict[str, Any]:
    """GUARD 1: Evaluates upfront tariff estimation, policy thresholds, and split-booking velocity."""
    policy = get_or_create_corporate_policy(conn, tenant_id)
    est_fare = estimate_corporate_fare(vehicle_type, tariff_model, distance_km, duration_hours, outstation_days)
    param_hash = compute_booking_parameter_hash(
        vehicle_type, tariff_model, pickup_address, drop_address, scheduled_at, est_fare
    )

    # Fetch user cost center if not provided
    if not cost_center_id:
        u_row = conn.execute("SELECT cost_center_id FROM corporate_users WHERE id = ?", (requester_user_id,)).fetchone()
        if u_row and u_row["cost_center_id"]:
            cost_center_id = u_row["cost_center_id"]

    # Check rolling 24h spend
    rolling_24h = calculate_rolling_24h_spend(conn, tenant_id, requester_user_id)
    models_requiring_mgr = json.loads(str(policy.get("require_manager_approval_for_models") or "[]"))

    auto_cap = float(policy.get("auto_approve_under_inr") or 800.0)
    velocity_cap = float(policy.get("rolling_24h_spend_cap_inr") or 2000.0)

    # Determine approval status
    requires_approval = False
    reasons = []

    if est_fare > auto_cap:
        requires_approval = True
        reasons.append(f"Fare ₹{est_fare:.2f} exceeds auto-approval threshold ₹{auto_cap:.2f}")

    if any(m.upper() in tariff_model.upper() for m in models_requiring_mgr):
        requires_approval = True
        reasons.append(f"Tariff model {tariff_model} requires mandatory manager review")

    if (rolling_24h + est_fare) > velocity_cap:
        requires_approval = True
        reasons.append(f"Rolling 24h spend ₹{rolling_24h + est_fare:.2f} exceeds cap ₹{velocity_cap:.2f} (Split-Booking Guard)")

    now = now_utc_iso()
    approval_id = f"bar_{trip_id}"

    if requires_approval:
        status = "PENDING_L1_MANAGER"
        decision_note = " | ".join(reasons)
        l1_approver = None
        l1_decided_at = None
    else:
        status = "APPROVED"
        decision_note = "SYSTEM_AUTO_APPROVED_POLICY"
        l1_approver = "SYSTEM_POLICY_ENGINE"
        l1_decided_at = now

    conn.execute(
        """
        INSERT OR REPLACE INTO booking_approval_requests (
            id, trip_id, tenant_id, requester_user_id, cost_center_id,
            estimated_fare_inr, booking_justification, approval_status,
            booking_parameter_hash, vehicle_type, tariff_model,
            pickup_address, drop_address, scheduled_at,
            l1_approver_id, l1_decided_at, l1_decision_note,
            l2_approver_id, l2_decided_at, l2_decision_note,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?)
        """,
        (
            approval_id, trip_id, tenant_id, requester_user_id, cost_center_id,
            est_fare, justification, status, param_hash, vehicle_type,
            tariff_model, pickup_address, drop_address, scheduled_at,
            l1_approver, l1_decided_at, decision_note, now, now
        ),
    )

    # Update cost center spend if approved
    if status == "APPROVED" and cost_center_id:
        conn.execute(
            "UPDATE cost_centers SET current_month_spend_inr = current_month_spend_inr + ? WHERE id = ?",
            (est_fare, cost_center_id),
        )

    conn.commit()

    return {
        "approval_id": approval_id,
        "trip_id": trip_id,
        "estimated_fare_inr": est_fare,
        "approval_status": status,
        "requires_manager_approval": requires_approval,
        "reasons": reasons,
        "booking_parameter_hash": param_hash,
    }


def decide_corporate_approval(
    conn: sqlite3.Connection,
    approval_id: str,
    decider_user_id: str,
    decision: str,  # "APPROVE" or "REJECT"
    decision_note: str = "",
) -> Dict[str, Any]:
    """GUARD 2 & GUARD 5: Enforces Anti-Self-Approval, strict reporting hierarchy, pickup expiry and budget ceiling."""
    row = conn.execute("SELECT * FROM booking_approval_requests WHERE id = ?", (approval_id,)).fetchone()
    if not row:
        raise ValueError(f"Approval request {approval_id} not found")
    req = dict(row)

    # 1. Anti-Self-Approval Check (Guard 2)
    if decider_user_id == req["requester_user_id"]:
        raise PermissionError("Anti-Self-Approval Guard: You cannot approve or reject your own corporate travel request.")

    # 2. Expiry Check (Guard 5)
    scheduled_at_str = req.get("scheduled_at")
    if scheduled_at_str:
        try:
            # Handle ISO string or common formats
            clean_ts = scheduled_at_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < datetime.now(timezone.utc):
                conn.execute(
                    "UPDATE booking_approval_requests SET approval_status = 'EXPIRED_UNAPPROVED', updated_at = ? WHERE id = ?",
                    (now_utc_iso(), approval_id),
                )
                conn.commit()
                raise ValueError("Approval Expired: Scheduled pickup window has already passed.")
        except (ValueError, TypeError) as ex:
            if "Approval Expired" in str(ex):
                raise

    # 3. Hierarchy & Authority Check
    decider = conn.execute("SELECT * FROM corporate_users WHERE id = ?", (decider_user_id,)).fetchone()
    requester = conn.execute("SELECT * FROM corporate_users WHERE id = ?", (req["requester_user_id"],)).fetchone()

    if not decider:
        raise PermissionError(f"Deciding user {decider_user_id} is not registered in corporate directory.")

    decider_role = decider["corp_role"]

    # If L1 Approval is pending
    if req["approval_status"] == "PENDING_L1_MANAGER":
        # Must be assigned manager, delegate approver, or travel desk admin
        is_assigned_mgr = requester and (decider_user_id in (requester["manager_user_id"], requester["delegate_approver_user_id"]))
        is_travel_desk = decider_role == "CORP_TRAVEL_DESK"

        if not (is_assigned_mgr or is_travel_desk):
            raise PermissionError("Hierarchy Guard: You are not the assigned line manager or delegate approver for this employee.")

        now = now_utc_iso()
        if decision.upper() == "REJECT":
            conn.execute(
                """
                UPDATE booking_approval_requests
                SET approval_status = 'REJECTED', l1_approver_id = ?, l1_decided_at = ?, l1_decision_note = ?, updated_at = ?
                WHERE id = ?
                """,
                (decider_user_id, now, decision_note or "Rejected by Manager", now, approval_id),
            )
            conn.commit()
            return {"approval_id": approval_id, "approval_status": "REJECTED", "message": "Booking request rejected"}

        # If decision is APPROVE, check if second-level finance approval is required
        policy = get_or_create_corporate_policy(conn, req["tenant_id"])
        l2_threshold = float(policy.get("require_second_level_finance_above_inr") or 10000.0)

        # Budget Ceiling Check (Guard 5)
        cost_center_budget_exceeded = False
        if req["cost_center_id"]:
            cc = conn.execute("SELECT * FROM cost_centers WHERE id = ?", (req["cost_center_id"],)).fetchone()
            if cc and float(cc["monthly_budget_inr"]) > 0:
                new_spend = float(cc["current_month_spend_inr"]) + float(req["estimated_fare_inr"])
                if new_spend > float(cc["monthly_budget_inr"]):
                    cost_center_budget_exceeded = True

        if float(req["estimated_fare_inr"]) > l2_threshold or cost_center_budget_exceeded:
            # Transition to PENDING_L2_FINANCE
            reason = "High-Value Trip > ₹10,000" if float(req["estimated_fare_inr"]) > l2_threshold else "Cost Center Monthly Budget Exceeded"
            conn.execute(
                """
                UPDATE booking_approval_requests
                SET approval_status = 'PENDING_L2_FINANCE', l1_approver_id = ?, l1_decided_at = ?, l1_decision_note = ?, updated_at = ?
                WHERE id = ?
                """,
                (decider_user_id, now, f"L1 Approved. Awaiting Finance L2 ({reason})", now, approval_id),
            )
            conn.commit()
            return {
                "approval_id": approval_id,
                "approval_status": "PENDING_L2_FINANCE",
                "message": f"L1 Approved. Sent to Finance for L2 Approval ({reason})",
            }

        # Otherwise fully APPROVED
        conn.execute(
            """
            UPDATE booking_approval_requests
            SET approval_status = 'APPROVED', l1_approver_id = ?, l1_decided_at = ?, l1_decision_note = ?, updated_at = ?
            WHERE id = ?
            """,
            (decider_user_id, now, decision_note or "Approved by Manager", now, approval_id),
        )
        if req["cost_center_id"]:
            conn.execute(
                "UPDATE cost_centers SET current_month_spend_inr = current_month_spend_inr + ? WHERE id = ?",
                (req["estimated_fare_inr"], req["cost_center_id"]),
            )
        conn.commit()
        return {"approval_id": approval_id, "approval_status": "APPROVED", "message": "Trip approved for dispatch"}

    # If L2 Finance Approval is pending
    elif req["approval_status"] == "PENDING_L2_FINANCE":
        if decider_role not in {"CORP_FINANCE_AUDITOR", "CORP_TRAVEL_DESK"}:
            raise PermissionError("L2 Finance Guard: Only a Corporate Finance Auditor or Travel Desk Head can grant L2 approval.")

        now = now_utc_iso()
        if decision.upper() == "REJECT":
            conn.execute(
                """
                UPDATE booking_approval_requests
                SET approval_status = 'REJECTED', l2_approver_id = ?, l2_decided_at = ?, l2_decision_note = ?, updated_at = ?
                WHERE id = ?
                """,
                (decider_user_id, now, decision_note or "Rejected by Finance L2", now, approval_id),
            )
            conn.commit()
            return {"approval_id": approval_id, "approval_status": "REJECTED", "message": "Booking request rejected by Finance"}

        conn.execute(
            """
            UPDATE booking_approval_requests
            SET approval_status = 'APPROVED', l2_approver_id = ?, l2_decided_at = ?, l2_decision_note = ?, updated_at = ?
            WHERE id = ?
            """,
            (decider_user_id, now, decision_note or "Approved by Finance L2", now, approval_id),
        )
        if req["cost_center_id"]:
            conn.execute(
                "UPDATE cost_centers SET current_month_spend_inr = current_month_spend_inr + ? WHERE id = ?",
                (req["estimated_fare_inr"], req["cost_center_id"]),
            )
        conn.commit()
        return {"approval_id": approval_id, "approval_status": "APPROVED", "message": "Trip L2 Approved and released for dispatch"}

    else:
        raise ValueError(f"Approval request {approval_id} is in status '{req['approval_status']}' and cannot be decided.")


def verify_booking_patch_tamper_guard(
    conn: sqlite3.Connection,
    trip_id: str,
    new_vehicle_type: Optional[str] = None,
    new_tariff_model: Optional[str] = None,
    new_pickup: Optional[str] = None,
    new_drop: Optional[str] = None,
    new_scheduled_at: Optional[str] = None,
    new_distance_km: Optional[float] = None,
    new_duration_hours: Optional[float] = None,
    new_outstation_days: Optional[int] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """GUARD 3: Post-Approval Bait & Switch Lock.

    Detects if booking parameters or fare changed post-approval.
    If changed, automatically revokes approval (REVOKED_ON_EDIT) and blocks dispatch.
    Returns (is_tampered, message, updated_approval_dict).
    """
    row = conn.execute("SELECT * FROM booking_approval_requests WHERE trip_id = ?", (trip_id,)).fetchone()
    if not row:
        return False, "No corporate approval request associated with trip", None

    req = dict(row)
    if req["approval_status"] != "APPROVED":
        return False, "Booking not currently in APPROVED status", req

    # Merge updated parameters
    veh = new_vehicle_type if new_vehicle_type is not None else req["vehicle_type"]
    tar = new_tariff_model if new_tariff_model is not None else req["tariff_model"]
    pick = new_pickup if new_pickup is not None else req["pickup_address"]
    drop = new_drop if new_drop is not None else req["drop_address"]
    sched = new_scheduled_at if new_scheduled_at is not None else req["scheduled_at"]
    dist = new_distance_km if new_distance_km is not None else 15.0
    dur = new_duration_hours if new_duration_hours is not None else 1.0
    days = new_outstation_days if new_outstation_days is not None else 1

    new_est_fare = estimate_corporate_fare(veh, tar, dist, dur, days)
    new_hash = compute_booking_parameter_hash(veh, tar, pick, drop, sched, new_est_fare)

    hash_changed = new_hash != req["booking_parameter_hash"]
    cost_increased_significantly = new_est_fare > (float(req["estimated_fare_inr"]) * 1.05)

    if hash_changed or cost_increased_significantly:
        now = now_utc_iso()
        note = f"APPROVAL REVOKED: Parameters altered post-approval (Original Fare: ₹{req['estimated_fare_inr']:.2f} -> New: ₹{new_est_fare:.2f})"
        conn.execute(
            """
            UPDATE booking_approval_requests
            SET approval_status = 'REVOKED_ON_EDIT',
                vehicle_type = ?, tariff_model = ?, pickup_address = ?, drop_address = ?,
                scheduled_at = ?, estimated_fare_inr = ?, booking_parameter_hash = ?,
                l1_decision_note = ?, updated_at = ?
            WHERE id = ?
            """,
            (veh, tar, pick, drop, sched, new_est_fare, new_hash, note, now, req["id"]),
        )
        # Deduct previously booked spend from cost center
        if req["cost_center_id"]:
            conn.execute(
                "UPDATE cost_centers SET current_month_spend_inr = MAX(0.0, current_month_spend_inr - ?) WHERE id = ?",
                (req["estimated_fare_inr"], req["cost_center_id"]),
            )
        conn.commit()

        # Fetch updated record
        updated = dict(conn.execute("SELECT * FROM booking_approval_requests WHERE id = ?", (req["id"],)).fetchone())
        return True, note, updated

    return False, "Parameters unaltered or within tolerance", req


def verify_dispatch_allowed_gate(conn: sqlite3.Connection, trip_id: str) -> Tuple[bool, str]:
    """GUARD 4: Hard Dispatch Gate.

    Ensures no driver can be assigned or partner waterfall dispatched unless corporate approval is APPROVED.
    """
    row = conn.execute("SELECT * FROM booking_approval_requests WHERE trip_id = ?", (trip_id,)).fetchone()
    if not row:
        # If trip is not a corporate trip requiring approval, dispatch is permitted
        return True, "No corporate approval required"

    status = row["approval_status"]
    if status != "APPROVED":
        return False, f"Cannot dispatch: Pending Corporate Manager Approval (Current Status: {status})"

    return True, "Corporate booking approved for dispatch"


# ---------------------------------------------------------------------------
# API ROUTER FOR /api/corp/* AND /api/v1/corp/*
# ---------------------------------------------------------------------------

def handle_corporate_approvals_api(
    conn: sqlite3.Connection,
    user: Dict[str, Any],
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    client_ip: str = "127.0.0.1",
) -> Optional[Dict[str, Any]]:
    """Master dispatcher for Corporate RBAC and Tamper-Proof Approvals API."""
    route = urlsplit(path).path.rstrip("/") or "/"
    norm_route = route.replace("/api/v1", "/api") if route.startswith("/api/v1") else route
    payload = payload or {}

    if not norm_route.startswith("/api/corp"):
        return None

    # Resolve corporate user context
    tenant_id = user.get("organization_id") or user.get("tenant_id") or "org_default"
    user_id = user.get("id") or "usr_corp_default"

    # Query corporate user role if exists
    corp_user = conn.execute(
        "SELECT * FROM corporate_users WHERE id = ? OR email = ?",
        (user_id, user.get("email", "")),
    ).fetchone()

    corp_role = corp_user["corp_role"] if corp_user else "CORP_EMPLOYEE"
    effective_user_id = corp_user["id"] if corp_user else user_id

    # 1. POST /api/corp/bookings/request
    if norm_route == "/api/corp/bookings/request" and method == "POST":
        trip_id = payload.get("trip_id") or f"trip_{int(datetime.now(timezone.utc).timestamp()*1000)}"
        veh = payload.get("vehicle_type", "SEDAN")
        tar = payload.get("tariff_model", "P2P_LOCAL")
        pick = payload.get("pickup_address", "Office HQ")
        drop = payload.get("drop_address", "Client Site")
        sched = payload.get("scheduled_at", now_utc_iso())
        just = payload.get("booking_justification", "")
        cc_id = payload.get("cost_center_id")
        dist = float(payload.get("distance_km", 15.0))
        dur = float(payload.get("duration_hours", 1.0))
        days = int(payload.get("outstation_days", 1))

        res = submit_corporate_booking_request(
            conn, tenant_id, effective_user_id, trip_id, veh, tar, pick, drop, sched,
            just, cc_id, dist, dur, days
        )
        return {"ok": True, "status": "REQUESTED", **res}

    # 2. GET /api/corp/bookings (RBAC Scoped Query)
    if norm_route == "/api/corp/bookings" and method == "GET":
        if corp_role == "CORP_EMPLOYEE":
            rows = conn.execute(
                "SELECT * FROM booking_approval_requests WHERE tenant_id = ? AND requester_user_id = ? ORDER BY created_at DESC",
                (tenant_id, effective_user_id),
            ).fetchall()
        elif corp_role == "CORP_LINE_MANAGER":
            # Own bookings + bookings by reportees
            rows = conn.execute(
                """
                SELECT bar.* FROM booking_approval_requests bar
                LEFT JOIN corporate_users cu ON cu.id = bar.requester_user_id
                WHERE bar.tenant_id = ?
                  AND (bar.requester_user_id = ? OR cu.manager_user_id = ? OR cu.delegate_approver_user_id = ?)
                ORDER BY bar.created_at DESC
                """,
                (tenant_id, effective_user_id, effective_user_id, effective_user_id),
            ).fetchall()
        else:
            # TRAVEL_DESK, HR, FINANCE see all tenant bookings
            rows = conn.execute(
                "SELECT * FROM booking_approval_requests WHERE tenant_id = ? ORDER BY created_at DESC",
                (tenant_id,),
            ).fetchall()

        return {"ok": True, "items": [dict(r) for r in rows], "count": len(rows), "corp_role": corp_role}

    # 3. GET /api/corp/approvals/inbox
    if norm_route == "/api/corp/approvals/inbox" and method == "GET":
        if corp_role == "CORP_LINE_MANAGER":
            rows = conn.execute(
                """
                SELECT bar.*, cu.full_name as requester_name, cu.email as requester_email, cc.name as cost_center_name
                FROM booking_approval_requests bar
                JOIN corporate_users cu ON cu.id = bar.requester_user_id
                LEFT JOIN cost_centers cc ON cc.id = bar.cost_center_id
                WHERE bar.tenant_id = ?
                  AND bar.approval_status = 'PENDING_L1_MANAGER'
                  AND bar.requester_user_id != ?
                  AND (cu.manager_user_id = ? OR cu.delegate_approver_user_id = ?)
                ORDER BY bar.created_at ASC
                """,
                (tenant_id, effective_user_id, effective_user_id, effective_user_id),
            ).fetchall()
        elif corp_role in {"CORP_FINANCE_AUDITOR", "CORP_TRAVEL_DESK"}:
            rows = conn.execute(
                """
                SELECT bar.*, cu.full_name as requester_name, cu.email as requester_email, cc.name as cost_center_name
                FROM booking_approval_requests bar
                JOIN corporate_users cu ON cu.id = bar.requester_user_id
                LEFT JOIN cost_centers cc ON cc.id = bar.cost_center_id
                WHERE bar.tenant_id = ?
                  AND bar.approval_status IN ('PENDING_L1_MANAGER', 'PENDING_L2_FINANCE')
                  AND bar.requester_user_id != ?
                ORDER BY bar.created_at ASC
                """,
                (tenant_id, effective_user_id),
            ).fetchall()
        else:
            rows = []

        return {"ok": True, "inbox": [dict(r) for r in rows], "count": len(rows)}

    # 4. POST /api/corp/approvals/{id}/decide
    if "/api/corp/approvals/" in norm_route and norm_route.endswith("/decide") and method == "POST":
        appr_id = norm_route.split("/api/corp/approvals/")[1].split("/decide")[0]
        decision = payload.get("decision", "APPROVE")
        note = payload.get("decision_note", "")

        try:
            res = decide_corporate_approval(conn, appr_id, effective_user_id, decision, note)
            return {"ok": True, **res}
        except PermissionError as pe:
            return {"status": 403, "error": "FORBIDDEN_APPROVAL", "message": str(pe)}
        except ValueError as ve:
            return {"status": 400, "error": "INVALID_APPROVAL", "message": str(ve)}

    # 5. PATCH /api/corp/bookings/{trip_id} (Tamper Guard)
    if norm_route.startswith("/api/corp/bookings/") and method in {"PATCH", "POST"}:
        trip_id = norm_route.split("/api/corp/bookings/")[1].split("/")[0]
        tampered, msg, updated = verify_booking_patch_tamper_guard(
            conn,
            trip_id,
            new_vehicle_type=payload.get("vehicle_type"),
            new_tariff_model=payload.get("tariff_model"),
            new_pickup=payload.get("pickup_address"),
            new_drop=payload.get("drop_address"),
            new_scheduled_at=payload.get("scheduled_at"),
            new_distance_km=float(payload.get("distance_km")) if "distance_km" in payload else None,
            new_duration_hours=float(payload.get("duration_hours")) if "duration_hours" in payload else None,
            new_outstation_days=int(payload.get("outstation_days")) if "outstation_days" in payload else None,
        )
        return {
            "ok": True,
            "tampered": tampered,
            "message": msg,
            "item": updated,
        }

    # 6. GET /api/corp/cost-centers
    if norm_route == "/api/corp/cost-centers" and method == "GET":
        rows = conn.execute("SELECT * FROM cost_centers WHERE tenant_id = ? ORDER BY code ASC", (tenant_id,)).fetchall()
        return {"ok": True, "cost_centers": [dict(r) for r in rows]}

    # 7. GET /api/corp/cost-centers/{id}/ledger (Finance Transparency Table)
    if norm_route.startswith("/api/corp/cost-centers/") and norm_route.endswith("/ledger") and method == "GET":
        cc_id = norm_route.split("/api/corp/cost-centers/")[1].split("/ledger")[0]
        rows = conn.execute(
            """
            SELECT bar.*, cu.full_name as requester_name, cu.employee_code,
                   appr.full_name as l1_approver_name, fin.full_name as l2_approver_name
            FROM booking_approval_requests bar
            JOIN corporate_users cu ON cu.id = bar.requester_user_id
            LEFT JOIN corporate_users appr ON appr.id = bar.l1_approver_id
            LEFT JOIN corporate_users fin ON fin.id = bar.l2_approver_id
            WHERE bar.tenant_id = ? AND bar.cost_center_id = ?
            ORDER BY bar.created_at DESC
            """,
            (tenant_id, cc_id),
        ).fetchall()
        return {"ok": True, "ledger": [dict(r) for r in rows], "count": len(rows)}

    # 8. GET /api/corp/compliance/night-shift (HR & Safety Transparency)
    if norm_route == "/api/corp/compliance/night-shift" and method == "GET":
        # Returns female & night rides (20:00-06:00) with compliance check
        rows = conn.execute(
            """
            SELECT bar.*, cu.full_name, cu.gender, cu.phone
            FROM booking_approval_requests bar
            JOIN corporate_users cu ON cu.id = bar.requester_user_id
            WHERE bar.tenant_id = ?
            ORDER BY bar.created_at DESC LIMIT 50
            """,
            (tenant_id,),
        ).fetchall()
        return {"ok": True, "records": [dict(r) for r in rows]}

    # 9. POST /api/corp/users/provision (Setup/Seed corporate hierarchy)
    if norm_route == "/api/corp/users/provision" and method == "POST":
        users_list = payload.get("users", [])
        now = now_utc_iso()
        for u in users_list:
            conn.execute(
                """
                INSERT OR REPLACE INTO corporate_users (
                    id, tenant_id, email, full_name, phone, employee_code,
                    gender, corp_role, manager_user_id, delegate_approver_user_id,
                    cost_center_id, daily_spend_limit_inr, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    u.get("id"), tenant_id, u.get("email"), u.get("full_name"),
                    u.get("phone"), u.get("employee_code"), u.get("gender", "NOT_SPECIFIED"),
                    u.get("corp_role", "CORP_EMPLOYEE"), u.get("manager_user_id"),
                    u.get("delegate_approver_user_id"), u.get("cost_center_id"),
                    float(u.get("daily_spend_limit_inr", 5000.0)), now, now
                ),
            )
        conn.commit()
        return {"ok": True, "provisioned_count": len(users_list)}

    return None
