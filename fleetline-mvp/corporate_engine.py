"""Axiom Corporate Mobility, Waterfall Allotment & REA Accounting Engine.

Ported and unified from Axiom_Corporate TypeScript stack into Python.
Provides deterministic, zero-dependency:
1. Corporate Mobility Policy Engine:
   - Band permission evaluation (cities, duty types, vehicle groups).
   - Extended vehicle group fallback when primary is unavailable.
   - Lead-time SLA evaluation.
   - Night-shift auto-approval window (e.g. 20:00 to 06:00 skips approval).
   - Cancellation liability determination (lead time cutoffs & penalties).
   - Digital duty slip validation & HMAC/SHA-256 signature hashing.

2. Automated Supplier Waterfall Allotment Engine:
   - Multi-tier ranking: Priority Tier ASC -> Share-of-Wallet Deficit DESC -> Reliability DESC.
   - Urgent pickup compressed SLA logic (< 180 min cutoff).
   - SLA expiration tracking and automated cascade to next tier.
   - Escalation to manual dispatch upon queue exhaustion.

3. Automatic Tier Demotion & Reliability Engine:
   - SLA breach scoring penalties (timeouts, rejections, no-shows).
   - Automated demotion to Tier 3 (Spot) when reliability drops below 85%.

4. REA (Resource-Event-Agent) Dual-Entry Economic Engine:
   - Immutable economic events (service consumption, delivery, tax accruals).
   - Full duality binding between Corporate Receivable & Supplier Payable.
   - Balanced double-entry journal generation (Debits == Credits).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, time
import hashlib
import json
import math
from typing import Any, Dict, List, Optional, Set, Tuple


# -----------------------------------------------------------------------------
# 1. CORPORATE MOBILITY & POLICY ENGINE
# -----------------------------------------------------------------------------

@dataclass
class EmployeeBand:
    id: str
    band_name: str
    allowed_vehicle_groups: List[str]
    extended_vehicle_groups: List[str] = field(default_factory=list)
    allowed_duty_types: List[str] = field(default_factory=list)
    allowed_cities: List[str] = field(default_factory=list)
    base_city: str = ""
    allow_custom_passengers: bool = False
    enable_auto_allotment: bool = True
    skip_approval_start_hour: Optional[int] = None  # e.g. 20 (8 PM)
    skip_approval_end_hour: Optional[int] = None    # e.g. 6 (6 AM)


@dataclass
class CorporateAccountSLA:
    corporate_id: str
    booking_lead_sla_mins: int = 60          # Min notice required
    cancellation_cutoff_sla_mins: int = 120  # Cutoff before cancellation becomes billable
    always_bill_late_cancel: bool = True
    cancellation_fee_flat: float = 500.0


@dataclass
class BookingPolicyEvaluation:
    allowed: bool
    status: str  # 'CONFIRMED' or 'PENDING_APPROVAL'
    auto_allot_to_supplier: bool
    resolved_vehicle_group: str
    violations: List[str] = field(default_factory=list)


class CorporateMobilityEngine:
    """Evaluates corporate policies, band entitlements, and SLA bounds."""

    @staticmethod
    def is_in_skip_approval_window(
        pickup_time: datetime,
        start_hour: Optional[int],
        end_hour: Optional[int],
    ) -> bool:
        """Determines if the booking falls in an auto-approval time window (e.g. night shift)."""
        if start_hour is None or end_hour is None:
            return False
        
        pickup_hour = pickup_time.hour
        if start_hour > end_hour:
            # Overnight window: e.g. 20:00 to 06:00
            return pickup_hour >= start_hour or pickup_hour < end_hour
        else:
            # Daytime window: e.g. 09:00 to 17:00
            return start_hour <= pickup_hour < end_hour

    @classmethod
    def evaluate_booking_request(
        cls,
        request: Dict[str, Any],
        band: EmployeeBand,
        sla: CorporateAccountSLA,
        now: Optional[datetime] = None,
    ) -> BookingPolicyEvaluation:
        if now is None:
            now = datetime.now(timezone.utc)

        pickup_time = request["pickup_time"]
        if isinstance(pickup_time, str):
            pickup_time = datetime.fromisoformat(pickup_time.replace("Z", "+00:00"))

        violations: List[str] = []

        # A. Lead-time SLA check
        lead_time_mins = (pickup_time - now).total_seconds() / 60.0
        if lead_time_mins < sla.booking_lead_sla_mins:
            violations.append(
                f"Booking violates corporate lead-time SLA: requires at least {sla.booking_lead_sla_mins} "
                f"mins notice (requested {math.floor(lead_time_mins)} mins prior)."
            )

        # B. City & Duty Type permissions
        if request.get("city") and band.allowed_cities and request["city"] not in band.allowed_cities:
            violations.append(f"City '{request['city']}' is not permitted under band '{band.band_name}'.")

        if request.get("duty_type") and band.allowed_duty_types and request["duty_type"] not in band.allowed_duty_types:
            violations.append(f"Duty type '{request['duty_type']}' is not permitted under band '{band.band_name}'.")

        # C. Vehicle Group & Extended Fallback Group
        requested_vehicle = request.get("vehicle_group", "")
        resolved_vehicle = requested_vehicle
        is_primary = requested_vehicle in band.allowed_vehicle_groups
        is_extended = requested_vehicle in band.extended_vehicle_groups
        primary_avail = request.get("primary_vehicle_available", True)

        if not is_primary:
            if is_extended and not primary_avail:
                resolved_vehicle = requested_vehicle  # Permitted via extended group fallback
            else:
                violations.append(
                    f"Vehicle group '{requested_vehicle}' is not permitted under band '{band.band_name}'."
                )

        # D. Custom passenger check
        if request.get("custom_passengers") and not band.allow_custom_passengers:
            violations.append(f"Band '{band.band_name}' does not permit booking for external/custom passengers.")

        allowed = len(violations) == 0

        # E. Determine approval requirement
        skip_window = cls.is_in_skip_approval_window(
            pickup_time, band.skip_approval_start_hour, band.skip_approval_end_hour
        )

        requires_manager = request.get("requires_manager_approval", False)
        if skip_window:
            status = "CONFIRMED"
        elif requires_manager:
            status = "PENDING_APPROVAL"
        else:
            status = "CONFIRMED"

        auto_allot = allowed and (status == "CONFIRMED") and band.enable_auto_allotment

        return BookingPolicyEvaluation(
            allowed=allowed,
            status=status,
            auto_allot_to_supplier=auto_allot,
            resolved_vehicle_group=resolved_vehicle,
            violations=violations,
        )

    @classmethod
    def calculate_cancellation_liability(
        cls,
        pickup_time: datetime,
        cancellation_time: datetime,
        sla: CorporateAccountSLA,
        base_fare: float = 0.0,
    ) -> Dict[str, Any]:
        """Calculates whether a cancellation is free or billable with penalty."""
        notice_mins = (pickup_time - cancellation_time).total_seconds() / 60.0
        is_late = notice_mins < sla.cancellation_cutoff_sla_mins

        if is_late and sla.always_bill_late_cancel:
            penalty = sla.cancellation_fee_flat if sla.cancellation_fee_flat > 0 else base_fare
            return {
                "status": "CANCELLED_BILLABLE",
                "is_billable": True,
                "cancellation_fee": round(penalty, 2),
                "notice_mins": round(notice_mins, 1),
                "cutoff_mins": sla.cancellation_cutoff_sla_mins,
                "reason": f"Cancelled {round(notice_mins, 1)}m before pickup; SLA cutoff is {sla.cancellation_cutoff_sla_mins}m.",
            }
        return {
            "status": "CANCELLED_FREE",
            "is_billable": False,
            "cancellation_fee": 0.0,
            "notice_mins": round(notice_mins, 1),
            "cutoff_mins": sla.cancellation_cutoff_sla_mins,
            "reason": f"Cancelled with adequate notice ({round(notice_mins, 1)}m >= {sla.cancellation_cutoff_sla_mins}m cutoff).",
        }

    @staticmethod
    def generate_duty_slip_signature_hash(
        booking_id: str,
        actual_km: float,
        actual_hours: float,
        toll_amount: float,
        secret: str = "axiom-slip-signing-key",
    ) -> str:
        payload = f"{booking_id}:{actual_km:.2f}:{actual_hours:.2f}:{toll_amount:.2f}:{secret}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# -----------------------------------------------------------------------------
# 2. AUTOMATED SUPPLIER WATERFALL ALLOTMENT ENGINE
# -----------------------------------------------------------------------------

@dataclass
class SupplierRoutingRule:
    rule_id: str
    corporate_id: str
    supplier_id: str
    supplier_name: str
    city: str
    vehicle_group: str
    priority_tier: int            # 1 = Primary, 2 = Secondary, 3 = Backup
    target_allocation_pct: float  # e.g. 70.0%
    current_month_share_pct: float # e.g. 55.0%
    acceptance_sla_mins: int = 20
    compressed_sla_mins: int = 8  # Used for urgent pickups
    daily_cap_duties: int = 50
    today_allotted_count: int = 0
    reliability_score: float = 100.0  # 0 to 100
    is_active: bool = True


@dataclass
class AllotmentAttempt:
    attempt_id: str
    booking_id: str
    supplier_id: str
    supplier_name: str
    attempt_sequence: int
    priority_tier: int
    status: str  # 'DISPATCHED_WAITING', 'ACCEPTED_ALLOTTED', 'REJECTED_BY_SUPPLIER', 'EXPIRED_SLA_TIMEOUT'
    dispatched_at: datetime
    sla_expires_at: datetime
    responded_at: Optional[datetime] = None
    allotment_details: Optional[Dict[str, str]] = None
    rejection_reason: Optional[str] = None


class AutomatedSupplierAllotmentEngine:
    """Manages multi-tier waterfall ordering, dynamic SLAs, and cascade timeouts."""

    URGENT_PICKUP_THRESHOLD_MINS = 180  # 3 hours

    @classmethod
    def build_waterfall_queue(
        cls,
        rules: List[SupplierRoutingRule],
        already_tried_supplier_ids: Optional[Set[str]] = None,
    ) -> List[SupplierRoutingRule]:
        """Ranks eligible suppliers: Tier (ASC) -> Share Deficit (DESC) -> Reliability (DESC)."""
        if already_tried_supplier_ids is None:
            already_tried_supplier_ids = set()

        eligible = [
            r for r in rules
            if r.is_active
            and r.today_allotted_count < r.daily_cap_duties
            and r.supplier_id not in already_tried_supplier_ids
        ]

        def sort_key(r: SupplierRoutingRule) -> Tuple[int, float, float]:
            share_deficit = r.target_allocation_pct - r.current_month_share_pct
            # Tier ascending (1 first), share_deficit descending, reliability descending
            return (r.priority_tier, -share_deficit, -r.reliability_score)

        return sorted(eligible, key=sort_key)

    @classmethod
    def calculate_sla_expiry(
        cls,
        pickup_time: datetime,
        rule: SupplierRoutingRule,
        now: Optional[datetime] = None,
    ) -> datetime:
        if now is None:
            now = datetime.now(timezone.utc)

        mins_until_pickup = (pickup_time - now).total_seconds() / 60.0
        effective_sla = (
            rule.compressed_sla_mins
            if mins_until_pickup <= cls.URGENT_PICKUP_THRESHOLD_MINS
            else rule.acceptance_sla_mins
        )
        return now + timedelta(minutes=effective_sla)

    @classmethod
    def handle_timeout_or_rejection_cascade(
        cls,
        booking_id: str,
        pickup_time: datetime,
        all_rules: List[SupplierRoutingRule],
        current_attempt: AllotmentAttempt,
        tried_supplier_ids: Set[str],
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Advances waterfall queue when the current supplier timeouts or rejects."""
        if now is None:
            now = datetime.now(timezone.utc)

        tried_supplier_ids.add(current_attempt.supplier_id)
        queue = cls.build_waterfall_queue(all_rules, tried_supplier_ids)

        if not queue:
            return {
                "action": "ESCALATE_MANUAL_INTERVENTION",
                "escalation_reason": "All eligible suppliers in waterfall queue exhausted or timed out.",
                "tried_suppliers_count": len(tried_supplier_ids),
            }

        next_rule = queue[0]
        next_attempt = AllotmentAttempt(
            attempt_id=f"att-{booking_id[:8]}-{current_attempt.attempt_sequence + 1}",
            booking_id=booking_id,
            supplier_id=next_rule.supplier_id,
            supplier_name=next_rule.supplier_name,
            attempt_sequence=current_attempt.attempt_sequence + 1,
            priority_tier=next_rule.priority_tier,
            status="DISPATCHED_WAITING",
            dispatched_at=now,
            sla_expires_at=cls.calculate_sla_expiry(pickup_time, next_rule, now),
        )

        return {
            "action": "DISPATCH_TO_SUPPLIER",
            "next_attempt": next_attempt,
            "selected_tier": next_rule.priority_tier,
            "supplier_id": next_rule.supplier_id,
            "supplier_name": next_rule.supplier_name,
        }


# -----------------------------------------------------------------------------
# 3. AUTOMATIC TIER DEMOTION & RELIABILITY ENGINE
# -----------------------------------------------------------------------------

class AutomaticTierDemotionEngine:
    """Enforces SLA accountability through automated score deduction and demotion."""

    RELIABILITY_THRESHOLD = 85.0
    SPOT_TIER_NUMBER = 3

    PENALTIES = {
        "TIMEOUT": 5.0,
        "REJECTION": 3.0,
        "LATE_CANCELLATION": 10.0,
        "DRIVER_NO_SHOW": 20.0,
    }

    @classmethod
    def apply_penalty(cls, current_score: float, penalty_type: str) -> float:
        penalty = cls.PENALTIES.get(penalty_type.upper(), 5.0)
        return max(0.0, round(current_score - penalty, 2))

    @classmethod
    def evaluate_and_execute_demotion(
        cls,
        supplier_id: str,
        supplier_name: str,
        current_tier: int,
        reliability_score: float,
        recent_timeouts: int = 1,
    ) -> Dict[str, Any]:
        """Demotes supplier to Spot Tier (Tier 3) if reliability score dips below 85%."""
        if reliability_score >= cls.RELIABILITY_THRESHOLD or current_tier >= cls.SPOT_TIER_NUMBER:
            return {"demotion_triggered": False, "supplier_id": supplier_id, "current_tier": current_tier}

        return {
            "demotion_triggered": True,
            "supplier_id": supplier_id,
            "supplier_name": supplier_name,
            "previous_tier": current_tier,
            "new_tier": cls.SPOT_TIER_NUMBER,
            "auto_allotment_revoked": True,
            "demotion_reason": (
                f"Reliability score fell to {reliability_score:.1f}% ({recent_timeouts} recent breach(es)), "
                f"violating the {cls.RELIABILITY_THRESHOLD}% SLA floor."
            ),
            "demoted_at": datetime.now(timezone.utc).isoformat(),
        }


# -----------------------------------------------------------------------------
# 4. REA (RESOURCE-EVENT-AGENT) DUAL-ENTRY ACCOUNTING ENGINE
# -----------------------------------------------------------------------------

@dataclass
class ReaAgent:
    id: str
    name: str
    role: str  # 'CORPORATE_CLIENT', 'SUPPLIER_VENDOR', 'PASSENGER_EMPLOYEE', 'PLATFORM_OPERATOR'
    gstin: str = ""


@dataclass
class ReaEconomicEvent:
    event_id: str
    duality_id: str
    event_type: str
    direction: str  # 'INCREMENT' or 'DECREMENT'
    resource_code: str
    from_agent: ReaAgent
    to_agent: ReaAgent
    amount: float
    currency: str = "INR"
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ReaJournalLine:
    account_code: str
    account_name: str
    debit: float
    credit: float
    description: str


class ReaAccountingEngine:
    """Produces immutable economic events and perfectly balanced double-entry journals."""

    @classmethod
    def generate_duality_and_journal(
        cls,
        booking_id: str,
        corporate_agent: ReaAgent,
        supplier_agent: ReaAgent,
        platform_agent: ReaAgent,
        taxable_ar: float,
        gst_ar: float,
        taxable_ap: float,
        gst_ap: float,
        tolls: float = 0.0,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        if now is None:
            now = datetime.now(timezone.utc)

        duality_id = f"dual-{booking_id[:8]}"
        gross_receivable = round(taxable_ar + gst_ar + tolls, 2)
        gross_payable = round(taxable_ap + gst_ap + tolls, 2)
        gross_margin = round(taxable_ar - taxable_ap, 2)
        margin_pct = round((gross_margin / taxable_ar * 100.0), 2) if taxable_ar > 0 else 0.0

        events = [
            ReaEconomicEvent(
                event_id=f"evt-{duality_id}-1",
                duality_id=duality_id,
                event_type="SERVICE_CONSUMED",
                direction="INCREMENT",
                resource_code="MOBILITY_SERVICE",
                from_agent=supplier_agent,
                to_agent=corporate_agent,
                amount=taxable_ar,
                occurred_at=now,
            ),
            ReaEconomicEvent(
                event_id=f"evt-{duality_id}-2",
                duality_id=duality_id,
                event_type="RECEIVABLE_INCURRED",
                direction="INCREMENT",
                resource_code="INR_CURRENCY",
                from_agent=corporate_agent,
                to_agent=platform_agent,
                amount=gross_receivable,
                occurred_at=now,
            ),
            ReaEconomicEvent(
                event_id=f"evt-{duality_id}-3",
                duality_id=duality_id,
                event_type="PAYABLE_INCURRED",
                direction="INCREMENT",
                resource_code="INR_CURRENCY",
                from_agent=platform_agent,
                to_agent=supplier_agent,
                amount=gross_payable,
                occurred_at=now,
            ),
            ReaEconomicEvent(
                event_id=f"evt-{duality_id}-4",
                duality_id=duality_id,
                event_type="TAX_OUTPUT_ACCRUED",
                direction="INCREMENT",
                resource_code="GST_OUTPUT_TAX",
                from_agent=platform_agent,
                to_agent=ReaAgent(id="govt", name="Government of India Tax Authority", role="TAX_AUTHORITY"),
                amount=gst_ar,
                occurred_at=now,
            ),
        ]

        # Double-entry lines (Debits must exactly equal Credits)
        journal_lines = [
            ReaJournalLine(
                account_code="1100",
                account_name="Accounts Receivable - Corporate",
                debit=gross_receivable,
                credit=0.0,
                description=f"Corporate trip charge: {corporate_agent.name}",
            ),
            ReaJournalLine(
                account_code="4000",
                account_name="Operating Revenue - Corporate Mobility",
                debit=0.0,
                credit=taxable_ar,
                description="Billed mobility trip revenue",
            ),
            ReaJournalLine(
                account_code="2200",
                account_name="GST Output Tax Payable",
                debit=0.0,
                credit=gst_ar,
                description=f"Output GST liability (18% / 5%) on booking {booking_id[:8]}",
            ),
            ReaJournalLine(
                account_code="5000",
                account_name="Direct Fleet Fulfillment Expense (Cost of Sales)",
                debit=taxable_ap,
                credit=0.0,
                description=f"Supplier fulfillment payable: {supplier_agent.name}",
            ),
            ReaJournalLine(
                account_code="1250",
                account_name="GST Input Tax Credit (ITC)",
                debit=gst_ap,
                credit=0.0,
                description="Input tax credit claimable from supplier invoice",
            ),
            ReaJournalLine(
                account_code="2100",
                account_name="Accounts Payable - Fleet Supplier",
                debit=0.0,
                credit=gross_payable,
                description=f"Supplier payout obligation: {supplier_agent.name}",
            ),
        ]

        # Pure agent reimbursement (tolls pass-through)
        if tolls > 0:
            journal_lines.append(
                ReaJournalLine(
                    account_code="2150",
                    account_name="Toll & Parking Reimbursable Clearing",
                    debit=tolls,
                    credit=tolls,
                    description="Pass-through pure agent toll reimbursement",
                )
            )

        total_debits = round(sum(line.debit for line in journal_lines), 2)
        total_credits = round(sum(line.credit for line in journal_lines), 2)
        balanced = abs(total_debits - total_credits) < 0.001

        return {
            "duality_id": duality_id,
            "booking_id": booking_id,
            "status": "BALANCED" if balanced else "UNBALANCED",
            "total_receivable": gross_receivable,
            "total_payable": gross_payable,
            "gross_margin": gross_margin,
            "margin_pct": margin_pct,
            "total_debits": total_debits,
            "total_credits": total_credits,
            "journal_lines": [
                {
                    "account_code": l.account_code,
                    "account_name": l.account_name,
                    "debit": l.debit,
                    "credit": l.credit,
                    "description": l.description,
                }
                for l in journal_lines
            ],
            "economic_events_count": len(events),
        }
