"""Phase 3 intelligence contracts for Axiom Fleet.

Phase 3 turns the operational evidence from Fleet, Network and Phase 1/2 into
six auditable intelligence surfaces:

* predictive operational alerts with explainable factors and feedback;
* a vendor-quality graph derived from service orders and scorecards;
* deterministic cost/service simulations with explicit assumptions;
* automated invoice, GPS and expense variance findings;
* sustainability trips, targets, factors and reduction recommendations;
* tenant-scoped regional, currency, tax and localization profiles.

The local implementation is deliberately deterministic and mock-first. It never
replaces Fleet duties, invoices or Network service orders: those remain the
canonical sources of truth. Supabase mirrors the additive tables and routes
through the authenticated phase3-orchestrator boundary.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import parse_qs, urlsplit

from backend_domain import DomainError, now_iso, new_id
from backend_p0 import _has_permission, _org, _role, _user_id, _row as p0_row


PHASE3_READ = {
    "phase3.analytics.read",
    "phase3.predictive.read",
    "phase3.vendor_quality.read",
    "phase3.simulation.read",
    "phase3.variance.read",
    "phase3.sustainability.read",
    "phase3.regions.read",
}
PHASE3_WRITE = {
    "phase3.analytics.write",
    "phase3.predictive.write",
    "phase3.vendor_quality.write",
    "phase3.simulation.write",
    "phase3.variance.write",
    "phase3.sustainability.write",
    "phase3.regions.write",
}

REGION_CATALOG = [
    {"country_code": "IN", "region_code": "IN-MH", "name": "India · Maharashtra", "currency": "INR", "timezone": "Asia/Kolkata", "locale": "en-IN", "tax_regime": "GST", "distance_unit": "km"},
    {"country_code": "IN", "region_code": "IN-KA", "name": "India · Karnataka", "currency": "INR", "timezone": "Asia/Kolkata", "locale": "en-IN", "tax_regime": "GST", "distance_unit": "km"},
    {"country_code": "AE", "region_code": "AE-DU", "name": "United Arab Emirates · Dubai", "currency": "AED", "timezone": "Asia/Dubai", "locale": "en-AE", "tax_regime": "VAT", "distance_unit": "km"},
    {"country_code": "SG", "region_code": "SG-SG", "name": "Singapore", "currency": "SGD", "timezone": "Asia/Singapore", "locale": "en-SG", "tax_regime": "GST", "distance_unit": "km"},
    {"country_code": "GB", "region_code": "GB-LND", "name": "United Kingdom · London", "currency": "GBP", "timezone": "Europe/London", "locale": "en-GB", "tax_regime": "VAT", "distance_unit": "mi"},
]

# Mock rates are versioned and labelled. They are not presented as live market data.
MOCK_FX = {
    ("INR", "AED"): Decimal("0.0435"),
    ("INR", "SGD"): Decimal("0.0160"),
    ("INR", "GBP"): Decimal("0.00935"),
    ("AED", "INR"): Decimal("22.9885"),
    ("SGD", "INR"): Decimal("62.5000"),
    ("GBP", "INR"): Decimal("106.9519"),
}

# Operational, well-to-wheel planning factors in kg CO2e/km. A production
# deployment should source approved factors by country and publish revisions.
EMISSION_FACTORS = {
    "petrol": Decimal("0.192"),
    "diesel": Decimal("0.171"),
    "cng": Decimal("0.130"),
    "hybrid": Decimal("0.100"),
    "ev": Decimal("0.050"),
    "electric": Decimal("0.050"),
}
GRID_FACTOR_KG_PER_KWH = Decimal("0.700")
DEFAULT_ENERGY_PRICE_MINOR = 1200
DEFAULT_EV_CONSUMPTION_KWH_PER_KM = Decimal("0.160")
DEFAULT_EV_RESERVE_PCT = 15.0


def _json(value, fallback):
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value) if value else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def _row(row, json_fields=()):
    if row is None:
        return None
    item = dict(row)
    for field in json_fields:
        if field in item:
            key = field[:-5] if field.endswith("_json") else field
            item[key] = _json(item.pop(field), {} if field.endswith("_json") else None)
    return item


def _limit(query, default=100):
    try:
        return min(max(int(query.get("limit", [default])[0] or default), 1), 500)
    except (TypeError, ValueError):
        return default


def _parse(raw_route):
    parsed = urlsplit(raw_route)
    return parsed.path.rstrip("/") or "/", parse_qs(parsed.query)


def _text(payload, key, default="", maximum=500):
    value = str(payload.get(key, default) or "").strip()
    if len(value) > maximum:
        raise DomainError(400, f"{key} is too long", "validation_error")
    return value


def _number(value, key, default=0.0, minimum=None):
    if value in (None, ""):
        result = float(default)
    else:
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise DomainError(400, f"{key} must be numeric", "validation_error") from exc
    if not math.isfinite(result):
        raise DomainError(400, f"{key} must be finite", "validation_error")
    if minimum is not None and result < minimum:
        raise DomainError(400, f"{key} cannot be below {minimum}", "validation_error")
    return result


def _int(value, key, default=0, minimum=None):
    number = int(round(_number(value, key, default)))
    if minimum is not None and number < minimum:
        raise DomainError(400, f"{key} cannot be below {minimum}", "validation_error")
    return number


def _iso_date(value, key, fallback=None):
    text = str(value or fallback or "")
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise DomainError(400, f"{key} must be an ISO date", "validation_error") from exc


def _parse_time(value):
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _clamp(value, low=0.0, high=100.0):
    return max(low, min(high, float(value)))


def _round_minor(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _phase3_permission(conn, user, permission: str, *, write=False):
    if _role(user) == "platform":
        return
    if _has_permission(conn, user, permission):
        return
    # New local tenants use the role defaults from backend_p0. This fallback
    # keeps existing databases usable before the next permission seed runs.
    if not write and _role(user) in {"vendor", "corporate"}:
        return
    raise DomainError(403, f"Permission required: {permission}", "permission_denied")


def _audit(conn, user, action, entity_type, entity_id, ip, metadata=None):
    conn.execute(
        "INSERT INTO audit_events(id, user_id, action, entity_type, entity_id, metadata_json, ip_address, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (new_id("audit"), _user_id(user), action, entity_type, entity_id, json.dumps(metadata or {}), ip, now_iso()),
    )


def _event(conn, user, event_type, entity_type, entity_id, ip, payload=None):
    event_id = new_id("p3evt")
    conn.execute(
        "INSERT INTO phase3_events(id, organization_id, event_type, entity_type, entity_id, payload_json, actor_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (event_id, _org(user), event_type, entity_type, entity_id, json.dumps(payload or {}), _user_id(user), now_iso()),
    )
    _audit(conn, user, event_type, entity_type, entity_id, ip, payload or {})
    return event_id


def _default_region():
    return dict(REGION_CATALOG[0])


def _ensure_default_region(conn, organization_id):
    today = date.today().isoformat()
    row = conn.execute("SELECT * FROM phase3_regions WHERE organization_id = ? AND is_default = 1 AND status = 'active' AND (effective_from IS NULL OR effective_from <= ?) AND (effective_to IS NULL OR effective_to >= ?) LIMIT 1", (organization_id, today, today)).fetchone()
    if row:
        return row
    existing = conn.execute("SELECT * FROM phase3_regions WHERE organization_id = ? AND status = 'active' AND (effective_from IS NULL OR effective_from <= ?) AND (effective_to IS NULL OR effective_to >= ?) ORDER BY created_at LIMIT 1", (organization_id, today, today)).fetchone()
    if existing:
        conn.execute("UPDATE phase3_regions SET is_default = 1 WHERE id = ?", (existing["id"],))
        return conn.execute("SELECT * FROM phase3_regions WHERE id = ?", (existing["id"],)).fetchone()
    profile = _default_region()
    region_id = new_id("region3")
    created_at = now_iso()
    # Several dashboard surfaces request localization concurrently on first
    # load. The organization/region unique key is the idempotency boundary;
    # ignore a competing insert and return the row that won the race.
    conn.execute(
        "INSERT OR IGNORE INTO phase3_regions(id, organization_id, country_code, region_code, name, currency, timezone, locale, tax_regime, distance_unit, is_default, status, metadata_json, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'active', '{}', NULL, ?, ?)",
        (region_id, organization_id, profile["country_code"], profile["region_code"], profile["name"], profile["currency"], profile["timezone"], profile["locale"], profile["tax_regime"], profile["distance_unit"], created_at, created_at),
    )
    return conn.execute("SELECT * FROM phase3_regions WHERE organization_id = ? AND region_code = ?", (organization_id, profile["region_code"])).fetchone()


def initialize_phase3_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS phase3_events (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            actor_id TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_phase3_events_org_time ON phase3_events(organization_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS phase3_region_catalog (
            country_code TEXT NOT NULL,
            region_code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            currency TEXT NOT NULL,
            timezone TEXT NOT NULL,
            locale TEXT NOT NULL,
            tax_regime TEXT NOT NULL,
            distance_unit TEXT NOT NULL DEFAULT 'km',
            status TEXT NOT NULL DEFAULT 'active'
        );
        CREATE TABLE IF NOT EXISTS phase3_emission_factors (
            fuel_type TEXT PRIMARY KEY,
            factor_kg_per_km REAL NOT NULL,
            factor_version TEXT NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
        );

        CREATE TABLE IF NOT EXISTS phase3_predictive_alerts (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            evaluation_key TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            risk_score REAL NOT NULL DEFAULT 0,
            confidence REAL NOT NULL DEFAULT 0,
            lead_time_minutes INTEGER NOT NULL DEFAULT 0,
            model_version TEXT NOT NULL DEFAULT 'predictive-v1',
            factors_json TEXT NOT NULL DEFAULT '[]',
            source_event_ids_json TEXT NOT NULL DEFAULT '[]',
            recommended_action TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open',
            predicted_at TEXT NOT NULL,
            due_at TEXT,
            acknowledged_by TEXT,
            acknowledged_at TEXT,
            resolved_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, evaluation_key)
        );
        CREATE INDEX IF NOT EXISTS idx_phase3_alerts_org_status ON phase3_predictive_alerts(organization_id, status, severity, predicted_at DESC);

        CREATE TABLE IF NOT EXISTS phase3_alert_feedback (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            alert_id TEXT NOT NULL,
            outcome TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_by TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS phase3_vendor_quality_snapshots (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            vendor_profile_id TEXT NOT NULL,
            vendor_organization_id TEXT,
            formula_version TEXT NOT NULL DEFAULT 'vendor-quality-v1',
            score REAL NOT NULL DEFAULT 0,
            confidence TEXT NOT NULL DEFAULT 'cold_start',
            sample_size INTEGER NOT NULL DEFAULT 0,
            metrics_json TEXT NOT NULL DEFAULT '{}',
            source_event_ids_json TEXT NOT NULL DEFAULT '[]',
            computed_at TEXT NOT NULL,
            UNIQUE(organization_id, vendor_profile_id, formula_version)
        );
        CREATE TABLE IF NOT EXISTS phase3_vendor_quality_edges (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            edge_key TEXT NOT NULL,
            from_type TEXT NOT NULL,
            from_id TEXT NOT NULL,
            to_type TEXT NOT NULL,
            to_id TEXT NOT NULL,
            edge_type TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 1,
            evidence_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, edge_key)
        );
        CREATE INDEX IF NOT EXISTS idx_phase3_vendor_edges_org ON phase3_vendor_quality_edges(organization_id, from_type, from_id);

        CREATE TABLE IF NOT EXISTS phase3_simulations (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            scenario_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'completed',
            model_version TEXT NOT NULL DEFAULT 'cost-service-v1',
            idempotency_key TEXT,
            inputs_json TEXT NOT NULL DEFAULT '{}',
            outputs_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE INDEX IF NOT EXISTS idx_phase3_simulations_org_time ON phase3_simulations(organization_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS phase3_variance_findings (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            scan_key TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            variance_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'medium',
            expected_paise INTEGER NOT NULL DEFAULT 0,
            observed_paise INTEGER NOT NULL DEFAULT 0,
            variance_paise INTEGER NOT NULL DEFAULT 0,
            variance_pct REAL NOT NULL DEFAULT 0,
            rule_version TEXT NOT NULL DEFAULT 'variance-v1',
            evidence_json TEXT NOT NULL DEFAULT '{}',
            source_event_ids_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'open',
            assigned_to TEXT,
            assigned_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            resolved_at TEXT,
            UNIQUE(organization_id, scan_key)
        );
        CREATE INDEX IF NOT EXISTS idx_phase3_variance_org_status ON phase3_variance_findings(organization_id, status, severity, created_at DESC);

        CREATE TABLE IF NOT EXISTS phase3_sustainability_trips (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            duty_id TEXT NOT NULL,
            vehicle_id TEXT,
            region_code TEXT,
            fuel_type TEXT NOT NULL DEFAULT 'petrol',
            distance_km REAL NOT NULL DEFAULT 0,
            passenger_count INTEGER NOT NULL DEFAULT 1,
            energy_kwh REAL NOT NULL DEFAULT 0,
            energy_cost_minor INTEGER NOT NULL DEFAULT 0,
            energy_price_per_kwh_minor INTEGER NOT NULL DEFAULT 0,
            emissions_kg REAL NOT NULL DEFAULT 0,
            emissions_per_passenger_km_g REAL NOT NULL DEFAULT 0,
            baseline_emissions_kg REAL NOT NULL DEFAULT 0,
            avoided_emissions_kg REAL NOT NULL DEFAULT 0,
            factor_kg_per_km REAL NOT NULL DEFAULT 0,
            grid_factor_kg_per_kwh REAL NOT NULL DEFAULT 0,
            factor_version TEXT NOT NULL DEFAULT 'factor-v1',
            range_required_km REAL NOT NULL DEFAULT 0,
            range_remaining_km REAL,
            charging_station_id TEXT,
            charging_available INTEGER NOT NULL DEFAULT 0,
            ev_eligibility_status TEXT NOT NULL DEFAULT 'not_applicable',
            ev_eligibility_reasons_json TEXT NOT NULL DEFAULT '[]',
            source_event_ids_json TEXT NOT NULL DEFAULT '[]',
            calculated_at TEXT NOT NULL,
            UNIQUE(organization_id, duty_id, factor_version)
        );
        CREATE INDEX IF NOT EXISTS idx_phase3_sustainability_org_time ON phase3_sustainability_trips(organization_id, calculated_at DESC);

        CREATE TABLE IF NOT EXISTS phase3_charging_stations (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            region_code TEXT NOT NULL,
            name TEXT NOT NULL,
            location_label TEXT NOT NULL DEFAULT '',
            connector_types_json TEXT NOT NULL DEFAULT '[]',
            total_ports INTEGER NOT NULL DEFAULT 0,
            available_ports INTEGER NOT NULL DEFAULT 0,
            power_kw REAL NOT NULL DEFAULT 0,
            energy_price_per_kwh_minor INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            operating_hours_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_phase3_charging_org_region ON phase3_charging_stations(organization_id, region_code, status);

        CREATE TABLE IF NOT EXISTS phase3_sustainability_targets (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT 'fleet',
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            baseline_kg REAL NOT NULL DEFAULT 0,
            target_kg REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, scope, period_start, period_end)
        );

        CREATE TABLE IF NOT EXISTS phase3_regions (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            country_code TEXT NOT NULL,
            region_code TEXT NOT NULL,
            name TEXT NOT NULL,
            currency TEXT NOT NULL,
            timezone TEXT NOT NULL,
            locale TEXT NOT NULL,
            tax_regime TEXT NOT NULL,
            distance_unit TEXT NOT NULL DEFAULT 'km',
            effective_from TEXT,
            effective_to TEXT,
            is_default INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, region_code)
        );
        CREATE INDEX IF NOT EXISTS idx_phase3_regions_org_default ON phase3_regions(organization_id, is_default, status);

        CREATE TABLE IF NOT EXISTS phase3_exchange_rates (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            base_currency TEXT NOT NULL,
            quote_currency TEXT NOT NULL,
            rate TEXT NOT NULL,
            effective_at TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'mock_fx',
            version TEXT NOT NULL DEFAULT 'fx-v1',
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, base_currency, quote_currency, effective_at)
        );
        CREATE INDEX IF NOT EXISTS idx_phase3_fx_org_pair ON phase3_exchange_rates(organization_id, base_currency, quote_currency, effective_at DESC);
        """
    )
    variance_columns = {row["name"] for row in conn.execute("PRAGMA table_info(phase3_variance_findings)").fetchall()}
    for column, definition in {"assigned_to": "TEXT", "assigned_at": "TEXT"}.items():
        if column not in variance_columns:
            conn.execute(f"ALTER TABLE phase3_variance_findings ADD COLUMN {column} {definition}")
    region_columns = {row["name"] for row in conn.execute("PRAGMA table_info(phase3_regions)").fetchall()}
    for column, definition in {"effective_from": "TEXT", "effective_to": "TEXT"}.items():
        if column not in region_columns:
            conn.execute(f"ALTER TABLE phase3_regions ADD COLUMN {column} {definition}")
    sustainability_columns = {row["name"] for row in conn.execute("PRAGMA table_info(phase3_sustainability_trips)").fetchall()}
    for column, definition in {
        "passenger_count": "INTEGER NOT NULL DEFAULT 1",
        "energy_kwh": "REAL NOT NULL DEFAULT 0",
        "energy_cost_minor": "INTEGER NOT NULL DEFAULT 0",
        "energy_price_per_kwh_minor": "INTEGER NOT NULL DEFAULT 0",
        "emissions_per_passenger_km_g": "REAL NOT NULL DEFAULT 0",
        "baseline_emissions_kg": "REAL NOT NULL DEFAULT 0",
        "avoided_emissions_kg": "REAL NOT NULL DEFAULT 0",
        "grid_factor_kg_per_kwh": "REAL NOT NULL DEFAULT 0",
        "range_required_km": "REAL NOT NULL DEFAULT 0",
        "range_remaining_km": "REAL",
        "charging_station_id": "TEXT",
        "charging_available": "INTEGER NOT NULL DEFAULT 0",
        "ev_eligibility_status": "TEXT NOT NULL DEFAULT 'not_applicable'",
        "ev_eligibility_reasons_json": "TEXT NOT NULL DEFAULT '[]'",
    }.items():
        if column not in sustainability_columns:
            conn.execute(f"ALTER TABLE phase3_sustainability_trips ADD COLUMN {column} {definition}")
    for catalog in REGION_CATALOG:
        conn.execute("INSERT OR IGNORE INTO phase3_region_catalog(country_code, region_code, name, currency, timezone, locale, tax_regime, distance_unit, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')", (catalog["country_code"], catalog["region_code"], catalog["name"], catalog["currency"], catalog["timezone"], catalog["locale"], catalog["tax_regime"], catalog["distance_unit"]))
    for fuel_type, factor in EMISSION_FACTORS.items():
        conn.execute("INSERT OR IGNORE INTO phase3_emission_factors(fuel_type, factor_kg_per_km, factor_version, source, status) VALUES (?, ?, 'factor-v1', 'Axiom planning catalog', 'active')", (fuel_type, float(factor)))
    for organization in conn.execute("SELECT id FROM organizations").fetchall():
        _ensure_default_region(conn, organization["id"])


def _active_duties(conn, user):
    org = _org(user)
    if _role(user) == "driver":
        return conn.execute(
            "SELECT d.* FROM domain_duties d JOIN domain_drivers dr ON dr.id = d.driver_id AND dr.user_id = ? WHERE d.organization_id = ? AND d.status NOT IN ('completed','cancelled') ORDER BY d.reporting_at ASC LIMIT 100",
            (_user_id(user), org),
        ).fetchall()
    return conn.execute("SELECT * FROM domain_duties WHERE organization_id = ? AND status NOT IN ('completed','cancelled') ORDER BY reporting_at ASC LIMIT 100", (org,)).fetchall()


def _latest_eta(conn, organization_id, duty_id):
    return conn.execute("SELECT * FROM phase12_eta_snapshots WHERE organization_id = ? AND duty_id = ? ORDER BY created_at DESC LIMIT 1", (organization_id, duty_id)).fetchone()


def _latest_track(conn, organization_id, duty_id):
    return conn.execute("SELECT * FROM domain_track_points WHERE organization_id = ? AND duty_id = ? ORDER BY recorded_at DESC LIMIT 1", (organization_id, duty_id)).fetchone()


def _vehicle(conn, organization_id, vehicle_id):
    if not vehicle_id:
        return None
    return conn.execute("SELECT * FROM domain_vehicles WHERE organization_id = ? AND id = ?", (organization_id, vehicle_id)).fetchone()


def _predictive_factors(conn, duty, org, now_dt, stale_after):
    factors = []
    source_ids = []
    eta = _latest_eta(conn, org, duty["id"])
    track = _latest_track(conn, org, duty["id"])
    if track:
        source_ids.append(track["id"])
        recorded = _parse_time(track["recorded_at"])
        age = int(max(0, (now_dt - recorded).total_seconds())) if recorded else stale_after + 1
        if age > stale_after:
            factors.append({"code": "stale_gps", "weight": min(40, 20 + round(age / 60)), "value": age, "unit": "seconds", "explanation": f"Latest location is {age // 60} minutes old."})
    else:
        factors.append({"code": "missing_gps", "weight": 28, "value": None, "unit": "", "explanation": "No location point is attached to the active duty."})
    if eta:
        source_ids.append(eta["id"])
        deviation = float(eta["deviation_minutes"] or 0)
        if deviation > 5:
            factors.append({"code": "eta_sla_risk", "weight": min(35, round(deviation * 1.7)), "value": deviation, "unit": "minutes", "explanation": f"Map ETA is {deviation:g} minutes off the planned route and may breach SLA."})
    reporting = _parse_time(duty["reporting_at"])
    if reporting and reporting < now_dt and str(duty["status"]) in {"assigned", "accepted"}:
        lateness = int((now_dt - reporting).total_seconds() / 60)
        code = "missed_pickup_risk" if lateness >= 10 else "sla_start_risk"
        factors.append({"code": code, "weight": min(42, 12 + lateness // 5), "value": lateness, "unit": "minutes", "explanation": f"Duty is {lateness} minutes past reporting without a start event."})
    incident = conn.execute("SELECT id FROM p0_safety_incidents WHERE organization_id = ? AND duty_id = ? AND status NOT IN ('closed','resolved') ORDER BY opened_at DESC LIMIT 1", (org, duty["id"])).fetchone()
    if incident:
        source_ids.append(incident["id"])
        factors.append({"code": "safety_risk", "weight": 38, "value": 1, "unit": "case", "explanation": "An unresolved safety incident is linked to this duty."})
    service_order = conn.execute("SELECT vendor_profile_id FROM domain_network_service_orders WHERE organization_id = ? AND fleet_duty_id = ? AND status NOT IN ('cancelled','closed') LIMIT 1", (org, duty["id"])).fetchone()
    if service_order:
        quality = conn.execute("SELECT id, score FROM phase3_vendor_quality_snapshots WHERE organization_id = ? AND vendor_profile_id = ? ORDER BY computed_at DESC LIMIT 1", (org, service_order["vendor_profile_id"])).fetchone()
        if quality and float(quality["score"] or 0) < 60:
            source_ids.append(quality["id"])
            factors.append({"code": "vendor_service_degradation", "weight": min(40, round(60 - float(quality["score"] or 0))), "value": float(quality["score"] or 0), "unit": "score", "explanation": "The linked invite-only service vendor has a degraded quality score."})
    vehicle = _vehicle(conn, org, duty["vehicle_id"])
    if vehicle:
        expiry_fields = ("rc_expiry", "insurance_expiry", "puc_expiry")
        expiring = []
        for field in expiry_fields:
            raw = vehicle[field]
            if raw:
                try:
                    days = (date.fromisoformat(raw) - now_dt.date()).days
                    if days <= 14:
                        expiring.append({"document": field.replace("_expiry", ""), "days": days})
                except ValueError:
                    pass
        if expiring:
            factors.append({"code": "compliance_expiry", "weight": 27, "value": expiring, "unit": "days", "explanation": "Vehicle compliance evidence reaches its review window soon."})
    return factors, sorted(set(source_ids))


def _predictive_alert_item(row):
    return _row(row, ("factors_json", "source_event_ids_json"))


def _predictive_list(conn, user, method, route, query, payload, ip):
    org = _org(user)
    _phase3_permission(conn, user, "phase3.predictive.read")
    if route == "/api/phase3/predictive-alerts" and method == "GET":
        sql = "SELECT * FROM phase3_predictive_alerts WHERE organization_id = ?"
        args = [org]
        for field in ("status", "severity", "entity_type"):
            value = (query.get(field) or [""])[0]
            if value and value != "all":
                sql += f" AND {field} = ?"; args.append(value)
        sql += " ORDER BY risk_score DESC, predicted_at DESC LIMIT ?"; args.append(_limit(query))
        rows = conn.execute(sql, args).fetchall()
        return {"ok": True, "items": [_predictive_alert_item(row) for row in rows], "count": len(rows), "model_version": "predictive-v1"}
    if route == "/api/phase3/predictive-alerts/evaluate" and method == "POST":
        _phase3_permission(conn, user, "phase3.predictive.write", write=True)
        model_version = _text(payload, "model_version", "predictive-v1", 40) or "predictive-v1"
        stale_after = max(60, _int(payload.get("stale_after_seconds"), "stale_after_seconds", 300, 60))
        threshold = _number(payload.get("minimum_risk_score"), "minimum_risk_score", 30, 0)
        evaluation_id = _text(payload, "idempotency_key", "", 160)
        now_dt = datetime.now(timezone.utc)
        created = []; updated = []; skipped = 0
        for duty in _active_duties(conn, user):
            factors, source_ids = _predictive_factors(conn, duty, org, now_dt, stale_after)
            score = _clamp(sum(float(factor["weight"]) for factor in factors))
            if score < threshold:
                skipped += 1
                continue
            primary = max(factors, key=lambda factor: float(factor["weight"])) if factors else {"code": "operational_risk"}
            severity = "critical" if score >= 80 else "high" if score >= 60 else "medium"
            confidence = _clamp(42 + len(source_ids) * 14 + len(factors) * 8, 0, 96)
            lead_time = 15 if severity == "critical" else 30 if severity == "high" else 60
            key_suffix = evaluation_id or now_dt.strftime("%Y-%m-%d-%H")
            evaluation_key = f"{model_version}:{duty['id']}:{primary['code']}:{key_suffix}"
            existing = conn.execute("SELECT * FROM phase3_predictive_alerts WHERE organization_id = ? AND evaluation_key = ?", (org, evaluation_key)).fetchone()
            values = (severity, round(score, 2), round(confidence, 2), lead_time, json.dumps(factors), json.dumps(source_ids), f"Review {primary['code'].replace('_', ' ')} before the next dispatch checkpoint.", now_iso(), (now_dt + timedelta(minutes=lead_time)).replace(microsecond=0).isoformat().replace("+00:00", "Z"), now_iso())
            if existing:
                conn.execute("UPDATE phase3_predictive_alerts SET severity = ?, risk_score = ?, confidence = ?, lead_time_minutes = ?, factors_json = ?, source_event_ids_json = ?, recommended_action = ?, predicted_at = ?, due_at = ?, updated_at = ? WHERE id = ? AND organization_id = ? AND status = 'open'", (*values, existing["id"], org))
                updated.append(_predictive_alert_item(conn.execute("SELECT * FROM phase3_predictive_alerts WHERE id = ?", (existing["id"],)).fetchone()))
            else:
                alert_id = new_id("p3alert")
                conn.execute("INSERT INTO phase3_predictive_alerts(id, organization_id, evaluation_key, entity_type, entity_id, alert_type, severity, risk_score, confidence, lead_time_minutes, model_version, factors_json, source_event_ids_json, recommended_action, status, predicted_at, due_at, created_at, updated_at) VALUES (?, ?, ?, 'duty', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)", (alert_id, org, evaluation_key, duty["id"], primary["code"], *values[:4], model_version, *values[4:-1], now_iso(), values[-1]))
                _event(conn, user, "phase3.predictive_alert.created", "duty", duty["id"], ip, {"alert_id": alert_id, "score": score, "factors": factors})
                created.append(_predictive_alert_item(conn.execute("SELECT * FROM phase3_predictive_alerts WHERE id = ?", (alert_id,)).fetchone()))
        return {"ok": True, "model_version": model_version, "evaluated_at": now_iso(), "created": len(created), "updated": len(updated), "skipped": skipped, "items": created + updated}
    feedback = re.fullmatch(r"/api/phase3/predictive-alerts/([^/]+)/(acknowledge|resolve|feedback)", route)
    if feedback and method == "POST":
        _phase3_permission(conn, user, "phase3.predictive.write", write=True)
        alert_id, action = feedback.groups()
        row = conn.execute("SELECT * FROM phase3_predictive_alerts WHERE id = ? AND organization_id = ?", (alert_id, org)).fetchone()
        if not row:
            raise DomainError(404, "Predictive alert not found", "not_found")
        if action == "feedback":
            outcome = _text(payload, "outcome", "unknown", 40)
            conn.execute("INSERT INTO phase3_alert_feedback(id, organization_id, alert_id, outcome, note, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (new_id("p3feedback"), org, alert_id, outcome, _text(payload, "note", "", 500), _user_id(user), now_iso()))
            return {"ok": True, "alert_id": alert_id, "outcome": outcome}
        status = "acknowledged" if action == "acknowledge" else "resolved"
        conn.execute("UPDATE phase3_predictive_alerts SET status = ?, acknowledged_by = COALESCE(?, acknowledged_by), acknowledged_at = CASE WHEN ? = 'acknowledged' THEN ? ELSE acknowledged_at END, resolved_at = CASE WHEN ? = 'resolved' THEN ? ELSE resolved_at END, updated_at = ? WHERE id = ? AND organization_id = ?", (status, _user_id(user), status, now_iso(), status, now_iso(), now_iso(), alert_id, org))
        _event(conn, user, f"phase3.predictive_alert.{action}", "predictive_alert", alert_id, ip, {"status": status})
        return {"ok": True, "item": _predictive_alert_item(conn.execute("SELECT * FROM phase3_predictive_alerts WHERE id = ?", (alert_id,)).fetchone())}
    return None


def _vendor_quality_graph(conn, user, method, route, query, payload, ip):
    org = _org(user)
    _phase3_permission(conn, user, "phase3.vendor_quality.read")
    if route == "/api/phase3/vendor-quality/graph" and method in {"GET", "POST"}:
        if method == "POST":
            _phase3_permission(conn, user, "phase3.vendor_quality.write", write=True)
        profiles = conn.execute("SELECT * FROM domain_network_vendor_profiles WHERE organization_id = ? ORDER BY vendor_name, id", (org,)).fetchall()
        total_orders_row = conn.execute("SELECT COUNT(*) AS count FROM domain_network_service_orders WHERE organization_id = ? AND status NOT IN ('cancelled','closed')", (org,)).fetchone()
        total_orders = int(total_orders_row["count"] or 0)
        nodes = []; edges = []; snapshots = []
        for profile in profiles:
            orders = conn.execute("SELECT * FROM domain_network_service_orders WHERE organization_id = ? AND vendor_profile_id = ? ORDER BY activated_at DESC", (org, profile["id"])).fetchall()
            order_ids = [row["id"] for row in orders]
            scorecards = []
            if order_ids:
                marks = ",".join("?" for _ in order_ids)
                scorecards = conn.execute(f"SELECT * FROM domain_network_scorecards WHERE organization_id = ? AND service_order_id IN ({marks}) ORDER BY period_start DESC", [org, *order_ids]).fetchall()
            metric_values = []
            source_ids = []
            on_time = []; completion = []; safety = []; response = []
            for scorecard in scorecards:
                metrics = _json(scorecard["metrics_json"], {})
                source_ids.append(scorecard["id"])
                for key, target in (("on_time", on_time), ("on_time_pct", on_time), ("completion", completion), ("completion_pct", completion), ("safety", safety), ("safety_score", safety), ("response", response), ("response_score", response)):
                    if metrics.get(key) is not None:
                        target.append(_clamp(_number(metrics.get(key), key, 0)))
            for values in (on_time, completion, safety, response):
                metric_values.extend(values)
            sample_size = len(scorecards)
            coverage = _clamp(35 + sample_size * 8)
            service_score = sum(metric_values) / len(metric_values) if metric_values else 70.0
            score = round(_clamp(service_score * 0.72 + coverage * 0.18 + (10 if orders else 0)), 2)
            confidence = "high" if sample_size >= 12 else "medium" if sample_size >= 4 else "cold_start"
            concentration = round(len(orders) / total_orders * 100, 2) if total_orders else 0
            metrics = {"on_time": round(sum(on_time) / len(on_time), 2) if on_time else None, "completion": round(sum(completion) / len(completion), 2) if completion else None, "safety": round(sum(safety) / len(safety), 2) if safety else None, "response": round(sum(response) / len(response), 2) if response else None, "coverage": round(coverage, 2), "service_score": round(service_score, 2), "concentration_pct": concentration}
            snapshot_key = "vendor-quality-v1"
            existing = conn.execute("SELECT id FROM phase3_vendor_quality_snapshots WHERE organization_id = ? AND vendor_profile_id = ? AND formula_version = ?", (org, profile["id"], snapshot_key)).fetchone()
            if existing:
                conn.execute("UPDATE phase3_vendor_quality_snapshots SET vendor_organization_id = ?, score = ?, confidence = ?, sample_size = ?, metrics_json = ?, source_event_ids_json = ?, computed_at = ? WHERE id = ?", (profile["vendor_organization_id"], score, confidence, sample_size, json.dumps(metrics), json.dumps(source_ids), now_iso(), existing["id"]))
                snapshot_id = existing["id"]
            else:
                snapshot_id = new_id("p3vq")
                conn.execute("INSERT INTO phase3_vendor_quality_snapshots(id, organization_id, vendor_profile_id, vendor_organization_id, formula_version, score, confidence, sample_size, metrics_json, source_event_ids_json, computed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (snapshot_id, org, profile["id"], profile["vendor_organization_id"], snapshot_key, score, confidence, sample_size, json.dumps(metrics), json.dumps(source_ids), now_iso()))
            node_id = f"vendor:{profile['id']}"
            nodes.append({"id": node_id, "type": "vendor", "label": profile["vendor_name"], "score": score, "confidence": confidence, "sample_size": sample_size, "concentration_pct": concentration, "status": profile["status"], "cities": _json(profile["cities_json"], [])})
            for order in orders:
                order_node = f"service_order:{order['id']}"
                nodes.append({"id": order_node, "type": "service_order", "label": order["id"], "status": order["status"]})
                edges.append({"from": node_id, "to": order_node, "type": "serves", "weight": 1, "evidence": {"service_order_id": order["id"]}})
                if order["fleet_duty_id"]:
                    duty_node = f"duty:{order['fleet_duty_id']}"
                    nodes.append({"id": duty_node, "type": "duty", "label": order["fleet_duty_id"], "status": "linked"})
                    edges.append({"from": order_node, "to": duty_node, "type": "fulfills", "weight": 1, "evidence": {"source": "fleet_handoff"}})
                for scorecard in scorecards:
                    if scorecard["service_order_id"] != order["id"]:
                        continue
                    scorecard_node = f"scorecard:{scorecard['id']}"
                    nodes.append({"id": scorecard_node, "type": "scorecard", "label": scorecard["id"], "status": scorecard["status"], "metrics": _json(scorecard["metrics_json"], {})})
                    edges.append({"from": order_node, "to": scorecard_node, "type": "measured_by", "weight": 1, "evidence": {"scorecard_id": scorecard["id"]}})
                    evidence = _json(scorecard["evidence_json"], {})
                    evidence_ids = evidence.get("source_event_ids", []) if isinstance(evidence, dict) else []
                    if isinstance(evidence_ids, list):
                        for evidence_id in evidence_ids[:50]:
                            evidence_node = f"evidence:{evidence_id}"
                            nodes.append({"id": evidence_node, "type": "evidence", "label": str(evidence_id), "status": "linked"})
                            edges.append({"from": scorecard_node, "to": evidence_node, "type": "supported_by", "weight": 1, "evidence": {"source": "scorecard_evidence"}})
            for city in _json(profile["cities_json"], []):
                region_node = f"region:{str(city).strip().lower().replace(' ', '-') }"
                nodes.append({"id": region_node, "type": "region", "label": city})
                edges.append({"from": node_id, "to": region_node, "type": "operates_in", "weight": 1, "evidence": {"source": "vendor_profile"}})
            snapshots.append({"id": snapshot_id, "vendor_profile_id": profile["id"], "score": score, "confidence": confidence, "sample_size": sample_size, "metrics": metrics})
        # De-duplicate graph nodes and persist the graph edges as an auditable projection.
        nodes = list({node["id"]: node for node in nodes}.values())
        edges = list({(edge["from"], edge["to"], edge["type"]): edge for edge in edges}.values())
        for edge in edges:
            edge_key = f"{edge['from']}:{edge['to']}:{edge['type']}"
            conn.execute("INSERT INTO phase3_vendor_quality_edges(id, organization_id, edge_key, from_type, from_id, to_type, to_id, edge_type, weight, evidence_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(organization_id, edge_key) DO UPDATE SET weight = excluded.weight, evidence_json = excluded.evidence_json, created_at = excluded.created_at", (new_id("p3edge"), org, edge_key, edge["from"].split(":", 1)[0], edge["from"].split(":", 1)[1], edge["to"].split(":", 1)[0], edge["to"].split(":", 1)[1], edge["type"], edge["weight"], json.dumps(edge["evidence"]), now_iso()))
        return {"ok": True, "formula_version": "vendor-quality-v1", "nodes": nodes, "edges": edges, "snapshots": snapshots, "count": len(nodes), "updated_at": now_iso()}
    vendor_match = re.fullmatch(r"/api/phase3/vendor-quality/vendors/([^/]+)", route)
    if vendor_match and method == "GET":
        vendor_id = vendor_match.group(1)
        row = conn.execute("SELECT * FROM phase3_vendor_quality_snapshots WHERE organization_id = ? AND (vendor_profile_id = ? OR vendor_organization_id = ?) ORDER BY computed_at DESC LIMIT 1", (org, vendor_id, vendor_id)).fetchone()
        if not row:
            raise DomainError(404, "Vendor quality snapshot not found", "not_found")
        return {"ok": True, "item": _row(row, ("metrics_json", "source_event_ids_json"))}
    return None


def _simulation_outputs(payload, region, quality_score=None):
    demand = _int(payload.get("demand_duties", payload.get("trips", 0)), "demand_duties", 0, 0)
    distance = _number(payload.get("avg_distance_km"), "avg_distance_km", 15, 0)
    duration = _number(payload.get("avg_duration_minutes"), "avg_duration_minutes", 45, 0)
    base_rate = _int(payload.get("base_rate_minor", payload.get("base_rate_paise", 1800)), "base_rate_minor", 1800, 0)
    fuel_rate = _int(payload.get("fuel_cost_per_km_minor", 18), "fuel_cost_per_km_minor", 18, 0)
    driver_rate = _int(payload.get("driver_cost_per_hour_minor", 320), "driver_cost_per_hour_minor", 320, 0)
    waiting_minutes = _number(payload.get("waiting_minutes"), "waiting_minutes", 8, 0)
    waiting_rate = _int(payload.get("waiting_cost_per_minute_minor", 6), "waiting_cost_per_minute_minor", 6, 0)
    service_penalty = _number(payload.get("service_penalty_pct"), "service_penalty_pct", 2.5, 0)
    capacity_per_duty = _number(payload.get("capacity_per_duty"), "capacity_per_duty", 4, 1)
    capacity_required = _number(payload.get("capacity_required"), "capacity_required", 1, 1)
    capacity_gap = max(0, capacity_required - capacity_per_duty)
    capacity_penalty = capacity_gap * 4
    effective_penalty = service_penalty + capacity_penalty
    carbon_price = _int(payload.get("carbon_price_per_kg_minor", 0), "carbon_price_per_kg_minor", 0, 0)
    emissions_factor = _number(payload.get("emissions_factor_kg_per_km"), "emissions_factor_kg_per_km", 0.192, 0)
    vendor_mix = payload.get("vendor_mix") if isinstance(payload.get("vendor_mix"), list) else []
    mix_cost = 0.0
    mix_total = 0.0
    for vendor in vendor_mix:
        if not isinstance(vendor, dict):
            continue
        share = _number(vendor.get("share"), "vendor_mix.share", 0, 0)
        cost = _int(vendor.get("cost_per_duty_minor"), "vendor_mix.cost_per_duty_minor", base_rate, 0)
        mix_total += share
        mix_cost += share * cost
    if mix_total > 0:
        vendor_cost = mix_cost / mix_total * demand
    else:
        vendor_cost = base_rate * demand
    base_total = base_rate * demand
    fuel_total = fuel_rate * distance * demand
    driver_total = driver_rate * duration / 60 * demand
    waiting_total = waiting_rate * waiting_minutes * demand
    carbon_total = carbon_price * emissions_factor * distance * demand
    service_risk_total = (base_total + vendor_cost) * effective_penalty / 100
    modeled = _round_minor(vendor_cost + fuel_total + driver_total + waiting_total + carbon_total + service_risk_total)
    baseline = _round_minor(base_total + fuel_total + driver_total + waiting_total)
    quality_adjustment = 0 if quality_score is None else round((70 - quality_score) * demand * base_rate / 1000)
    modeled += quality_adjustment
    service_level = _clamp(100 - effective_penalty - max(0, (70 - (quality_score or 70)) * 0.25))
    emissions = round(emissions_factor * distance * demand, 3)
    return {
        "currency": region["currency"] if region else str(payload.get("currency") or "INR"),
        "unit": "minor",
        "demand_duties": demand,
        "distance_km": round(distance * demand, 2),
        "baseline_total_minor": baseline,
        "modeled_total_minor": modeled,
        "delta_minor": modeled - baseline,
        "per_duty_minor": _round_minor(modeled / demand) if demand else 0,
        "service_level_pct": round(service_level, 2),
        "emissions_kg": emissions,
        "assumptions": {"avg_distance_km": distance, "avg_duration_minutes": duration, "base_rate_minor": base_rate, "vendor_rate_minor": _round_minor(vendor_cost / demand) if demand else base_rate, "vendor_mix": vendor_mix, "fuel_cost_per_km_minor": fuel_rate, "driver_cost_per_hour_minor": driver_rate, "waiting_minutes": waiting_minutes, "waiting_cost_per_minute_minor": waiting_rate, "service_penalty_pct": service_penalty, "capacity_per_duty": capacity_per_duty, "capacity_required": capacity_required, "capacity_gap": capacity_gap, "effective_service_penalty_pct": effective_penalty, "carbon_price_per_kg_minor": carbon_price, "emissions_factor_kg_per_km": emissions_factor, "quality_score": quality_score},
        "sensitivity": {"low_demand_total_minor": _round_minor(modeled * 0.9), "high_demand_total_minor": _round_minor(modeled * 1.1), "service_level_floor_pct": round(max(0, service_level - 5), 2)},
    }


def _simulations(conn, user, method, route, query, payload, ip):
    org = _org(user)
    if route.startswith("/api/phase3/simulations"):
        _phase3_permission(conn, user, "phase3.simulation.read")
    if route == "/api/phase3/simulations" and method == "GET":
        rows = conn.execute("SELECT * FROM phase3_simulations WHERE organization_id = ? ORDER BY created_at DESC LIMIT ?", (org, _limit(query))).fetchall()
        return {"ok": True, "items": [_row(row, ("inputs_json", "outputs_json")) for row in rows], "count": len(rows)}
    run_match = route in {"/api/phase3/simulations", "/api/phase3/simulations/run"} and method == "POST"
    if run_match:
        _phase3_permission(conn, user, "phase3.simulation.write", write=True)
        idempotency_key = _text(payload, "idempotency_key", "", 160) or None
        if idempotency_key:
            existing = conn.execute("SELECT * FROM phase3_simulations WHERE organization_id = ? AND idempotency_key = ?", (org, idempotency_key)).fetchone()
            if existing:
                return {"ok": True, "replayed": True, "item": _row(existing, ("inputs_json", "outputs_json"))}
        region = _ensure_default_region(conn, org)
        quality = None
        vendor_id = _text(payload, "vendor_profile_id", "", 160)
        if vendor_id:
            quality_row = conn.execute("SELECT score FROM phase3_vendor_quality_snapshots WHERE organization_id = ? AND vendor_profile_id = ? ORDER BY computed_at DESC LIMIT 1", (org, vendor_id)).fetchone()
            quality = float(quality_row["score"]) if quality_row else None
        outputs = _simulation_outputs(payload, region, quality)
        item_id = new_id("p3sim")
        conn.execute("INSERT INTO phase3_simulations(id, organization_id, scenario_name, status, model_version, idempotency_key, inputs_json, outputs_json, created_by, created_at) VALUES (?, ?, ?, 'completed', 'cost-service-v1', ?, ?, ?, ?, ?)", (item_id, org, _text(payload, "scenario_name", "Untitled scenario", 160), idempotency_key, json.dumps(payload), json.dumps(outputs), _user_id(user), now_iso()))
        _event(conn, user, "phase3.simulation.completed", "simulation", item_id, ip, outputs)
        return {"ok": True, "replayed": False, "item": _row(conn.execute("SELECT * FROM phase3_simulations WHERE id = ?", (item_id,)).fetchone(), ("inputs_json", "outputs_json"))}
    detail = re.fullmatch(r"/api/phase3/simulations/([^/]+)", route)
    if detail and method == "GET":
        row = conn.execute("SELECT * FROM phase3_simulations WHERE id = ? AND organization_id = ?", (detail.group(1), org)).fetchone()
        if not row:
            raise DomainError(404, "Simulation not found", "not_found")
        return {"ok": True, "item": _row(row, ("inputs_json", "outputs_json"))}
    if route == "/api/phase3/simulations/compare" and method == "POST":
        _phase3_permission(conn, user, "phase3.simulation.write", write=True)
        scenarios = payload.get("scenarios") if isinstance(payload.get("scenarios"), list) else []
        if not scenarios or len(scenarios) > 10:
            raise DomainError(400, "scenarios must contain between 1 and 10 entries", "validation_error")
        region = _ensure_default_region(conn, org)
        results = []
        for index, scenario in enumerate(scenarios):
            values = scenario if isinstance(scenario, dict) else {}
            results.append({"scenario_name": values.get("scenario_name") or f"Scenario {index + 1}", "outputs": _simulation_outputs(values, region)})
        return {"ok": True, "model_version": "cost-service-v1", "items": results}
    return None


def _variance_severity(pct):
    absolute = abs(float(pct))
    return "critical" if absolute >= 25 else "high" if absolute >= 10 else "medium" if absolute >= 3 else "low"


def _variance_scan(conn, user, payload, ip):
    org = _org(user)
    created = []; updated = []
    duties = _active_duties(conn, user) if _role(user) == "driver" else conn.execute("SELECT * FROM domain_duties WHERE organization_id = ? ORDER BY created_at DESC LIMIT 500", (org,)).fetchall()
    for duty in duties:
        snapshot = _json(duty["calculation_snapshot_json"], {})
        expected = int(snapshot.get("total_paise") or 0)
        invoice = conn.execute("SELECT id,total_paise FROM domain_invoices WHERE organization_id = ? AND duty_id = ? ORDER BY created_at DESC LIMIT 1", (org, duty["id"])).fetchone()
        if invoice and expected > 0 and int(invoice["total_paise"] or 0) != expected:
            observed = int(invoice["total_paise"] or 0); variance = observed - expected; pct = variance / expected * 100
            created_item = _upsert_variance(conn, user, "invoice_calculation", duty["id"], expected, observed, pct, {"invoice_id": invoice["id"], "duty_id": duty["id"]}, [invoice["id"], duty["id"]], ip)
            (updated if created_item.get("updated") else created).append(created_item["item"])
        expense = conn.execute("SELECT COALESCE(SUM(amount_paise),0) amount FROM domain_expenses WHERE organization_id = ? AND duty_id = ?", (org, duty["id"])).fetchone()
        expense_expected = int(_json(snapshot.get("inputs"), {}).get("expense_paise") or 0)
        expense_observed = int(expense["amount"] or 0)
        if expense_observed != expense_expected and (expense_observed or expense_expected):
            variance = expense_observed - expense_expected; pct = variance / max(1, expense_expected or expense_observed) * 100
            created_item = _upsert_variance(conn, user, "expense_snapshot", duty["id"], expense_expected, expense_observed, pct, {"expense_total_paise": expense_observed, "duty_id": duty["id"]}, [duty["id"]], ip)
            (updated if created_item.get("updated") else created).append(created_item["item"])
        eta = _latest_eta(conn, org, duty["id"])
        rated_distance = float(_json(snapshot.get("inputs"), {}).get("distance_km") or 0)
        gps_distance = float(eta["distance_km"] or 0) if eta else 0
        if eta and rated_distance > 0 and abs(gps_distance - rated_distance) >= max(5, rated_distance * 0.15):
            pct = (gps_distance - rated_distance) / rated_distance * 100
            created_item = _upsert_variance(conn, user, "gps_rated_distance", duty["id"], _round_minor(rated_distance * 100), _round_minor(gps_distance * 100), pct, {"rated_distance_km": rated_distance, "gps_distance_km": gps_distance, "eta_id": eta["id"]}, [eta["id"], duty["id"]], ip)
            (updated if created_item.get("updated") else created).append(created_item["item"])
        bill = conn.execute("SELECT id, total_paise FROM domain_supplier_bills WHERE organization_id = ? AND duty_id = ? ORDER BY created_at DESC LIMIT 1", (org, duty["id"])).fetchone()
        if bill and expected > 0 and int(bill["total_paise"] or 0) != expected:
            observed = int(bill["total_paise"] or 0); pct = (observed - expected) / expected * 100
            created_item = _upsert_variance(conn, user, "supplier_bill_rate", duty["id"], expected, observed, pct, {"supplier_bill_id": bill["id"], "duty_id": duty["id"]}, [bill["id"], duty["id"]], ip)
            (updated if created_item.get("updated") else created).append(created_item["item"])
    reconciliation_rows = conn.execute("SELECT id, service_order_id, expected_paise, observed_paise, evidence_json FROM phase12_reconciliations WHERE organization_id = ? AND expected_paise != observed_paise ORDER BY created_at DESC LIMIT 500", (org,)).fetchall()
    for reconciliation in reconciliation_rows:
        expected = int(reconciliation["expected_paise"] or 0); observed = int(reconciliation["observed_paise"] or 0); pct = (observed - expected) / max(1, expected or observed) * 100
        created_item = _upsert_variance(conn, user, "network_reconciliation", reconciliation["service_order_id"], expected, observed, pct, {"reconciliation_id": reconciliation["id"], "evidence": _json(reconciliation["evidence_json"], {})}, [reconciliation["id"]], ip)
        (updated if created_item.get("updated") else created).append(created_item["item"])
    scorecards = conn.execute("SELECT sc.id, sc.service_order_id, sc.metrics_json, so.vendor_profile_id FROM domain_network_scorecards sc JOIN domain_network_service_orders so ON so.id = sc.service_order_id WHERE sc.organization_id = ? ORDER BY sc.created_at DESC LIMIT 500", (org,)).fetchall()
    for scorecard in scorecards:
        metrics = _json(scorecard["metrics_json"], {}); on_time = metrics.get("on_time", metrics.get("on_time_pct"))
        if on_time is not None and float(on_time) < 90:
            expected = 90; observed = _round_minor(float(on_time)); pct = (observed - expected) / expected * 100
            created_item = _upsert_variance(conn, user, "scorecard_sla", scorecard["service_order_id"], expected, observed, pct, {"scorecard_id": scorecard["id"], "metric": "on_time", "observed": on_time}, [scorecard["id"]], ip)
            (updated if created_item.get("updated") else created).append(created_item["item"])
    return {"ok": True, "rule_version": "variance-v1", "evaluated_at": now_iso(), "created": len(created), "updated": len(updated), "items": created + updated}


def _upsert_variance(conn, user, variance_type, entity_id, expected, observed, pct, evidence, source_ids, ip):
    org = _org(user)
    scan_key = f"{variance_type}:{entity_id}:{date.today().isoformat()}"
    severity = _variance_severity(pct)
    existing = conn.execute("SELECT * FROM phase3_variance_findings WHERE organization_id = ? AND scan_key = ?", (org, scan_key)).fetchone()
    if existing:
        conn.execute("UPDATE phase3_variance_findings SET expected_paise = ?, observed_paise = ?, variance_paise = ?, variance_pct = ?, severity = ?, evidence_json = ?, source_event_ids_json = ?, updated_at = ? WHERE id = ?", (expected, observed, observed - expected, pct, severity, json.dumps(evidence), json.dumps(source_ids), now_iso(), existing["id"]))
        return {"updated": True, "item": _row(conn.execute("SELECT * FROM phase3_variance_findings WHERE id = ?", (existing["id"],)).fetchone(), ("evidence_json", "source_event_ids_json"))}
    item_id = new_id("p3var")
    conn.execute("INSERT INTO phase3_variance_findings(id, organization_id, scan_key, entity_type, entity_id, variance_type, severity, expected_paise, observed_paise, variance_paise, variance_pct, rule_version, evidence_json, source_event_ids_json, status, created_at, updated_at) VALUES (?, ?, ?, 'duty', ?, ?, ?, ?, ?, ?, ?, 'variance-v1', ?, ?, 'open', ?, ?)", (item_id, org, scan_key, entity_id, variance_type, severity, expected, observed, observed - expected, pct, json.dumps(evidence), json.dumps(source_ids), now_iso(), now_iso()))
    _event(conn, user, "phase3.variance.created", "duty", entity_id, ip, {"finding_id": item_id, "variance_type": variance_type, "variance_pct": pct})
    return {"updated": False, "item": _row(conn.execute("SELECT * FROM phase3_variance_findings WHERE id = ?", (item_id,)).fetchone(), ("evidence_json", "source_event_ids_json"))}


def _variance(conn, user, method, route, query, payload, ip):
    org = _org(user)
    _phase3_permission(conn, user, "phase3.variance.read")
    if route == "/api/phase3/variance/findings" and method == "GET":
        status = (query.get("status") or [""])[0]
        sql = "SELECT * FROM phase3_variance_findings WHERE organization_id = ?"; args = [org]
        if status and status != "all":
            sql += " AND status = ?"; args.append(status)
        sql += " ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END, created_at DESC LIMIT ?"; args.append(_limit(query))
        rows = conn.execute(sql, args).fetchall()
        return {"ok": True, "items": [_row(row, ("evidence_json", "source_event_ids_json")) for row in rows], "count": len(rows), "rule_version": "variance-v1"}
    if route == "/api/phase3/variance/evaluate" and method == "POST":
        _phase3_permission(conn, user, "phase3.variance.write", write=True)
        return _variance_scan(conn, user, payload, ip)
    finding_match = re.fullmatch(r"/api/phase3/variance/findings/([^/]+)/(assign|acknowledge|resolve)", route)
    if finding_match and method == "POST":
        _phase3_permission(conn, user, "phase3.variance.write", write=True)
        finding_id, action = finding_match.groups()
        if action == "assign":
            assignee = _text(payload, "assigned_to", _user_id(user), 160)
            updated = conn.execute("UPDATE phase3_variance_findings SET assigned_to = ?, assigned_at = ?, status = 'assigned', updated_at = ? WHERE id = ? AND organization_id = ?", (assignee, now_iso(), now_iso(), finding_id, org))
            status = "assigned"
        else:
            status = "acknowledged" if action == "acknowledge" else "resolved"
            updated = conn.execute("UPDATE phase3_variance_findings SET status = ?, resolved_at = CASE WHEN ? = 'resolved' THEN ? ELSE resolved_at END, updated_at = ? WHERE id = ? AND organization_id = ?", (status, status, now_iso(), now_iso(), finding_id, org))
        if updated.rowcount == 0:
            raise DomainError(404, "Variance finding not found", "not_found")
        _event(conn, user, f"phase3.variance.{action}", "variance_finding", finding_id, ip, {"status": status, "assigned_to": payload.get("assigned_to")})
        return {"ok": True, "item": _row(conn.execute("SELECT * FROM phase3_variance_findings WHERE id = ?", (finding_id,)).fetchone(), ("evidence_json", "source_event_ids_json"))}
    return None


def _charging_station_candidates(conn, organization_id, region_code, connector=""):
    rows = conn.execute(
        "SELECT * FROM phase3_charging_stations WHERE organization_id = ? AND region_code = ? AND status = 'active' ORDER BY available_ports DESC, name",
        (organization_id, region_code),
    ).fetchall()
    if not connector:
        return rows
    matching = []
    for row in rows:
        connectors = _json(row["connector_types_json"], [])
        if connector in connectors:
            matching.append(row)
    return matching


def _ev_metrics(conn, organization_id, vehicle, payload, distance, passenger_count, region_code):
    is_ev = bool(vehicle and (vehicle["ev_eligible"] or str(vehicle["fuel_type"] or "").lower() in {"ev", "electric"}))
    vehicle_status = str(vehicle["status"] or "unknown").lower() if vehicle else "missing"
    if not is_ev:
        return {
            "is_ev": False,
            "vehicle_status": vehicle_status,
            "operational_constraint": None,
            "eligibility_status": "not_applicable",
            "eligibility_reasons": [],
            "charging_available": False,
            "charging_station_id": None,
            "range_required_km": 0,
            "range_remaining_km": None,
            "energy_kwh": 0,
            "energy_cost_minor": 0,
            "energy_price_per_kwh_minor": 0,
            "emissions_kg": round(distance * float(EMISSION_FACTORS.get(str(vehicle["fuel_type"] or "petrol").lower(), EMISSION_FACTORS["petrol"])), 3),
            "baseline_emissions_kg": 0,
            "avoided_emissions_kg": 0,
            "emissions_per_passenger_km_g": 0,
            "grid_factor_kg_per_kwh": 0,
        }
    connector = str(payload.get("charging_connector") or vehicle["charging_connector"] or "").strip()
    stations = _charging_station_candidates(conn, organization_id, region_code, connector)
    requested_station_id = _text(payload, "charging_station_id", "", 160) or None
    station = next((item for item in stations if item["id"] == requested_station_id), None) if requested_station_id else (stations[0] if stations else None)
    if requested_station_id and station is None:
        station = conn.execute("SELECT * FROM phase3_charging_stations WHERE organization_id = ? AND id = ?", (organization_id, requested_station_id)).fetchone()
    charging_available = bool(station and station["status"] == "active" and int(station["available_ports"] or 0) > 0)
    reserve_pct = max(0.0, _number(payload.get("reserve_pct"), "reserve_pct", DEFAULT_EV_RESERVE_PCT, 0))
    deadhead = max(0.0, _number(payload.get("deadhead_km"), "deadhead_km", 0, 0))
    range_required = round((distance + deadhead) * (1 + reserve_pct / 100), 3)
    usable_range = _number(payload.get("usable_range_km"), "usable_range_km", float(vehicle["usable_range_km"] or 0) if vehicle and vehicle["usable_range_km"] is not None else 0, 0)
    range_remaining = _number(payload.get("range_remaining_km"), "range_remaining_km", usable_range, 0)
    capacity = int(vehicle["seating_capacity"] or 0) if vehicle else 0
    consumption = _number(payload.get("energy_consumption_kwh_per_km"), "energy_consumption_kwh_per_km", float(vehicle["energy_consumption_kwh_per_km"] or DEFAULT_EV_CONSUMPTION_KWH_PER_KM), 0)
    price = _int(payload.get("energy_price_per_kwh_minor"), "energy_price_per_kwh_minor", int(vehicle["energy_price_per_kwh_minor"] or (station["energy_price_per_kwh_minor"] if station else DEFAULT_ENERGY_PRICE_MINOR)), 0)
    grid_factor = _number(payload.get("grid_factor_kg_per_kwh"), "grid_factor_kg_per_kwh", float(GRID_FACTOR_KG_PER_KWH), 0)
    baseline_factor = _number(payload.get("baseline_factor_kg_per_km"), "baseline_factor_kg_per_km", float(EMISSION_FACTORS["petrol"]), 0)
    energy_kwh = round(distance * consumption, 3)
    energy_cost = _round_minor(Decimal(str(energy_kwh)) * Decimal(price))
    emissions = round(energy_kwh * grid_factor, 3)
    baseline_emissions = round(distance * baseline_factor, 3)
    avoided = round(max(0.0, baseline_emissions - emissions), 3)
    passenger_km = max(0.001, distance * max(1, passenger_count))
    reasons = []
    operational_constraint = None
    if vehicle_status in {"inactive", "archived", "retired"}:
        operational_constraint = "Vehicle is not operationally available"
        reasons.append(operational_constraint)
    if capacity < passenger_count:
        reasons.append(f"Vehicle seats {capacity}; {passenger_count} passengers requested")
    range_sufficient = range_remaining >= range_required
    if not range_sufficient:
        if charging_available:
            reasons.append("A charging stop is required before the duty can complete")
        else:
            reasons.append("Usable range is below the duty distance plus reserve")
    if not charging_available and not range_sufficient:
        reasons.append("No active charging station with an available port was found in the selected region")
    if station and connector and connector not in _json(station["connector_types_json"], []):
        reasons.append("Selected charging station does not list the vehicle connector")
    if range_sufficient:
        reasons.append("Range covers the duty distance and reserve")
    status = "eligible"
    if vehicle_status in {"inactive", "archived", "retired"} or capacity < passenger_count or (not range_sufficient and not charging_available):
        status = "ineligible"
    elif not range_sufficient and charging_available:
        status = "eligible_with_charge"
    return {
        "is_ev": True,
        "vehicle_status": vehicle_status,
        "operational_constraint": operational_constraint,
        "eligibility_status": status,
        "eligibility_reasons": reasons,
        "charging_available": charging_available,
        "charging_station_id": station["id"] if station else None,
        "charging_station": _row(station, ("connector_types_json", "operating_hours_json")) if station else None,
        "range_required_km": range_required,
        "range_remaining_km": range_remaining,
        "energy_kwh": energy_kwh,
        "energy_cost_minor": energy_cost,
        "energy_price_per_kwh_minor": price,
        "emissions_kg": emissions,
        "baseline_emissions_kg": baseline_emissions,
        "avoided_emissions_kg": avoided,
        "emissions_per_passenger_km_g": round(emissions * 1000 / passenger_km, 3),
        "grid_factor_kg_per_kwh": grid_factor,
        "consumption_kwh_per_km": consumption,
        "passenger_km": round(passenger_km, 3),
    }


def _ev_eligibility(conn, user, payload, ip):
    org = _org(user)
    vehicle_id = _text(payload, "vehicle_id", "", 160)
    if not vehicle_id:
        raise DomainError(400, "vehicle_id is required", "validation_error")
    vehicle = _vehicle(conn, org, vehicle_id)
    if not vehicle:
        raise DomainError(404, "Vehicle not found", "not_found")
    distance = _number(payload.get("distance_km"), "distance_km", 0, 0)
    passenger_count = _int(payload.get("passenger_count"), "passenger_count", 1, 1)
    region = _ensure_default_region(conn, org)
    region_code = _text(payload, "region_code", region["region_code"], 24).upper()
    metrics = _ev_metrics(conn, org, vehicle, payload, distance, passenger_count, region_code)
    result = {
        "vehicle_id": vehicle_id,
        "registration_number": vehicle["registration_number"],
        "region_code": region_code,
        "distance_km": distance,
        "passenger_count": passenger_count,
        "vehicle_capacity": int(vehicle["seating_capacity"] or 0),
        "usable_range_km": float(vehicle["usable_range_km"] or 0) if vehicle["usable_range_km"] is not None else None,
        "ev_eligible": metrics["is_ev"],
        **metrics,
        "formula_version": "sustainability-v2",
    }
    _event(conn, user, "phase3.sustainability.ev_eligibility", "vehicle", vehicle_id, ip, result)
    result["audit_reference"] = conn.execute("SELECT id FROM audit_events WHERE user_id = ? ORDER BY rowid DESC LIMIT 1", (_user_id(user),)).fetchone()["id"]
    return {"ok": True, "item": result}


def _sustainability_trip(conn, user, duty_id, payload, ip):
    org = _org(user)
    duty = conn.execute("SELECT * FROM domain_duties WHERE organization_id = ? AND id = ?", (org, duty_id)).fetchone()
    if not duty:
        raise DomainError(404, "Duty not found", "not_found")
    vehicle = _vehicle(conn, org, duty["vehicle_id"])
    fuel_type = str(payload.get("fuel_type") or (vehicle["fuel_type"] if vehicle else "petrol") or "petrol").lower()
    eta = _latest_eta(conn, org, duty_id)
    snapshot = _json(duty["calculation_snapshot_json"], {})
    distance = _number(payload.get("distance_km"), "distance_km", float(eta["distance_km"] if eta else _json(snapshot.get("inputs"), {}).get("distance_km") or 0), 0)
    passenger_count = _int(payload.get("passenger_count"), "passenger_count", 1, 1)
    region = _ensure_default_region(conn, org)
    region_code = _text(payload, "region_code", region["region_code"], 24).upper()
    factor = _number(payload.get("factor_kg_per_km"), "factor_kg_per_km", float(EMISSION_FACTORS.get(fuel_type, EMISSION_FACTORS["petrol"])), 0)
    ev_metrics = _ev_metrics(conn, org, vehicle, payload, distance, passenger_count, region_code)
    if ev_metrics["is_ev"]:
        emissions = ev_metrics["emissions_kg"]
        energy_kwh = ev_metrics["energy_kwh"]
        energy_cost = ev_metrics["energy_cost_minor"]
        price = ev_metrics["energy_price_per_kwh_minor"]
        baseline_emissions = ev_metrics["baseline_emissions_kg"]
        avoided = ev_metrics["avoided_emissions_kg"]
        per_passenger_km = ev_metrics["emissions_per_passenger_km_g"]
        grid_factor = ev_metrics["grid_factor_kg_per_kwh"]
        range_required = ev_metrics["range_required_km"]
        range_remaining = ev_metrics["range_remaining_km"]
        charging_station_id = ev_metrics["charging_station_id"]
        charging_available = 1 if ev_metrics["charging_available"] else 0
        eligibility_status = ev_metrics["eligibility_status"]
        eligibility_reasons = ev_metrics["eligibility_reasons"]
    else:
        emissions = round(distance * factor, 3)
        energy_kwh = _number(payload.get("energy_kwh"), "energy_kwh", 0, 0)
        price = _int(payload.get("energy_price_per_kwh_minor"), "energy_price_per_kwh_minor", 0, 0)
        energy_cost = _round_minor(Decimal(str(energy_kwh)) * Decimal(price)) if energy_kwh and price else 0
        baseline_emissions = 0
        avoided = 0
        per_passenger_km = round(emissions * 1000 / max(0.001, distance * passenger_count), 3)
        grid_factor = 0
        range_required = 0
        range_remaining = None
        charging_station_id = None
        charging_available = 0
        eligibility_status = "not_applicable"
        eligibility_reasons = []
    source_ids = [duty_id]
    if eta:
        source_ids.append(eta["id"])
    factor_version = _text(payload, "factor_version", "factor-v1", 40) or "factor-v1"
    existing = conn.execute("SELECT id FROM phase3_sustainability_trips WHERE organization_id = ? AND duty_id = ? AND factor_version = ?", (org, duty_id, factor_version)).fetchone()
    values = (
        vehicle["id"] if vehicle else duty["vehicle_id"], region_code, fuel_type, distance, passenger_count,
        energy_kwh, energy_cost, price, emissions, per_passenger_km, baseline_emissions, avoided, factor,
        grid_factor, range_required, range_remaining, charging_station_id, charging_available,
        eligibility_status, json.dumps(eligibility_reasons), json.dumps(source_ids), now_iso(),
    )
    if existing:
        conn.execute("""UPDATE phase3_sustainability_trips SET vehicle_id = ?, region_code = ?, fuel_type = ?, distance_km = ?, passenger_count = ?, energy_kwh = ?, energy_cost_minor = ?, energy_price_per_kwh_minor = ?, emissions_kg = ?, emissions_per_passenger_km_g = ?, baseline_emissions_kg = ?, avoided_emissions_kg = ?, factor_kg_per_km = ?, grid_factor_kg_per_kwh = ?, range_required_km = ?, range_remaining_km = ?, charging_station_id = ?, charging_available = ?, ev_eligibility_status = ?, ev_eligibility_reasons_json = ?, source_event_ids_json = ?, calculated_at = ? WHERE id = ?""", (*values, existing["id"]))
        trip_id = existing["id"]
    else:
        trip_id = new_id("p3trip")
        conn.execute("""INSERT INTO phase3_sustainability_trips(id, organization_id, duty_id, vehicle_id, region_code, fuel_type, distance_km, passenger_count, energy_kwh, energy_cost_minor, energy_price_per_kwh_minor, emissions_kg, emissions_per_passenger_km_g, baseline_emissions_kg, avoided_emissions_kg, factor_kg_per_km, grid_factor_kg_per_kwh, factor_version, range_required_km, range_remaining_km, charging_station_id, charging_available, ev_eligibility_status, ev_eligibility_reasons_json, source_event_ids_json, calculated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (trip_id, org, duty_id, *values[:14], factor_version, *values[14:]))
    return _row(conn.execute("SELECT * FROM phase3_sustainability_trips WHERE id = ?", (trip_id,)).fetchone(), ("ev_eligibility_reasons_json", "source_event_ids_json"))

def _query_value(query, key, default=""):
    value = query.get(key, [default]) if isinstance(query, dict) else default
    return str(value[0] if isinstance(value, list) else value or default)


def _sustainability_rows(conn, organization_id, query):
    clauses = ["t.organization_id = ?"]
    args = [organization_id]
    period_start = _query_value(query, "period_start")
    period_end = _query_value(query, "period_end")
    region_code = _query_value(query, "region_code")
    fuel_type = _query_value(query, "fuel_type")
    service_at = "COALESCE(d.reporting_at, t.calculated_at)"
    if period_start:
        clauses.append(f"{service_at} >= ?")
        args.append(period_start)
    if period_end:
        clauses.append(f"{service_at} < ?")
        args.append(period_end + "T23:59:59Z")
    if region_code:
        clauses.append("t.region_code = ?")
        args.append(region_code)
    if fuel_type:
        clauses.append("t.fuel_type = ?")
        args.append(fuel_type)
    return conn.execute(f"SELECT t.* FROM phase3_sustainability_trips t LEFT JOIN domain_duties d ON d.id = t.duty_id AND d.organization_id = t.organization_id WHERE {' AND '.join(clauses)} ORDER BY {service_at} DESC, t.calculated_at DESC", args).fetchall()


def _sustainability_summary(rows, region, target):
    total_distance = round(sum(float(row["distance_km"] or 0) for row in rows), 3)
    total_emissions = round(sum(float(row["emissions_kg"] or 0) for row in rows), 3)
    total_energy = round(sum(float(row["energy_kwh"] or 0) for row in rows), 3)
    total_energy_cost = sum(int(row["energy_cost_minor"] or 0) for row in rows)
    passenger_km = round(sum(float(row["distance_km"] or 0) * max(1, int(row["passenger_count"] or 1)) for row in rows), 3)
    avoided = round(sum(float(row["avoided_emissions_kg"] or 0) for row in rows), 3)
    by_fuel = {}
    by_region = {}
    for row in rows:
        fuel = row["fuel_type"]
        fuel_bucket = by_fuel.setdefault(fuel, {"fuel_type": fuel, "distance_km": 0, "energy_kwh": 0, "energy_cost_minor": 0, "emissions_kg": 0, "avoided_emissions_kg": 0, "trips": 0})
        fuel_bucket["distance_km"] += float(row["distance_km"] or 0)
        fuel_bucket["energy_kwh"] += float(row["energy_kwh"] or 0)
        fuel_bucket["energy_cost_minor"] += int(row["energy_cost_minor"] or 0)
        fuel_bucket["emissions_kg"] += float(row["emissions_kg"] or 0)
        fuel_bucket["avoided_emissions_kg"] += float(row["avoided_emissions_kg"] or 0)
        fuel_bucket["trips"] += 1
        key = row["region_code"] or region["region_code"]
        region_bucket = by_region.setdefault(key, {"region_code": key, "distance_km": 0, "passenger_km": 0, "energy_kwh": 0, "energy_cost_minor": 0, "emissions_kg": 0, "avoided_emissions_kg": 0, "trips": 0})
        region_bucket["distance_km"] += float(row["distance_km"] or 0)
        region_bucket["passenger_km"] += float(row["distance_km"] or 0) * max(1, int(row["passenger_count"] or 1))
        region_bucket["energy_kwh"] += float(row["energy_kwh"] or 0)
        region_bucket["energy_cost_minor"] += int(row["energy_cost_minor"] or 0)
        region_bucket["emissions_kg"] += float(row["emissions_kg"] or 0)
        region_bucket["avoided_emissions_kg"] += float(row["avoided_emissions_kg"] or 0)
        region_bucket["trips"] += 1
    for value in [*by_fuel.values(), *by_region.values()]:
        for key in ("distance_km", "passenger_km", "energy_kwh", "emissions_kg", "avoided_emissions_kg"):
            if key in value:
                value[key] = round(value[key], 3)
    target_item = _row(target) if target else None
    if target_item:
        target_item["progress_pct"] = round(total_emissions / max(0.001, float(target["target_kg"])) * 100, 2)
    ev_rows = [row for row in rows if str(row["fuel_type"] or "").lower() in {"ev", "electric"}]
    ev_distance = sum(float(row["distance_km"] or 0) for row in ev_rows)
    ev_eligible = sum(1 for row in rows if row["ev_eligibility_status"] in {"eligible", "eligible_with_charge"})
    charging_available = sum(1 for row in rows if row["charging_available"])
    range_constrained = sum(1 for row in rows if row["ev_eligibility_status"] == "eligible_with_charge")
    return {
        "region": _row(region),
        "trips": len(rows),
        "total_distance_km": total_distance,
        "total_passenger_km": passenger_km,
        "total_energy_kwh": total_energy,
        "total_energy_cost_minor": total_energy_cost,
        "total_emissions_kg": total_emissions,
        "emissions_per_passenger_km_g": round(total_emissions * 1000 / max(0.001, passenger_km), 3),
        "total_avoided_emissions_kg": avoided,
        "average_emissions_kg": round(total_emissions / len(rows), 3) if rows else 0,
        "electric_distance_share_pct": round(ev_distance / max(0.001, total_distance) * 100, 2),
        "ev_trips": len(ev_rows),
        "ev_eligible_trips": ev_eligible,
        "charging_available_trips": charging_available,
        "range_constrained_trips": range_constrained,
        "by_fuel": list(by_fuel.values()),
        "by_region": list(by_region.values()),
        "target": target_item,
        "factor_version": "factor-v1",
        "reporting_version": "sustainability-report-v2",
        "recommendations": (
            ([{"code": "electrify_high_utilization", "priority": "medium", "message": "Pilot EV allocation on high-distance duty clusters to reduce energy and tailpipe emissions."}] if total_distance > 0 and (not rows or len(ev_rows) / len(rows) < 0.2) else [])
            + ([{"code": "secure_charging_capacity", "priority": "high", "message": "Add or reserve charging capacity for EV duties that require a charging stop."}] if range_constrained and charging_available < range_constrained else [])
            + ([{"code": "reduce_empty_km", "priority": "high", "message": "Review route bundling and deadhead distance before adding fleet capacity."}] if rows and total_emissions / max(1, len(rows)) > 3 else [])
        ),
    }


def _sustainability(conn, user, method, route, query, payload, ip):
    org = _org(user)
    _phase3_permission(conn, user, "phase3.sustainability.read")
    station_match = re.fullmatch(r"/api/phase3/sustainability/charging-stations/([^/]+)", route)
    if station_match:
        station_id = station_match.group(1); station = conn.execute("SELECT * FROM phase3_charging_stations WHERE id = ? AND organization_id = ?", (station_id, org)).fetchone()
        if not station: raise DomainError(404, "Charging station not found", "not_found")
        if method == "GET": return {"ok": True, "item": _row(station, ("connector_types_json", "operating_hours_json"))}
        _phase3_permission(conn, user, "phase3.sustainability.write", write=True)
        if method in {"PATCH", "DELETE"}:
            updates = {}
            if method == "DELETE": updates = {"status": "inactive"}
            else:
                for field in ("name", "location_label", "power_kw", "energy_price_per_kwh_minor", "status", "total_ports", "available_ports"):
                    if field in payload: updates[field] = payload[field]
                if "connector_types" in payload and isinstance(payload["connector_types"], list): updates["connector_types_json"] = json.dumps([str(item) for item in payload["connector_types"][:10]])
                if "operating_hours" in payload and isinstance(payload["operating_hours"], dict): updates["operating_hours_json"] = json.dumps(payload["operating_hours"])
            if "total_ports" in updates and int(updates["total_ports"]) < 0: raise DomainError(400, "total_ports cannot be negative", "validation_error")
            if "available_ports" in updates and int(updates["available_ports"]) < 0: raise DomainError(400, "available_ports cannot be negative", "validation_error")
            total = int(updates.get("total_ports", station["total_ports"])); available = int(updates.get("available_ports", station["available_ports"]))
            if available > total: raise DomainError(400, "available_ports cannot exceed total_ports", "validation_error")
            if updates:
                updates["updated_at"] = now_iso(); conn.execute(f"UPDATE phase3_charging_stations SET {', '.join(f'{key} = ?' for key in updates)} WHERE id = ? AND organization_id = ?", [*updates.values(), station_id, org])
            updated = conn.execute("SELECT * FROM phase3_charging_stations WHERE id = ?", (station_id,)).fetchone(); event_id = _event(conn, user, "phase3.sustainability.charging_station.updated", "charging_station", station_id, ip, {"status": updated["status"]})
            return {"ok": True, "item": _row(updated, ("connector_types_json", "operating_hours_json")), "audit_reference": event_id}
    if route == "/api/phase3/sustainability/charging-stations" and method == "GET":
        region_code = _query_value(query, "region_code")
        status_filter = _query_value(query, "status")
        clauses = ["organization_id = ?"]; args: list[object] = [org]
        if region_code: clauses.append("region_code = ?"); args.append(region_code)
        if status_filter and status_filter != "all": clauses.append("status = ?"); args.append(status_filter)
        args.append(_limit(query)); rows = conn.execute(f"SELECT * FROM phase3_charging_stations WHERE {' AND '.join(clauses)} ORDER BY region_code, name LIMIT ?", args).fetchall()
        return {"ok": True, "items": [_row(row, ("connector_types_json", "operating_hours_json")) for row in rows], "count": len(rows), "result_count": len(rows)}
    if route == "/api/phase3/sustainability/charging-stations" and method == "POST":
        _phase3_permission(conn, user, "phase3.sustainability.write", write=True)
        station_id = new_id("charge")
        region_code = _text(payload, "region_code", "", 24).upper()
        if region_code not in {item["region_code"] for item in REGION_CATALOG}:
            raise DomainError(400, "Select a region from the controlled catalog", "validation_error")
        connectors = payload.get("connector_types") if isinstance(payload.get("connector_types"), list) else ["CCS2"]
        total_ports = _int(payload.get("total_ports"), "total_ports", 1, 1)
        available_ports = _int(payload.get("available_ports"), "available_ports", total_ports, 0)
        if available_ports > total_ports:
            raise DomainError(400, "available_ports cannot exceed total_ports", "validation_error")
        conn.execute("INSERT INTO phase3_charging_stations(id, organization_id, region_code, name, location_label, connector_types_json, total_ports, available_ports, power_kw, energy_price_per_kwh_minor, status, operating_hours_json, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (station_id, org, region_code, _text(payload, "name", "Charging station", 160), _text(payload, "location_label", "", 200), json.dumps([str(item) for item in connectors[:10]]), total_ports, available_ports, _number(payload.get("power_kw"), "power_kw", 0, 0), _int(payload.get("energy_price_per_kwh_minor"), "energy_price_per_kwh_minor", DEFAULT_ENERGY_PRICE_MINOR, 0), _text(payload, "status", "active", 24), json.dumps(payload.get("operating_hours") if isinstance(payload.get("operating_hours"), dict) else {}), _user_id(user), now_iso(), now_iso()))
        event_id = _event(conn, user, "phase3.sustainability.charging_station.created", "charging_station", station_id, ip, {"region_code": region_code})
        item = _row(conn.execute("SELECT * FROM phase3_charging_stations WHERE id = ?", (station_id,)).fetchone(), ("connector_types_json", "operating_hours_json"))
        return {"ok": True, "item": item, "audit_reference": event_id}
    if route == "/api/phase3/sustainability/ev-eligibility" and method == "POST":
        _phase3_permission(conn, user, "phase3.sustainability.read")
        return _ev_eligibility(conn, user, payload, ip)
    if route in {"/api/phase3/sustainability/summary", "/api/phase3/sustainability/report"} and method == "GET":
        region = _ensure_default_region(conn, org)
        rows = _sustainability_rows(conn, org, query)
        target = conn.execute("SELECT * FROM phase3_sustainability_targets WHERE organization_id = ? AND status = 'active' ORDER BY period_end DESC LIMIT 1", (org,)).fetchone()
        result = _sustainability_summary(rows, region, target)
        result.update({"ok": True, "generated_at": now_iso(), "period_start": _query_value(query, "period_start") or None, "period_end": _query_value(query, "period_end") or None})
        if route.endswith("/report"):
            result["report_type"] = "fleet_sustainability"
            result["audit_reference"] = _event(conn, user, "phase3.sustainability.report.generated", "sustainability_report", None, ip, {"period_start": result["period_start"], "period_end": result["period_end"], "trips": result["trips"]})
        return result
    if route == "/api/phase3/sustainability/trips" and method == "GET":
        rows = _sustainability_rows(conn, org, query)
        return {"ok": True, "items": [_row(row, ("ev_eligibility_reasons_json", "source_event_ids_json")) for row in rows[:_limit(query)]], "count": min(len(rows), _limit(query)), "result_count": min(len(rows), _limit(query))}
    if route == "/api/phase3/sustainability/trips" and method == "POST":
        _phase3_permission(conn, user, "phase3.sustainability.write", write=True)
        duty_ids = payload.get("duty_ids") if isinstance(payload.get("duty_ids"), list) else ([payload.get("duty_id")] if payload.get("duty_id") else [])
        if not duty_ids:
            raise DomainError(400, "duty_id or duty_ids is required", "validation_error")
        items = []
        for duty_id in duty_ids[:200]:
            item = _sustainability_trip(conn, user, str(duty_id), payload, ip)
            event_id = _event(conn, user, "phase3.sustainability.trip.calculated", "sustainability_trip", item["id"], ip, {"duty_id": duty_id, "factor_version": item["factor_version"]})
            item["audit_reference"] = event_id
            items.append(item)
        return {"ok": True, "items": items, "count": len(items), "factor_version": payload.get("factor_version") or "factor-v1"}
    if route == "/api/phase3/sustainability/targets" and method == "GET":
        rows = conn.execute("SELECT * FROM phase3_sustainability_targets WHERE organization_id = ? ORDER BY period_end DESC", (org,)).fetchall()
        return {"ok": True, "items": [_row(row) for row in rows], "count": len(rows), "result_count": len(rows)}
    if route == "/api/phase3/sustainability/targets" and method == "POST":
        _phase3_permission(conn, user, "phase3.sustainability.write", write=True)
        start = _iso_date(payload.get("period_start"), "period_start", date.today().replace(day=1).isoformat())
        end = _iso_date(payload.get("period_end"), "period_end", date.today().isoformat())
        if end < start:
            raise DomainError(400, "period_end must be on or after period_start", "validation_error")
        baseline = _number(payload.get("baseline_kg"), "baseline_kg", 0, 0); target = _number(payload.get("target_kg"), "target_kg", baseline, 0)
        item_id = new_id("p3target")
        scope = _text(payload, "scope", "fleet", 60)
        conn.execute("INSERT INTO phase3_sustainability_targets(id, organization_id, scope, period_start, period_end, baseline_kg, target_kg, status, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ? ) ON CONFLICT(organization_id, scope, period_start, period_end) DO UPDATE SET baseline_kg = excluded.baseline_kg, target_kg = excluded.target_kg, status = 'active'", (item_id, org, scope, start, end, baseline, target, _user_id(user), now_iso()))
        row = conn.execute("SELECT * FROM phase3_sustainability_targets WHERE organization_id = ? AND scope = ? AND period_start = ? AND period_end = ?", (org, scope, start, end)).fetchone()
        event_id = _event(conn, user, "phase3.sustainability.target.saved", "sustainability_target", row["id"], ip, {"scope": scope, "period_start": start, "period_end": end})
        return {"ok": True, "item": _row(row), "audit_reference": event_id}
    return None

def _effective_region_dates(payload):
    effective_from = _iso_date(payload.get("effective_from"), "effective_from") if payload.get("effective_from") else None
    effective_to = _iso_date(payload.get("effective_to"), "effective_to") if payload.get("effective_to") else None
    if effective_from and effective_to and effective_from > effective_to:
        raise DomainError(400, "effective_to must be on or after effective_from", "validation_error")
    return effective_from, effective_to


def _regions(conn, user, method, route, query, payload, ip):
    org = _org(user)
    _phase3_permission(conn, user, "phase3.regions.read")
    if route == "/api/phase3/regions" and method == "GET":
        _ensure_default_region(conn, org)
        rows = conn.execute("SELECT * FROM phase3_regions WHERE organization_id = ? ORDER BY is_default DESC, name", (org,)).fetchall()
        return {"ok": True, "items": [_row(row, ("metadata_json",)) for row in rows], "catalog": REGION_CATALOG, "count": len(rows)}
    if route == "/api/phase3/regions" and method == "POST":
        _phase3_permission(conn, user, "phase3.regions.write", write=True)
        country = _text(payload, "country_code", "", 2).upper(); code = _text(payload, "region_code", "", 24).upper()
        if not code:
            raise DomainError(400, "region_code is required", "validation_error")
        match = next((item for item in REGION_CATALOG if item["region_code"] == code), None)
        if not match:
            raise DomainError(400, "Select a region from the controlled catalog", "validation_error")
        country = match["country_code"]
        profile = {**match, **{key: payload[key] for key in ("name", "currency", "timezone", "locale", "tax_regime", "distance_unit") if payload.get(key)}}
        for key in ("name", "currency", "timezone", "locale", "tax_regime"):
            if not profile.get(key):
                raise DomainError(400, f"{key} is required", "validation_error")
        effective_from, effective_to = _effective_region_dates(payload)
        is_default = 1 if payload.get("is_default") else 0
        if is_default:
            conn.execute("UPDATE phase3_regions SET is_default = 0 WHERE organization_id = ?", (org,))
        item_id = new_id("region3")
        conn.execute("INSERT INTO phase3_regions(id, organization_id, country_code, region_code, name, currency, timezone, locale, tax_regime, distance_unit, effective_from, effective_to, is_default, status, metadata_json, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)", (item_id, org, country, code, profile["name"], str(profile["currency"]).upper(), profile["timezone"], profile["locale"], profile["tax_regime"], profile.get("distance_unit", "km"), effective_from, effective_to, is_default, json.dumps(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}), _user_id(user), now_iso(), now_iso()))
        _event(conn, user, "phase3.region.created", "region", item_id, ip, {"region_code": code})
        return {"ok": True, "item": _row(conn.execute("SELECT * FROM phase3_regions WHERE id = ?", (item_id,)).fetchone(), ("metadata_json",))}
    region_match = re.fullmatch(r"/api/phase3/regions/([^/]+)", route)
    if region_match and method == "PATCH":
        _phase3_permission(conn, user, "phase3.regions.write", write=True)
        region_id = region_match.group(1)
        row = conn.execute("SELECT * FROM phase3_regions WHERE id = ? AND organization_id = ?", (region_id, org)).fetchone()
        if not row:
            raise DomainError(404, "Region not found", "not_found")
        if payload.get("is_default"):
            conn.execute("UPDATE phase3_regions SET is_default = 0 WHERE organization_id = ?", (org,))
        effective_from, effective_to = _effective_region_dates(payload)
        updates = {key: payload[key] for key in ("name", "currency", "timezone", "locale", "tax_regime", "distance_unit", "status") if payload.get(key) is not None}
        if "effective_from" in payload and effective_from is not None:
            updates["effective_from"] = effective_from
        if "effective_to" in payload and effective_to is not None:
            updates["effective_to"] = effective_to
        if "is_default" in payload:
            updates["is_default"] = 1 if payload["is_default"] else 0
        updates["updated_at"] = now_iso()
        conn.execute(f"UPDATE phase3_regions SET {', '.join(f'{key} = ?' for key in updates)} WHERE id = ? AND organization_id = ?", [*updates.values(), region_id, org])
        return {"ok": True, "item": _row(conn.execute("SELECT * FROM phase3_regions WHERE id = ?", (region_id,)).fetchone(), ("metadata_json",))}
    if route == "/api/phase3/localization" and method == "GET":
        return {"ok": True, "item": _row(_ensure_default_region(conn, org), ("metadata_json",)), "supported_countries": sorted({item["country_code"] for item in REGION_CATALOG})}
    if route == "/api/phase3/localization" and method == "PATCH":
        _phase3_permission(conn, user, "phase3.regions.write", write=True)
        region_id = _text(payload, "region_id", "", 160)
        row = conn.execute("SELECT id FROM phase3_regions WHERE id = ? AND organization_id = ?", (region_id, org)).fetchone()
        if not row:
            raise DomainError(404, "Region not found", "not_found")
        conn.execute("UPDATE phase3_regions SET is_default = 0 WHERE organization_id = ?", (org,))
        conn.execute("UPDATE phase3_regions SET is_default = 1, updated_at = ? WHERE id = ? AND organization_id = ?", (now_iso(), region_id, org))
        return {"ok": True, "item": _row(conn.execute("SELECT * FROM phase3_regions WHERE id = ?", (region_id,)).fetchone(), ("metadata_json",))}
    if route == "/api/phase3/fx/rates" and method == "GET":
        rows = conn.execute("SELECT * FROM phase3_exchange_rates WHERE organization_id = ? ORDER BY effective_at DESC LIMIT ?", (org, _limit(query))).fetchall()
        return {"ok": True, "items": [_row(row) for row in rows], "mock_catalog": [{"base_currency": base, "quote_currency": quote, "rate": str(rate), "source": "mock_fx"} for (base, quote), rate in MOCK_FX.items()]}
    if route == "/api/phase3/fx/rates" and method == "POST":
        _phase3_permission(conn, user, "phase3.regions.write", write=True)
        base = _text(payload, "base_currency", "", 3).upper(); quote = _text(payload, "quote_currency", "", 3).upper(); rate = _text(payload, "rate", "", 40)
        try:
            if Decimal(rate) <= 0: raise InvalidOperation
        except (InvalidOperation, ValueError):
            raise DomainError(400, "rate must be a positive decimal", "validation_error")
        item_id = new_id("fx3")
        conn.execute("INSERT INTO phase3_exchange_rates(id, organization_id, base_currency, quote_currency, rate, effective_at, source, version, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (item_id, org, base, quote, rate, payload.get("effective_at") or now_iso(), _text(payload, "source", "operator", 80), _text(payload, "version", "fx-v1", 40), _user_id(user), now_iso()))
        return {"ok": True, "item": _row(conn.execute("SELECT * FROM phase3_exchange_rates WHERE id = ?", (item_id,)).fetchone())}
    if route == "/api/phase3/fx/convert" and method == "POST":
        base = _text(payload, "base_currency", "", 3).upper(); quote = _text(payload, "quote_currency", "", 3).upper(); amount = _int(payload.get("amount_minor"), "amount_minor", 0, 0)
        saved = None
        if base == quote:
            rate = Decimal("1")
        else:
            saved = conn.execute("SELECT rate FROM phase3_exchange_rates WHERE organization_id = ? AND base_currency = ? AND quote_currency = ? ORDER BY effective_at DESC LIMIT 1", (org, base, quote)).fetchone()
            rate = Decimal(saved["rate"]) if saved else MOCK_FX.get((base, quote))
            if rate is None and (quote, base) in MOCK_FX:
                rate = Decimal("1") / MOCK_FX[(quote, base)]
            if rate is None:
                raise DomainError(400, "No FX rate is configured for that currency pair", "fx_rate_missing")
        converted = _round_minor(Decimal(amount) * rate)
        return {"ok": True, "base_currency": base, "quote_currency": quote, "amount_minor": amount, "rate": str(rate), "converted_minor": converted, "source": "configured" if saved else "mock_fx"}
    if route == "/api/phase3/tax/preview" and method == "POST":
        region = _ensure_default_region(conn, org)
        amount = _int(payload.get("amount_minor"), "amount_minor", 0, 0)
        requested_rate = payload.get("tax_rate_bps")
        rate_bps = _int(requested_rate, "tax_rate_bps", 1800 if region["tax_regime"] == "GST" else 500, 0)
        tax = _round_minor(Decimal(amount) * Decimal(rate_bps) / Decimal(10000))
        split = "CGST_SGST" if region["tax_regime"] == "GST" and payload.get("intra_state", True) else region["tax_regime"]
        return {"ok": True, "region": _row(region), "currency": region["currency"], "tax_regime": region["tax_regime"], "tax_rate_bps": rate_bps, "tax_minor": tax, "total_minor": amount + tax, "split": split}
    return None


def handle_phase3(conn, user, method: str, raw_route: str, payload: dict, ip: str):
    route, query = _parse(raw_route)
    if not route.startswith("/api/phase3"):
        return None
    if route.startswith("/api/phase3/predictive-alerts"):
        result = _predictive_list(conn, user, method, route, query, payload, ip)
        if result is not None:
            return result
    if route.startswith("/api/phase3/vendor-quality"):
        result = _vendor_quality_graph(conn, user, method, route, query, payload, ip)
        if result is not None:
            return result
    if route.startswith("/api/phase3/simulations"):
        result = _simulations(conn, user, method, route, query, payload, ip)
        if result is not None:
            return result
    if route.startswith("/api/phase3/variance"):
        result = _variance(conn, user, method, route, query, payload, ip)
        if result is not None:
            return result
    if route.startswith("/api/phase3/sustainability"):
        result = _sustainability(conn, user, method, route, query, payload, ip)
        if result is not None:
            return result
    if route.startswith("/api/phase3/regions") or route.startswith("/api/phase3/localization") or route.startswith("/api/phase3/fx/") or route == "/api/phase3/tax/preview":
        result = _regions(conn, user, method, route, query, payload, ip)
        if result is not None:
            return result
    raise DomainError(404, "Phase 3 route not found", "not_found")
