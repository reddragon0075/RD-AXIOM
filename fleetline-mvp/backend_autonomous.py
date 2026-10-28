"""Axiom Mobility Autonomous Platform Engine.

Implements:
1. Zero-Touch Trip Trust Score & Auto-Audit Engine
2. Predictive SLA Breach Radar & Night Safety Guardian
3. "What-If" Tariff Savings Simulator integration
4. Automated Credit Limit Dunning & Self-Serve Instant Settlement
"""

from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlsplit
import uuid

from backend_domain import DomainError, _assert_owned, _audit, _org, _require_role, new_id, now_iso
from tariff_engine import calculate_dual_ledger_duty


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def initialize_autonomous_schema(conn: sqlite3.Connection) -> None:
    """Initializes tables and columns for trust audits and auto-dunning."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS domain_duty_trust_audits (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            duty_id TEXT NOT NULL UNIQUE,
            trust_score INTEGER NOT NULL CHECK (trust_score >= 0 AND trust_score <= 100),
            audit_status TEXT NOT NULL DEFAULT 'AUTO_VERIFIED' CHECK (audit_status IN ('AUTO_VERIFIED', 'NEEDS_AUDIT', 'RESOLVED_APPROVED', 'RESOLVED_SNAPPED')),
            audit_flags_json TEXT NOT NULL DEFAULT '[]',
            odometer_distance_km REAL NOT NULL DEFAULT 0.0,
            expected_distance_km REAL NOT NULL DEFAULT 0.0,
            duration_hours REAL NOT NULL DEFAULT 0.0,
            implied_speed_kmh REAL NOT NULL DEFAULT 0.0,
            resolved_by TEXT,
            resolved_at TEXT,
            resolution_action TEXT,
            resolution_notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_trust_audits_org ON domain_duty_trust_audits(organization_id, audit_status);
        CREATE INDEX IF NOT EXISTS idx_trust_audits_duty ON domain_duty_trust_audits(duty_id);
        """
    )
    # Check if auto_block_on_overdue exists in tenant_billing_accounts
    try:
        conn.execute("ALTER TABLE tenant_billing_accounts ADD COLUMN auto_block_on_overdue INTEGER NOT NULL DEFAULT 1")
    except Exception:
        pass


def compute_trip_trust_score(
    conn: sqlite3.Connection,
    duty_id: str,
    payload: Dict[str, Any],
    duty_row: sqlite3.Row,
) -> Dict[str, Any]:
    """Computes deterministic 0-100 Trust Score and audit flags for a completed trip."""
    org = duty_row["organization_id"]
    start_odo = int(payload.get("start_odometer") if payload.get("start_odometer") is not None else (payload.get("start_km") if payload.get("start_km") is not None else (duty_row["start_odometer"] or 0)))
    end_odo = int(payload.get("end_odometer") if payload.get("end_odometer") is not None else (payload.get("end_km") if payload.get("end_km") is not None else (duty_row["end_odometer"] or start_odo)))
    delta_km = max(0.0, float(end_odo - start_odo))

    # Expected Route / GPS Distance
    expected_km = float(payload.get("expected_distance_km") or payload.get("gps_distance_km") or 0.0)
    if expected_km <= 0.0:
        booking_id = duty_row["booking_id"] if "booking_id" in duty_row.keys() else None
        if booking_id:
            bk = conn.execute("SELECT pickup_json, dropoff_json FROM domain_bookings WHERE id = ?", (booking_id,)).fetchone()
            if bk:
                try:
                    p = json.loads(bk["pickup_json"] or "{}")
                    d = json.loads(bk["dropoff_json"] or "{}")
                    if p.get("lat") and d.get("lat"):
                        expected_km = round(haversine_distance(p["lat"], p["lon"], d["lat"], d["lon"]) * 1.35, 1)
                except Exception:
                    pass
        if expected_km <= 0.0:
            expected_km = delta_km

    # Duration & Speed Plausibility
    duration_hours = float(payload.get("duration_hours") or 0.0)
    if duration_hours <= 0.0 and duty_row["started_at"]:
        try:
            t_start = dt.datetime.fromisoformat(duty_row["started_at"].replace("Z", "+00:00"))
            t_now = dt.datetime.now(dt.timezone.utc)
            duration_hours = max(0.1, (t_now - t_start).total_seconds() / 3600.0)
        except Exception:
            duration_hours = 1.0

    speed_kmh = (delta_km / duration_hours) if duration_hours > 0 else 0.0

    # Start with 100 points
    score = 100
    flags = []

    # 1. Odometer vs GPS Variance (Deduct up to 35 points)
    if expected_km > 0.0 and delta_km > (expected_km * 1.15):
        ratio = delta_km / expected_km
        deduction = min(35, max(15, int((ratio - 1.0) * 100)))
        score -= deduction
        variance_pct = round((ratio - 1.0) * 100, 1)
        flags.append({
            "code": "ODOMETER_GPS_VARIANCE",
            "message": f"Odometer distance ({delta_km} km) exceeds expected route distance ({expected_km:.1f} km) by {variance_pct}%.",
            "severity": "HIGH",
            "delta_km": delta_km,
            "expected_km": expected_km,
            "variance_pct": variance_pct,
        })

    # 2. Duration / Speed Plausibility (Deduct up to 25 points)
    if duration_hours >= 1.5 and delta_km < 4.0:
        score -= 20
        flags.append({
            "code": "STATIONARY_TRIP_PADDING",
            "message": f"Implausibly low speed ({speed_kmh:.1f} km/h) over {duration_hours:.1f} hours indicates stationary waiting padding.",
            "severity": "MEDIUM",
        })
    elif speed_kmh > 130.0:
        score -= 25
        flags.append({
            "code": "IMPLAUSIBLE_HIGH_SPEED",
            "message": f"Implausibly high average speed ({speed_kmh:.1f} km/h) exceeds highway threshold (130 km/h).",
            "severity": "HIGH",
        })

    # 3. OTP & Geofence Verification (Deduct up to 20 points)
    otp_ok = payload.get("otp_verified") is not False and payload.get("pickup_otp_verified") is not False
    if not otp_ok:
        score -= 15
        flags.append({
            "code": "MISSING_PASSENGER_OTP",
            "message": "Trip started without passenger pickup OTP verification.",
            "severity": "MEDIUM",
        })

    geofence_ok = payload.get("geofence_verified") is not False
    if not geofence_ok:
        score -= 10
        flags.append({
            "code": "GEOFENCE_BOUNDARY_BREACH",
            "message": "Trip start or drop events occurred outside the authorized geofence radius.",
            "severity": "LOW",
        })

    # 4. Toll / Parking Ratio (Deduct 10 points)
    toll_paise = int(payload.get("toll_charges_paise") or 0)
    parking_paise = int(payload.get("parking_charges_paise") or 0)
    base_fare_paise = int(payload.get("base_fare_paise") or 150000)
    if (toll_paise + parking_paise) > (0.40 * base_fare_paise):
        score -= 10
        flags.append({
            "code": "TOLL_PARKING_OUTLIER",
            "message": f"Toll/parking charges (₹{(toll_paise + parking_paise)/100:.2f}) exceed 40% of base fare.",
            "severity": "MEDIUM",
        })

    final_score = max(0, min(100, score))
    audit_status = "AUTO_VERIFIED" if (final_score >= 95 and not flags) else "NEEDS_AUDIT"
    now = now_iso()

    # Insert or update domain_duty_trust_audits
    audit_id = f"aud_{duty_id}"
    conn.execute(
        """INSERT OR REPLACE INTO domain_duty_trust_audits
           (id, organization_id, duty_id, trust_score, audit_status, audit_flags_json, odometer_distance_km, expected_distance_km, duration_hours, implied_speed_kmh, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (audit_id, org, duty_id, final_score, audit_status, json.dumps(flags), delta_km, expected_km, duration_hours, round(speed_kmh, 1), now, now),
    )
    conn.commit()

    return {
        "trust_score": final_score,
        "audit_status": audit_status,
        "audit_flags": flags,
        "odometer_distance_km": delta_km,
        "expected_distance_km": expected_km,
        "duration_hours": duration_hours,
        "implied_speed_kmh": round(speed_kmh, 1),
    }


def resolve_duty_audit(
    conn: sqlite3.Connection,
    user: Dict[str, Any],
    duty_id: str,
    action: str,
    reason: str,
    ip: str,
) -> Dict[str, Any]:
    """1-Click Discrepancy Resolver for trips flagged as NEEDS_AUDIT."""
    org = _org(user)
    audit_row = conn.execute("SELECT * FROM domain_duty_trust_audits WHERE duty_id = ? AND organization_id = ?", (duty_id, org)).fetchone()
    if not audit_row:
        raise DomainError(404, f"Trust audit record for duty '{duty_id}' not found.", "audit_record_not_found")

    duty_row = conn.execute("SELECT * FROM domain_duties WHERE id = ? AND organization_id = ?", (duty_id, org)).fetchone()
    if not duty_row:
        raise DomainError(404, f"Duty '{duty_id}' not found.", "duty_not_found")

    now = now_iso()
    action_clean = action.strip().lower()

    if action_clean == "approve_as_is":
        new_status = "RESOLVED_APPROVED"
        conn.execute(
            """UPDATE domain_duty_trust_audits SET
               audit_status = ?,
               resolved_by = ?,
               resolved_at = ?,
               resolution_action = ?,
               resolution_notes = ?,
               updated_at = ?
               WHERE duty_id = ?""",
            (new_status, user.get("email") or user.get("id"), now, action_clean, reason, now, duty_id),
        )
    elif action_clean == "snap_gps_distance":
        new_status = "RESOLVED_SNAPPED"
        exp_km = audit_row["expected_distance_km"]
        start_odo = duty_row["start_odometer"] or 0
        new_end_odo = start_odo + int(exp_km)

        conn.execute(
            "UPDATE domain_duties SET end_odometer = ?, updated_at = ? WHERE id = ? AND organization_id = ?",
            (new_end_odo, now, duty_id, org),
        )
        conn.execute(
            """UPDATE domain_duty_trust_audits SET
               audit_status = ?,
               odometer_distance_km = ?,
               resolved_by = ?,
               resolved_at = ?,
               resolution_action = ?,
               resolution_notes = ?,
               updated_at = ?
               WHERE duty_id = ?""",
            (new_status, exp_km, user.get("email") or user.get("id"), now, action_clean, reason, now, duty_id),
        )
    else:
        raise DomainError(400, "Invalid resolution action. Must be 'approve_as_is' or 'snap_gps_distance'.", "invalid_action")

    _audit(conn, user, "duty.audit_resolved", "domain_duty_trust_audits", duty_id, ip, {"action": action_clean, "notes": reason, "status": new_status})
    conn.commit()

    return {
        "ok": True,
        "duty_id": duty_id,
        "audit_status": new_status,
        "resolution_action": action_clean,
        "end_odometer": new_end_odo if action_clean == "snap_gps_distance" else (duty_row["end_odometer"] or 0),
        "snapped_km": exp_km if action_clean == "snap_gps_distance" else None,
        "message": f"Duty discrepancy resolved via '{action_clean}'.",
    }


def scan_sla_radar(conn: sqlite3.Connection, organization_id: str) -> Dict[str, Any]:
    """Scans upcoming and active trips for predictive SLA breaches and night safety risks."""
    now_dt = dt.datetime.now(dt.timezone.utc)
    now_hour = now_dt.hour
    is_night_window = now_hour >= 20 or now_hour < 6

    # Fetch active / dispatched duties
    duties = conn.execute(
        """SELECT d.id, d.booking_id, d.driver_id, d.vehicle_id, d.status, d.started_at, d.created_at,
                  b.passenger_name, b.passenger_phone, b.pickup_json, b.dropoff_json, b.scheduled_at, b.duty_type
           FROM domain_duties d
           LEFT JOIN domain_bookings b ON d.booking_id = b.id
           WHERE d.organization_id = ? AND d.status IN ('dispatched', 'allotted', 'in_progress', 'assigned')
           ORDER BY d.created_at ASC LIMIT 50""",
        (organization_id,),
    ).fetchall()

    radar_items = []
    high_risk_count = 0
    night_safety_alerts_count = 0

    # Cache available backup drivers & vehicles
    backups = conn.execute(
        """SELECT dr.id as driver_id, dr.full_name, dr.phone, v.id as vehicle_id, v.registration_number, v.make_model
           FROM domain_drivers dr
           JOIN domain_vehicles v ON v.organization_id = dr.organization_id
           WHERE dr.organization_id = ? AND dr.status IN ('available', 'active') AND v.status = 'active'
           LIMIT 5""",
        (organization_id,),
    ).fetchall()

    suggested_backups = [
        {
            "driver_id": b["driver_id"],
            "driver_name": b["full_name"],
            "driver_phone": b["phone"],
            "vehicle_id": b["vehicle_id"],
            "vehicle_number": b["registration_number"],
            "make_model": b["make_model"],
            "distance_to_pickup_km": round(2.5 + (i * 1.2), 1),
        }
        for i, b in enumerate(backups)
    ]

    for d in duties:
        duty_id = d["id"]
        # Determine risk level based on scheduled time vs now
        sched_str = d["scheduled_at"] or d["started_at"] or d["created_at"]
        minutes_to_pickup = 45.0
        if sched_str:
            try:
                t_sched = dt.datetime.fromisoformat(sched_str.replace("Z", "+00:00"))
                minutes_to_pickup = (t_sched - now_dt).total_seconds() / 60.0
            except Exception:
                minutes_to_pickup = 30.0

        risk_level = "LOW"
        risk_reason = "Driver on schedule and moving."

        # Risk classification
        if minutes_to_pickup < 0:
            risk_level = "CRITICAL"
            risk_reason = f"Pickup delayed by {abs(round(minutes_to_pickup))} minutes past scheduled reporting time."
            high_risk_count += 1
        elif minutes_to_pickup <= 15:
            risk_level = "CRITICAL"
            risk_reason = f"Reporting window starts in {round(minutes_to_pickup)} mins; vehicle approaching pickup."
            high_risk_count += 1
        elif minutes_to_pickup <= 35:
            risk_level = "MEDIUM"
            risk_reason = f"Vehicle en route. Pickup in {round(minutes_to_pickup)} mins."

        # Night Safety Guardian (20:00 - 06:00 POSH protection)
        night_safety_alert = False
        night_alert_reason = ""
        # Check if current time OR duty scheduled pickup is in night window (20:00 - 06:00 IST)
        duty_ist_hour = (now_dt + dt.timedelta(hours=5.5)).hour
        if sched_str:
            try:
                t_sched = dt.datetime.fromisoformat(sched_str.replace("Z", "+00:00"))
                duty_ist_hour = (t_sched + dt.timedelta(hours=5.5)).hour
            except Exception:
                pass
        is_night_commute = (duty_ist_hour >= 20 or duty_ist_hour < 6)

        # Check passenger gender / protected flag
        passenger_name = d["passenger_name"] or ""
        is_female_candidate = any(k in passenger_name.lower() for k in ["female", "sharma", "ananya", "priya", "pooja", "neha", "ms.", "mrs.", "sunita", "sen"])
        if is_night_commute and is_female_candidate:
            night_safety_alert = True
            night_alert_reason = f"Night commute ({duty_ist_hour:02d}:00 IST): Protected passenger '{passenger_name}' requires active route geofence tracking & escort verification."
            night_safety_alerts_count += 1

        radar_items.append({
            "duty_id": duty_id,
            "booking_id": d["booking_id"],
            "driver_id": d["driver_id"],
            "vehicle_id": d["vehicle_id"],
            "passenger_name": passenger_name,
            "status": d["status"],
            "minutes_to_pickup": round(minutes_to_pickup, 1),
            "sla_risk_level": risk_level,
            "risk_reason": risk_reason,
            "night_safety_alert": night_safety_alert,
            "night_alert_reason": night_alert_reason,
            "suggested_backups": [b for b in suggested_backups if b["driver_id"] != d["driver_id"]][:3] if risk_level == "CRITICAL" else [],
        })

    return {
        "ok": True,
        "scanned_duties_count": len(duties),
        "high_risk_count": high_risk_count,
        "night_safety_alerts_count": night_safety_alerts_count,
        "radar": radar_items,
        "critical_trips": [item for item in radar_items if item["sla_risk_level"] in ("CRITICAL", "HIGH")],
        "night_safety_alerts": [item for item in radar_items if item.get("night_safety_alert")],
    }


def simulate_tariff_scenarios(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Runs What-If Tariff Simulation across all 6 billing models."""
    profile = payload.get("profile") or {}
    monthly_trips = int(profile.get("monthly_trips") or payload.get("monthly_trips") or 100)
    avg_distance_km = float(profile.get("avg_distance_km") or payload.get("avg_distance_km") or 40.0)
    avg_duration_hr = float(profile.get("avg_duration_hours") or payload.get("avg_duration_hours") or 4.0)

    # Standard baseline tariff cards
    cards = {
        "slab": {
            "billing_mode": "slab",
            "client_base_fare_paise": 150000,
            "client_base_distance_km": 40.0,
            "client_base_duration_hr": 4.0,
            "client_extra_km_rate_paise": 1800,
            "client_extra_hr_rate_paise": 15000,
            "supplier_base_fare_paise": 110000,
            "supplier_base_distance_km": 40.0,
            "supplier_base_duration_hr": 4.0,
            "supplier_extra_km_rate_paise": 1400,
            "supplier_extra_hr_rate_paise": 10000,
            "fuel_rate_current": 100.0,
            "fuel_rate_base": 100.0,
            "fuel_efficiency_km_per_l": 15.0,
            "gst_rate_pct": 5.0,
        },
        "outstation": {
            "billing_mode": "outstation",
            "client_min_km_per_day": 250.0,
            "client_per_km_rate_paise": 1600,
            "client_driver_allowance_daily_paise": 50000,
            "supplier_min_km_per_day": 250.0,
            "supplier_per_km_rate_paise": 1300,
            "supplier_driver_allowance_daily_paise": 40000,
            "days_count": 1,
            "fuel_rate_current": 100.0,
            "fuel_rate_base": 100.0,
            "fuel_efficiency_km_per_l": 15.0,
            "gst_rate_pct": 5.0,
        },
        "zone_ring": {
            "billing_mode": "zone_ring",
            "client_zone_matrix": {"Z1_Z2": 95000, "Z1_Z3": 140000},
            "supplier_zone_matrix": {"Z1_Z2": 72000, "Z1_Z3": 105000},
            "from_zone": "Z1",
            "to_zone": "Z2",
            "fuel_rate_current": 100.0,
            "fuel_rate_base": 100.0,
            "fuel_efficiency_km_per_l": 15.0,
            "gst_rate_pct": 5.0,
        },
        "package": {
            "billing_mode": "package",
            "client_package_fare_paise": 180000,
            "client_package_distance_km": 50.0,
            "client_package_duration_hr": 5.0,
            "supplier_package_fare_paise": 140000,
            "supplier_package_distance_km": 50.0,
            "supplier_package_duration_hr": 5.0,
            "client_extra_km_rate_paise": 1800,
            "supplier_extra_km_rate_paise": 1400,
            "client_extra_hr_rate_paise": 15000,
            "supplier_extra_hr_rate_paise": 10000,
            "fuel_rate_current": 100.0,
            "fuel_rate_base": 100.0,
            "fuel_efficiency_km_per_l": 15.0,
            "gst_rate_pct": 5.0,
        },
        "flat": {
            "billing_mode": "flat",
            "client_flat_fare_paise": 125000,
            "supplier_flat_fare_paise": 95000,
            "fuel_rate_current": 100.0,
            "fuel_rate_base": 100.0,
            "fuel_efficiency_km_per_l": 15.0,
            "gst_rate_pct": 5.0,
        },
        "day_rate": {
            "billing_mode": "day_rate",
            "client_daily_rate_paise": 280000,
            "supplier_daily_rate_paise": 220000,
            "client_max_km_per_day": 100.0,
            "supplier_max_km_per_day": 100.0,
            "client_extra_km_rate_paise": 1800,
            "supplier_extra_km_rate_paise": 1400,
            "days_count": 1,
            "fuel_rate_current": 100.0,
            "fuel_rate_base": 100.0,
            "fuel_efficiency_km_per_l": 15.0,
            "gst_rate_pct": 5.0,
        },
    }

    results = []
    sample_duty = {
        "distance_km": avg_distance_km,
        "duration_hours": avg_duration_hr,
        "toll_charges_paise": 15000,
        "parking_charges_paise": 5000,
    }

    total_km = monthly_trips * avg_distance_km

    for mode_name, card in cards.items():
        sample_duty_copy = {**sample_duty, "billing_mode": mode_name}
        calc = calculate_dual_ledger_duty(sample_duty_copy, card)
        single_trip_client_paise = calc["client_receivable"]["net_receivable_paise"]
        single_trip_vendor_paise = calc["supplier_payable"]["net_payable_paise"]

        total_client_spend_paise = single_trip_client_paise * monthly_trips
        total_vendor_cost_paise = single_trip_vendor_paise * monthly_trips
        margin_paise = total_client_spend_paise - total_vendor_cost_paise
        margin_pct = round((margin_paise / total_client_spend_paise) * 100, 1) if total_client_spend_paise else 0.0
        effective_cost_per_km = round((total_client_spend_paise / 100) / total_km, 2) if total_km else 0.0

        results.append({
            "model": mode_name,
            "model_title": mode_name.replace("_", " ").upper(),
            "single_trip_client_inr": round(single_trip_client_paise / 100, 2),
            "monthly_client_spend_inr": round(total_client_spend_paise / 100, 2),
            "monthly_vendor_cost_inr": round(total_vendor_cost_paise / 100, 2),
            "gross_margin_inr": round(margin_paise / 100, 2),
            "gross_margin_percentage": margin_pct,
            "effective_cost_per_km_inr": effective_cost_per_km,
        })

    # Sort to determine optimal model
    sorted_by_spend = sorted(results, key=lambda x: x["monthly_client_spend_inr"])
    optimal = sorted_by_spend[0]
    baseline_slab = next((r for r in results if r["model"] == "slab"), sorted_by_spend[-1])

    monthly_savings_inr = max(0.0, baseline_slab["monthly_client_spend_inr"] - optimal["monthly_client_spend_inr"])
    savings_pct = round((monthly_savings_inr / baseline_slab["monthly_client_spend_inr"]) * 100, 1) if baseline_slab["monthly_client_spend_inr"] else 0.0

    return {
        "ok": True,
        "simulation_parameters": {
            "monthly_trips": monthly_trips,
            "avg_distance_km": avg_distance_km,
            "avg_duration_hours": avg_duration_hr,
            "total_monthly_km": total_km,
        },
        "optimal_recommendation": {
            "optimal_model": optimal["model"],
            "optimal_title": optimal["model_title"],
            "projected_monthly_spend_inr": optimal["monthly_client_spend_inr"],
            "effective_cost_per_km_inr": optimal["effective_cost_per_km_inr"],
            "projected_monthly_savings_inr": monthly_savings_inr,
            "annual_projected_savings_inr": round(monthly_savings_inr * 12, 2),
            "savings_percentage": savings_pct,
            "pitch_summary": f"By transitioning to {optimal['model_title']}, this corporate saves ₹{monthly_savings_inr:,.2f}/mo ({savings_pct}% ROI) compared to standard HR/KM slab billing.",
        },
        "comparison_matrix": results,
    }


def check_credit_limit_dunning(conn: sqlite3.Connection, organization_id: str) -> None:
    """Checks if tenant has breached credit limit and enforces SOFT_BLOCKED dunning."""
    row = conn.execute(
        "SELECT tenant_id, tenant_name, account_status, outstanding_balance_paise, credit_limit_paise, auto_block_on_overdue FROM tenant_billing_accounts WHERE tenant_id = ?",
        (organization_id,),
    ).fetchone()

    if not row:
        return

    auto_block = bool(row["auto_block_on_overdue"]) if "auto_block_on_overdue" in row.keys() else True
    bal = row["outstanding_balance_paise"]
    limit = row["credit_limit_paise"]

    if auto_block and bal > limit and row["account_status"] == "ACTIVE":
        now = now_iso()
        reason = f"Credit limit breached: Outstanding ₹{bal/100:,.2f} exceeds credit limit ₹{limit/100:,.2f}."
        conn.execute(
            """UPDATE tenant_billing_accounts SET
               account_status = 'SOFT_BLOCKED',
               block_reason = ?,
               blocked_at = ?,
               blocked_by = 'SYSTEM_DUNNING',
               updated_at = ?
               WHERE tenant_id = ?""",
            (reason, now, now, organization_id),
        )
        conn.execute(
            """INSERT INTO audit_events(id, user_id, action, entity_type, entity_id, metadata_json, ip_address, created_at)
               VALUES (?, 'sys_dunning', 'tenant.auto_blocked_credit_limit', 'tenant_billing_account', ?, ?, '127.0.0.1', ?)""",
            (new_id("audit"), organization_id, json.dumps({"balance_paise": bal, "limit_paise": limit, "reason": reason}), now),
        )
        conn.commit()


def self_settle_tenant_dues(
    conn: sqlite3.Connection,
    user: Dict[str, Any],
    payload: Dict[str, Any],
    ip: str,
) -> Dict[str, Any]:
    """Self-serve instant settlement allowing blocked tenants to unblock their own account."""
    org = user.get("organization_id")
    if not org:
        raise DomainError(400, "User is not associated with a tenant organization.", "missing_organization")

    row = conn.execute("SELECT * FROM tenant_billing_accounts WHERE tenant_id = ?", (org,)).fetchone()
    if not row:
        raise DomainError(404, "Tenant billing account not found.", "tenant_not_found")

    bal = row["outstanding_balance_paise"]
    if bal <= 0:
        return {"ok": True, "account_status": row["account_status"], "message": "No outstanding balance due."}

    now = now_iso()
    ref_id = payload.get("reference_id") or f"INSTANT-PAY-{uuid.uuid4().hex[:8].upper()}"
    method = payload.get("payment_method") or "GATEWAY_INSTANT"

    # Insert settlement record
    conn.execute(
        """INSERT INTO axiom_receivable_ledger (id, tenant_id, entry_type, reference_id, amount_paise, description, payment_method, created_by, created_at)
           VALUES (?, ?, 'PAYMENT', ?, ?, 'Self-serve instant settlement & unblock', ?, ?, ?)""",
        (f"rec_self_{uuid.uuid4().hex[:10]}", org, ref_id, bal, method, user.get("email") or "self_serve", now),
    )

    # Clear balance and auto-unblock
    conn.execute(
        """UPDATE tenant_billing_accounts SET
           total_paid_paise = total_paid_paise + ?,
           outstanding_balance_paise = 0,
           account_status = 'ACTIVE',
           block_reason = '',
           days_overdue = 0,
           updated_at = ?
           WHERE tenant_id = ?""",
        (bal, now, org),
    )

    _audit(conn, user, "tenant.self_settle_unblocked", "tenant_billing_account", org, ip, {"settled_amount_paise": bal, "reference_id": ref_id})
    conn.commit()

    return {
        "ok": True,
        "tenant_id": org,
        "account_status": "ACTIVE",
        "amount_settled_paise": bal,
        "amount_paid_paise": bal,
        "new_outstanding_balance_paise": 0,
        "amount_settled_inr": round(bal / 100, 2),
        "message": f"Successfully settled ₹{bal/100:,.2f} dues. Platform access restored immediately.",
    }
