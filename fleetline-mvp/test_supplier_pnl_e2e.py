import urllib.request, json, sys
sys.stdout.reconfigure(encoding='utf-8')

BASE = "http://localhost:4173"
HEADERS = {
    "X-Axiom-User-Email": "reddragon0075@gmail.com",
    "Content-Type": "application/json"
}

def get(path):
    req = urllib.request.Request(f"{BASE}{path}", headers=HEADERS)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())

def patch(path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=HEADERS, method="PATCH")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())

def test_suppliers_list_and_pnl():
    suppliers_data = get("/api/suppliers")
    items = suppliers_data.get("items", [])
    print(f"Total suppliers in DB: {len(items)}")
    assert len(items) > 0, "No suppliers returned"

    for supp in items[:3]:
        sid = supp["id"]
        sname = supp["name"]
        print(f"\nTesting 360 for: {sname} ({sid})")

        profile = get(f"/api/suppliers/{sid}/360")
        assert profile.get("ok") is True, f"Failed for {sid}"
        pnl = profile.get("pnl_summary", {})
        ledger = profile.get("ledger_summary", {})
        duties = profile.get("duties", [])
        vehicles = profile.get("vehicles", [])

        print(f"  Gross GMV: ₹{pnl.get('gross_revenue_paise', 0) / 100:,.2f}")
        print(f"  Supplier Payout: ₹{pnl.get('supplier_payout_paise', 0) / 100:,.2f}")
        print(f"  Net Axiom Margin: ₹{pnl.get('net_profit_paise', 0) / 100:,.2f} ({pnl.get('margin_pct', 0)}%)")
        print(f"  Duties Count: {len(duties)} (Completed: {pnl.get('completed_duties_count', 0)})")
        print(f"  Attached Vehicles: {len(vehicles)}")
        print(f"  Total Billed: ₹{ledger.get('total_billed_paise', 0) / 100:,.2f}")

        assert pnl.get("gross_revenue_paise", 0) >= 0
        assert len(duties) > 0, "Duties list should not be empty"

    # Test settings update
    test_sid = items[0]["id"]
    update_res = patch(f"/api/suppliers/{test_sid}", {
        "settings": {
            "bank_name": "Axis Commercial Bank",
            "settlement_cycle": "Weekly Friday"
        }
    })
    assert update_res.get("ok") is True
    assert update_res.get("supplier", {}).get("settings", {}).get("bank_name") == "Axis Commercial Bank"
    print("\nPATCH settings verified successfully!")

    print("\nALL SUPPLIER P&L PROFILE E2E TESTS PASSED 100%!")

if __name__ == "__main__":
    test_suppliers_list_and_pnl()
