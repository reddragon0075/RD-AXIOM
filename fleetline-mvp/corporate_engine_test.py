"""Unit tests for Axiom Corporate Engine (Policy, Waterfall Allotment, Demotion, REA Accounting)."""

import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from corporate_engine import (
    CorporateMobilityEngine,
    EmployeeBand,
    CorporateAccountSLA,
    AutomatedSupplierAllotmentEngine,
    SupplierRoutingRule,
    AllotmentAttempt,
    AutomaticTierDemotionEngine,
    ReaAccountingEngine,
    ReaAgent,
)


def test_corporate_policy_evaluation():
    band = EmployeeBand(
        id="band-exec",
        band_name="L1-Executive",
        allowed_vehicle_groups=["SEDAN", "EV_COMPACT"],
        extended_vehicle_groups=["SUV_PRIME"],
        allowed_duty_types=["AIRPORT_DROP", "8HR_80KM"],
        allowed_cities=["Bengaluru", "Mumbai"],
        allow_custom_passengers=False,
        enable_auto_allotment=True,
        skip_approval_start_hour=20,
        skip_approval_end_hour=6,
    )
    sla = CorporateAccountSLA(
        corporate_id="corp-1",
        booking_lead_sla_mins=60,
        cancellation_cutoff_sla_mins=120,
        cancellation_fee_flat=450.0,
    )

    now = datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc)

    # 1. Valid booking within policy (daytime, requires manager approval)
    valid_req = {
        "pickup_time": now + timedelta(hours=3),  # 13:00 UTC (180 mins notice)
        "city": "Bengaluru",
        "duty_type": "8HR_80KM",
        "vehicle_group": "SEDAN",
        "requires_manager_approval": True,
        "primary_vehicle_available": True,
    }
    eval1 = CorporateMobilityEngine.evaluate_booking_request(valid_req, band, sla, now)
    assert eval1.allowed, f"Expected allowed, got violations: {eval1.violations}"
    assert eval1.status == "PENDING_APPROVAL"
    assert eval1.resolved_vehicle_group == "SEDAN"

    # 2. Night shift auto-approval skips manager approval
    night_req = {
        "pickup_time": datetime(2026, 10, 22, 22, 30, tzinfo=timezone.utc),  # 22:30 UTC
        "city": "Bengaluru",
        "duty_type": "AIRPORT_DROP",
        "vehicle_group": "SEDAN",
        "requires_manager_approval": True,
        "primary_vehicle_available": True,
    }
    eval2 = CorporateMobilityEngine.evaluate_booking_request(night_req, band, sla, now)
    assert eval2.allowed
    assert eval2.status == "CONFIRMED", "Night shift booking should auto-approve without manager"
    assert eval2.auto_allot_to_supplier is True

    # 3. Fallback to extended vehicle group when primary unavailable
    fallback_req = {
        "pickup_time": now + timedelta(hours=4),
        "city": "Bengaluru",
        "duty_type": "AIRPORT_DROP",
        "vehicle_group": "SUV_PRIME",  # Not in allowed, but in extended
        "requires_manager_approval": False,
        "primary_vehicle_available": False,  # Primary sedan unavailable
    }
    eval3 = CorporateMobilityEngine.evaluate_booking_request(fallback_req, band, sla, now)
    assert eval3.allowed
    assert eval3.resolved_vehicle_group == "SUV_PRIME"

    # 4. Lead-time SLA violation
    short_notice_req = {
        "pickup_time": now + timedelta(minutes=30),  # Only 30m notice (< 60m SLA)
        "city": "Bengaluru",
        "duty_type": "AIRPORT_DROP",
        "vehicle_group": "SEDAN",
    }
    eval4 = CorporateMobilityEngine.evaluate_booking_request(short_notice_req, band, sla, now)
    assert not eval4.allowed
    assert any("lead-time SLA" in v for v in eval4.violations)

    print("[PASS] Corporate policy and band tests passed.")


def test_cancellation_liability():
    sla = CorporateAccountSLA(
        corporate_id="corp-1",
        cancellation_cutoff_sla_mins=120,
        always_bill_late_cancel=True,
        cancellation_fee_flat=500.0,
    )
    pickup = datetime(2026, 10, 22, 14, 0, tzinfo=timezone.utc)

    # Cancelled 3 hours before -> free
    cancel_early = datetime(2026, 10, 22, 11, 0, tzinfo=timezone.utc)
    res_free = CorporateMobilityEngine.calculate_cancellation_liability(pickup, cancel_early, sla)
    assert res_free["status"] == "CANCELLED_FREE"
    assert res_free["is_billable"] is False
    assert res_free["cancellation_fee"] == 0.0

    # Cancelled 45 mins before -> billable late cancellation
    cancel_late = datetime(2026, 10, 22, 13, 15, tzinfo=timezone.utc)
    res_late = CorporateMobilityEngine.calculate_cancellation_liability(pickup, cancel_late, sla)
    assert res_late["status"] == "CANCELLED_BILLABLE"
    assert res_late["is_billable"] is True
    assert res_late["cancellation_fee"] == 500.0

    print("[PASS] Cancellation liability tests passed.")


def test_waterfall_allotment_and_cascade():
    now = datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc)

    # Rules with different tiers and share-of-wallet deficits
    # Rule A: Tier 1, target 60%, current 50% -> deficit 10%
    rule_a = SupplierRoutingRule(
        rule_id="r-1",
        corporate_id="corp-1",
        supplier_id="sup-A",
        supplier_name="Vendor A",
        city="Bengaluru",
        vehicle_group="SEDAN",
        priority_tier=1,
        target_allocation_pct=60.0,
        current_month_share_pct=50.0,
        reliability_score=95.0,
    )
    # Rule B: Tier 1, target 40%, current 20% -> deficit 20% (Furthest below share)
    rule_b = SupplierRoutingRule(
        rule_id="r-2",
        corporate_id="corp-1",
        supplier_id="sup-B",
        supplier_name="Vendor B",
        city="Bengaluru",
        vehicle_group="SEDAN",
        priority_tier=1,
        target_allocation_pct=40.0,
        current_month_share_pct=20.0,
        reliability_score=92.0,
    )
    # Rule C: Tier 2 (Secondary)
    rule_c = SupplierRoutingRule(
        rule_id="r-3",
        corporate_id="corp-1",
        supplier_id="sup-C",
        supplier_name="Vendor C",
        city="Bengaluru",
        vehicle_group="SEDAN",
        priority_tier=2,
        target_allocation_pct=100.0,
        current_month_share_pct=0.0,
        reliability_score=99.0,
    )

    # Queue should place Tier 1 before Tier 2, and within Tier 1, Vendor B (20% deficit) ahead of Vendor A (10% deficit)
    queue = AutomatedSupplierAllotmentEngine.build_waterfall_queue([rule_a, rule_b, rule_c])
    assert len(queue) == 3
    assert queue[0].supplier_id == "sup-B", f"Expected sup-B first, got {queue[0].supplier_id}"
    assert queue[1].supplier_id == "sup-A"
    assert queue[2].supplier_id == "sup-C"

    # Dynamic SLA: urgent (<180m) vs standard (>180m)
    urgent_pickup = now + timedelta(minutes=90)
    sla_urgent = AutomatedSupplierAllotmentEngine.calculate_sla_expiry(urgent_pickup, rule_a, now)
    assert (sla_urgent - now).total_seconds() / 60 == rule_a.compressed_sla_mins

    standard_pickup = now + timedelta(minutes=240)
    sla_std = AutomatedSupplierAllotmentEngine.calculate_sla_expiry(standard_pickup, rule_a, now)
    assert (sla_std - now).total_seconds() / 60 == rule_a.acceptance_sla_mins

    # Timeout cascade from sup-B to sup-A
    attempt_1 = AllotmentAttempt(
        attempt_id="att-1",
        booking_id="bk-12345678",
        supplier_id="sup-B",
        supplier_name="Vendor B",
        attempt_sequence=1,
        priority_tier=1,
        status="EXPIRED_SLA_TIMEOUT",
        dispatched_at=now,
        sla_expires_at=now + timedelta(minutes=8),
    )
    tried = set()
    cascade_1 = AutomatedSupplierAllotmentEngine.handle_timeout_or_rejection_cascade(
        "bk-12345678", urgent_pickup, [rule_a, rule_b, rule_c], attempt_1, tried, now
    )
    assert cascade_1["action"] == "DISPATCH_TO_SUPPLIER"
    assert cascade_1["supplier_id"] == "sup-A"

    print("[PASS] Waterfall allotment and cascade tests passed.")


def test_tier_demotion():
    # Supplier score 92 -> applies TIMEOUT (-5) -> 87 (still >= 85, no demotion)
    score1 = AutomaticTierDemotionEngine.apply_penalty(92.0, "TIMEOUT")
    assert score1 == 87.0
    dem1 = AutomaticTierDemotionEngine.evaluate_and_execute_demotion("sup-X", "Vendor X", 1, score1)
    assert not dem1["demotion_triggered"]

    # Supplier score 87 -> applies TIMEOUT (-5) -> 82 (< 85 -> DEMOTION to Tier 3)
    score2 = AutomaticTierDemotionEngine.apply_penalty(score1, "TIMEOUT")
    assert score2 == 82.0
    dem2 = AutomaticTierDemotionEngine.evaluate_and_execute_demotion("sup-X", "Vendor X", 1, score2, recent_timeouts=2)
    assert dem2["demotion_triggered"]
    assert dem2["new_tier"] == 3
    assert dem2["auto_allotment_revoked"] is True

    print("[PASS] Tier demotion tests passed.")


def test_rea_accounting_balance():
    corp = ReaAgent(id="corp-acme", name="Acme Corp India", role="CORPORATE_CLIENT", gstin="29AAAAA0000A1Z5")
    supp = ReaAgent(id="sup-swift", name="Swift Fleet Ltd", role="SUPPLIER_VENDOR", gstin="29BBBBB1111B1Z2")
    plat = ReaAgent(id="plat-axiom", name="Axiom Fleet Platform", role="PLATFORM_OPERATOR")

    # Corporate invoice: Taxable 2000 INR, GST 100 INR (5%), Tolls 150 INR -> Total AR 2250 INR
    # Supplier payout: Taxable 1600 INR, GST 80 INR (5%), Tolls 150 INR -> Total AP 1830 INR
    res = ReaAccountingEngine.generate_duality_and_journal(
        booking_id="bk-99887766",
        corporate_agent=corp,
        supplier_agent=supp,
        platform_agent=plat,
        taxable_ar=2000.0,
        gst_ar=100.0,
        taxable_ap=1600.0,
        gst_ap=80.0,
        tolls=150.0,
    )

    assert res["status"] == "BALANCED", f"Accounting journal is unbalanced! Debits: {res['total_debits']}, Credits: {res['total_credits']}"
    assert res["total_debits"] == res["total_credits"]
    assert res["gross_margin"] == 400.0  # 2000 - 1600
    assert res["margin_pct"] == 20.0     # 400 / 2000 * 100%

    print("[PASS] REA double-entry accounting balance test passed.")


if __name__ == "__main__":
    test_corporate_policy_evaluation()
    test_cancellation_liability()
    test_waterfall_allotment_and_cascade()
    test_tier_demotion()
    test_rea_accounting_balance()
    print("\nALL CORPORATE ENGINE & REA TESTS PASSED SUCCESSFULLY!")
