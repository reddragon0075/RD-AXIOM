#!/usr/bin/env python3
"""Insert 1 Outstation Trip and 1 4Hr/40Km Local Trip and verify Fare Engine pricing."""

import time
from backend_smoke_test import call, expect, make_client

BASE = "http://127.0.0.1:4173"

def main():
    jar, client = make_client(BASE)
    
    # 1. Sign up / login tenant
    email = f"trip_ops_{int(time.time())}@axiom.in"
    status, signup_res = call(client, BASE, "POST", "/api/auth/signup", {
        "email": email,
        "password": "Password123!",
        "role": "vendor",
        "full_name": "Karnataka Fleet Operations",
        "organization_name": "Axiom Rental Hub",
        "city": "Bengaluru",
        "timezone": "Asia/Kolkata"
    })
    expect(status == 201 and signup_res.get("ok"), "Tenant signed up")

    # 2. Setup Corporate Customers
    status, cust_wipro = call(client, BASE, "POST", "/api/customers", {
        "name": "Wipro Technologies",
        "email": "travel@wipro.com",
        "phone": "+91 80 2844 0011",
        "gstin": "29AAACW1234A1Z1"
    })
    wipro_id = cust_wipro["item"]["id"]

    status, cust_infy = call(client, BASE, "POST", "/api/customers", {
        "name": "Infosys Corporate Travel",
        "email": "travel@infosys.com",
        "phone": "+91 80 2852 0261",
        "gstin": "29AAACI1234A1Z5"
    })
    infy_id = cust_infy["item"]["id"]

    # 3. Setup Custom Tariff Rules
    # Tier 1: Wipro Contracted Outstation SUV Rate Card
    call(client, BASE, "POST", "/api/fare/rules", {
        "entity_type": "CLIENT",
        "entity_id": wipro_id,
        "city_id": "Bengaluru",
        "vehicle_group_id": "SUV",
        "fare_mode": "outstation",
        "package_name": "Wipro Corporate Outstation SUV (300km/day min)",
        "daily_min_km": 300,
        "extra_km_paise": 24_00,             # Rs 24.00 / KM
        "driver_allowance_day_paise": 500_00, # Rs 500.00 / day batta
        "driver_allowance_night_paise": 400_00, # Rs 400.00 / night halt
        "tax_rate_bps": 500,                 # 5% GST
        "effective_from": "2026-10-01",
    })

    # Tier 3: City Default Outstation SUV Driver Payout Rate Card
    call(client, BASE, "POST", "/api/fare/rules", {
        "entity_type": "SUPPLIER",
        "city_id": "Bengaluru",
        "vehicle_group_id": "SUV",
        "fare_mode": "outstation",
        "package_name": "City Supplier Outstation SUV (300km/day min)",
        "daily_min_km": 300,
        "extra_km_paise": 20_00,             # Rs 20.00 / KM
        "driver_allowance_day_paise": 400_00, # Rs 400.00 / day batta
        "driver_allowance_night_paise": 300_00, # Rs 300.00 / night halt
        "tax_rate_bps": 500,                 # 5% GST
        "effective_from": "2026-10-01",
    })

    # Tier 1: Infosys Contracted Local Sedan Rate Card
    call(client, BASE, "POST", "/api/fare/rules", {
        "entity_type": "CLIENT",
        "entity_id": infy_id,
        "city_id": "Bengaluru",
        "vehicle_group_id": "SEDAN",
        "fare_mode": "local",
        "package_name": "4Hr 40Km",
        "package_minutes": 240,
        "included_km": 40,
        "base_paise": 1400_00,               # Rs 1,400.00
        "extra_km_paise": 18_00,             # Rs 18.00 / KM
        "extra_hour_paise": 200_00,          # Rs 200.00 / hr
        "grace_period_minutes": 15,          # 15 min grace window
        "tax_rate_bps": 500,                 # 5% GST
        "effective_from": "2026-10-01",
    })

    # Tier 3: City Default Local Sedan Supplier Rate Card
    call(client, BASE, "POST", "/api/fare/rules", {
        "entity_type": "SUPPLIER",
        "city_id": "Bengaluru",
        "vehicle_group_id": "SEDAN",
        "fare_mode": "local",
        "package_name": "4Hr 40Km",
        "package_minutes": 240,
        "included_km": 40,
        "base_paise": 1100_00,               # Rs 1,100.00
        "extra_km_paise": 15_00,             # Rs 15.00 / KM
        "extra_hour_paise": 150_00,          # Rs 150.00 / hr
        "grace_period_minutes": 15,
        "tax_rate_bps": 500,
        "effective_from": "2026-10-01",
    })

    print("\n" + "="*75)
    print("                     TRIP 1: OUTSTATION DUTY")
    print("="*75)
    # Booking: 2-Day Bengaluru -> Mysuru -> Coorg roundtrip
    status, book_out = call(client, BASE, "POST", "/api/bookings", {
        "customer_id": wipro_id,
        "passenger_name": "Rajesh Nambiar (Client Executive)",
        "passenger_phone": "+91 98450 99887",
        "duty_type": "outstation",
        "scheduled_at": "2026-10-14T06:00:00Z",
        "pickup": {"label": "Wipro Sarjapur Campus, Bengaluru", "city": "Bengaluru"},
        "dropoff": {"label": "Mysuru & Madikeri (Coorg) Tour", "city": "Bengaluru"},
        "vehicle_group_id": "SUV",
    })
    out_book_id = book_out["item"]["id"]
    out_book_ref = book_out["item"]["booking_reference"]

    status, duty_out = call(client, BASE, "POST", "/api/duties", {
        "booking_id": out_book_id,
        "reporting_at": "2026-10-14T05:45:00Z",
        "status": "completed",
        "start_odometer": 62000,
        "end_odometer": 62560,               # 560 KM run
    })
    out_duty_id = duty_out["item"]["id"]

    # Telemetry:
    # 2 days trip, actual run 560 KM
    # Minimum guarantee is 300 KM/day * 2 days = 600 KM!
    # So customer is billed on 600 KM guaranteed!
    # 1 night halt, Rs 360 Expressway Toll, Rs 150 Parking
    out_telemetry = {
        "duty_id": out_duty_id,
        "fare_mode": "outstation",
        "vehicle_group": "SUV",
        "billing_mode": "P2P",
        "reporting_km": 62000.0,
        "releasing_km": 62560.0,
        "duration_minutes": 2160,            # 36 hours
        "calendar_days": 2,                  # 2 Calendar Days
        "night_count": 1,                    # 1 Night Halt
        "toll_paise": 360_00,                # Rs 360 Tolls
        "parking_paise": 150_00,             # Rs 150 Parking
        "reimbursements_taxable": False,
        "is_customer_interstate": False,
        "city_id": "Bengaluru"
    }

    status, recalc_out = call(client, BASE, "POST", f"/api/fare/duties/{out_duty_id}/recalculate", out_telemetry)
    expect(status == 200 and recalc_out.get("ok"), "Outstation fare recalculated")

    snap_out = recalc_out["item"]["calculation_snapshot"]
    settle_out = snap_out["settlement"]
    rec_out = settle_out["receivable"]
    pay_out = settle_out["payable"]
    pnl_out = settle_out["settlement_pnl"]

    print(f"Booking Ref:     {out_book_ref}")
    print(f"Duty ID:         {out_duty_id}")
    print(f"Passenger:       Rajesh Nambiar (Client Executive)")
    print(f"Corporate:       Wipro Technologies")
    print(f"Service Mode:    OUTSTATION (2 Days, 1 Night Halt)")
    print(f"Route:           Bengaluru -> Mysuru -> Coorg -> Bengaluru")
    print(f"Vehicle:         SUV (Innova Crysta)")
    print(f"Actual Distance: 560 KM | Guaranteed Chargeable: 600 KM (2 Days x 300 KM/day min)")
    print(f"Allowances:      2 Days Batta + 1 Night Halt")
    print(f"Disbursements:   Tolls: Rs 360.00 | Parking: Rs 150.00 (Pass-through)")

    print("\n  [A] CUSTOMER RECEIVABLE (INVOICE)")
    for line in rec_out["lines"]:
        qty = line.get("quantity", 1)
        unit = line.get("unit_paise", line["amount_paise"]) / 100
        amt = line["amount_paise"] / 100
        lbl = line['label'].replace('₹', 'Rs ')
        print(f"    * {lbl:<48} Qty: {qty:>3}  @ Rs {unit:>7.2f} = Rs {amt:>8.2f}")
    
    tax_base_out = rec_out["taxable_base_paise"] / 100
    reimb_out = rec_out["reimbursements_paise"] / 100
    gst_out = rec_out["tax_paise"] / 100
    total_out = rec_out["total_fare_paise"] / 100

    print(f"    {'-'*68}")
    print(f"    Taxable Transport Subtotal:                                 Rs {tax_base_out:>8.2f}")
    print(f"    Tax-Exempt Reimbursables (Tolls + Parking):                 Rs {reimb_out:>8.2f}")
    print(f"    GST (CGST 2.5% + SGST 2.5% on Rs {tax_base_out:.2f}):                       Rs {gst_out:>8.2f}")
    print(f"    {'='*68}")
    print(f"    TOTAL INVOICE (RECEIVABLE):                                 Rs {total_out:>8.2f}")

    print("\n  [B] SUPPLIER / DRIVER PAYABLE (PAYOUT SLIP)")
    for line in pay_out["lines"]:
        qty = line.get("quantity", 1)
        unit = line.get("unit_paise", line["amount_paise"]) / 100
        amt = line["amount_paise"] / 100
        lbl = line['label'].replace('₹', 'Rs ')
        print(f"    * {lbl:<48} Qty: {qty:>3}  @ Rs {unit:>7.2f} = Rs {amt:>8.2f}")
    
    pay_base_out = pay_out["taxable_base_paise"] / 100
    pay_reimb_out = pay_out["reimbursements_paise"] / 100
    pay_tax_out = pay_out["tax_paise"] / 100
    pay_total_out = pay_out["total_fare_paise"] / 100

    print(f"    {'-'*68}")
    print(f"    Supplier Base Transport Subtotal:                           Rs {pay_base_out:>8.2f}")
    print(f"    Reimbursement Pass-through (Tolls + Parking):               Rs {pay_reimb_out:>8.2f}")
    print(f"    Supplier Tax (5% RCM/GST):                                  Rs {pay_tax_out:>8.2f}")
    print(f"    {'='*68}")
    print(f"    TOTAL SUPPLIER PAYABLE:                                     Rs {pay_total_out:>8.2f}")

    print("\n  [C] DUTY PROFITABILITY (P&L)")
    rev_net_out = pnl_out["net_revenue_paise"] / 100
    cost_net_out = pnl_out["net_cost_paise"] / 100
    gp_out = pnl_out["gross_profit_paise"] / 100
    margin_out = pnl_out["gross_margin_percentage"]

    print(f"    Customer Net Billing (Excl GST):                            Rs {rev_net_out:>8.2f}")
    print(f"    Supplier Net Cost (Excl GST):                               Rs {cost_net_out:>8.2f}")
    print(f"    Portal Owner Gross Profit:                                  Rs {gp_out:>8.2f}")
    print(f"    Gross Profit Margin %:                                      {margin_out:>7.2f}%")


    print("\n" + "="*75)
    print("                     TRIP 2: LOCAL 4HR / 40KM DUTY")
    print("="*75)
    # Booking: Local City Run for Infosys
    status, book_loc = call(client, BASE, "POST", "/api/bookings", {
        "customer_id": infy_id,
        "passenger_name": "Sudha Rao (Delivery Manager)",
        "passenger_phone": "+91 99001 23456",
        "duty_type": "local",
        "scheduled_at": "2026-10-15T09:00:00Z",
        "pickup": {"label": "Infosys Electronic City, Gate 1", "city": "Bengaluru"},
        "dropoff": {"label": "Whitefield Export Promotion Industrial Park", "city": "Bengaluru"},
        "vehicle_group_id": "SEDAN",
    })
    loc_book_id = book_loc["item"]["id"]
    loc_book_ref = book_loc["item"]["booking_reference"]

    status, duty_loc = call(client, BASE, "POST", "/api/duties", {
        "booking_id": loc_book_id,
        "reporting_at": "2026-10-15T08:50:00Z",
        "status": "completed",
        "start_odometer": 10000,
        "end_odometer": 10046,               # 46 KM run (6 KM extra)
    })
    loc_duty_id = duty_loc["item"]["id"]

    # Telemetry:
    # 46 KM run -> 6 KM extra over 40 KM included
    # Duration: 245 mins (4 hrs 5 mins) -> within 15 min grace period over 240 mins (0 extra hour charge!)
    # Toll: Rs 70.00 NICE road toll
    # Parking: Rs 50.00
    loc_telemetry = {
        "duty_id": loc_duty_id,
        "fare_mode": "local",
        "vehicle_group": "SEDAN",
        "billing_mode": "P2P",
        "reporting_km": 10000.0,
        "releasing_km": 10046.0,
        "duration_minutes": 245,             # 4 hrs 5 mins (under 15 min grace)
        "toll_paise": 70_00,                 # Rs 70 NICE road toll
        "parking_paise": 50_00,              # Rs 50 parking
        "reimbursements_taxable": False,
        "is_customer_interstate": False,
        "city_id": "Bengaluru"
    }

    status, recalc_loc = call(client, BASE, "POST", f"/api/fare/duties/{loc_duty_id}/recalculate", loc_telemetry)
    expect(status == 200 and recalc_loc.get("ok"), "Local 4Hr/40Km fare recalculated")

    snap_loc = recalc_loc["item"]["calculation_snapshot"]
    settle_loc = snap_loc["settlement"]
    rec_loc = settle_loc["receivable"]
    pay_loc = settle_loc["payable"]
    pnl_loc = settle_loc["settlement_pnl"]

    print(f"Booking Ref:     {loc_book_ref}")
    print(f"Duty ID:         {loc_duty_id}")
    print(f"Passenger:       Sudha Rao (Delivery Manager)")
    print(f"Corporate:       Infosys Corporate Travel")
    print(f"Service Mode:    LOCAL PACKAGE (Booked: 4Hr 40Km)")
    print(f"Route:           Electronic City <-> Whitefield")
    print(f"Vehicle:         SEDAN (Dzire/Etios)")
    print(f"Actual Distance: 46.0 KM (40 KM included + 6.0 KM extra @ Rs 18.00/km)")
    print(f"Duty Duration:   245 mins (4h 5m -> within 15-min grace period: 0 extra time charge)")
    print(f"Disbursements:   NICE Road Toll: Rs 70.00 | Parking: Rs 50.00 (Pass-through)")

    print("\n  [A] CUSTOMER RECEIVABLE (INVOICE)")
    for line in rec_loc["lines"]:
        qty = line.get("quantity", 1)
        unit = line.get("unit_paise", line["amount_paise"]) / 100
        amt = line["amount_paise"] / 100
        lbl = line['label'].replace('₹', 'Rs ')
        print(f"    * {lbl:<48} Qty: {qty:>3}  @ Rs {unit:>7.2f} = Rs {amt:>8.2f}")
    
    tax_base_loc = rec_loc["taxable_base_paise"] / 100
    reimb_loc = rec_loc["reimbursements_paise"] / 100
    gst_loc = rec_loc["tax_paise"] / 100
    total_loc = rec_loc["total_fare_paise"] / 100

    print(f"    {'-'*68}")
    print(f"    Taxable Transport Subtotal:                                 Rs {tax_base_loc:>8.2f}")
    print(f"    Tax-Exempt Reimbursables (Toll + Parking):                  Rs {reimb_loc:>8.2f}")
    print(f"    GST (CGST 2.5% + SGST 2.5% on Rs {tax_base_loc:.2f}):                       Rs {gst_loc:>8.2f}")
    print(f"    {'='*68}")
    print(f"    TOTAL INVOICE (RECEIVABLE):                                 Rs {total_loc:>8.2f}")

    print("\n  [B] SUPPLIER / DRIVER PAYABLE (PAYOUT SLIP)")
    for line in pay_loc["lines"]:
        qty = line.get("quantity", 1)
        unit = line.get("unit_paise", line["amount_paise"]) / 100
        amt = line["amount_paise"] / 100
        lbl = line['label'].replace('₹', 'Rs ')
        print(f"    * {lbl:<48} Qty: {qty:>3}  @ Rs {unit:>7.2f} = Rs {amt:>8.2f}")
    
    pay_base_loc = pay_loc["taxable_base_paise"] / 100
    pay_reimb_loc = pay_loc["reimbursements_paise"] / 100
    pay_tax_loc = pay_loc["tax_paise"] / 100
    pay_total_loc = pay_loc["total_fare_paise"] / 100

    print(f"    {'-'*68}")
    print(f"    Supplier Base Transport Subtotal:                           Rs {pay_base_loc:>8.2f}")
    print(f"    Reimbursement Pass-through (Toll + Parking):                 Rs {pay_reimb_loc:>8.2f}")
    print(f"    Supplier Tax (5% RCM/GST):                                  Rs {pay_tax_loc:>8.2f}")
    print(f"    {'='*68}")
    print(f"    TOTAL SUPPLIER PAYABLE:                                     Rs {pay_total_loc:>8.2f}")

    print("\n  [C] DUTY PROFITABILITY (P&L)")
    rev_net_loc = pnl_loc["net_revenue_paise"] / 100
    cost_net_loc = pnl_loc["net_cost_paise"] / 100
    gp_loc = pnl_loc["gross_profit_paise"] / 100
    margin_loc = pnl_loc["gross_margin_percentage"]

    print(f"    Customer Net Billing (Excl GST):                            Rs {rev_net_loc:>8.2f}")
    print(f"    Supplier Net Cost (Excl GST):                               Rs {cost_net_loc:>8.2f}")
    print(f"    Portal Owner Gross Profit:                                  Rs {gp_loc:>8.2f}")
    print(f"    Gross Profit Margin %:                                      {margin_loc:>7.2f}%")
    print("="*75 + "\n")

    # Math Validations:
    # Outstation:
    # Customer: 600 KM @ Rs 24.00 = 14400.00 + 2 days batta @ 400 = 800.00 + 1 night = 300.00 -> Base = 15500.00
    # Reimbursables = 360 + 150 = 510.00
    # GST 5% on 15500.00 = 775.00
    # Total = 15500.00 + 510.00 + 775.00 = 16785.00
    assert rec_out["taxable_base_paise"] == 15500_00, f"Expected 1550000 paise base, got {rec_out['taxable_base_paise']}"
    assert rec_out["total_fare_paise"] == 16785_00, f"Expected 1678500 paise total, got {rec_out['total_fare_paise']}"
    
    # Supplier Outstation: 600 KM @ Rs 20.00 = 12000.00 + 2 days batta @ 400 = 800.00 + 1 night = 300.00 -> Base = 13100.00
    # Reimbursables = 510.00
    # Gross Profit = 15500.00 - 13100.00 = 2400.00!
    assert pnl_out["gross_profit_paise"] == 2400_00, f"Expected 240000 paise gross profit, got {pnl_out['gross_profit_paise']}"
    assert pnl_out["gross_margin_percentage"] == 14.99, f"Expected 14.99% margin, got {pnl_out['gross_margin_percentage']}%"

    # Local 4Hr 40Km:
    # Customer: Base 1400.00 + 6 KM extra @ Rs 18.00 = 108.00 -> Base = 1508.00
    # Reimbursables = 70 + 50 = 120.00
    # GST 5% on 1508.00 = 75.40 -> 75.00
    # Total = 1508.00 + 120.00 + 75.40 = 1703.40
    assert rec_loc["taxable_base_paise"] == 1508_00, f"Expected 150800 paise base, got {rec_loc['taxable_base_paise']}"
    assert rec_loc["reimbursements_paise"] == 120_00, f"Expected 12000 paise reimbursables, got {rec_loc['reimbursements_paise']}"

    # Supplier Local: Base 1100.00 + 6 KM extra @ Rs 15.00 = 90.00 -> Base = 1190.00
    # Gross Profit = 1508.00 - 1190.00 = 318.00!
    assert pnl_loc["gross_profit_paise"] == 318_00, f"Expected 31800 paise gross profit, got {pnl_loc['gross_profit_paise']}"
    assert pnl_loc["gross_margin_percentage"] == 19.53, f"Expected 19.53% margin, got {pnl_loc['gross_margin_percentage']}%"

    print("[OK] ALL OUTSTATION AND 4HR/40KM FARE ENGINE ASSERTIONS MATCH 100%!")

if __name__ == "__main__":
    main()
