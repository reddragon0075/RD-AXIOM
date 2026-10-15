#!/usr/bin/env python3
"""End-to-end smoke test for Fare Engine APIs and Duty Recalculation."""

import time
from backend_smoke_test import call, expect, make_client

BASE = "http://127.0.0.1:4173"

def main():
    jar, client = make_client(BASE)
    
    # 1. Sign up a fresh vendor
    email = f"fare_tester_{int(time.time())}@axiom.in"
    status, signup_res = call(client, BASE, "POST", "/api/auth/signup", {
        "email": email,
        "password": "Password123!",
        "role": "vendor",
        "full_name": "Fare Tester",
        "organization_name": "Axiom Rental Test Corp",
        "city": "Mumbai",
        "timezone": "Asia/Kolkata"
    })
    expect(status == 201 and signup_res.get("ok"), "Vendor account created for fare smoke test")

    # 2. Test GET /api/fare/presets
    status, presets_res = call(client, BASE, "GET", "/api/fare/presets")
    expect(status == 200 and presets_res.get("ok"), "Fare presets retrieved")
    expect(presets_res.get("engine_version") == "2026.10.1", "Fare engine version is 2026.10.1")

    # 3. Test GET /api/fare/rules
    status, rules_res = call(client, BASE, "GET", "/api/fare/rules")
    expect(status == 200 and len(rules_res.get("items", [])) >= 8, f"Tariff rules seeded (count: {len(rules_res.get('items', []))})")

    # 4. Test POST /api/fare/calculate with auto-slab switching
    calc_payload = {
        "telemetry": {
            "billing_mode": "P2P",
            "reporting_km": 1000,
            "releasing_km": 1072, # 72km
            "duration_minutes": 465, # 7h 45m
            "toll_paise": 120_00
        },
        "profile": {
            "fare_mode": "local",
            "package_name": "4Hr 40Km",
            "package_minutes": 240,
            "included_km": 40,
            "base_paise": 1400_00,
            "extra_km_paise": 18_00,
            "extra_hour_paise": 200_00,
            "grace_period_minutes": 15,
            "slab_switch_mode": "UPGRADE_ONLY",
            "tax_rate_bps": 500
        },
        "candidate_slabs": [
            {
                "id": "slab-4x40",
                "package_name": "4Hr 40Km",
                "package_minutes": 240,
                "included_km": 40,
                "base_paise": 1400_00,
                "extra_km_paise": 18_00,
                "extra_hour_paise": 200_00,
            },
            {
                "id": "slab-8x80",
                "package_name": "8Hr 80Km",
                "package_minutes": 480,
                "included_km": 80,
                "base_paise": 2400_00,
                "extra_km_paise": 18_00,
                "extra_hour_paise": 200_00,
            }
        ]
    }
    status, calc_res = call(client, BASE, "POST", "/api/fare/calculate", calc_payload)
    expect(status == 200 and calc_res.get("ok"), "Fare calculation returned 200 OK")
    opt = calc_res["fare"]["explanation"]["slab_optimization"]
    expect(opt["was_switched"] is True, "Auto slab optimization switched to 8Hr 80Km")
    expect(opt["selected_rule_id"] == "slab-8x80", "Winning slab is slab-8x80")
    expect(opt["savings_paise"] == 376_00, "Customer savings computed accurately (Rs 376)")

    # 5. Test POST /api/fare/settlement (Dual-Ledger Customer vs Supplier P&L)
    settle_payload = {
        "telemetry": {
            "billing_mode": "P2P",
            "reporting_km": 1000,
            "releasing_km": 1080, # 80km
            "duration_minutes": 480, # 8h
            "toll_paise": 100_00
        },
        "receivable_profile": {
            "fare_mode": "local",
            "package_name": "8Hr 80Km",
            "package_minutes": 480,
            "included_km": 80,
            "base_paise": 2400_00,
            "extra_km_paise": 18_00,
            "extra_hour_paise": 200_00,
            "tax_rate_bps": 500
        },
        "payable_profile": {
            "fare_mode": "local",
            "package_name": "8Hr 80Km",
            "package_minutes": 480,
            "included_km": 80,
            "base_paise": 1800_00,
            "extra_km_paise": 14_00,
            "extra_hour_paise": 150_00,
            "tax_rate_bps": 500
        }
    }
    status, settle_res = call(client, BASE, "POST", "/api/fare/settlement", settle_payload)
    expect(status == 200 and settle_res.get("ok"), "Dual ledger settlement returned 200 OK")
    pnl = settle_res["settlement"]["settlement_pnl"]
    expect(pnl["gross_profit_paise"] == 600_00, f"Gross profit is Rs 600 (computed {pnl['gross_profit_paise']})")
    expect(pnl["gross_margin_percentage"] == 24.0, f"Gross margin is 24% (computed {pnl['gross_margin_percentage']}%)")

    # 6. Test Duty Fare Recalculation on an actual duty
    status, cust_res = call(client, BASE, "POST", "/api/customers", {
        "name": "Infosys Corporate",
        "email": "travel@infosys.com",
        "phone": "+91 99999 88888",
        "gstin": "27AAACI1234A1Z5"
    })
    print("Customer response:", status, cust_res)
    expect(status in (200, 201) and "item" in cust_res, "Customer created")
    cust_id = cust_res["item"]["id"]

    status, book_res = call(client, BASE, "POST", "/api/bookings", {
        "customer_id": cust_id,
        "passenger_name": "Narayan Murthy",
        "duty_type": "local",
        "scheduled_at": "2026-10-15T10:00:00Z"
    })
    print("Booking response:", status, book_res)
    expect(status in (200, 201) and "item" in book_res, "Booking created")
    book_id = book_res["item"]["id"]

    status, duty_res = call(client, BASE, "POST", "/api/duties", {
        "booking_id": book_id,
        "reporting_at": "2026-10-15T09:00:00Z",
        "status": "completed",
        "start_odometer": 20000,
        "end_odometer": 20085
    })
    print("Duty response:", status, duty_res)
    expect(status in (200, 201) and "item" in duty_res, "Duty created")
    duty_id = duty_res["item"]["id"]

    status, recalc_res = call(client, BASE, "POST", f"/api/fare/duties/{duty_id}/recalculate", {
        "reporting_km": 20000,
        "releasing_km": 20085,
        "duration_minutes": 470,
        "toll_paise": 150_00,
        "parking_paise": 50_00
    })
    expect(status == 200 and recalc_res.get("ok"), "Duty fare recalculated successfully")
    duty_snap = recalc_res["item"]["calculation_snapshot"]
    expect(duty_snap["fare_engine_managed"] is True, "Duty snapshot marked fare_engine_managed")
    expect(duty_snap["total_paise"] > 0, f"Recalculated total paise: {duty_snap['total_paise']}")
    pnl_out = duty_snap["settlement"]["settlement_pnl"]
    expect(pnl_out["is_profitable"] is True, f"Duty is profitable: margin {pnl_out['gross_margin_percentage']}%")

    print("\nALL FARE ENGINE ENDPOINTS & RECALCULATIONS PASSED 100%!")

if __name__ == "__main__":
    main()
