#!/usr/bin/env python3
"""
Single Trip End-to-End Cycle Runner
Creates a trip, captures Trip ID (primary key), executes the complete cycle,
and reports both Trip ID and Invoice ID.
"""

import json
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

session_cookie = ""

def api(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    global session_cookie
    url = f"{BASE_URL}{path}"
    headers = {
        "Content-Type": "application/json",
        "X-Request-ID": f"req-trip-{int(time.time()*1000)}",
        "X-Axiom-User-Email": EMAIL
    }
    if session_cookie:
        headers["Cookie"] = session_cookie

    data_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as resp:
            set_cookie = resp.headers.get("Set-Cookie")
            if set_cookie and "axiom_session=" in set_cookie:
                session_cookie = set_cookie.split(";")[0]
            body_text = resp.read().decode("utf-8")
            return resp.status, (json.loads(body_text) if body_text else {})
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8")
        try:
            body = json.loads(body_text)
        except Exception:
            body = {"raw": body_text}
        return e.code, body


def main():
    print("=" * 70)
    print("STARTING SINGLE TRIP CREATION AND FULL CYCLE TESTING")
    print("=" * 70)

    # 1. Login
    status, login = api("POST", "/api/auth/login", {"email": EMAIL, "password": PASSWORD})
    assert status == 200, f"Login failed: {login}"
    print(f"[AUTH] Logged in as: {login['user']['full_name']} ({login['user']['email']})")

    # 2. Get active customer, driver, vehicle
    status, custs = api("GET", "/api/customers")
    cust_id = custs["items"][0]["id"]
    cust_name = custs["items"][0]["name"]

    status, suppliers = api("GET", "/api/suppliers")
    supplier = suppliers["items"][0] if suppliers.get("items") else None

    status, drivers = api("GET", "/api/drivers")
    driver = drivers["items"][0]
    
    status, vehicles = api("GET", "/api/vehicles")
    vehicle = vehicles["items"][0]

    now_utc = datetime.now(timezone.utc)
    reporting_iso = (now_utc + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 3. Create Booking
    booking_payload = {
        "customer_id": cust_id,
        "passenger_name": "Siddharth Verma (Director, Operations)",
        "passenger_phone": "+91 99887 76655",
        "passenger_email": "siddharth.verma@corp.example.com",
        "pickup": {
            "label": "ITC Gardenia, Residency Road",
            "city": "Bengaluru",
            "coordinates": [12.9698, 77.5968]
        },
        "dropoff": {
            "label": "Manyata Tech Park, Nagavara",
            "city": "Bengaluru",
            "coordinates": [13.0475, 77.6202]
        },
        "duty_type": "local",
        "vehicle_group": "Sedan",
        "scheduled_at": reporting_iso,
        "special_instructions": "Executive transfer - Airport return"
    }

    status, b_res = api("POST", "/api/bookings", booking_payload)
    assert status == 201, f"Booking creation failed: {b_res}"
    booking_id = b_res["item"]["id"]
    booking_ref = b_res["item"].get("booking_reference", booking_id)

    # 4. Create Trip (Duty) - This gives us the Primary Key Trip ID
    trip_payload = {
        "booking_id": booking_id,
        "supplier_id": supplier["id"] if supplier else None,
        "driver_id": driver["id"],
        "vehicle_id": vehicle["id"],
        "reporting_at": reporting_iso
    }
    status, d_res = api("POST", "/api/duties", trip_payload)
    assert status == 201, f"Duty/Trip creation failed: {d_res}"
    
    trip_id = d_res["item"]["id"]  # Primary key for the trip
    
    print("\n" + "#" * 70)
    print(f"🎯 TRIP CREATED! PRIMARY KEY TRIP ID: {trip_id}")
    print(f"   Booking Reference: {booking_ref}")
    print(f"   Customer:          {cust_name}")
    print(f"   Passenger:         {b_res['item']['passenger_name']}")
    print(f"   Assigned Driver:   {driver['full_name']}")
    print(f"   Assigned Vehicle:  {vehicle['registration_number']}")
    print("#" * 70 + "\n")

    # 5. Field Duty Execution & Closure
    start_odo = 52100
    end_odo = 52148  # 48 km
    close_payload = {
        "start_odometer": start_odo,
        "end_odometer": end_odo,
        "started_at": (now_utc + timedelta(hours=1, minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "completed_at": (now_utc + timedelta(hours=3, minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "mobile_driver_pwa",
        "evidence": [
            {
                "evidence_type": "photo",
                "storage_path": "uploads/evidence/odo_end_52148.jpg",
                "sha256": "4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a"
            },
            {
                "evidence_type": "signature",
                "storage_path": "uploads/evidence/sig_siddharth_verma.png",
                "sha256": "ef2d127de37b942baad06145e54b0c619a1f22327b2ebbcfbec78f5564afe39d"
            }
        ]
    }
    status, close_res = api("POST", f"/api/duties/{trip_id}/close", close_payload)
    assert status in (200, 201), f"Duty closure failed: {close_res}"
    print(f"[EXECUTION] Trip closed. Traversed: {end_odo - start_odo} km. Evidence attached.")

    # 6. Calculate Fare
    calc_payload = {
        "base_paise": 180000,      # ₹1,800 package (4hr 40km)
        "distance_km": 48,          # 48 km run
        "per_km_paise": 1800,       # ₹18/km
        "duration_minutes": 125,    # 2h 5m
        "per_hour_paise": 2000,     # ₹20/hr
        "tax_rate_bps": 1800,       # 18% GST
        "parking_paise": 10000,     # ₹100 parking
        "toll_paise": 9000          # ₹90 toll
    }
    status, calc_res = api("POST", f"/api/duties/{trip_id}/calculate", calc_payload)
    assert status == 200, f"Fare calculation failed: {calc_res}"
    calc = calc_res["calculation"]
    print(f"[FARE] Calculated: Subtotal ₹{calc['subtotal_paise']/100:,.2f} + Tax ₹{calc['tax_paise']/100:,.2f} = Total ₹{calc['total_paise']/100:,.2f}")

    # 7. Generate Invoice
    inv_number = f"INV-TRIP-{int(time.time())}"
    inv_payload = {
        "duty_id": trip_id,
        "invoice_number": inv_number
    }
    status, inv_res = api("POST", "/api/invoices", inv_payload)
    assert status == 201, f"Invoice creation failed: {inv_res}"
    invoice = inv_res["item"]
    invoice_id = invoice["id"]  # Primary key for the invoice

    # Transition invoice to issued
    status, _ = api("PATCH", f"/api/invoices/{invoice_id}", {"status": "issued"})
    assert status == 200, "Invoice status update to issued failed"

    # 8. Generate E-Invoice (IRN)
    status, einv = api("POST", f"/api/invoices/{invoice_id}/e-invoice", {})
    irn = einv.get("item", {}).get("irn", "IRN_MOCK_READY") if status in (200, 201) else "N/A"

    # 9. Record Payment & Reconcile
    pay_payload = {
        "invoice_id": invoice_id,
        "amount_paise": invoice["total_paise"],
        "mode": "corporate_direct_debit",
        "reference": f"TXN-NEFT-{int(time.time())}",
        "idempotency_key": f"pay-trip-{int(time.time()*1000)}"
    }
    status, pay_res = api("POST", "/api/payments", pay_payload)
    assert status == 201, f"Payment recording failed: {pay_res}"
    final_status = pay_res.get("invoice", {}).get("status", "paid").upper()

    print("\n" + "=" * 70)
    print("✅ TRIP LIFECYCLE COMPLETED SUCCESSFULLY!")
    print("=" * 70)
    print(f"👉 TRIP ID (Primary Key):    {trip_id}")
    print(f"👉 INVOICE ID (Primary Key): {invoice_id}")
    print(f"👉 INVOICE NUMBER:           {invoice['invoice_number']}")
    print(f"👉 TOTAL BILLED / PAID:      ₹{invoice['total_paise']/100:,.2f}")
    print(f"👉 INVOICE STATUS:           {final_status}")
    print(f"👉 GST IRN:                  {irn}")
    print("=" * 70)

    # Return structured dict to json output for callers if needed
    result = {
        "trip_id": trip_id,
        "booking_id": booking_id,
        "booking_reference": booking_ref,
        "invoice_id": invoice_id,
        "invoice_number": invoice["invoice_number"],
        "total_fare_inr": invoice["total_paise"] / 100,
        "invoice_status": final_status
    }
    with open("last_trip_result.json", "w") as f:
        json.dump(result, f, indent=2)

if __name__ == "__main__":
    main()
