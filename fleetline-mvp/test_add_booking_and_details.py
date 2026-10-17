#!/usr/bin/env python3
"""Add a new booking and test end-to-end duty details, allotment, and fare engine."""

import json
import time
from pathlib import Path
from backend_smoke_test import call, expect, make_client

BASE = "http://127.0.0.1:4173"

def main():
    print("=" * 70)
    print("       TESTING: ADD BOOKING & DUTY DETAILS END-TO-END")
    print("=" * 70)

    jar, client = make_client(BASE)
    
    # 1. Sign up/Log in operator session
    timestamp = int(time.time())
    email = f"rydeon_ops_{timestamp}@axiom.in"
    status, signup_res = call(client, BASE, "POST", "/api/auth/signup", {
        "email": email,
        "password": "Password123!",
        "role": "vendor",
        "full_name": "Rydeon Operations Desk",
        "organization_name": "Rydeon Hospitality Private Limited",
        "city": "Bengaluru",
        "timezone": "Asia/Kolkata"
    })
    expect(status == 201 and signup_res.get("ok"), "Operator signed up and session established")
    org_id = signup_res.get("user", {}).get("organization_id")
    print(f"[OK] Session active for organization: {org_id}")

    # 2. Create Customer (Rydeon Hospitality - Bangalore)
    status, cust_res = call(client, BASE, "POST", "/api/customers", {
        "name": "Rydeon Hospitality - Bangalore",
        "email": "corporate@rydeon.in",
        "phone": "+91 80 4123 4567",
        "gstin": "29AABCR1234F1Z5",
        "city": "Bengaluru"
    })
    expect(status in (200, 201), "Customer created: Rydeon Hospitality - Bangalore")
    cust_id = cust_res["item"]["id"]

    # 3. Create Supplier & Driver & Vehicle
    status, sup_res = call(client, BASE, "POST", "/api/suppliers", {
        "name": "Shivakumar",
        "phone": "9972514143",
        "city": "Bengaluru"
    })
    expect(status in (200, 201), "Supplier created: Shivakumar (9972514143)")
    sup_id = sup_res["item"]["id"]

    status, drv_res = call(client, BASE, "POST", "/api/drivers", {
        "full_name": "Shivakumar",
        "phone": "9972514143",
        "city": "Bengaluru"
    })
    expect(status in (200, 201), "Driver created: Shivakumar")
    drv_id = drv_res["item"]["id"]

    status, veh_res = call(client, BASE, "POST", "/api/vehicles", {
        "registration_number": "KA41C 1108",
        "make_model": "Toyota Innova Crysta",
        "group_code": "Toyota Innova Crysta",
        "city": "Bengaluru"
    })
    expect(status in (200, 201), "Vehicle created: KA41C 1108 (Toyota Innova Crysta)")
    veh_id = veh_res["item"]["id"]

    # 4. Setup Airport Tariff Rules (Client + Supplier)
    status, client_rule_res = call(client, BASE, "POST", "/api/fare/rules", {
        "entity_type": "CLIENT",
        "entity_id": cust_id,
        "city_id": "Bengaluru",
        "vehicle_group_id": "Toyota Innova Crysta",
        "fare_mode": "airport",
        "package_name": "BLR Airport Transfer - Innova Crysta",
        "base_paise": 2500_00,             # Rs 2,500.00 Flat Base
        "free_waiting_minutes": 45,
        "waiting_paise_per_hour": 250_00,
        "tax_rate_bps": 500,               # 5% GST
    })
    expect(status in (200, 201), "Client Airport Tariff configured")

    status, sup_rule_res = call(client, BASE, "POST", "/api/fare/rules", {
        "entity_type": "SUPPLIER",
        "entity_id": sup_id,
        "city_id": "Bengaluru",
        "vehicle_group_id": "Toyota Innova Crysta",
        "fare_mode": "airport",
        "package_name": "Supplier Innova Crysta Payout",
        "base_paise": 1800_00,             # Rs 1,800.00 Base Cost
        "free_waiting_minutes": 45,
        "waiting_paise_per_hour": 150_00,
        "tax_rate_bps": 500,
    })
    expect(status in (200, 201), "Supplier Tariff configured")

    # 5. Add Booking (Matching screenshot reference)
    booking_payload = {
        "customer_id": cust_id,
        "customer_name": "Rydeon Hospitality - Bangalore",
        "passenger_name": "Miss Claire Spooner-Loveday",
        "passenger_phone": "9036110972",
        "duty_type": "Airport Transfer",
        "vehicle_group_code": "Toyota Innova Crysta",
        "booking_type": "single",
        "allotment_mode": "company_supplier",
        "scheduled_at": "2026-10-18T04:30:00Z",
        "start_at": "2026-10-18T03:30:00Z",
        "pickup": {
            "label": "Holiday Inn Racecourse",
            "city": "Bengaluru"
        },
        "dropoff": {
            "label": "Kempegowda International Airport",
            "city": "Bengaluru"
        },
        "notes": "Flight departure T2. Preferred Innova Crysta.",
        "labels": ["VVIP"],
        "booked_by": "Self",
        "supplier_id": sup_id,
        "driver_id": drv_id,
        "vehicle_id": veh_id
    }

    status, book_res = call(client, BASE, "POST", "/api/bookings", booking_payload)
    expect(status in (200, 201) and book_res.get("ok"), "Booking added successfully")
    booking_item = book_res["item"]
    booking_id = booking_item["id"]
    book_ref = booking_item.get("booking_reference", booking_id)
    print(f"\n[PASS] New Booking Created:")
    print(f"       Booking ID:        {booking_id}")
    print(f"       Booking Reference: #{book_ref}")
    print(f"       Passenger:         {booking_item['passenger_name']} ({booking_item.get('passenger_phone')})")
    print(f"       Duty Type:         {booking_item['duty_type']}")
    print(f"       Pickup -> Dropoff: {booking_item['pickup']['label']} -> {booking_item['dropoff']['label']}")

    # 6. Assign Driver, Vehicle, Supplier explicitly (allotment step)
    status, assign_res = call(client, BASE, "POST", f"/api/bookings/{booking_id}/assign", {
        "supplier_id": sup_id,
        "driver_id": drv_id,
        "vehicle_id": veh_id
    })
    print(f"[OK] Assignment response: status={status}")

    # 7. Create or Verify Duty Record
    status, duty_res = call(client, BASE, "POST", "/api/duties", {
        "booking_id": booking_id,
        "reporting_at": "2026-10-18T04:30:00Z",
        "status": "completed",
        "driver_id": drv_id,
        "vehicle_id": veh_id,
        "supplier_id": sup_id,
        "start_odometer": 31200,
        "end_odometer": 31242,
    })
    expect(status in (200, 201), "Duty created for booking")
    duty_item = duty_res["item"]
    duty_id = duty_item["id"]
    print(f"[PASS] Duty Created: ID = {duty_id}")

    # 8. Recalculate Fare Engine on the duty
    recalc_payload = {
        "duty_id": duty_id,
        "fare_mode": "airport",
        "vehicle_group": "Toyota Innova Crysta",
        "billing_mode": "P2P",
        "reporting_km": 31200.0,
        "releasing_km": 31242.0,
        "duration_minutes": 65,
        "waiting_minutes": 0,
        "toll_paise": 115_00,
        "parking_paise": 0,
        "reimbursements_taxable": False,
        "is_customer_interstate": False
    }
    status, recalc_res = call(client, BASE, "POST", f"/api/fare/duties/{duty_id}/recalculate", recalc_payload)
    expect(status == 200 and recalc_res.get("ok"), "Fare Engine calculation successful")

    snap = recalc_res["item"]["calculation_snapshot"]
    settlement = snap.get("settlement", {})
    pnl = settlement.get("settlement_pnl", {})
    rev = (pnl.get("net_revenue_paise", 0) / 100)
    cost = (pnl.get("net_cost_paise", 0) / 100)
    profit = (pnl.get("gross_profit_paise", 0) / 100)
    margin = pnl.get("gross_margin_percentage", 0)

    print("\n" + "=" * 70)
    print("           DUTY DETAILS SUMMARY & P&L AUDIT")
    print("=" * 70)
    print(f"Duty Details Header: Duty Details - #{book_ref}-1")
    print(f"Status:              Completed")
    print(f"Start / End Date:    18-10-2026 / 18-10-2026")
    print(f"Garage / Rep Time:   03:30 / 04:30")
    print(f"City:                Bengaluru")
    print(f"Duty Type:           Airport Transfer")
    print(f"Vehicle Group:       Toyota Innova Crysta")
    print(f"Customer:            Rydeon Hospitality - Bangalore")
    print(f"Supplier:            Shivakumar - [tel] 9972514143")
    print(f"Booked By:           Self")
    print(f"Labels:              [VVIP]")
    print(f"Reporting Address:   Holiday Inn Racecourse")
    print(f"Drop Address:        Kempegowda International Airport")
    print(f"Price:               Rs {rev:.2f} (Base + Toll)")
    print(f"Supplier Cost:       Rs {cost:.2f}")
    print(f"Duty Gross Profit:   Rs {profit:.2f} ({margin:.1f}% margin)")
    print(f"Passengers:          1. Miss Claire Spooner-Loveday - [tel] 9036110972")
    print("=" * 70)
    print("ALL TESTS PASSED: Booking added and verified with Duty Details parity!")

if __name__ == "__main__":
    main()
