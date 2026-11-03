"""Axiom Mobility (Fleetline) - Unstructured Booking AI Parser.

Provides direct access to:
1. Deterministic regex & heuristic WhatsApp/email booking extraction.
2. Relative datetime resolver (e.g. 'tomorrow 6:30 AM', 'tonight 10 PM').
3. Integrated OpenStreetMap geocoding and routing estimate pre-calculation.
4. Corporate rate card matched theoretical fare & payout calculation.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add fleetline-mvp to sys.path
mvp_dir = Path(__file__).resolve().parent.parent / "fleetline-mvp"
if str(mvp_dir) not in sys.path:
    sys.path.insert(0, str(mvp_dir))

from backend_booking_ai_parser import (
    parse_unstructured_booking,
    parse_relative_datetime,
    handle_booking_ai_parser_api,
)

__all__ = [
    "parse_unstructured_booking",
    "parse_relative_datetime",
    "handle_booking_ai_parser_api",
]
