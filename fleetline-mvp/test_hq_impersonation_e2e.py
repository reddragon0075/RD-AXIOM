import urllib.request
import urllib.error
import json
import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "http://127.0.0.1:4173"
ADMIN_HEADERS = {
    "Content-Type": "application/json",
    "X-Axiom-User-Email": "reddragon0075@gmail.com",
    "X-Axiom-User": json.dumps({"email": "reddragon0075@gmail.com", "role": "vendor", "id": "usr_abhijith_test"})
}

def run_test(name, fn):
    print(f"\n[RUNNING] {name}...")
    try:
        fn()
        print(f" [PASS] {name}")
        return True
    except Exception as e:
        print(f" [FAIL] {name}: {e}")
        return False

# 1. Test Telemetry APIs
def test_hq_telemetry():
    endpoints = [
        ("/api/axiom-hq/vendors", 3, "items"),
        ("/api/axiom-hq/corporates", 4, "items"),
        ("/api/axiom-hq/plans", 4, "items"),
        ("/api/axiom-hq/invoices", 4, "items"),
        ("/api/axiom-hq/kpis", None, "total_vendors")
    ]
    for ep, expected_min, key in endpoints:
        req = urllib.request.Request(f"{BASE_URL}{ep}", headers=ADMIN_HEADERS)
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200, f"Expected 200 for {ep}, got {resp.status}"
            data = json.loads(resp.read().decode('utf-8'))
            if expected_min is not None:
                items = data.get(key, [])
                assert len(items) >= expected_min, f"Expected at least {expected_min} in {ep}, got {len(items)}"
                print(f"   {ep} returned {len(items)} items OK")
            else:
                assert data.get(key) is not None, f"Missing key {key} in {ep}"
                print(f"   {ep} returned MRR: ₹{data.get('monthly_saas_mrr_inr')}, Vendors: {data.get('total_vendors')} OK")

# 2. Test Vendor Impersonation ("Login As Vendor")
def test_vendor_impersonation():
    payload = {
        "target_type": "vendor",
        "target_id": "ven_metroroyal",
        "reason": "Test diagnostics for Metro Royal Cabs"
    }
    req = urllib.request.Request(
        f"{BASE_URL}/api/axiom-hq/impersonate",
        data=json.dumps(payload).encode('utf-8'),
        headers=ADMIN_HEADERS,
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode('utf-8'))
        assert data.get("ok") is True, "Expected ok: True"
        target_user = data.get("target_user", {})
        assert target_user.get("role") == "vendor", "Expected vendor role"
        assert target_user.get("impersonation_target_name") == "Metro Royal Cabs Pvt Ltd"
        assert target_user.get("is_impersonated") is True
        print(f"   Vendor Shadow Session Created: ID={data.get('session_id')}, User={target_user.get('full_name')}")

    # Verify audit log in SQLite
    conn = sqlite3.connect('fleetline-mvp/data/axiom_fleet.sqlite3')
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM admin_impersonation_audit_logs WHERE target_tenant_name = 'Metro Royal Cabs Pvt Ltd' ORDER BY started_at DESC LIMIT 1").fetchone()
    assert row is not None, "Audit log not found in admin_impersonation_audit_logs"
    assert row["actor_admin_email"] == "reddragon0075@gmail.com"
    print(f"   Audit Log Verified: Log ID={row['id']}, Actor={row['actor_admin_email']}")

# 3. Test Corporate Impersonation ("Login As Corporate")
def test_corporate_impersonation():
    payload = {
        "target_type": "corporate",
        "target_id": "corp_infosys",
        "reason": "Test corporate travel desk"
    }
    req = urllib.request.Request(
        f"{BASE_URL}/api/axiom-hq/impersonate",
        data=json.dumps(payload).encode('utf-8'),
        headers=ADMIN_HEADERS,
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode('utf-8'))
        assert data.get("ok") is True
        target_user = data.get("target_user", {})
        assert target_user.get("role") == "corporate", "Expected corporate role"
        assert target_user.get("corporate_name") == "Infosys BPM Logistics"
        assert target_user.get("portal_subdomain") == "infosys-bpm.axiomfleet.in"
        print(f"   Corporate Shadow Session Created: ID={data.get('session_id')}, Portal={target_user.get('portal_subdomain')}")

    # Verify audit log in SQLite
    conn = sqlite3.connect('fleetline-mvp/data/axiom_fleet.sqlite3')
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM admin_impersonation_audit_logs WHERE target_tenant_name = 'Infosys BPM Logistics' ORDER BY started_at DESC LIMIT 1").fetchone()
    assert row is not None, "Audit log not found for corporate impersonation"
    print(f"   Corporate Audit Log Verified: Log ID={row['id']}, Tenant={row['target_tenant_name']}")

# 4. Test Swift Fleet Impersonation & Operations Access
def test_vendor_operations_access():
    payload = {
        "target_type": "vendor",
        "target_id": "ven_swift",
        "reason": "Test duty slips and bookings"
    }
    req = urllib.request.Request(
        f"{BASE_URL}/api/axiom-hq/impersonate",
        data=json.dumps(payload).encode('utf-8'),
        headers=ADMIN_HEADERS,
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        shadow_user = data["target_user"]

    # Now make an operational request using this shadow user's credentials
    shadow_headers = {
        "X-Axiom-User-Email": shadow_user["email"],
        "X-Axiom-User": json.dumps(shadow_user)
    }
    req_bookings = urllib.request.Request(f"{BASE_URL}/api/bookings", headers=shadow_headers)
    with urllib.request.urlopen(req_bookings) as b_resp:
        assert b_resp.status == 200, f"Expected 200, got {b_resp.status}"
        b_data = json.loads(b_resp.read().decode('utf-8'))
        print(f"   Logged in as {shadow_user['full_name']} -> Successfully accessed /api/bookings (status 200, items={len(b_data.get('items', []))})")

def main():
    print("=" * 60)
    print("AXIOM FLEET HQ & LOGIN-AS (IMPERSONATION) END-TO-END SUITE")
    print("=" * 60)
    results = [
        run_test("HQ Telemetry APIs (Vendors, Corporates, Plans, Invoices, KPIs)", test_hq_telemetry),
        run_test("Login As Vendor (Metro Royal Cabs)", test_vendor_impersonation),
        run_test("Login As Corporate (Infosys BPM)", test_corporate_impersonation),
        run_test("Shadow Identity Operational Access (/api/bookings as Swift Fleet)", test_vendor_operations_access),
    ]
    print("\n" + "=" * 60)
    if all(results):
        print(f"ALL {len(results)} SUITE TESTS PASSED PERFECTLY!")
    else:
        print(f"SOME TESTS FAILED! Passed: {results.count(True)}/{len(results)}")
    print("=" * 60)

if __name__ == "__main__":
    main()
