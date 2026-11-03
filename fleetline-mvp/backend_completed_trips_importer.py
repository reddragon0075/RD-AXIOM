"""Axiom Mobility (Fleetline) - Completed Trips Bulk Upload & Reconciliation Engine.

High-speed bulk ingestion pipeline for historical/offline completed trips:
1. Smart Fuzzy Header & Indian Date/Time Normalizer (CSV/Excel).
2. In-Memory Batch Entity Resolution (Customers, Vehicles, Drivers) - No N+1 queries.
3. Duplicate Trip-Sheet / Double-Billing Prevention Guard.
4. Auto-Tariff & Dual-Ledger Margin Dry Run with Warning Variance Detection.
5. Atomic Transaction Commit to Bookings, Duties, and Supplier Payable Ledger.
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

# Canonical fuzzy header mappings for Indian fleet operations
HEADER_ALIASES = {
    "external_tripsheet_no": [
        "external_tripsheet_no", "trip sheet no", "duty slip #", "duty slip no", "trip sheet", "tripsheet no",
        "tripsheet", "trip #", "slip no", "duty slip", "trip id", "ticket no", "duties no"
    ],
    "trip_date": [
        "trip_date", "trip date", "date", "duty date", "booking date", "start date"
    ],
    "vehicle_registration": [
        "vehicle_registration", "cab no", "reg no", "vehicle reg", "vehicle no", "car no", "vehicle number",
        "registration number", "registration", "cab number", "taxi no"
    ],
    "corporate_name": [
        "corporate_name", "corp name", "corporate", "client", "customer", "company", "corporate name",
        "client name", "account", "corp"
    ],
    "passenger_name": [
        "passenger_name", "passenger name", "passenger", "user", "guest", "employee", "rider", "emp name"
    ],
    "passenger_phone": [
        "passenger_phone", "passenger phone", "phone", "mobile", "contact", "rider phone", "passenger contact"
    ],
    "pickup_location": [
        "pickup_location", "pickup location", "pickup", "from", "origin", "reporting address", "pickup address"
    ],
    "drop_location": [
        "drop_location", "drop location", "dropoff", "drop", "destination", "drop address"
    ],
    "duty_type": [
        "duty_type", "duty type", "rental type", "package", "service type", "billing model", "tariff type"
    ],
    "driver_name": [
        "driver_name", "driver name", "driver", "pilot", "chauffeur"
    ],
    "driver_phone": [
        "driver_phone", "driver phone", "driver mobile", "driver contact"
    ],
    "practical_start_km": [
        "practical_start_km", "start km", "opening km", "start odo", "starting km", "start odometer",
        "open km", "initial km"
    ],
    "practical_end_km": [
        "practical_end_km", "end km", "closing km", "end odo", "ending km", "end odometer",
        "close km", "final km"
    ],
    "practical_start_time": [
        "practical_start_time", "start_time", "start time", "report time", "pickup time", "started at", "reporting time",
        "start datetime", "pickup datetime"
    ],
    "practical_end_time": [
        "practical_end_time", "end_time", "end time", "drop time", "release time", "completed at", "closing time",
        "end datetime", "drop datetime"
    ],
    "toll_parking_inr": [
        "toll_parking_inr", "toll/parking", "toll", "parking", "tolls", "toll and parking", "toll amount",
        "parking amount", "misc charges"
    ],
    "manual_billed_amount": [
        "client_final_price_inr", "manual_billed_amount", "billed amount", "client fare", "billed fare", "invoice amount", "amount",
        "total fare", "billed inr", "net fare", "client price"
    ],
    "supplier_final_payout_inr": [
        "supplier_final_payout_inr", "supplier payout", "driver payout", "vendor payout", "supplier cost", "supplier fare"
    ],
    "remarks": [
        "remarks", "remark", "notes", "comment", "description", "special instructions"
    ],
    "vehicle_category": [
        "vehicle_category", "vehicle category", "vehicle type", "category", "car type", "segment", "cab type"
    ],
}

STANDARDIZED_SAMPLE_HEADERS = [
    "external_tripsheet_no",
    "trip_date",
    "corporate_name",
    "passenger_name",
    "passenger_phone",
    "pickup_location",
    "drop_location",
    "duty_type",
    "vehicle_category",
    "vehicle_registration",
    "driver_name",
    "driver_phone",
    "start_time",
    "end_time",
    "practical_start_km",
    "practical_end_km",
    "toll_parking_inr",
    "client_final_price_inr",
    "supplier_final_payout_inr",
    "remarks",
]

SAMPLE_TEMPLATE_ROWS = [
    [
        "TS-2026-001",
        "2026-11-03",
        "Infosys Campus",
        "Vikram Malhotra",
        "+919880023456",
        "Electronic City Phase 1",
        "BLR Airport Terminal 2",
        "AIRPORT_TRANSFER",
        "Sedan",
        "KA-01-MJ-4412",
        "Ramesh Kumar",
        "+919880011223",
        "2026-11-03 06:30",
        "2026-11-03 08:45",
        "14200",
        "14256",
        "120",
        "2450.00",
        "1950.00",
        "Airport drop via Tollway",
    ],
    [
        "TS-2026-002",
        "2026-11-03",
        "Goldman Sachs",
        "Anita Sharma",
        "+919880034567",
        "Embassy GolfLinks Domlur",
        "Whitefield ITPL",
        "LOCAL_8HR_80KM",
        "SUV / Innova",
        "KA-04-AK-9821",
        "Suresh Gowda",
        "+919880022334",
        "2026-11-03 09:00",
        "2026-11-03 17:30",
        "28540",
        "28618",
        "0",
        "3850.00",
        "3100.00",
        "Full day executive disposal",
    ],
    [
        "TS-2026-003",
        "2026-11-03",
        "Microsoft Bellandur",
        "Rohan Varma",
        "+919880045678",
        "Outer Ring Road Bellandur",
        "MG Road Metro",
        "LOCAL_4HR_40KM",
        "Sedan",
        "KA-01-MJ-4412",
        "Manjunath B",
        "+919880033445",
        "2026-11-03 14:00",
        "2026-11-03 18:00",
        "14256",
        "14296",
        "50",
        "1850.00",
        "1450.00",
        "Client meeting return",
    ],
]


def generate_sample_template(format_type: str = "csv") -> Dict[str, Any]:
    """Generates standardized sample template pre-populated with exact headers & realistic sample rows."""
    format_clean = str(format_type or "csv").strip().lower()
    if format_clean == "json":
        return {
            "ok": True,
            "format": "json",
            "headers": STANDARDIZED_SAMPLE_HEADERS,
            "rows": [dict(zip(STANDARDIZED_SAMPLE_HEADERS, row)) for row in SAMPLE_TEMPLATE_ROWS],
        }

    # Generate CSV with UTF-8 BOM so Excel opens Indian Rupee values and timestamps cleanly
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(STANDARDIZED_SAMPLE_HEADERS)
    for row in SAMPLE_TEMPLATE_ROWS:
        writer.writerow(row)

    csv_text = output.getvalue()
    csv_bytes = "\ufeff" + csv_text

    return {
        "ok": True,
        "format": "csv",
        "filename": "axiom_completed_trips_template.csv",
        "_content_type": "text/csv; charset=utf-8",
        "_disposition": 'attachment; filename="axiom_completed_trips_template.csv"',
        "_raw_body": csv_bytes,
        "csv_text": csv_bytes,
        "headers": STANDARDIZED_SAMPLE_HEADERS,
        "rows_count": len(SAMPLE_TEMPLATE_ROWS),
    }


def initialize_bulk_importer_schema(conn: sqlite3.Connection) -> None:
    """Initializes tables for bulk import batches and staging rows."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS completed_trip_import_batches (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            uploaded_by TEXT NOT NULL,
            filename TEXT NOT NULL,
            total_rows INTEGER NOT NULL DEFAULT 0,
            valid_rows INTEGER NOT NULL DEFAULT 0,
            warning_rows INTEGER NOT NULL DEFAULT 0,
            error_rows INTEGER NOT NULL DEFAULT 0,
            duplicate_rows INTEGER NOT NULL DEFAULT 0,
            estimated_total_receivable_inr REAL NOT NULL DEFAULT 0.0,
            estimated_total_payable_inr REAL NOT NULL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'STAGED_DRY_RUN' CHECK (status IN ('STAGED_DRY_RUN', 'COMMITTED', 'CANCELLED')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS completed_trip_import_rows (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            row_number INTEGER NOT NULL,
            raw_json TEXT NOT NULL DEFAULT '{}',
            normalized_payload TEXT NOT NULL DEFAULT '{}',
            validation_status TEXT NOT NULL DEFAULT 'VALID' CHECK (validation_status IN ('VALID', 'WARNING_VARIANCE', 'ERROR_MISSING_REF', 'DUPLICATE_TRIPSHEET')),
            validation_messages TEXT NOT NULL DEFAULT '[]',
            computed_client_fare_inr REAL NOT NULL DEFAULT 0.0,
            computed_supplier_payout_inr REAL NOT NULL DEFAULT 0.0,
            applied_slab_name TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (batch_id) REFERENCES completed_trip_import_batches(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_trip_import_tenant ON completed_trip_import_batches(tenant_id, status);
        CREATE INDEX IF NOT EXISTS idx_import_rows_batch_status ON completed_trip_import_rows(batch_id, validation_status);
        """
    )

    # Ensure domain_duties has external_tripsheet_no & import_batch_id
    cols_duties = {r["name"] for r in conn.execute("PRAGMA table_info(domain_duties)").fetchall()}
    for col in ("external_tripsheet_no", "import_batch_id"):
        if col not in cols_duties:
            try:
                conn.execute(f"ALTER TABLE domain_duties ADD COLUMN {col} TEXT")
            except Exception:
                pass

    # Ensure odometer continuity and adjustment schema
    try:
        from backend_odometer_and_adjustment import initialize_odometer_and_adjustment_schema
        initialize_odometer_and_adjustment_schema(conn)
    except Exception:
        pass


def clean_reg_number(reg: Optional[str]) -> str:
    """Normalizes vehicle plate numbers by removing hyphens and spaces (e.g. KA-01-MJ-4412 -> KA01MJ4412)."""
    if not reg:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", str(reg)).upper()


def normalize_indian_timestamp(val: Any) -> str:
    """Parses diverse Indian date/time string formats into standard ISO-8601 strings."""
    if not val:
        return now_iso()
    raw = str(val).strip()
    if not raw:
        return now_iso()

    # Try standard ISO first
    if "T" in raw and len(raw) >= 16:
        return raw

    # Common Indian date formats: DD-MM-YYYY, DD/MM/YYYY, YYYY-MM-DD
    patterns = [
        ("%d-%m-%Y %H:%M", True),
        ("%d/%m/%Y %H:%M", True),
        ("%Y-%m-%d %H:%M", True),
        ("%d-%m-%Y %I:%M %p", True),
        ("%d/%m/%Y %I:%M %p", True),
        ("%d-%m-%Y", False),
        ("%d/%m/%Y", False),
        ("%Y-%m-%d", False),
    ]

    for pat, has_time in patterns:
        try:
            parsed = dt.datetime.strptime(raw, pat)
            if not has_time:
                parsed = parsed.replace(hour=9, minute=0, second=0)
            return parsed.replace(tzinfo=dt.timezone.utc).isoformat()
        except Exception:
            continue

    return now_iso()


def match_header(header_name: str) -> Optional[str]:
    """Matches a spreadsheet column header against our canonical dictionary."""
    clean = header_name.strip().lower()
    # 1. Exact match pass
    for field, aliases in HEADER_ALIASES.items():
        if clean == field or clean in aliases:
            return field
    # 2. Token match pass (requires alias length >= 4)
    for field, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if len(alias) >= 4 and (alias in clean or clean in alias):
                return field
    return None


def parse_csv_or_matrix(raw_data: str) -> List[Dict[str, Any]]:
    """Parses CSV text into a list of normalized row dictionaries."""
    f = io.StringIO(raw_data.strip())
    reader = csv.reader(f)
    try:
        raw_headers = next(reader)
    except StopIteration:
        return []

    # Map headers
    field_mapping = {}
    for idx, h in enumerate(raw_headers):
        canonical = match_header(h)
        if canonical:
            field_mapping[idx] = canonical

    rows = []
    for line_idx, row in enumerate(reader):
        if not row or all(not cell.strip() for cell in row):
            continue
        row_dict = {}
        for col_idx, cell in enumerate(row):
            target_field = field_mapping.get(col_idx)
            if target_field:
                row_dict[target_field] = cell.strip()
            else:
                row_dict[f"raw_col_{col_idx}"] = cell.strip()
        rows.append(row_dict)

    return rows


def stage_completed_trips(
    conn: sqlite3.Connection,
    user: Dict[str, Any],
    file_content: str,
    filename: str = "completed_trips.csv",
) -> Dict[str, Any]:
    """Step 1 & 2: Ingests, normalizes, dry-runs tariff calculations & detects duplicates."""
    tenant_id = user.get("organization_id") or "org_default"
    user_id = user.get("id") or "usr_ops"
    batch_id = f"batch_{uuid.uuid4().hex[:10]}"
    now = now_iso()

    parsed_rows = parse_csv_or_matrix(file_content)
    if not parsed_rows:
        raise DomainError(400, "Spreadsheet contains no valid data rows or unreadable headers", "empty_import")

    # In-memory bulk entity caches (NO N+1 queries)
    # 1. Existing duties for duplicate check
    existing_duty_rows = conn.execute(
        "SELECT external_tripsheet_no FROM domain_duties WHERE organization_id = ? AND external_tripsheet_no IS NOT NULL",
        (tenant_id,),
    ).fetchall()
    existing_tripsheets = {r["external_tripsheet_no"] for r in existing_duty_rows if r["external_tripsheet_no"]}

    # 2. Existing vehicles cache (both exact & normalized plate)
    veh_rows = conn.execute(
        "SELECT id, registration_number, model, vehicle_type FROM domain_vehicles WHERE organization_id = ? OR ? = 'org_default'",
        (tenant_id, tenant_id),
    ).fetchall()
    veh_cache = {}
    for v in veh_rows:
        veh_cache[v["registration_number"].upper()] = v
        veh_cache[clean_reg_number(v["registration_number"])] = v

    # 3. Existing customers / corporates cache
    cust_rows = conn.execute(
        "SELECT id, name FROM domain_customers WHERE organization_id = ? OR ? = 'org_default'",
        (tenant_id, tenant_id),
    ).fetchall()
    cust_cache = {}
    for c in cust_rows:
        cust_cache[c["name"].lower().strip()] = c
        cust_cache[c["id"]] = c

    # 4. Existing drivers cache
    drv_rows = conn.execute(
        "SELECT id, full_name, phone FROM domain_drivers WHERE organization_id = ? OR ? = 'org_default'",
        (tenant_id, tenant_id),
    ).fetchall()
    drv_cache = {}
    for d in drv_rows:
        if d["phone"]:
            drv_cache[re.sub(r"[^0-9]", "", d["phone"])] = d
        if d["full_name"]:
            drv_cache[d["full_name"].lower().strip()] = d

    # 5. Pre-fetch latest completed duties per vehicle for fast O(1) in-memory continuity audit
    latest_veh_duties = conn.execute(
        """
        SELECT vehicle_id, id, practical_end_km, practical_end_time
        FROM domain_duties
        WHERE (organization_id = ? OR ? = 'org_default')
          AND status = 'completed'
          AND practical_end_km IS NOT NULL
        ORDER BY practical_end_time DESC
        """,
        (tenant_id, tenant_id),
    ).fetchall()
    latest_veh_map = {}
    for lvd in latest_veh_duties:
        vid = lvd["vehicle_id"]
        if vid and vid not in latest_veh_map:
            latest_veh_map[vid] = {
                "prev_duty_id": lvd["id"],
                "prev_duty_end_km": float(lvd["practical_end_km"]),
                "prev_duty_end_time": lvd["practical_end_time"],
            }

    staged_items = []
    staging_db_rows = []
    seen_in_batch_tripsheets = set()

    total_valid = 0
    total_warnings = 0
    total_errors = 0
    total_duplicates = 0
    total_receivable_inr = 0.0
    total_payable_inr = 0.0

    for idx, r in enumerate(parsed_rows):
        row_num = idx + 1
        row_id = f"imp_{uuid.uuid4().hex[:10]}"
        messages = []
        status = "VALID"

        ext_sheet = r.get("external_tripsheet_no") or f"TS-{row_num:04d}"
        reg_num = r.get("vehicle_registration")
        corp_name = r.get("corporate_name") or "Corporate Default"

        # Check Duplicate
        if ext_sheet in existing_tripsheets or ext_sheet in seen_in_batch_tripsheets:
            status = "DUPLICATE_TRIPSHEET"
            messages.append(f"Trip sheet #{ext_sheet} already exists in database or batch (Double-billing prevented)")
            total_duplicates += 1
        seen_in_batch_tripsheets.add(ext_sheet)

        # Check Vehicle Reference
        matched_veh = None
        if reg_num:
            matched_veh = veh_cache.get(reg_num.upper()) or veh_cache.get(clean_reg_number(reg_num))
        if not matched_veh and status != "DUPLICATE_TRIPSHEET":
            status = "ERROR_MISSING_REF"
            messages.append(f"Vehicle '{reg_num or 'BLANK'}' not found in registered fleet masters")
            total_errors += 1

        # Check Corporate Reference
        matched_cust = cust_cache.get(corp_name.lower().strip())
        if not matched_cust and cust_cache:
            # Pick first available or fallback
            matched_cust = list(cust_cache.values())[0]

        # Parse Kilometers
        try:
            start_km = float(r.get("practical_start_km") or 1000.0)
            end_km = float(r.get("practical_end_km") or (start_km + 40.0))
            if end_km < start_km:
                status = "ERROR_MISSING_REF"
                messages.append(f"Invalid Odometer: End KM ({end_km}) is less than Start KM ({start_km})")
            billable_km = max(0.0, end_km - start_km)
        except Exception:
            start_km, end_km, billable_km = 1000.0, 1040.0, 40.0

        # Parse Timestamps
        start_time = normalize_indian_timestamp(r.get("practical_start_time"))
        end_time = normalize_indian_timestamp(r.get("practical_end_time"))
        toll_parking = float(r.get("toll_parking_inr") or 0.0)

        # Recalculate Tariffs & Auto-Slab
        pricing = recalculate_practical_tariffs(
            practical_km=billable_km,
            practical_duration_mins=240,
            base_rate_inr=1500.0,
            extra_km_rate_inr=25.0,
            extra_hr_rate_inr=150.0,
            toll_parking_inr=toll_parking,
        )

        computed_client = pricing["final_client_fare_inr"]
        computed_supplier = pricing["final_supplier_payout_inr"]
        slab_name = pricing["slab_label"]

        # Check Manual Billed Amount Variance
        manual_billed = r.get("manual_billed_amount")
        if manual_billed and status not in ("DUPLICATE_TRIPSHEET", "ERROR_MISSING_REF"):
            try:
                m_val = float(manual_billed)
                if abs(m_val - computed_client) > 5.0:
                    status = "WARNING_VARIANCE"
                    messages.append(f"Manual billed amount ₹{m_val:,.2f} differs from calculated tariff ₹{computed_client:,.2f} (Delta: ₹{m_val - computed_client:+,.2f})")
                    total_warnings += 1
            except Exception:
                pass

        # Check Odometer Continuity via in-memory O(1) tracker
        veh_target = matched_veh["id"] if matched_veh else reg_num
        prev_entry = latest_veh_map.get(veh_target)
        if prev_entry:
            prev_end_km = prev_entry["prev_duty_end_km"]
            dead_gap = round(start_km - prev_end_km, 1)
            if start_km < prev_end_km:
                continuity_status = "ROLLBACK_ERROR"
                continuity_msg = f"Start KM ({start_km:,.1f}) is lower than previous trip End KM ({prev_end_km:,.1f})"
            elif dead_gap > 50.0:
                continuity_status = "HIGH_DEAD_MILEAGE_GAP"
                continuity_msg = f"{dead_gap:,.1f} km unaccounted dead-mileage gap since last trip ended"
            else:
                continuity_status = "CONTINUOUS_OK"
                continuity_msg = "Odometer continuity verified"
            prev_duty_id = prev_entry["prev_duty_id"]
        else:
            continuity_status = "FIRST_VEHICLE_TRIP"
            continuity_msg = "First tracked duty for vehicle in system"
            prev_duty_id = None
            prev_end_km = None
            dead_gap = 0.0

        # Update in-memory tracker for subsequent batch rows
        latest_veh_map[veh_target] = {
            "prev_duty_id": f"staged_{row_id}",
            "prev_duty_end_km": end_km,
            "prev_duty_end_time": end_time,
        }
        continuity = {
            "prev_duty_id": prev_duty_id,
            "prev_duty_end_km": prev_end_km,
            "dead_mileage_gap_km": dead_gap,
            "odometer_continuity_status": continuity_status,
            "message": continuity_msg,
        }

        if continuity_status == "ROLLBACK_ERROR":
            if status != "ERROR_MISSING_REF":
                status = "ERROR_MISSING_REF"
                total_errors += 1
            messages.append(f"Odometer Rollback: {continuity_msg}")
        elif continuity_status == "HIGH_DEAD_MILEAGE_GAP":
            if status == "VALID":
                status = "WARNING_VARIANCE"
                total_warnings += 1
            messages.append(f"Dead Mileage Gap: {continuity_msg}")

        if status == "VALID":
            total_valid += 1

        if status in ("VALID", "WARNING_VARIANCE"):
            total_receivable_inr += computed_client
            total_payable_inr += computed_supplier

        norm_payload = {
            "external_tripsheet_no": ext_sheet,
            "trip_date": r.get("trip_date"),
            "vehicle_registration": reg_num,
            "vehicle_id": matched_veh["id"] if matched_veh else None,
            "corporate_name": corp_name,
            "customer_id": matched_cust["id"] if matched_cust else None,
            "passenger_name": r.get("passenger_name") or "Corporate Guest",
            "passenger_phone": r.get("passenger_phone") or "+91 98800 12345",
            "pickup_location": r.get("pickup_location"),
            "drop_location": r.get("drop_location"),
            "duty_type": r.get("duty_type"),
            "driver_name": r.get("driver_name"),
            "driver_phone": r.get("driver_phone"),
            "practical_start_km": start_km,
            "practical_end_km": end_km,
            "practical_billable_km": billable_km,
            "practical_start_time": start_time,
            "practical_end_time": end_time,
            "toll_parking_inr": toll_parking,
            "client_final_price_inr": float(r.get("manual_billed_amount") or r.get("client_final_price_inr") or computed_client),
            "supplier_final_payout_inr": float(r.get("supplier_final_payout_inr") or computed_supplier),
            "remarks": r.get("remarks"),
            "vehicle_category": r.get("vehicle_category") or "Sedan",
            "override_tariff_lock": False,
            "prev_duty_id": continuity.get("prev_duty_id"),
            "prev_duty_end_km": continuity.get("prev_duty_end_km"),
            "dead_mileage_gap_km": continuity.get("dead_mileage_gap_km"),
            "odometer_continuity_status": continuity_status,
            "continuity_message": continuity_msg,
        }

        # Collect staging record for batch executemany
        staging_db_rows.append((
            row_id, batch_id, tenant_id, row_num,
            json.dumps(r), json.dumps(norm_payload),
            status, json.dumps(messages),
            computed_client, computed_supplier, slab_name, now,
        ))

        staged_items.append({
            "id": row_id,
            "row_index": row_num,
            "row_number": row_num,
            "external_tripsheet_no": ext_sheet,
            "vehicle_registration": reg_num,
            "corporate_name": corp_name,
            "passenger_name": norm_payload["passenger_name"],
            "passenger_phone": norm_payload["passenger_phone"],
            "practical_start_km": start_km,
            "practical_end_km": end_km,
            "practical_billable_km": billable_km,
            "practical_start_time": start_time,
            "practical_end_time": end_time,
            "toll_parking_inr": toll_parking,
            "validation_status": status,
            "validation_messages": messages,
            "computed_client_fare_inr": computed_client,
            "computed_supplier_payout_inr": computed_supplier,
            "applied_slab_name": slab_name,
            "override_tariff_lock": False,
            "prev_duty_id": continuity.get("prev_duty_id"),
            "prev_duty_end_km": continuity.get("prev_duty_end_km"),
            "dead_mileage_gap_km": continuity.get("dead_mileage_gap_km"),
            "odometer_continuity_status": continuity_status,
            "continuity_message": continuity_msg,
            "raw_data": r,
        })

    # Vectorized batch insert of all staged rows in chunks
    if staging_db_rows:
        conn.executemany(
            """
            INSERT INTO completed_trip_import_rows (
                id, batch_id, tenant_id, row_number, raw_json, normalized_payload,
                validation_status, validation_messages, computed_client_fare_inr,
                computed_supplier_payout_inr, applied_slab_name, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            staging_db_rows,
        )

    # Store batch header
    conn.execute(
        """
        INSERT INTO completed_trip_import_batches (
            id, tenant_id, uploaded_by, filename, total_rows, valid_rows,
            warning_rows, error_rows, duplicate_rows,
            estimated_total_receivable_inr, estimated_total_payable_inr,
            status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'STAGED_DRY_RUN', ?, ?)
        """,
        (
            batch_id, tenant_id, user_id, filename, len(parsed_rows),
            total_valid, total_warnings, total_errors, total_duplicates,
            round(total_receivable_inr, 2), round(total_payable_inr, 2), now, now,
        ),
    )

    net_margin = round(total_receivable_inr - total_payable_inr, 2)
    margin_pct = round((net_margin / max(1.0, total_receivable_inr)) * 100, 1)

    return {
        "ok": True,
        "batch_id": batch_id,
        "filename": filename,
        "summary": {
            "total_rows": len(parsed_rows),
            "valid_rows": total_valid,
            "warning_rows": total_warnings,
            "error_rows": total_errors,
            "duplicate_rows": total_duplicates,
            "estimated_total_receivable_inr": round(total_receivable_inr, 2),
            "estimated_total_payable_inr": round(total_payable_inr, 2),
            "net_margin_inr": net_margin,
            "margin_pct": margin_pct,
        },
        "staged_rows": staged_items,
    }


def commit_completed_trips_batch(
    conn: sqlite3.Connection,
    user: Dict[str, Any],
    batch_id: str,
    ip: str = "127.0.0.1",
) -> Dict[str, Any]:
    """Step 3: Atomically commits valid and approved warning rows into bookings & duties."""
    tenant_id = user.get("organization_id") or "org_default"
    user_id = user.get("id") or "usr_ops"
    now = now_iso()

    batch = conn.execute(
        "SELECT * FROM completed_trip_import_batches WHERE id = ? AND (tenant_id = ? OR ? = 'org_default')",
        (batch_id, tenant_id, tenant_id),
    ).fetchone()
    if not batch:
        raise DomainError(404, f"Import batch {batch_id} not found", "not_found")

    if batch["status"] == "COMMITTED":
        raise DomainError(409, f"Batch {batch_id} is already committed", "already_committed")

    # Fetch committable rows (VALID and WARNING_VARIANCE)
    rows = conn.execute(
        """
        SELECT * FROM completed_trip_import_rows
        WHERE batch_id = ? AND validation_status IN ('VALID', 'WARNING_VARIANCE')
        ORDER BY row_number ASC
        """,
        (batch_id,),
    ).fetchall()

    if not rows:
        raise DomainError(422, "No valid or approved rows to commit in this batch", "no_committable_rows")

    committed_duties = []
    committed_receivable = 0.0
    committed_payable = 0.0

    # Execute vectorized chunked insertions (chunks of 250 rows)
    CHUNK_SIZE = 250
    has_spl = False
    try:
        cols_spl = {c["name"] for c in conn.execute("PRAGMA table_info(supplier_payable_ledger)").fetchall()}
        has_spl = bool(cols_spl)
    except Exception:
        has_spl = False

    for chunk_start in range(0, len(rows), CHUNK_SIZE):
        chunk = rows[chunk_start : chunk_start + CHUNK_SIZE]
        bookings_chunk = []
        duties_chunk = []
        ledger_chunk = []

        for r in chunk:
            payload = json.loads(r["normalized_payload"])
            duty_id = f"duty_{uuid.uuid4().hex[:10]}"
            booking_id = f"bk_{uuid.uuid4().hex[:10]}"
            ref = payload.get("external_tripsheet_no") or f"BK-IMP-{r['row_number']}"

            bookings_chunk.append((
                booking_id, tenant_id, payload.get("customer_id"), ref,
                payload.get("passenger_name", "Corporate Guest"), payload.get("passenger_phone", ""),
                payload.get("practical_start_time"), payload.get("vehicle_category", "Sedan"),
                payload.get("practical_billable_km"), r["computed_client_fare_inr"], r["computed_supplier_payout_inr"],
                now, now,
            ))

            duties_chunk.append((
                duty_id, tenant_id, booking_id, payload.get("vehicle_id"),
                payload.get("practical_start_time"), payload.get("practical_start_time"), payload.get("practical_end_time"),
                int(payload.get("practical_start_km")), int(payload.get("practical_end_km")),
                payload.get("practical_start_km"), payload.get("practical_end_km"), payload.get("practical_billable_km"),
                payload.get("practical_start_time"), payload.get("practical_end_time"),
                r["computed_client_fare_inr"], r["computed_supplier_payout_inr"],
                ref, batch_id,
                payload.get("prev_duty_id"), payload.get("prev_duty_end_km"), payload.get("dead_mileage_gap_km"),
                payload.get("odometer_continuity_status", "FIRST_VEHICLE_TRIP"), payload.get("continuity_message"),
                now, now,
            ))

            if has_spl:
                payout_paise = int(round(r["computed_supplier_payout_inr"] * 100))
                ledger_chunk.append((f"spl_{duty_id}", duty_id, tenant_id, payout_paise, now, now, now))

            committed_duties.append(duty_id)
            committed_receivable += r["computed_client_fare_inr"]
            committed_payable += r["computed_supplier_payout_inr"]

        conn.executemany(
            """
            INSERT INTO domain_bookings (
                id, organization_id, customer_id, booking_reference, status,
                passenger_name, passenger_phone, scheduled_at, vehicle_category,
                estimated_distance_km, estimated_client_fare_inr, estimated_supplier_payout_inr,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            bookings_chunk,
        )

        conn.executemany(
            """
            INSERT INTO domain_duties (
                id, organization_id, booking_id, vehicle_id, status, reporting_at,
                started_at, completed_at, start_odometer, end_odometer,
                practical_start_km, practical_end_km, practical_billable_km,
                practical_start_time, practical_end_time,
                final_client_fare_inr, final_supplier_payout_inr,
                closing_source, external_tripsheet_no, import_batch_id,
                prev_duty_id, prev_duty_end_km, dead_mileage_gap_km, odometer_continuity_status, continuity_message,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'BULK_COMPLETED_IMPORT', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            duties_chunk,
        )

        if ledger_chunk:
            try:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO supplier_payable_ledger (
                        id, duty_id, vendor_id, amount_paise, status, audit_passed_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'FUNDS_HELD_BY_AXIOM', ?, ?, ?)
                    """,
                    ledger_chunk,
                )
            except Exception:
                pass

    # Mark batch committed
    conn.execute(
        """
        UPDATE completed_trip_import_batches
        SET status = 'COMMITTED', updated_at = ?
        WHERE id = ?
        """,
        (now, batch_id),
    )

    _audit(
        conn,
        user,
        "import.completed_trips_committed",
        "import_batch",
        batch_id,
        ip,
        {"duties_count": len(committed_duties), "receivable_inr": committed_receivable},
    )

    return {
        "ok": True,
        "batch_id": batch_id,
        "status": "COMMITTED",
        "committed_duties_count": len(committed_duties),
        "committed_duties": committed_duties,
        "committed_total_receivable_inr": round(committed_receivable, 2),
        "committed_total_payable_inr": round(committed_payable, 2),
        "net_margin_inr": round(committed_receivable - committed_payable, 2),
    }


def update_staged_trip_row(
    conn: sqlite3.Connection,
    user: Dict[str, Any],
    row_id: str,
    payload: Dict[str, Any],
    ip: str = "127.0.0.1",
) -> Dict[str, Any]:
    """Pre-commit correction of trip details in staging table with tariff recalculation vs manual price override lock."""
    tenant_id = user.get("organization_id") or "org_default"
    now = now_iso()

    row = conn.execute(
        "SELECT * FROM completed_trip_import_rows WHERE id = ? AND (tenant_id = ? OR ? = 'org_default')",
        (row_id, tenant_id, tenant_id),
    ).fetchone()
    if not row:
        raise DomainError(404, f"Staged import row '{row_id}' not found", "not_found")

    batch_id = row["batch_id"]
    batch = conn.execute(
        "SELECT * FROM completed_trip_import_batches WHERE id = ?",
        (batch_id,),
    ).fetchone()
    if not batch:
        raise DomainError(404, f"Import batch '{batch_id}' not found", "not_found")
    if batch["status"] == "COMMITTED":
        raise DomainError(409, "Cannot edit rows in an already committed batch", "batch_already_committed")

    curr_payload = json.loads(row["normalized_payload"]) if row["normalized_payload"] else {}
    raw_data = json.loads(row["raw_json"]) if row["raw_json"] else {}

    # Extract updated fields
    ext_sheet = payload.get("external_tripsheet_no") or curr_payload.get("external_tripsheet_no") or f"TS-{row['row_number']:04d}"
    reg_num = payload.get("vehicle_registration") if "vehicle_registration" in payload else (payload.get("cab_no") if "cab_no" in payload else curr_payload.get("vehicle_registration"))
    corp_name = payload.get("corporate_name") if "corporate_name" in payload else (payload.get("corporate") if "corporate" in payload else curr_payload.get("corporate_name", "Corporate Default"))
    passenger_name = payload.get("passenger_name") or curr_payload.get("passenger_name", "Corporate Guest")
    passenger_phone = payload.get("passenger_phone") or curr_payload.get("passenger_phone", "+91 98800 12345")
    driver_name = payload.get("driver_name") or curr_payload.get("driver_name")
    driver_phone = payload.get("driver_phone") or curr_payload.get("driver_phone")

    try:
        start_km = float(payload["practical_start_km"]) if "practical_start_km" in payload else float(curr_payload.get("practical_start_km", 1000.0))
    except Exception:
        start_km = float(curr_payload.get("practical_start_km", 1000.0))

    try:
        end_km = float(payload["practical_end_km"]) if "practical_end_km" in payload else float(curr_payload.get("practical_end_km", start_km + 40.0))
    except Exception:
        end_km = float(curr_payload.get("practical_end_km", start_km + 40.0))

    start_time = normalize_indian_timestamp(payload.get("practical_start_time") or payload.get("start_time") or curr_payload.get("practical_start_time"))
    end_time = normalize_indian_timestamp(payload.get("practical_end_time") or payload.get("end_time") or curr_payload.get("practical_end_time"))

    try:
        toll_parking = float(payload["toll_parking_inr"]) if "toll_parking_inr" in payload else float(curr_payload.get("toll_parking_inr", 0.0))
    except Exception:
        toll_parking = float(curr_payload.get("toll_parking_inr", 0.0))

    override_lock = bool(payload.get("override_tariff_lock", curr_payload.get("override_tariff_lock", False)))

    messages = []
    status = "VALID"

    # 1. Check duplicate external tripsheet against already committed duties
    existing_duty = conn.execute(
        "SELECT id FROM domain_duties WHERE organization_id = ? AND external_tripsheet_no = ?",
        (tenant_id, ext_sheet),
    ).fetchone()
    if existing_duty:
        status = "DUPLICATE_TRIPSHEET"
        messages.append(f"Trip sheet #{ext_sheet} already exists in database (Double-billing prevented)")

    # 2. Check Vehicle Reference
    matched_veh = None
    if reg_num:
        clean_reg = clean_reg_number(reg_num)
        veh_row = conn.execute(
            "SELECT id, registration_number, model, vehicle_type FROM domain_vehicles WHERE (organization_id = ? OR ? = 'org_default') AND (UPPER(registration_number) = ? OR UPPER(REPLACE(REPLACE(registration_number, '-', ''), ' ', '')) = ?)",
            (tenant_id, tenant_id, reg_num.upper(), clean_reg),
        ).fetchone()
        if veh_row:
            matched_veh = dict(veh_row)
    if not matched_veh and status != "DUPLICATE_TRIPSHEET":
        status = "ERROR_MISSING_REF"
        messages.append(f"Vehicle '{reg_num or 'BLANK'}' not found in registered fleet masters")

    # 3. Check Corporate Reference
    matched_cust = None
    if corp_name:
        cust_row = conn.execute(
            "SELECT id, name FROM domain_customers WHERE (organization_id = ? OR ? = 'org_default') AND LOWER(TRIM(name)) = ?",
            (tenant_id, tenant_id, corp_name.lower().strip()),
        ).fetchone()
        if cust_row:
            matched_cust = dict(cust_row)
        else:
            first_cust = conn.execute("SELECT id, name FROM domain_customers WHERE organization_id = ? OR ? = 'org_default' LIMIT 1", (tenant_id, tenant_id)).fetchone()
            if first_cust:
                matched_cust = dict(first_cust)

    # 4. Check Odometer Consistency
    if end_km < start_km:
        status = "ERROR_MISSING_REF"
        messages.append(f"Invalid Odometer: End KM ({end_km}) is less than Start KM ({start_km})")
    billable_km = max(0.0, end_km - start_km)

    # Check Odometer Continuity
    from backend_odometer_and_adjustment import audit_vehicle_odometer_continuity
    veh_target = matched_veh["id"] if matched_veh else reg_num
    continuity = audit_vehicle_odometer_continuity(conn, tenant_id, veh_target, start_km, start_time)
    continuity_status = continuity.get("odometer_continuity_status", "FIRST_VEHICLE_TRIP")
    continuity_msg = continuity.get("message", "")

    if continuity_status == "ROLLBACK_ERROR":
        if status not in ("DUPLICATE_TRIPSHEET", "ERROR_MISSING_REF"):
            status = "ERROR_MISSING_REF"
        messages.append(f"Odometer Rollback: {continuity_msg}")
    elif continuity_status == "HIGH_DEAD_MILEAGE_GAP":
        if status == "VALID":
            status = "WARNING_VARIANCE"
        messages.append(f"Dead Mileage Gap: {continuity_msg}")

    # Duration calculation
    try:
        dt_start = dt.datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        dt_end = dt.datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        duration_mins = max(30, int((dt_end - dt_start).total_seconds() / 60))
    except Exception:
        duration_mins = 240

    # 5. Pricing & Auto-Tariff vs Override Lock
    if override_lock:
        try:
            computed_client = float(payload.get("client_final_price_inr", payload.get("manual_billed_amount", curr_payload.get("client_final_price_inr", row["computed_client_fare_inr"]))))
        except Exception:
            computed_client = float(row["computed_client_fare_inr"])
        try:
            computed_supplier = float(payload.get("supplier_final_payout_inr", curr_payload.get("supplier_final_payout_inr", row["computed_supplier_payout_inr"])))
        except Exception:
            computed_supplier = float(row["computed_supplier_payout_inr"])
        slab_name = "MANUAL_PRICE_OVERRIDE_LOCKED"
    else:
        pricing = recalculate_practical_tariffs(
            practical_km=billable_km,
            practical_duration_mins=duration_mins,
            base_rate_inr=1500.0,
            extra_km_rate_inr=25.0,
            extra_hr_rate_inr=150.0,
            toll_parking_inr=toll_parking,
        )
        computed_client = pricing["final_client_fare_inr"]
        computed_supplier = pricing["final_supplier_payout_inr"]
        slab_name = pricing["slab_label"]

        # Check Manual Billed Amount Variance
        manual_billed = payload.get("client_final_price_inr") or payload.get("manual_billed_amount") or curr_payload.get("client_final_price_inr")
        if manual_billed is not None and status not in ("DUPLICATE_TRIPSHEET", "ERROR_MISSING_REF"):
            try:
                m_val = float(manual_billed)
                if abs(m_val - computed_client) > 5.0:
                    status = "WARNING_VARIANCE"
                    messages.append(f"Manual billed amount ₹{m_val:,.2f} differs from calculated tariff ₹{computed_client:,.2f} (Delta: ₹{m_val - computed_client:+,.2f})")
            except Exception:
                pass

    updated_norm_payload = {
        **curr_payload,
        "external_tripsheet_no": ext_sheet,
        "vehicle_registration": reg_num,
        "vehicle_id": matched_veh["id"] if matched_veh else None,
        "corporate_name": corp_name,
        "customer_id": matched_cust["id"] if matched_cust else None,
        "passenger_name": passenger_name,
        "passenger_phone": passenger_phone,
        "driver_name": driver_name,
        "driver_phone": driver_phone,
        "practical_start_km": start_km,
        "practical_end_km": end_km,
        "practical_billable_km": billable_km,
        "practical_start_time": start_time,
        "practical_end_time": end_time,
        "toll_parking_inr": toll_parking,
        "client_final_price_inr": computed_client,
        "supplier_final_payout_inr": computed_supplier,
        "override_tariff_lock": override_lock,
        "prev_duty_id": continuity.get("prev_duty_id"),
        "prev_duty_end_km": continuity.get("prev_duty_end_km"),
        "dead_mileage_gap_km": continuity.get("dead_mileage_gap_km"),
        "odometer_continuity_status": continuity_status,
        "continuity_message": continuity_msg,
    }

    # Update raw_data for UI backward-compatibility
    raw_data["Cab No"] = reg_num
    raw_data["Corporate"] = corp_name
    raw_data["Start KM"] = start_km
    raw_data["End KM"] = end_km
    raw_data["Toll/Parking"] = toll_parking
    raw_data["Billed Amount"] = computed_client

    conn.execute(
        """
        UPDATE completed_trip_import_rows
        SET raw_json = ?,
            normalized_payload = ?,
            validation_status = ?,
            validation_messages = ?,
            computed_client_fare_inr = ?,
            computed_supplier_payout_inr = ?,
            applied_slab_name = ?
        WHERE id = ?
        """,
        (
            json.dumps(raw_data),
            json.dumps(updated_norm_payload),
            status,
            json.dumps(messages),
            computed_client,
            computed_supplier,
            slab_name,
            row_id,
        ),
    )

    try:
        cols_rows = {c["name"] for c in conn.execute("PRAGMA table_info(completed_trip_import_rows)").fetchall()}
        if "odometer_continuity_status" in cols_rows:
            conn.execute(
                """
                UPDATE completed_trip_import_rows
                SET prev_duty_id = ?, prev_duty_end_km = ?, dead_mileage_gap_km = ?, odometer_continuity_status = ?, continuity_message = ?
                WHERE id = ?
                """,
                (continuity.get("prev_duty_id"), continuity.get("prev_duty_end_km"), continuity.get("dead_mileage_gap_km"), continuity_status, continuity_msg, row_id)
            )
    except Exception:
        pass

    # Re-calculate batch summary KPIs
    batch_rows = conn.execute(
        "SELECT validation_status, computed_client_fare_inr, computed_supplier_payout_inr FROM completed_trip_import_rows WHERE batch_id = ?",
        (batch_id,),
    ).fetchall()

    v_count = sum(1 for r in batch_rows if r["validation_status"] == "VALID")
    w_count = sum(1 for r in batch_rows if r["validation_status"] == "WARNING_VARIANCE")
    e_count = sum(1 for r in batch_rows if r["validation_status"] == "ERROR_MISSING_REF")
    d_count = sum(1 for r in batch_rows if r["validation_status"] == "DUPLICATE_TRIPSHEET")
    rec_sum = sum(r["computed_client_fare_inr"] for r in batch_rows if r["validation_status"] in ("VALID", "WARNING_VARIANCE"))
    pay_sum = sum(r["computed_supplier_payout_inr"] for r in batch_rows if r["validation_status"] in ("VALID", "WARNING_VARIANCE"))

    conn.execute(
        """
        UPDATE completed_trip_import_batches
        SET valid_rows = ?,
            warning_rows = ?,
            error_rows = ?,
            duplicate_rows = ?,
            estimated_total_receivable_inr = ?,
            estimated_total_payable_inr = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (v_count, w_count, e_count, d_count, round(rec_sum, 2), round(pay_sum, 2), now, batch_id),
    )

    net_margin = round(rec_sum - pay_sum, 2)
    margin_pct = round((net_margin / max(1.0, rec_sum)) * 100, 1)

    _audit(
        conn,
        user,
        "import.staged_row_corrected",
        "import_row",
        row_id,
        ip,
        {"batch_id": batch_id, "status": status, "computed_client": computed_client, "override_lock": override_lock},
    )

    return {
        "ok": True,
        "row": {
            "id": row_id,
            "row_index": row["row_number"],
            "row_number": row["row_number"],
            "external_tripsheet_no": ext_sheet,
            "vehicle_registration": reg_num,
            "corporate_name": corp_name,
            "passenger_name": passenger_name,
            "practical_start_km": start_km,
            "practical_end_km": end_km,
            "practical_billable_km": billable_km,
            "practical_start_time": start_time,
            "practical_end_time": end_time,
            "toll_parking_inr": toll_parking,
            "validation_status": status,
            "validation_messages": messages,
            "computed_client_fare_inr": computed_client,
            "computed_supplier_payout_inr": computed_supplier,
            "applied_slab_name": slab_name,
            "override_tariff_lock": override_lock,
            "odometer_continuity_status": continuity_status,
            "continuity_message": continuity_msg,
            "prev_duty_end_km": continuity.get("prev_duty_end_km"),
            "dead_mileage_gap_km": continuity.get("dead_mileage_gap_km"),
            "raw_data": raw_data,
        },
        "batch_summary": {
            "total_rows": len(batch_rows),
            "valid_rows": v_count,
            "warning_rows": w_count,
            "error_rows": e_count,
            "duplicate_rows": d_count,
            "estimated_total_receivable_inr": round(rec_sum, 2),
            "estimated_total_payable_inr": round(pay_sum, 2),
            "net_margin_inr": net_margin,
            "margin_pct": margin_pct,
        },
    }


def correct_duty_trip_details(
    conn: sqlite3.Connection,
    user: Dict[str, Any],
    duty_id: str,
    payload: Dict[str, Any],
    ip: str = "127.0.0.1",
) -> Dict[str, Any]:
    """Interactive post-commit trip details & pricing correction workbench for completed duties."""
    tenant_id = user.get("organization_id") or "org_default"
    now = now_iso()

    duty = conn.execute(
        "SELECT * FROM domain_duties WHERE id = ? AND (organization_id = ? OR ? = 'org_default')",
        (duty_id, tenant_id, tenant_id),
    ).fetchone()
    if not duty:
        raise DomainError(404, f"Duty '{duty_id}' not found", "not_found")

    # Start / End KM
    try:
        start_km = float(payload["practical_start_km"]) if "practical_start_km" in payload else float(duty["practical_start_km"] or duty["start_odometer"] or 0.0)
    except Exception:
        start_km = float(duty["practical_start_km"] or duty["start_odometer"] or 0.0)

    try:
        end_km = float(payload["practical_end_km"]) if "practical_end_km" in payload else float(duty["practical_end_km"] or duty["end_odometer"] or (start_km + 40.0))
    except Exception:
        end_km = float(duty["practical_end_km"] or duty["end_odometer"] or (start_km + 40.0))

    if end_km < start_km:
        raise DomainError(400, f"End odometer ({end_km}) cannot be less than start odometer ({start_km})", "invalid_odometer")
    billable_km = max(0.0, end_km - start_km)


    # Timestamps
    start_time = normalize_indian_timestamp(payload.get("practical_start_time") or payload.get("start_time") or duty["practical_start_time"] or duty["started_at"])
    end_time = normalize_indian_timestamp(payload.get("practical_end_time") or payload.get("end_time") or duty["practical_end_time"] or duty["completed_at"])

    try:
        dt_start = dt.datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        dt_end = dt.datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        duration_mins = max(30, int((dt_end - dt_start).total_seconds() / 60))
    except Exception:
        duration_mins = 240

    try:
        toll_parking = float(payload["toll_parking_inr"]) if "toll_parking_inr" in payload else float(duty["toll_parking_inr"] or 0.0)
    except Exception:
        toll_parking = 0.0

    override_lock = bool(payload.get("override_tariff_lock", False))
    remarks = str(payload.get("remarks") or payload.get("correction_reason") or "Operator correction via workbench")

    # Resolve Vehicle & Driver
    vehicle_id = payload.get("vehicle_id")
    reg_num = payload.get("vehicle_registration") or payload.get("cab_no")
    if reg_num and not vehicle_id:
        clean_reg = clean_reg_number(reg_num)
        veh = conn.execute(
            "SELECT id FROM domain_vehicles WHERE (organization_id = ? OR ? = 'org_default') AND (UPPER(registration_number) = ? OR UPPER(REPLACE(REPLACE(registration_number, '-', ''), ' ', '')) = ?)",
            (tenant_id, tenant_id, reg_num.upper(), clean_reg),
        ).fetchone()
        if veh:
            vehicle_id = veh["id"]

    driver_id = payload.get("driver_id")
    driver_name = payload.get("driver_name")
    if driver_name and not driver_id:
        drv = conn.execute(
            "SELECT id FROM domain_drivers WHERE (organization_id = ? OR ? = 'org_default') AND LOWER(TRIM(full_name)) = ?",
            (tenant_id, tenant_id, driver_name.lower().strip()),
        ).fetchone()
        if drv:
            driver_id = drv["id"]

    # Check Odometer Continuity
    from backend_odometer_and_adjustment import audit_vehicle_odometer_continuity
    veh_target = vehicle_id or (duty["vehicle_id"] if "vehicle_id" in duty.keys() else None) or reg_num
    continuity = audit_vehicle_odometer_continuity(conn, tenant_id, veh_target, start_km, start_time, current_duty_id=duty_id)
    continuity_status = continuity.get("odometer_continuity_status", "FIRST_VEHICLE_TRIP")
    continuity_msg = continuity.get("message", "")

    # Pricing: Recalculate vs Lock Manual Override
    if override_lock:
        final_client = float(payload.get("client_final_price_inr", payload.get("final_client_fare_inr", duty["final_client_fare_inr"] or 0.0)))
        final_supplier = float(payload.get("supplier_final_payout_inr", payload.get("final_supplier_payout_inr", duty["final_supplier_payout_inr"] or 0.0)))
        closing_source = "MANUAL_PRICE_OVERRIDE"
        slab_label = "MANUAL_PRICE_OVERRIDE_LOCKED"
    else:
        pricing = recalculate_practical_tariffs(
            practical_km=billable_km,
            practical_duration_mins=duration_mins,
            base_rate_inr=1500.0,
            extra_km_rate_inr=25.0,
            extra_hr_rate_inr=150.0,
            toll_parking_inr=toll_parking,
        )
        final_client = pricing["final_client_fare_inr"]
        final_supplier = pricing["final_supplier_payout_inr"]
        closing_source = "PRACTICAL_TARIFF_RECALCULATED"
        slab_label = pricing["slab_label"]

    # Update domain_duties
    conn.execute(
        """
        UPDATE domain_duties
        SET practical_start_km = ?,
            practical_end_km = ?,
            practical_billable_km = ?,
            start_odometer = ?,
            end_odometer = ?,
            practical_start_time = ?,
            practical_end_time = ?,
            started_at = ?,
            completed_at = ?,
            vehicle_id = COALESCE(?, vehicle_id),
            driver_id = COALESCE(?, driver_id),
            final_client_fare_inr = ?,
            final_supplier_payout_inr = ?,
            closing_source = ?,
            updated_at = ?
        WHERE id = ? AND (organization_id = ? OR ? = 'org_default')
        """,
        (
            start_km,
            end_km,
            billable_km,
            int(start_km),
            int(end_km),
            start_time,
            end_time,
            start_time,
            end_time,
            vehicle_id,
            driver_id,
            final_client,
            final_supplier,
            closing_source,
            now,
            duty_id,
            tenant_id,
            tenant_id,
        ),
    )

    # Synchronize supplier_payable_ledger
    try:
        cols_spl = {c["name"] for c in conn.execute("PRAGMA table_info(supplier_payable_ledger)").fetchall()}
        if cols_spl:
            payout_paise = int(round(final_supplier * 100))
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

    # Synchronize domain_bookings
    booking_id = duty["booking_id"]
    if booking_id:
        conn.execute(
            """
            UPDATE domain_bookings
            SET estimated_distance_km = ?,
                estimated_client_fare_inr = ?,
                estimated_supplier_payout_inr = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (billable_km, final_client, final_supplier, now, booking_id),
        )

    _audit(
        conn,
        user,
        "duty.trip_details_corrected",
        "duty",
        duty_id,
        ip,
        {
            "final_client_fare_inr": final_client,
            "final_supplier_payout_inr": final_supplier,
            "override_tariff_lock": override_lock,
            "billable_km": billable_km,
            "remarks": remarks,
        },
    )

    try:
        cols_duties = {c["name"] for c in conn.execute("PRAGMA table_info(domain_duties)").fetchall()}
        if "odometer_continuity_status" in cols_duties:
            conn.execute(
                """
                UPDATE domain_duties
                SET prev_duty_id = ?, prev_duty_end_km = ?, dead_mileage_gap_km = ?, odometer_continuity_status = ?, continuity_message = ?
                WHERE id = ?
                """,
                (continuity.get("prev_duty_id"), continuity.get("prev_duty_end_km"), continuity.get("dead_mileage_gap_km"), continuity_status, continuity_msg, duty_id)
            )
    except Exception:
        pass

    return {
        "ok": True,
        "duty_id": duty_id,
        "practical_billable_km": billable_km,
        "final_client_fare_inr": final_client,
        "final_supplier_payout_inr": final_supplier,
        "closing_source": closing_source,
        "slab_label": slab_label,
        "override_tariff_lock": override_lock,
        "odometer_continuity_status": continuity_status,
        "continuity_message": continuity_msg,
        "prev_duty_end_km": continuity.get("prev_duty_end_km"),
        "dead_mileage_gap_km": continuity.get("dead_mileage_gap_km"),
        "updated_at": now,
    }


def handle_completed_trips_api(
    conn: sqlite3.Connection,
    user: Dict[str, Any],
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    ip: str = "127.0.0.1",
) -> Optional[Dict[str, Any]]:
    """Master routing dispatcher for Completed Trips Bulk Import & Correction Workbench APIs."""
    payload = payload or {}

    try:
        from backend_odometer_and_adjustment import handle_odometer_and_adjustment_api
        odo_res = handle_odometer_and_adjustment_api(conn, user, method, path, payload, ip)
        if odo_res is not None:
            return odo_res
    except Exception:
        pass
    norm_path = path.replace("/api/v1", "/api")
    clean_path = urlsplit(norm_path).path
    qs = parse_qs(urlsplit(norm_path).query)

    # 1. Sample Template Generator & Downloader: GET /api/imports/completed-trips/sample-template
    if clean_path == "/api/imports/completed-trips/sample-template" and method == "GET":
        fmt = qs.get("format", ["csv"])[0]
        return generate_sample_template(fmt)

    # 2. Stage CSV / Excel Data: POST /api/imports/completed-trips/stage
    if clean_path == "/api/imports/completed-trips/stage" and method == "POST":
        file_content = payload.get("file_content") or payload.get("csv") or ""
        filename = payload.get("filename") or "completed_trips.csv"
        return stage_completed_trips(conn, user, file_content, filename)

    # 3. Commit Staged Batch: POST /api/imports/completed-trips/{batch_id}/commit
    if "/api/imports/completed-trips/" in clean_path and clean_path.endswith("/commit") and method == "POST":
        parts = clean_path.split("/api/imports/completed-trips/")[1].split("/commit")[0]
        batch_id = parts.strip("/")
        return commit_completed_trips_batch(conn, user, batch_id, ip)

    # 4. Correct Staged Row: PATCH / PUT / POST /api/imports/completed-trips/rows/{row_id}
    if "/api/imports/completed-trips/rows/" in clean_path and method in ("PATCH", "PUT", "POST"):
        parts = clean_path.split("/api/imports/completed-trips/rows/")[1]
        row_id = parts.strip("/")
        return update_staged_trip_row(conn, user, row_id, payload, ip)

    # 5. Correct Completed Duty Details: PATCH / POST / PUT /api/duties/{duty_id}/trip-details
    if "/api/duties/" in clean_path and clean_path.endswith("/trip-details") and method in ("PATCH", "POST", "PUT"):
        parts = clean_path.split("/api/duties/")[1].split("/trip-details")[0]
        duty_id = parts.strip("/")
        return correct_duty_trip_details(conn, user, duty_id, payload, ip)

    return None
