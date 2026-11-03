"""Axiom Mobility (Fleetline) - Root Backend Bridge for Workspace Bootstrap Service."""

from __future__ import annotations

from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parent.parent / "fleetline-mvp"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend_workspace_bootstrap import (
    get_workspace_bootstrap_summary,
    handle_workspace_bootstrap_api,
    initialize_performance_indexes,
)

__all__ = [
    "get_workspace_bootstrap_summary",
    "handle_workspace_bootstrap_api",
    "initialize_performance_indexes",
]
