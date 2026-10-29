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
    print("=" * 68)
    print("AXIOM FLEET: E2E TRIP CYCLE, VEHICLE P&L & DRIVER PAYOUT TEST")
    print("=" * 68)

    # 1. Select Target Vehicle, Driver, Customer
    code, v_res = api("/api/vehicles?limit=50")
    vehicles = v_res.get("items", [])
    target_vehicle = next((v for v in vehicles if v.get("registration_number") == "KA 05 SP 2164"), vehicles[0])
    target_veh_id = target_vehicle["id"]
    target_reg = target_vehicle["registration_number"]

    code, d_res = api("/api/drivers?limit=50")
    drivers = d_res.get("items", [])
    target_driver = next((d for d in drivers if "Ramesh" in d.get("full_name", "")), drivers[0])
    target_driver_id = target_driver["id"]
    target_driver_name = target_driver["full_name"]

    code, c_res = api("/api/customers?limit=50")
    customers = c_res.get("items", [])
    target_cust = customers[0]
    target_cust_id = target_cust["id"]
    target_cust_name = target_cust["name"]

    print("\n[SETUP] Test Target Configuration:")
    print(f"  - Vehicle : {target_reg} ({target_vehicle.get('make_model')}) [ID: {target_veh_id}]")
    print(f"  - Driver  : {target_driver_name} [ID: {target_driver_id}]")
    print(f"  - Customer: {target_cust_name} [ID: {target_cust_id}]")

    # 2. Record BEFORE state of Vehicle P&L
    code, pnl_before = api(f"/api/vehicles/{urllib.parse.quote(target_reg)}/lifecycle")
    sum_before = pnl_before.get("summary", {})
    rev_before = sum_before.get("total_revenue_paise", 0) / 100
    cost_before = sum_before.get("total_cost_paise", 0) / 100
    profit_before = sum_before.get("profit_paise", 0) / 100
    km_before = sum_before.get("total_km", 0)
    duties_before = sum_before.get("duty_count", 0)

    print("\n[STEP 0] Vehicle P&L BEFORE Trip:")
    print(f"  - Completed Duties : {duties_before}")
    print(f"  - Total Distance   : {km_before} km")
    print(f"  - Gross Revenue    : Rs. {rev_before:,.2f}")
    print(f"  - Total Expenses   : Rs. {cost_before:,.2f}")
    print(f"  - Net Profit / PnL : Rs. {profit_before:,.2f}")

    # 3. Step 1: Book a Trip
    print("\n[STEP 1] Booking a new corporate trip...")
    now_utc = datetime.now(timezone.utc)
    scheduled_iso = (now_utc + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    booking_payload = {
        "customer_id": target_cust_id,
        "passenger_name": "Dr. Ananya Roy (VP Engineering)",
        "passenger_phone": "+91 98450 77112",
        "passenger_email": "ananya.roy@example.com",
        "pickup": {
            "label": "Indiranagar 100ft Road, Bengaluru",
            "city": "Bengaluru",
            "coordinates": [12.9784, 77.6408]
        },
        "dropoff": {
            "label": "Kempegowda International Airport Terminal 2",
            "city": "Bengaluru",
            "coordinates": [13.1986, 77.7066]
        },
        "duty_type": "airport",
        "vehicle_group": "Sedan",
        "scheduled_at": scheduled_iso,
        "special_instructions": "VIP Guest - Pls display name placard at Arrival Gate 4"
    }
    code, booking_res = api("/api/bookings", method="POST", body=booking_payload)
    assert code == 201, f"Booking creation failed: {code} {booking_res}"
    booking_id = booking_res["item"]["id"]
    print(f"  [OK] Booking Created: {booking_id} (Status: {booking_res['item']['status']})")

    # 4. Step 2: Allot Vehicle & Driver to Duty
    print("\n[STEP 2] Assigning Vehicle & Driver to Duty...")
    duty_payload = {
        "booking_id": booking_id,
        "vehicle_id": target_veh_id,
        "driver_id": target_driver_id,
        "supplier_id": target_vehicle.get("supplier_id") or "Falcon Corporate Fleet",
        "reporting_at": scheduled_iso
    }
    code, duty_res = api("/api/duties", method="POST", body=duty_payload)
    assert code == 201, f"Duty creation failed: {code} {duty_res}"
    duty_id = duty_res["item"]["id"]
    print(f"  [OK] Duty Allotted & Created: {duty_id} (Vehicle: {target_reg}, Driver: {target_driver_name})")

    # 5. Step 3: Trip Execution & Closure
    print("\n[STEP 3] Executing Trip & Closing Telemetry...")
    start_odo = 91600.0
    trip_km = 75.0
    end_odo = start_odo + trip_km
    start_time = (now_utc + timedelta(hours=1, minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    complete_time = (now_utc + timedelta(hours=2, minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ")

    close_payload = {
        "start_odometer": start_odo,
        "end_odometer": end_odo,
        "started_at": start_time,
        "completed_at": complete_time,
        "source": "web_command_center",
        "evidence": [
            {
                "evidence_type": "photo",
                "storage_path": "uploads/evidence/odo_end_91675.jpg",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            }
        ]
    }
    code, close_res = api(f"/api/duties/{duty_id}/close", method="POST", body=close_payload)
    assert code in (200, 201), f"Duty close failed: {code} {close_res}"
    print(f"  [OK] Duty Closed! Odometer: {start_odo} -> {end_odo} km (Total: {trip_km} km)")

    # 6. Step 4: Fare Calculation & Invoicing
    print("\n[STEP 4] Calculating Fare Snapshot & Issuing Invoice...")
    calc_payload = {
        "base_paise": 240000,
        "distance_km": int(trip_km),
        "per_km_paise": 2000,
        "duration_minutes": 105,
        "per_hour_paise": 2400,
        "tax_rate_bps": 1800,
        "parking_paise": 15000,
        "toll_paise": 10000
    }
    code, calc_res = api(f"/api/duties/{duty_id}/calculate", method="POST", body=calc_payload)
    assert code == 200, f"Calculate failed: {code} {calc_res}"
    calc = calc_res["calculation"]
    total_inv_paise = calc["total_paise"]
    print(f"  [OK] Fare Calculated: Rs. {total_inv_paise/100:,.2f} (Subtotal: Rs. {calc['subtotal_paise']/100:,.2f} + GST: Rs. {calc['tax_paise']/100:,.2f})")

    invoice_payload = {
        "duty_id": duty_id,
        "invoice_number": f"INV-TEST-{int(time.time())}"
    }
    code, inv_res = api("/api/invoices", method="POST", body=invoice_payload)
    assert code == 201, f"Invoice creation failed: {code} {inv_res}"
    inv_item = inv_res["item"]
    print(f"  [OK] Invoice Issued: {inv_item['id']} ({inv_item['invoice_number']}) - Rs. {inv_item['total_paise']/100:,.2f}")

    # 7. Step 5: Verify Vehicle P&L AFTER Invoice
    print("\n[STEP 5] Verifying Vehicle P&L Update...")
    code, pnl_after = api(f"/api/vehicles/{urllib.parse.quote(target_reg)}/lifecycle")
    sum_after = pnl_after.get("summary", {})
    rev_after = sum_after.get("total_revenue_paise", 0) / 100
    cost_after = sum_after.get("total_cost_paise", 0) / 100
    profit_after = sum_after.get("profit_paise", 0) / 100
    km_after = sum_after.get("total_km", 0)
    duties_after = sum_after.get("duty_count", 0)

    print(f"  - Completed Duties : {duties_before} -> {duties_after} (Diff: +{duties_after - duties_before})")
    print(f"  - Total Distance   : {km_before} km -> {km_after} km (Diff: +{km_after - km_before} km)")
    print(f"  - Gross Revenue    : Rs. {rev_before:,.2f} -> Rs. {rev_after:,.2f} (Diff: +Rs. {rev_after - rev_before:,.2f})")
    print(f"  - Net Profit / PnL : Rs. {profit_before:,.2f} -> Rs. {profit_after:,.2f} (Diff: +Rs. {profit_after - profit_before:,.2f})")

    assert duties_after == duties_before + 1, "Duties count did not increment!"
    assert abs(rev_after - (rev_before + (total_inv_paise / 100))) < 0.05, "Revenue did not increase by invoice total!"
    assert km_after >= km_before + trip_km, "Total km did not increase by trip distance!"
    print("  >>> SUCCESS: Vehicle P&L successfully updated with revenue, distance and duty count!")

    # 8. Step 6: Test Driver Payout Lifecycle
    print("\n[STEP 6] Testing Driver Payout Lifecycle...")
    cur_ts = int(time.time())
    driver_payout_amount_paise = 185000 # Rs. 1,850.00 driver allowance & trip wage
    payout_payload = {
        "driver_id": target_driver_id,
        "recipient_id": target_driver_id,
        "recipient_type": "driver",
        "period_start": f"2026-10-25 #{cur_ts}",
        "period_end": f"2026-10-29 #{cur_ts}",
        "gross_paise": 200000,
        "deductions_paise": 15000,
        "net_paise": driver_payout_amount_paise,
        "amount_paise": driver_payout_amount_paise,
        "metadata": {
            "driver_name": target_driver_name,
            "driver_phone": target_driver.get("phone"),
            "driver_type": target_driver.get("driver_type", "supplier"),
            "trips_count": 1,
            "total_km": trip_km,
            "trips": [{
                "duty_id": duty_id,
                "booking_id": booking_id,
                "customer_name": target_cust_name,
                "route": "Indiranagar -> KIAL T2",
                "total_km": trip_km,
                "allowance_paise": driver_payout_amount_paise
            }]
        }
    }
    code, payout_res = api("/api/driver-payouts/requests", method="POST", body=payout_payload)
    assert code == 201, f"Driver payout create failed: {code} {payout_res}"
    payout_id = payout_res["item"]["id"]
    print(f"  [OK] Driver Payout Created: {payout_id} (Status: {payout_res['item']['status']})")
    print(f"       Net Payable: Rs. {driver_payout_amount_paise / 100:,.2f}")

    # Approve Payout
    code, approve_res = api(f"/api/driver-payouts/{urllib.parse.quote(payout_id)}/approve", method="POST", body={})
    assert code == 200, f"Approve payout failed: {code} {approve_res}"
    print("  [OK] Payout Approved by Maker-Checker (Status: approved)")

    # Disburse Payout
    code, disburse_res = api(f"/api/driver-payouts/{urllib.parse.quote(payout_id)}/disburse", method="POST", body={})
    assert code == 200, f"Disburse payout failed: {code} {disburse_res}"
    bank_ref = disburse_res.get("bank_reference") or disburse_res.get("item", {}).get("bank_reference")
    print(f"  [OK] Funds Disbursed to Driver Bank Account! UTR / Bank Ref: {bank_ref}")

    # Verify Payout in List
    code, all_payouts = api("/api/driver-payouts/requests")
    matched = next((p for p in all_payouts.get("items", []) if p["id"] == payout_id), None)
    assert matched is not None and matched["status"] == "disbursed"
    print(f"  [OK] Registry Check: Payout {payout_id} is verified as 'disbursed'!")

    # 9. Step 7: Attribute Driver Cost to Vehicle P&L
    print("\n[STEP 7] Attributing Driver Cost to Vehicle P&L...")
    cost_payload = {
        "vehicle_id": target_veh_id,
        "cost_type": "vehicle",
        "category": "driver_cost",
        "amount_paise": driver_payout_amount_paise,
        "duty_id": duty_id,
        "status": "paid",
        "notes": f"Driver trip wage for {target_driver_name} (Duty {duty_id[-6:]}, {trip_km} km)"
    }
    code, cost_res = api("/api/vehicle-costs", method="POST", body=cost_payload)
    assert code in {200, 201}, f"Log vehicle cost failed: {code} {cost_res}"
    print(f"  [OK] Vehicle Cost Entry Logged: Rs. {driver_payout_amount_paise / 100:,.2f} under driver_cost")

    # 10. Final Verification of Vehicle Lifecycle & P&L
    code, pnl_final = api(f"/api/vehicles/{urllib.parse.quote(target_reg)}/lifecycle")
    sum_final = pnl_final.get("summary", {})
    cost_final = sum_final.get("total_cost_paise", 0) / 100
    profit_final = sum_final.get("profit_paise", 0) / 100

    print("\n" + "=" * 68)
    print("FINAL AUDIT: VEHICLE LIFECYCLE, P&L & UNIT ECONOMICS")
    print("=" * 68)
    print(f"  - Target Vehicle  : {target_reg} ({target_vehicle.get('make_model')})")
    print(f"  - Invoiced Revenue: Rs. {sum_final.get('total_revenue_paise', 0)/100:,.2f} (+Rs. {total_inv_paise/100:,.2f})")
    print(f"  - Total Expenses  : Rs. {cost_final:,.2f} (+Rs. {driver_payout_amount_paise/100:,.2f})")
    print(f"  - Trip Net Margin : Rs. {(total_inv_paise - driver_payout_amount_paise)/100:,.2f} ({(total_inv_paise - driver_payout_amount_paise)/total_inv_paise*100:.1f}%)")
    print(f"  - Net Vehicle P&L : Rs. {profit_final:,.2f}")
    print(f"  - Cost Breakdown  : {json.dumps({k: v/100 for k, v in pnl_final.get('cost_breakdown', {}).items()})}")
    print(f"  - Breakeven Status: {'REACHED' if sum_final.get('breakeven_reached') else 'AMORTIZING'}")
    print("=" * 68)
    print("ALL TESTS COMPLETED SUCCESSFULLY!")

if __name__ == "__main__":
    main()
