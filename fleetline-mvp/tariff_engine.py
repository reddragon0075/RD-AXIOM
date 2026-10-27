"""Axiom Mobility (Fleetline) Tri-Stack Unified Tariff & Dual-Ledger Engine.

Dual-Ledger Resolution (Client Receivable vs. Supplier Payable) in exact integer paise:
1. HR_KM_SLAB (Spot Rental with Auto-Slab Package Optimizer)
2. OUTSTATION_CALENDAR_DAY (Calendar-Day Rules & Driver Bhatta)
3. RADIAL_ZONE_RING (Campus concentric geofenced rings)
4. PER_SEAT_SHARED_POOL (MoveInSync shared employee seat split)
5. MONTHLY_DEDICATED_FIXED_VARIABLE (Dedicated monthly fleet lease)
6. FUEL_INDEXED_BACK_TO_BACK (Dynamic daily fuel tariff index adjustment)
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


def resolve_auto_slab(
    actual_hours: float,
    actual_km: float,
    slabs: List[Dict[str, Any]],
    extra_hr_paise: int,
    extra_km_paise: int,
    client_favorable: bool = True,
    supplier_payable_paise: Optional[int] = None,
    min_gross_margin_threshold_paise: int = 15000,  # ₹150 minimum margin floor
    min_gross_margin_threshold_pct: float = 8.0,    # 8% minimum margin floor
) -> Tuple[Dict[str, Any], int, str, bool]:
    """Auto-Slab Optimizer: Compares Base + Extras against higher packages to find optimal rate.
    
    Includes Margin-Floor Guardrail: Never allows an auto-slab upgrade if
    (Optimized_Client_Receivable - Supplier_Payable) < min_gross_margin_threshold.
    """
    if not slabs:
        # Default fallback 4Hr/40Km
        slabs = [{"hours": 4, "km": 40, "base_paise": 180000}, {"hours": 8, "km": 80, "base_paise": 320000}, {"hours": 12, "km": 120, "base_paise": 450000}]

    sorted_slabs = sorted(slabs, key=lambda s: (s["hours"], s["km"]))
    candidates = []

    for s in sorted_slabs:
        s_hr = s["hours"]
        s_km = s["km"]
        base = s["base_paise"]

        extra_hr = max(0.0, actual_hours - s_hr)
        extra_km = max(0.0, actual_km - s_km)

        cost = base + math.ceil(extra_hr) * extra_hr_paise + math.ceil(extra_km) * extra_km_paise
        candidates.append((cost, s, f"Slab {s_hr}H/{s_km}K (Base: {base} + Extras: {cost - base})"))

    standard_base_slab = candidates[0]  # Unoptimized lowest slab (e.g. 4H/40K + extras)

    if client_favorable:
        # Sort candidate packages by client cost ascending
        candidates.sort(key=lambda c: c[0])
        best_cost, best_slab, explanation = candidates[0]
        margin_floor_breached = False

        # Apply Margin-Floor Guardrail if supplier payable is known
        if supplier_payable_paise is not None and best_slab != standard_base_slab[1]:
            projected_margin = best_cost - supplier_payable_paise
            margin_pct = (projected_margin / best_cost * 100.0) if best_cost > 0 else 0.0

            if projected_margin < min_gross_margin_threshold_paise or margin_pct < min_gross_margin_threshold_pct:
                # Upgraded slab breaches margin floor: lock to standard unoptimized slab
                margin_floor_breached = True
                best_cost, best_slab, orig_exp = standard_base_slab
                explanation = (
                    f"Auto-slab upgrade blocked by Margin Guardrail (Projected margin INR {projected_margin/100:.2f} [{margin_pct:.1f}%] "
                    f"< threshold INR {min_gross_margin_threshold_paise/100:.2f} [{min_gross_margin_threshold_pct}%]). "
                    f"Locked to standard unoptimized slab {best_slab['hours']}H/{best_slab['km']}K."
                )
    else:
        # Strict matching slab
        best_cost, best_slab, explanation = standard_base_slab
        margin_floor_breached = False

    return best_slab, best_cost, explanation, margin_floor_breached


def calculate_dual_ledger_duty(
    duty_params: Dict[str, Any],
    client_rate_card: Dict[str, Any],
    supplier_rate_card: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Calculates both Client Receivable and Supplier Payable ledgers deterministically in integer paise."""
    mode = duty_params.get("billing_mode", "HR_KM_SLAB")
    matrix = duty_params.get("garage_matrix", "P2P_STRICT")

    raw_km = float(duty_params.get("distance_km", 0.0))
    raw_hrs = float(duty_params.get("duration_hours", 0.0))

    # Apply Garage-to-Garage buffer if configured
    if matrix == "G2G_FIXED_BUFFER":
        buf_km = float(client_rate_card.get("buffer_km", 10.0))
        buf_min = float(client_rate_card.get("buffer_minutes", 30.0))
        billable_km = raw_km + (buf_km * 2)  # Two-way depot buffer
        billable_hrs = raw_hrs + ((buf_min * 2) / 60.0)
    elif matrix == "G2G_ACTUAL":
        billable_km = float(duty_params.get("depot_return_km", raw_km * 1.15))
        billable_hrs = float(duty_params.get("depot_return_hours", raw_hrs + 1.0))
    else:  # P2P_STRICT
        billable_km = raw_km
        billable_hrs = raw_hrs

    tolls_paise = int(duty_params.get("toll_parking_paise", 0))

    # =========================================================================
    # 1. PRELIMINARY SUPPLIER PAYABLE ESTIMATE (FOR MARGIN-FLOOR GUARDRAIL)
    # =========================================================================
    c_bhatta = int(client_rate_card.get("driver_bhatta_paise", 40000)) if duty_params.get("is_night_or_outstation") else 0
    c_extra_km_paise = int(client_rate_card.get("extra_km_paise", 1800))
    c_extra_hr_paise = int(client_rate_card.get("extra_hr_paise", 15000))

    s_card = supplier_rate_card or {}
    s_extra_km_paise = int(s_card.get("extra_km_paise", round(c_extra_km_paise * 0.80)))
    s_extra_hr_paise = int(s_card.get("extra_hr_paise", round(c_extra_hr_paise * 0.80)))
    s_bhatta = int(s_card.get("driver_bhatta_paise", round(c_bhatta * 0.85)))
    s_base_default = int(s_card.get("base_paise", 140000))
    s_gross_estimate = s_base_default + (math.ceil(max(0.0, billable_km - 40.0)) * s_extra_km_paise) + s_bhatta + tolls_paise

    # =========================================================================
    # 2. CLIENT RECEIVABLE LEDGER WITH AUTO-SLAB MARGIN GUARDRAIL
    # =========================================================================
    margin_floor_breached = False
    slab_note = "Standard Slab"

    if mode == "HR_KM_SLAB":
        slabs = client_rate_card.get("slabs", [])
        min_margin_paise = int(client_rate_card.get("min_margin_paise", 15000))
        min_margin_pct = float(client_rate_card.get("min_margin_pct", 8.0))
        _, c_base_and_extras, slab_note, margin_floor_breached = resolve_auto_slab(
            billable_hrs,
            billable_km,
            slabs,
            c_extra_hr_paise,
            c_extra_km_paise,
            client_favorable=True,
            supplier_payable_paise=s_gross_estimate,
            min_gross_margin_threshold_paise=min_margin_paise,
            min_gross_margin_threshold_pct=min_margin_pct,
        )
        c_base = c_base_and_extras
        c_extra_km = 0
        c_extra_hr = 0

    elif mode == "OUTSTATION_CALENDAR_DAY":
        days = max(1, int(duty_params.get("calendar_days", 1)))
        min_km_per_day = float(client_rate_card.get("min_km_per_day", 300.0))
        min_billable_km = days * min_km_per_day
        effective_km = max(billable_km, min_billable_km)
        c_base = int(effective_km * c_extra_km_paise)
        c_extra_km = 0
        c_extra_hr = 0
        c_bhatta = int(client_rate_card.get("driver_bhatta_paise", 50000)) * days

    elif mode == "RADIAL_ZONE_RING":
        # Radial zone pricing (e.g. Ring 1: 0-10km @ 600, Ring 2: 10-25km @ 1200)
        ring_rates = client_rate_card.get("zone_rings", [{"max_km": 10, "paise": 60000}, {"max_km": 25, "paise": 120000}, {"max_km": 50, "paise": 200000}])
        matched = next((r["paise"] for r in ring_rates if billable_km <= r["max_km"]), ring_rates[-1]["paise"])
        c_base = matched
        c_extra_km = 0
        c_extra_hr = 0

    elif mode == "MONTHLY_DEDICATED_FIXED_VARIABLE":
        # Monthly dedicated prorated daily cap
        daily_fixed = int(client_rate_card.get("daily_fixed_paise", 250000))
        km_cap = float(client_rate_card.get("daily_km_cap", 100.0))
        hr_cap = float(client_rate_card.get("daily_hr_cap", 10.0))
        extra_k = max(0.0, billable_km - km_cap)
        extra_h = max(0.0, billable_hrs - hr_cap)
        c_base = daily_fixed
        c_extra_km = math.ceil(extra_k) * c_extra_km_paise
        c_extra_hr = math.ceil(extra_h) * c_extra_hr_paise

    elif mode == "FUEL_INDEXED_BACK_TO_BACK":
        base_dry_paise = int(client_rate_card.get("dry_base_paise", 150000))
        current_fuel_price = float(duty_params.get("current_fuel_price_inr", 102.5))
        base_fuel_price = float(client_rate_card.get("base_fuel_price_inr", 95.0))
        vehicle_mileage_kmpl = float(client_rate_card.get("vehicle_mileage_kmpl", 15.0))
        fuel_diff_inr = max(0.0, current_fuel_price - base_fuel_price)
        fuel_surcharge_paise = int((billable_km / vehicle_mileage_kmpl) * (fuel_diff_inr * 100))
        c_base = base_dry_paise + fuel_surcharge_paise
        c_extra_km = 0
        c_extra_hr = 0

    else:  # Standard fallback
        c_base = int(client_rate_card.get("base_paise", 200000))
        c_extra_km = math.ceil(max(0.0, billable_km - 40.0)) * c_extra_km_paise
        c_extra_hr = math.ceil(max(0.0, billable_hrs - 4.0)) * c_extra_hr_paise

    c_gross = c_base + c_extra_km + c_extra_hr + c_bhatta + tolls_paise
    gst_rate = float(client_rate_card.get("gst_rate_pct", 5.0))
    c_tax = round(c_gross * (gst_rate / 100.0))
    c_net = c_gross + c_tax

    # =========================================================================
    # 2. SUPPLIER PAYABLE LEDGER (SUB-VENDOR OR DCO)
    # =========================================================================
    s_card = supplier_rate_card or {}
    s_extra_km_paise = int(s_card.get("extra_km_paise", round(c_extra_km_paise * 0.80)))
    s_extra_hr_paise = int(s_card.get("extra_hr_paise", round(c_extra_hr_paise * 0.80)))
    s_base = int(s_card.get("base_paise", round(c_base * 0.78)))
    s_bhatta = int(s_card.get("driver_bhatta_paise", round(c_bhatta * 0.85)))
    penalty_deduction = int(duty_params.get("supplier_penalty_paise", 0))

    s_gross = s_base + (math.ceil(max(0.0, billable_km - 40.0)) * s_extra_km_paise) + s_bhatta + tolls_paise
    s_net = max(0, s_gross - penalty_deduction)

    # Unit economics & Maker-Checker flag
    gross_margin_paise = c_gross - s_gross
    is_negative_margin = gross_margin_paise < 0

    return {
        "billing_mode": mode,
        "garage_matrix": matrix,
        "billable_km": round(billable_km, 2),
        "billable_hours": round(billable_hrs, 2),
        "client_receivable": {
            "base_paise": c_base,
            "extra_km_paise": c_extra_km,
            "extra_hr_paise": c_extra_hr,
            "driver_bhatta_paise": c_bhatta,
            "tolls_parking_paise": tolls_paise,
            "gross_receivable_paise": c_gross,
            "gst_tax_paise": c_tax,
            "net_receivable_paise": c_net,
        },
        "supplier_payable": {
            "base_paise": s_base,
            "driver_bhatta_paise": s_bhatta,
            "tolls_parking_paise": tolls_paise,
            "penalty_deduction_paise": penalty_deduction,
            "gross_payable_paise": s_gross,
            "net_payable_paise": s_net,
        },
        "gross_margin_paise": gross_margin_paise,
        "gross_margin_percentage": round((gross_margin_paise / c_gross) * 100.0, 2) if c_gross > 0 else 0.0,
        "is_negative_margin": is_negative_margin,
        "auto_slab_margin_floor_breached": margin_floor_breached,
        "slab_explanation": slab_note,
        "maker_checker_audit_hold": is_negative_margin or margin_floor_breached,
    }
