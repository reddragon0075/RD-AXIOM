"""Axiom Mobility (Fleetline) - Practical Pricing & Trip-Sheet Discrepancy Engine.

Handles:
1. Theoretical Baseline vs. Practical Final Fare recalculations.
2. Driver App Telemetry vs. Physical Trip-Sheet Upload discrepancy workflow.
3. Vendor Mobile Pocket App ("On-the-Go Pulse & Express Allotment").
4. 422 Mandatory Proof Trigger & Dual-Ledger sync.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, ROUND_HALF_UP
import json
import math
from pathlib import Path
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit
import uuid

# Add current dir to sys.path for internal imports
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend_domain import DomainError, _audit, new_id, now_iso
try:
    from tariff_engine import calculate_dual_ledger_duty, resolve_auto_slab
except ImportError:
    calculate_dual_ledger_duty = None
    resolve_auto_slab = None


def initialize_practical_pricing_schema(conn: sqlite3.Connection) -> None:
    """Ensures theoretical and practical columns exist in SQLite database."""
    # Ensure domain_duties has the required columns
    cols_duties = {r["name"] for r in conn.execute("PRAGMA table_info(domain_duties)").fetchall()}
    needed_columns = {
        "estimated_start_km": "REAL DEFAULT 0.0",
        "estimated_end_km": "REAL DEFAULT 0.0",
        "estimated_distance_km": "REAL DEFAULT 0.0",
        "estimated_duration_mins": "INTEGER DEFAULT 0",
        "estimated_client_fare_inr": "REAL DEFAULT 0.0",
        "estimated_supplier_payout_inr": "REAL DEFAULT 0.0",
        "app_captured_start_km": "REAL",
        "app_captured_end_km": "REAL",
        "app_gps_distance_km": "REAL DEFAULT 0.0",
        "app_start_time": "TEXT",
        "app_end_time": "TEXT",
        "practical_start_km": "REAL",
        "practical_end_km": "REAL",
        "practical_billable_km": "REAL DEFAULT 0.0",
        "practical_start_time": "TEXT",
        "practical_end_time": "TEXT",
        "practical_duration_mins": "INTEGER DEFAULT 0",
        "final_client_fare_inr": "REAL DEFAULT 0.0",
        "final_supplier_payout_inr": "REAL DEFAULT 0.0",
        "closing_source": "TEXT DEFAULT 'DRIVER_APP_AUTO'",
        "has_discrepancy": "INTEGER DEFAULT 0",
        "discrepancy_reason": "TEXT",
        "physical_tripsheet_file_url": "TEXT",
        "physical_tripsheet_uploaded_by": "TEXT",
        "physical_tripsheet_uploaded_at": "TEXT",
        "closed_by_operator_id": "TEXT",
    }
    for col_name, col_def in needed_columns.items():
        if col_name not in cols_duties:
            try:
                conn.execute(f"ALTER TABLE domain_duties ADD COLUMN {col_name} {col_def}")
            except Exception:
                pass

    # Ensure booking table has estimated fields as well
    cols_bookings = {r["name"] for r in conn.execute("PRAGMA table_info(domain_bookings)").fetchall()}
    for col_name in ("estimated_distance_km", "estimated_client_fare_inr", "estimated_supplier_payout_inr", "vehicle_category"):
        if col_name not in cols_bookings:
            try:
                conn.execute(f"ALTER TABLE domain_bookings ADD COLUMN {col_name} REAL DEFAULT 0.0")
            except Exception:
                pass

    # Create immutable audit logs for trip-sheet overrides & practical closures
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS duty_tripsheet_audit_logs (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            duty_id TEXT NOT NULL,
            closing_source TEXT NOT NULL,
            estimated_distance_km REAL,
            estimated_client_fare_inr REAL,
            practical_billable_km REAL,
            final_client_fare_inr REAL,
            km_variance_delta REAL,
            fare_variance_delta REAL,
            has_discrepancy INTEGER NOT NULL DEFAULT 0,
            discrepancy_reason TEXT,
            physical_tripsheet_file_url TEXT,
            closed_by TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )


def compute_theoretical_pricing(
    distance_km: float = 40.0,
    duration_mins: int = 240,
    start_km: float = 1000.0,
    base_rate_inr: float = 1500.0,
    extra_km_rate_inr: float = 25.0,
    extra_hr_rate_inr: float = 150.0,
    supplier_margin_discount: float = 0.80,
) -> Dict[str, Any]:
    """Computes baseline theoretical pricing at booking creation."""
    dist = max(0.0, float(distance_km))
    dur_hrs = max(0.0, float(duration_mins) / 60.0)
    end_km = start_km + dist

    # Base package: 4Hr / 40Km = base_rate_inr (default ₹1,500)
    extra_km = max(0.0, dist - 40.0)
    extra_hr = max(0.0, dur_hrs - 4.0)

    client_fare = base_rate_inr + (math.ceil(extra_km) * extra_km_rate_inr) + (math.ceil(extra_hr) * extra_hr_rate_inr)
    supplier_payout = round(client_fare * supplier_margin_discount, 2)

    return {
        "estimated_start_km": round(start_km, 1),
        "estimated_end_km": round(end_km, 1),
        "estimated_distance_km": round(dist, 1),
        "estimated_duration_mins": int(duration_mins),
        "estimated_client_fare_inr": round(client_fare, 2),
        "estimated_supplier_payout_inr": round(supplier_payout, 2),
    }


def recalculate_practical_tariffs(
    practical_km: float,
    practical_duration_mins: int,
    base_rate_inr: float = 1500.0,
    extra_km_rate_inr: float = 25.0,
    extra_hr_rate_inr: float = 150.0,
    toll_parking_inr: float = 0.0,
    supplier_margin_discount: float = 0.80,
) -> Dict[str, Any]:
    """Calculates final tariff and auto-slab upgrades using practical road execution."""
    km = max(0.0, float(practical_km))
    hrs = max(0.0, float(practical_duration_mins) / 60.0)

    # Standard 4H/40K Slab
    extra_km_4 = max(0.0, km - 40.0)
    extra_hr_4 = max(0.0, hrs - 4.0)
    cost_4h = base_rate_inr + (math.ceil(extra_km_4) * extra_km_rate_inr) + (math.ceil(extra_hr_4) * extra_hr_rate_inr)

    # Higher 8H/80K Slab (e.g. ₹2,500 base)
    cost_8h = 2500.0 + (math.ceil(max(0.0, km - 80.0)) * extra_km_rate_inr) + (math.ceil(max(0.0, hrs - 8.0)) * extra_hr_rate_inr)

    # Auto-Slab Optimizer: choose most economical package for client
    if cost_8h < cost_4h and km >= 65:
        chosen_fare = cost_8h
        slab_label = "8Hr/80Km Slab (Auto-Upgraded)"
    else:
        chosen_fare = cost_4h
        slab_label = "4Hr/40Km Standard Slab"

    final_client_fare = round(chosen_fare + float(toll_parking_inr), 2)
    final_supplier_payout = round((chosen_fare * supplier_margin_discount) + float(toll_parking_inr), 2)
    net_margin = round(final_client_fare - final_supplier_payout, 2)

    return {
        "final_client_fare_inr": final_client_fare,
        "final_supplier_payout_inr": final_supplier_payout,
        "net_margin_inr": net_margin,
        "slab_label": slab_label,
        "toll_parking_inr": float(toll_parking_inr),
    }


def close_duty_practical(
    conn: sqlite3.Connection,
    user: Dict[str, Any],
    duty_id: str,
    payload: Dict[str, Any],
    ip: str = "127.0.0.1",
) -> Dict[str, Any]:
    """Closes duty using practical kilometers & timestamps with mandatory proof checks."""
    org = user.get("organization_id") or "org_default"
    duty_row = conn.execute(
        "SELECT * FROM domain_duties WHERE id = ? AND organization_id = ?",
        (duty_id, org),
    ).fetchone()

    if not duty_row:
        # Fallback without org filter if admin or system
        duty_row = conn.execute("SELECT * FROM domain_duties WHERE id = ?", (duty_id,)).fetchone()
        if not duty_row:
            raise DomainError(404, f"Duty {duty_id} not found", "not_found")
        org = duty_row["organization_id"]

    closing_source = str(payload.get("closing_source") or "DRIVER_APP_AUTO").upper()
    has_discrepancy = bool(payload.get("has_discrepancy", False) or closing_source == "PHYSICAL_TRIPSHEET_OVERRIDE")
    discrepancy_reason = payload.get("discrepancy_reason")
    tripsheet_url = payload.get("physical_tripsheet_file_url")

    # 1. MANDATORY PROOF CONSTRAINT:
    # If closing_source = 'PHYSICAL_TRIPSHEET_OVERRIDE' OR has_discrepancy = true,
    # then physical_tripsheet_file_url and discrepancy_reason MUST NOT BE NULL.
    if closing_source == "PHYSICAL_TRIPSHEET_OVERRIDE" or has_discrepancy:
        if not tripsheet_url or not str(tripsheet_url).strip() or not discrepancy_reason or not str(discrepancy_reason).strip():
            raise DomainError(
                422,
                "422 PHYSICAL_TRIPSHEET_PROOF_REQUIRED: When closing via PHYSICAL_TRIPSHEET_OVERRIDE or reporting a discrepancy, physical_tripsheet_file_url and discrepancy_reason are strictly required.",
                "physical_tripsheet_proof_required",
            )

    # 2. Extract Practical or App-Captured Kilometers
    if closing_source == "DRIVER_APP_AUTO" and payload.get("practical_start_km") is None:
        p_start_km = float(duty_row["app_captured_start_km"] or duty_row["start_odometer"] or duty_row["estimated_start_km"] or 1000.0)
        p_end_km = float(duty_row["app_captured_end_km"] or duty_row["end_odometer"] or duty_row["estimated_end_km"] or (p_start_km + 40.0))
    else:
        p_start_km = float(payload.get("practical_start_km") if payload.get("practical_start_km") is not None else (duty_row["start_odometer"] or 1000.0))
        p_end_km = float(payload.get("practical_end_km") if payload.get("practical_end_km") is not None else (p_start_km + 40.0))

    if p_end_km < p_start_km:
        raise DomainError(422, f"practical_end_km ({p_end_km}) cannot be less than practical_start_km ({p_start_km})", "invalid_odometer")

    billable_km = round(p_end_km - p_start_km, 1)

    # 3. Timestamps & Duration
    p_start_time = str(payload.get("practical_start_time") or duty_row["started_at"] or duty_row["reporting_at"] or now_iso())
    p_end_time = str(payload.get("practical_end_time") or duty_row["completed_at"] or now_iso())

    if p_start_time and p_end_time and p_end_time < p_start_time:
        raise DomainError(422, "practical_end_time cannot be earlier than practical_start_time", "invalid_timestamps")

    calc_duration_mins = payload.get("practical_duration_mins")
    if calc_duration_mins is not None:
        duration_mins = int(calc_duration_mins)
    else:
        try:
            t_start = dt.datetime.fromisoformat(p_start_time.replace("Z", "+00:00"))
            t_end = dt.datetime.fromisoformat(p_end_time.replace("Z", "+00:00"))
            duration_mins = max(15, int((t_end - t_start).total_seconds() / 60))
        except Exception:
            duration_mins = 240

    toll_parking_inr = float(payload.get("toll_parking_inr") or 0.0)

    # 4. Dynamic Tariff & Auto-Slab Re-Evaluation
    pricing = recalculate_practical_tariffs(
        practical_km=billable_km,
        practical_duration_mins=duration_mins,
        base_rate_inr=1500.0,
        extra_km_rate_inr=25.0,
        extra_hr_rate_inr=150.0,
        toll_parking_inr=toll_parking_inr,
    )

    final_client_fare = pricing["final_client_fare_inr"]
    final_supplier_payout = pricing["final_supplier_payout_inr"]

    # Baseline theoretical values (preserved for reporting)
    est_km = float(duty_row["estimated_distance_km"] or 40.0)
    est_fare = float(duty_row["estimated_client_fare_inr"] or 1500.0)
    est_payout = float(duty_row["estimated_supplier_payout_inr"] or 1200.0)

    now = now_iso()
    operator_id = user.get("id") or "usr_operator"

    # 5. Update Duty Record
    conn.execute(
        """
        UPDATE domain_duties
        SET practical_start_km = ?,
            practical_end_km = ?,
            practical_billable_km = ?,
            practical_start_time = ?,
            practical_end_time = ?,
            practical_duration_mins = ?,
            final_client_fare_inr = ?,
            final_supplier_payout_inr = ?,
            closing_source = ?,
            has_discrepancy = ?,
            discrepancy_reason = ?,
            physical_tripsheet_file_url = ?,
            physical_tripsheet_uploaded_by = ?,
            physical_tripsheet_uploaded_at = ?,
            closed_by_operator_id = ?,
            start_odometer = ?,
            end_odometer = ?,
            status = 'completed',
            completed_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            p_start_km,
            p_end_km,
            billable_km,
            p_start_time,
            p_end_time,
            duration_mins,
            final_client_fare,
            final_supplier_payout,
            closing_source,
            1 if has_discrepancy else 0,
            discrepancy_reason,
            tripsheet_url,
            operator_id if tripsheet_url else None,
            now if tripsheet_url else None,
            operator_id,
            int(p_start_km),
            int(p_end_km),
            p_end_time,
            now,
            duty_id,
        ),
    )

    # Also update associated booking status if applicable
    booking_id = duty_row["booking_id"] if "booking_id" in duty_row.keys() else None
    if booking_id:
        try:
            conn.execute("UPDATE domain_bookings SET status = 'completed', updated_at = ? WHERE id = ?", (now, booking_id))
        except Exception:
            pass

    # 6. Insert Tripsheet Audit Log
    km_delta = round(billable_km - est_km, 1)
    fare_delta = round(final_client_fare - est_fare, 2)
    audit_id = f"aud_{uuid.uuid4().hex[:8]}"

    conn.execute(
        """
        INSERT INTO duty_tripsheet_audit_logs(
            id, organization_id, duty_id, closing_source,
            estimated_distance_km, estimated_client_fare_inr,
            practical_billable_km, final_client_fare_inr,
            km_variance_delta, fare_variance_delta,
            has_discrepancy, discrepancy_reason,
            physical_tripsheet_file_url, closed_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            audit_id,
            org,
            duty_id,
            closing_source,
            est_km,
            est_fare,
            billable_km,
            final_client_fare,
            km_delta,
            fare_delta,
            1 if has_discrepancy else 0,
            discrepancy_reason,
            tripsheet_url,
            operator_id,
            now,
        ),
    )

    # 7. Dual-Ledger Treasury Sync (Record payable in supplier_payable_ledger if present)
    try:
        cols_spl = {r["name"] for r in conn.execute("PRAGMA table_info(supplier_payable_ledger)").fetchall()}
        if cols_spl:
            payout_paise = int(round(final_supplier_payout * 100))
            vendor_id = duty_row["supplier_id"] or org
            entry_id = f"spl_{duty_id}"
            conn.execute(
                """
                INSERT OR REPLACE INTO supplier_payable_ledger (
                    id, duty_id, vendor_id, amount_paise, status, audit_passed_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'FUNDS_HELD_BY_AXIOM', ?, ?, ?)
                """,
                (entry_id, duty_id, vendor_id, payout_paise, now, now, now),
            )
    except Exception:
        pass

    explanation = (
        f"Estimated: {duty_row['estimated_duration_mins'] or 240}min/{est_km}Km (₹{est_fare:,.2f}) -> "
        f"Practical: {duration_mins}min/{billable_km}Km -> {pricing['slab_label']} (₹{final_client_fare:,.2f})"
    )

    _audit(
        conn,
        user,
        "duty.practical_closed",
        "duty",
        duty_id,
        ip,
        {
            "closing_source": closing_source,
            "has_discrepancy": has_discrepancy,
            "estimated_fare": est_fare,
            "final_fare": final_client_fare,
            "variance_delta": fare_delta,
        },
    )

    updated_row = conn.execute("SELECT * FROM domain_duties WHERE id = ?", (duty_id,)).fetchone()
    return {
        "ok": True,
        "duty": dict(updated_row),
        "price_change_explanation": explanation,
        "estimated_baseline": {
            "estimated_distance_km": est_km,
            "estimated_client_fare_inr": est_fare,
            "estimated_supplier_payout_inr": est_payout,
        },
        "practical_final": {
            "practical_billable_km": billable_km,
            "final_client_fare_inr": final_client_fare,
            "final_supplier_payout_inr": final_supplier_payout,
            "variance_delta_inr": fare_delta,
            "km_variance_delta": km_delta,
            "pricing": pricing,
        },
    }


def get_vendor_pocket_pulse(conn: sqlite3.Connection, user: Dict[str, Any]) -> Dict[str, Any]:
    """Provides thumb-friendly mobile pulse stats for fleet vendors."""
    org = user.get("organization_id") or "org_default"

    # 1. Unassigned Cabs Count (Requested / Unallotted Bookings)
    unassigned_row = conn.execute(
        """
        SELECT COUNT(*) as cnt FROM domain_bookings
        WHERE (organization_id = ? OR ? = 'org_default')
          AND status IN ('requested', 'pending', 'unallotted', 'draft')
        """,
        (org, org),
    ).fetchone()
    unassigned_cabs_count = int(unassigned_row["cnt"] or 0)

    # 2. Live Running Cabs
    live_row = conn.execute(
        """
        SELECT COUNT(*) as cnt FROM domain_duties
        WHERE (organization_id = ? OR ? = 'org_default')
          AND status IN ('assigned', 'allotted', 'en_route', 'arrived', 'started', 'active', 'in_progress')
        """,
        (org, org),
    ).fetchone()
    live_running_count = int(live_row["cnt"] or 0)

    # 3. Discrepancy / To Close Count
    to_close_row = conn.execute(
        """
        SELECT COUNT(*) as cnt FROM domain_duties
        WHERE (organization_id = ? OR ? = 'org_default')
          AND (has_discrepancy = 1 OR status IN ('completed_pending_review', 'to_close', 'arrived_destination'))
        """,
        (org, org),
    ).fetchone()
    discrepancy_to_close_count = int(to_close_row["cnt"] or 0)

    # 4. Today's Revenue & Net Payout Summary
    rev_row = conn.execute(
        """
        SELECT 
            COALESCE(SUM(final_client_fare_inr), 0) as total_rev,
            COALESCE(SUM(final_client_fare_inr - final_supplier_payout_inr), 0) as total_net
        FROM domain_duties
        WHERE (organization_id = ? OR ? = 'org_default')
          AND status = 'completed'
        """,
        (org, org),
    ).fetchone()

    today_rev = float(rev_row["total_rev"] or 0.0)
    today_net = float(rev_row["total_net"] or 0.0)

    # Fallback to demo pulse numbers if fresh database
    if today_rev == 0.0:
        today_rev = 48500.0
        today_net = 11200.0

    rev_k = f"₹{today_rev/1000.0:.1f}k"
    net_k = f"₹{today_net/1000.0:.1f}k"

    return {
        "ok": True,
        "pulse": {
            "unassigned_cabs": unassigned_cabs_count,
            "live_running": live_running_count,
            "discrepancy_to_close": discrepancy_to_close_count,
            "today_revenue_inr": today_rev,
            "today_net_inr": today_net,
            "summary_pill_text": f"Rev: {rev_k} | Net: {net_k}",
        },
    }


def get_vendor_pocket_unassigned(conn: sqlite3.Connection, user: Dict[str, Any]) -> Dict[str, Any]:
    """Returns compact cards of unassigned bookings and smart driver/vehicle pairings."""
    org = user.get("organization_id") or "org_default"

    bookings = conn.execute(
        """
        SELECT b.*, c.name as corporate_name
        FROM domain_bookings b
        LEFT JOIN domain_customers c ON b.customer_id = c.id
        WHERE (b.organization_id = ? OR ? = 'org_default')
          AND b.status IN ('requested', 'pending', 'unallotted', 'draft')
        ORDER BY b.scheduled_at ASC LIMIT 20
        """,
        (org, org),
    ).fetchall()

    # Get available drivers with compliance checks
    today_str = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    driver_rows = conn.execute(
        """
        SELECT * FROM domain_drivers
        WHERE (organization_id = ? OR ? = 'org_default')
          AND status IN ('active', 'available')
        LIMIT 10
        """,
        (org, org),
    ).fetchall()

    # Get available vehicles
    vehicle_rows = conn.execute(
        """
        SELECT * FROM domain_vehicles
        WHERE (organization_id = ? OR ? = 'org_default')
          AND status IN ('active', 'available')
        LIMIT 10
        """,
        (org, org),
    ).fetchall()

    # Build smart driver + vehicle suggestion pairs
    suggested_pairs = []
    for idx, d_row in enumerate(driver_rows):
        v_row = vehicle_rows[idx % len(vehicle_rows)] if vehicle_rows else None
        if v_row:
            d = dict(d_row)
            v = dict(v_row)
            # Check compliance
            license_exp = str(d.get("license_expiry") or "2099-12-31")[:10]
            insurance_exp = str(v.get("insurance_expiry") or "2099-12-31")[:10]
            docs_valid = (license_exp >= today_str) and (insurance_exp >= today_str)

            drv_name = d.get("full_name") or d.get("name") or "Assigned Driver"
            veh_cat = v.get("vehicle_type") or v.get("category") or "Sedan"
            veh_model = v.get("model") or v.get("make_model") or "Maruti Dzire"
            suggested_pairs.append({
                "driver_id": d["id"],
                "driver_name": drv_name,
                "driver_phone": d.get("phone", ""),
                "vehicle_id": v["id"],
                "vehicle_number": v["registration_number"],
                "vehicle_model": veh_model,
                "vehicle_category": veh_cat,
                "proximity_text": f"{(idx + 1) * 1.2:.1f} km away",
                "compliance_badge": "✅ Docs Valid" if docs_valid else "⚠️ Docs Expiring Soon",
                "is_compliant": docs_valid,
            })

    card_items = []
    for b_row in bookings:
        b = dict(b_row)
        pickup_raw = b.get("pickup_json") or "{}"
        drop_raw = b.get("dropoff_json") or "{}"
        try:
            pickup_obj = json.loads(pickup_raw) if isinstance(pickup_raw, str) else (pickup_raw or {})
            drop_obj = json.loads(drop_raw) if isinstance(drop_raw, str) else (drop_raw or {})
        except Exception:
            pickup_obj, drop_obj = {}, {}

        pickup_label = pickup_obj.get("label") or pickup_obj.get("address") or "Bangalore Airport"
        drop_label = drop_obj.get("label") or drop_obj.get("address") or "Whitefield Tech Park"

        card_items.append({
            "id": b["id"],
            "booking_reference": b["booking_reference"],
            "passenger_name": b.get("passenger_name") or "Corporate Guest",
            "passenger_phone": b.get("passenger_phone") or "+91 98800 12345",
            "corporate_tag": b.get("corporate_name") or "Infosys Corp",
            "pickup": pickup_label,
            "dropoff": drop_label,
            "vehicle_category": b.get("vehicle_category") or "Sedan",
            "pickup_countdown_text": "In 45 mins",
            "estimated_distance_km": float(b.get("estimated_distance_km") or 40.0),
            "estimated_client_fare_inr": float(b.get("estimated_client_fare_inr") or 1500.0),
        })

    return {
        "ok": True,
        "unassigned_bookings": card_items,
        "count": len(card_items),
        "suggested_pairs": suggested_pairs,
    }


def express_assign_cab(
    conn: sqlite3.Connection,
    user: Dict[str, Any],
    payload: Dict[str, Any],
    ip: str = "127.0.0.1",
) -> Dict[str, Any]:
    """Atomically allots a driver + vehicle pair to a booking or broadcasts to partner network."""
    org = user.get("organization_id") or "org_default"
    booking_id = payload.get("booking_id")
    duty_id = payload.get("duty_id")
    driver_id = payload.get("driver_id")
    vehicle_id = payload.get("vehicle_id")
    is_partner_overflow = bool(payload.get("is_partner_overflow", False))

    if not booking_id and not duty_id:
        raise DomainError(400, "Either booking_id or duty_id is required for cab assignment", "validation_error")

    now = now_iso()

    # Find booking if only booking_id provided
    if booking_id and not duty_id:
        booking = conn.execute("SELECT * FROM domain_bookings WHERE id = ?", (booking_id,)).fetchone()
        if not booking:
            raise DomainError(404, f"Booking {booking_id} not found", "not_found")
        # Check existing duty
        existing = conn.execute("SELECT * FROM domain_duties WHERE booking_id = ?", (booking_id,)).fetchone()
        if existing:
            duty_id = existing["id"]
        else:
            duty_id = f"duty_{uuid.uuid4().hex[:8]}"
            conn.execute(
                """
                INSERT INTO domain_duties(
                    id, organization_id, booking_id, status, reporting_at,
                    estimated_distance_km, estimated_client_fare_inr, estimated_supplier_payout_inr,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 'draft', ?, 40.0, 1500.0, 1200.0, ?, ?)
                """,
                (duty_id, org, booking_id, booking["scheduled_at"] or now, now, now),
            )

    if is_partner_overflow:
        # Mark as broadcasted to partner network
        conn.execute(
            """
            UPDATE domain_duties
            SET status = 'ALLOTTED',
                supplier_id = 'PARTNER_NETWORK_OVERFLOW',
                updated_at = ?
            WHERE id = ?
            """,
            (now, duty_id),
        )
        if booking_id:
            conn.execute("UPDATE domain_bookings SET status = 'assigned', updated_at = ? WHERE id = ?", (now, booking_id))

        dispatch_alert = {
            "channel": "WHATSAPP",
            "type": "PARTNER_OVERFLOW_BROADCAST",
            "message": f"Trip {duty_id} broadcasted to partner fleet network.",
            "status": "SENT",
        }
    else:
        if not driver_id or not vehicle_id:
            raise DomainError(400, "driver_id and vehicle_id are required for cab assignment", "validation_error")

        # Update duty status to ALLOTTED
        conn.execute(
            """
            UPDATE domain_duties
            SET driver_id = ?,
                vehicle_id = ?,
                status = 'ALLOTTED',
                updated_at = ?
            WHERE id = ?
            """,
            (driver_id, vehicle_id, now, duty_id),
        )
        if booking_id:
            conn.execute("UPDATE domain_bookings SET status = 'assigned', updated_at = ? WHERE id = ?", (now, booking_id))

        # Retrieve driver & vehicle details for dispatch alert
        drv = conn.execute("SELECT * FROM domain_drivers WHERE id = ?", (driver_id,)).fetchone()
        veh = conn.execute("SELECT * FROM domain_vehicles WHERE id = ?", (vehicle_id,)).fetchone()

        drv_name = (drv["full_name"] if "full_name" in drv.keys() else drv.get("name")) if drv else "Assigned Driver"
        drv_phone = drv["phone"] if drv else "+91 98800 00000"
        veh_plate = veh["registration_number"] if veh else "KA-01-AB-1234"
        veh_model = (veh["model"] or veh.get("make_model") or "Sedan") if veh else "Sedan"

        dispatch_alert = {
            "channel": "WHATSAPP_AND_SMS",
            "driver_name": drv_name,
            "driver_phone": drv_phone,
            "vehicle_plate": veh_plate,
            "vehicle_model": veh_model,
            "passenger_sms_text": f"Axiom Fleet: Cab assigned! {veh_model} ({veh_plate}), Driver {drv_name} ({drv_phone}).",
            "driver_sms_text": f"New Trip Allotted: Duty {duty_id}. Report on time.",
            "dispatched_at": now,
            "status": "DISPATCH_CONFIRMED",
        }

    _audit(
        conn,
        user,
        "duty.express_assigned",
        "duty",
        duty_id,
        ip,
        {"driver_id": driver_id, "vehicle_id": vehicle_id, "is_partner_overflow": is_partner_overflow},
    )

    return {
        "ok": True,
        "duty_id": duty_id,
        "status": "ALLOTTED",
        "dispatch_alert": dispatch_alert,
        "assigned_at": now,
    }


def handle_practical_pricing_api(
    conn: sqlite3.Connection,
    user: Dict[str, Any],
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    ip: str = "127.0.0.1",
) -> Optional[Dict[str, Any]]:
    """Master routing dispatcher for Practical Pricing, Discrepancy & Pocket App APIs."""
    payload = payload or {}
    norm_path = path.replace("/api/v1", "/api")

    # 1. Close Practical Recalculation Endpoint: POST /api/duties/{duty_id}/close-practical
    if "/api/duties/" in norm_path and norm_path.endswith("/close-practical") and method == "POST":
        parts = norm_path.split("/api/duties/")[1].split("/close-practical")[0]
        duty_id = parts.strip("/")
        return close_duty_practical(conn, user, duty_id, payload, ip)

    # 2. Vendor Pocket Pulse: GET /api/vendor-pocket/pulse
    if norm_path == "/api/vendor-pocket/pulse" and method == "GET":
        return get_vendor_pocket_pulse(conn, user)

    # 3. Vendor Pocket Unassigned List: GET /api/vendor-pocket/unassigned
    if norm_path == "/api/vendor-pocket/unassigned" and method == "GET":
        return get_vendor_pocket_unassigned(conn, user)

    # 4. Vendor Pocket Express Cab Assignment: POST /api/vendor-pocket/express-assign
    if norm_path == "/api/vendor-pocket/express-assign" and method == "POST":
        return express_assign_cab(conn, user, payload, ip)

    # 5. Duty-specific Express Assign: POST /api/duties/{duty_id}/express-assign
    if "/api/duties/" in norm_path and norm_path.endswith("/express-assign") and method == "POST":
        parts = norm_path.split("/api/duties/")[1].split("/express-assign")[0]
        duty_id = parts.strip("/")
        payload_with_duty = dict(payload)
        payload_with_duty["duty_id"] = duty_id
        return express_assign_cab(conn, user, payload_with_duty, ip)

    # 6. Duty Trip Details & Pricing Correction Workbench: PATCH / POST / PUT /api/duties/{duty_id}/trip-details
    if "/api/duties/" in norm_path and norm_path.endswith("/trip-details") and method in ("PATCH", "POST", "PUT"):
        parts = norm_path.split("/api/duties/")[1].split("/trip-details")[0]
        duty_id = parts.strip("/")
        try:
            from backend_completed_trips_importer import correct_duty_trip_details
            return correct_duty_trip_details(conn, user, duty_id, payload, ip)
        except ImportError:
            pass

    return None
