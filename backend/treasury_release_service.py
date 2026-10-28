"""Axiom Mobility - Treasury Fund Release & Hold Service Layer.
Re-exports treasury release logic from fleetline-mvp for direct backend access.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add fleetline-mvp to sys.path if not present
mvp_dir = Path(__file__).resolve().parent.parent / "fleetline-mvp"
if str(mvp_dir) not in sys.path:
    sys.path.insert(0, str(mvp_dir))

from backend_treasury_release import (
    can_release_vendor_funds,
    get_platform_settings,
    get_treasury_summary,
    get_vendor_payout_balance,
    handle_treasury_release,
    initialize_treasury_release_schema,
    record_duty_completion_payable,
    release_batch,
    toggle_global_hold,
    toggle_vendor_hold,
)

__all__ = [
    "initialize_treasury_release_schema",
    "get_platform_settings",
    "record_duty_completion_payable",
    "can_release_vendor_funds",
    "toggle_global_hold",
    "toggle_vendor_hold",
    "release_batch",
    "get_treasury_summary",
    "get_vendor_payout_balance",
    "handle_treasury_release",
]
