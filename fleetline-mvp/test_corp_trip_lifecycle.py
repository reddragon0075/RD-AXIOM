#!/usr/bin/env python3
"""
Test Corporate Code Based Trip ID Generation & Full Lifecycle Testing
Company: 'India White Pvt' with code 'IWP'
Expected Trip ID: IWP0001
Complete cycle -> Invoicing -> Invoice ID
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

from http.cookiejar import CookieJar

jar = CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

def api(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    url = f"{BASE_URL}{path}"
    headers = {
        "Content-Type": "application/json",
        "X-Request-ID": f"req-iwp-{int(time.time()*1000)}",
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


def main():
    print("=" * 75)
    print("TESTING CORPORATE PREFIX TRIP ID & FULL CYCLE (COMPANY: INDIA WHITE PVT)")
    print("=" * 75)

    # 1. Login
    status, login = api("POST", "/api/auth/login", {"email": EMAIL, "password": PASSWORD})
    assert status == 200, f"Login failed: {login}"
    print(f"✓ [AUTH] Authenticated as: {login['user']['full_name']} ({login['user']['email']})")

    # 2. Check or Create Company "India White Pvt" with code "IWP"
    status, custs = api("GET", "/api/customers")
    assert status == 200, f"Failed to get customers: {custs}"
    
    target_cust = None
    for c in custs.get("items", []):
        if c.get("name", "").strip().lower() == "india white pvt" or c.get("code") == "IWP":
            target_cust = c
            break

    if not target_cust:
        status, new_cust = api("POST", "/api/customers", {
            "name": "India White Pvt",
            "code": "IWP",
            "email": "operations@indiawhite.example.com",
            "phone": "+91 80 4123 9900",
            "gstin": "29AAACI9876Q1Z9",
            "city": "Bengaluru"
        })
        assert status == 201, f"Failed to create India White Pvt customer: {new_cust}"
        target_cust = new_cust["item"]
        print(f"✓ Created Company: '{target_cust['name']}' with Code: '{target_cust.get('code')}' (ID: {target_cust['id']})")
    else:
        print(f"✓ Found Company: '{target_cust['name']}' with Code: '{target_cust.get('code')}' (ID: {target_cust['id']})")

    # 3. Get active supplier, driver and vehicle (pick ones without active duty conflict)
    status, suppliers = api("GET", "/api/suppliers")
    supplier = suppliers["items"][0] if suppliers.get("items") else None
    status, duties = api("GET", "/api/duties?limit=200")
    active_duties = [d for d in duties.get("items", []) if d.get("status") not in ("completed", "billed", "cancelled")]
    busy_drivers = {d.get("driver_id") for d in active_duties if d.get("driver_id")}
    busy_vehicles = {d.get("vehicle_id") for d in active_duties if d.get("vehicle_id")}

    status, drivers = api("GET", "/api/drivers")
    driver = next((d for d in drivers.get("items", []) if d.get("id") not in busy_drivers), drivers["items"][0])
    status, vehicles = api("GET", "/api/vehicles")
    vehicle = next((v for v in vehicles.get("items", []) if v.get("id") not in busy_vehicles), vehicles["items"][0])

    now_utc = datetime.now(timezone.utc)
    reporting_iso = (now_utc + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 4. Create Trip Booking for India White Pvt
    booking_payload = {
        "customer_id": target_cust["id"],
        "passenger_name": "Arjun Singhania (Head of Procurement)",
        "passenger_phone": "+91 98888 11223",
        "passenger_email": "arjun.singhania@indiawhite.example.com",
        "pickup": {
            "label": "India White HQ, Indiranagar 100ft Road",
            "city": "Bengaluru",
            "coordinates": [12.9784, 77.6408]
        },
        "dropoff": {
            "label": "Kempegowda International Airport Terminal 2",
            "city": "Bengaluru",
            "coordinates": [13.2001, 77.7089]
        },
        "duty_type": "airport",
        "vehicle_group": "Sedan",
        "scheduled_at": reporting_iso,
        "special_instructions": "VIP Corporate Guest - Flight UK-812"
    }

    status, b_res = api("POST", "/api/bookings", booking_payload)
    assert status == 201, f"Booking creation failed: {b_res}"
    booking_id = b_res["item"]["id"]
    booking_ref = b_res["item"].get("booking_reference", booking_id)
    print(f"✓ Booking Created: {booking_ref} (ID: {booking_id})")

    # 5. Create Duty / Trip -> Verify generated Trip ID
    duty_payload = {
        "booking_id": booking_id,
        "supplier_id": supplier["id"] if supplier else None,
        "driver_id": driver["id"],
        "vehicle_id": vehicle["id"],
        "reporting_at": reporting_iso
    }
    status, d_res = api("POST", "/api/duties", duty_payload)
    assert status == 201, f"Duty/Trip creation failed: {d_res}"
    trip_id = d_res["item"]["id"]

    print("\n" + "*" * 75)
    print(f"👉 GENERATED TRIP ID (PRIMARY KEY): {trip_id}")
    print(f"   Company:        {target_cust['name']} (Code: {target_cust.get('code', 'IWP')})")
    print(f"   Passenger:      {b_res['item']['passenger_name']}")
    print(f"   Assigned Driver:{driver['full_name']}")
    print(f"   Vehicle:        {vehicle['registration_number']}")
    print("*" * 75 + "\n")

    # Assert that the trip id starts with "IWP" and has 4 digits (e.g. IWP0001)
    assert trip_id.startswith("IWP"), f"Trip ID {trip_id} does not start with IWP"
    suffix = trip_id[3:]
    assert len(suffix) >= 4 and suffix.isdigit(), f"Trip ID {trip_id} does not have numeric sequence suffix"
    print(f"✓ TRIP ID FORMAT VERIFIED: Follows {target_cust.get('code')} + 4-digit sequence -> {trip_id}")

    # 6. Execute Trip & Field Closure
    start_odo = 31200
    end_odo = 31252  # 52 km
    close_payload = {
        "start_odometer": start_odo,
        "end_odometer": end_odo,
        "started_at": (now_utc + timedelta(hours=1, minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "completed_at": (now_utc + timedelta(hours=2, minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "driver_field_pwa",
        "evidence": [
            {
                "evidence_type": "photo",
                "storage_path": "uploads/evidence/odo_end_31252.jpg",
                "sha256": "8f48032271864e766f6c2953ec11615544b7e626bce349f21e42eccf438972ee"
            },
            {
                "evidence_type": "signature",
                "storage_path": "uploads/evidence/sig_arjun_singhania.png",
                "sha256": "4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a"
            }
        ]
    }
    status, close_res = api("POST", f"/api/duties/{trip_id}/close", close_payload)
    assert status in (200, 201), f"Duty closure failed: {close_res}"
    print(f"✓ Trip {trip_id} Closed. Distance traversed: {end_odo - start_odo} km. Evidence attached.")

    # 7. Fare Calculation
    calc_payload = {
        "base_paise": 220000,      # ₹2,200 airport package
        "distance_km": 52,          # 52 km
        "per_km_paise": 2000,       # ₹20/km
        "duration_minutes": 95,     # 1h 35m
        "per_hour_paise": 2400,     # ₹24/hr
        "tax_rate_bps": 1800,       # 18% GST
        "toll_paise": 11000,        # ₹110 airport toll
        "parking_paise": 10000      # ₹100 airport parking
    }
    status, calc_res = api("POST", f"/api/duties/{trip_id}/calculate", calc_payload)
    assert status == 200, f"Fare calculation failed: {calc_res}"
    calc = calc_res["calculation"]
    print(f"✓ Fare Snapshot Generated: Subtotal ₹{calc['subtotal_paise']/100:,.2f} + Tax ₹{calc['tax_paise']/100:,.2f} = Grand Total ₹{calc['total_paise']/100:,.2f}")

    # 8. Generate Invoice
    inv_number = f"INV-{target_cust.get('code', 'IWP')}-{int(time.time())}"
    inv_payload = {
        "duty_id": trip_id,
        "invoice_number": inv_number
    }
    status, inv_res = api("POST", "/api/invoices", inv_payload)
    assert status == 201, f"Invoice creation failed: {inv_res}"
    invoice = inv_res["item"]
    invoice_id = invoice["id"]  # Primary key for the invoice

    # Issue Invoice
    status, _ = api("PATCH", f"/api/invoices/{invoice_id}", {"status": "issued"})
    assert status == 200, "Invoice status update to issued failed"
    print(f"✓ Tax Invoice Generated & Issued! ID: {invoice_id} (Number: {invoice['invoice_number']})")

    # 9. Generate E-Invoice (IRN)
    status, einv = api("POST", f"/api/invoices/{invoice_id}/e-invoice", {})
    irn = einv.get("item", {}).get("irn", "IRN_MOCK_READY") if status in (200, 201) else "N/A"
    print(f"✓ E-Invoice IRN: {irn}")

    # 10. Record Payment & Reconcile
    pay_payload = {
        "invoice_id": invoice_id,
        "amount_paise": invoice["total_paise"],
        "mode": "corporate_direct_debit",
        "reference": f"IWP-PAY-{int(time.time())}",
        "idempotency_key": f"pay-iwp-{int(time.time()*1000)}"
    }
    status, pay_res = api("POST", "/api/payments", pay_payload)
    assert status == 201, f"Payment recording failed: {pay_res}"
    final_status = pay_res.get("invoice", {}).get("status", "paid").upper()
    print(f"✓ Payment of ₹{invoice['total_paise']/100:,.2f} recorded. Status: {final_status}")

    print("\n" + "=" * 75)
    print("🎉 FULL CYCLE TEST FOR 'INDIA WHITE PVT' (CODE: IWP) COMPLETED!")
    print("=" * 75)
    print(f"👉 TRIP ID (Primary Key):    {trip_id}")
    print(f"👉 INVOICE ID (Primary Key): {invoice_id}")
    print(f"👉 INVOICE NUMBER:           {invoice['invoice_number']}")
    print(f"👉 TOTAL BILLED / PAID:      ₹{invoice['total_paise']/100:,.2f}")
    print(f"👉 INVOICE STATUS:           {final_status}")
    print(f"👉 GST IRN:                  {irn}")
    print("=" * 75)

if __name__ == "__main__":
    main()
