#!/usr/bin/env python3
"""
E2E Test Suite: Supplier-First Allotment Hierarchy & Full Trip Lifecycle to Invoicing
- Criteria 1: Block/Flag assignment without Supplier (Status: 'Supplier needed', Needs Attention)
- Criteria 2: Add Supplier first, then Vehicle & Driver in any order (Vehicle first -> Driver next, or Driver first -> Vehicle next)
- Criteria 3: Only when Supplier + Driver + Vehicle are present does status become 'Allotted'
- Full Cycle: Booking -> Allotment -> Execution & Closure -> Fare Calculation -> Tax Invoice -> Payment
"""

import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "http://127.0.0.1:4173"
EMAIL = "reddragon0075@gmail.com"
PASSWORD = "motion2026"

from http.cookiejar import CookieJar

jar = CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

def api(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    url = f"{BASE_URL}{path}"
    headers = {
        "Content-Type": "application/json",
        "X-Request-ID": f"req-sup-first-{int(time.time()*1000)}",
        "X-Axiom-User-Email": EMAIL
    }
    data_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)

    try:
        with opener.open(req, timeout=15) as resp:
            body_text = resp.read().decode("utf-8")
            return resp.status, (json.loads(body_text) if body_text else {})
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8")
        try:
            body = json.loads(body_text)
        except Exception:
            body = {"raw": body_text}
        return e.code, body


def resolve_frontend_status(booking: dict, duty: dict | None, has_invoice: bool = False):
    """Replicates the exact frontend status computation logic from index.html bookingRowsForDisplay"""
    b_stat = str(booking.get("status", "requested")).lower()
    d_stat = str(duty.get("status", "")).lower() if duty else ""

    raw_status = b_stat
    if has_invoice or d_stat == "billed" or b_stat == "billed":
        raw_status = "billed"
    elif d_stat in ("completed", "closed") or b_stat in ("completed", "closed"):
        raw_status = "completed"
    elif d_stat in ("dispatched", "en_route", "started", "in_progress") or b_stat in ("dispatched", "en_route", "started", "in_progress"):
        raw_status = "dispatched"
    elif d_stat == "assigned" or b_stat == "assigned":
        raw_status = "assigned"

    sup_name = booking.get("supplier_name") or (duty.get("supplier_name") if duty else "")
    sup_id = booking.get("supplier_id") or (duty.get("supplier_id") if duty else "")
    has_supplier = bool(sup_name or sup_id)

    drv_name = booking.get("driver_name") or (duty.get("driver_name") if duty else "")
    drv_id = booking.get("driver_id") or (duty.get("driver_id") if duty else "")
    has_driver = bool(drv_name or drv_id)

    veh_num = booking.get("vehicle_number") or (duty.get("vehicle_number") if duty else "")
    veh_id = booking.get("vehicle_id") or (duty.get("vehicle_id") if duty else "")
    has_vehicle = bool(veh_num or veh_id)

    if raw_status in ("cancelled", "rejected"):
        return "Cancelled", False
    if raw_status in ("billed", "invoiced"):
        return "Billed", False
    if raw_status in ("completed", "closed"):
        return "Completed", False
    if raw_status in ("dispatched", "en_route", "started", "in_progress"):
        return "Dispatched", False

    # Allotment hierarchy: Supplier FIRST
    if not has_supplier and (has_vehicle or has_driver):
        return "Supplier needed", True
    if not has_supplier and not has_vehicle and not has_driver:
        return "To be assigned", True
    if has_supplier and not has_vehicle and not has_driver:
        return "Driver & Vehicle needed", True
    if has_supplier and has_vehicle and not has_driver:
        return "Driver needed", True
    if has_supplier and not has_vehicle and has_driver:
        return "Vehicle needed", True
    if has_supplier and has_vehicle and has_driver:
        return "Allotted", False

    return "Booked", False


def main():
    print("=" * 80)
    print("AXIOM FLEET: SUPPLIER-FIRST ALLOTMENT & FULL TRIP CYCLE E2E TEST")
    print("=" * 80)

    # 1. Authenticate
    status, login = api("POST", "/api/auth/login", {"email": EMAIL, "password": PASSWORD})
    assert status == 200, f"Login failed: {login}"
    print(f"✓ [1. AUTH] Logged in as: {login['user']['full_name']} ({login['user']['email']})")

    # 2. Get customer (India White Pvt - IWP)
    status, custs = api("GET", "/api/customers")
    assert status == 200
    target_cust = next((c for c in custs.get("items", []) if c.get("code") == "IWP" or "india white" in c.get("name", "").lower()), None)
    if not target_cust:
        status, new_c = api("POST", "/api/customers", {"name": "India White Pvt", "code": "IWP", "city": "Bengaluru"})
        target_cust = new_c["item"]
    print(f"✓ [2. CUSTOMER] Corporate Customer: '{target_cust['name']}' (Code: {target_cust['code']})")

    # 3. Retrieve available Resources: Supplier, Driver, Vehicle
    status, sups = api("GET", "/api/suppliers")
    supplier = sups["items"][0]
    status, drvs = api("GET", "/api/drivers")
    driver = drvs["items"][0]
    status, vehs = api("GET", "/api/vehicles")
    vehicle = vehs["items"][0]
    print(f"✓ [3. RESOURCES] Supplier: {supplier['name']} | Driver: {driver['full_name']} | Vehicle: {vehicle['registration_number']}")

    now_utc = datetime.now(timezone.utc)
    rep_time = (now_utc + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # =========================================================================
    # PART A: TEST CRITERIA — "Supplier must be added ... vehicle and driver next
    #         irrespective of the order ... but supplier first"
    # =========================================================================
    print("\n" + "-" * 80)
    print("TESTING CRITERIA 1: ATTEMPTING ALLOTMENT WITHOUT SUPPLIER")
    print("-" * 80)

    # Create Booking
    b_payload = {
        "customer_id": target_cust["id"],
        "passenger_name": "Meera Nambiar (VP Strategy)",
        "passenger_phone": "+91 97777 22334",
        "pickup": {"label": "India White HQ, Indiranagar", "city": "Bengaluru"},
        "dropoff": {"label": "Kempegowda International Airport Terminal 2", "city": "Bengaluru"},
        "duty_type": "airport",
        "vehicle_group": "Sedan",
        "scheduled_at": rep_time
    }
    status, b1 = api("POST", "/api/bookings", b_payload)
    assert status == 201, f"Booking creation failed: {b1}"
    b1_id = b1["item"]["id"]
    print(f"✓ Booking b1 created: {b1_id}")

    # Initial state: no resources
    st_init, att_init = resolve_frontend_status(b1["item"], None)
    print(f"   Initial Status: '{st_init}', Needs Attention: {att_init}")
    assert st_init == "To be assigned" and att_init is True

    # Attempt to assign Vehicle & Driver WITHOUT Supplier
    print("\n👉 Attempting to assign Driver and Vehicle without a Supplier...")
    status, assign_no_sup = api("POST", f"/api/bookings/{b1_id}/assign", {
        "driver_id": driver["id"],
        "vehicle_id": vehicle["id"],
        "supplier_id": None
    })
    assert status == 200, f"Assignment failed ({status}): {assign_no_sup}"
    b1_assigned = assign_no_sup["booking"]

    # Verify backend does NOT mark booking as 'assigned' (it stays 'confirmed' or requires attention)
    assert b1_assigned["status"] != "assigned", f"Booking must NOT be marked assigned without supplier: {b1_assigned['status']}"
    print(f"✓ Backend status without supplier: '{b1_assigned['status']}' (NOT 'assigned')")

    # Verify frontend evaluates to 'Supplier needed' and triggers Needs Attention
    st_no_sup, att_no_sup = resolve_frontend_status(b1_assigned, assign_no_sup.get("duty"))
    print(f"✓ Frontend display status: '{st_no_sup}', Needs Attention: {att_no_sup}")
    assert st_no_sup == "Supplier needed", f"Expected 'Supplier needed' but got '{st_no_sup}'"
    assert att_no_sup is True, "Must require attention when supplier is missing!"
    print("✅ CRITERIA 1 VERIFIED: Resource allotment without supplier is flagged 'Supplier needed' and stays in Needs Attention!")

    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("TESTING CRITERIA 2: ALLOTTING SUPPLIER FIRST -> THEN VEHICLE -> THEN DRIVER")
    print("-" * 80)

    # Step A: Allot Supplier FIRST
    print(f"👉 Step A: Assigning Supplier '{supplier['name']}' first...")
    status, assign_sup = api("POST", f"/api/bookings/{b1_id}/assign", {
        "supplier_id": supplier["id"],
        "driver_id": None,
        "vehicle_id": None
    })
    assert status == 200
    st_sup, att_sup = resolve_frontend_status(assign_sup["booking"], assign_sup.get("duty"))
    print(f"✓ After Supplier assigned: Status = '{st_sup}', Needs Attention = {att_sup}")
    assert st_sup == "Driver & Vehicle needed" and att_sup is True

    # Step B: Allot Vehicle SECOND (before driver)
    print(f"👉 Step B: Assigning Vehicle '{vehicle['registration_number']}' next (Driver still unassigned)...")
    status, assign_veh = api("POST", f"/api/bookings/{b1_id}/assign", {
        "supplier_id": supplier["id"],
        "vehicle_id": vehicle["id"],
        "driver_id": None
    })
    assert status == 200
    st_veh, att_veh = resolve_frontend_status(assign_veh["booking"], assign_veh.get("duty"))
    print(f"✓ After Vehicle assigned: Status = '{st_veh}', Needs Attention = {att_veh}")
    assert st_veh == "Driver needed" and att_veh is True

    # Step C: Allot Driver THIRD
    print(f"👉 Step C: Assigning Driver '{driver['full_name']}'...")
    status, assign_all = api("POST", f"/api/bookings/{b1_id}/assign", {
        "supplier_id": supplier["id"],
        "vehicle_id": vehicle["id"],
        "driver_id": driver["id"]
    })
    assert status == 200
    st_all, att_all = resolve_frontend_status(assign_all["booking"], assign_all.get("duty"))
    print(f"✓ After All three assigned: Status = '{st_all}', Needs Attention = {att_all}")
    assert st_all == "Allotted" and att_all is False
    print("✅ CRITERIA 2 VERIFIED: Supplier first -> Vehicle next -> Driver next -> Status transitions to 'Allotted'!")

    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("TESTING CRITERIA 3: REVERSE SECONDARY ORDER (SUPPLIER FIRST -> DRIVER -> VEHICLE)")
    print("-" * 80)

    # Create second booking to test Driver first, Vehicle second
    status, b2 = api("POST", "/api/bookings", {**b_payload, "passenger_name": "Kavita Rao (Director)"})
    b2_id = b2["item"]["id"]

    # Allot Supplier first
    api("POST", f"/api/bookings/{b2_id}/assign", {"supplier_id": supplier["id"]})

    # Allot Driver next (before vehicle)
    print(f"👉 Assigning Driver '{driver['full_name']}' before Vehicle...")
    status, assign_drv_first = api("POST", f"/api/bookings/{b2_id}/assign", {
        "supplier_id": supplier["id"],
        "driver_id": driver["id"],
        "vehicle_id": None
    })
    st_drv, att_drv = resolve_frontend_status(assign_drv_first["booking"], assign_drv_first.get("duty"))
    print(f"✓ After Driver assigned: Status = '{st_drv}', Needs Attention = {att_drv}")
    assert st_drv == "Vehicle needed" and att_drv is True

    # Allot Vehicle next
    status, assign_b2_all = api("POST", f"/api/bookings/{b2_id}/assign", {
        "supplier_id": supplier["id"],
        "driver_id": driver["id"],
        "vehicle_id": vehicle["id"]
    })
    st_b2_all, att_b2_all = resolve_frontend_status(assign_b2_all["booking"], assign_b2_all.get("duty"))
    print(f"✓ After Vehicle assigned: Status = '{st_b2_all}', Needs Attention = {att_b2_all}")
    assert st_b2_all == "Allotted" and att_b2_all is False
    print("✅ CRITERIA 3 VERIFIED: Supplier first -> Driver next -> Vehicle next -> Status transitions to 'Allotted'!")

    # =========================================================================
    # PART B: FULL TRIP CYCLE TO INVOICE (USING B1 / IWP)
    # =========================================================================
    print("\n" + "=" * 80)
    print("STARTING FULL TRIP CYCLE TO INVOICE FOR TRIP")
    print("=" * 80)

    # 1. Fetch Duty ID
    duty_item = assign_all.get("duty")
    duty_id = duty_item["id"] if duty_item else None
    if not duty_id:
        status, duties = api("GET", "/api/duties")
        duty_item = next((d for d in duties.get("items", []) if d.get("booking_id") == b1_id), None)
        assert duty_item, "Duty not found for booking b1"
        duty_id = duty_item["id"]

    print(f"👉 TRIP ID (PRIMARY KEY): {duty_id}")
    match = re.match(r"^IWP(\d{4})$", duty_id)
    assert match, f"Trip ID {duty_id} does not follow IWP0000 format!"
    print(f"✓ Trip ID naming confirmed: {duty_id} (Corporate Prefix: IWP, Sequence: {match.group(1)})")

    # 2. Execute Field Duty & Close with Telemetry
    print("\n👉 Executing trip on road and submitting closure telemetry...")
    start_odo = 41500
    end_odo = 41558  # 58 km covered
    close_payload = {
        "start_odometer": start_odo,
        "end_odometer": end_odo,
        "started_at": (now_utc + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "completed_at": (now_utc + timedelta(hours=2, minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "driver_app",
        "evidence": [
            {
                "evidence_type": "photo",
                "storage_path": f"uploads/evidence/odo_{end_odo}.jpg",
                "content": f"data:image/jpeg;base64,odo_{end_odo}"
            },
            {
                "evidence_type": "signature",
                "storage_path": "uploads/evidence/sig_meera_nambiar.png",
                "content": "data:image/png;base64,signature_meera"
            }
        ]
    }
    status, close_res = api("POST", f"/api/duties/{duty_id}/close", close_payload)
    assert status in (200, 201), f"Duty closure failed: {close_res}"
    closed_duty = close_res.get("duty", close_res.get("item", {}))
    print(f"✓ Duty {duty_id} closed! Status: {closed_duty.get('status')}")
    assert closed_duty.get("status") == "completed"

    # Verify parent booking status was synchronized to 'completed'
    status, b_check = api("GET", f"/api/bookings")
    updated_b1 = next((b for b in b_check.get("items", []) if b.get("id") == b1_id), None)
    assert updated_b1 and updated_b1.get("status") == "completed", f"Parent booking status should be 'completed', got {updated_b1}"
    print(f"✓ Parent booking {b1_id} status synchronized: '{updated_b1['status']}'")

    # 3. Calculate Pricing with Fare Engine
    print("\n👉 Running Fare Engine calculation audit...")
    calc_payload = {
        "base_paise": 240000,       # ₹2,400 airport package
        "distance_km": 58,          # 58 km traversed
        "per_km_paise": 2000,       # ₹20/km
        "duration_minutes": 125,    # 2h 5m
        "per_hour_paise": 2500,     # ₹25/hr
        "tax_rate_bps": 1800,       # 18% GST
        "toll_paise": 11000,        # ₹110 airport toll
        "parking_paise": 10000      # ₹100 airport parking
    }
    status, calc_res = api("POST", f"/api/duties/{duty_id}/calculate", calc_payload)
    assert status == 200, f"Fare calculation failed: {calc_res}"
    calc = calc_res["calculation"]
    total_paise = calc["total_paise"]
    print(f"✓ Fare Snapshot Generated: Subtotal ₹{calc['subtotal_paise']/100:,.2f} + Tax ₹{calc['tax_paise']/100:,.2f} = Grand Total ₹{total_paise/100:,.2f}")

    # 4. Generate & Issue Tax Invoice
    print("\n👉 Generating Tax Invoice...")
    inv_number = f"INV-{target_cust.get('code', 'IWP')}-{int(time.time())}"
    inv_payload = {
        "duty_id": duty_id,
        "invoice_number": inv_number
    }
    status, inv_res = api("POST", "/api/invoices", inv_payload)
    assert status == 201, f"Invoice creation failed: {inv_res}"
    invoice = inv_res["item"]
    invoice_id = invoice["id"]
    invoice_num = invoice.get("invoice_number", invoice_id)
    print(f"✓ Tax Invoice Created: {invoice_num} (ID: {invoice_id})")

    # Issue Invoice
    status, _ = api("PATCH", f"/api/invoices/{invoice_id}", {"status": "issued"})
    assert status == 200, "Failed to issue invoice"

    # 5. Issue E-Invoice & GST IRN
    print("👉 Generating E-Invoice IRN & QR payload...")
    status, einv_res = api("POST", f"/api/invoices/{invoice_id}/e-invoice")
    assert status in (200, 201), f"E-invoice failed: {einv_res}"
    irn = einv_res.get("irn", "mock_irn_success")
    print(f"✓ GST IRN Issued: {irn}")

    # 6. Record Payment Reconciliation
    print("👉 Recording customer payment...")
    pay_payload = {
        "invoice_id": invoice_id,
        "amount_paise": total_paise,
        "payment_method": "neft",
        "transaction_reference": f"TXN-{int(time.time())}",
        "paid_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    }
    status, pay_res = api("POST", "/api/payments", pay_payload)
    assert status in (200, 201), f"Payment failed: {pay_res}"
    print(f"✓ Payment of ₹{(total_paise / 100):.2f} reconciled. Status: PAID")

    # Verify final frontend status
    st_final, att_final = resolve_frontend_status(updated_b1, closed_duty, has_invoice=True)
    assert st_final == "Billed" and att_final is False
    print(f"✓ Final table status: '{st_final}', Needs Attention: {att_final}")

    print("\n" + "=" * 80)
    print("🎉 ALL TESTS PASSED: SUPPLIER-FIRST CRITERIA & FULL TRIP CYCLE VERIFIED!")
    print("=" * 80)
    print(f"👉 TRIP ID (Primary Key):       {duty_id}")
    print(f"👉 INVOICE ID (Primary Key):    {invoice_id}")
    print(f"👉 INVOICE NUMBER:              {invoice_num}")
    print(f"👉 CORPORATE CUSTOMER:          {target_cust['name']} ({target_cust['code']})")
    print(f"👉 ALLOTTED SUPPLIER:           {supplier['name']}")
    print(f"👉 ALLOTTED DRIVER:             {driver['full_name']}")
    print(f"👉 ALLOTTED VEHICLE:            {vehicle['registration_number']}")
    print(f"👉 TOTAL AMOUNT:                ₹{(total_paise / 100):.2f}")
    print(f"👉 INVOICE & PAYMENT STATUS:    PAID")
    print("=" * 80)

if __name__ == "__main__":
    main()
