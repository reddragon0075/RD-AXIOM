"""Axiom Fleetline Comprehensive Fare Engine for Indian Car Rental Operations.

Deterministic integer-paise precision engine handling:
1. Local Packages (e.g., 4h/40km, 8h/80km, 12h/120km) with grace period and
   Auto Slab Optimization (UPGRADE_ONLY / AUTO_OPTIMAL / NONE).
2. Outstation Fares with daily minimum KM guarantee, calendar vs. 24-hr day modes,
   driver daily batta, and night driving allowances.
3. Airport Transfers & Fixed Point-to-Point routes with free waiting & excess charges.
4. Odometer normalization: Point-to-Point (P2P) vs. Garage-to-Garage (G2G) with shed KM caps.
5. Dynamic Fuel Surcharge calculation (KM * fuel_delta / mileage benchmark).
6. Dual-Ledger Settlement:
   - Receivable (Customer Invoice) billed on requested vehicle group unless upgrade charged.
   - Payable (Supplier / DCO / Driver Payout) based on allotted vehicle group.
   - Net Duty P&L (Gross Profit & Margin %).
7. State-aware GST (CGST/SGST intra-state vs. IGST inter-state) with pure-agent
   reimbursement exclusion (toll/parking non-taxable vs. taxable pass-through).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import math
from typing import Any, Optional


FARE_ENGINE_VERSION = "2026.10.1"

MAX_CALCULATION_PAISE = 9_000_000_000_000_000  # 90,000 Crore INR ceiling
MAX_DISTANCE_KM = 1_000_000
MAX_DURATION_MINUTES = 1_000_000


class FareError(ValueError):
    """Base error for fare calculation and rate card resolution."""

    def __init__(self, message: str, code: str = "fare_calculation_error"):
        super().__init__(message)
        self.message = message
        self.code = code


def _to_int(val: Any, name: str, default: int = 0, minimum: int = 0, maximum: int = MAX_CALCULATION_PAISE) -> int:
    if val is None or val == "":
        return default
    if isinstance(val, bool):
        raise FareError(f"{name} cannot be a boolean", "invalid_type")
    if isinstance(val, float):
        if not val.is_integer():
            raise FareError(f"{name} must be an integer, got float {val}", "invalid_type")
        val = int(val)
    try:
        num = int(val)
    except (TypeError, ValueError, OverflowError) as exc:
        raise FareError(f"{name} must be a valid integer", "invalid_type") from exc
    if num < minimum:
        raise FareError(f"{name} cannot be less than {minimum}", "out_of_bounds")
    if num > maximum:
        raise FareError(f"{name} exceeds maximum limit of {maximum}", "out_of_bounds")
    return num


def _to_float(val: Any, name: str, default: float = 0.0, minimum: float = 0.0, maximum: float = float(MAX_DISTANCE_KM)) -> float:
    if val is None or val == "":
        return default
    if isinstance(val, bool):
        raise FareError(f"{name} cannot be a boolean", "invalid_type")
    try:
        num = float(val)
    except (TypeError, ValueError, OverflowError) as exc:
        raise FareError(f"{name} must be a valid number", "invalid_type") from exc
    if math.isnan(num) or math.isinf(num):
        raise FareError(f"{name} must be finite", "invalid_value")
    if num < minimum:
        raise FareError(f"{name} cannot be less than {minimum}", "out_of_bounds")
    if num > maximum:
        raise FareError(f"{name} exceeds maximum limit of {maximum}", "out_of_bounds")
    return num


def round_div(numerator: int, denominator: int) -> int:
    """Half-up integer division."""
    if denominator <= 0:
        raise FareError("Denominator must be positive", "invalid_denominator")
    if numerator < 0:
        raise FareError("Numerator cannot be negative", "invalid_numerator")
    return (numerator + denominator // 2) // denominator


def calc_percentage_bps(amount_paise: int, bps: int) -> int:
    """Calculate basis points percentage with half-up rounding (100 bps = 1%)."""
    if amount_paise < 0 or bps < 0:
        raise FareError("Amount and basis points must be non-negative", "invalid_input")
    whole, remainder = divmod(amount_paise, 10_000)
    return whole * bps + (remainder * bps + 5_000) // 10_000


def _normalise_mode(mode_str: Any) -> str:
    m = str(mode_str or "local").strip().lower()
    if m in {"local", "hourly", "city"}:
        return "local"
    if m in {"outstation", "intercity", "out_station"}:
        return "outstation"
    if m in {"airport", "transfer", "airport_transfer", "flat"}:
        return "airport"
    if m in {"monthly", "long_term"}:
        return "monthly"
    return m


@dataclass(frozen=True)
class TelemetryData:
    billing_mode: str = "P2P"  # "P2P" or "G2G"
    reporting_km: float = 0.0
    releasing_km: float = 0.0
    garage_out_km: float = 0.0
    garage_in_km: float = 0.0
    duration_minutes: int = 0
    waiting_minutes: int = 0
    night_hours_count: int = 0  # detected night duty blocks
    calendar_days: int = 1
    toll_paise: int = 0
    parking_paise: int = 0
    state_tax_paise: int = 0
    extra_expense_paise: int = 0
    reimbursements_taxable: bool = False

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> TelemetryData:
        billing_mode = str(data.get("billing_mode") or "P2P").strip().upper()
        if billing_mode not in {"P2P", "G2G"}:
            billing_mode = "P2P"

        rep_km = _to_float(data.get("reporting_km") or data.get("start_km") or data.get("start_odometer"), "reporting_km")
        rel_km = _to_float(data.get("releasing_km") or data.get("end_km") or data.get("end_odometer"), "releasing_km")
        if rel_km < rep_km:
            raise FareError(f"Releasing odometer ({rel_km}) cannot be less than reporting ({rep_km})", "odometer_reversal")

        gar_out = _to_float(data.get("garage_out_km") or rep_km, "garage_out_km")
        gar_in = _to_float(data.get("garage_in_km") or rel_km, "garage_in_km")
        if gar_in < gar_out:
            raise FareError(f"Garage in ({gar_in}) cannot be less than garage out ({gar_out})", "garage_odometer_reversal")

        # Duration
        dur = _to_int(data.get("duration_minutes") or data.get("total_minutes"), "duration_minutes", maximum=MAX_DURATION_MINUTES)
        wait_m = _to_int(data.get("waiting_minutes"), "waiting_minutes", maximum=MAX_DURATION_MINUTES)

        # Days
        days = _to_int(data.get("calendar_days") or data.get("total_days") or 1, "calendar_days", default=1, minimum=1, maximum=365)
        night_blocks = _to_int(data.get("night_hours_count") or data.get("night_allowance_count") or data.get("night_count") or 0, "night_hours_count", default=0, maximum=100)

        tolls = _to_int(data.get("toll_paise") or data.get("tolls"), "toll_paise")
        parking = _to_int(data.get("parking_paise") or data.get("parking"), "parking_paise")
        state_tax = _to_int(data.get("state_tax_paise") or data.get("permit_paise"), "state_tax_paise")
        other_exp = _to_int(data.get("extra_expense_paise") or data.get("misc_expense_paise"), "extra_expense_paise")
        reim_tax = bool(data.get("reimbursements_taxable", False))

        return cls(
            billing_mode=billing_mode,
            reporting_km=rep_km,
            releasing_km=rel_km,
            garage_out_km=gar_out,
            garage_in_km=gar_in,
            duration_minutes=dur,
            waiting_minutes=wait_m,
            night_hours_count=night_blocks,
            calendar_days=days,
            toll_paise=tolls,
            parking_paise=parking,
            state_tax_paise=state_tax,
            extra_expense_paise=other_exp,
            reimbursements_taxable=reim_tax,
        )

    @property
    def p2p_km(self) -> float:
        return max(0.0, self.releasing_km - self.reporting_km)

    @property
    def garage_km(self) -> float:
        return max(0.0, self.garage_in_km - self.garage_out_km)

    @property
    def shed_km(self) -> float:
        front_shed = max(0.0, self.reporting_km - self.garage_out_km)
        back_shed = max(0.0, self.garage_in_km - self.releasing_km)
        return front_shed + back_shed

    def effective_km(self, max_shed_km: Optional[float] = None) -> float:
        if self.billing_mode == "G2G":
            if max_shed_km is not None and max_shed_km >= 0:
                allowed_shed = min(self.shed_km, float(max_shed_km))
                return self.p2p_km + allowed_shed
            return self.garage_km
        return self.p2p_km


def calculate_optimal_local_fare(
    telemetry: TelemetryData,
    booked_rule: dict[str, Any],
    candidate_slabs: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Calculate local fare evaluating auto-slab optimization.

    If booked_rule specifies slab_switch_mode == 'UPGRADE_ONLY' or 'AUTO_OPTIMAL',
    evaluates candidate slabs from the rate card. If a higher slab results in lower total
    or satisfies policy, auto-switches and notes the savings.
    """
    effective_km = telemetry.effective_km(booked_rule.get("max_shed_km"))
    duration_min = telemetry.duration_minutes
    switch_mode = str(booked_rule.get("slab_switch_mode") or "NONE").strip().upper()

    slabs_to_evaluate = [booked_rule]
    if candidate_slabs and switch_mode in {"UPGRADE_ONLY", "AUTO_OPTIMAL"}:
        slabs_to_evaluate = candidate_slabs

    evaluated_candidates = []
    for slab in slabs_to_evaluate:
        pkg_min = _to_int(slab.get("package_minutes") or 0, "package_minutes")
        inc_km = _to_float(slab.get("included_km") or 0.0, "included_km")
        base_fare = _to_int(slab.get("base_paise") or 0, "base_paise")
        extra_km_rate = _to_int(slab.get("extra_km_paise") or 0, "extra_km_paise")
        extra_hr_rate = _to_int(slab.get("extra_hour_paise") or 0, "extra_hour_paise")
        extra_half_hr_rate = _to_int(slab.get("extra_half_hour_paise") or 0, "extra_half_hour_paise")
        grace_period = _to_int(slab.get("grace_period_minutes") or 0, "grace_period_minutes", maximum=120)

        # Extra KM
        extra_km = max(0.0, effective_km - inc_km)
        extra_km_paise = int(round(extra_km * extra_km_rate))

        # Extra Time
        billable_extra_minutes = 0
        if duration_min > pkg_min:
            overage = duration_min - pkg_min
            if overage > grace_period:
                billable_extra_minutes = overage

        extra_time_paise = 0
        extra_hours_billed = 0
        if billable_extra_minutes > 0:
            if extra_half_hr_rate > 0:
                half_blocks = (billable_extra_minutes + 29) // 30
                extra_time_paise = half_blocks * extra_half_hr_rate
            elif extra_hr_rate > 0:
                extra_hours_billed = (billable_extra_minutes + 59) // 60
                extra_time_paise = extra_hours_billed * extra_hr_rate

        subtotal = base_fare + extra_km_paise + extra_time_paise
        evaluated_candidates.append({
            "rule": slab,
            "slab_name": str(slab.get("package_name") or f"{pkg_min // 60}Hr {int(inc_km)}Km"),
            "package_minutes": pkg_min,
            "included_km": inc_km,
            "base_fare_paise": base_fare,
            "extra_km": extra_km,
            "extra_km_paise": extra_km_paise,
            "billable_extra_minutes": billable_extra_minutes,
            "extra_time_paise": extra_time_paise,
            "transport_subtotal_paise": subtotal,
        })

    # Find the booked candidate baseline
    booked_cand = evaluated_candidates[0]
    for c in evaluated_candidates:
        if str(c["rule"].get("id")) == str(booked_rule.get("id")):
            booked_cand = c
            break

    winning_cand = booked_cand
    was_switched = False
    savings_paise = 0

    if switch_mode in {"UPGRADE_ONLY", "AUTO_OPTIMAL"} and len(evaluated_candidates) > 1:
        # Sort candidates by package capacity: (package_minutes, included_km)
        candidates_sorted = sorted(
            evaluated_candidates,
            key=lambda c: (c["package_minutes"], c["included_km"])
        )

        if switch_mode == "UPGRADE_ONLY":
            # Only consider slabs greater than or equal to booked package capacity
            eligible = [
                c for c in candidates_sorted
                if c["package_minutes"] >= booked_cand["package_minutes"]
                and c["included_km"] >= booked_cand["included_km"]
            ]
            if eligible:
                cheapest_upgrade = min(eligible, key=lambda c: c["transport_subtotal_paise"])
                if cheapest_upgrade["transport_subtotal_paise"] < booked_cand["transport_subtotal_paise"]:
                    winning_cand = cheapest_upgrade
                    was_switched = True
                    savings_paise = booked_cand["transport_subtotal_paise"] - winning_cand["transport_subtotal_paise"]
        elif switch_mode == "AUTO_OPTIMAL":
            cheapest_any = min(candidates_sorted, key=lambda c: c["transport_subtotal_paise"])
            if cheapest_any["transport_subtotal_paise"] < booked_cand["transport_subtotal_paise"]:
                winning_cand = cheapest_any
                was_switched = True
                savings_paise = booked_cand["transport_subtotal_paise"] - winning_cand["transport_subtotal_paise"]

    return {
        "winning_candidate": winning_cand,
        "booked_candidate": booked_cand,
        "was_switched": was_switched,
        "switch_mode": switch_mode,
        "savings_paise": savings_paise,
        "evaluated_candidates": evaluated_candidates,
    }


def calculate_outstation_fare(
    telemetry: TelemetryData,
    rule: dict[str, Any],
) -> dict[str, Any]:
    """Calculate Outstation duty fare.

    Total Chargeable KM = max(actual_km, calendar_days * min_km_per_day)
    Add Driver Day Batta per day + Driver Night Allowance.
    """
    min_daily_km = _to_float(rule.get("min_km_per_day") or rule.get("daily_min_km") or 250.0, "min_km_per_day")
    rate_per_km = _to_int(rule.get("rate_per_km_paise") or rule.get("extra_km_paise") or 1500, "rate_per_km_paise")
    driver_day_batta = _to_int(rule.get("allowance_paise") or rule.get("driver_day_allowance_paise") or rule.get("driver_batta_paise") or 40000, "driver_day_allowance_paise")
    driver_night_allowance = _to_int(rule.get("night_allowance_paise") or rule.get("driver_night_allowance_paise") or rule.get("night_charge_paise") or 30000, "driver_night_allowance_paise")

    effective_km = telemetry.effective_km(rule.get("max_shed_km"))
    total_days = max(1, telemetry.calendar_days)
    guaranteed_km = total_days * min_daily_km
    chargeable_km = max(effective_km, guaranteed_km)

    km_charge_paise = int(round(chargeable_km * rate_per_km))
    total_day_batta_paise = total_days * driver_day_batta
    total_night_allowance_paise = telemetry.night_hours_count * driver_night_allowance

    return {
        "effective_km": effective_km,
        "calendar_days": total_days,
        "min_daily_km": min_daily_km,
        "guaranteed_km": guaranteed_km,
        "chargeable_km": chargeable_km,
        "rate_per_km_paise": rate_per_km,
        "km_charge_paise": km_charge_paise,
        "driver_day_batta_per_day_paise": driver_day_batta,
        "total_day_batta_paise": total_day_batta_paise,
        "driver_night_allowance_rate_paise": driver_night_allowance,
        "night_blocks_count": telemetry.night_hours_count,
        "total_night_allowance_paise": total_night_allowance_paise,
        "transport_subtotal_paise": km_charge_paise + total_day_batta_paise + total_night_allowance_paise,
    }


def calculate_airport_fare(
    telemetry: TelemetryData,
    rule: dict[str, Any],
) -> dict[str, Any]:
    """Calculate Airport transfer / fixed zone flat fare with waiting."""
    flat_paise = _to_int(rule.get("flat_rate_paise") or rule.get("base_paise") or 180000, "flat_rate_paise")
    free_waiting_min = _to_int(rule.get("free_waiting_minutes") or 45, "free_waiting_minutes")
    waiting_rate_hr = _to_int(rule.get("waiting_paise_per_hour") or rule.get("waiting_paise") or 20000, "waiting_paise_per_hour")

    billable_waiting_min = max(0, telemetry.waiting_minutes - free_waiting_min)
    waiting_paise = round_div(billable_waiting_min * waiting_rate_hr, 60) if billable_waiting_min > 0 else 0

    return {
        "flat_rate_paise": flat_paise,
        "free_waiting_minutes": free_waiting_min,
        "total_waiting_minutes": telemetry.waiting_minutes,
        "billable_waiting_minutes": billable_waiting_min,
        "waiting_paise_per_hour": waiting_rate_hr,
        "waiting_charge_paise": waiting_paise,
        "transport_subtotal_paise": flat_paise + waiting_paise,
    }


def calculate_fuel_surcharge(
    effective_km: float,
    surcharge_rule: Optional[dict[str, Any]] = None,
    current_fuel_rate_paise: Optional[int] = None,
) -> dict[str, Any]:
    """Calculate dynamic fuel surcharge adjustment.

    Formula: (effective_km * fuel_delta_paise) / mileage_benchmark_km_per_litre
    Or percentage basis points if specified.
    """
    if not surcharge_rule:
        return {"amount_paise": 0, "formula": "no_surcharge_rule", "active": False}

    mode = str(surcharge_rule.get("mode") or "DYNAMIC_DELTA").upper()
    if mode == "PERCENTAGE":
        rate_bps = _to_int(surcharge_rule.get("surcharge_bps") or 0, "surcharge_bps")
        return {"amount_paise": 0, "mode": "PERCENTAGE", "rate_bps": rate_bps, "active": True}

    base_fuel_rate = _to_int(surcharge_rule.get("base_fuel_rate_paise") or 9000, "base_fuel_rate_paise")  # e.g. 90.00 INR/L
    cur_rate = _to_int(current_fuel_rate_paise or surcharge_rule.get("current_fuel_rate_paise") or base_fuel_rate, "current_fuel_rate_paise")
    mileage = _to_float(surcharge_rule.get("mileage_km_per_litre") or 12.0, "mileage_km_per_litre", minimum=1.0)

    fuel_delta_paise = max(0, cur_rate - base_fuel_rate)
    if fuel_delta_paise == 0 or effective_km <= 0:
        return {
            "amount_paise": 0,
            "mode": "DYNAMIC_DELTA",
            "base_fuel_rate_paise": base_fuel_rate,
            "current_fuel_rate_paise": cur_rate,
            "fuel_delta_paise": 0,
            "mileage_km_per_litre": mileage,
            "active": True,
        }

    surcharge_paise = int(round((effective_km * fuel_delta_paise) / mileage))
    return {
        "amount_paise": surcharge_paise,
        "mode": "DYNAMIC_DELTA",
        "base_fuel_rate_paise": base_fuel_rate,
        "current_fuel_rate_paise": cur_rate,
        "fuel_delta_paise": fuel_delta_paise,
        "mileage_km_per_litre": mileage,
        "active": True,
    }


def calculate_fare(
    telemetry_input: dict[str, Any] | TelemetryData,
    rate_rule: dict[str, Any],
    *,
    candidate_slabs: Optional[list[dict[str, Any]]] = None,
    surcharge_rule: Optional[dict[str, Any]] = None,
    current_fuel_rate_paise: Optional[int] = None,
    is_interstate: bool = False,
    tax_rate_bps: Optional[int] = None,
) -> dict[str, Any]:
    """Unified fare calculation engine for Axiom Fleet.

    Returns deterministic explainable line items, subtotal, fuel surcharge,
    tax calculation (CGST/SGST or IGST), and grand total in integer paise.
    """
    telemetry = TelemetryData.from_payload(telemetry_input) if isinstance(telemetry_input, dict) else telemetry_input
    duty_mode = _normalise_mode(rate_rule.get("fare_mode") or rate_rule.get("duty_type") or "local")

    lines: list[dict[str, Any]] = []
    explanation: dict[str, Any] = {
        "engine_version": FARE_ENGINE_VERSION,
        "duty_mode": duty_mode,
        "billing_mode": telemetry.billing_mode,
        "effective_km": telemetry.effective_km(rate_rule.get("max_shed_km")),
    }

    transport_subtotal_paise = 0

    if duty_mode == "local":
        local_calc = calculate_optimal_local_fare(telemetry, rate_rule, candidate_slabs)
        win = local_calc["winning_candidate"]
        transport_subtotal_paise = win["transport_subtotal_paise"]

        lines.append({
            "code": "BASE_PACKAGE",
            "label": f"Package Base ({win['slab_name']})",
            "quantity": 1,
            "unit_paise": win["base_fare_paise"],
            "amount_paise": win["base_fare_paise"],
            "category": "transport",
        })
        if win["extra_km"] > 0:
            lines.append({
                "code": "EXTRA_KM",
                "label": f"Extra Distance ({win['extra_km']:.1f} KM)",
                "quantity": int(round(win["extra_km"])),
                "unit_paise": int(round(win["extra_km_paise"] / win["extra_km"])) if win["extra_km"] else 0,
                "amount_paise": win["extra_km_paise"],
                "category": "transport",
            })
        if win["extra_time_paise"] > 0:
            lines.append({
                "code": "EXTRA_TIME",
                "label": f"Extra Time ({win['billable_extra_minutes']} mins)",
                "quantity": win["billable_extra_minutes"],
                "unit_paise": win["extra_time_paise"],
                "amount_paise": win["extra_time_paise"],
                "category": "transport",
            })

        explanation["slab_optimization"] = {
            "was_switched": local_calc["was_switched"],
            "switch_mode": local_calc["switch_mode"],
            "savings_paise": local_calc["savings_paise"],
            "booked_slab": local_calc["booked_candidate"]["slab_name"],
            "selected_slab": win["slab_name"],
            "selected_rule_id": win["rule"].get("id"),
        }
        # Check driver day and night allowances for local duty if applicable
        day_allowance = _to_int(rate_rule.get("allowance_paise") or rate_rule.get("driver_day_allowance_paise") or 0, "allowance_paise")
        if day_allowance > 0 and telemetry.calendar_days > 0:
            tot_day = telemetry.calendar_days * day_allowance
            lines.append({
                "code": "DRIVER_DAY_BATTA",
                "label": f"Driver Day Allowance ({telemetry.calendar_days} day{'s' if telemetry.calendar_days > 1 else ''})",
                "quantity": telemetry.calendar_days,
                "unit_paise": day_allowance,
                "amount_paise": tot_day,
                "category": "allowance",
            })
            transport_subtotal_paise += tot_day
        night_allowance = _to_int(rate_rule.get("night_allowance_paise") or rate_rule.get("driver_night_allowance_paise") or (rate_rule.get("extras") or {}).get("night_allowance_paise") or 0, "night_allowance_paise")
        if night_allowance > 0 and telemetry.night_hours_count > 0:
            tot_night = telemetry.night_hours_count * night_allowance
            lines.append({
                "code": "NIGHT_ALLOWANCE",
                "label": f"Driver Night Allowance ({telemetry.night_hours_count} block{'s' if telemetry.night_hours_count > 1 else ''})",
                "quantity": telemetry.night_hours_count,
                "unit_paise": night_allowance,
                "amount_paise": tot_night,
                "category": "allowance",
            })
            transport_subtotal_paise += tot_night

    elif duty_mode == "outstation":
        out_calc = calculate_outstation_fare(telemetry, rate_rule)
        transport_subtotal_paise = out_calc["transport_subtotal_paise"]

        lines.append({
            "code": "OUTSTATION_KM",
            "label": f"Outstation Distance ({out_calc['chargeable_km']:.1f} KM @ ₹{out_calc['rate_per_km_paise'] / 100:.2f}/km)",
            "quantity": int(round(out_calc["chargeable_km"])),
            "unit_paise": out_calc["rate_per_km_paise"],
            "amount_paise": out_calc["km_charge_paise"],
            "category": "transport",
        })
        if out_calc["total_day_batta_paise"] > 0:
            lines.append({
                "code": "DRIVER_BATTA",
                "label": f"Driver Day Allowance ({out_calc['calendar_days']} day{'s' if out_calc['calendar_days'] > 1 else ''})",
                "quantity": out_calc["calendar_days"],
                "unit_paise": out_calc["driver_day_batta_per_day_paise"],
                "amount_paise": out_calc["total_day_batta_paise"],
                "category": "allowance",
            })
        if out_calc["total_night_allowance_paise"] > 0:
            lines.append({
                "code": "NIGHT_ALLOWANCE",
                "label": f"Driver Night Allowance ({out_calc['night_blocks_count']} block{'s' if out_calc['night_blocks_count'] > 1 else ''})",
                "quantity": out_calc["night_blocks_count"],
                "unit_paise": out_calc["driver_night_allowance_rate_paise"],
                "amount_paise": out_calc["total_night_allowance_paise"],
                "category": "allowance",
            })

        explanation["outstation_breakdown"] = out_calc

    elif duty_mode == "airport":
        air_calc = calculate_airport_fare(telemetry, rate_rule)
        transport_subtotal_paise = air_calc["transport_subtotal_paise"]

        lines.append({
            "code": "AIRPORT_FLAT",
            "label": "Airport Transfer Flat Base",
            "quantity": 1,
            "unit_paise": air_calc["flat_rate_paise"],
            "amount_paise": air_calc["flat_rate_paise"],
            "category": "transport",
        })
        if air_calc["waiting_charge_paise"] > 0:
            lines.append({
                "code": "WAITING_CHARGE",
                "label": f"Excess Waiting ({air_calc['billable_waiting_minutes']} mins)",
                "quantity": air_calc["billable_waiting_minutes"],
                "unit_paise": air_calc["waiting_charge_paise"],
                "amount_paise": air_calc["waiting_charge_paise"],
                "category": "transport",
            })

        explanation["airport_breakdown"] = air_calc

    # Dynamic fuel surcharge
    fuel_result = calculate_fuel_surcharge(
        explanation["effective_km"],
        surcharge_rule or rate_rule.get("fuel_surcharge_rule"),
        current_fuel_rate_paise,
    )
    if fuel_result.get("amount_paise", 0) > 0:
        lines.append({
            "code": "FUEL_SURCHARGE",
            "label": f"Dynamic Fuel Surcharge (Δ ₹{fuel_result['fuel_delta_paise'] / 100:.2f}/L)",
            "quantity": 1,
            "unit_paise": fuel_result["amount_paise"],
            "amount_paise": fuel_result["amount_paise"],
            "category": "surcharge",
        })
        transport_subtotal_paise += fuel_result["amount_paise"]
    explanation["fuel_surcharge"] = fuel_result

    # Pass-through reimbursements (Tolls, Parking, Permits)
    reimbursements_paise = 0
    if telemetry.toll_paise > 0:
        lines.append({
            "code": "TOLL",
            "label": "Toll Charges",
            "quantity": 1,
            "unit_paise": telemetry.toll_paise,
            "amount_paise": telemetry.toll_paise,
            "category": "reimbursement",
        })
        reimbursements_paise += telemetry.toll_paise
    if telemetry.parking_paise > 0:
        lines.append({
            "code": "PARKING",
            "label": "Parking Fees",
            "quantity": 1,
            "unit_paise": telemetry.parking_paise,
            "amount_paise": telemetry.parking_paise,
            "category": "reimbursement",
        })
        reimbursements_paise += telemetry.parking_paise
    if telemetry.state_tax_paise > 0:
        lines.append({
            "code": "STATE_TAX",
            "label": "Inter-State Permit / Tax",
            "quantity": 1,
            "unit_paise": telemetry.state_tax_paise,
            "amount_paise": telemetry.state_tax_paise,
            "category": "reimbursement",
        })
        reimbursements_paise += telemetry.state_tax_paise
    if telemetry.extra_expense_paise > 0:
        lines.append({
            "code": "OTHER_EXPENSE",
            "label": "Approved Field Expense",
            "quantity": 1,
            "unit_paise": telemetry.extra_expense_paise,
            "amount_paise": telemetry.extra_expense_paise,
            "category": "expense",
        })
        reimbursements_paise += telemetry.extra_expense_paise

    subtotal_paise = transport_subtotal_paise + reimbursements_paise

    # Tax Calculation: By Indian GST rules, pure-agent reimbursements (tolls/permits)
    # can be excluded from GST base if reimbursements_taxable is False
    taxable_base_paise = subtotal_paise if telemetry.reimbursements_taxable else transport_subtotal_paise
    gst_bps = _to_int(tax_rate_bps if tax_rate_bps is not None else rate_rule.get("tax_rate_bps") or 500, "tax_rate_bps", maximum=2800)

    total_tax_paise = calc_percentage_bps(taxable_base_paise, gst_bps)

    tax_lines = []
    if gst_bps > 0:
        if is_interstate:
            tax_lines.append({
                "code": "IGST",
                "label": f"Integrated GST (IGST @ {gst_bps / 100:.1f}%)",
                "rate_bps": gst_bps,
                "taxable_amount_paise": taxable_base_paise,
                "tax_amount_paise": total_tax_paise,
            })
        else:
            half_bps = gst_bps // 2
            cgst_paise = round_div(total_tax_paise, 2)
            sgst_paise = total_tax_paise - cgst_paise
            tax_lines.append({
                "code": "CGST",
                "label": f"Central GST (CGST @ {half_bps / 100:.1f}%)",
                "rate_bps": half_bps,
                "taxable_amount_paise": taxable_base_paise,
                "tax_amount_paise": cgst_paise,
            })
            tax_lines.append({
                "code": "SGST",
                "label": f"State GST (SGST @ {half_bps / 100:.1f}%)",
                "rate_bps": half_bps,
                "taxable_amount_paise": taxable_base_paise,
                "tax_amount_paise": sgst_paise,
            })

    total_fare_paise = subtotal_paise + total_tax_paise

    return {
        "engine_version": FARE_ENGINE_VERSION,
        "duty_mode": duty_mode,
        "currency": str(rate_rule.get("currency") or "INR").upper(),
        "lines": lines,
        "tax_lines": tax_lines,
        "transport_subtotal_paise": transport_subtotal_paise,
        "reimbursements_paise": reimbursements_paise,
        "taxable_subtotal_paise": subtotal_paise,
        "taxable_base_paise": taxable_base_paise,
        "tax_rate_bps": gst_bps,
        "tax_paise": total_tax_paise,
        "total_fare_paise": total_fare_paise,
        "explanation": explanation,
    }


def calculate_dual_ledger_settlement(
    telemetry_input: dict[str, Any] | TelemetryData,
    receivable_profile: dict[str, Any],
    payable_profile: dict[str, Any],
    *,
    is_customer_interstate: bool = False,
    is_supplier_interstate: bool = False,
    current_fuel_rate_paise: Optional[int] = None,
) -> dict[str, Any]:
    """Calculate Dual-Ledger Settlement & Duty-Specific Gross Profit (P&L).

    Calculates:
    1. Receivable Ledger (Customer Billable Fare)
    2. Payable Ledger (Supplier / Attached Vehicle Owner Cost)
    3. Net Duty Gross Profit and Gross Margin Percentage
    """
    telemetry = TelemetryData.from_payload(telemetry_input) if isinstance(telemetry_input, dict) else telemetry_input

    # 1. Receivable calculation
    rec_result = calculate_fare(
        telemetry,
        receivable_profile,
        candidate_slabs=receivable_profile.get("candidate_slabs"),
        surcharge_rule=receivable_profile.get("fuel_surcharge_rule"),
        current_fuel_rate_paise=current_fuel_rate_paise,
        is_interstate=is_customer_interstate,
    )

    # 2. Payable calculation
    pay_result = calculate_fare(
        telemetry,
        payable_profile,
        candidate_slabs=payable_profile.get("candidate_slabs"),
        surcharge_rule=payable_profile.get("fuel_surcharge_rule"),
        current_fuel_rate_paise=current_fuel_rate_paise,
        is_interstate=is_supplier_interstate,
    )

    # Net Duty P&L (Excludes GST since tax is statutory pass-through)
    net_revenue_paise = rec_result["taxable_subtotal_paise"]
    net_cost_paise = pay_result["taxable_subtotal_paise"]
    gross_profit_paise = net_revenue_paise - net_cost_paise

    gross_margin_pct = 0.0
    if net_revenue_paise > 0:
        gross_margin_pct = round((gross_profit_paise / net_revenue_paise) * 100.0, 2)

    return {
        "engine_version": FARE_ENGINE_VERSION,
        "receivable": rec_result,
        "payable": pay_result,
        "settlement_pnl": {
            "currency": rec_result["currency"],
            "net_revenue_paise": net_revenue_paise,
            "net_cost_paise": net_cost_paise,
            "gross_profit_paise": gross_profit_paise,
            "gross_margin_percentage": gross_margin_pct,
            "is_profitable": gross_profit_paise >= 0,
        },
    }
