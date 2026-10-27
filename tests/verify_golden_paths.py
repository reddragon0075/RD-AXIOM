#!/usr/bin/env python3
"""Axiom Mobility (Fleetline) Tri-Stack Golden-Path E2E Verification Suite.

Executes and asserts the 4 critical enterprise mobility workflows:
1. Workflow A: RAC Spot Rental + Auto-Slab + Margin Guardrail Dual-Ledger Flow
2. Workflow B: 3-Way Distance Fraud Hold & Maker-Checker Queue Flow
3. Workflow C: Partner SLA Breach, Tier Demotion Hysteresis & Force Majeure Flow
4. Workflow D: ETS Night-Shift Women's Safety (POSH) Lock & Guard OTP Flow
"""

import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import sys

# Ensure parent fleetline-mvp directory is on sys.path
BASE_DIR = Path(__file__).resolve().parent
if BASE_DIR.name == "tests":
    ROOT = BASE_DIR.parent
    if (ROOT / "fleetline-mvp").is_dir():
        sys.path.insert(0, str(ROOT / "fleetline-mvp"))
    sys.path.insert(0, str(ROOT))
else:
    sys.path.insert(0, str(BASE_DIR))

from backend_domain import DomainError
from backend_tristack import (
    compute_haversine_distance,
    handle_tristack,
    initialize_tristack_schema,
)
from safety_compliance import (
    evaluate_safe_reach_escalation,
    validate_night_shift_safety,
    verify_guard_trip_otp,
)
from sla_governance import (
    evaluate_sla_breach,
    evaluate_tier_demotion,
    generate_penalty_debit_note,
)
from tariff_engine import (
    calculate_dual_ledger_duty,
    resolve_auto_slab,
)


def run_golden_paths():
    print("======================================================================")
    print("AXIOM MOBILITY (FLEETLINE) GOLDEN-PATH E2E VERIFICATION SUITE")
    print("======================================================================\n")

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    initialize_tristack_schema(conn)

    admin_user = {"id": "usr_superadmin", "role": "vendor", "organization_id": "org_tenant_169"}

    # -------------------------------------------------------------------------
    # WORKFLOW A: RAC SPOT RENTAL + AUTO-SLAB + MARGIN GUARDRAIL FLOW
    # -------------------------------------------------------------------------
    print(">> WORKFLOW A: RAC Spot Rental + Auto-Slab + Margin Guardrail Flow")
    slabs = [
        {"hours": 4.0, "km": 40, "base_paise": 180000},  # 4H/40K @ ₹1,800
        {"hours": 8.0, "km": 80, "base_paise": 320000},  # 8H/80K @ ₹3,200
        {"hours": 12.0, "km": 120, "base_paise": 480000}, # 12H/120K @ ₹4,800
    ]

    best_slab, opt_cost, explanation, breached = resolve_auto_slab(
        7.5, 78, slabs, extra_hr_paise=25000, extra_km_paise=2500,
        supplier_payable_paise=250000, min_gross_margin_threshold_paise=15000, min_gross_margin_threshold_pct=8.0
    )
    assert best_slab["hours"] == 8.0 and best_slab["km"] == 80
    assert opt_cost == 320000
    assert breached is False
    print(f"  [A1] Auto-Slab upgraded 4H/40K -> 8H/80K: Client cost optimized to INR {opt_cost/100} (Saved INR 425.00)")

    locked_slab, locked_cost, locked_expl, margin_breached = resolve_auto_slab(
        7.5, 78, slabs, extra_hr_paise=25000, extra_km_paise=2500,
        supplier_payable_paise=310000, min_gross_margin_threshold_paise=15000, min_gross_margin_threshold_pct=8.0
    )
    assert margin_breached is True
    assert locked_cost == 375000
    assert "Margin Guardrail" in locked_expl
    print(f"  [A2] Margin-Floor Guardrail triggered: Upgrade blocked, duty locked to INR {locked_cost/100} to protect INR 650 margin")

    client_card = {
        "slabs": slabs,
        "driver_bhatta_paise": 40000,
        "extra_km_paise": 1800,
        "extra_hr_paise": 15000,
        "gst_rate_pct": 5.0,
        "min_margin_paise": 15000,
    }
    supplier_card = {
        "base_paise": 140000,
        "extra_km_paise": 1200,
        "driver_bhatta_paise": 30000,
    }
    duty_params = {
        "billing_mode": "HR_KM_SLAB",
        "garage_matrix": "P2P_STRICT",
        "distance_km": 50.0,
        "duration_hours": 5.0,
        "toll_parking_paise": 15000,
    }
    dl_res = calculate_dual_ledger_duty(duty_params, client_card, supplier_card)
    assert dl_res["gross_margin_paise"] > 0
    margin_inr = dl_res["gross_margin_paise"] / 100
    assert margin_inr == 310.0
    print(f"  [A3] Dual-Ledger calculated: Client REV INR {dl_res['client_receivable']['gross_receivable_paise']/100} | Supplier PAY INR {dl_res['supplier_payable']['gross_payable_paise']/100} | Net Margin INR {margin_inr} ({dl_res['gross_margin_percentage']}%)")
    print("  --> WORKFLOW A PASSED (3/3)\n")

    # -------------------------------------------------------------------------
    # WORKFLOW B: 3-WAY DISTANCE FRAUD HOLD & MAKER-CHECKER FLOW
    # -------------------------------------------------------------------------
    print(">> WORKFLOW B: 3-Way Distance Fraud Hold & Maker-Checker Flow")
    audit_payload = {
        "duty_id": "DUTY_GOLDEN_002",
        "odometer_start": 40000,
        "odometer_end": 40095,
        "raw_gps_crumb_km": 63.0,
        "snapped_route_km": 62.0,
    }
    audit_res = handle_tristack(conn, admin_user, "POST", "/api/tri-stack/audits/distance", audit_payload)
    assert audit_res["distance_audit"]["is_fraud_flagged"] is True
    assert audit_res["distance_audit"]["maker_checker_task_created"] is True
    assert audit_res["distance_audit"]["discrepancy_pct"] > 50.0
    print(f"  [B1] 3-Way Distance Audit flagged fraud: Odo 95km vs Snapped 62km (+{audit_res['distance_audit']['discrepancy_pct']}%)")

    mc_cur = conn.execute("SELECT reason, duty_id, status FROM tristack_maker_checker_queue WHERE duty_id = 'DUTY_GOLDEN_002'")
    mc_row = mc_cur.fetchone()
    assert mc_row is not None
    assert "variance" in mc_row[0].lower()
    assert mc_row[2] == "PENDING_REVIEW"
    print(f"  [B2] Maker-Checker task {mc_row[0]} queued in database for duty {mc_row[1]} with status {mc_row[2]}")
    print("  --> WORKFLOW B PASSED (2/2)\n")

    # -------------------------------------------------------------------------
    # WORKFLOW C: PARTNER SLA BREACH, TIER DEMOTION & HYSTERESIS FLOW
    # -------------------------------------------------------------------------
    print(">> WORKFLOW C: Partner SLA Breach, Tier Demotion & Hysteresis Flow")
    _, demoted_hyst, reason_hyst = evaluate_tier_demotion("TIER_1_PLATINUM", 88.0, 4, completed_duties_14d=15)
    assert demoted_hyst is False
    assert "Hysteresis" in reason_hyst
    print(f"  [C1] Hysteresis Protection: Vendor with 15/20 duties deferred from demotion ({reason_hyst[:70]}...)")

    next_tier, demoted_active, reason_active = evaluate_tier_demotion("TIER_1_PLATINUM", 88.0, 4, completed_duties_14d=35)
    assert demoted_active is True
    assert next_tier == "TIER_2_GOLD"
    print(f"  [C2] SLA Tier Demotion: Vendor demoted from TIER_1_PLATINUM -> {next_tier} ({reason_active})")

    _, demoted_fm, reason_fm = evaluate_tier_demotion("TIER_1_PLATINUM", 82.0, 6, completed_duties_14d=35, force_majeure_active=True)
    assert demoted_fm is False
    assert "Force Majeure" in reason_fm
    print(f"  [C3] Force Majeure Exemption: Extreme weather toggle paused automated tier demotion")
    print("  --> WORKFLOW C PASSED (3/3)\n")

    # -------------------------------------------------------------------------
    # WORKFLOW D: ETS NIGHT-SHIFT WOMEN'S SAFETY (POSH) LOCK FLOW
    # -------------------------------------------------------------------------
    print(">> WORKFLOW D: ETS Night-Shift Women's Safety (POSH) Lock Flow")
    passengers_logout = [
        {"name": "Karthik Raj", "gender": "male"},
        {"name": "Aditi Sharma", "gender": "female"}
    ]
    safe_logout, err_logout = validate_night_shift_safety("LOGOUT", passengers_logout, "2026-10-27T22:30:00Z", guard_assigned=False)
    assert safe_logout is False
    assert "last drop" in err_logout
    print(f"  [D1] POSH Night-Shift Hard-Lock triggered: {err_logout}")

    guard_rec = {"id": "guard_blr_001", "start_otp": "445566", "end_otp": "778899"}
    verified_start, _ = verify_guard_trip_otp(guard_rec, "445566", "START")
    assert verified_start is True
    verified_end, _ = verify_guard_trip_otp(guard_rec, "778899", "END")
    assert verified_end is True
    print(f"  [D2] Security Guard verified: START OTP (445566) & END OTP (778899) cleared")

    now_t = dt.datetime.now(dt.timezone.utc)
    t_2m = (now_t - dt.timedelta(minutes=2)).isoformat()
    t_4m = (now_t - dt.timedelta(minutes=4)).isoformat()
    t_6m = (now_t - dt.timedelta(minutes=6)).isoformat()

    esc_2m = evaluate_safe_reach_escalation(t_2m, safe_reach_confirmed=False)
    assert esc_2m["tier"] == "TIER_1_PUSH_SMS" and not esc_2m["p0_escalation_required"]

    esc_4m = evaluate_safe_reach_escalation(t_4m, safe_reach_confirmed=False)
    assert esc_4m["tier"] == "TIER_2_IVR_CALL" and not esc_4m["p0_escalation_required"]

    esc_6m = evaluate_safe_reach_escalation(t_6m, safe_reach_confirmed=False)
    assert esc_6m["tier"] == "TIER_3_P0_ESCALATION_SUPERVISOR" and esc_6m["p0_escalation_required"]

    esc_emergency = evaluate_safe_reach_escalation(t_2m, safe_reach_confirmed=False, ivr_response="2")
    assert esc_emergency["p0_escalation_required"] and esc_emergency["status"] == "EMERGENCY_TRIGGERED_BY_EMPLOYEE"
    print(f"  [D3] Safe-Reach Escalation verified: 2m -> PUSH_SMS, 4m -> IVR_CALL, 6m -> P0_EMERGENCY_ALARM")
    print("  --> WORKFLOW D PASSED (3/3)\n")

    print("======================================================================")
    print("ALL 4 GOLDEN-PATH WORKFLOWS VERIFIED & FULLY COMPLIANT (11/11)")
    print("======================================================================")


if __name__ == "__main__":
    run_golden_paths()
