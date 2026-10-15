#!/usr/bin/env python3
"""Execute an Airport Trip and check its fare through the Axiom Fare Engine."""

import time
from backend_smoke_test import call, expect, make_client

BASE = "http://127.0.0.1:4173"

def main():
    jar, client = make_client(BASE)
    
    # 1. Sign up tenant
    email = f"airport_ops_{int(time.time())}@axiom.in"
    status, signup_res = call(client, BASE, "POST", "/api/auth/signup", {
        "email": email,
        "password": "Password123!",
        "role": "vendor",
        "full_name": "Bengaluru Airport Dispatch",
        "organization_name": "Axiom Airport Express",
        "city": "Bengaluru",
        "timezone": "Asia/Kolkata"
    })
    expect(status == 201 and signup_res.get("ok"), "Tenant signed up")

    # 2. Setup Airport Tariff Rules in 4-Tier Hierarchy
    # Client Contracted Rate Card (Tier 1: Client Specific)
    status, client_rule_res = call(client, BASE, "POST", "/api/fare/rules", {
        "entity_type": "CLIENT",
        "entity_id": "cust-infosys",
        "city_id": "Bengaluru",
        "vehicle_group_id": "SEDAN",
        "fare_mode": "airport",
        "package_name": "BLR T2 Airport Transfer - Corporate Sedan",
        "base_paise": 1400_00,             # Rs 1,400.00 Flat Base
        "free_waiting_minutes": 45,        # 45 mins free waiting
        "waiting_paise_per_hour": 200_00,   # Rs 200.00/hr excess waiting
        "tax_rate_bps": 500,               # 5% GST
    })
    expect(status in (200, 201), "Client airport tariff rule saved")
    client_rule_id = client_rule_res["item"]["id"]

    # Supplier Payable Rate Card (Tier 3: City Default)
    status, supplier_rule_res = call(client, BASE, "POST", "/api/fare/rules", {
        "entity_type": "SUPPLIER",
        "city_id": "Bengaluru",
        "vehicle_group_id": "SEDAN",
        "fare_mode": "airport",
        "package_name": "BLR Airport Transfer - Driver Rack",
        "base_paise": 1100_00,             # Rs 1,100.00 Flat Base
        "free_waiting_minutes": 45,        # 45 mins free waiting
        "waiting_paise_per_hour": 150_00,   # Rs 150.00/hr excess waiting
        "tax_rate_bps": 500,               # 5% GST
    })
    expect(status in (200, 201), "Supplier airport tariff rule saved")
    supplier_rule_id = supplier_rule_res["item"]["id"]

    # 3. Create Corporate Customer
    status, cust_res = call(client, BASE, "POST", "/api/customers", {
        "name": "Infosys Corporate Travel",
        "email": "travel-blr@infosys.com",
        "phone": "+91 80 2852 0261",
        "gstin": "29AAACI1234A1Z5"
    })
    expect(status in (200, 201), "Customer created")
    cust_id = cust_res["item"]["id"]

    # Also update our client tariff rule entity_id to match this created customer id
    call(client, BASE, "POST", "/api/fare/rules", {
        "id": client_rule_id,
        "entity_type": "CLIENT",
        "entity_id": cust_id,
        "city_id": "Bengaluru",
        "vehicle_group_id": "SEDAN",
        "fare_mode": "airport",
        "package_name": "BLR T2 Airport Transfer - Corporate Sedan",
        "base_paise": 1400_00,
        "free_waiting_minutes": 45,
        "waiting_paise_per_hour": 200_00,
        "tax_rate_bps": 500,
    })

    # 4. Create Airport Booking
    status, book_res = call(client, BASE, "POST", "/api/bookings", {
        "customer_id": cust_id,
        "passenger_name": "Dr. Vikram Malhotra (VP Engineering)",
        "passenger_phone": "+91 98450 12345",
        "duty_type": "airport",
        "scheduled_at": "2026-10-15T08:30:00Z",
        "pickup": {"label": "Kempegowda International Airport (BLR) T2 Arrivals", "city": "Bengaluru"},
        "dropoff": {"label": "Manyata Tech Park, Outer Ring Road, Bengaluru", "city": "Bengaluru"},
        "vehicle_group_id": "SEDAN",
    })
    expect(status in (200, 201), "Airport Booking created")
    print("Book response:", book_res)
    book_id = book_res["item"]["id"]
    book_ref = book_res["item"]["booking_reference"]

    # 5. Create Assigned Duty for Booking
    status, duty_res = call(client, BASE, "POST", "/api/duties", {
        "booking_id": book_id,
        "reporting_at": "2026-10-15T08:15:00Z",
        "status": "completed",
        "start_odometer": 45210,
        "end_odometer": 45248,
    })
    print("Duty response:", status, duty_res)
    expect(status in (200, 201), "Duty created")
    duty_id = duty_res["item"]["id"]

    # 6. Recalculate Fare on Duty via Fare Engine
    # Telemetry: 38 KM distance, 75 mins waiting at Airport (Flight delay), Rs 115 KIAL Toll, Rs 150 Parking
    recalc_payload = {
        "duty_id": duty_id,
        "fare_mode": "airport",
        "vehicle_group": "SEDAN",
        "billing_mode": "P2P",
        "reporting_km": 45210.0,
        "releasing_km": 45248.0,
        "duration_minutes": 115,         # 1 hr 55 mins total trip
        "waiting_minutes": 75,           # 75 mins waiting (45 free + 30 excess)
        "toll_paise": 115_00,            # Rs 115 Airport Trumpet Toll
        "parking_paise": 150_00,         # Rs 150 Airport T2 Parking
        "reimbursements_taxable": False, # Pure agent exclusion
        "is_customer_interstate": False
    }

    status, recalc_res = call(client, BASE, "POST", f"/api/fare/duties/{duty_id}/recalculate", recalc_payload)
    print("Recalc response:", status, recalc_res)
    expect(status == 200 and recalc_res.get("ok"), "Fare recalculated successfully")

    snapshot = recalc_res["item"]["calculation_snapshot"]
    settlement = snapshot["settlement"]
    rec = settlement["receivable"]
    pay = settlement["payable"]
    pnl = settlement["settlement_pnl"]

    print("\n" + "="*70)
    print("           AXIOM FLEET FARE ENGINE - AIRPORT TRIP AUDIT")
    print("="*70)
    print(f"Booking Ref:    {book_ref}")
    print(f"Duty ID:        {duty_id}")
    print(f"Passenger:      Dr. Vikram Malhotra (VP Engineering)")
    print(f"Client:         Infosys Corporate Travel")
    print(f"Service Mode:   AIRPORT TRANSFER (airport)")
    print(f"Pickup:         Kempegowda International Airport (BLR) T2 Arrivals")
    print(f"Dropoff:        Manyata Tech Park, Outer Ring Road, Bengaluru")
    print(f"Vehicle Group:  SEDAN")
    print(f"Distance:       {45248 - 45210} KM (Odometer: 45210 -> 45248)")
    print(f"Airport Wait:   75 mins total (45 mins free included + 30 mins excess billable)")
    print(f"Toll & Parking: KIAL Toll: Rs 115.00 | T2 Parking: Rs 150.00 (Pure Agent Reimbursable)")
    
    print("\n" + "-"*70)
    print("  1. CUSTOMER RECEIVABLE (TAX INVOICE BREAKDOWN)")
    print("-"*70)
    for line in rec["lines"]:
        qty = line.get("quantity", 1)
        unit = line.get("unit_paise", line["amount_paise"]) / 100
        amt = line["amount_paise"] / 100
        print(f"  * {line['label']:<46} Qty: {qty:>3}  @ Rs {unit:>7.2f} = Rs {amt:>8.2f}")
    
    tax_subtotal = rec.get("taxable_base_paise", rec.get("transport_subtotal_paise", 0)) / 100
    reimbursables = rec.get("reimbursements_paise", 0) / 100
    gst = rec.get("tax_paise", 0) / 100
    grand_total = rec.get("total_fare_paise", 0) / 100

    print(f"  {'-'*66}")
    print(f"  Taxable Services Subtotal:                                   Rs {tax_subtotal:>8.2f}")
    print(f"  Reimbursables (Toll Rs 115 + Parking Rs 150 - Tax Exempt):   Rs {reimbursables:>8.2f}")
    print(f"  GST (CGST 2.5% + SGST 2.5% on Rs {tax_subtotal:.2f}):                     Rs {gst:>8.2f}")
    print(f"  {'='*66}")
    print(f"  TOTAL INVOICE AMOUNT (RECEIVABLE):                           Rs {grand_total:>8.2f}")

    print("\n" + "-"*70)
    print("  2. SUPPLIER / DRIVER PAYABLE (DISBURSEMENT SLIP)")
    print("-"*70)
    for line in pay["lines"]:
        qty = line.get("quantity", 1)
        unit = line.get("unit_paise", line["amount_paise"]) / 100
        amt = line["amount_paise"] / 100
        print(f"  * {line['label']:<46} Qty: {qty:>3}  @ Rs {unit:>7.2f} = Rs {amt:>8.2f}")
    
    pay_subtotal = pay.get("taxable_base_paise", pay.get("transport_subtotal_paise", 0)) / 100
    pay_reimb = pay.get("reimbursements_paise", 0) / 100
    pay_tax = pay.get("tax_paise", 0) / 100
    pay_total = pay.get("total_fare_paise", 0) / 100

    print(f"  {'-'*66}")
    print(f"  Base Transport Subtotal:                                     Rs {pay_subtotal:>8.2f}")
    print(f"  Reimbursement Pass-through (Toll + Parking):                 Rs {pay_reimb:>8.2f}")
    print(f"  Supplier Tax (5% RCM/GST):                                   Rs {pay_tax:>8.2f}")
    print(f"  {'='*66}")
    print(f"  TOTAL SUPPLIER PAYABLE:                                      Rs {pay_total:>8.2f}")

    print("\n" + "-"*70)
    print("  3. DUTY-LEVEL P&L (GROSS PROFIT & MARGIN %)")
    print("-"*70)
    rev_net = pnl["net_revenue_paise"] / 100
    cost_net = pnl["net_cost_paise"] / 100
    gp = pnl["gross_profit_paise"] / 100
    margin = pnl["gross_margin_percentage"]

    print(f"  Customer Net Billable (Excl GST):                            Rs {rev_net:>8.2f}")
    print(f"  Supplier Net Cost (Excl GST):                                Rs {cost_net:>8.2f}")
    print(f"  Duty Gross Profit:                                           Rs {gp:>8.2f}")
    print(f"  Duty Gross Margin %:                                         {margin:>7.2f}%")
    print(f"  Profitability Status:                                        {'PROFITABLE' if pnl['is_profitable'] else 'LOSS'}")
    print("="*70 + "\n")

    assert rec["total_fare_paise"] == 1840_00, f"Expected 184000 paise total, got {rec['total_fare_paise']}"
    assert pay["total_fare_paise"] > 0, "Payable should be greater than zero"
    assert pnl["gross_profit_paise"] == 325_00, f"Expected 32500 paise gross profit, got {pnl['gross_profit_paise']}"

    # Math validations:
    # Customer: Base 1400.00 + 30 mins excess waiting (30 * 200/60 = 100.00) = 1500.00
    # Toll 115.00 + Parking 150.00 = 265.00
    # Taxable = 1500.00. GST 5% = 75.00. Total = 1500 + 265 + 75 = 1840.00
    assert rec["taxable_base_paise"] == 1500_00, f"Expected 150000 paise taxable base, got {rec['taxable_base_paise']}"
    assert rec["reimbursements_paise"] == 265_00, f"Expected 26500 paise reimbursements, got {rec['reimbursements_paise']}"
    assert rec["tax_paise"] == 75_00, f"Expected 7500 paise GST, got {rec['tax_paise']}"
    assert rec["total_fare_paise"] == 1840_00, f"Expected 184000 paise total, got {rec['total_fare_paise']}"

    assert pay["taxable_base_paise"] == 1175_00, f"Expected 117500 paise, got {pay['taxable_base_paise']}"
    assert pay["reimbursements_paise"] == 265_00, f"Expected 26500 paise, got {pay['reimbursements_paise']}"
    assert pnl["gross_profit_paise"] == 325_00, f"Expected 32500 paise gross profit, got {pnl['gross_profit_paise']}"
    assert pnl["gross_margin_percentage"] == 18.41, f"Expected 18.41% gross margin, got {pnl['gross_margin_percentage']}%"

    print("[OK] ALL AIRPORT FARE ENGINE ASSERTIONS MATCH EXACT DETERMINISTIC RESULTS!")

if __name__ == "__main__":
    main()
