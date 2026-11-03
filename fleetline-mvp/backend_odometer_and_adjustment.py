"""Axiom Mobility (Fleetline) - Odometer Continuity Auditor & Post-Invoice Adjustments.

Implements:
1. Sequential Vehicle Odometer Continuity Checker (Rollback detection & Dead Mileage gaps).
2. Partial Batch Commit & Error-Row CSV Exporter (21st column axiom_error_explanation).
3. Multi-Row Bulk Correction & Rate-Card Re-evaluation (Staged rows and completed duties).
4. Post-Invoice Credit Note / Supplementary Debit Note Generator (GST audit compliance).
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit
import uuid

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend_domain import DomainError, _audit, new_id, now_iso
from backend_practical_pricing import recalculate_practical_tariffs


def initialize_odometer_and_adjustment_schema(conn: sqlite3.Connection) -> None:
    """Initializes SQLite tables and columns for odometer continuity & credit/debit notes."""
    # 1. Upgrade completed_trip_import_rows
    cols_rows = {r["name"] for r in conn.execute("PRAGMA table_info(completed_trip_import_rows)").fetchall()}
    needed_import_cols = {
        "prev_duty_id": "TEXT",
        "prev_duty_end_km": "REAL",
        "dead_mileage_gap_km": "REAL",
        "odometer_continuity_status": "TEXT DEFAULT 'FIRST_VEHICLE_TRIP'",
        "continuity_message": "TEXT",
    }
    for col, c_type in needed_import_cols.items():
        if col not in cols_rows:
            try:
                conn.execute(f"ALTER TABLE completed_trip_import_rows ADD COLUMN {col} {c_type}")
            except Exception:
                pass

    # 2. Upgrade domain_duties
    cols_duties = {r["name"] for r in conn.execute("PRAGMA table_info(domain_duties)").fetchall()}
    needed_duty_cols = {
        "prev_duty_id": "TEXT",
        "prev_duty_end_km": "REAL",
        "dead_mileage_gap_km": "REAL",
        "odometer_continuity_status": "TEXT DEFAULT 'FIRST_VEHICLE_TRIP'",
        "continuity_message": "TEXT",
        "invoice_status": "TEXT DEFAULT 'UNBILLED'",
        "invoice_id": "TEXT",
        "toll_parking_inr": "REAL DEFAULT 0.0",
    }
    for col, c_type in needed_duty_cols.items():
        if col not in cols_duties:
            try:
                conn.execute(f"ALTER TABLE domain_duties ADD COLUMN {col} {c_type}")
            except Exception:
                pass

    # 3. Create financial_credit_debit_notes table
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS financial_credit_debit_notes (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            original_duty_id TEXT NOT NULL,
            original_invoice_id TEXT,
            note_type TEXT NOT NULL CHECK (note_type IN ('CREDIT_NOTE_CLIENT', 'DEBIT_NOTE_CLIENT', 'CREDIT_NOTE_SUPPLIER', 'DEBIT_NOTE_SUPPLIER')),
            note_number TEXT NOT NULL UNIQUE,
            previous_amount_inr REAL NOT NULL,
            corrected_amount_inr REAL NOT NULL,
            delta_amount_inr REAL NOT NULL,
            gst_adjustment_inr REAL NOT NULL DEFAULT 0.00,
            reason_code TEXT NOT NULL DEFAULT 'ODOMETER_PRICE_CORRECTION',
            remarks TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_cdn_tenant_duty ON financial_credit_debit_notes(tenant_id, original_duty_id);
        CREATE INDEX IF NOT EXISTS idx_cdn_invoice ON financial_credit_debit_notes(original_invoice_id);
        """
    )


def audit_vehicle_odometer_continuity(
    conn: sqlite3.Connection,
    tenant_id: str,
    vehicle_id_or_reg: str,
    start_km: float,
    duty_start_time: Optional[str] = None,
    current_duty_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Audits vehicle odometer continuity against previous completed duties.

    Detects:
    1. Rollbacks: start_km < previous_trip_end_km
    2. High Dead Mileage Gaps: start_km - previous_trip_end_km > 50.0 km
    """
    if not vehicle_id_or_reg:
        return {
            "odometer_continuity_status": "FIRST_VEHICLE_TRIP",
            "prev_duty_id": None,
            "prev_duty_end_km": None,
            "dead_mileage_gap_km": 0.0,
            "message": "No vehicle assigned yet",
        }

    clean_reg = re.sub(r"[^A-Za-z0-9]", "", str(vehicle_id_or_reg)).upper()

    # Find vehicle
    veh = conn.execute(
        """
        SELECT id, registration_number FROM domain_vehicles
        WHERE (organization_id = ? OR ? = 'org_default')
          AND (id = ? OR UPPER(registration_number) = ? OR UPPER(REPLACE(REPLACE(registration_number, '-', ''), ' ', '')) = ?)
        LIMIT 1
        """,
        (tenant_id, tenant_id, vehicle_id_or_reg, vehicle_id_or_reg.upper(), clean_reg),
    ).fetchone()

    veh_id = veh["id"] if veh else vehicle_id_or_reg
    veh_reg = veh["registration_number"] if veh else vehicle_id_or_reg

    # Query preceding completed duty
    query = """
        SELECT id, practical_start_km, practical_end_km, end_odometer, practical_end_time, completed_at
        FROM domain_duties
        WHERE (organization_id = ? OR ? = 'org_default')
          AND vehicle_id = ?
          AND status IN ('completed', 'closed', 'billed')
    """
    params: List[Any] = [tenant_id, tenant_id, veh_id]

    if current_duty_id:
        query += " AND id != ?"
        params.append(current_duty_id)

    query += " ORDER BY COALESCE(practical_end_time, completed_at, updated_at) DESC, practical_end_km DESC LIMIT 1"

    prev_duty = conn.execute(query, tuple(params)).fetchone()
    if not prev_duty:
        return {
            "odometer_continuity_status": "FIRST_VEHICLE_TRIP",
            "prev_duty_id": None,
            "prev_duty_end_km": None,
            "dead_mileage_gap_km": 0.0,
            "message": f"First recorded trip for vehicle {veh_reg} in platform",
        }

    prev_end_km = float(prev_duty["practical_end_km"] or prev_duty["end_odometer"] or 0.0)
    gap_km = round(start_km - prev_end_km, 1)

    # Rule 1: Rollback Error
    if start_km < prev_end_km:
        diff = round(prev_end_km - start_km, 1)
        return {
            "odometer_continuity_status": "ROLLBACK_ERROR",
            "prev_duty_id": prev_duty["id"],
            "prev_duty_end_km": prev_end_km,
            "dead_mileage_gap_km": gap_km,
            "message": f"Start KM ({start_km:,.0f}) is lower than Vehicle {veh_reg}'s previous trip End KM ({prev_end_km:,.0f}) by {diff:,.0f} km",
        }

    # Rule 2: High Dead Mileage Gap (> 50 km)
    if gap_km > 50.0:
        return {
            "odometer_continuity_status": "HIGH_DEAD_MILEAGE_GAP",
            "prev_duty_id": prev_duty["id"],
            "prev_duty_end_km": prev_end_km,
            "dead_mileage_gap_km": gap_km,
            "message": f"{gap_km:,.0f} km unaccounted gap since last trip ended — check for unauthorized vehicle usage or typo",
        }

    # Rule 3: Continuous OK
    return {
        "odometer_continuity_status": "CONTINUOUS_OK",
        "prev_duty_id": prev_duty["id"],
        "prev_duty_end_km": prev_end_km,
        "dead_mileage_gap_km": gap_km,
        "message": f"Continuous (+{gap_km:,.0f} km from prev trip)",
    }


def export_batch_errors_csv(conn: sqlite3.Connection, user: Dict[str, Any], batch_id: str) -> Dict[str, Any]:
    """Generates a downloadable CSV containing ONLY the ERROR and unapproved WARNING rows from a staging batch.

    Preserves the exact 20 standardized columns plus a 21st column 'axiom_error_explanation'.
    Pre-pends UTF-8 BOM so operators can edit directly in Microsoft Excel.
    """
    tenant_id = user.get("organization_id") or "org_default"

    from backend_completed_trips_importer import STANDARDIZED_SAMPLE_HEADERS

    headers_21 = list(STANDARDIZED_SAMPLE_HEADERS) + ["axiom_error_explanation"]

    rows = conn.execute(
        """
        SELECT id, row_number, raw_json, normalized_payload, validation_status, validation_messages
        FROM completed_trip_import_rows
        WHERE batch_id = ? AND (tenant_id = ? OR ? = 'org_default')
          AND validation_status IN ('ERROR_MISSING_REF', 'DUPLICATE_TRIPSHEET', 'WARNING_VARIANCE')
        ORDER BY row_number ASC
        """,
        (batch_id, tenant_id, tenant_id),
    ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers_21)

    for r in rows:
        norm = json.loads(r["normalized_payload"]) if r["normalized_payload"] else {}
        raw = json.loads(r["raw_json"]) if r["raw_json"] else {}
        messages = json.loads(r["validation_messages"]) if r["validation_messages"] else []

        explanation = " | ".join(messages) if messages else f"Validation Status: {r['validation_status']}"

        row_cells = [
            norm.get("external_tripsheet_no") or raw.get("external_tripsheet_no") or raw.get("Trip Sheet No") or f"TS-{r['row_number']:04d}",
            norm.get("trip_date") or raw.get("trip_date") or "",
            norm.get("corporate_name") or raw.get("corporate_name") or raw.get("Corporate") or "",
            norm.get("passenger_name") or raw.get("passenger_name") or raw.get("Passenger Name") or "",
            norm.get("passenger_phone") or raw.get("passenger_phone") or raw.get("Passenger Phone") or "",
            norm.get("pickup_location") or raw.get("pickup_location") or "",
            norm.get("drop_location") or raw.get("drop_location") or "",
            norm.get("duty_type") or raw.get("duty_type") or "LOCAL",
            norm.get("vehicle_category") or raw.get("vehicle_category") or "Sedan",
            norm.get("vehicle_registration") or raw.get("vehicle_registration") or raw.get("Cab No") or "",
            norm.get("driver_name") or raw.get("driver_name") or "",
            norm.get("driver_phone") or raw.get("driver_phone") or "",
            norm.get("practical_start_time") or raw.get("start_time") or raw.get("Start Time") or "",
            norm.get("practical_end_time") or raw.get("end_time") or raw.get("End Time") or "",
            norm.get("practical_start_km", raw.get("Start KM", 1000)),
            norm.get("practical_end_km", raw.get("End KM", 1040)),
            norm.get("toll_parking_inr", raw.get("Toll/Parking", 0)),
            norm.get("client_final_price_inr", raw.get("Billed Amount", 0)),
            norm.get("supplier_final_payout_inr", 0),
            norm.get("remarks") or raw.get("remarks") or "",
            explanation,
        ]
        writer.writerow(row_cells)

    csv_text = output.getvalue()
    csv_bytes = "\ufeff" + csv_text

    return {
        "ok": True,
        "batch_id": batch_id,
        "format": "csv",
        "error_rows_count": len(rows),
        "filename": f"completed_trips_errors_{batch_id}.csv",
        "_content_type": "text/csv; charset=utf-8",
        "_disposition": f'attachment; filename="completed_trips_errors_{batch_id}.csv"',
        "_raw_body": csv_bytes,
        "csv_text": csv_bytes,
    }


def bulk_correct_duties(
    conn: sqlite3.Connection,
    user: Dict[str, Any],
    payload: Dict[str, Any],
    ip: str = "127.0.0.1",
) -> Dict[str, Any]:
    """Multi-row bulk correction and rate-card re-evaluation for staged rows or completed duties."""
    tenant_id = user.get("organization_id") or "org_default"
    action = payload.get("patch_action") or payload.get("action")
    now = now_iso()

    staged_row_ids = payload.get("row_ids") or []
    duty_ids = payload.get("duty_ids") or []

    modified_count = 0
    updated_items = []

    # 1. Staged Rows Bulk Correction
    if staged_row_ids:
        from backend_completed_trips_importer import update_staged_trip_row

        for r_id in staged_row_ids:
            row = conn.execute("SELECT * FROM completed_trip_import_rows WHERE id = ?", (r_id,)).fetchone()
            if not row:
                continue
            norm = json.loads(row["normalized_payload"]) if row["normalized_payload"] else {}

            patch_data: Dict[str, Any] = {}
            override_lock = None

            if action == "RECALCULATE_FROM_RATE_CARD":
                override_lock = False
                patch_data["override_tariff_lock"] = False
            elif action == "SET_CORPORATE" and payload.get("corporate_name"):
                patch_data["corporate_name"] = payload["corporate_name"]
            elif action == "SET_SUPPLIER_VENDOR" and payload.get("supplier_vendor"):
                patch_data["supplier_vendor"] = payload["supplier_vendor"]
            elif action == "ADD_TOLL_PARKING" and payload.get("toll_parking_inr") is not None:
                patch_data["toll_parking_inr"] = float(payload["toll_parking_inr"])
            elif action == "APPROVE_WARNINGS":
                override_lock = True
                patch_data["override_tariff_lock"] = True

            res = update_staged_trip_row(conn, user, r_id, patch_data, ip)
            if res.get("ok"):
                modified_count += 1
                updated_items.append(res["row"])

    # 2. Completed Duties Bulk Correction
    if duty_ids:
        from backend_completed_trips_importer import correct_duty_trip_details

        for d_id in duty_ids:
            duty = conn.execute("SELECT * FROM domain_duties WHERE id = ?", (d_id,)).fetchone()
            if not duty:
                continue

            patch_data = {}
            if action == "RECALCULATE_FROM_RATE_CARD":
                patch_data["override_tariff_lock"] = False
            elif action == "SET_CORPORATE" and payload.get("customer_id"):
                conn.execute(
                    "UPDATE domain_bookings SET customer_id = ?, updated_at = ? WHERE id = ?",
                    (payload["customer_id"], now, duty["booking_id"]),
                )
            elif action == "ADD_TOLL_PARKING" and payload.get("toll_parking_inr") is not None:
                patch_data["toll_parking_inr"] = float(payload["toll_parking_inr"])
            elif action == "APPROVE_WARNINGS":
                patch_data["override_tariff_lock"] = True

            res = correct_duty_trip_details(conn, user, d_id, patch_data, ip)
            if res.get("ok"):
                modified_count += 1
                updated_items.append(res)

    _audit(
        conn,
        user,
        "duties.bulk_corrected",
        "duties_bulk",
        f"bulk_{len(staged_row_ids) or len(duty_ids)}",
        ip,
        {"action": action, "modified_count": modified_count},
    )

    return {
        "ok": True,
        "action": action,
        "modified_count": modified_count,
        "updated_count": modified_count,
        "updated_items": updated_items,
    }


def create_post_invoice_adjustment(
    conn: sqlite3.Connection,
    user: Dict[str, Any],
    duty_id: str,
    payload: Dict[str, Any],
    ip: str = "127.0.0.1",
) -> Dict[str, Any]:
    """Generates an immutable Credit Note or Supplementary Debit Note for already-invoiced completed trips.

    Keeps the original GST Tax Invoice immutable.
    Generates:
    - CREDIT_NOTE_CLIENT when delta < 0 (client was overbilled)
    - DEBIT_NOTE_CLIENT when delta > 0 (client was underbilled)
    """
    tenant_id = user.get("organization_id") or "org_default"
    user_id = user.get("id") or "usr_ops"
    now = now_iso()

    duty = conn.execute(
        "SELECT * FROM domain_duties WHERE id = ? AND (organization_id = ? OR ? = 'org_default')",
        (duty_id, tenant_id, tenant_id),
    ).fetchone()
    if not duty:
        raise DomainError(404, f"Duty '{duty_id}' not found", "not_found")

    # Invoiced reference
    invoice_id = duty["invoice_id"] if "invoice_id" in duty.keys() and duty["invoice_id"] else f"INV-{duty_id[:8].upper()}"

    original_fare = float(duty["final_client_fare_inr"] or 0.0)
    original_payout = float(duty["final_supplier_payout_inr"] or 0.0)

    # Calculate new values
    start_km = float(payload.get("practical_start_km", duty["practical_start_km"] or duty["start_odometer"] or 0.0))
    end_km = float(payload.get("practical_end_km", duty["practical_end_km"] or duty["end_odometer"] or (start_km + 40.0)))
    billable_km = max(0.0, end_km - start_km)

    toll_parking = float(payload.get("toll_parking_inr", 0.0))
    override_lock = bool(payload.get("override_tariff_lock", False))

    manual_fare = payload.get("final_client_fare_inr") if "final_client_fare_inr" in payload else payload.get("client_final_price_inr")
    if override_lock and manual_fare is not None:
        corrected_fare = float(manual_fare)
        manual_payout = payload.get("final_supplier_payout_inr") if "final_supplier_payout_inr" in payload else payload.get("supplier_final_payout_inr")
        corrected_payout = float(manual_payout) if manual_payout is not None else original_payout
    else:
        pricing = recalculate_practical_tariffs(
            practical_km=billable_km,
            practical_duration_mins=240,
            base_rate_inr=1500.0,
            extra_km_rate_inr=25.0,
            extra_hr_rate_inr=150.0,
            toll_parking_inr=toll_parking,
        )
        corrected_fare = pricing["final_client_fare_inr"]
        corrected_payout = pricing["final_supplier_payout_inr"]

    delta_fare = round(corrected_fare - original_fare, 2)
    delta_payout = round(corrected_payout - original_payout, 2)

    note_id = f"cdn_{uuid.uuid4().hex[:10]}"
    note_type = "DEBIT_NOTE_CLIENT" if delta_fare > 0 else "CREDIT_NOTE_CLIENT"
    note_number = f"{'DN' if delta_fare > 0 else 'CN'}-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m')}-{uuid.uuid4().hex[:6].upper()}"
    remarks = payload.get("remarks") or payload.get("reason") or "Odometer and pricing adjustment post GST invoice finalization"

    # GST is typically 5% on rental in India
    gst_adjustment = round(abs(delta_fare) * 0.05, 2)

    # 1. Insert note record
    conn.execute(
        """
        INSERT INTO financial_credit_debit_notes (
            id, tenant_id, original_duty_id, original_invoice_id, note_type, note_number,
            previous_amount_inr, corrected_amount_inr, delta_amount_inr, gst_adjustment_inr,
            reason_code, remarks, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ODOMETER_PRICE_CORRECTION', ?, ?, ?, ?)
        """,
        (
            note_id,
            tenant_id,
            duty_id,
            invoice_id,
            note_type,
            note_number,
            original_fare,
            corrected_fare,
            abs(delta_fare),
            gst_adjustment,
            remarks,
            user_id,
            now,
            now,
        ),
    )

    # 2. Update duty with corrected operational metrics but keep closing_source auditable
    conn.execute(
        """
        UPDATE domain_duties
        SET practical_start_km = ?,
            practical_end_km = ?,
            practical_billable_km = ?,
            final_client_fare_inr = ?,
            final_supplier_payout_inr = ?,
            closing_source = 'POST_INVOICE_ADJUSTMENT',
            updated_at = ?
        WHERE id = ? AND (organization_id = ? OR ? = 'org_default')
        """,
        (
            start_km,
            end_km,
            billable_km,
            corrected_fare,
            corrected_payout,
            now,
            duty_id,
            tenant_id,
            tenant_id,
        ),
    )

    # 3. Adjust Dual-Ledger supplier_payable_ledger
    try:
        payout_paise = int(round(corrected_payout * 100))
        conn.execute(
            """
            UPDATE supplier_payable_ledger
            SET amount_paise = ?, updated_at = ?
            WHERE duty_id = ?
            """,
            (payout_paise, now, duty_id),
        )
    except Exception:
        pass

    _audit(
        conn,
        user,
        "financial.credit_debit_note_issued",
        "financial_note",
        note_id,
        ip,
        {
            "duty_id": duty_id,
            "note_number": note_number,
            "note_type": note_type,
            "delta_amount_inr": abs(delta_fare),
            "original_fare": original_fare,
            "corrected_fare": corrected_fare,
        },
    )

    return {
        "ok": True,
        "note_id": note_id,
        "note_number": note_number,
        "note_type": note_type,
        "original_invoice_id": invoice_id,
        "previous_amount_inr": original_fare,
        "corrected_amount_inr": corrected_fare,
        "delta_amount_inr": abs(delta_fare),
        "gst_adjustment_inr": gst_adjustment,
        "is_credit_note": delta_fare < 0,
        "is_debit_note": delta_fare > 0,
        "duty_id": duty_id,
        "practical_billable_km": billable_km,
        "created_at": now,
    }


def handle_odometer_and_adjustment_api(
    conn: sqlite3.Connection,
    user: Dict[str, Any],
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    ip: str = "127.0.0.1",
) -> Optional[Dict[str, Any]]:
    """Master routing dispatcher for Odometer Continuity and Credit/Debit Adjustment APIs."""
    payload = payload or {}
    norm_path = path.replace("/api/v1", "/api")
    clean_path = urlsplit(norm_path).path

    # 1. Export Batch Errors CSV: GET /api/imports/completed-trips/{batch_id}/export-errors
    if "/api/imports/completed-trips/" in clean_path and clean_path.endswith("/export-errors") and method == "GET":
        parts = clean_path.split("/api/imports/completed-trips/")[1].split("/export-errors")[0]
        batch_id = parts.strip("/")
        return export_batch_errors_csv(conn, user, batch_id)

    # 2. Bulk Multi-Row Correction: PATCH / POST /api/duties/bulk-correct
    if clean_path in ("/api/duties/bulk-correct", "/api/imports/completed-trips/bulk-correct") and method in ("PATCH", "POST"):
        return bulk_correct_duties(conn, user, payload, ip)

    # 3. Post-Invoice Adjustment: POST /api/duties/{duty_id}/post-invoice-adjustment
    if "/api/duties/" in clean_path and clean_path.endswith("/post-invoice-adjustment") and method == "POST":
        parts = clean_path.split("/api/duties/")[1].split("/post-invoice-adjustment")[0]
        duty_id = parts.strip("/")
        return create_post_invoice_adjustment(conn, user, duty_id, payload, ip)

    return None
