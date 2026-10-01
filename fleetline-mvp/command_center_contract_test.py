#!/usr/bin/env python3
"""Static local/Supabase/OpenAPI parity guard for the action center."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print("PASS", message)


def main() -> None:
    local = (ROOT / "backend_command_center.py").read_text()
    server = (ROOT / "server.py").read_text()
    migration = (ROOT / "supabase/migrations/20261001010000_workspace_action_center.sql").read_text()
    edge = (ROOT / "supabase/functions/workspace-orchestrator/index.ts").read_text()
    browser = (ROOT / "supabase/client.js").read_text()
    api = yaml.safe_load((ROOT / "openapi.yaml").read_text())

    expect("/api/workspace/next-actions" in api["paths"], "OpenAPI declares the action-center read route")
    expect("/api/workspace/next-actions/{action_id}/status" in api["paths"], "OpenAPI declares per-user action state mutations")
    expect("initialize_command_center_schema" in server and "handle_command_center" in server, "local server initializes and dispatches the action center")
    expect("workspace_action_states" in local and "canonical tenant" in local, "local action center stores per-user state over canonical records")
    expect("operations.action_center" in migration and "workspace_action_states" in migration, "Supabase migration adds the action-center permission and state table")
    expect("enable row level security" in migration and "user_id = auth.uid()" in migration, "Supabase action state is RLS-protected per user and tenant")
    expect("p0_audit_row()" in migration, "Supabase action state uses the append-only audit trigger when available")
    expect("workspace-orchestrator" in browser and "supabaseWorkspaceRequest" in browser, "browser adapter routes action-center calls to the authenticated Edge boundary")
    for marker in ["next-actions", "operations.action_center", "workspace_action_states", "deterministic_exception_projection"]:
        expect(marker in edge, f"Supabase Edge action center includes {marker}")
    expect("blocking" in local and "source" in local and "next_step" in local, "action payloads explain impact, source and recovery")
    expect((ROOT / "command_center_smoke_test.py").exists(), "action-center local regression coverage exists")
    print("RESULT command center contract test passed")


if __name__ == "__main__":
    main()
