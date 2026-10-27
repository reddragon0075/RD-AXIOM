"""Axiom Mobility (Fleetline) Tri-Stack REST API Controller.

Provides REST interfaces for:
1. Unified Tariff & Dual-Ledger Resolver
2. Partner Network SLA Governance & Tier Demotion
3. Statutory Women's Safety & Live Telemetry Rules
4. GST E-Invoicing & Tally Prime Bridge
5. 3-Way Distance Audit & Anti-Fraud Inspection
6. Admin Webhook & Integration Audit Logs
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlsplit

from backend_domain import DomainError, _audit, _org, _serialize, _text, new_id, now_iso
from erp_gst_bridge import determine_gst_tax_structure, export_tally_prime_xml, generate_irp_einvoice_payload
from safety_compliance import evaluate_safe_reach_escalation, scan_telemetry_alerts, validate_night_shift_safety
from sla_governance import evaluate_sla_breach, evaluate_tier_demotion, generate_penalty_debit_note
from tariff_engine import calculate_dual_ledger_duty

TRISTACK_PREFIX = "/api/tri-stack"


def initialize_tristack_schema(conn: sqlite3.Connection) -> None:
    """Initializes local tables for Tri-Stack features."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tristack_webhook_logs (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            direction TEXT NOT NULL CHECK(direction IN ('INBOUND', 'OUTBOUND')),
            service_name TEXT NOT NULL,
            endpoint_url TEXT NOT NULL,
            http_method TEXT NOT NULL DEFAULT 'POST',
            request_payload_json TEXT NOT NULL DEFAULT '{}',
            response_payload_json TEXT NOT NULL DEFAULT '{}',
            http_status INTEGER NOT NULL DEFAULT 200,
            latency_ms INTEGER NOT NULL DEFAULT 120,
            retry_count INTEGER NOT NULL DEFAULT 0,
            is_dead_letter INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tristack_sla_breaches (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            vendor_id TEXT NOT NULL,
            vendor_name TEXT NOT NULL,
            duty_id TEXT,
            breach_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            penalty_paise INTEGER NOT NULL DEFAULT 0,
            debit_note_reference TEXT,
            occurred_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tristack_partner_sla_profiles (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            vendor_id TEXT NOT NULL UNIQUE,
            vendor_name TEXT NOT NULL,
            current_tier TEXT NOT NULL DEFAULT 'TIER_1_PLATINUM',
            rolling_ota_pct REAL NOT NULL DEFAULT 96.5,
            active_breaches_7d INTEGER NOT NULL DEFAULT 0,
            total_trips_allocated INTEGER NOT NULL DEFAULT 120,
            trips_completed INTEGER NOT NULL DEFAULT 118,
            total_penalties_paise INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            updated_at TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tristack_distance_audits (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            duty_id TEXT NOT NULL UNIQUE,
            odometer_start INTEGER NOT NULL,
            odometer_end INTEGER NOT NULL,
            odometer_delta_km REAL NOT NULL,
            raw_gps_crumb_km REAL NOT NULL,
            snapped_route_km REAL NOT NULL,
            discrepancy_pct REAL NOT NULL,
            is_fraud_flagged INTEGER NOT NULL DEFAULT 0,
            fastag_toll_deductions_paise INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()

    # Seed partner SLA profiles if empty
    cur = conn.execute("SELECT count(*) FROM tristack_partner_sla_profiles")
    if cur.fetchone()[0] == 0:
        now = now_iso()
        sample_partners = [
            ("sla_p1", "org_sample", "ven_apex", "Apex Logistics Bangalore", "TIER_1_PLATINUM", 98.2, 0, 142, 141, 0, "ACTIVE", now),
            ("sla_p2", "org_sample", "ven_southcity", "South City Cabs & Fleet", "TIER_2_GOLD", 91.5, 3, 98, 94, 150000, "DEMOTED_WARNING", now),
            ("sla_p3", "org_sample", "ven_primeshuttle", "Prime Shuttle Services", "TIER_3_SILVER", 87.4, 6, 85, 79, 320000, "PROBATION", now),
        ]
        conn.executemany(
            """
            INSERT INTO tristack_partner_sla_profiles (
                id, organization_id, vendor_id, vendor_name, current_tier,
                rolling_ota_pct, active_breaches_7d, total_trips_allocated,
                trips_completed, total_penalties_paise, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            sample_partners,
        )
        conn.commit()

    # Seed distance audits if empty
    cur = conn.execute("SELECT count(*) FROM tristack_distance_audits")
    if cur.fetchone()[0] == 0:
        now = now_iso()
        sample_audits = [
            ("da_101", "org_sample", "duty_ecity_991", 14200, 14285, 85.0, 72.4, 71.8, 18.38, 1, 17000, now),
            ("da_102", "org_sample", "duty_whitefield_402", 22100, 22142, 42.0, 41.5, 41.2, 1.94, 0, 9500, now),
            ("da_103", "org_sample", "duty_airport_778", 38000, 38048, 48.0, 47.6, 47.2, 1.69, 0, 11500, now),
        ]
        conn.executemany(
            """
            INSERT INTO tristack_distance_audits (
                id, organization_id, duty_id, odometer_start, odometer_end,
                odometer_delta_km, raw_gps_crumb_km, snapped_route_km,
                discrepancy_pct, is_fraud_flagged, fastag_toll_deductions_paise, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            sample_audits,
        )
        conn.commit()

    # Seed baseline webhook logs if empty
    cur = conn.execute("SELECT count(*) FROM tristack_webhook_logs")
    if cur.fetchone()[0] == 0:
        now = now_iso()
        sample_logs = [
            (
                "wh_101",
                "org_sample",
                "OUTBOUND",
                "Exotel Masked Telephony",
                "https://api.exotel.com/v1/Accounts/call-mask",
                "POST",
                json.dumps({"driver_phone": "+919845011223", "passenger_phone": "+919845099887", "virtual_did": "+918047192837"}),
                json.dumps({"Call": {"Sid": "call_99281a", "Status": "in-progress"}}),
                200,
                145,
                0,
                0,
                None,
                now,
            ),
            (
                "wh_102",
                "org_sample",
                "INBOUND",
                "NETC FASTag NPCI",
                "https://api.axiomfleet.in/api/v1/telemetry/fastag",
                "POST",
                json.dumps({"tag_id": "34161FA8203281", "vehicle_no": "KA-01-MJ-5544", "toll_plaza": "Electronic City Toll", "amount_inr": 85.0}),
                json.dumps({"status": "matched", "reconciled_duty_id": "duty_active_1"}),
                200,
                82,
                0,
                0,
                None,
                now,
            ),
            (
                "wh_103",
                "org_sample",
                "OUTBOUND",
                "IRP NIC E-Invoice",
                "https://einvoice1.gst.gov.in/api/v1/irn/generate",
                "POST",
                json.dumps({"Version": "1.1", "DocDtls": {"Typ": "INV", "No": "AXM-2026-901"}}),
                json.dumps({"Status": 1, "Data": {"Irn": "f9182a938c827361a9928172c728192837", "AckNo": "112699281721"}}),
                200,
                320,
                0,
                0,
                None,
                now,
            ),
            (
                "wh_104",
                "org_sample",
                "OUTBOUND",
                "WhatsApp Business Cloud API",
                "https://graph.facebook.com/v19.0/messages",
                "POST",
                json.dumps({"messaging_product": "whatsapp", "to": "+919845011223", "type": "template", "template": {"name": "trip_assigned"}}),
                json.dumps({"error": {"message": "Service timeout after 5000ms", "code": 504}}),
                504,
                5012,
                2,
                1,
                "HTTP 504 Gateway Timeout: queued in DLQ for automated retry",
                now,
            ),
        ]
        conn.executemany(
            """
            INSERT INTO tristack_webhook_logs (
                id, organization_id, direction, service_name, endpoint_url,
                http_method, request_payload_json, response_payload_json,
                http_status, latency_ms, retry_count, is_dead_letter,
                error_message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            sample_logs,
        )
        conn.commit()


def handle_tristack(
    conn: sqlite3.Connection,
    user: Dict[str, Any],
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    remote_ip: str = "127.0.0.1",
) -> Optional[Dict[str, Any]]:
    """Handles Tri-Stack REST API endpoints."""
    clean_path = urlsplit(path).path

    if not clean_path.startswith(TRISTACK_PREFIX):
        return None

    # 1. Unified Tariff & Dual-Ledger Calculation
    if clean_path == "/api/tri-stack/tariff/calculate" and method == "POST":
        data = payload or {}
        duty_params = data.get("duty_params", {})
        client_rate_card = data.get("client_rate_card", {})
        supplier_rate_card = data.get("supplier_rate_card", {})
        calc = calculate_dual_ledger_duty(duty_params, client_rate_card, supplier_rate_card)
        return {"ok": True, "calculation": calc}

    # 2. Partner Network SLA Evaluation & Tier Demotion
    if clean_path == "/api/tri-stack/sla/evaluate" and method == "POST":
        data = payload or {}
        duty_evidence = data.get("duty_evidence", {})
        breach = evaluate_sla_breach(duty_evidence)
        vendor_tier = data.get("current_tier", "TIER_2_GOLD")
        ota_pct = float(data.get("rolling_ota_pct", 91.5))
        breaches_7d = int(data.get("active_breaches_7d", 3))

        new_tier, demoted, reason = evaluate_tier_demotion(vendor_tier, ota_pct, breaches_7d)
        debit_note = None
        if breach:
            debit_note = generate_penalty_debit_note(data.get("vendor_id", "ven_sample"), data.get("duty_id", "duty_sample"), breach)
            conn.execute(
                """
                INSERT INTO tristack_sla_breaches (
                    id, organization_id, vendor_id, vendor_name, duty_id,
                    breach_type, severity, penalty_paise, debit_note_reference,
                    occurred_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("breach"),
                    _org(user),
                    data.get("vendor_id", "ven_sample"),
                    data.get("vendor_name", "Sample Vendor Partner"),
                    data.get("duty_id", "duty_sample"),
                    breach["breach_type"],
                    breach["severity"],
                    breach["penalty_paise"],
                    debit_note["debit_note_reference"],
                    now_iso(),
                    now_iso(),
                ),
            )
            conn.commit()

        return {
            "ok": True,
            "has_breach": breach is not None,
            "breach": breach,
            "debit_note": debit_note,
            "tier_evaluation": {
                "previous_tier": vendor_tier,
                "current_tier": new_tier,
                "tier_demoted": demoted,
                "reason": reason,
            },
        }

    # 3. Statutory Women's Safety & Safe-Reach Escalation
    if clean_path == "/api/tri-stack/safety/validate" and method == "POST":
        data = payload or {}
        trip_type = data.get("trip_type", "LOGOUT")
        passengers = data.get("passengers", [])
        sched_time = data.get("scheduled_time", now_iso())
        has_guard = bool(data.get("guard_assigned", False))

        is_valid, err_msg = validate_night_shift_safety(trip_type, passengers, sched_time, has_guard)
        safe_reach_res = None
        if data.get("drop_time_iso"):
            safe_reach_res = evaluate_safe_reach_escalation(
                data["drop_time_iso"],
                bool(data.get("safe_reach_confirmed", False)),
                data.get("ivr_response"),
            )

        telemetry_alerts = scan_telemetry_alerts(data.get("telemetry_packet", {}))

        return {
            "ok": True,
            "safety_hard_lock_cleared": is_valid,
            "hard_lock_error": err_msg,
            "safe_reach": safe_reach_res,
            "active_telemetry_alerts": telemetry_alerts,
        }

    # 4. GST Rent-a-Cab E-Invoicing & Tally Prime
    if clean_path == "/api/tri-stack/e-invoice/generate" and method == "POST":
        data = payload or {}
        supplier_gst = data.get("supplier_gstin", "29AABCA1234F1Z1")
        client_gst = data.get("client_gstin", "29AABCC5678K1Z2")
        tax_rules = determine_gst_tax_structure(supplier_gst, client_gst, bool(data.get("supplier_is_corporate", False)))
        e_inv = generate_irp_einvoice_payload({**data, "is_rcm_applicable": tax_rules["is_rcm_applicable"]})
        return {
            "ok": True,
            "tax_rules": tax_rules,
            "e_invoice": e_inv,
        }

    if clean_path == "/api/tri-stack/tally/export" and method == "POST":
        data = payload or {}
        invoices = data.get("invoices", [])
        if not invoices:
            invoices = [
                {
                    "invoice_number": "AXM-2026-101",
                    "client_name": "Infosys BPM Logistics",
                    "gross_amount_paise": 4500000,
                    "gst_amount_paise": 225000,
                    "net_amount_paise": 4725000,
                }
            ]
        xml_output = export_tally_prime_xml(invoices)
        return {
            "ok": True,
            "format": "XML",
            "filename": f"Tally_Vouchers_{int(dt.datetime.now().timestamp())}.xml",
            "xml": xml_output,
        }

    # 5. 3-Way Distance Audit & Anti-Fraud Inspection
    if clean_path == "/api/tri-stack/audits/distance" and method == "POST":
        data = payload or {}
        start_odo = int(data.get("odometer_start", 12000))
        end_odo = int(data.get("odometer_end", 12085))
        delta_odo = end_odo - start_odo
        gps_km = float(data.get("raw_gps_crumb_km", 72.4))
        snapped_km = float(data.get("snapped_route_km", 71.8))

        discrepancy_pct = round(((delta_odo - snapped_km) / snapped_km) * 100.0, 2) if snapped_km > 0 else 0.0
        # Fraud flag if odo exceeds snapped by > 10% or > 5km
        is_fraud = discrepancy_pct > 10.0 or (delta_odo - snapped_km) > 5.0
        fastag_deductions = int(data.get("fastag_toll_deductions_paise", 17000))

        audit_record = {
            "duty_id": data.get("duty_id", "duty_sample_audit"),
            "odometer_start": start_odo,
            "odometer_end": end_odo,
            "odometer_delta_km": delta_odo,
            "raw_gps_crumb_km": gps_km,
            "snapped_route_km": snapped_km,
            "discrepancy_pct": discrepancy_pct,
            "is_fraud_flagged": is_fraud,
            "audit_action": "BILLING_AUDIT_HOLD" if is_fraud else "VERIFIED_PASS",
            "fastag_toll_deductions_paise": fastag_deductions,
            "fastag_inr": round(fastag_deductions / 100.0, 2),
        }
        return {"ok": True, "distance_audit": audit_record}

    if clean_path == "/api/tri-stack/audits/distance" and method == "GET":
        cur = conn.execute("SELECT * FROM tristack_distance_audits ORDER BY created_at DESC LIMIT 50")
        rows = [dict(r) for r in cur.fetchall()]
        return {"ok": True, "items": rows, "count": len(rows)}

    if clean_path == "/api/tri-stack/sla/scorecard" and method == "GET":
        cur_partners = conn.execute("SELECT * FROM tristack_partner_sla_profiles ORDER BY rolling_ota_pct DESC")
        partners = [dict(r) for r in cur_partners.fetchall()]
        cur_breaches = conn.execute("SELECT * FROM tristack_sla_breaches ORDER BY created_at DESC LIMIT 30")
        breaches = [dict(r) for r in cur_breaches.fetchall()]
        return {"ok": True, "partners": partners, "breaches": breaches}

    if clean_path == "/api/tri-stack/billing/dual-ledger-queue" and method == "GET":
        # Pre-calculated maker-checker dual ledger items
        queue = [
            {
                "id": "dlq_001",
                "duty_id": "duty_ecity_991",
                "client_name": "Infosys BPM Logistics",
                "supplier_name": "South City Cabs & Fleet",
                "service_mode": "HR_KM_SLAB",
                "client_slab": "4Hr / 40Km",
                "actual_hours": 7.5,
                "actual_km": 75.0,
                "client_gross_paise": 303000,
                "supplier_payable_paise": 261000,
                "gross_margin_paise": 42000,
                "margin_pct": 13.86,
                "maker_checker_audit_hold": False,
                "distance_audit_status": "BILLING_AUDIT_HOLD",
                "distance_discrepancy_pct": 18.38,
                "gst_rcm": True,
                "status": "PENDING_AUDIT_CHECK",
            },
            {
                "id": "dlq_002",
                "duty_id": "duty_whitefield_402",
                "client_name": "Wipro Technologies",
                "supplier_name": "Apex Logistics Bangalore",
                "service_mode": "RADIAL_ZONE_RING",
                "client_slab": "Zone Ring 2 (Outer Ring Road)",
                "actual_hours": 3.0,
                "actual_km": 42.0,
                "client_gross_paise": 185000,
                "supplier_payable_paise": 155000,
                "gross_margin_paise": 30000,
                "margin_pct": 16.22,
                "maker_checker_audit_hold": False,
                "distance_audit_status": "VERIFIED_PASS",
                "distance_discrepancy_pct": 1.94,
                "gst_rcm": True,
                "status": "APPROVED",
            },
            {
                "id": "dlq_003",
                "duty_id": "duty_airport_778",
                "client_name": "Accenture Mobility",
                "supplier_name": "Prime Shuttle Services",
                "service_mode": "OUTSTATION_CALENDAR_DAY",
                "client_slab": "Mysuru Day Package",
                "actual_hours": 12.0,
                "actual_km": 310.0,
                "client_gross_paise": 420000,
                "supplier_payable_paise": 445000,
                "gross_margin_paise": -25000,
                "margin_pct": -5.95,
                "maker_checker_audit_hold": True,
                "distance_audit_status": "VERIFIED_PASS",
                "distance_discrepancy_pct": 1.69,
                "gst_rcm": False,
                "status": "NEGATIVE_MARGIN_BLOCKED",
            },
        ]
        return {"ok": True, "items": queue, "count": len(queue)}

    # 6. Admin Webhook & Event Integration Logs
    if clean_path == "/api/tri-stack/webhooks/logs" and method == "GET":
        cur = conn.execute("SELECT * FROM tristack_webhook_logs ORDER BY created_at DESC LIMIT 50")
        rows = [dict(r) for r in cur.fetchall()]
        return {"ok": True, "items": rows, "count": len(rows)}

    if clean_path.startswith("/api/tri-stack/webhooks/") and clean_path.endswith("/replay") and method == "POST":
        wh_id = clean_path.split("/")[4]
        cur = conn.execute("SELECT * FROM tristack_webhook_logs WHERE id = ?", (wh_id,))
        row = cur.fetchone()
        if not row:
            raise DomainError(404, f"Webhook log {wh_id} not found", "not_found")
        w = dict(row)
        now = now_iso()
        # Simulate replay execution
        conn.execute(
            """
            UPDATE tristack_webhook_logs
            SET retry_count = retry_count + 1,
                http_status = 200,
                is_dead_letter = 0,
                error_message = NULL,
                response_payload_json = ?
            WHERE id = ?
            """,
            (json.dumps({"replayed_at": now, "status": "success", "replay_ack": "OK"}), wh_id),
        )
        conn.commit()
        return {
            "ok": True,
            "webhook_id": wh_id,
            "service_name": w["service_name"],
            "status": "REPLAY_DISPATCHED_SUCCESSFULLY",
            "replayed_at": now,
        }

    return None
