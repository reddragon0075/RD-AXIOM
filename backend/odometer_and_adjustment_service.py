"""Axiom Mobility (Fleetline) - Odometer Continuity & Post-Invoice Adjustment Service Layer.

Provides direct access to:
1. Sequential Vehicle Odometer Continuity Checker (Rollbacks & Dead Mileage gaps).
2. Partial Batch Commit & Error-Row CSV Exporter (21st column axiom_error_explanation).
3. Multi-Row Bulk Correction & Rate-Card Re-evaluation.
4. Post-Invoice Credit Note / Supplementary Debit Note Generator.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add fleetline-mvp to sys.path
mvp_dir = Path(__file__).resolve().parent.parent / "fleetline-mvp"
if str(mvp_dir) not in sys.path:
    sys.path.insert(0, str(mvp_dir))

from backend_odometer_and_adjustment import (
    initialize_odometer_and_adjustment_schema,
    audit_vehicle_odometer_continuity,
    export_batch_errors_csv,
    bulk_correct_duties,
    create_post_invoice_adjustment,
    handle_odometer_and_adjustment_api,
)

__all__ = [
    "initialize_odometer_and_adjustment_schema",
    "audit_vehicle_odometer_continuity",
    "export_batch_errors_csv",
    "bulk_correct_duties",
    "create_post_invoice_adjustment",
    "handle_odometer_and_adjustment_api",
]
