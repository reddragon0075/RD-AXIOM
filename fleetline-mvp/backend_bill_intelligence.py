"""Mock-first AI bill reading and auditable auto-posting for Axiom Fleet.

The local fallback deliberately separates extraction from posting. Uploads create a
reviewable record with field-level confidence, validation warnings, vehicle
candidates and source provenance. A staff user must confirm the record before it
can write fuel, vehicle-cost, supplier-bill, odometer or compliance data.

Production direction: replace ``_extract_fields`` with the vision/OCR worker and
move the posting transaction behind the authenticated Supabase Edge boundary.
The table and route contract stays the same so a real OCR provider can be
introduced without changing the operator workflow.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import parse_qs, urlsplit

from backend_domain import DEFAULT_PROVIDERS, DomainError, _audit, _org, now_iso, new_id


BILL_TYPES = {"fuel", "maintenance", "toll", "insurance", "tyre", "other"}
FUEL_TYPES = {"petrol", "diesel", "cng", "ev", "electric", "hybrid", "petrol+cng"}
REGISTRATION_RE = re.compile(r"\b[A-Z]{2}[\s-]?\d{1,2}[\s-]?[A-Z]{1,3}[\s-]?\d{4}\b", re.I)
DATE_RE = re.compile(r"\b(?:\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4}|\d{4}[\-/]\d{1,2}[\-/]\d{1,2})\b")
NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


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
            target = field[:-5] if field.endswith("_json") else field
            item[target] = _json(item.pop(field), {} if field.endswith("_json") else [])
    return item


def _text(payload, key, default="", maximum=500):
    value = str(payload.get(key, default) or "").strip()
    if len(value) > maximum:
        raise DomainError(400, f"{key} is too long", "validation_error")
    return value


def _staff(user):
    if user["role"] not in {"vendor", "corporate"}:
        raise DomainError(403, "Bill review and posting require an organization operator", "role_forbidden")


def _limit(query, default=100):
    try:
        return min(max(int(query.get("limit", [default])[0] or default), 1), 500)
    except (TypeError, ValueError):
        return default


def _money(value):
    if value in (None, ""):
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", str(value).replace(",", ""))
    if not cleaned or cleaned in {"-", "."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _minor(value):
    if value in (None, ""):
        return 0
    try:
        return int((Decimal(str(value)) * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError):
        return 0


def _number_from(text, labels):
    label = "|".join(re.escape(item) for item in labels)
    match = re.search(rf"(?:{label})\s*[:=#-]?\s*({NUMBER_RE.pattern})", text, re.I)
    return _money(match.group(1)) if match else None


def _value_from(text, labels):
    label = "|".join(re.escape(item) for item in labels)
    match = re.search(rf"(?:{label})\s*[:=#-]?\s*([^\n\r|]+)", text, re.I)
    return match.group(1).strip() if match else ""


def _date_value(value):
    if not value:
        return ""
    raw = str(value).strip().replace(".", "/")
    match = DATE_RE.search(raw)
    if not match:
        return ""
    candidate = match.group(0).replace("/", "-")
    parts = candidate.split("-")
    try:
        if len(parts[0]) == 4:
            return date(int(parts[0]), int(parts[1]), int(parts[2])).isoformat()
        year = int(parts[2]); year += 2000 if year < 100 else 0
        return date(year, int(parts[1]), int(parts[0])).isoformat()
    except ValueError:
        return ""


def _normalize_registration(value):
    raw = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    return raw


def _registration(value):
    match = REGISTRATION_RE.search(str(value or "").upper())
    return re.sub(r"\s+", " ", match.group(0).replace("-", " ")).strip() if match else ""


def _registration_variants(value):
    normalized = _normalize_registration(value)
    variants = {normalized}
    if normalized:
        variants.add(normalized.replace("O", "0").replace("I", "1"))
        variants.add(normalized.replace("0", "O").replace("1", "I"))
    return {item for item in variants if item}


def _canonical_fuel(value):
    raw = str(value or "").lower().replace("electric", "ev").replace("petrol+cng", "petrol+cng")
    for option in FUEL_TYPES:
        if option in raw:
            return option
    return ""


def _bill_type(text, explicit=""):
    value = str(explicit or "").lower().strip()
    if value in BILL_TYPES:
        return value
    lower = text.lower()
    if any(word in lower for word in ("fuel", "petrol", "diesel", "cng", "litre", "liter", "pump")):
        return "fuel"
    if any(word in lower for word in ("toll", "fastag", "plaza")):
        return "toll"
    if any(word in lower for word in ("insurance", "premium", "policy")):
        return "insurance"
    if any(word in lower for word in ("service", "maintenance", "repair", "labour", "labour")):
        return "maintenance"
    return "other"


def _extract_fields(source_text, supplied):
    """Return a strict, deterministic extraction envelope.

    ``supplied`` is the seam for a production vision model. Local preview users
    can paste OCR text or provide structured values, while the response always
    exposes the same field-level confidence contract.
    """
    text = str(source_text or "")[:20000]
    data = supplied if isinstance(supplied, dict) else {}
    extracted = {
        "bill_type": _bill_type(text, data.get("bill_type")),
        "vendor_name": str(data.get("vendor_name") or _value_from(text, ["vendor", "supplier", "petrol pump", "service centre"])),
        "vendor_gstin": str(data.get("vendor_gstin") or _value_from(text, ["gstin", "gst no", "gst number"])).upper(),
        "vendor_phone": str(data.get("vendor_phone") or _value_from(text, ["phone", "mobile"])),
        "invoice_number": str(data.get("invoice_number") or _value_from(text, ["invoice no", "invoice number", "bill no", "bill number", "receipt no"])),
        "invoice_date": _date_value(data.get("invoice_date") or _value_from(text, ["invoice date", "bill date", "date"])),
        "vehicle_regd_no_raw": str(data.get("vehicle_regd_no_raw") or data.get("vehicle_registration") or _registration(text)),
        "odometer_km": data.get("odometer_km") if data.get("odometer_km") not in (None, "") else _number_from(text, ["odometer", "odo", "speedo", "km reading"]),
        "fuel_type": _canonical_fuel(data.get("fuel_type") or _value_from(text, ["fuel type", "fuel"])),
        "quantity": data.get("quantity") if data.get("quantity") not in (None, "") else _number_from(text, ["quantity", "qty", "litres", "liters", "kwh"]),
        "unit": str(data.get("unit") or _value_from(text, ["unit"]) or "L"),
        "rate_per_unit": data.get("rate_per_unit") if data.get("rate_per_unit") not in (None, "") else _number_from(text, ["rate", "rate per litre", "rate per unit", "price per litre"]),
        "amount_fuel": data.get("amount_fuel") if data.get("amount_fuel") not in (None, "") else _number_from(text, ["fuel amount", "amount fuel"]),
        "service_type": str(data.get("service_type") or _value_from(text, ["service type", "work done", "description"])),
        "parts": data.get("parts") if isinstance(data.get("parts"), list) else [],
        "labour_amount": data.get("labour_amount") if data.get("labour_amount") not in (None, "") else _number_from(text, ["labour", "labor"]),
        "next_service_due_km": data.get("next_service_due_km") if data.get("next_service_due_km") not in (None, "") else _number_from(text, ["next service km", "service due km"]),
        "next_service_due_date": _date_value(data.get("next_service_due_date") or _value_from(text, ["next service date", "service due date"])),
        "toll_plaza": str(data.get("toll_plaza") or _value_from(text, ["toll plaza", "plaza"])),
        "toll_amount": data.get("toll_amount") if data.get("toll_amount") not in (None, "") else _number_from(text, ["toll amount", "toll"]),
        "fastag_txn_id": str(data.get("fastag_txn_id") or _value_from(text, ["fastag", "transaction id", "txn id"])),
        "policy_number": str(data.get("policy_number") or _value_from(text, ["policy no", "policy number"])),
        "policy_expiry": _date_value(data.get("policy_expiry") or _value_from(text, ["policy expiry", "expiry", "valid till"])),
        "premium_amount": data.get("premium_amount") if data.get("premium_amount") not in (None, "") else _number_from(text, ["premium", "insurance amount"]),
        "taxable_value": data.get("taxable_value") if data.get("taxable_value") not in (None, "") else _number_from(text, ["taxable", "taxable value"]),
        "cgst": data.get("cgst") if data.get("cgst") not in (None, "") else _number_from(text, ["cgst"]),
        "sgst": data.get("sgst") if data.get("sgst") not in (None, "") else _number_from(text, ["sgst"]),
        "igst": data.get("igst") if data.get("igst") not in (None, "") else _number_from(text, ["igst"]),
        "total_amount": data.get("total_amount") if data.get("total_amount") not in (None, "") else _number_from(text, ["grand total", "total amount", "invoice total", "total", "amount payable"]),
        "payment_mode": str(data.get("payment_mode") or _value_from(text, ["payment mode", "paid by"])),
    }
    # A fuel bill commonly labels only one amount. Keep the extracted amount
    # explicit so posting and validation never infer a silent zero.
    if extracted["total_amount"] is None:
        extracted["total_amount"] = extracted["amount_fuel"] or extracted["toll_amount"] or extracted["premium_amount"]
    if extracted["amount_fuel"] is None and extracted["bill_type"] == "fuel":
        extracted["amount_fuel"] = extracted["total_amount"]
    confidence = {}
    for key, value in extracted.items():
        if key in {"parts", "unit"}:
            continue
        confidence[key] = 0.96 if key in data and value not in (None, "", []) else (0.88 if value not in (None, "", []) else 0.0)
    confidence.update({key: float(value) for key, value in (data.get("confidence") or {}).items() if isinstance(value, (int, float))})
    extracted["confidence"] = confidence
    extracted["needs_review"] = True
    return extracted


def _match_vehicles(conn, organization_id, registration):
    variants = _registration_variants(registration)
    if not variants:
        return []
    candidates = []
    for row in conn.execute("SELECT id, registration_number, make_model, fuel_type, status FROM domain_vehicles WHERE organization_id = ? ORDER BY registration_number", (organization_id,)).fetchall():
        vehicle_variants = _registration_variants(row["registration_number"])
        overlap = variants & vehicle_variants
        score = 100 if overlap else 0
        if not score:
            # Fuzzy OCR tolerance: compare every OCR normalization variant,
            # not an arbitrary set member, so O/0 and I/1 substitutions do not
            # accidentally hide an otherwise one-character registration match.
            distances = [
                sum(left != right for left, right in zip(raw, existing))
                for raw in variants for existing in vehicle_variants
                if len(raw) == len(existing)
            ]
            score = 88 if distances and min(distances) == 1 else 0
        if score:
            candidates.append({"vehicle_id": row["id"], "registration_number": row["registration_number"], "make_model": row["make_model"], "fuel_type": row["fuel_type"], "status": row["status"], "score": score})
    return sorted(candidates, key=lambda item: (-item["score"], item["registration_number"]))[:3]


def _validate(conn, organization_id, extracted, vehicle_id=None):
    errors = []
    warnings = []
    checks = []
    total = _money(extracted.get("total_amount"))
    if not total or total <= 0:
        errors.append({"code": "total_missing", "message": "A positive total amount is required."})
    else:
        checks.append({"code": "total_present", "status": "passed", "message": "Total amount is present."})
    invoice_number = str(extracted.get("invoice_number") or "").strip()
    vendor_gstin = str(extracted.get("vendor_gstin") or "").strip().upper()
    if invoice_number and vendor_gstin:
        for row in conn.execute("SELECT id, extracted_json, status FROM bill_intelligence_records WHERE organization_id = ? AND status NOT IN ('rejected','reversed')", (organization_id,)).fetchall():
            existing = _json(row["extracted_json"], {})
            if str(existing.get("invoice_number") or "").strip() == invoice_number and str(existing.get("vendor_gstin") or "").strip().upper() == vendor_gstin:
                errors.append({"code": "duplicate_bill", "message": f"Invoice {invoice_number} from {vendor_gstin} was already captured.", "bill_id": row["id"]})
                break
    if extracted.get("invoice_date"):
        try:
            if date.fromisoformat(str(extracted["invoice_date"])) > date.today():
                warnings.append({"code": "future_date", "message": "Invoice date is in the future; verify the source."})
        except ValueError:
            warnings.append({"code": "date_format", "message": "Invoice date needs review."})
    quantity = _money(extracted.get("quantity")); rate = _money(extracted.get("rate_per_unit")); amount_fuel = _money(extracted.get("amount_fuel"))
    if quantity and rate and amount_fuel:
        expected = quantity * rate
        difference = abs(expected - amount_fuel)
        if difference > max(1.0, amount_fuel * 0.01):
            warnings.append({"code": "amount_mismatch", "message": f"Quantity × rate is {expected:.2f}, but fuel amount is {amount_fuel:.2f}."})
        else:
            checks.append({"code": "quantity_rate_total", "status": "passed", "message": "Quantity × rate reconciles within 1%."})
    candidates = _match_vehicles(conn, organization_id, extracted.get("vehicle_regd_no_raw"))
    selected = None
    if vehicle_id:
        selected = conn.execute("SELECT id, registration_number, fuel_type, make_model FROM domain_vehicles WHERE id = ? AND organization_id = ?", (vehicle_id, organization_id)).fetchone()
        if not selected:
            errors.append({"code": "vehicle_not_owned", "message": "Selected vehicle is not in this tenant."})
    elif candidates and candidates[0]["score"] >= 100:
        vehicle_id = candidates[0]["vehicle_id"]
        selected = conn.execute("SELECT id, registration_number, fuel_type, make_model FROM domain_vehicles WHERE id = ?", (vehicle_id,)).fetchone()
    if not vehicle_id:
        warnings.append({"code": "vehicle_match_required", "message": "Choose the cab before posting this bill."})
    if selected:
        selected_fuel = str(selected["fuel_type"] or "").lower()
        bill_fuel = str(extracted.get("fuel_type") or "").lower()
        if selected_fuel in {"ev", "electric"} and extracted.get("bill_type") == "fuel" and bill_fuel not in {"ev", "electric"}:
            errors.append({"code": "fuel_vehicle_mismatch", "message": "A combustion-fuel bill cannot be posted to an EV."})
        elif bill_fuel and selected_fuel and bill_fuel != selected_fuel and not (bill_fuel == "electric" and selected_fuel == "ev"):
            warnings.append({"code": "fuel_vehicle_review", "message": f"Bill says {bill_fuel}; vehicle master says {selected_fuel}."})
    confidence = extracted.get("confidence") or {}
    if total and float(confidence.get("total_amount", 0)) < 0.85:
        warnings.append({"code": "low_amount_confidence", "message": "Amount confidence is below the auto-post threshold."})
    if extracted.get("odometer_km") not in (None, "") and float(confidence.get("odometer_km", 0)) < 0.85:
        warnings.append({"code": "low_odometer_confidence", "message": "Odometer confidence is below the auto-post threshold."})
    auto_post_eligible = bool(total and vehicle_id and not errors and float(confidence.get("total_amount", 0)) >= 0.85 and (extracted.get("odometer_km") in (None, "") or float(confidence.get("odometer_km", 0)) >= 0.85))
    return {"errors": errors, "warnings": warnings, "checks": checks, "vehicle_candidates": candidates, "selected_vehicle_id": vehicle_id or "", "auto_post_eligible": auto_post_eligible, "review_required": True}


def initialize_bill_intelligence_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bill_intelligence_records (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'vendor_portal',
            filename TEXT NOT NULL DEFAULT '',
            content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
            storage_reference TEXT NOT NULL DEFAULT '',
            file_sha256 TEXT NOT NULL DEFAULT '',
            ocr_text TEXT NOT NULL DEFAULT '',
            bill_type TEXT NOT NULL DEFAULT 'other',
            vehicle_id TEXT,
            duty_id TEXT,
            supplier_id TEXT,
            status TEXT NOT NULL DEFAULT 'needs_review',
            extracted_json TEXT NOT NULL DEFAULT '{}',
            confidence_json TEXT NOT NULL DEFAULT '{}',
            validation_json TEXT NOT NULL DEFAULT '{}',
            posting_json TEXT NOT NULL DEFAULT '{}',
            review_note TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT,
            created_by TEXT,
            reviewed_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            posted_at TEXT,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE INDEX IF NOT EXISTS idx_bill_intelligence_org_status ON bill_intelligence_records(organization_id, status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_bill_intelligence_org_vehicle ON bill_intelligence_records(organization_id, vehicle_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS bill_intelligence_postings (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            bill_id TEXT NOT NULL,
            posting_type TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE(bill_id, posting_type, entity_id)
        );
        CREATE INDEX IF NOT EXISTS idx_bill_intelligence_postings_bill ON bill_intelligence_postings(organization_id, bill_id, created_at);
        CREATE TABLE IF NOT EXISTS bill_intelligence_fuel_entries (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            bill_id TEXT NOT NULL,
            vehicle_id TEXT NOT NULL,
            duty_id TEXT,
            fuel_type TEXT NOT NULL DEFAULT '',
            quantity REAL NOT NULL DEFAULT 0,
            unit TEXT NOT NULL DEFAULT 'L',
            rate_per_unit REAL,
            amount_paise INTEGER NOT NULL DEFAULT 0,
            odometer_km REAL,
            station TEXT NOT NULL DEFAULT '',
            invoice_date TEXT,
            mileage_km_per_unit REAL,
            anomaly_code TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'posted',
            created_at TEXT NOT NULL,
            reversed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_bill_fuel_vehicle ON bill_intelligence_fuel_entries(organization_id, vehicle_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS bill_intelligence_timeline (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            vehicle_id TEXT NOT NULL,
            bill_id TEXT,
            event_type TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'ocr_bill',
            payload_json TEXT NOT NULL DEFAULT '{}',
            event_at TEXT NOT NULL,
            created_by TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_bill_timeline_vehicle ON bill_intelligence_timeline(organization_id, vehicle_id, event_at DESC);
        """
    )
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(domain_vehicles)").fetchall()}
    for column, definition in {
        "current_odometer_km": "REAL NOT NULL DEFAULT 0",
        "odometer_updated_at": "TEXT",
        "insurance_policy_number": "TEXT NOT NULL DEFAULT ''",
        "next_service_due_km": "REAL",
        "next_service_due_date": "TEXT",
    }.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE domain_vehicles ADD COLUMN {column} {definition}")


def _detail(conn, record_id, organization_id):
    row = conn.execute("SELECT * FROM bill_intelligence_records WHERE id = ? AND organization_id = ?", (record_id, organization_id)).fetchone()
    if not row:
        raise DomainError(404, "Bill record not found", "not_found")
    item = _row(row, ("extracted_json", "confidence_json", "validation_json", "posting_json"))
    vehicle = conn.execute("SELECT id, registration_number, make_model, fuel_type, current_odometer_km, insurance_expiry FROM domain_vehicles WHERE id = ? AND organization_id = ?", (row["vehicle_id"], organization_id)).fetchone() if row["vehicle_id"] else None
    item["vehicle"] = dict(vehicle) if vehicle else None
    item["postings"] = [_row(posting, ("payload_json",)) for posting in conn.execute("SELECT * FROM bill_intelligence_postings WHERE bill_id = ? AND organization_id = ? ORDER BY created_at", (record_id, organization_id)).fetchall()]
    item["timeline"] = [_row(event, ("payload_json",)) for event in conn.execute("SELECT * FROM bill_intelligence_timeline WHERE bill_id = ? AND organization_id = ? ORDER BY event_at", (record_id, organization_id)).fetchall()]
    return item


def _summary(conn, organization_id):
    counts = {row["status"]: row["count"] for row in conn.execute("SELECT status, COUNT(*) AS count FROM bill_intelligence_records WHERE organization_id = ? GROUP BY status", (organization_id,)).fetchall()}
    posted = conn.execute("SELECT COALESCE(SUM(CAST(json_extract(extracted_json, '$.total_amount') AS REAL)),0) AS total FROM bill_intelligence_records WHERE organization_id = ? AND status = 'posted'", (organization_id,)).fetchone()["total"]
    total = conn.execute("SELECT COUNT(*) AS count FROM bill_intelligence_records WHERE organization_id = ?", (organization_id,)).fetchone()["count"]
    matched = conn.execute("SELECT COUNT(*) AS count FROM bill_intelligence_records WHERE organization_id = ? AND vehicle_id IS NOT NULL", (organization_id,)).fetchone()["count"]
    return {"review_count": sum(counts.get(key, 0) for key in ("needs_review", "draft")), "posted_count": counts.get("posted", 0), "reversed_count": counts.get("reversed", 0), "rejected_count": counts.get("rejected", 0), "total_count": total, "posted_amount": round(float(posted or 0), 2), "auto_match_rate": round((matched / total) * 100, 1) if total else 0.0}


def _create_record(conn, user, payload, ip):
    organization_id = _org(user)
    source = _text(payload, "source", "vendor_portal", 40)
    filename = _text(payload, "filename", "bill-upload", 200)
    content_type = _text(payload, "content_type", "application/octet-stream", 120)
    ocr_text = _text(payload, "ocr_text", maximum=20000)
    idempotency_key = _text(payload, "idempotency_key", maximum=160) or None
    if idempotency_key:
        existing = conn.execute("SELECT id FROM bill_intelligence_records WHERE organization_id = ? AND idempotency_key = ?", (organization_id, idempotency_key)).fetchone()
        if existing:
            return {"ok": True, "item": _detail(conn, existing["id"], organization_id), "replayed": True}
    record_id = new_id("billai")
    extracted = _extract_fields(ocr_text, payload.get("extracted"))
    selected_vehicle = _text(payload, "vehicle_id", maximum=160) or None
    validation = _validate(conn, organization_id, extracted, selected_vehicle)
    selected_vehicle = validation.get("selected_vehicle_id") or selected_vehicle
    if selected_vehicle:
        extracted["vehicle_id"] = selected_vehicle
    raw_hash = _text(payload, "file_sha256", maximum=128) or hashlib.sha256(ocr_text.encode("utf-8")).hexdigest()
    storage = DEFAULT_PROVIDERS.storage.register_attachment(organization_id=organization_id, entity_type="bill_intelligence", entity_id=record_id, filename=filename, content_type=content_type, size_bytes=int(payload.get("size_bytes") or len(ocr_text.encode("utf-8"))))
    now = now_iso()
    conn.execute("INSERT INTO bill_intelligence_records(id, organization_id, source, filename, content_type, storage_reference, file_sha256, ocr_text, bill_type, vehicle_id, duty_id, supplier_id, status, extracted_json, confidence_json, validation_json, posting_json, review_note, idempotency_key, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'needs_review', ?, ?, ?, '{}', '', ?, ?, ?, ?)", (record_id, organization_id, source, filename, content_type, storage.reference, raw_hash, ocr_text, extracted["bill_type"], selected_vehicle, _text(payload, "duty_id", maximum=160) or None, _text(payload, "supplier_id", maximum=160) or None, json.dumps(extracted), json.dumps(extracted.get("confidence", {})), json.dumps(validation), idempotency_key, user["id"], now, now))
    if selected_vehicle:
        conn.execute("INSERT INTO bill_intelligence_timeline(id, organization_id, vehicle_id, bill_id, event_type, source, payload_json, event_at, created_by) VALUES (?, ?, ?, ?, 'bill_captured', 'ocr_bill', ?, ?, ?)", (new_id("biltime"), organization_id, selected_vehicle, record_id, json.dumps({"filename": filename, "bill_type": extracted["bill_type"], "confidence": extracted.get("confidence", {}).get("total_amount", 0)}), now, user["id"]))
    _audit(conn, user, "bill_intelligence.captured", "bill", record_id, ip, {"bill_type": extracted["bill_type"], "vehicle_id": selected_vehicle, "storage_reference": storage.reference, "validation": validation})
    return {"ok": True, "item": _detail(conn, record_id, organization_id), "replayed": False, "storage": storage.payload}


def _review_record(conn, user, record_id, payload, ip):
    _staff(user); organization_id = _org(user)
    row = conn.execute("SELECT * FROM bill_intelligence_records WHERE id = ? AND organization_id = ?", (record_id, organization_id)).fetchone()
    if not row:
        raise DomainError(404, "Bill record not found", "not_found")
    if row["status"] in {"posted", "reversed"}:
        raise DomainError(409, "Posted records cannot be edited; use undo to create a reversal", "immutable_bill")
    extracted = _json(row["extracted_json"], {})
    if isinstance(payload.get("fields"), dict):
        extracted.update({key: value for key, value in payload["fields"].items() if key in extracted or key in {"vehicle_id", "total_amount", "invoice_number", "odometer_km", "fuel_type", "quantity", "rate_per_unit", "policy_expiry", "policy_number"}})
    if payload.get("vehicle_id"):
        extracted["vehicle_id"] = _text(payload, "vehicle_id", maximum=160)
    validation = _validate(conn, organization_id, extracted, extracted.get("vehicle_id"))
    selected_vehicle = validation.get("selected_vehicle_id") or extracted.get("vehicle_id") or None
    now = now_iso()
    conn.execute("UPDATE bill_intelligence_records SET vehicle_id = ?, bill_type = ?, extracted_json = ?, confidence_json = ?, validation_json = ?, review_note = ?, reviewed_by = ?, updated_at = ? WHERE id = ? AND organization_id = ?", (selected_vehicle, extracted.get("bill_type", "other"), json.dumps(extracted), json.dumps(extracted.get("confidence", {})), json.dumps(validation), _text(payload, "note", maximum=500), user["id"], now, record_id, organization_id))
    _audit(conn, user, "bill_intelligence.reviewed", "bill", record_id, ip, {"vehicle_id": selected_vehicle, "validation": validation})
    return {"ok": True, "item": _detail(conn, record_id, organization_id)}


def _post_record(conn, user, record_id, payload, ip):
    _staff(user); organization_id = _org(user)
    row = conn.execute("SELECT * FROM bill_intelligence_records WHERE id = ? AND organization_id = ?", (record_id, organization_id)).fetchone()
    if not row:
        raise DomainError(404, "Bill record not found", "not_found")
    if row["status"] == "posted":
        return {"ok": True, "item": _detail(conn, record_id, organization_id), "replayed": True}
    if row["status"] == "reversed":
        raise DomainError(409, "A reversed bill cannot be posted again", "reversed_bill")
    if isinstance(payload.get("overrides"), dict):
        _review_record(conn, user, record_id, {"fields": payload["overrides"], "vehicle_id": payload.get("vehicle_id"), "note": payload.get("note", "")}, ip)
        row = conn.execute("SELECT * FROM bill_intelligence_records WHERE id = ?", (record_id,)).fetchone()
    extracted = _json(row["extracted_json"], {})
    validation = _json(row["validation_json"], {})
    if validation.get("errors"):
        raise DomainError(422, "Resolve blocking bill validation errors before posting", "bill_review_required")
    vehicle_id = _text(payload, "vehicle_id", maximum=160) or row["vehicle_id"] or validation.get("selected_vehicle_id") or extracted.get("vehicle_id")
    if not vehicle_id:
        raise DomainError(422, "Select the vehicle that this bill belongs to", "vehicle_match_required")
    vehicle = conn.execute("SELECT * FROM domain_vehicles WHERE id = ? AND organization_id = ?", (vehicle_id, organization_id)).fetchone()
    if not vehicle:
        raise DomainError(404, "Vehicle not found in this tenant", "not_found")
    total_amount = _money(extracted.get("total_amount")) or 0
    if total_amount <= 0:
        raise DomainError(422, "A positive total amount is required before posting", "amount_required")
    bill_type = extracted.get("bill_type") if extracted.get("bill_type") in BILL_TYPES else "other"
    now = now_iso(); postings = []
    invoice_number = str(extracted.get("invoice_number") or f"AI-{record_id[-10:].upper()}")
    duplicate_invoice = conn.execute("SELECT id FROM domain_supplier_bills WHERE organization_id = ? AND bill_number = ?", (organization_id, invoice_number)).fetchone()
    if duplicate_invoice:
        raise DomainError(409, "A supplier bill with this invoice number already exists", "duplicate_bill")
    attachment = {"source": "ocr_bill", "bill_id": record_id, "filename": row["filename"], "storage_reference": row["storage_reference"], "file_sha256": row["file_sha256"], "confidence": extracted.get("confidence", {})}
    supplier_bill_id = new_id("bill")
    conn.execute("INSERT INTO domain_supplier_bills(id, organization_id, supplier_id, bill_number, subtotal_paise, tax_paise, total_paise, status, due_at, duty_id, attachment_json, validation_json, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'approved', ?, ?, ?, ?, ?, ?, ?)", (supplier_bill_id, organization_id, row["supplier_id"], invoice_number, _minor(extracted.get("taxable_value") or total_amount), _minor((_money(extracted.get("cgst")) or 0) + (_money(extracted.get("sgst")) or 0) + (_money(extracted.get("igst")) or 0)), _minor(total_amount), extracted.get("invoice_date") or None, row["duty_id"], json.dumps(attachment), json.dumps({"source": "bill_intelligence", "validation": validation}), user["id"], now, now))
    postings.append(("supplier_bill", "supplier_bill", supplier_bill_id, {"status": "approved"}))
    category = {"fuel": "fuel", "maintenance": "maintenance", "toll": "toll", "insurance": "insurance", "tyre": "tyre"}.get(bill_type, "other")
    cost_id = new_id("cost")
    conn.execute("INSERT INTO domain_cost_entries(id, organization_id, cost_type, category, amount_paise, vehicle_id, duty_id, supplier_bill_id, status, attachment_json, notes, created_by, created_at) VALUES (?, ?, 'vehicle', ?, ?, ?, ?, ?, 'approved', ?, ?, ?, ?)", (cost_id, organization_id, category, _minor(total_amount), vehicle_id, row["duty_id"], supplier_bill_id, json.dumps(attachment), f"Auto-posted from bill {record_id} · confidence {float((extracted.get('confidence') or {}).get('total_amount', 0)):.2f}", user["id"], now))
    postings.append(("cost_entry", "cost_entry", cost_id, {"status": "approved", "category": category}))
    fuel_entry_id = None
    if bill_type == "fuel":
        quantity = _money(extracted.get("quantity")) or 0
        if quantity <= 0:
            raise DomainError(422, "Fuel quantity is required for a fuel bill", "quantity_required")
        odometer = _money(extracted.get("odometer_km"))
        previous = conn.execute("SELECT odometer_km FROM bill_intelligence_fuel_entries WHERE organization_id = ? AND vehicle_id = ? AND status = 'posted' AND odometer_km IS NOT NULL ORDER BY odometer_km DESC, created_at DESC LIMIT 1", (organization_id, vehicle_id)).fetchone()
        previous_odo = float(previous["odometer_km"]) if previous else float(vehicle["current_odometer_km"] or 0)
        mileage = None; anomaly = ""
        if odometer is not None and previous_odo > 0:
            mileage = (float(odometer) - previous_odo) / quantity
            if mileage <= 0:
                anomaly = "odometer_rollback"
            elif mileage > 200:
                anomaly = "mileage_outlier"
        fuel_entry_id = new_id("fuel")
        conn.execute("INSERT INTO bill_intelligence_fuel_entries(id, organization_id, bill_id, vehicle_id, duty_id, fuel_type, quantity, unit, rate_per_unit, amount_paise, odometer_km, station, invoice_date, mileage_km_per_unit, anomaly_code, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'posted', ?)", (fuel_entry_id, organization_id, record_id, vehicle_id, row["duty_id"], extracted.get("fuel_type", ""), quantity, extracted.get("unit", "L"), _money(extracted.get("rate_per_unit")), _minor(total_amount), odometer, extracted.get("vendor_name", ""), extracted.get("invoice_date") or None, mileage, anomaly, now))
        postings.append(("fuel_entry", "fuel_entry", fuel_entry_id, {"status": "posted", "previous_odo": previous_odo, "anomaly_code": anomaly}))
        conn.execute("INSERT INTO bill_intelligence_timeline(id, organization_id, vehicle_id, bill_id, event_type, source, payload_json, event_at, created_by) VALUES (?, ?, ?, ?, 'fuel_posted', 'ocr_bill', ?, ?, ?)", (new_id("biltime"), organization_id, vehicle_id, record_id, json.dumps({"fuel_entry_id": fuel_entry_id, "quantity": quantity, "amount_paise": _minor(total_amount), "mileage_km_per_unit": mileage, "anomaly_code": anomaly}), now, user["id"]))
    prior_vehicle = {"current_odometer_km": vehicle["current_odometer_km"], "odometer_updated_at": vehicle["odometer_updated_at"], "insurance_expiry": vehicle["insurance_expiry"], "insurance_policy_number": vehicle["insurance_policy_number"], "next_service_due_km": vehicle["next_service_due_km"], "next_service_due_date": vehicle["next_service_due_date"]}
    vehicle_updates = {}
    odometer = _money(extracted.get("odometer_km"))
    if odometer is not None and odometer > float(vehicle["current_odometer_km"] or 0):
        vehicle_updates.update({"current_odometer_km": odometer, "odometer_updated_at": now})
    if bill_type == "insurance":
        if extracted.get("policy_expiry"): vehicle_updates["insurance_expiry"] = extracted["policy_expiry"]
        if extracted.get("policy_number"): vehicle_updates["insurance_policy_number"] = extracted["policy_number"]
    if extracted.get("next_service_due_km") not in (None, ""): vehicle_updates["next_service_due_km"] = _money(extracted["next_service_due_km"])
    if extracted.get("next_service_due_date"): vehicle_updates["next_service_due_date"] = extracted["next_service_due_date"]
    if vehicle_updates:
        assignments = ", ".join(f"{key} = ?" for key in vehicle_updates)
        conn.execute(f"UPDATE domain_vehicles SET {assignments}, updated_at = ? WHERE id = ? AND organization_id = ?", [*vehicle_updates.values(), now, vehicle_id, organization_id])
        postings.append(("vehicle_update", "vehicle", vehicle_id, {"prior": prior_vehicle, "new": vehicle_updates}))
        conn.execute("INSERT INTO bill_intelligence_timeline(id, organization_id, vehicle_id, bill_id, event_type, source, payload_json, event_at, created_by) VALUES (?, ?, ?, ?, 'vehicle_master_updated', 'ocr_bill', ?, ?, ?)", (new_id("biltime"), organization_id, vehicle_id, record_id, json.dumps({"updated_fields": sorted(vehicle_updates), "source": "ocr_bill"}), now, user["id"]))
        if odometer is not None:
            conn.execute("INSERT INTO bill_intelligence_timeline(id, organization_id, vehicle_id, bill_id, event_type, source, payload_json, event_at, created_by) VALUES (?, ?, ?, ?, 'odometer_recorded', 'ocr_bill', ?, ?, ?)", (new_id("biltime"), organization_id, vehicle_id, record_id, json.dumps({"odometer_km": odometer, "source": "ocr_bill"}), now, user["id"]))
    for posting_type, entity_type, entity_id, posting_payload in postings:
        conn.execute("INSERT INTO bill_intelligence_postings(id, organization_id, bill_id, posting_type, entity_type, entity_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (new_id("billpost"), organization_id, record_id, posting_type, entity_type, entity_id, json.dumps(posting_payload), now))
    posting_summary = {"supplier_bill_id": supplier_bill_id, "cost_entry_id": cost_id, "fuel_entry_id": fuel_entry_id, "vehicle_id": vehicle_id, "posting_types": [item[0] for item in postings]}
    conn.execute("UPDATE bill_intelligence_records SET status = 'posted', vehicle_id = ?, posting_json = ?, reviewed_by = ?, posted_at = ?, updated_at = ? WHERE id = ? AND organization_id = ?", (vehicle_id, json.dumps(posting_summary), user["id"], now, now, record_id, organization_id))
    _audit(conn, user, "bill_intelligence.posted", "bill", record_id, ip, posting_summary)
    return {"ok": True, "item": _detail(conn, record_id, organization_id), "posted": posting_summary, "replayed": False}


def _reject_record(conn, user, record_id, payload, ip):
    _staff(user); organization_id = _org(user)
    row = conn.execute("SELECT id, status FROM bill_intelligence_records WHERE id = ? AND organization_id = ?", (record_id, organization_id)).fetchone()
    if not row:
        raise DomainError(404, "Bill record not found", "not_found")
    if row["status"] in {"posted", "reversed"}:
        raise DomainError(409, "Posted records cannot be rejected", "immutable_bill")
    note = _text(payload, "note", "Rejected by reviewer", 500)
    conn.execute("UPDATE bill_intelligence_records SET status = 'rejected', review_note = ?, reviewed_by = ?, updated_at = ? WHERE id = ? AND organization_id = ?", (note, user["id"], now_iso(), record_id, organization_id))
    _audit(conn, user, "bill_intelligence.rejected", "bill", record_id, ip, {"note": note})
    return {"ok": True, "item": _detail(conn, record_id, organization_id)}


def _undo_record(conn, user, record_id, payload, ip):
    _staff(user); organization_id = _org(user)
    row = conn.execute("SELECT * FROM bill_intelligence_records WHERE id = ? AND organization_id = ?", (record_id, organization_id)).fetchone()
    if not row:
        raise DomainError(404, "Bill record not found", "not_found")
    if row["status"] == "reversed":
        return {"ok": True, "item": _detail(conn, record_id, organization_id), "replayed": True}
    if row["status"] != "posted":
        raise DomainError(409, "Only a posted bill can be undone", "bill_not_posted")
    now = now_iso()
    for posting in conn.execute("SELECT * FROM bill_intelligence_postings WHERE organization_id = ? AND bill_id = ?", (organization_id, record_id)).fetchall():
        detail = _json(posting["payload_json"], {})
        if posting["posting_type"] == "cost_entry":
            conn.execute("UPDATE domain_cost_entries SET status = 'reversed', notes = notes || ? WHERE id = ? AND organization_id = ?", (f" · Reversed from bill {record_id}", posting["entity_id"], organization_id))
        elif posting["posting_type"] == "supplier_bill":
            conn.execute("UPDATE domain_supplier_bills SET status = 'cancelled', updated_at = ? WHERE id = ? AND organization_id = ?", (now, posting["entity_id"], organization_id))
        elif posting["posting_type"] == "fuel_entry":
            conn.execute("UPDATE bill_intelligence_fuel_entries SET status = 'reversed', reversed_at = ? WHERE id = ? AND organization_id = ?", (now, posting["entity_id"], organization_id))
        elif posting["posting_type"] == "vehicle_update":
            prior = detail.get("prior") if isinstance(detail.get("prior"), dict) else {}
            if prior:
                assignments = ", ".join(f"{key} = ?" for key in prior)
                conn.execute(f"UPDATE domain_vehicles SET {assignments}, updated_at = ? WHERE id = ? AND organization_id = ?", [*prior.values(), now, posting["entity_id"], organization_id])
    conn.execute("UPDATE bill_intelligence_records SET status = 'reversed', review_note = ?, updated_at = ? WHERE id = ? AND organization_id = ?", (_text(payload, "note", "Reversed by reviewer", 500), now, record_id, organization_id))
    vehicle_id = row["vehicle_id"]
    if vehicle_id:
        conn.execute("INSERT INTO bill_intelligence_timeline(id, organization_id, vehicle_id, bill_id, event_type, source, payload_json, event_at, created_by) VALUES (?, ?, ?, ?, 'bill_reversed', 'reviewer', ?, ?, ?)", (new_id("biltime"), organization_id, vehicle_id, record_id, json.dumps({"reason": _text(payload, "note", "Reversed by reviewer", 500)}), now, user["id"]))
    _audit(conn, user, "bill_intelligence.reversed", "bill", record_id, ip, {"reason": _text(payload, "note", "Reversed by reviewer", 500)})
    return {"ok": True, "item": _detail(conn, record_id, organization_id), "replayed": False}


def handle_bill_intelligence(conn, user, method: str, raw_route: str, payload: dict, ip: str):
    route = urlsplit(raw_route).path.rstrip("/") or "/"
    query = parse_qs(urlsplit(raw_route).query)
    if not route.startswith("/api/bill-intelligence"):
        return None
    organization_id = _org(user)
    if route == "/api/bill-intelligence/summary" and method == "GET":
        return {"ok": True, "summary": _summary(conn, organization_id)}
    if route == "/api/bill-intelligence" and method == "GET":
        status_filter = (query.get("status") or [""])[0]
        sql = "SELECT * FROM bill_intelligence_records WHERE organization_id = ?"; args: list[object] = [organization_id]
        if status_filter and status_filter != "all": sql += " AND status = ?"; args.append(status_filter)
        sql += " ORDER BY created_at DESC LIMIT ?"; args.append(_limit(query))
        items = []
        for row in conn.execute(sql, args).fetchall():
            item = _row(row, ("extracted_json", "confidence_json", "validation_json", "posting_json"))
            if row["vehicle_id"]:
                vehicle = conn.execute("SELECT registration_number, make_model FROM domain_vehicles WHERE id = ? AND organization_id = ?", (row["vehicle_id"], organization_id)).fetchone()
                item["vehicle"] = dict(vehicle) if vehicle else None
            items.append(item)
        return {"ok": True, "items": items, "count": len(items), "summary": _summary(conn, organization_id)}
    if route == "/api/bill-intelligence" and method == "POST":
        return _create_record(conn, user, payload, ip)
    timeline_match = re.fullmatch(r"/api/bill-intelligence/vehicles/([^/]+)/timeline", route)
    if timeline_match and method == "GET":
        vehicle_id = timeline_match.group(1)
        vehicle = conn.execute("SELECT id, registration_number, make_model FROM domain_vehicles WHERE id = ? AND organization_id = ?", (vehicle_id, organization_id)).fetchone()
        if not vehicle: raise DomainError(404, "Vehicle not found", "not_found")
        rows = conn.execute("SELECT * FROM bill_intelligence_timeline WHERE organization_id = ? AND vehicle_id = ? ORDER BY event_at DESC LIMIT ?", (organization_id, vehicle_id, _limit(query, 100))).fetchall()
        return {"ok": True, "vehicle": dict(vehicle), "items": [_row(row, ("payload_json",)) for row in rows], "count": len(rows)}
    detail_match = re.fullmatch(r"/api/bill-intelligence/([^/]+)(?:/(review|approve|reject|undo))?", route)
    if detail_match:
        record_id, action = detail_match.groups()
        if method == "GET" and not action:
            return {"ok": True, "item": _detail(conn, record_id, organization_id)}
        if method == "POST" and action == "review": return _review_record(conn, user, record_id, payload, ip)
        if method == "POST" and action == "approve": return _post_record(conn, user, record_id, payload, ip)
        if method == "POST" and action == "reject": return _reject_record(conn, user, record_id, payload, ip)
        if method == "POST" and action == "undo": return _undo_record(conn, user, record_id, payload, ip)
    raise DomainError(404, "Bill intelligence route not found", "not_found")
