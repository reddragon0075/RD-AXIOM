"""Comprehensive Tri-Stack Engine Test Suite (MoveInSync + Routematic + Indecab Parity)."""

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from tariff_engine import calculate_dual_ledger_duty, resolve_auto_slab
from sla_governance import evaluate_sla_breach, evaluate_tier_demotion, generate_penalty_debit_note
from safety_compliance import evaluate_safe_reach_escalation, is_night_shift_window, scan_telemetry_alerts, validate_night_shift_safety
from erp_gst_bridge import determine_gst_tax_structure, export_tally_prime_xml, generate_irp_einvoice_payload
from backend_tristack import handle_tristack, initialize_tristack_schema

def run_tests():
    print("--- 1. TARIFF & DUAL-LEDGER ENGINE TESTS ---")
    # Auto-slab test
    slabs = [
        {"hours": 4, "km": 40, "base_paise": 180000},
        {"hours": 8, "km": 80, "base_paise": 320000},
        {"hours": 12, "km": 120, "base_paise": 450000},
    ]
    # Trip of 7.5 hrs and 75 km -> client favorable picks lowest cost
    best_slab, cost, note = resolve_auto_slab(7.5, 75, slabs, extra_hr_paise=15000, extra_km_paise=1800)
    assert cost == 303000
    print(f"PASS: Auto-slab selected lowest client cost of INR {cost/100} ({note})")

    # Trip with strict slab jump (client_favorable=False)
    strict_slab, strict_cost, strict_note = resolve_auto_slab(8.0, 95, slabs, extra_hr_paise=15000, extra_km_paise=1800, client_favorable=False)
    assert strict_slab["hours"] == 4
    print(f"PASS: Strict slab resolution picked base slab {strict_slab['hours']}H/{strict_slab['km']}K")

    # Dual-ledger test: verifies live Gross Margin & negative margin audit hold
    client_card = {
        "slabs": slabs,
        "driver_bhatta_paise": 40000,
        "extra_km_paise": 1800,
        "extra_hr_paise": 15000,
        "buffer_km": 10.0,
        "buffer_minutes": 30.0,
        "gst_rate_pct": 5.0,
    }
    supplier_card = {
        "base_paise": 180000,
        "extra_km_paise": 1200,
        "driver_bhatta_paise": 30000,
    }
    duty_params = {
        "billing_mode": "HR_KM_SLAB",
        "garage_matrix": "G2G_FIXED_BUFFER",
        "distance_km": 50.0,
        "duration_hours": 5.0,
        "toll_parking_paise": 15000,
    }
    dl_res = calculate_dual_ledger_duty(duty_params, client_card, supplier_card)
    assert dl_res["client_receivable"]["gross_receivable_paise"] > 0
    assert dl_res["supplier_payable"]["gross_payable_paise"] > 0
    assert dl_res["gross_margin_paise"] > 0
    assert dl_res["billable_km"] == 70.0  # 50 + 20 buffer
    print(f"PASS: Dual-ledger calculated Gross Receivable INR {dl_res['client_receivable']['gross_receivable_paise']/100} vs Payable INR {dl_res['supplier_payable']['gross_payable_paise']/100} (Margin: INR {dl_res['gross_margin_paise']/100})")

    # Negative margin audit hold check: expensive supplier base
    neg_supplier_card = {"base_paise": 350000, "extra_km_paise": 2000}
    dl_neg = calculate_dual_ledger_duty(duty_params, client_card, neg_supplier_card)
    assert dl_neg["is_negative_margin"] is True
    assert dl_neg["maker_checker_audit_hold"] is True
    print(f"PASS: Negative gross margin ({dl_neg['gross_margin_paise']/100} INR) correctly triggered maker_checker_audit_hold")

    print("\n--- 2. SLA GOVERNANCE & TIER DEMOTION TESTS ---")
    # Breach test: late arrival 25 mins
    breach = evaluate_sla_breach({"reporting_delay_minutes": 25})
    assert breach and breach["breach_type"] == "LATE_ARRIVAL_15M"
    # Tier demotion test: OTA 89.5% with 3 breaches -> demote from TIER_1_PLATINUM to TIER_2_GOLD
    new_tier, demoted, reason = evaluate_tier_demotion("TIER_1_PLATINUM", 89.5, 3)
    assert demoted and new_tier == "TIER_2_GOLD"
    debit_note = generate_penalty_debit_note("ven_blueorbit", "duty_101", breach)
    assert debit_note["penalty_paise"] == 50000
    print(f"PASS: SLA breach triggered penalty INR {debit_note['penalty_inr']} & demoted tier to {new_tier} ({reason})")

    print("\n--- 3. STATUTORY WOMEN'S SAFETY & ALERTS TESTS ---")
    # Night window check
    assert is_night_shift_window("2026-10-27T22:30:00Z") is True
    assert is_night_shift_window("2026-10-27T14:30:00Z") is False

    # Night shift hard-lock: female last drop on logout trip without guard
    passengers = [{"name": "Rahul", "gender": "male"}, {"name": "Priya", "gender": "female"}]
    is_safe, err = validate_night_shift_safety("LOGOUT", passengers, "2026-10-27T23:00:00Z", guard_assigned=False)
    assert not is_safe and "SAFETY HARD-LOCK" in err
    print(f"PASS: Night shift female safety hard-lock triggered: {err}")

    # 3-Tier Safe reach escalation: IVR pressed '2' (emergency)
    esc_res = evaluate_safe_reach_escalation("2026-10-27T23:45:00Z", False, ivr_response="2")
    assert esc_res["p0_escalation_required"] is True
    assert esc_res["tier"] == "TIER_3_P0_ESCALATION_SUPERVISOR"
    print(f"PASS: 3-Tier Safe Reach escalated to P0 Command Center ({esc_res['status']})")

    # 16+ Telemetry alert: Overspeeding + Mock Location
    alerts = scan_telemetry_alerts({"speed_kmh": 105, "speed_limit_kmh": 80, "is_mock_location_detected": True})
    assert len(alerts) == 2
    assert any(a["alert_code"] == "OVERSPEEDING" for a in alerts)
    assert any(a["alert_code"] == "MOCK_LOCATION_DETECTED" for a in alerts)
    print("PASS: Telemetry stream detected OVERSPEEDING and MOCK_LOCATION_DETECTED")

    print("\n--- 4. GST E-INVOICING & TALLY PRIME BRIDGE TESTS ---")
    # Rent-a-Cab SAC 996601 RCM determination
    tax_rules = determine_gst_tax_structure("29AABCA1234F1Z1", "29AABCC5678K1Z2", supplier_is_corporate=False)
    assert tax_rules["hsn_sac"] == "996601"
    assert tax_rules["is_rcm_applicable"] is True
    print(f"PASS: GST Rent-a-Cab resolved SAC {tax_rules['hsn_sac']} with Reverse Charge (RCM={tax_rules['is_rcm_applicable']})")

    # IRP E-Invoice payload generation
    inv_data = {
        "invoice_number": "AXM-2026-8801",
        "supplier_gstin": "29AABCA1234F1Z1",
        "client_gstin": "29AABCC5678K1Z2",
        "total_amount_paise": 525000,
        "is_rcm_applicable": True,
    }
    e_inv = generate_irp_einvoice_payload(inv_data)
    assert len(e_inv["irn"]) == 64
    assert "https://einvoice1.gst.gov.in/qr" in e_inv["signed_qr_code"]
    print(f"PASS: Generated signed IRP E-Invoice with IRN: {e_inv['irn'][:16]}...")

    # Tally Prime XML export
    tally_xml = export_tally_prime_xml([{"invoice_number": "AXM-2026-8801", "client_name": "Test Client", "gross_amount_paise": 500000, "gst_amount_paise": 25000, "net_amount_paise": 525000}])
    assert "<ENVELOPE>" in tally_xml and "<VOUCHER VCHTYPE=\"Sales\"" in tally_xml
    print("PASS: Tally Prime XML generated with Sales Voucher envelopes")

    print("\n--- 5. REST API & DATABASE INTEGRATION TESTS ---")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    initialize_tristack_schema(conn)

    user = {"id": "usr_superadmin", "role": "vendor", "organization_id": "org_test"}

    # 3-Way Distance Fraud Audit Endpoint
    audit_req = {
        "duty_id": "duty_test_01",
        "odometer_start": 10000,
        "odometer_end": 10090,  # 90 km
        "raw_gps_crumb_km": 72.0,
        "snapped_route_km": 70.0,
    }
    audit_res = handle_tristack(conn, user, "POST", "/api/tri-stack/audits/distance", audit_req)
    assert audit_res["ok"] is True
    assert audit_res["distance_audit"]["is_fraud_flagged"] is True
    assert audit_res["distance_audit"]["audit_action"] == "BILLING_AUDIT_HOLD"
    print(f"PASS: 3-Way distance discrepancy of {audit_res['distance_audit']['discrepancy_pct']}% correctly flagged BILLING_AUDIT_HOLD")

    # Webhook logs & Replay
    wh_logs = handle_tristack(conn, user, "GET", "/api/tri-stack/webhooks/logs")
    assert wh_logs["count"] >= 4
    wh_id = wh_logs["items"][0]["id"]
    replay_res = handle_tristack(conn, user, "POST", f"/api/tri-stack/webhooks/{wh_id}/replay")
    assert replay_res["status"] == "REPLAY_DISPATCHED_SUCCESSFULLY"
    print(f"PASS: Webhook inspection retrieved {wh_logs['count']} integration events and replayed {wh_id}")

    print("\nALL TRI-STACK SPECIFICATION TESTS PASSED (16/16)")

if __name__ == "__main__":
    run_tests()
