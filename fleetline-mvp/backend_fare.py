"""Axiom Fleet Fare Engine Backend Controller & Tariff Rule Manager.

Provides REST API endpoints for:
1. Rate Card & Tariff Rule Management (4-Tier Waterfall)
2. Interactive Fare Calculation (Local, Outstation, Airport, Point-to-Point)
3. Dual-Ledger Settlement (Customer Receivable vs Supplier Payable + Net Duty P&L)
4. Dynamic Duty Fare Recalculation with Auto-Slab Optimization
"""

from __future__ import annotations

import datetime
import json
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from backend_domain import DomainError, _assert_owned, _audit, _org, _serialize, _text, new_id, now_iso

try:
    from .fare_engine import (
        FARE_ENGINE_VERSION,
        FareError,
        calculate_dual_ledger_settlement,
        calculate_fare,
        calculate_optimal_local_fare,
    )
    from .fare_resolver import (
        TIER_LABELS,
        WATERFALL_RATE_RESOLUTION_SQL,
        resolve_billed_vehicle_group,
        resolve_rate_card_context,
    )
except (ImportError, ValueError):
    from fare_engine import (
        FARE_ENGINE_VERSION,
        FareError,
        calculate_dual_ledger_settlement,
        calculate_fare,
        calculate_optimal_local_fare,
    )
    from fare_resolver import (
        TIER_LABELS,
        WATERFALL_RATE_RESOLUTION_SQL,
        resolve_billed_vehicle_group,
        resolve_rate_card_context,
    )


STANDARD_PRESETS = {
    "vehicle_groups": [
        {"id": "HATCHBACK", "name": "Hatchback (WagonR, Swift)", "default_fuel": "petrol"},
        {"id": "SEDAN", "name": "Standard Sedan (Dzire, Etios)", "default_fuel": "diesel"},
        {"id": "EXECUTIVE_SEDAN", "name": "Executive Sedan (Ciaz, City)", "default_fuel": "petrol"},
        {"id": "SUV", "name": "SUV (Innova Crysta, Ertiga)", "default_fuel": "diesel"},
        {"id": "LUXURY", "name": "Luxury (Camry, Mercedes E-Class)", "default_fuel": "petrol"},
        {"id": "TEMPO", "name": "Tempo Traveller (12/17 Seater)", "default_fuel": "diesel"},
    ],
    "sample_rules": [
        # Local Sedan Slabs
        {
            "fare_mode": "local",
            "vehicle_group_id": "SEDAN",
            "package_name": "4Hr 40Km",
            "package_minutes": 240,
            "included_km": 40,
            "base_paise": 1400_00,
            "extra_km_paise": 18_00,
            "extra_hour_paise": 200_00,
            "grace_period_minutes": 15,
            "slab_switch_mode": "UPGRADE_ONLY",
            "tax_rate_bps": 500,
        },
        {
            "fare_mode": "local",
            "vehicle_group_id": "SEDAN",
            "package_name": "8Hr 80Km",
            "package_minutes": 480,
            "included_km": 80,
            "base_paise": 2400_00,
            "extra_km_paise": 18_00,
            "extra_hour_paise": 200_00,
            "grace_period_minutes": 15,
            "slab_switch_mode": "UPGRADE_ONLY",
            "tax_rate_bps": 500,
        },
        {
            "fare_mode": "local",
            "vehicle_group_id": "SEDAN",
            "package_name": "12Hr 120Km",
            "package_minutes": 720,
            "included_km": 120,
            "base_paise": 3400_00,
            "extra_km_paise": 18_00,
            "extra_hour_paise": 200_00,
            "grace_period_minutes": 15,
            "slab_switch_mode": "UPGRADE_ONLY",
            "tax_rate_bps": 500,
        },
        # Local SUV Slabs
        {
            "fare_mode": "local",
            "vehicle_group_id": "SUV",
            "package_name": "4Hr 40Km",
            "package_minutes": 240,
            "included_km": 40,
            "base_paise": 2200_00,
            "extra_km_paise": 24_00,
            "extra_hour_paise": 300_00,
            "grace_period_minutes": 15,
            "slab_switch_mode": "UPGRADE_ONLY",
            "tax_rate_bps": 500,
        },
        {
            "fare_mode": "local",
            "vehicle_group_id": "SUV",
            "package_name": "8Hr 80Km",
            "package_minutes": 480,
            "included_km": 80,
            "base_paise": 3600_00,
            "extra_km_paise": 24_00,
            "extra_hour_paise": 300_00,
            "grace_period_minutes": 15,
            "slab_switch_mode": "UPGRADE_ONLY",
            "tax_rate_bps": 500,
        },
        # Outstation Sedan
        {
            "fare_mode": "outstation",
            "vehicle_group_id": "SEDAN",
            "package_name": "Outstation Roundtrip (250km/day min)",
            "daily_min_km": 250,
            "extra_km_paise": 15_00,
            "driver_allowance_day_paise": 400_00,
            "driver_allowance_night_paise": 300_00,
            "tax_rate_bps": 500,
        },
        # Outstation SUV
        {
            "fare_mode": "outstation",
            "vehicle_group_id": "SUV",
            "package_name": "Outstation Roundtrip (300km/day min)",
            "daily_min_km": 300,
            "extra_km_paise": 22_00,
            "driver_allowance_day_paise": 500_00,
            "driver_allowance_night_paise": 400_00,
            "tax_rate_bps": 500,
        },
        # Airport Sedan
        {
            "fare_mode": "airport",
            "vehicle_group_id": "SEDAN",
            "package_name": "Airport Fixed Transfer",
            "base_paise": 1400_00,
            "free_waiting_minutes": 45,
            "waiting_paise_per_hour": 200_00,
            "tax_rate_bps": 500,
        },
    ],
}


def initialize_fare_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS domain_tariff_rules (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            rate_card_id TEXT,
            entity_type TEXT NOT NULL DEFAULT 'DEFAULT',
            entity_id TEXT,
            city_id TEXT,
            branch_id TEXT,
            vehicle_group_id TEXT NOT NULL,
            fare_mode TEXT NOT NULL DEFAULT 'local',
            package_name TEXT NOT NULL DEFAULT '',
            package_minutes INTEGER NOT NULL DEFAULT 0,
            included_km REAL NOT NULL DEFAULT 0,
            base_paise INTEGER NOT NULL DEFAULT 0,
            extra_km_paise INTEGER NOT NULL DEFAULT 0,
            extra_hour_paise INTEGER NOT NULL DEFAULT 0,
            grace_period_minutes INTEGER NOT NULL DEFAULT 0,
            daily_min_km REAL NOT NULL DEFAULT 0,
            driver_allowance_day_paise INTEGER NOT NULL DEFAULT 0,
            driver_allowance_night_paise INTEGER NOT NULL DEFAULT 0,
            waiting_paise_per_hour INTEGER NOT NULL DEFAULT 0,
            free_waiting_minutes INTEGER NOT NULL DEFAULT 0,
            fuel_benchmark_rate_paise INTEGER NOT NULL DEFAULT 0,
            fuel_mileage_km_per_unit REAL NOT NULL DEFAULT 0,
            fuel_type TEXT NOT NULL DEFAULT '',
            slab_switch_mode TEXT NOT NULL DEFAULT 'UPGRADE_ONLY',
            tax_rate_bps INTEGER NOT NULL DEFAULT 500,
            effective_from TEXT,
            effective_to TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tariff_rules_org ON domain_tariff_rules(organization_id, entity_type, fare_mode, vehicle_group_id);
        CREATE INDEX IF NOT EXISTS idx_tariff_rules_entity ON domain_tariff_rules(organization_id, entity_id, city_id);
        """
    )


def _seed_default_tariff_rules_if_empty(conn, org_id: str, user_id: str) -> None:
    count = conn.execute(
        "SELECT count(*) FROM domain_tariff_rules WHERE organization_id = ?",
        (org_id,),
    ).fetchone()[0]
    if count > 0:
        return

    now = now_iso()
    for rule in STANDARD_PRESETS["sample_rules"]:
        rule_id = new_id("tariff")
        conn.execute(
            """
            INSERT INTO domain_tariff_rules(
                id, organization_id, rate_card_id, entity_type, entity_id, city_id, branch_id,
                vehicle_group_id, fare_mode, package_name, package_minutes, included_km,
                base_paise, extra_km_paise, extra_hour_paise, grace_period_minutes,
                daily_min_km, driver_allowance_day_paise, driver_allowance_night_paise,
                waiting_paise_per_hour, free_waiting_minutes, fuel_benchmark_rate_paise,
                fuel_mileage_km_per_unit, fuel_type, slab_switch_mode, tax_rate_bps,
                effective_from, effective_to, is_active, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                rule_id,
                org_id,
                None,
                "DEFAULT",
                None,
                None,
                None,
                rule.get("vehicle_group_id", "SEDAN"),
                rule.get("fare_mode", "local"),
                rule.get("package_name", ""),
                rule.get("package_minutes", 0),
                rule.get("included_km", 0),
                rule.get("base_paise", 0),
                rule.get("extra_km_paise", 0),
                rule.get("extra_hour_paise", 0),
                rule.get("grace_period_minutes", 0),
                rule.get("daily_min_km", 0),
                rule.get("driver_allowance_day_paise", 0),
                rule.get("driver_allowance_night_paise", 0),
                rule.get("waiting_paise_per_hour", 0),
                rule.get("free_waiting_minutes", 0),
                rule.get("fuel_benchmark_rate_paise", 0),
                rule.get("fuel_mileage_km_per_unit", 0),
                rule.get("fuel_type", ""),
                rule.get("slab_switch_mode", "UPGRADE_ONLY"),
                rule.get("tax_rate_bps", 500),
                "2026-01-01",
                None,
                user_id,
                now,
                now,
            ),
        )


def _rule_from_row(row) -> dict[str, Any]:
    res = dict(row)
    res["tenant_id"] = res.get("organization_id")
    return res


def handle_fare(conn, user: dict, method: str, path: str, payload: dict, ip: str) -> dict[str, Any] | None:
    route = urlsplit(path).path.rstrip("/") or "/"
    if not route.startswith("/api/fare"):
        return None

    org = _org(user)
    _seed_default_tariff_rules_if_empty(conn, org, user["id"])

    # 1. Presets / Defaults
    if route == "/api/fare/presets" and method == "GET":
        return {
            "ok": True,
            "engine_version": FARE_ENGINE_VERSION,
            "tier_labels": TIER_LABELS,
            "presets": STANDARD_PRESETS,
        }

    # 2. Tariff Rules Listing
    if route == "/api/fare/rules" and method == "GET":
        query_params = parse_qs(urlsplit(path).query)
        fare_mode = query_params.get("fare_mode", [None])[0]
        vehicle_group = query_params.get("vehicle_group", [None])[0]
        entity_type = query_params.get("entity_type", [None])[0]

        sql = "SELECT * FROM domain_tariff_rules WHERE organization_id = ?"
        params: list[Any] = [org]
        if fare_mode:
            sql += " AND lower(fare_mode) = ?"
            params.append(fare_mode.lower())
        if vehicle_group:
            sql += " AND upper(vehicle_group_id) = ?"
            params.append(vehicle_group.upper())
        if entity_type:
            sql += " AND upper(entity_type) = ?"
            params.append(entity_type.upper())
        sql += " ORDER BY entity_type ASC, vehicle_group_id ASC, package_minutes ASC, included_km ASC"

        rows = conn.execute(sql, params).fetchall()
        return {"ok": True, "items": [_rule_from_row(r) for r in rows]}

    # 3. Create Tariff Rule
    if route == "/api/fare/rules" and method == "POST":
        rule_id = new_id("tariff")
        now = now_iso()
        vg = str(payload.get("vehicle_group_id") or payload.get("vehicle_group") or "SEDAN").strip().upper()
        mode = str(payload.get("fare_mode") or payload.get("duty_type") or "local").strip().lower()

        conn.execute(
            """
            INSERT INTO domain_tariff_rules(
                id, organization_id, rate_card_id, entity_type, entity_id, city_id, branch_id,
                vehicle_group_id, fare_mode, package_name, package_minutes, included_km,
                base_paise, extra_km_paise, extra_hour_paise, grace_period_minutes,
                daily_min_km, driver_allowance_day_paise, driver_allowance_night_paise,
                waiting_paise_per_hour, free_waiting_minutes, fuel_benchmark_rate_paise,
                fuel_mileage_km_per_unit, fuel_type, slab_switch_mode, tax_rate_bps,
                effective_from, effective_to, is_active, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rule_id,
                org,
                payload.get("rate_card_id"),
                str(payload.get("entity_type") or "DEFAULT").upper(),
                payload.get("entity_id"),
                payload.get("city_id"),
                payload.get("branch_id"),
                vg,
                mode,
                _text(payload, "package_name", maximum=120) or f"{vg} {mode.capitalize()}",
                int(payload.get("package_minutes") or 0),
                float(payload.get("included_km") or 0.0),
                int(payload.get("base_paise") or 0),
                int(payload.get("extra_km_paise") or 0),
                int(payload.get("extra_hour_paise") or 0),
                int(payload.get("grace_period_minutes") or 0),
                float(payload.get("daily_min_km") or 0.0),
                int(payload.get("driver_allowance_day_paise") or 0),
                int(payload.get("driver_allowance_night_paise") or 0),
                int(payload.get("waiting_paise_per_hour") or 0),
                int(payload.get("free_waiting_minutes") or 0),
                int(payload.get("fuel_benchmark_rate_paise") or 0),
                float(payload.get("fuel_mileage_km_per_unit") or 0.0),
                str(payload.get("fuel_type") or ""),
                str(payload.get("slab_switch_mode") or "UPGRADE_ONLY").upper(),
                int(payload.get("tax_rate_bps") or 500),
                payload.get("effective_from") or now[:10],
                payload.get("effective_to"),
                1 if payload.get("is_active", True) else 0,
                user["id"],
                now,
                now,
            ),
        )
        _audit(conn, user, "tariff_rule.created", "tariff_rule", rule_id, ip, {"vehicle_group": vg, "fare_mode": mode})
        row = conn.execute("SELECT * FROM domain_tariff_rules WHERE id = ?", (rule_id,)).fetchone()
        return {"ok": True, "item": _rule_from_row(row)}

    # 4. Delete Tariff Rule
    rule_match = re.match(r"^/api/fare/rules/([^/]+)$", route)
    if rule_match and method == "DELETE":
        rule_id = rule_match.group(1)
        _assert_owned(conn, "domain_tariff_rules", rule_id, org)
        conn.execute("DELETE FROM domain_tariff_rules WHERE id = ? AND organization_id = ?", (rule_id, org))
        _audit(conn, user, "tariff_rule.deleted", "tariff_rule", rule_id, ip, {})
        return {"ok": True, "deleted_id": rule_id}

    # 4b. Visual Rate Card Copy Tool (Bulk copy tariff matrix with % markup/markdown across cities/entities)
    if route == "/api/fare/rules/copy" and method == "POST":
        source_city_id = payload.get("source_city_id")
        target_city_id = payload.get("target_city_id")
        source_entity_id = payload.get("source_entity_id")
        target_entity_id = payload.get("target_entity_id")
        source_entity_type = (payload.get("source_entity_type") or "DEFAULT").upper()
        target_entity_type = (payload.get("target_entity_type") or "DEFAULT").upper()
        markup_pct = float(payload.get("markup_pct") or 0.0)
        overwrite = bool(payload.get("overwrite", False))

        sql = "SELECT * FROM domain_tariff_rules WHERE organization_id = ? AND is_active = 1"
        params = [org]
        if source_city_id:
            sql += " AND city_id = ?"
            params.append(source_city_id)
        if source_entity_id:
            sql += " AND entity_id = ?"
            params.append(source_entity_id)
        else:
            sql += " AND entity_type = ?"
            params.append(source_entity_type)

        source_rows = conn.execute(sql, params).fetchall()
        if not source_rows:
            raise DomainError(404, "No matching source tariff rules found to copy", "NO_SOURCE_RULES")

        multiplier = 1.0 + (markup_pct / 100.0)
        now = now_iso()
        copied_rules = []

        for row in source_rows:
            orig = dict(row)
            new_rule_id = new_id("trf")

            base_p = max(0, int(round((orig.get("base_paise") or 0) * multiplier)))
            km_p = max(0, int(round((orig.get("extra_km_paise") or 0) * multiplier)))
            hr_p = max(0, int(round((orig.get("extra_hour_paise") or 0) * multiplier)))
            allowance_d = max(0, int(round((orig.get("driver_allowance_day_paise") or 0) * multiplier)))
            allowance_n = max(0, int(round((orig.get("driver_allowance_night_paise") or 0) * multiplier)))
            waiting_p = max(0, int(round((orig.get("waiting_paise_per_hour") or 0) * multiplier)))

            dest_city = target_city_id if target_city_id is not None else orig.get("city_id")
            dest_entity_type = target_entity_type if target_entity_id or payload.get("target_entity_type") else orig.get("entity_type")
            dest_entity_id = target_entity_id if target_entity_id is not None else orig.get("entity_id")

            if overwrite:
                conn.execute(
                    """
                    DELETE FROM domain_tariff_rules
                    WHERE organization_id = ? AND (city_id = ? OR (city_id IS NULL AND ? IS NULL))
                      AND entity_type = ? AND (entity_id = ? OR (entity_id IS NULL AND ? IS NULL))
                      AND vehicle_group_id = ? AND fare_mode = ? AND package_name = ?
                    """,
                    (org, dest_city, dest_city, dest_entity_type, dest_entity_id, dest_entity_id, orig.get("vehicle_group_id"), orig.get("fare_mode"), orig.get("package_name")),
                )

            conn.execute(
                """
                INSERT INTO domain_tariff_rules (
                    id, organization_id, rate_card_id, entity_type, entity_id, city_id, branch_id,
                    vehicle_group_id, fare_mode, package_name, package_minutes, included_km,
                    base_paise, extra_km_paise, extra_hour_paise, grace_period_minutes,
                    daily_min_km, driver_allowance_day_paise, driver_allowance_night_paise,
                    waiting_paise_per_hour, free_waiting_minutes, fuel_benchmark_rate_paise,
                    fuel_mileage_km_per_unit, fuel_type, slab_switch_mode, tax_rate_bps,
                    effective_from, effective_to, is_active, created_by, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    new_rule_id,
                    org,
                    orig.get("rate_card_id"),
                    dest_entity_type,
                    dest_entity_id,
                    dest_city,
                    orig.get("branch_id"),
                    orig.get("vehicle_group_id"),
                    orig.get("fare_mode"),
                    orig.get("package_name"),
                    orig.get("package_minutes") or 0,
                    orig.get("included_km") or 0.0,
                    base_p,
                    km_p,
                    hr_p,
                    orig.get("grace_period_minutes") or 0,
                    orig.get("daily_min_km") or 0.0,
                    allowance_d,
                    allowance_n,
                    waiting_p,
                    orig.get("free_waiting_minutes") or 0,
                    orig.get("fuel_benchmark_rate_paise") or 0,
                    orig.get("fuel_mileage_km_per_unit") or 0.0,
                    orig.get("fuel_type") or "",
                    orig.get("slab_switch_mode") or "UPGRADE_ONLY",
                    orig.get("tax_rate_bps") or 500,
                    orig.get("effective_from") or now[:10],
                    orig.get("effective_to"),
                    1,
                    user["id"],
                    now,
                    now,
                ),
            )
            copied_rules.append({
                "id": new_rule_id,
                "vehicle_group_id": orig.get("vehicle_group_id"),
                "fare_mode": orig.get("fare_mode"),
                "package_name": orig.get("package_name"),
                "base_paise": base_p,
                "extra_km_paise": km_p,
            })

        _audit(
            conn,
            user,
            "tariff_rules.bulk_copied",
            "tariff_rule",
            f"count:{len(copied_rules)}",
            ip,
            {
                "source_city": source_city_id,
                "target_city": target_city_id,
                "markup_pct": markup_pct,
                "count": len(copied_rules),
            },
        )
        return {
            "ok": True,
            "message": f"Successfully copied {len(copied_rules)} tariff rules with {markup_pct:+.1f}% adjustment.",
            "copied_count": len(copied_rules),
            "items": copied_rules,
        }


    # 5. Rate Resolution Endpoint (4-Tier Waterfall)
    if route == "/api/fare/resolve" and method == "POST":
        rules = payload.get("rate_rules")
        if not rules:
            rows = conn.execute(
                "SELECT * FROM domain_tariff_rules WHERE organization_id = ? AND is_active = 1",
                (org,),
            ).fetchall()
            rules = [_rule_from_row(r) for r in rows]

        try:
            resolved = resolve_rate_card_context(
                rules,
                tenant_id=str(org),
                ledger_side=payload.get("ledger_side", "RECEIVABLE"),
                entity_id=payload.get("entity_id"),
                city_id=payload.get("city_id"),
                duty_date=payload.get("duty_date"),
                fare_mode=payload.get("fare_mode", "local"),
                requested_vehicle_group=payload.get("requested_vehicle_group", "SEDAN"),
                allotted_vehicle_group=payload.get("allotted_vehicle_group"),
                charge_upgrade_to_client=bool(payload.get("charge_upgrade_to_client", False)),
                booked_package_name=payload.get("booked_package_name"),
                booked_rule_id=payload.get("booked_rule_id"),
            )
            return {"ok": True, "resolved_profile": resolved}
        except FareError as exc:
            raise DomainError(400, exc.message, exc.code)

    # 6. Single Fare Calculation
    if route == "/api/fare/calculate" and method == "POST":
        telemetry = payload.get("telemetry", {})
        profile = payload.get("profile", {})
        candidate_slabs = payload.get("candidate_slabs")
        surcharge_rule = payload.get("surcharge_rule")
        current_fuel_rate_paise = payload.get("current_fuel_rate_paise")
        is_interstate = bool(payload.get("is_interstate", False))

        try:
            result = calculate_fare(
                telemetry,
                profile,
                candidate_slabs=candidate_slabs,
                surcharge_rule=surcharge_rule,
                current_fuel_rate_paise=current_fuel_rate_paise,
                is_interstate=is_interstate,
            )
            return {"ok": True, "fare": result}
        except FareError as exc:
            raise DomainError(400, exc.message, exc.code)

    # 7. Dual Ledger Settlement (Customer Receivable vs Supplier Payable + Net Duty P&L)
    if route == "/api/fare/settlement" and method == "POST":
        telemetry = payload.get("telemetry", {})
        rec_profile = payload.get("receivable_profile", {})
        pay_profile = payload.get("payable_profile", {})
        current_fuel_rate_paise = payload.get("current_fuel_rate_paise")
        is_customer_interstate = bool(payload.get("is_customer_interstate") or payload.get("is_client_interstate", False))
        is_supplier_interstate = bool(payload.get("is_supplier_interstate", False))

        try:
            settlement = calculate_dual_ledger_settlement(
                telemetry,
                rec_profile,
                pay_profile,
                current_fuel_rate_paise=current_fuel_rate_paise,
                is_customer_interstate=is_customer_interstate,
                is_supplier_interstate=is_supplier_interstate,
            )
            return {"ok": True, "settlement": settlement}
        except FareError as exc:
            raise DomainError(400, exc.message, exc.code)

    # 8. Recalculate Duty Fare (Database Duty -> Dual-Ledger Calculation -> Snapshot Update)
    duty_recalc_match = re.match(r"^/api/fare/duties/([^/]+)/recalculate$", route)
    if duty_recalc_match and method == "POST":
        duty_id = duty_recalc_match.group(1)
        duty_row = _assert_owned(conn, "domain_duties", duty_id, org)
        duty = dict(duty_row)
        if duty.get("status") in ("completed", "invoiced", "locked", "billed"):
            raise DomainError(409, f"Cannot recalculate duty {duty_id} because it is already finalized in status '{duty['status']}'. Recalculation is locked.", "duty_tariff_locked")
        inv_row = conn.execute("SELECT id FROM domain_invoices WHERE organization_id = ? AND duty_id = ? AND status != 'void'", (org, duty_id)).fetchone()
        if inv_row:
            raise DomainError(409, f"Cannot recalculate duty {duty_id} because an invoice ({inv_row['id']}) has already been generated.", "duty_invoiced_locked")
        booking = dict(_assert_owned(conn, "domain_bookings", duty["booking_id"], org))

        # Vehicle info
        vehicle = None
        if duty.get("vehicle_id"):
            v_row = conn.execute(
                "SELECT * FROM domain_vehicles WHERE id = ? AND organization_id = ?",
                (duty["vehicle_id"], org),
            ).fetchone()
            if v_row:
                vehicle = dict(v_row)

        # Telemetry resolution
        start_odo = duty["start_odometer"]
        end_odo = duty["end_odometer"]
        duration_minutes = 0
        if duty["started_at"] and duty["completed_at"]:
            try:
                t1 = datetime.datetime.fromisoformat(duty["started_at"].replace("Z", "+00:00"))
                t2 = datetime.datetime.fromisoformat(duty["completed_at"].replace("Z", "+00:00"))
                duration_minutes = max(0, int((t2 - t1).total_seconds() // 60))
            except Exception:
                pass
        elif duty["reporting_at"] and duty["completed_at"]:
            try:
                t1 = datetime.datetime.fromisoformat(duty["reporting_at"].replace("Z", "+00:00"))
                t2 = datetime.datetime.fromisoformat(duty["completed_at"].replace("Z", "+00:00"))
                duration_minutes = max(0, int((t2 - t1).total_seconds() // 60))
            except Exception:
                pass

        # Check payload overrides
        rep_km = payload.get("reporting_km", start_odo or 1000)
        rel_km = payload.get("releasing_km", end_odo or (rep_km + 40))
        dur_mins = payload.get("duration_minutes", duration_minutes or 240)
        billing_mode = payload.get("billing_mode", "P2P")
        toll_paise = int(payload.get("toll_paise") or 0)
        parking_paise = int(payload.get("parking_paise") or 0)

        # Vehicle groups
        req_vg = str(
            payload.get("requested_vehicle_group")
            or payload.get("vehicle_group")
            or (booking.get("duty_type") if str(booking.get("duty_type")).upper() in ("SEDAN", "SUV", "HATCHBACK", "TEMPO", "LUXURY") else None)
            or booking.get("vehicle_group_id")
            or "SEDAN"
        ).upper()
        if vehicle and vehicle.get("vehicle_group"):
            allot_vg = str(vehicle["vehicle_group"]).upper()
            if "SUV" in allot_vg:
                allot_vg = "SUV"
            elif "SEDAN" in allot_vg:
                allot_vg = "SEDAN"
            elif "TEMPO" in allot_vg:
                allot_vg = "TEMPO"
            elif "HATCH" in allot_vg:
                allot_vg = "HATCHBACK"
        else:
            allot_vg = str(payload.get("allotted_vehicle_group") or req_vg).upper()

        duty_mode = str(payload.get("fare_mode") or booking.get("duty_type") or "local").lower()
        if duty_mode not in ("local", "outstation", "airport", "point_to_point"):
            duty_mode = "local"

        duty_telemetry = {
            "billing_mode": billing_mode,
            "reporting_km": rep_km,
            "releasing_km": rel_km,
            "duration_minutes": dur_mins,
            "toll_paise": toll_paise,
            "parking_paise": parking_paise,
            "calendar_days": int(payload.get("calendar_days") or 1),
            "night_count": int(payload.get("night_count") or payload.get("night_hours_count") or 0),
            "night_hours_count": int(payload.get("night_count") or payload.get("night_hours_count") or 0),
            "waiting_minutes": int(payload.get("waiting_minutes") or 0),
        }

        # Query all active tariff rules
        rules = [_rule_from_row(r) for r in conn.execute(
            "SELECT * FROM domain_tariff_rules WHERE organization_id = ? AND is_active = 1",
            (org,),
        ).fetchall()]

        # Resolve Customer Profile
        charge_upgrade = bool(payload.get("charge_upgrade_to_client", False))
        customer_id = booking.get("customer_id")
        supplier_id = duty.get("supplier_id")

        city_id = payload.get("city_id") or payload.get("city")
        if not city_id and booking.get("pickup_json"):
            try:
                p_data = json.loads(booking["pickup_json"])
                city_id = p_data.get("city")
            except Exception:
                pass

        rec_profile = resolve_rate_card_context(
            rules,
            tenant_id=str(org),
            ledger_side="RECEIVABLE",
            entity_id=customer_id,
            city_id=city_id,
            duty_date=str(duty.get("reporting_at") or now_iso())[:10],
            fare_mode=duty_mode,
            requested_vehicle_group=req_vg,
            allotted_vehicle_group=allot_vg,
            charge_upgrade_to_client=charge_upgrade,
        )

        # Resolve Supplier Profile
        pay_profile = resolve_rate_card_context(
            rules,
            tenant_id=str(org),
            ledger_side="PAYABLE",
            entity_id=supplier_id,
            city_id=city_id,
            duty_date=str(duty.get("reporting_at") or now_iso())[:10],
            fare_mode=duty_mode,
            requested_vehicle_group=req_vg,
            allotted_vehicle_group=allot_vg,
        )

        settlement = calculate_dual_ledger_settlement(duty_telemetry, rec_profile, pay_profile)

        # Build snapshot maintaining backwards compatibility with legacy invoice generation
        rec = settlement["receivable"]
        subtotal = rec.get("taxable_subtotal_paise", 0)
        total_fare = rec.get("total_fare_paise", 0)
        dist_km = (rec.get("explanation") or {}).get("telemetry", {}).get("billable_km", 0.0)
        snapshot = {
            "engine_version": FARE_ENGINE_VERSION,
            "fare_engine_managed": True,
            "subtotal_paise": subtotal,
            "taxable_subtotal_paise": subtotal,
            "tax_paise": rec.get("tax_paise", 0),
            "total_paise": total_fare,
            "total_fare_paise": total_fare,
            "currency": rec.get("currency", "INR"),
            "distance_km": dist_km,
            "lines": rec.get("lines", []),
            "tax_lines": rec.get("tax_lines", []),
            "explanation": rec.get("explanation"),
            "settlement": settlement,
        }

        now = now_iso()
        conn.execute(
            """
            UPDATE domain_duties
            SET calculation_snapshot_json = ?,
                start_odometer = coalesce(start_odometer, ?),
                end_odometer = coalesce(end_odometer, ?),
                updated_at = ?
            WHERE id = ? AND organization_id = ?
            """,
            (json.dumps(snapshot), rep_km, rel_km, now, duty_id, org),
        )

        _audit(
            conn,
            user,
            "duty.fare_recalculated",
            "duty",
            duty_id,
            ip,
            {
                "receivable_total_paise": total_fare,
                "gross_profit_paise": settlement["settlement_pnl"]["gross_profit_paise"],
                "gross_margin_pct": settlement["settlement_pnl"]["gross_margin_percentage"],
            },
        )

        fresh_duty = conn.execute("SELECT * FROM domain_duties WHERE id = ?", (duty_id,)).fetchone()
        item = _serialize(fresh_duty, ("calculation_snapshot_json",))
        item["calculation_snapshot"] = snapshot
        return {
            "ok": True,
            "item": item,
            "settlement": settlement,
        }

    return None
