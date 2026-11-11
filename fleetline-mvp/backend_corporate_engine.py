"""Axiom Corporate Engine Backend Controller & API Handler.

Unified REST API for:
1. Employee Band Management & Evaluation (cities, duty types, extended fallback, night shift window)
2. Automated Supplier Waterfall Allotment (queue ranking by tier, wallet share deficit, reliability)
3. Dynamic SLA & Timeout/Rejection Cascading
4. Automatic Tier Demotion on Reliability Score Breach
5. REA Dual-Entry Economic Accounting (balanced debit/credit journals & immutable events)
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlsplit

from backend_domain import DomainError, _assert_owned, _audit, _org, _serialize, _text, new_id, now_iso
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


def _req_text(payload: Dict[str, Any], key: str) -> str:
    val = _text(payload, key)
    if not val:
        raise DomainError(f"{key} is required", 400)
    return val


def initialize_corporate_engine_schema(conn: sqlite3.Connection) -> None:
    """Creates SQLite tables for Corporate Engine entities if they do not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS employee_bands (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            corporate_account_id TEXT,
            band_name TEXT NOT NULL,
            allowed_vehicle_groups TEXT NOT NULL DEFAULT '[]',
            extended_vehicle_groups TEXT NOT NULL DEFAULT '[]',
            allowed_duty_types TEXT NOT NULL DEFAULT '[]',
            allowed_cities TEXT NOT NULL DEFAULT '[]',
            base_city TEXT NOT NULL DEFAULT '',
            allow_custom_passengers INTEGER NOT NULL DEFAULT 0,
            enable_auto_allotment INTEGER NOT NULL DEFAULT 1,
            skip_approval_start_hour INTEGER,
            skip_approval_end_hour INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS supplier_waterfall_rules (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            corporate_account_id TEXT,
            supplier_id TEXT NOT NULL,
            supplier_name TEXT NOT NULL,
            city TEXT NOT NULL,
            vehicle_group TEXT NOT NULL,
            priority_tier INTEGER NOT NULL DEFAULT 1,
            target_allocation_pct REAL NOT NULL DEFAULT 100.0,
            current_month_share_pct REAL NOT NULL DEFAULT 0.0,
            acceptance_sla_mins INTEGER NOT NULL DEFAULT 20,
            compressed_sla_mins INTEGER NOT NULL DEFAULT 8,
            daily_cap_duties INTEGER NOT NULL DEFAULT 50,
            today_allotted_count INTEGER NOT NULL DEFAULT 0,
            reliability_score REAL NOT NULL DEFAULT 100.0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS supplier_waterfall_attempts (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            booking_id TEXT NOT NULL,
            supplier_id TEXT NOT NULL,
            supplier_name TEXT NOT NULL,
            attempt_sequence INTEGER NOT NULL DEFAULT 1,
            priority_tier INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'DISPATCHED_WAITING',
            dispatched_at TEXT NOT NULL,
            sla_expires_at TEXT NOT NULL,
            responded_at TEXT,
            rejection_reason TEXT,
            allotment_details TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rea_dualities (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            booking_id TEXT,
            duality_type TEXT NOT NULL DEFAULT 'DUAL_LEDGER_TRIP_FULFILLMENT',
            status TEXT NOT NULL DEFAULT 'BALANCED',
            total_receivable_amount REAL NOT NULL DEFAULT 0.0,
            total_payable_amount REAL NOT NULL DEFAULT 0.0,
            gross_margin_amount REAL NOT NULL DEFAULT 0.0,
            margin_pct REAL NOT NULL DEFAULT 0.0,
            journal_lines TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS corporate_shadow_evaluations (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            vendor_name TEXT NOT NULL,
            route_name TEXT NOT NULL,
            contracted_billed_inr REAL NOT NULL,
            axiom_audited_inr REAL NOT NULL,
            leakage_inr REAL NOT NULL,
            savings_pct REAL NOT NULL,
            reported_kms REAL NOT NULL DEFAULT 0.0,
            actual_gps_kms REAL NOT NULL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'EVALUATED_SHADOW',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def handle_corporate_engine(
    conn: sqlite3.Connection,
    user: Dict[str, Any],
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    remote_ip: str = "127.0.0.1",
) -> Optional[Dict[str, Any]]:
    """Handles corporate engine API routes: /api/corporate/..."""
    parsed = urlsplit(path)
    clean_path = parsed.path
    org_id = _org(user)

    if not clean_path.startswith("/api/corporate/"):
        return None

    # -------------------------------------------------------------------------
    # 1. Employee Bands
    # -------------------------------------------------------------------------
    if clean_path == "/api/corporate/bands":
        if method == "GET":
            cur = conn.execute(
                "SELECT * FROM employee_bands WHERE organization_id = ? ORDER BY band_name ASC",
                (org_id,),
            )
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                r["allowed_vehicle_groups"] = json.loads(r.get("allowed_vehicle_groups") or "[]")
                r["extended_vehicle_groups"] = json.loads(r.get("extended_vehicle_groups") or "[]")
                r["allowed_duty_types"] = json.loads(r.get("allowed_duty_types") or "[]")
                r["allowed_cities"] = json.loads(r.get("allowed_cities") or "[]")
                r["allow_custom_passengers"] = bool(r.get("allow_custom_passengers"))
                r["enable_auto_allotment"] = bool(r.get("enable_auto_allotment"))
            return {"items": rows}

        if method == "POST":
            data = payload or {}
            band_id = data.get("id") or new_id("band")
            now = now_iso()
            conn.execute(
                """
                INSERT OR REPLACE INTO employee_bands (
                    id, organization_id, corporate_account_id, band_name,
                    allowed_vehicle_groups, extended_vehicle_groups, allowed_duty_types,
                    allowed_cities, base_city, allow_custom_passengers, enable_auto_allotment,
                    skip_approval_start_hour, skip_approval_end_hour, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    band_id,
                    org_id,
                    data.get("corporate_account_id"),
                    _req_text(data, "band_name"),
                    json.dumps(data.get("allowed_vehicle_groups", [])),
                    json.dumps(data.get("extended_vehicle_groups", [])),
                    json.dumps(data.get("allowed_duty_types", [])),
                    json.dumps(data.get("allowed_cities", [])),
                    data.get("base_city", ""),
                    1 if data.get("allow_custom_passengers") else 0,
                    1 if data.get("enable_auto_allotment", True) else 0,
                    data.get("skip_approval_start_hour"),
                    data.get("skip_approval_end_hour"),
                    now,
                    now,
                ),
            )
            conn.commit()
            return {"status": "success", "id": band_id}

    # -------------------------------------------------------------------------
    # 2. Evaluate Booking Policy
    # -------------------------------------------------------------------------
    if clean_path == "/api/corporate/evaluate-booking" and method == "POST":
        data = payload or {}
        band_data = data.get("band", {})
        band = EmployeeBand(
            id=band_data.get("id", "default"),
            band_name=band_data.get("band_name", "Default"),
            allowed_vehicle_groups=band_data.get("allowed_vehicle_groups", ["SEDAN"]),
            extended_vehicle_groups=band_data.get("extended_vehicle_groups", []),
            allowed_duty_types=band_data.get("allowed_duty_types", []),
            allowed_cities=band_data.get("allowed_cities", []),
            allow_custom_passengers=bool(band_data.get("allow_custom_passengers")),
            enable_auto_allotment=bool(band_data.get("enable_auto_allotment", True)),
            skip_approval_start_hour=band_data.get("skip_approval_start_hour"),
            skip_approval_end_hour=band_data.get("skip_approval_end_hour"),
        )
        sla_data = data.get("sla", {})
        sla = CorporateAccountSLA(
            corporate_id=sla_data.get("corporate_id", "corp"),
            booking_lead_sla_mins=int(sla_data.get("booking_lead_sla_mins", 60)),
            cancellation_cutoff_sla_mins=int(sla_data.get("cancellation_cutoff_sla_mins", 120)),
            cancellation_fee_flat=float(sla_data.get("cancellation_fee_flat", 500.0)),
        )

        res = CorporateMobilityEngine.evaluate_booking_request(data.get("booking", {}), band, sla)
        return {
            "allowed": res.allowed,
            "status": res.status,
            "auto_allot_to_supplier": res.auto_allot_to_supplier,
            "resolved_vehicle_group": res.resolved_vehicle_group,
            "violations": res.violations,
        }

    # -------------------------------------------------------------------------
    # 3. Waterfall Routing Rules
    # -------------------------------------------------------------------------
    if clean_path == "/api/corporate/waterfall/rules":
        if method == "GET":
            cur = conn.execute(
                "SELECT * FROM supplier_waterfall_rules WHERE organization_id = ? ORDER BY priority_tier ASC, reliability_score DESC",
                (org_id,),
            )
            return {"items": [dict(r) for r in cur.fetchall()]}

        if method == "POST":
            data = payload or {}
            rule_id = data.get("id") or new_id("wrule")
            now = now_iso()
            conn.execute(
                """
                INSERT OR REPLACE INTO supplier_waterfall_rules (
                    id, organization_id, corporate_account_id, supplier_id, supplier_name,
                    city, vehicle_group, priority_tier, target_allocation_pct, current_month_share_pct,
                    acceptance_sla_mins, compressed_sla_mins, daily_cap_duties, today_allotted_count,
                    reliability_score, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule_id,
                    org_id,
                    data.get("corporate_account_id"),
                    _req_text(data, "supplier_id"),
                    _req_text(data, "supplier_name"),
                    data.get("city", ""),
                    data.get("vehicle_group", ""),
                    int(data.get("priority_tier", 1)),
                    float(data.get("target_allocation_pct", 100.0)),
                    float(data.get("current_month_share_pct", 0.0)),
                    int(data.get("acceptance_sla_mins", 20)),
                    int(data.get("compressed_sla_mins", 8)),
                    int(data.get("daily_cap_duties", 50)),
                    int(data.get("today_allotted_count", 0)),
                    float(data.get("reliability_score", 100.0)),
                    1 if data.get("is_active", True) else 0,
                    now,
                    now,
                ),
            )
            conn.commit()
            return {"status": "success", "id": rule_id}

    # -------------------------------------------------------------------------
    # 4. Waterfall Queue Computation
    # -------------------------------------------------------------------------
    if clean_path == "/api/corporate/waterfall/queue" and method == "POST":
        data = payload or {}
        cur = conn.execute(
            """
            SELECT * FROM supplier_waterfall_rules
            WHERE organization_id = ? AND is_active = 1
            """,
            (org_id,),
        )
        db_rules = [dict(r) for r in cur.fetchall()]
        rules = [
            SupplierRoutingRule(
                rule_id=r["id"],
                corporate_id=r.get("corporate_account_id", ""),
                supplier_id=r["supplier_id"],
                supplier_name=r["supplier_name"],
                city=r["city"],
                vehicle_group=r["vehicle_group"],
                priority_tier=int(r["priority_tier"]),
                target_allocation_pct=float(r["target_allocation_pct"]),
                current_month_share_pct=float(r["current_month_share_pct"]),
                acceptance_sla_mins=int(r["acceptance_sla_mins"]),
                compressed_sla_mins=int(r["compressed_sla_mins"]),
                daily_cap_duties=int(r["daily_cap_duties"]),
                today_allotted_count=int(r["today_allotted_count"]),
                reliability_score=float(r["reliability_score"]),
                is_active=bool(r["is_active"]),
            )
            for r in db_rules
        ]
        already_tried = set(data.get("already_tried_supplier_ids", []))
        queue = AutomatedSupplierAllotmentEngine.build_waterfall_queue(rules, already_tried)
        return {
            "queue": [
                {
                    "rule_id": q.rule_id,
                    "supplier_id": q.supplier_id,
                    "supplier_name": q.supplier_name,
                    "priority_tier": q.priority_tier,
                    "target_allocation_pct": q.target_allocation_pct,
                    "current_month_share_pct": q.current_month_share_pct,
                    "share_deficit": round(q.target_allocation_pct - q.current_month_share_pct, 2),
                    "reliability_score": q.reliability_score,
                }
                for q in queue
            ]
        }

    # -------------------------------------------------------------------------
    # 5. Demotion Evaluation
    # -------------------------------------------------------------------------
    if clean_path == "/api/corporate/demotion/evaluate" and method == "POST":
        data = payload or {}
        supplier_id = _req_text(data, "supplier_id")
        cur = conn.execute(
            "SELECT * FROM supplier_waterfall_rules WHERE organization_id = ? AND supplier_id = ?",
            (org_id, supplier_id),
        )
        row = cur.fetchone()
        if not row:
            raise DomainError(f"Supplier rule for {supplier_id} not found", 404)
        rule = dict(row)
        score = float(rule["reliability_score"])
        tier = int(rule["priority_tier"])

        penalty_type = data.get("penalty_type")
        if penalty_type:
            score = AutomaticTierDemotionEngine.apply_penalty(score, penalty_type)
            conn.execute(
                "UPDATE supplier_waterfall_rules SET reliability_score = ? WHERE id = ?",
                (score, rule["id"]),
            )

        demotion_eval = AutomaticTierDemotionEngine.evaluate_and_execute_demotion(
            supplier_id, rule["supplier_name"], tier, score, recent_timeouts=data.get("recent_timeouts", 1)
        )

        if demotion_eval.get("demotion_triggered"):
            conn.execute(
                "UPDATE supplier_waterfall_rules SET priority_tier = 3 WHERE id = ?",
                (rule["id"],),
            )
        conn.commit()

        return {
            "updated_score": score,
            "demotion": demotion_eval,
        }

    # -------------------------------------------------------------------------
    # 6. REA Accounting Duality & Journals
    # -------------------------------------------------------------------------
    if clean_path == "/api/corporate/rea/duality":
        if method == "POST":
            data = payload or {}
            booking_id = _req_text(data, "booking_id")
            corp = ReaAgent(
                id=data.get("corporate_id", "corp"),
                name=data.get("corporate_name", "Corporate Client"),
                role="CORPORATE_CLIENT",
                gstin=data.get("corporate_gstin", ""),
            )
            supp = ReaAgent(
                id=data.get("supplier_id", "supp"),
                name=data.get("supplier_name", "Supplier Vendor"),
                role="SUPPLIER_VENDOR",
                gstin=data.get("supplier_gstin", ""),
            )
            plat = ReaAgent(id="plat", name="Axiom Fleet", role="PLATFORM_OPERATOR")

            result = ReaAccountingEngine.generate_duality_and_journal(
                booking_id=booking_id,
                corporate_agent=corp,
                supplier_agent=supp,
                platform_agent=plat,
                taxable_ar=float(data.get("taxable_ar", 0.0)),
                gst_ar=float(data.get("gst_ar", 0.0)),
                taxable_ap=float(data.get("taxable_ap", 0.0)),
                gst_ap=float(data.get("gst_ap", 0.0)),
                tolls=float(data.get("tolls", 0.0)),
            )

            now = now_iso()
            conn.execute(
                """
                INSERT OR REPLACE INTO rea_dualities (
                    id, organization_id, booking_id, duality_type, status,
                    total_receivable_amount, total_payable_amount, gross_margin_amount,
                    margin_pct, journal_lines, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result["duality_id"],
                    org_id,
                    booking_id,
                    "DUAL_LEDGER_TRIP_FULFILLMENT",
                    result["status"],
                    result["total_receivable"],
                    result["total_payable"],
                    result["gross_margin"],
                    result["margin_pct"],
                    json.dumps(result["journal_lines"]),
                    now,
                ),
            )
            conn.commit()
            return result

        if method == "GET":
            cur = conn.execute(
                "SELECT * FROM rea_dualities WHERE organization_id = ? ORDER BY created_at DESC",
                (org_id,),
            )
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                r["journal_lines"] = json.loads(r.get("journal_lines") or "[]")
            return {"items": rows}

    # -------------------------------------------------------------------------
    # 6. Shadow Evaluation Mode (Zero-Disruption Parallel Vendor Audit)
    # -------------------------------------------------------------------------
    if clean_path == "/api/corporate/shadow-evaluation":
        if method == "POST":
            data = payload or {}
            eval_id = new_id("shd")
            now = now_iso()
            vendor = str(data.get("vendor_name") or "Contracted Vendor Partner")
            route_name = str(data.get("route_name") or "Airport Corporate Transfer")
            contracted_billed = float(data.get("contracted_vendor_billed_inr", 2500.0))
            rep_kms = float(data.get("reported_kms", 55.0))
            gps_kms = float(data.get("actual_gps_kms", 42.0))
            toll_claimed = float(data.get("toll_claimed_inr", 150.0))
            genuine_toll = float(data.get("genuine_toll_inr", toll_claimed if toll_claimed <= 150.0 else 120.0))

            # Axiom Algorithmic Tariff Benchmark (Tier-1 Sedan rate: base ₹800/40km + ₹18/extra km + toll)
            base_fare = 800.0
            extra_km = max(0.0, gps_kms - 40.0)
            extra_km_charge = extra_km * 18.0
            axiom_audited = round(base_fare + extra_km_charge + genuine_toll, 2)
            leakage = max(0.0, round(contracted_billed - axiom_audited, 2))
            savings_pct = round((leakage / contracted_billed) * 100.0, 1) if contracted_billed > 0 else 0.0

            conn.execute(
                """
                INSERT INTO corporate_shadow_evaluations (
                    id, organization_id, vendor_name, route_name,
                    contracted_billed_inr, axiom_audited_inr, leakage_inr,
                    savings_pct, reported_kms, actual_gps_kms, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'EVALUATED_SHADOW', ?)
                """,
                (
                    eval_id,
                    org_id,
                    vendor,
                    route_name,
                    contracted_billed,
                    axiom_audited,
                    leakage,
                    savings_pct,
                    rep_kms,
                    gps_kms,
                    now,
                ),
            )
            conn.commit()

            return {
                "ok": True,
                "shadow_evaluation_id": eval_id,
                "vendor_name": vendor,
                "route_name": route_name,
                "contracted_vendor_billed_inr": contracted_billed,
                "axiom_audited_inr": axiom_audited,
                "leakage_prevented_inr": leakage,
                "savings_pct": savings_pct,
                "reported_kms": rep_kms,
                "actual_gps_kms": gps_kms,
                "mode": "PARALLEL_SHADOW_EVALUATION",
                "migration_risk": "ZERO_DISRUPTION",
                "evaluated_at": now,
            }

        if method == "GET":
            cur = conn.execute(
                "SELECT * FROM corporate_shadow_evaluations WHERE organization_id = ? ORDER BY created_at DESC",
                (org_id,),
            )
            return {"items": [dict(r) for r in cur.fetchall()]}

    if clean_path == "/api/corporate/shadow-evaluation/summary":
        if method == "GET":
            cur = conn.execute(
                """
                SELECT
                    count(*) as total_audited,
                    COALESCE(sum(contracted_billed_inr), 0.0) as total_vendor_billed,
                    COALESCE(sum(axiom_audited_inr), 0.0) as total_axiom_audited,
                    COALESCE(sum(leakage_inr), 0.0) as total_leakage_prevented
                FROM corporate_shadow_evaluations
                WHERE organization_id = ?
                """,
                (org_id,),
            )
            agg = dict(cur.fetchone() or {})
            total_audited = agg.get("total_audited", 0)
            total_billed = agg.get("total_vendor_billed", 0.0)
            total_leakage = agg.get("total_leakage_prevented", 0.0)
            avg_savings = round((total_leakage / total_billed) * 100.0, 1) if total_billed > 0 else 0.0

            cur_items = conn.execute(
                "SELECT * FROM corporate_shadow_evaluations WHERE organization_id = ? ORDER BY created_at DESC LIMIT 20",
                (org_id,),
            )
            return {
                "ok": True,
                "total_trips_audited": total_audited,
                "total_vendor_billed_inr": round(total_billed, 2),
                "total_axiom_audited_inr": round(agg.get("total_axiom_audited", 0.0), 2),
                "total_leakage_prevented_inr": round(total_leakage, 2),
                "average_savings_pct": avg_savings,
                "migration_risk": "ZERO_DISRUPTION",
                "items": [dict(r) for r in cur_items.fetchall()],
            }

    return None
