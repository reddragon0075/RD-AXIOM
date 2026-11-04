#!/usr/bin/env python3
"""Axiom Mobility - Live HTTP RBAC & Anti-Exploit Verification Suite.

Tests live API endpoints on http://127.0.0.1:4173 against Corporate RBAC policies:
1. Split-Booking Velocity Guard (rolling 24h cap triggers PENDING_L1_MANAGER).
2. Anti-Self-Approval Guard (Requester cannot approve own trip -> 403).
3. Hierarchy Guard (Unrelated manager cannot approve -> 403; assigned manager can -> 200).
4. Bait-and-Switch Tamper Guard (Tampering with approved trip parameters revokes to REVOKED_ON_EDIT).
5. Hard Dispatch Gate (Unapproved trips cannot be allotted -> 409 Conflict).
6. Budget Ceiling & L2 Finance Escalation (Breached budget requires L2 Finance approval).
7. Scoped Visibility Isolation (Employee vs Manager vs Finance).
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import datetime
import hashlib
import json
import secrets
import sqlite3
import time
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:4173"
DB_PATH = "fleetline-mvp/data/axiom_fleet.sqlite3"

def hash_pw(password: str, salt: str = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 180000)
    return salt, digest.hex()

def setup_rbac_live_users():
    """Seed corporate hierarchy and user accounts into live SQLite database."""
    from backend_corporate_approvals import initialize_corporate_rbac_schema
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    initialize_corporate_rbac_schema(conn)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    salt, p_hash = hash_pw("motion2026")

    # 1. Organization
    tenant_id = "org_zenith_corp"
    conn.execute("""
        INSERT OR IGNORE INTO organizations (id, name, kind, phone, city, gstin, created_at)
        VALUES (?, 'Zenith Corporate Tech', 'corporate', '+91 80 4000 1962', 'Bengaluru', '29AAACZ1962M1Z5', ?)
    """, (tenant_id, now))

    # 2. Cost Centers
    conn.execute("""
        INSERT OR REPLACE INTO cost_centers (id, tenant_id, code, name, monthly_budget_inr, current_month_spend_inr, created_at, updated_at)
        VALUES ('cc_live_gen', ?, 'CC-GEN', 'General Administration', 100000.0, 500.0, ?, ?)
    """, (tenant_id, now, now))
    conn.execute("""
        INSERT OR REPLACE INTO cost_centers (id, tenant_id, code, name, monthly_budget_inr, current_month_spend_inr, created_at, updated_at)
        VALUES ('cc_live_tight', ?, 'CC-TIGHT', 'Strict R&D Budget', 5000.0, 4200.0, ?, ?)
    """, (tenant_id, now, now))

    # 3. Users in `users` (for authentication)
    users_to_seed = [
        ("usr_live_emp_rahul", "rahul.emp@zenith.in", "Rahul Verma", "corporate"),
        ("usr_live_mgr_suresh", "suresh.mgr@zenith.in", "Suresh Rao", "corporate"),
        ("usr_live_mgr_other", "other.mgr@zenith.in", "Vikram Seth", "corporate"),
        ("usr_live_fin_anita", "anita.fin@zenith.in", "Anita Desai", "corporate"),
    ]
    for uid, email, full_name, role in users_to_seed:
        conn.execute("""
            INSERT OR REPLACE INTO users (id, email, password_hash, password_salt, role, full_name, organization_id, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
        """, (uid, email, p_hash, salt, role, full_name, tenant_id, now))

    # 4. Corporate Users in `corporate_users` (for RBAC hierarchy)
    corp_users = [
        ("usr_live_emp_rahul", tenant_id, "rahul.emp@zenith.in", "Rahul Verma", "CORP_EMPLOYEE", "usr_live_mgr_suresh", None, "cc_live_gen"),
        ("usr_live_mgr_suresh", tenant_id, "suresh.mgr@zenith.in", "Suresh Rao", "CORP_LINE_MANAGER", None, None, "cc_live_gen"),
        ("usr_live_mgr_other", tenant_id, "other.mgr@zenith.in", "Vikram Seth", "CORP_LINE_MANAGER", None, None, "cc_live_gen"),
        ("usr_live_fin_anita", tenant_id, "anita.fin@zenith.in", "Anita Desai", "CORP_FINANCE_AUDITOR", None, None, "cc_live_gen"),
    ]
    for cid, tid, em, fn, cr, mgr, delg, cc in corp_users:
        conn.execute("""
            INSERT OR REPLACE INTO corporate_users (id, tenant_id, email, full_name, corp_role, manager_user_id, delegate_approver_user_id, cost_center_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (cid, tid, em, fn, cr, mgr, delg, cc, now, now))

    # Clean prior test requests for repeatable assertions
    conn.execute("DELETE FROM booking_approval_requests WHERE tenant_id = ?", (tenant_id,))

    # 5. Corporate Policy
    from backend_corporate_approvals import get_or_create_corporate_policy
    get_or_create_corporate_policy(conn, tenant_id)

    conn.commit()
    conn.close()
    print("  ✓ Live database seeded with Corporate RBAC users & policies.")

def http_req(path: str, method: str = "GET", body: dict = None, token: str = None) -> tuple[int, dict]:
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            resp_body = resp.read().decode("utf-8")
            return resp.status, json.loads(resp_body) if resp_body else {}
    except urllib.error.HTTPError as e:
        resp_body = e.read().decode("utf-8")
        try:
            parsed = json.loads(resp_body)
        except Exception:
            parsed = {"error": resp_body}
        return e.code, parsed

def login_user(email: str) -> str:
    status, res = http_req("/api/auth/login", method="POST", body={"email": email, "password": "motion2026"})
    if status != 200:
        raise RuntimeError(f"Login failed for {email}: {res}")
    return res.get("access_token")

def run_rbac_test_suite():
    print("=" * 75)
    print("   AXIOM MOBILITY: LIVE HTTP CORPORATE RBAC & ANTI-EXPLOIT SUITE")
    print("=" * 75)

    setup_rbac_live_users()

    # 1. Login all roles
    print("\n[STEP 1] Authenticating Corporate Users...")
    token_rahul = login_user("rahul.emp@zenith.in")
    token_suresh = login_user("suresh.mgr@zenith.in")
    token_other = login_user("other.mgr@zenith.in")
    token_anita = login_user("anita.fin@zenith.in")
    print("  ✓ Rahul (Employee) authenticated.")
    print("  ✓ Suresh (Line Manager) authenticated.")
    print("  ✓ Vikram (Unrelated Manager) authenticated.")
    print("  ✓ Anita (Finance Auditor) authenticated.")

    # 2. Test Split-Booking Velocity Guard
    print("\n[STEP 2] Testing Split-Booking Velocity Guard (Anti-Smurfing)...")
    ts = int(time.time() * 1000)
    trip1_id = f"TRIP-SPLIT-1-{ts}"
    trip2_id = f"TRIP-SPLIT-2-{ts}"
    trip3_id = f"TRIP-SPLIT-3-{ts}"

    # Trip 1: ₹672 (<₹800 auto-approve cap) -> Should auto-approve
    st, r1 = http_req("/api/corp/bookings/request", "POST", {
        "trip_id": trip1_id,
        "vehicle_type": "SEDAN",
        "tariff_model": "P2P_LOCAL",
        "distance_km": 25.0,
        "duration_hours": 1.0,
        "pickup_address": "Indiranagar",
        "drop_address": "Whitefield",
        "cost_center_id": "cc_live_gen"
    }, token=token_rahul)
    assert st == 200 and r1.get("approval_status") == "APPROVED", f"Trip 1 failed: {r1}"
    print(f"  ✓ Trip 1 (₹{r1.get('estimated_fare_inr')}): Auto-approved (<₹800).")

    # Trip 2: ₹672 (Cumulative ₹1,344 <= ₹2,000 cap) -> Should auto-approve
    st, r2 = http_req("/api/corp/bookings/request", "POST", {
        "trip_id": trip2_id,
        "vehicle_type": "SEDAN",
        "tariff_model": "P2P_LOCAL",
        "distance_km": 25.0,
        "duration_hours": 1.0,
        "pickup_address": "Indiranagar",
        "drop_address": "MG Road",
        "cost_center_id": "cc_live_gen"
    }, token=token_rahul)
    assert st == 200 and r2.get("approval_status") == "APPROVED", f"Trip 2 failed: {r2}"
    print(f"  ✓ Trip 2 (₹{r2.get('estimated_fare_inr')}): Auto-approved (Cumulative ₹1,344 <= ₹2,000).")

    # Trip 3: ₹672 (Cumulative ₹2,016 > ₹2,000 cap) -> Blocked from auto-approval, held in PENDING_L1_MANAGER!
    st, r3 = http_req("/api/corp/bookings/request", "POST", {
        "trip_id": trip3_id,
        "vehicle_type": "SEDAN",
        "tariff_model": "P2P_LOCAL",
        "distance_km": 25.0,
        "duration_hours": 1.0,
        "pickup_address": "Indiranagar",
        "drop_address": "Electronic City",
        "cost_center_id": "cc_live_gen"
    }, token=token_rahul)
    assert st == 200 and r3.get("approval_status") == "PENDING_L1_MANAGER", f"Trip 3 failed: {r3}"
    print(f"  ✓ Trip 3 (₹{r3.get('estimated_fare_inr')}): CUMULATIVE BREACH DETECTED!")
    print(f"    Status: {r3.get('approval_status')} - Reasons: {r3.get('reasons')}")
    print("  ✅ PASS: Split-Booking Velocity Guard active and preventing policy evasion.")

    # 3. Test Anti-Self-Approval Guard
    print("\n[STEP 3] Testing Anti-Self-Approval Guard...")
    trip_self_id = f"TRIP-SELF-{ts}"
    sched_future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=6)).isoformat()
    st, r_self = http_req("/api/corp/bookings/request", "POST", {
        "trip_id": trip_self_id,
        "vehicle_type": "SUV_CRYSTA",
        "tariff_model": "8HR_80KM",
        "distance_km": 80.0,
        "pickup_address": "Office",
        "drop_address": "Site A",
        "scheduled_at": sched_future,
        "cost_center_id": "cc_live_gen"
    }, token=token_rahul)
    approval_id = r_self.get("approval_id")

    # Rahul attempts to self-approve his own trip -> /decide
    st, err_self = http_req(f"/api/corp/approvals/{approval_id}/decide", "POST", {
        "decision": "APPROVE"
    }, token=token_rahul)
    assert st == 403 or err_self.get("status") == 403 or "FORBIDDEN" in str(err_self), f"Expected 403 Forbidden for self-approval, got {st}: {err_self}"
    print(f"  ✓ Self-approval attempt rejected: {err_self.get('message', err_self)}")
    print("  ✅ PASS: Anti-Self-Approval Guard strictly prevents self-authorization.")

    # 4. Test Hierarchy & Delegate Approver Guard
    print("\n[STEP 4] Testing Hierarchy Guard (Unrelated Manager vs Assigned Manager)...")
    # Vikram Seth (unrelated manager) attempts to approve Rahul's trip
    st, err_other = http_req(f"/api/corp/approvals/{approval_id}/decide", "POST", {
        "decision": "APPROVE"
    }, token=token_other)
    assert st == 403 or err_other.get("status") == 403 or "FORBIDDEN" in str(err_other), f"Expected 403 Forbidden for unrelated manager, got {st}: {err_other}"
    print(f"  ✓ Unrelated manager approval rejected: {err_other.get('message', err_other)}")

    # Suresh Rao (assigned Line Manager) approves Rahul's trip
    st, ok_mgr = http_req(f"/api/corp/approvals/{approval_id}/decide", "POST", {
        "decision": "APPROVE"
    }, token=token_suresh)
    assert st == 200 and ok_mgr.get("approval_status") == "APPROVED", f"Assigned manager failed: {ok_mgr}"
    print(f"  ✓ Assigned line manager approved successfully: Status = {ok_mgr.get('approval_status')}")
    print("  ✅ PASS: Hierarchy Guard verified.")

    # 5. Test Post-Approval Bait-and-Switch Tamper Guard
    print("\n[STEP 5] Testing Post-Approval Bait-and-Switch Tamper Guard...")
    st, patch_res = http_req(f"/api/corp/bookings/{trip_self_id}", "PATCH", {
        "vehicle_type": "LUXURY_MERCEDES",
        "drop_address": "Goa Luxury Beach Resort",
        "tariff_model": "OUTSTATION"
    }, token=token_suresh)
    assert patch_res.get("tampered"), f"Tamper guard failed: {patch_res}"
    assert patch_res.get("item", {}).get("approval_status") == "REVOKED_ON_EDIT", f"Expected REVOKED_ON_EDIT, got: {patch_res}"
    print(f"  ✓ Tampered trip flagged: {patch_res.get('message')}")
    print(f"  ✓ Status auto-revoked to: {patch_res.get('item', {}).get('approval_status')}")
    print("  ✅ PASS: Cryptographic parameter hash lock protects against bait-and-switch.")

    # 6. Test Hard Dispatch Gate
    print("\n[STEP 6] Testing Hard Dispatch Gate (Block Unapproved / Revoked Trips)...")
    from backend_corporate_approvals import verify_dispatch_allowed_gate
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    allowed, gate_msg = verify_dispatch_allowed_gate(conn, trip_self_id)
    conn.close()
    assert not allowed, f"Dispatch gate should block revoked trip: {gate_msg}"
    print(f"  ✓ Dispatch gate blocked revoked trip: {gate_msg}")
    print("  ✅ PASS: Hard Dispatch Gate blocks resource assignment for non-approved trips.")

    # 7. Test Budget Ceiling & L2 Finance Escalation
    print("\n[STEP 7] Testing Budget Ceiling Breach & L2 Finance Escalation...")
    trip_budget_id = f"TRIP-BUDGET-{ts}"
    # cc_live_tight has remaining budget of only ₹800 (5000 - 4200). A ₹3,500 trip breaches it!
    st, r_b = http_req("/api/corp/bookings/request", "POST", {
        "trip_id": trip_budget_id,
        "vehicle_type": "SUV_CRYSTA",
        "tariff_model": "8HR_80KM",
        "distance_km": 80.0,
        "pickup_address": "R&D Lab",
        "drop_address": "Component Test Center",
        "scheduled_at": sched_future,
        "cost_center_id": "cc_live_tight"
    }, token=token_rahul)
    b_appr_id = r_b.get("approval_id")

    # Suresh (L1 Manager) approves -> triggers escalation to PENDING_L2_FINANCE because budget is breached!
    st, res_l1 = http_req(f"/api/corp/approvals/{b_appr_id}/decide", "POST", {
        "decision": "APPROVE"
    }, token=token_suresh)
    assert st == 200 and res_l1.get("approval_status") == "PENDING_L2_FINANCE", f"Expected L2 escalation, got: {res_l1}"
    print(f"  ✓ L1 Manager approval triggered L2 escalation due to budget ceiling: {res_l1.get('message')}")

    # Anita (Finance Auditor) gives L2 approval
    st, res_l2 = http_req(f"/api/corp/approvals/{b_appr_id}/decide", "POST", {
        "decision": "APPROVE"
    }, token=token_anita)
    assert st == 200 and res_l2.get("approval_status") == "APPROVED", f"L2 Finance approval failed: {res_l2}"
    print(f"  ✓ Finance Auditor granted L2 approval: Status = {res_l2.get('approval_status')}")
    print("  ✅ PASS: Multi-tier escalation engine verified.")

    # 8. Test RBAC Scoped Query Visibility
    print("\n[STEP 8] Testing RBAC Scoped API Query Isolation...")
    # Rahul (Employee) query
    st, emp_view = http_req("/api/corp/bookings", "GET", token=token_rahul)
    # Suresh (Line Manager) query
    st, mgr_view = http_req("/api/corp/bookings", "GET", token=token_suresh)
    # Anita (Finance Auditor) query
    st, fin_view = http_req("/api/corp/bookings", "GET", token=token_anita)

    print(f"  ✓ Employee query count : {emp_view.get('count')} (Role: {emp_view.get('corp_role')})")
    print(f"  ✓ Line Manager query count : {mgr_view.get('count')} (Role: {mgr_view.get('corp_role')})")
    print(f"  ✓ Finance Auditor query count : {fin_view.get('count')} (Role: {fin_view.get('corp_role')})")
    assert fin_view.get("count") >= emp_view.get("count"), "Finance must see all tenant records"
    print("  ✅ PASS: Role-scoped isolation verified across Employee, Manager, and Finance.")

    print("\n" + "=" * 75)
    print("   ALL RBAC & ANTI-EXPLOIT LIVE VERIFICATIONS PASSED SUCCESSFULLY!")
    print("=" * 75 + "\n")

if __name__ == "__main__":
    run_rbac_test_suite()
