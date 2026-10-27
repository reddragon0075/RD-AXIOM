"""Axiom Mobility (Fleetline) Tri-Stack SLA Governance & Partner Tiering Engine.

Handles:
1. Vendor Tier Matrix (TIER_1_PLATINUM to BLOCKED)
2. Automated SLA Breach Detection (OTA < 92%, Late arrival > 15m, GPS blackout > 20%, unapproved swap)
3. Tier Demotion on Breach
4. Automated Penalty Debit Note Generation on Supplier Payable Ledger
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

PENALTY_SCHEDULE_PAISE = {
    "LATE_ARRIVAL_15M": 50000,      # ₹500
    "LATE_CANCELLATION": 100000,    # ₹1,000
    "UNAPPROVED_SWAP": 150000,      # ₹1,500
    "GPS_BLACKOUT_20PCT": 75000,    # ₹750
    "AC_FAILURE": 100000,           # ₹1,000
    "NO_SHOW": 200000,              # ₹2,000
}

TIER_HIERARCHY = ["TIER_1_PLATINUM", "TIER_2_GOLD", "TIER_3_SILVER", "PROBATION", "BLOCKED"]


def evaluate_sla_breach(
    duty_evidence: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Evaluates telemetry & duty evidence to detect SLA breaches."""
    late_minutes = int(duty_evidence.get("reporting_delay_minutes", 0))
    if late_minutes >= 15:
        return {
            "breach_type": "LATE_ARRIVAL_15M",
            "severity": "CRITICAL" if late_minutes >= 30 else "WARNING",
            "penalty_paise": PENALTY_SCHEDULE_PAISE["LATE_ARRIVAL_15M"],
            "explanation": f"Vehicle reported {late_minutes} mins late (SLA limit 15 mins).",
        }

    if duty_evidence.get("is_late_cancellation"):
        return {
            "breach_type": "LATE_CANCELLATION",
            "severity": "CRITICAL",
            "penalty_paise": PENALTY_SCHEDULE_PAISE["LATE_CANCELLATION"],
            "explanation": "Partner vendor cancelled duty within 4 hours of scheduled reporting.",
        }

    if duty_evidence.get("unapproved_driver_or_vehicle_swap"):
        return {
            "breach_type": "UNAPPROVED_SWAP",
            "severity": "CRITICAL",
            "penalty_paise": PENALTY_SCHEDULE_PAISE["UNAPPROVED_SWAP"],
            "explanation": "Driver or vehicle substituted at pickup without prior dispatcher approval.",
        }

    gps_drop_pct = float(duty_evidence.get("gps_blackout_pct", 0.0))
    if gps_drop_pct >= 20.0:
        return {
            "breach_type": "GPS_BLACKOUT_20PCT",
            "severity": "WARNING",
            "penalty_paise": PENALTY_SCHEDULE_PAISE["GPS_BLACKOUT_20PCT"],
            "explanation": f"GPS telemetry unavailable for {gps_drop_pct}% of trip duration.",
        }

    return None


def evaluate_tier_demotion(
    current_tier: str,
    rolling_ota_pct: float,
    active_breaches_7d: int,
) -> Tuple[str, bool, str]:
    """Calculates whether a partner vendor should be automatically demoted."""
    curr_idx = TIER_HIERARCHY.index(current_tier) if current_tier in TIER_HIERARCHY else 1
    
    # Severe failure -> immediate Probation or Blocked
    if rolling_ota_pct < 85.0 or active_breaches_7d >= 5:
        new_tier = "PROBATION" if curr_idx < 3 else "BLOCKED"
        reason = f"Critical breach: OTA {rolling_ota_pct}% or {active_breaches_7d} breaches in 7 days."
        return new_tier, True, reason

    # Threshold demotion
    if rolling_ota_pct < 92.0 or active_breaches_7d >= 3:
        new_idx = min(len(TIER_HIERARCHY) - 1, curr_idx + 1)
        new_tier = TIER_HIERARCHY[new_idx]
        reason = f"SLA breach threshold reached: OTA {rolling_ota_pct}% (<92%) with {active_breaches_7d} active breaches."
        return new_tier, True, reason

    return current_tier, False, "SLA within contractual limits."


def generate_penalty_debit_note(
    vendor_id: str,
    duty_id: str,
    breach: Dict[str, Any],
) -> Dict[str, Any]:
    """Issues an automated penalty debit note applied against the vendor's payable ledger."""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    debit_ref = f"DN-{vendor_id[:6].upper()}-{int(dt.datetime.now().timestamp())}"
    return {
        "debit_note_reference": debit_ref,
        "vendor_id": vendor_id,
        "duty_id": duty_id,
        "breach_type": breach["breach_type"],
        "penalty_paise": breach["penalty_paise"],
        "penalty_inr": round(breach["penalty_paise"] / 100.0, 2),
        "explanation": breach["explanation"],
        "issued_at": now,
        "status": "APPLIED_ON_PAYABLE_LEDGER",
    }
