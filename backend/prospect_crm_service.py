"""Axiom Mobility (Fleetline) - Prospect CRM, SaaS Dunning & Corporate Annexure Service.

Provides direct access to:
1. Prospect Capture CRM & 1-Click Tenant Onboarding.
2. Automated SaaS Dunning, Balance Ledger & 3-Stage Access Control.
3. Zero-Login Corporate Proforma Annexure & Trip-Sheet Verification Portal.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add fleetline-mvp to sys.path
mvp_dir = Path(__file__).resolve().parent.parent / "fleetline-mvp"
if str(mvp_dir) not in sys.path:
    sys.path.insert(0, str(mvp_dir))

from backend_prospect_crm import (
    initialize_prospect_crm_schema,
    capture_public_prospect,
    list_prospects,
    add_prospect_note,
    convert_prospect_to_tenant,
    get_tenant_billing_overview,
    create_tenant_platform_invoice,
    update_tenant_access_control,
    generate_proforma_share_link,
    get_corporate_review_data,
    decide_corporate_review,
    handle_prospect_crm_api,
)

__all__ = [
    "initialize_prospect_crm_schema",
    "capture_public_prospect",
    "list_prospects",
    "add_prospect_note",
    "convert_prospect_to_tenant",
    "get_tenant_billing_overview",
    "create_tenant_platform_invoice",
    "update_tenant_access_control",
    "generate_proforma_share_link",
    "get_corporate_review_data",
    "decide_corporate_review",
    "handle_prospect_crm_api",
]
