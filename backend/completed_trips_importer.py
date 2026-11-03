"""Axiom Mobility (Fleetline) - Completed Trips Bulk Upload & Reconciliation Service Layer.

Provides direct access to:
1. Smart Fuzzy Header & Indian Date/Time Normalizer.
2. In-Memory Batch Entity Resolution (Customers, Vehicles, Drivers).
3. Duplicate Trip-Sheet Prevention Guard.
4. Auto-Tariff & Dual-Ledger Margin Dry Run.
5. Atomic Transaction Commit to Bookings, Duties, and Ledgers.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add fleetline-mvp to sys.path
mvp_dir = Path(__file__).resolve().parent.parent / "fleetline-mvp"
if str(mvp_dir) not in sys.path:
    sys.path.insert(0, str(mvp_dir))

from backend_completed_trips_importer import (
    initialize_bulk_importer_schema,
    HEADER_ALIASES,
    STANDARDIZED_SAMPLE_HEADERS,
    SAMPLE_TEMPLATE_ROWS,
    generate_sample_template,
    clean_reg_number,
    normalize_indian_timestamp,
    match_header,
    parse_csv_or_matrix,
    stage_completed_trips,
    commit_completed_trips_batch,
    update_staged_trip_row,
    correct_duty_trip_details,
    handle_completed_trips_api,
)

__all__ = [
    "initialize_bulk_importer_schema",
    "HEADER_ALIASES",
    "STANDARDIZED_SAMPLE_HEADERS",
    "SAMPLE_TEMPLATE_ROWS",
    "generate_sample_template",
    "clean_reg_number",
    "normalize_indian_timestamp",
    "match_header",
    "parse_csv_or_matrix",
    "stage_completed_trips",
    "commit_completed_trips_batch",
    "update_staged_trip_row",
    "correct_duty_trip_details",
    "handle_completed_trips_api",
]
