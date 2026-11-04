"""Axiom Mobility - Corporate Approvals & RBAC Service Layer.
Re-exports corporate approval business logic from fleetline-mvp for cross-module usage.
"""
from __future__ import annotations

import sys
from pathlib import Path

mvp_dir = Path(__file__).resolve().parent.parent / "fleetline-mvp"
if str(mvp_dir) not in sys.path:
    sys.path.insert(0, str(mvp_dir))

from backend_corporate_approvals import (
    ROLES,
    now_utc_iso,
    compute_booking_parameter_hash,
    initialize_corporate_rbac_schema,
    estimate_corporate_fare,
    get_or_create_corporate_policy,
    calculate_rolling_24h_spend,
    submit_corporate_booking_request,
    decide_corporate_approval,
    verify_booking_patch_tamper_guard,
    verify_dispatch_allowed_gate,
)

__all__ = [
    "ROLES",
    "now_utc_iso",
    "compute_booking_parameter_hash",
    "initialize_corporate_rbac_schema",
    "estimate_corporate_fare",
    "get_or_create_corporate_policy",
    "calculate_rolling_24h_spend",
    "submit_corporate_booking_request",
    "decide_corporate_approval",
    "verify_booking_patch_tamper_guard",
    "verify_dispatch_allowed_gate",
]
