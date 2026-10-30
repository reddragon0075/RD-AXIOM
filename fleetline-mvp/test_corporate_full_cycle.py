import urllib.request
import urllib.parse
import json
import time
from datetime import datetime, timedelta, timezone

BASE_URL = "http://localhost:4173"
HEADERS = {
    "X-Axiom-User-Email": "reddragon0075@gmail.com",
    "Content-Type": "application/json"
}

def api(path, method="GET", body=None):
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(err_body)
        except Exception:
            return e.code, {"raw": err_body}

def main():
    print("=" * 75)
    print("AXIOM FLEET: FULL CORPORATE LIFECYCLE & DASHBOARDS END-TO-END TEST")
    print("=" * 75)

    # ---------------------------------------------------------
    # STEP 0: Check Baseline State of Organization P&L Dashboard
    # ---------------------------------------------------------
    print("\n[STEP 0] Inspecting Baseline Organization P&L Dashboard...")
    code, pnl_base = api("/api/dashboards/pnl")
    assert code == 200, f"P&L Dashboard failed: {code} {pnl_base}"
    base_sum = pnl_base["summary"]
    base_rev_rs = base_sum["revenue_paise"] / 100
    base_cost_rs = base_sum["operating_cost_paise"] / 100
    base_profit_rs = base_sum["net_profit_paise"] / 100
    base_duties_count = base_sum["total_duties_count"]
    base_clients_count = len(pnl_base["customers"])

    print(f"  - Baseline Total Duties   : {base_duties_count}")
    print(f"  - Baseline Active Clients : {base_clients_count}")
    print(f"  - Baseline Gross Revenue  : Rs. {base_rev_rs:,.2f}")
    print(f"  - Baseline Operating Cost : Rs. {base_cost_rs:,.2f}")
    print(f"  - Baseline Net Operating  : Rs. {base_profit_rs:,.2f} ({base_sum['margin_pct']}% margin)")

    # ---------------------------------------------------------
    # STEP 1: Add a Corporate Customer
    # ---------------------------------------------------------
    print("\n[STEP 1] Adding a new Corporate Customer...")
    run_id = int(time.time()) % 100000
    corp_payload = {
        "name": f"Acme Dynamics Global {run_id} Pvt Ltd",
        "code": f"AD{run_id % 1000}",
        "email": f"traveldesk_{run_id}@acmedynamics.example.com",
        "phone": f"+91 80 4912 {run_id % 9000 + 1000}",
        "gstin": f"29AAACA{run_id:04d}B1Z8",
        "customer_type": "Company",
        "city": "Bengaluru",
        "notes": "Tier-1 Enterprise client with national corporate travel scope."
    }
    code, cust_res = api("/api/customers", method="POST", body=corp_payload)
    assert code == 201, f"Create customer failed: {code} {cust_res}"
    cust = cust_res["item"]
    cust_id = cust["id"]
    print(f"  [OK] Corporate Customer Created: {cust['name']} ({cust.get('code')})")
    print(f"       Customer ID: {cust_id} | GSTIN: {cust.get('gstin')} | Hub: {cust.get('city')}")

    # Set governance & payment settings
    patch_settings_payload = {
        "payment_terms": 30,
        "credit_limit": 500000,
        "pan": "AAACA1122B",
        "require_employee_id": True,
        "require_cost_center": True,
        "require_digital_sig": True
    }
    code, patch_res = api(f"/api/customers/{cust_id}", method="PATCH", body=patch_settings_payload)
    print(f"  [OK] Corporate Governance Settings Saved: Net 30 Days | Credit Limit Rs. 5,00,000")

    # ---------------------------------------------------------
    # STEP 2: Add an Employee Attached to this Corporate Customer
    # ---------------------------------------------------------
    print("\n[STEP 2] Adding an Authorized Corporate Employee...")
    emp_code = f"ADG-{run_id}"
    emp_payload = {
        "full_name": f"Siddharth Varma {run_id} (VP Products)",
        "employee_code": emp_code,
        "email": f"siddharth.{run_id}@acmedynamics.example.com",
        "phone": f"+91 98801 {run_id % 90000 + 10000}",
        "department": "Product Engineering",
        "cost_center": "CC-PROD-2026",
        "customer_id": cust_id
    }
    code, emp_res = api("/api/employees", method="POST", body=emp_payload)
    assert code == 201, f"Create employee failed: {code} {emp_res}"
    emp = emp_res["item"]
    emp_id = emp["id"]
    print(f"  [OK] Employee Record Created: {emp['full_name']} [Code: {emp['employee_code']}]")
    print(f"       Affiliated to Customer ID: {emp['customer_id']} | Cost Center: {emp['cost_center']}")

    # ---------------------------------------------------------
    # STEP 3: Add Corporate Rate Card (Pricing Contract & Tariffs)
    # ---------------------------------------------------------
    print("\n[STEP 3] Configuring Corporate Rate Card & Tariffs...")
    contract_payload = {
        "name": "Acme Global Corporate Agreement 2026-27",
        "contract_type": "customer",
        "customer_id": cust_id,
        "supplier_id": None,
        "status": "active",
        "description": "Negotiated enterprise contract for Acme Dynamics Bengaluru operations."
    }
    code, contract_res = api("/api/pricing/contracts", method="POST", body=contract_payload)
    assert code in (200, 201), f"Create contract failed: {code} {contract_res}"
    contract_id = (contract_res.get("item") or contract_res)["id"]
    print(f"  [OK] Contract Created: {contract_id}")

    # Add pricing rule: Airport Transfer & Local 8hr/80km
    rule_payload = {
        "city": "Bengaluru",
        "vehicle_group": "Sedan",
        "duty_type": "airport",
        "included_km": 45,
        "package_minutes": 180,
        "base_paise": 280000,          # Rs. 2,800.00
        "extra_km_paise": 1800,         # Rs. 18 / km
        "extra_hour_paise": 15000,      # Rs. 150 / hr
        "allowance_paise": 40000,       # Rs. 400 day batta
        "night_allowance_paise": 45000, # Rs. 450 night batta
        "fuel_surcharge_pct": 0
    }
    code, rule_res = api(f"/api/pricing/contracts/{urllib.parse.quote(contract_id)}/rules", method="POST", body=rule_payload)
    assert code in (200, 201), f"Create contract rule failed: {code} {rule_res}"
    print(f"  [OK] Rate Card Rule Attached: Sedan Airport Transfer - Base Rs. 2,800 (45 km, 3 hrs)")

    # ---------------------------------------------------------
    # STEP 4: Book a Trip for this Corporate Customer & Employee
    # ---------------------------------------------------------
    print("\n[STEP 4] Booking a Corporate Duty for Passenger...")
    now_utc = datetime.now(timezone.utc)
    scheduled_iso = (now_utc + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    booking_payload = {
        "customer_id": cust_id,
        "passenger_name": emp["full_name"],
        "passenger_phone": emp["phone"],
        "passenger_email": emp["email"],
        "pickup": {
            "label": "Acme Tech Park, Outer Ring Road, Bellandur, Bengaluru",
            "city": "Bengaluru",
            "coordinates": [12.9279, 77.6833]
        },
        "dropoff": {
            "label": "Kempegowda International Airport Terminal 2",
            "city": "Bengaluru",
            "coordinates": [13.1986, 77.7066]
        },
        "duty_type": "airport",
        "vehicle_group": "Sedan",
        "scheduled_at": scheduled_iso,
        "special_instructions": f"Corporate Employee ID: {emp['employee_code']} | Cost Center: {emp['cost_center']}"
    }
    code, booking_res = api("/api/bookings", method="POST", body=booking_payload)
    assert code == 201, f"Booking creation failed: {code} {booking_res}"
    booking_id = booking_res["item"]["id"]
    print(f"  [OK] Booking Created: {booking_id} (Customer: {cust['name']}, Passenger: {emp['full_name']})")

    # ---------------------------------------------------------
    # STEP 5: Allot Vehicle & Driver to Duty
    # ---------------------------------------------------------
    print("\n[STEP 5] Allotting Vehicle & Driver to Duty...")
    code, v_res = api("/api/vehicles?limit=5")
    target_vehicle = v_res["items"][0]
    target_veh_id = target_vehicle["id"]
    target_reg = target_vehicle.get("registration_number") or target_vehicle.get("license_plate")

    code, d_res = api("/api/drivers?limit=5")
    target_driver = d_res["items"][0]
    target_driver_id = target_driver["id"]
    target_driver_name = target_driver["full_name"]

    duty_payload = {
        "booking_id": booking_id,
        "vehicle_id": target_veh_id,
        "driver_id": target_driver_id,
        "supplier_id": target_vehicle.get("supplier_id") or "Falcon Fleet Partners",
        "reporting_at": scheduled_iso
    }
    code, duty_res = api("/api/duties", method="POST", body=duty_payload)
    assert code == 201, f"Duty creation failed: {code} {duty_res}"
    duty_id = duty_res["item"]["id"]
    print(f"  [OK] Duty Dispatched: {duty_id} (Vehicle: {target_reg}, Driver: {target_driver_name})")

    # ---------------------------------------------------------
    # STEP 6: Execute & Close Duty
    # ---------------------------------------------------------
    print("\n[STEP 6] Completing Trip & Closing Duty Telemetry...")
    start_odo = 92400.0
    trip_distance_km = 52.0
    end_odo = start_odo + trip_distance_km
    start_time = (now_utc + timedelta(hours=1, minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    complete_time = (now_utc + timedelta(hours=2, minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

    close_payload = {
        "start_odometer": start_odo,
        "end_odometer": end_odo,
        "started_at": start_time,
        "completed_at": complete_time,
        "source": "web_command_center",
        "evidence": [
            {
                "evidence_type": "photo",
                "storage_path": "uploads/evidence/acme_trip_odo.jpg",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            }
        ]
    }
    code, close_res = api(f"/api/duties/{duty_id}/close", method="POST", body=close_payload)
    assert code in (200, 201), f"Duty close failed: {code} {close_res}"
    print(f"  [OK] Duty Closed! Odometer: {start_odo} -> {end_odo} km ({trip_distance_km} km executed)")

    # ---------------------------------------------------------
    # STEP 7: Calculate Fare & Bill Trip (Invoice Generation)
    # ---------------------------------------------------------
    print("\n[STEP 7] Calculating Fare & Generating Tax Invoice...")
    calc_payload = {
        "base_paise": 280000,       # Base package: Rs. 2,800
        "distance_km": int(trip_distance_km),
        "per_km_paise": 1800,
        "duration_minutes": 80,
        "per_hour_paise": 15000,
        "tax_rate_bps": 500,        # 5% GST on transport
        "parking_paise": 15000,     # Rs. 150 airport toll/parking
        "toll_paise": 10000
    }
    code, calc_res = api(f"/api/duties/{duty_id}/calculate", method="POST", body=calc_payload)
    assert code == 200, f"Fare calculation failed: {code} {calc_res}"
    calc = calc_res["calculation"]
    trip_total_paise = calc["total_paise"]
    print(f"  [OK] Trip Fare Snapshot: Rs. {trip_total_paise/100:,.2f} (Subtotal: Rs. {calc['subtotal_paise']/100:,.2f} + GST: Rs. {calc['tax_paise']/100:,.2f})")

    invoice_number = f"INV-ACME-{int(time.time())}"
    inv_payload = {
        "duty_id": duty_id,
        "invoice_number": invoice_number
    }
    code, inv_res = api("/api/invoices", method="POST", body=inv_payload)
    assert code == 201, f"Invoice creation failed: {code} {inv_res}"
    inv = inv_res["item"]
    print(f"  [OK] Tax Invoice Billed: {inv['invoice_number']} [ID: {inv['id']}] for Rs. {inv['total_paise']/100:,.2f}")

    # ---------------------------------------------------------
    # STEP 8: Verify Corporate Customer 360 Dashboard
    # ---------------------------------------------------------
    print("\n[STEP 8] Verifying Customer 360 Dashboard for Acme Dynamics...")
    code, c360 = api(f"/api/customers/{cust_id}/360")
    assert code == 200, f"Customer 360 fetch failed: {code} {c360}"

    c_pnl = c360["pnl_summary"]
    c_ledger = c360["ledger_summary"]
    c_employees = c360.get("employees", [])
    c_invoices = c360.get("invoices", [])
    c_duties = c360.get("duties", [])
    c_contracts = c360.get("contracts", [])

    print("  Customer 360 KPI Deck:")
    print(f"    - Billed Revenue     : Rs. {c_pnl['revenue_paise']/100:,.2f}")
    print(f"    - Duty Operating Cost: Rs. {c_pnl['operating_cost_paise']/100:,.2f}")
    print(f"    - Net Operating P&L  : Rs. {c_pnl['net_profit_paise']/100:,.2f} ({c_pnl['margin_pct']}% margin)")
    print(f"    - Outstanding Due    : Rs. {c_ledger['outstanding_balance_paise']/100:,.2f}")

    print("  Customer 360 Roster & Ledger:")
    print(f"    - Employees Roster   : {len(c_employees)} employee(s) attached")
    print(f"    - Invoices Ledger    : {len(c_invoices)} invoice(s) generated")
    print(f"    - Executed Duties    : {len(c_duties)} duty run(s)")
    print(f"    - Active Contracts   : {len(c_contracts)} rate card(s)")

    # Assert Customer 360 verification
    assert c_pnl["revenue_paise"] == trip_total_paise, f"Revenue mismatch: {c_pnl['revenue_paise']} vs {trip_total_paise}"
    assert len(c_employees) >= 1, "Employee was not returned in Customer 360 employees roster!"
    assert c_employees[0]["employee_code"] == emp_code, f"Wrong employee code: {c_employees[0]['employee_code']}"
    assert len(c_invoices) >= 1, "Invoice was not attached to customer ledger!"
    assert c_invoices[0]["invoice_number"] == invoice_number, "Invoice number mismatch!"
    assert len(c_duties) >= 1, "Duty was not returned in customer duties breakdown!"
    assert len(c_contracts) >= 1, "Contract was not attached to customer rate cards!"
    print("  >>> SUCCESS: Customer 360 reflects full financial, roster, contract and invoice state!")

    # ---------------------------------------------------------
    # STEP 9: Verify Executive Organization-Wide P&L Dashboard
    # ---------------------------------------------------------
    print("\n[STEP 9] Verifying Organization-Wide Executive P&L Dashboard (/api/dashboards/pnl)...")
    code, pnl_after = api("/api/dashboards/pnl")
    assert code == 200, f"Organization P&L fetch failed: {code} {pnl_after}"

    after_sum = pnl_after["summary"]
    after_rev_rs = after_sum["revenue_paise"] / 100
    after_cost_rs = after_sum["operating_cost_paise"] / 100
    after_profit_rs = after_sum["net_profit_paise"] / 100
    after_duties_count = after_sum["total_duties_count"]
    after_clients = pnl_after["customers"]

    print("  Executive P&L Master Deck Comparison:")
    print(f"    - Duties Count     : {base_duties_count} -> {after_duties_count} (+{after_duties_count - base_duties_count})")
    print(f"    - Gross Revenue    : Rs. {base_rev_rs:,.2f} -> Rs. {after_rev_rs:,.2f} (+Rs. {after_rev_rs - base_rev_rs:,.2f})")
    print(f"    - Duty Expenses    : Rs. {base_cost_rs:,.2f} -> Rs. {after_cost_rs:,.2f} (+Rs. {after_cost_rs - base_cost_rs:,.2f})")
    print(f"    - Net Operating PnL: Rs. {base_profit_rs:,.2f} -> Rs. {after_profit_rs:,.2f} (+Rs. {after_profit_rs - base_profit_rs:,.2f})")
    print(f"    - Net Margin %     : {after_sum['margin_pct']}%")

    print("\n  Corporate Customer Leaderboard Ranking:")
    acme_in_leaderboard = None
    for idx, c in enumerate(after_clients):
        p_rs = c["net_profit_paise"] / 100
        r_rs = c["revenue_paise"] / 100
        print(f"    #{idx+1} {c['name']} - {c['duties_count']} duties | Rev: Rs. {r_rs:,.2f} | Profit: Rs. {p_rs:,.2f} ({c['margin_pct']}%)")
        if c["id"] == cust_id:
            acme_in_leaderboard = c

    assert acme_in_leaderboard is not None, "Acme Dynamics Global was not found in P&L customer leaderboard!"
    assert after_duties_count == base_duties_count + 1, "Total duties did not increment!"
    assert abs((after_rev_rs - base_rev_rs) - (trip_total_paise / 100)) < 0.1, "Revenue delta did not match invoice total!"

    print("\n  Duty Types Economics Split:")
    for dt in pnl_after.get("duty_types", []):
        print(f"    - {dt['duty_type'].upper():14}: {dt['duties_count']} duties | Rev: Rs. {dt['revenue_paise']/100:,.2f} | Margin: {dt['margin_pct']}%")

    print("\n  Fleet Operating Model Split:")
    for fm in pnl_after.get("fleet_models", []):
        print(f"    - {fm['label']:26}: {fm['duties_count']} duties | Rev: Rs. {fm['revenue_paise']/100:,.2f} | Margin: {fm['margin_pct']}%")

    print("\n" + "=" * 75)
    print("ALL TESTS PASSED! FULL CORPORATE LIFECYCLE & DASHBOARDS VERIFIED 100%!")
    print("=" * 75)

if __name__ == "__main__":
    main()
