"""Supplier purchase, fuel, petty cash, allowances and payroll parity slice."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from backend_domain import DomainError, _assert_owned, _audit, _org, _serialize, _text, new_id, now_iso


FUEL_TYPES = {"petrol", "diesel", "cng", "ev", "electric", "other"}
ALLOWANCE_TYPES = {"meal", "night", "outstation", "parking", "toll", "phone", "other"}


def initialize_supplier_finance_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS domain_purchase_orders (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            supplier_id TEXT,
            duty_id TEXT,
            purchase_reference TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            amount_paise INTEGER NOT NULL DEFAULT 0,
            due_at TEXT,
            supplier_bill_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            idempotency_key TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, purchase_reference),
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_fuel_entries (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            vehicle_id TEXT NOT NULL,
            duty_id TEXT,
            driver_id TEXT,
            fuel_station TEXT NOT NULL DEFAULT '',
            fuel_type TEXT NOT NULL,
            quantity_millilitres INTEGER NOT NULL,
            amount_paise INTEGER NOT NULL,
            odometer_km INTEGER,
            receipt_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'submitted',
            transaction_reference TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_petty_cash_entries (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            driver_id TEXT,
            duty_id TEXT,
            direction TEXT NOT NULL CHECK(direction IN ('credit','debit')),
            category TEXT NOT NULL,
            amount_paise INTEGER NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'submitted',
            idempotency_key TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_driver_allowances (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            driver_id TEXT NOT NULL,
            duty_id TEXT,
            category TEXT NOT NULL,
            amount_paise INTEGER NOT NULL,
            period_start TEXT,
            period_end TEXT,
            status TEXT NOT NULL DEFAULT 'submitted',
            evidence_json TEXT NOT NULL DEFAULT '{}',
            idempotency_key TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_payroll_runs (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            gross_paise INTEGER NOT NULL DEFAULT 0,
            deductions_paise INTEGER NOT NULL DEFAULT 0,
            net_paise INTEGER NOT NULL DEFAULT 0,
            idempotency_key TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, period_start, period_end),
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_payroll_lines (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            payroll_run_id TEXT NOT NULL,
            driver_id TEXT NOT NULL,
            base_paise INTEGER NOT NULL DEFAULT 0,
            allowance_paise INTEGER NOT NULL DEFAULT 0,
            deduction_paise INTEGER NOT NULL DEFAULT 0,
            gross_paise INTEGER NOT NULL DEFAULT 0,
            net_paise INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE(payroll_run_id, driver_id)
        );
        CREATE TABLE IF NOT EXISTS domain_supplier_settlements (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            supplier_id TEXT,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            bill_count INTEGER NOT NULL DEFAULT 0,
            gross_paise INTEGER NOT NULL DEFAULT 0,
            paid_paise INTEGER NOT NULL DEFAULT 0,
            balance_paise INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'draft',
            payout_id TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, supplier_id, period_start, period_end)
        );
        CREATE INDEX IF NOT EXISTS idx_purchase_orders_org_due ON domain_purchase_orders(organization_id, status, due_at);
        CREATE INDEX IF NOT EXISTS idx_fuel_entries_org_vehicle ON domain_fuel_entries(organization_id, vehicle_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_petty_cash_org_created ON domain_petty_cash_entries(organization_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_allowances_org_driver_period ON domain_driver_allowances(organization_id, driver_id, period_start, period_end);
        CREATE INDEX IF NOT EXISTS idx_payroll_runs_org_period ON domain_payroll_runs(organization_id, period_end DESC);
        CREATE INDEX IF NOT EXISTS idx_payroll_lines_run ON domain_payroll_lines(organization_id, payroll_run_id);
        CREATE INDEX IF NOT EXISTS idx_supplier_settlements_org_period ON domain_supplier_settlements(organization_id, period_end DESC);
        """
    )


def _staff(user):
    if user["role"] not in {"vendor", "corporate"}:
        raise DomainError(403, "Finance administration is restricted to organization operators", "role_forbidden")


def _int(payload, key, default=0):
    try: return int(payload.get(key, default) or default)
    except (TypeError, ValueError): raise DomainError(400, f"{key} must be an integer", "validation_error")


def _items(conn, table, org, fields=()):
    return [_serialize(row, fields) for row in conn.execute(f"SELECT * FROM {table} WHERE organization_id = ? ORDER BY created_at DESC LIMIT 500", (org,)).fetchall()]


def _create_purchase(conn, user, payload, ip):
    org = _org(user); _staff(user)
    supplier_id = _text(payload, "supplier_id") or None
    if supplier_id: _assert_owned(conn, "domain_suppliers", supplier_id, org)
    amount = _int(payload, "amount_paise")
    if amount <= 0: raise DomainError(400, "amount_paise must be positive", "validation_error")
    key = _text(payload, "idempotency_key", maximum=160) or None
    if key:
        existing = conn.execute("SELECT * FROM domain_purchase_orders WHERE organization_id = ? AND idempotency_key = ?", (org, key)).fetchone()
        if existing: return {"ok": True, "item": _serialize(existing, ("metadata_json",)), "idempotent": True}
    reference = _text(payload, "purchase_reference", maximum=100) or f"PO-{datetime.now(timezone.utc):%Y%m%d}-{new_id('po')[-6:]}"
    duty_id = _text(payload, "duty_id") or None
    if duty_id: _assert_owned(conn, "domain_duties", duty_id, org)
    now = now_iso(); purchase_id = new_id("purchase")
    conn.execute("INSERT INTO domain_purchase_orders(id, organization_id, supplier_id, duty_id, purchase_reference, status, amount_paise, due_at, supplier_bill_id, metadata_json, idempotency_key, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (purchase_id, org, supplier_id, duty_id, reference, _text(payload, "status", "draft", 30), amount, _text(payload, "due_at", maximum=40) or None, _text(payload, "supplier_bill_id") or None, json.dumps(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}), key, user["id"], now, now))
    _audit(conn, user, "supplier_purchase.created", "purchase_order", purchase_id, ip, {"supplier_id": supplier_id, "amount_paise": amount})
    return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_purchase_orders WHERE id = ?", (purchase_id,)).fetchone(), ("metadata_json",))}


def _create_fuel(conn, user, payload, ip):
    org = _org(user); vehicle_id = _text(payload, "vehicle_id")
    _assert_owned(conn, "domain_vehicles", vehicle_id, org)
    driver_id = _text(payload, "driver_id") or None
    if driver_id: _assert_owned(conn, "domain_drivers", driver_id, org)
    duty_id = _text(payload, "duty_id") or None
    if duty_id: _assert_owned(conn, "domain_duties", duty_id, org)
    fuel_type = _text(payload, "fuel_type", "petrol", 20).lower()
    if fuel_type not in FUEL_TYPES: raise DomainError(400, "Unsupported fuel type", "validation_error")
    quantity = _int(payload, "quantity_millilitres")
    if quantity <= 0 and payload.get("quantity_litres") is not None:
        try: quantity = round(float(payload["quantity_litres"]) * 1000)
        except (TypeError, ValueError): quantity = 0
    amount = _int(payload, "amount_paise")
    if quantity <= 0 or amount <= 0: raise DomainError(400, "Fuel quantity and amount must be positive", "validation_error")
    key = _text(payload, "idempotency_key", maximum=160) or None
    if key:
        existing = conn.execute("SELECT * FROM domain_fuel_entries WHERE organization_id = ? AND idempotency_key = ?", (org, key)).fetchone()
        if existing: return {"ok": True, "item": _serialize(existing, ("receipt_json",)), "idempotent": True}
    fuel_id = new_id("fuel"); now = now_iso()
    conn.execute("INSERT INTO domain_fuel_entries(id, organization_id, vehicle_id, duty_id, driver_id, fuel_station, fuel_type, quantity_millilitres, amount_paise, odometer_km, receipt_json, status, transaction_reference, idempotency_key, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (fuel_id, org, vehicle_id, duty_id, driver_id, _text(payload, "fuel_station", maximum=160), fuel_type, quantity, amount, _int(payload, "odometer_km") if payload.get("odometer_km") is not None else None, json.dumps(payload.get("receipt") if isinstance(payload.get("receipt"), dict) else {}), _text(payload, "status", "submitted", 30), _text(payload, "transaction_reference", maximum=100), key, user["id"], now))
    _audit(conn, user, "fuel_entry.created", "fuel_entry", fuel_id, ip, {"vehicle_id": vehicle_id, "amount_paise": amount, "quantity_millilitres": quantity})
    return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_fuel_entries WHERE id = ?", (fuel_id,)).fetchone(), ("receipt_json",))}


def _create_petty_cash(conn, user, payload, ip):
    org = _org(user); direction = _text(payload, "direction", "debit", 10).lower()
    if direction not in {"credit", "debit"}: raise DomainError(400, "direction must be credit or debit", "validation_error")
    amount = _int(payload, "amount_paise")
    if amount <= 0: raise DomainError(400, "Petty cash amount must be positive", "validation_error")
    driver_id = _text(payload, "driver_id") or None
    if driver_id: _assert_owned(conn, "domain_drivers", driver_id, org)
    duty_id = _text(payload, "duty_id") or None
    if duty_id: _assert_owned(conn, "domain_duties", duty_id, org)
    key = _text(payload, "idempotency_key", maximum=160) or None
    if key:
        existing = conn.execute("SELECT * FROM domain_petty_cash_entries WHERE organization_id = ? AND idempotency_key = ?", (org, key)).fetchone()
        if existing: return {"ok": True, "item": _serialize(existing), "idempotent": True}
    entry_id = new_id("cash"); now = now_iso(); conn.execute("INSERT INTO domain_petty_cash_entries(id, organization_id, driver_id, duty_id, direction, category, amount_paise, note, status, idempotency_key, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (entry_id, org, driver_id, duty_id, direction, _text(payload, "category", "general", 50), amount, _text(payload, "note", maximum=500), _text(payload, "status", "submitted", 30), key, user["id"], now)); _audit(conn, user, "petty_cash.created", "petty_cash_entry", entry_id, ip, {"direction": direction, "amount_paise": amount}); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_petty_cash_entries WHERE id = ?", (entry_id,)).fetchone())}


def _create_allowance(conn, user, payload, ip):
    org = _org(user); driver_id = _text(payload, "driver_id")
    _assert_owned(conn, "domain_drivers", driver_id, org)
    category = _text(payload, "category", "other", 30).lower()
    if category not in ALLOWANCE_TYPES: raise DomainError(400, "Unsupported allowance category", "validation_error")
    amount = _int(payload, "amount_paise")
    if amount <= 0: raise DomainError(400, "Allowance amount must be positive", "validation_error")
    duty_id = _text(payload, "duty_id") or None
    if duty_id: _assert_owned(conn, "domain_duties", duty_id, org)
    key = _text(payload, "idempotency_key", maximum=160) or None
    if key:
        existing = conn.execute("SELECT * FROM domain_driver_allowances WHERE organization_id = ? AND idempotency_key = ?", (org, key)).fetchone()
        if existing: return {"ok": True, "item": _serialize(existing, ("evidence_json",)), "idempotent": True}
    allowance_id = new_id("allowance"); now = now_iso(); conn.execute("INSERT INTO domain_driver_allowances(id, organization_id, driver_id, duty_id, category, amount_paise, period_start, period_end, status, evidence_json, idempotency_key, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (allowance_id, org, driver_id, duty_id, category, amount, _text(payload, "period_start", maximum=40), _text(payload, "period_end", maximum=40), _text(payload, "status", "submitted", 30), json.dumps(payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}), key, user["id"], now)); _audit(conn, user, "driver_allowance.created", "driver_allowance", allowance_id, ip, {"driver_id": driver_id, "amount_paise": amount}); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_driver_allowances WHERE id = ?", (allowance_id,)).fetchone(), ("evidence_json",))}


def _create_payroll_run(conn, user, payload, ip):
    org = _org(user); _staff(user); start = _text(payload, "period_start", maximum=40); end = _text(payload, "period_end", maximum=40)
    if not start or not end: raise DomainError(400, "period_start and period_end are required", "validation_error")
    key = _text(payload, "idempotency_key", maximum=160) or None
    if key:
        existing = conn.execute("SELECT * FROM domain_payroll_runs WHERE organization_id = ? AND idempotency_key = ?", (org, key)).fetchone()
        if existing: return _payroll_payload(conn, existing["id"], org, True)
    existing_period = conn.execute("SELECT * FROM domain_payroll_runs WHERE organization_id = ? AND period_start = ? AND period_end = ?", (org, start, end)).fetchone()
    if existing_period: return _payroll_payload(conn, existing_period["id"], org, True)
    lines = payload.get("lines") if isinstance(payload.get("lines"), list) else []
    if not lines:
        driver_rows = conn.execute("SELECT id FROM domain_drivers WHERE organization_id = ? AND status <> 'inactive' ORDER BY id", (org,)).fetchall()
        default_base = _int(payload, "default_base_paise")
        lines = [{"driver_id": row["id"], "base_paise": default_base} for row in driver_rows if default_base > 0]
    if not lines: raise DomainError(400, "Payroll requires at least one driver line", "validation_error")
    run_id = new_id("payroll"); now = now_iso(); totals = {"gross": 0, "deductions": 0, "net": 0}
    conn.execute("INSERT INTO domain_payroll_runs(id, organization_id, period_start, period_end, status, idempotency_key, metadata_json, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?)", (run_id, org, start, end, key, json.dumps(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}), user["id"], now, now))
    for line in lines:
        driver_id = _text(line, "driver_id")
        _assert_owned(conn, "domain_drivers", driver_id, org)
        base = _int(line, "base_paise"); deductions = _int(line, "deduction_paise")
        allowance_rows = conn.execute("SELECT COALESCE(SUM(amount_paise),0) AS total FROM domain_driver_allowances WHERE organization_id = ? AND driver_id = ? AND status = 'approved' AND (period_start IS NULL OR period_start >= ?) AND (period_end IS NULL OR period_end <= ?)", (org, driver_id, start, end)).fetchone()
        allowance = _int(line, "allowance_paise", int(allowance_rows["total"] or 0)); gross = base + allowance; net = gross - deductions
        if base < 0 or deductions < 0 or allowance < 0 or net < 0: raise DomainError(400, "Payroll amounts are invalid", "validation_error")
        line_id = new_id("payrollline"); conn.execute("INSERT INTO domain_payroll_lines(id, organization_id, payroll_run_id, driver_id, base_paise, allowance_paise, deduction_paise, gross_paise, net_paise, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (line_id, org, run_id, driver_id, base, allowance, deductions, gross, net, json.dumps(line.get("metadata") if isinstance(line.get("metadata"), dict) else {}), now)); totals["gross"] += gross; totals["deductions"] += deductions; totals["net"] += net
    conn.execute("UPDATE domain_payroll_runs SET gross_paise = ?, deductions_paise = ?, net_paise = ?, updated_at = ? WHERE id = ?", (totals["gross"], totals["deductions"], totals["net"], now_iso(), run_id)); _audit(conn, user, "payroll_run.created", "payroll_run", run_id, ip, {"gross_paise": totals["gross"], "net_paise": totals["net"]}); return _payroll_payload(conn, run_id, org, False)


def _payroll_payload(conn, run_id, org, idempotent=False):
    row = _assert_owned(conn, "domain_payroll_runs", run_id, org); item = _serialize(row, ("metadata_json",)); item["lines"] = [_serialize(line, ("metadata_json",)) for line in conn.execute("SELECT * FROM domain_payroll_lines WHERE organization_id = ? AND payroll_run_id = ? ORDER BY driver_id", (org, run_id)).fetchall()]; result = {"ok": True, "item": item};
    if idempotent: result["idempotent"] = True
    return result


def _supplier_ageing(conn, user, query):
    org = _org(user); _staff(user); now = datetime.now(timezone.utc); rows = conn.execute("SELECT b.*, s.name AS supplier_name FROM domain_supplier_bills b LEFT JOIN domain_suppliers s ON s.id = b.supplier_id WHERE b.organization_id = ? AND b.status NOT IN ('paid','void') ORDER BY b.due_at", (org,)).fetchall(); buckets = {"current": [], "1_30": [], "31_60": [], "61_90": [], "90_plus": []}
    for row in rows:
        age = 0
        if row["due_at"]:
            try:
                due = datetime.fromisoformat(str(row["due_at"]).replace("Z", "+00:00")); due = due if due.tzinfo else due.replace(tzinfo=timezone.utc); age = max(0, (now - due).days)
            except ValueError: pass
        bucket = "current" if age == 0 else "1_30" if age <= 30 else "31_60" if age <= 60 else "61_90" if age <= 90 else "90_plus"; buckets[bucket].append({**_serialize(row, ("attachment_json", "validation_json")), "age_days": age})
    return {"ok": True, "buckets": {key: {"count": len(values), "total_paise": sum(int(item["total_paise"] or 0) for item in values), "items": values} for key, values in buckets.items()}}


def _settlement(conn, user, payload, ip):
    org = _org(user); _staff(user); supplier_id = _text(payload, "supplier_id") or None
    if supplier_id: _assert_owned(conn, "domain_suppliers", supplier_id, org)
    start = _text(payload, "period_start", maximum=40); end = _text(payload, "period_end", maximum=40)
    if not start or not end: raise DomainError(400, "period_start and period_end are required", "validation_error")
    bills = conn.execute("SELECT COALESCE(SUM(total_paise),0) AS gross, COUNT(*) AS count FROM domain_supplier_bills WHERE organization_id = ? AND (? IS NULL OR supplier_id = ?) AND created_at >= ? AND created_at <= ? AND status NOT IN ('void')", (org, supplier_id, supplier_id, start, end)).fetchone(); gross = int(bills["gross"] or 0); count = int(bills["count"] or 0)
    row = conn.execute("SELECT * FROM domain_supplier_settlements WHERE organization_id = ? AND supplier_id IS ? AND period_start = ? AND period_end = ?", (org, supplier_id, start, end)).fetchone()
    if row:
        return {"ok": True, "item": _serialize(row), "idempotent": True}
    settlement_id = new_id("settlement"); now = now_iso(); conn.execute("INSERT INTO domain_supplier_settlements(id, organization_id, supplier_id, period_start, period_end, bill_count, gross_paise, balance_paise, status, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)", (settlement_id, org, supplier_id, start, end, count, gross, gross, user["id"], now)); _audit(conn, user, "supplier_settlement.generated", "supplier_settlement", settlement_id, ip, {"supplier_id": supplier_id, "gross_paise": gross}); return {"ok": True, "item": _serialize(conn.execute("SELECT * FROM domain_supplier_settlements WHERE id = ?", (settlement_id,)).fetchone())}


def handle_supplier_finance(conn, user, method: str, raw_route: str, payload: dict, ip: str):
    route = urlsplit(raw_route).path.rstrip("/") or "/"; query = parse_qs(urlsplit(raw_route).query)
    if route == "/api/supplier-purchases" and method == "GET": return {"ok": True, "items": _items(conn, "domain_purchase_orders", _org(user), ("metadata_json",))}
    if route == "/api/supplier-purchases" and method == "POST": return _create_purchase(conn, user, payload, ip)
    if route == "/api/supplier-ageing" and method == "GET": return _supplier_ageing(conn, user, query)
    if route == "/api/supplier-settlements" and method == "GET": return {"ok": True, "items": _items(conn, "domain_supplier_settlements", _org(user))}
    if route == "/api/supplier-settlements/generate" and method == "POST": return _settlement(conn, user, payload, ip)
    if route == "/api/fuel-entries" and method == "GET": return {"ok": True, "items": _items(conn, "domain_fuel_entries", _org(user), ("receipt_json",))}
    if route == "/api/fuel-entries" and method == "POST": return _create_fuel(conn, user, payload, ip)
    if route == "/api/petty-cash/entries" and method == "GET": return {"ok": True, "items": _items(conn, "domain_petty_cash_entries", _org(user))}
    if route == "/api/petty-cash/entries" and method == "POST": return _create_petty_cash(conn, user, payload, ip)
    if route == "/api/driver-allowances" and method == "GET": return {"ok": True, "items": _items(conn, "domain_driver_allowances", _org(user), ("evidence_json",))}
    if route == "/api/driver-allowances" and method == "POST": return _create_allowance(conn, user, payload, ip)
    if route == "/api/payroll/runs" and method == "GET": return {"ok": True, "items": _items(conn, "domain_payroll_runs", _org(user), ("metadata_json",))}
    if route == "/api/payroll/runs" and method == "POST": return _create_payroll_run(conn, user, payload, ip)
    payroll_match = __import__("re").match(r"^/api/payroll/runs/([^/]+)/lines$", route)
    if payroll_match and method == "GET":
        org = _org(user); _staff(user); _assert_owned(conn, "domain_payroll_runs", payroll_match.group(1), org); return {"ok": True, "items": [_serialize(row, ("metadata_json",)) for row in conn.execute("SELECT * FROM domain_payroll_lines WHERE organization_id = ? AND payroll_run_id = ? ORDER BY driver_id", (org, payroll_match.group(1))).fetchall()]}
    return None
