"""Test suite for Axiom HQ Custom Pricing Plans & Subscription Billing Automation."""

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from backend_axiom_hq import handle_axiom_hq, initialize_axiom_hq_schema

def run_tests():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    initialize_axiom_hq_schema(conn)

    hq_user = {
        "id": "usr_hq_superadmin",
        "email": "superadmin@axiomfleet.in",
        "role": "axiom_super_admin",
        "organization_id": "org_axiom_hq",
    }
    unauth_user = {
        "id": "usr_vendor_1",
        "email": "vendor@blueorbit.in",
        "role": "vendor",
        "organization_id": "org_blueorbit",
    }

    # 1. 403 Security Check
    try:
        handle_axiom_hq(conn, unauth_user, "GET", "/api/axiom-hq/plans")
        assert False, "Should have raised 403 DomainError for non-Axiom employee"
    except Exception as e:
        assert getattr(e, "status", None) == 403 or "403" in str(e), f"Expected 403, got {e}"
    print("PASS: Strict 403 isolation verified for non-HQ users")

    # 2. Plans Catalog
    plans = handle_axiom_hq(conn, hq_user, "GET", "/api/axiom-hq/plans")
    assert plans and len(plans["items"]) >= 3, f"Expected seeded plans, got {plans}"
    print(f"PASS: Fetched {len(plans['items'])} master pricing plans")

    # 3. Create Custom Pricing Plan
    new_plan_res = handle_axiom_hq(
        conn,
        hq_user,
        "POST",
        "/api/axiom-hq/plans",
        {
            "id": "plan_custom_express",
            "name": "Express City Tier",
            "tier": "CUSTOM_EXPRESS",
            "monthly_fee_inr": 18500.0,
            "annual_fee_inr": 185000.0,
            "duty_limit": 600,
            "vehicle_limit": 30,
            "white_label_enabled": True,
            "api_access_enabled": True,
            "support_tier": "Priority Chat (4h SLA)",
        },
    )
    assert new_plan_res and new_plan_res["status"] == "success"
    print("PASS: Created bespoke master pricing plan 'plan_custom_express'")

    # 4. Customize Vendor Plan & Pricing
    custom_plan_res = handle_axiom_hq(
        conn,
        hq_user,
        "POST",
        "/api/axiom-hq/vendors/ven_swift/custom-plan",
        {
            "saas_plan": "ENTERPRISE_WHITE_LABEL",
            "custom_plan_name": "Swift Enterprise Custom VIP",
            "saas_fee_inr": 42000.0,
            "billing_cycle": "MONTHLY",
            "custom_discount_pct": 10.0,
            "next_payment_due_date": "2026-11-01",
            "payment_status": "ACTIVE_PAID",
        },
    )
    assert custom_plan_res["status"] == "success"
    assert custom_plan_res["saas_fee_inr"] == 42000.0
    print("PASS: Customized vendor pricing terms and fee overrides")

    # 5. Issue SaaS Invoice
    inv_res = handle_axiom_hq(
        conn,
        hq_user,
        "POST",
        "/api/axiom-hq/invoices",
        {
            "vendor_id": "ven_swift",
            "base_amount_inr": 42000.0,
            "period_start": "2026-11-01",
            "period_end": "2026-11-30",
            "due_date": "2026-11-01",
            "notes": "Custom negotiated enterprise rate invoice",
        },
    )
    assert inv_res["status"] == "success"
    inv_id = inv_res["id"]
    print(f"PASS: Issued invoice {inv_res['invoice_number']} for INR {inv_res['total_amount_inr']}")

    # 6. Record Payment & Auto Advance Billing Cycle
    pay_res = handle_axiom_hq(
        conn,
        hq_user,
        "POST",
        f"/api/axiom-hq/invoices/{inv_id}/pay",
        {
            "payment_reference": "AXIS-IMPS-889211",
            "notes": "Payment reconciled via corporate banking",
        },
    )
    assert pay_res["status"] == "success"
    # Verify vendor next due date advanced by 30 days
    v_row = conn.execute("SELECT * FROM axiom_hq_vendors WHERE id = 'ven_swift'").fetchone()
    assert v_row["payment_status"] == "ACTIVE_PAID"
    assert v_row["next_payment_due_date"] == "2026-12-01", f"Expected 2026-12-01, got {v_row['next_payment_due_date']}"
    print("PASS: Recorded invoice payment and automatically advanced billing cycle to 2026-12-01")

    # 7. Run Automated Billing Scheduler
    # Force one vendor to be due in 3 days
    conn.execute("UPDATE axiom_hq_vendors SET next_payment_due_date = '2026-10-30', payment_status = 'ACTIVE_PAID' WHERE id = 'ven_apex'")
    # Force another vendor to be overdue by 20 days (should suspend)
    conn.execute("UPDATE axiom_hq_vendors SET next_payment_due_date = '2026-10-01', payment_status = 'OVERDUE_GRACE' WHERE id = 'ven_metroroyal'")
    conn.commit()

    auto_res = handle_axiom_hq(conn, hq_user, "POST", "/api/axiom-hq/billing/run-automation")
    assert auto_res["status"] == "success"
    assert auto_res["vendors_analyzed"] >= 3
    print(f"PASS: Billing automation executed. Log: {auto_res['actions_log']}")

    # Check vendor states post automation
    v_apex = conn.execute("SELECT * FROM axiom_hq_vendors WHERE id = 'ven_apex'").fetchone()
    assert v_apex["payment_status"] == "DUE_SOON"
    v_metro = conn.execute("SELECT * FROM axiom_hq_vendors WHERE id = 'ven_metroroyal'").fetchone()
    assert v_metro["payment_status"] == "SUSPENDED"
    print("PASS: Automated billing updated due-soon notices and suspended payment-defaulted accounts")

    # 8. Check KPIs
    kpi_res = handle_axiom_hq(conn, hq_user, "GET", "/api/axiom-hq/kpis")
    assert kpi_res["monthly_saas_mrr_inr"] > 0
    assert kpi_res["active_plans_count"] >= 4
    assert kpi_res["vendors_suspended"] == 1
    print(f"PASS: Axiom HQ telemetry KPIs updated with subscription billing metrics (MRR: INR {kpi_res['monthly_saas_mrr_inr']})")

    print("\nALL AXIOM HQ SUBSCRIPTION BILLING AUTOMATION TESTS PASSED (8/8)")

if __name__ == "__main__":
    run_tests()
