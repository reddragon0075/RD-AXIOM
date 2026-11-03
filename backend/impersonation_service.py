"""Axiom Mobility (Fleetline) - Impersonation Service Layer."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent / "fleetline-mvp"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend_impersonation import (
    SHADOW_SECRET,
    DEFAULT_EXPIRY_SECONDS,
    mint_shadow_jwt,
    verify_shadow_jwt,
    initialize_impersonation_schema,
    check_read_only_mutation_guard,
    handle_impersonation_api,
)

__all__ = [
    "SHADOW_SECRET",
    "DEFAULT_EXPIRY_SECONDS",
    "mint_shadow_jwt",
    "verify_shadow_jwt",
    "initialize_impersonation_schema",
    "check_read_only_mutation_guard",
    "handle_impersonation_api",
]
