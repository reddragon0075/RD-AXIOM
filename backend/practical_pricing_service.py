"""Axiom Mobility (Fleetline) - Practical Pricing & Trip-Sheet Discrepancy Service Layer.

Provides direct access to:
1. Theoretical Baseline vs. Practical Final Fare Engine (Auto-Slab Optimizer & Dual-Ledger).
2. Mandatory Proof Constraint (422 PHYSICAL_TRIPSHEET_PROOF_REQUIRED).
3. Vendor Mobile Pocket App ("On-the-Go Cab Assignment & Daily Pulse").
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add fleetline-mvp to sys.path if not present
mvp_dir = Path(__file__).resolve().parent.parent / "fleetline-mvp"
if str(mvp_dir) not in sys.path:
    sys.path.insert(0, str(mvp_dir))

from backend_practical_pricing import (
    initialize_practical_pricing_schema,
    compute_theoretical_pricing,
    recalculate_practical_tariffs,
    close_duty_practical,
    get_vendor_pocket_pulse,
    get_vendor_pocket_unassigned,
    express_assign_cab,
    handle_practical_pricing_api,
)

__all__ = [
    "initialize_practical_pricing_schema",
    "compute_theoretical_pricing",
    "recalculate_practical_tariffs",
    "close_duty_practical",
    "get_vendor_pocket_pulse",
    "get_vendor_pocket_unassigned",
    "express_assign_cab",
    "handle_practical_pricing_api",
]
