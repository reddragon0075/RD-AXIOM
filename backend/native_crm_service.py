"""Axiom Mobility (Fleetline) - Native-Link CRM v2.0 Service Layer.

Provides direct access to:
1. Inbound Prospect Capture & Deterministic Lead Scoring (0-100).
2. Dual-Track Pipeline (Corporate Demand vs Vendor Supply).
3. Spread-Aware 6-Model CPQ Engine via tariff_engine.py.
4. Atomic 1-Click Workspace Provisioner.
5. Customer 360°, Aging Buckets & Treasury Bridge.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add fleetline-mvp to sys.path
mvp_dir = Path(__file__).resolve().parent.parent / "fleetline-mvp"
if str(mvp_dir) not in sys.path:
    sys.path.insert(0, str(mvp_dir))

from backend_native_crm import (
    initialize_native_crm_schema,
    compute_lead_score,
    capture_crm_public_prospect,
    simulate_deal_cpq,
    convert_crm_deal_to_workspace,
    get_crm_account_360,
    get_crm_executive_summary,
    handle_native_crm_api,
)

__all__ = [
    "initialize_native_crm_schema",
    "compute_lead_score",
    "capture_crm_public_prospect",
    "simulate_deal_cpq",
    "convert_crm_deal_to_workspace",
    "get_crm_account_360",
    "get_crm_executive_summary",
    "handle_native_crm_api",
]
