#!/usr/bin/env python3
"""Axiom Mobility (Fleetline) 10/10 SaaS Console & Impersonation Verification Suite."""

import datetime as dt
import json
import sqlite3
import time

from backend_impersonation import (
    check_read_only_mutation_guard,
    handle_impersonation_api,
    initialize_impersonation_schema,
    mint_shadow_jwt,
    verify_shadow_jwt,
)


def run_tests():
    print("--- 1. CRYPTOGRAPHIC SHADOW JWT TESTS ---")
    token, exp_ts = mint_shadow_jwt(169, "Zion Travels", "usr_admin_1", "usr_vendor_169", "READ_ONLY", 1800)
    assert token and token.count(".") == 2
    print(f"PASS: Minted Shadow JWT token (length={len(token)}, exp={exp_ts})")

    payload = verify_shadow_jwt(token)
    assert payload is not None
    assert payload["tenant_id"] == 169
    assert payload["tenant_name"] == "Zion Travels"
    assert payload["impersonation_mode"] == "READ_ONLY"
    assert payload["actor_admin_id"] == "usr_admin_1"
    print("PASS: Verified Shadow JWT signature & payload claims")

    # Tampered token check
    tampered = token[:-4] + "abcd"
    assert verify_shadow_jwt(tampered) is None
    print("PASS: Tampered token rejected")

    # Expired token check
    exp_token, _ = mint_shadow_jwt(169, "Zion Travels", "usr_admin_1", "usr_vendor_169", "READ_ONLY", -10)
    assert verify_shadow_jwt(exp_token) is None
    print("PASS: Expired shadow token rejected")

    print("\n--- 2. READ-ONLY SHADOW MUTATION GUARDRAIL TESTS ---")
    shadow_ro = {"impersonation_mode": "READ_ONLY", "tenant_id": 169, "actor_admin_id": "usr_admin_1"}
    
    # GET allowed
    assert check_read_only_mutation_guard("GET", "/api/duties", shadow_ro) is None
    # POST blocked
    err = check_read_only_mutation_guard("POST", "/api/duties", shadow_ro)
    assert err is not None and err[0] == 403
    assert err[1]["error"] == "READ_ONLY_SHADOW_MODE"
    print(f"PASS: Read-Only shadow mutation guard blocked POST /api/duties with HTTP 403: {err[1]['error']}")

    # Mode switch allowed
    assert check_read_only_mutation_guard("POST", "/api/v1/admin/impersonate/mode", shadow_ro) is None
    assert check_read_only_mutation_guard("POST", "/api/v1/admin/impersonate/end", shadow_ro) is None
    print("PASS: Session termination & mode routes bypass read-only mutation guard")

    # READ_WRITE mode allows mutations
    shadow_rw = {"impersonation_mode": "READ_WRITE", "tenant_id": 169, "actor_admin_id": "usr_admin_1"}
    assert check_read_only_mutation_guard("POST", "/api/duties", shadow_rw) is None
    print("PASS: READ_WRITE shadow mode permits authorized support mutations")

    print("\n--- 3. MULTI-TENANT SAAS & IMPERSONATION API TESTS ---")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    initialize_impersonation_schema(conn)

    admin_user = {"id": "usr_superadmin_01", "email": "ops-head@axiomfleet.com", "role": "vendor"}

    # GET /api/v1/admin/saas/tenants
    saas_data = handle_impersonation_api(conn, admin_user, "GET", "/api/v1/admin/saas/tenants", {})
    assert saas_data["ok"] is True
    assert saas_data["kpi_strip"]["active_corporates"] == 71
    assert saas_data["kpi_strip"]["mrr_paise"] == 30999700
    assert len(saas_data["tenants"]) >= 5
    print(f"PASS: SaaS Tenants API returned {len(saas_data['tenants'])} tenants and executive KPI strip (MRR INR {saas_data['kpi_strip']['mrr_paise']/100})")

    # POST /api/v1/admin/impersonate (Start 30-min shadow session)
    imp_req = {"tenant_id": 169, "impersonation_mode": "READ_ONLY", "reason_code": "Customer Support Escalation"}
    imp_res = handle_impersonation_api(conn, admin_user, "POST", "/api/v1/admin/impersonate", imp_req)
    assert imp_res["ok"] is True
    assert imp_res["tenant"]["id"] == 169
    assert imp_res["impersonation_mode"] == "READ_ONLY"
    session_id = imp_res["session_id"]
    print(f"PASS: Minted Shadow Session {session_id} for {imp_res['tenant']['name']} with audit log")

    # Verify audit log in DB
    log_cur = conn.execute("SELECT actor_admin_id, target_tenant_id, impersonation_mode, session_status FROM admin_impersonation_audit_logs WHERE id = ?", (session_id,))
    log_row = log_cur.fetchone()
    assert log_row[0] == "usr_superadmin_01"
    assert log_row[1] == 169
    assert log_row[2] == "READ_ONLY"
    assert log_row[3] == "ACTIVE"
    print("PASS: Audit log entry verified in admin_impersonation_audit_logs")

    # Mode switch to READ_WRITE
    mode_res = handle_impersonation_api(conn, admin_user, "POST", "/api/v1/admin/impersonate/mode", {
        "session_id": session_id,
        "impersonation_mode": "READ_WRITE",
        "reason_code": "Emergency Route Adjustment"
    })
    assert mode_res["ok"] is True
    assert mode_res["impersonation_mode"] == "READ_WRITE"
    print("PASS: Mode switched to READ_WRITE with reason code")

    # End session
    end_res = handle_impersonation_api(conn, admin_user, "POST", "/api/v1/admin/impersonate/end", {"session_id": session_id})
    assert end_res["ok"] is True
    log_cur2 = conn.execute("SELECT session_status FROM admin_impersonation_audit_logs WHERE id = ?", (session_id,))
    assert log_cur2.fetchone()[0] == "ENDED_BY_USER"
    print("PASS: Terminated shadow session and marked audit log ENDED_BY_USER")

    # Toggle Feature Flags
    flag_res = handle_impersonation_api(conn, admin_user, "POST", "/api/v1/admin/saas/tenants/169/flags", {"flag_key": "whatsapp_bot", "enabled": True})
    assert flag_res["ok"] is True
    assert flag_res["enabled"] is True
    print("PASS: Feature flag 'whatsapp_bot' enabled for tenant #169")

    # Top Up Wallet
    topup_res = handle_impersonation_api(conn, admin_user, "POST", "/api/v1/admin/saas/tenants/169/topup", {"amount_paise": 50000})
    assert topup_res["ok"] is True
    assert topup_res["new_balance_paise"] == 50500  # 500 + 50000 = 50500 paise (₹505.00)
    print(f"PASS: Top up wallet succeeded: new balance INR {topup_res['new_balance_paise']/100}")

    print("\nALL 10/10 SAAS CONSOLE & IMPERSONATION TESTS PASSED (15/15)")


if __name__ == "__main__":
    run_tests()
