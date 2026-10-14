#!/usr/bin/env python3
"""Seed comprehensive operational data for tenant organizations (e.g. org_axiom_logistics)."""

import json
import sqlite3
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "axiom_fleet.sqlite3"

def now_iso(offset_hours: float = 0, offset_days: float = 0) -> str:
    target = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=offset_days, hours=offset_hours)
    return target.replace(microsecond=0).isoformat().replace("+00:00", "Z")

def seed_organization(conn: sqlite3.Connection, org_id: str, creator_id: str = "usr_abhijith_test"):
    print(f"Seeding tenant data for org: {org_id} ...")
    prefix = f"{org_id[:8]}"
    
    # 1. Customers
    customers = [
        (f"cust_{prefix}_northstar", "NorthStar Technologies", "travel@northstar.example", "+91 98450 11001", "29AABCN1234F1Z1"),
        (f"cust_{prefix}_infosys", "Infosys BPM Ltd", "transport@infosys.example", "+91 98450 22002", "29AAACI4567G1Z2"),
        (f"cust_{prefix}_wipro", "Wipro Digital Enterprises", "logistics@wipro.example", "+91 98450 33003", "29AAACW7890H1Z3"),
        (f"cust_{prefix}_tcs", "Tata Consultancy Services", "travel.blr@tcs.example", "+91 98450 44004", "29AAACT1234J1Z4"),
        (f"cust_{prefix}_gs", "Goldman Sachs Services", "gs.transport@gs.example", "+91 98450 55005", "29AABCG5678K1Z5"),
    ]
    for cid, name, email, phone, gstin in customers:
        conn.execute("""
            INSERT OR REPLACE INTO domain_customers(id, organization_id, name, email, phone, gstin, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
        """, (cid, org_id, name, email, phone, gstin, now_iso(-24), now_iso()))

    # 2. Branches
    branches = [
        (f"branch_{prefix}_blr_wf", "BLR-WF", "Whitefield Operations Hub", "Bengaluru", json.dumps({"label": "ITPB Main Road, Whitefield, Bengaluru"})),
        (f"branch_{prefix}_blr_ec", "BLR-EC", "Electronic City Dispatch Hub", "Bengaluru", json.dumps({"label": "Phase 1, Electronic City, Bengaluru"})),
        (f"branch_{prefix}_blr_air", "BLR-AIR", "Kempegowda Airport Desk", "Bengaluru", json.dumps({"label": "T2 Arrival Hall, KIAL, Devanahalli"})),
        (f"branch_{prefix}_bom_bkc", "BOM-BKC", "BKC Financial Centre", "Mumbai", json.dumps({"label": "G Block, BKC, Bandra East, Mumbai"})),
    ]
    for bid, code, name, city, addr in branches:
        conn.execute("""
            INSERT OR REPLACE INTO domain_branches(id, organization_id, code, name, city, address_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
        """, (bid, org_id, code, name, city, addr, now_iso(-48), now_iso()))

    # 3. Suppliers
    suppliers = [
        (f"supp_{prefix}_apex", "Apex Mobility Solutions", "company", "dispatch@apexmobility.example", "+91 98111 22233", "29AAACA1111A1Z1", json.dumps(["Bengaluru", "Mysuru"])),
        (f"supp_{prefix}_royal", "Royal Cabs & Logistics", "company", "partner@royalcabs.example", "+91 98222 33344", "29AAACR2222B1Z2", json.dumps(["Bengaluru"])),
        (f"supp_{prefix}_city", "CityFleet Express Partners", "network_partner", "ops@cityfleet.example", "+91 98333 44455", "29AAACC3333C1Z3", json.dumps(["Bengaluru", "Chennai"])),
        (f"supp_{prefix}_kiran", "Kiran Travels (DCO Network)", "individual", "kiran@kirantravels.example", "+91 98444 55566", "29AAACK4444D1Z4", json.dumps(["Bengaluru"])),
    ]
    for sid, name, stype, email, phone, gstin, cities in suppliers:
        conn.execute("""
            INSERT OR REPLACE INTO domain_suppliers(id, organization_id, name, supplier_type, email, phone, gstin, cities_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
        """, (sid, org_id, name, stype, email, phone, gstin, cities, now_iso(-72), now_iso()))

    # 4. Vehicles
    vehicles = [
        (f"veh_{prefix}_dzire1", "KA 01 EQ 1001", "sedan", "Sedan", "Maruti Suzuki Dzire", "Maruti Suzuki", "Dzire", "Bengaluru", "on_duty", "petrol", 4, 0),
        (f"veh_{prefix}_dzire2", "KA 01 EQ 1002", "sedan", "Sedan", "Maruti Suzuki Dzire", "Maruti Suzuki", "Dzire", "Bengaluru", "available", "petrol", 4, 0),
        (f"veh_{prefix}_innova1", "KA 03 MN 2045", "suv", "Premium SUV", "Toyota Innova Crysta", "Toyota", "Innova Crysta", "Bengaluru", "on_duty", "diesel", 7, 0),
        (f"veh_{prefix}_etios1", "KA 04 JK 3344", "sedan", "Sedan", "Toyota Etios", "Toyota", "Etios", "Bengaluru", "available", "petrol", 4, 0),
        (f"veh_{prefix}_city1", "KA 51 MC 4412", "sedan", "Executive Sedan", "Honda City", "Honda", "City", "Bengaluru", "available", "petrol", 4, 0),
        (f"veh_{prefix}_aura1", "KA 05 AB 7788", "sedan", "Sedan", "Hyundai Aura", "Hyundai", "Aura", "Bengaluru", "available", "cng", 4, 0),
        (f"veh_{prefix}_ertiga1", "KA 02 MN 8899", "suv", "SUV", "Maruti Suzuki Ertiga", "Maruti Suzuki", "Ertiga", "Bengaluru", "on_duty", "petrol", 6, 0),
        (f"veh_{prefix}_tigor_ev", "KA 01 EV 5500", "sedan", "Executive Sedan", "Tata Tigor EV", "Tata Motors", "Tigor EV", "Bengaluru", "available", "electric", 4, 1),
    ]
    for vid, reg, vtype, vgrp, make_model, mfr, mdl, city, status, fuel, seat, ev_elig in vehicles:
        conn.execute("""
            INSERT OR REPLACE INTO domain_vehicles(
                id, organization_id, registration_number, vehicle_type, vehicle_group,
                make_model, manufacturer, model, city, status, fuel_type, seating_capacity,
                ev_eligible, ownership_type, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'owned', ?, ?)
        """, (vid, org_id, reg, vtype, vgrp, make_model, mfr, mdl, city, status, fuel, seat, ev_elig, now_iso(-96), now_iso()))

    # 5. Drivers
    drivers = [
        (f"drv_{prefix}_ramesh", "Ramesh Kumar", "+91 98450 33445", "DL-KA01-2020-001", "Bengaluru", "on_duty", "own"),
        (f"drv_{prefix}_imran", "Mohammed Imran", "+91 98450 12345", "DL-KA01-2023-002", "Bengaluru", "on_duty", "own"),
        (f"drv_{prefix}_suresh", "Suresh Patil", "+91 98450 55667", "DL-KA03-2018-003", "Bengaluru", "available", "supplier"),
        (f"drv_{prefix}_anand", "Anand Gowda", "+91 98450 77889", "DL-KA04-2021-004", "Bengaluru", "available", "dco"),
        (f"drv_{prefix}_rajesh", "Rajesh Verma", "+91 98450 99001", "DL-KA05-2022-005", "Bengaluru", "available", "own"),
        (f"drv_{prefix}_deepak", "Deepak Naik", "+91 98450 67890", "DL-KA02-2021-006", "Bengaluru", "available", "supplier"),
        (f"drv_{prefix}_santosh", "Santosh Hegde", "+91 98450 24680", "DL-KA04-2020-007", "Bengaluru", "available", "own"),
    ]
    for did, name, phone, lic, city, status, dtype in drivers:
        conn.execute("""
            INSERT OR REPLACE INTO domain_drivers(
                id, organization_id, full_name, phone, license_number, city, status, driver_type, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (did, org_id, name, phone, lic, city, status, dtype, now_iso(-120), now_iso()))

    # 6. Update existing 5 bookings in this organization
    existing_rows = conn.execute("SELECT id FROM domain_bookings WHERE organization_id = ? ORDER BY created_at ASC LIMIT 5", (org_id,)).fetchall()
    updates = [
        (customers[0][0], "Rohan Sharma", "+91 98801 11222", now_iso(offset_hours=-2), "assigned", vehicles[0][0], vehicles[0][1], drivers[1][0], drivers[1][1], suppliers[0][0], suppliers[0][1]),
        (customers[1][0], "Priya Menon", "+91 98802 22333", now_iso(offset_hours=1), "dispatched", vehicles[2][0], vehicles[2][1], drivers[0][0], drivers[0][1], suppliers[1][0], suppliers[1][1]),
        (customers[2][0], "Abhijith", "+91 98803 33444", now_iso(offset_hours=3), "assigned", vehicles[1][0], vehicles[1][1], drivers[3][0], drivers[3][1], suppliers[3][0], suppliers[3][1]),
        (customers[3][0], "Abhijith", "+91 98803 33444", now_iso(offset_days=1, offset_hours=-4), "allotted", vehicles[4][0], vehicles[4][1], drivers[4][0], drivers[4][1], None, None),
        (customers[4][0], "Tanvi Sengupta", "+91 98804 44555", now_iso(offset_days=1, offset_hours=2), "confirmed", None, None, None, None, None, None),
    ]
    for i, row in enumerate(existing_rows):
        if i < len(updates):
            cid, pname, ph, sched, stat, vid, vnum, did, dname, sid, sname = updates[i]
            conn.execute("""
                UPDATE domain_bookings
                SET customer_id = ?, passenger_name = ?, passenger_phone = ?, scheduled_at = ?, start_at = ?,
                    status = ?, vehicle_id = ?, driver_id = ?, supplier_id = ?,
                    vehicle_number = ?, driver_name = ?, supplier_name = ?, updated_at = ?
                WHERE id = ?
            """, (cid, pname, ph, sched, sched, stat, vid, did, sid, vnum, dname, sname, now_iso(), row["id"]))
            
            # Ensure duty exists
            if vid or did or sid:
                conn.execute("""
                    INSERT OR REPLACE INTO domain_duties(
                        id, organization_id, booking_id, driver_id, vehicle_id, supplier_id,
                        status, reporting_at, started_at, completed_at, calculation_snapshot_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
                """, (f"duty_{row['id'][:16]}", org_id, row["id"], did, vid, sid, stat, sched, sched if stat == "dispatched" else None, None, now_iso(-12), now_iso()))

    # 7. Add 6 new bookings (covering Today, Tomorrow, and Past Completed & Billed)
    new_bookings = [
        (
            f"book_{prefix}_today_airport", f"BK-{prefix[:4].upper()}-101", customers[0][0],
            "Dr. Arvind Swaminathan", "+91 98801 12345", now_iso(offset_hours=2), "airport",
            "Kempegowda Airport T2 Arrivals", "NorthStar Whitefield Campus",
            "requested", None, None, None, None, None, None
        ),
        (
            f"book_{prefix}_today_local", f"BK-{prefix[:4].upper()}-102", customers[1][0],
            "Pooja Hegde", "+91 98802 23456", now_iso(offset_hours=4), "local",
            "Infosys Gate 1, Electronic City", "Multiple client visits / MG Road",
            "requested", None, None, None, None, None, None
        ),
        (
            f"book_{prefix}_tmrw_station", f"BK-{prefix[:4].upper()}-103", customers[2][0],
            "Karthik Narayanan", "+91 98803 34567", now_iso(offset_days=1, offset_hours=-3), "local",
            "Wipro Sarjapur Campus", "Bengaluru City Railway Station",
            "requested", None, None, None, None, None, None
        ),
        (
            f"book_{prefix}_tmrw_outstation", f"BK-{prefix[:4].upper()}-104", customers[3][0],
            "Sunita Roy", "+91 98804 45678", now_iso(offset_days=1, offset_hours=3), "outstation",
            "Manyata Tech Park T-5", "Mysuru Industrial Area, Hebbal",
            "requested", None, None, None, None, None, None
        ),
        (
            f"book_{prefix}_past_comp1", f"BK-{prefix[:4].upper()}-105", customers[0][0],
            "Siddharth Verma", "+91 98805 56789", now_iso(offset_days=-1, offset_hours=-5), "local",
            "MG Road Metro Station", "Whitefield EPIP Zone",
            "completed", vehicles[0][0], vehicles[0][1], drivers[1][0], drivers[1][1], suppliers[0][0], suppliers[0][1]
        ),
        (
            f"book_{prefix}_past_comp2", f"BK-{prefix[:4].upper()}-106", customers[1][0],
            "Deepak Patel", "+91 98806 67890", now_iso(offset_days=-2, offset_hours=-4), "airport",
            "Electronic City Phase 1", "Kempegowda Airport T1",
            "billed", vehicles[2][0], vehicles[2][1], drivers[0][0], drivers[0][1], suppliers[0][0], suppliers[0][1]
        ),
    ]

    for bid, bref, cid, pname, phone, sched, dtype, pickup, drop, status, vid, vnum, did, dname, sid, sname in new_bookings:
        conn.execute("""
            INSERT OR REPLACE INTO domain_bookings(
                id, organization_id, customer_id, booking_reference, status,
                passenger_name, passenger_phone, passenger_email,
                pickup_json, dropoff_json, scheduled_at, start_at, duty_type,
                booking_type, allotment_mode, vehicle_group_code,
                vehicle_id, vehicle_number, driver_id, driver_name, supplier_id, supplier_name,
                created_by, created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?, ?,
                'single', 'owned', 'Sedan',
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?
            )
        """, (
            bid, org_id, cid, bref, status,
            pname, phone, f"{pname.lower().replace(' ', '.')}@example.com",
            json.dumps({"label": pickup}), json.dumps({"label": drop}), sched, sched, dtype,
            vid, vnum, did, dname, sid, sname,
            creator_id, now_iso(-48), now_iso()
        ))

    # 8. Create duties for the new bookings
    snapshot_comp1 = {
        "base_paise": 180000, "distance_km": 42.5, "per_km_paise": 1800,
        "duration_minutes": 180, "per_hour_paise": 2400, "tax_rate_bps": 1800,
        "subtotal_paise": 235000, "tax_paise": 42300, "total_paise": 277300,
        "lines": [
            {"code": "BASE_8H80K", "label": "Local 8H 80K package", "quantity": 1, "unit_paise": 180000, "amount_paise": 180000},
            {"code": "EXTRA_KM", "label": "Extra distance (5.5 km)", "quantity": 5.5, "unit_paise": 10000, "amount_paise": 55000},
            {"code": "GST_18", "label": "GST @ 18%", "quantity": 1, "unit_paise": 42300, "amount_paise": 42300}
        ]
    }
    snapshot_comp2 = {
        "base_paise": 220000, "distance_km": 54.0, "per_km_paise": 2000,
        "duration_minutes": 110, "per_hour_paise": 2400, "tax_rate_bps": 1800,
        "subtotal_paise": 220000, "tax_paise": 39600, "total_paise": 259600,
        "lines": [
            {"code": "AIRPORT_XFER", "label": "Airport transfer package", "quantity": 1, "unit_paise": 220000, "amount_paise": 220000},
            {"code": "GST_18", "label": "GST @ 18%", "quantity": 1, "unit_paise": 39600, "amount_paise": 39600}
        ]
    }

    new_duties = [
        (f"duty_{prefix}_101", new_bookings[0][0], None, None, None, "draft", now_iso(offset_hours=1.75), None, None, "{}"),
        (f"duty_{prefix}_102", new_bookings[1][0], None, None, None, "draft", now_iso(offset_hours=3.75), None, None, "{}"),
        (f"duty_{prefix}_103", new_bookings[2][0], None, None, None, "draft", now_iso(offset_days=1, offset_hours=-3), None, None, "{}"),
        (f"duty_{prefix}_105", new_bookings[4][0], drivers[1][0], vehicles[0][0], suppliers[0][0], "completed", now_iso(offset_days=-1, offset_hours=-5), now_iso(offset_days=-1, offset_hours=-5), now_iso(offset_days=-1, offset_hours=-2), json.dumps(snapshot_comp1)),
        (f"duty_{prefix}_106", new_bookings[5][0], drivers[0][0], vehicles[2][0], suppliers[0][0], "completed", now_iso(offset_days=-2, offset_hours=-4), now_iso(offset_days=-2, offset_hours=-4), now_iso(offset_days=-2, offset_hours=-2), json.dumps(snapshot_comp2)),
    ]

    for duty_id, bid, did, vid, sid, status, rep_at, start_at, comp_at, snap in new_duties:
        conn.execute("""
            INSERT OR REPLACE INTO domain_duties(
                id, organization_id, booking_id, driver_id, vehicle_id, supplier_id,
                status, reporting_at, started_at, completed_at, calculation_snapshot_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (duty_id, org_id, bid, did, vid, sid, status, rep_at, start_at, comp_at, snap, now_iso(-24), now_iso()))

    # 9. Invoices
    invoices = [
        (f"inv_{prefix}_101", customers[0][0], new_duties[3][0], f"INV-{prefix[:4].upper()}-101", "issued", 235000, 42300, 277300, now_iso(offset_days=-1), json.dumps(snapshot_comp1)),
        (f"inv_{prefix}_102", customers[1][0], new_duties[4][0], f"INV-{prefix[:4].upper()}-102", "paid", 220000, 39600, 259600, now_iso(offset_days=-2), json.dumps(snapshot_comp2)),
    ]
    for inv_id, cid, duty_id, inv_num, status, subtotal, tax, total, issued, snap in invoices:
        conn.execute("""
            INSERT OR REPLACE INTO domain_invoices(
                id, organization_id, customer_id, duty_id, invoice_number, status,
                subtotal_paise, tax_paise, total_paise, issued_at, immutable_snapshot_json, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (inv_id, org_id, cid, duty_id, inv_num, status, subtotal, tax, total, issued, snap, creator_id, now_iso(-48), now_iso()))
        
        # Invoice lines
        lines_data = json.loads(snap).get("lines", [])
        for line in lines_data:
            line_id = f"line_{inv_id}_{line['code'].lower()}"
            conn.execute("""
                INSERT OR REPLACE INTO domain_invoice_lines(
                    id, invoice_id, code, label, quantity, unit_paise, amount_paise, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (line_id, inv_id, line["code"], line["label"], line["quantity"], line["unit_paise"], line["amount_paise"], now_iso(-48)))

    # 10. Price Books
    pb_id = f"pb_{prefix}_standard_2026"
    conn.execute("""
        INSERT OR REPLACE INTO domain_price_books(id, organization_id, branch_id, name, effective_from, status, version, created_by, created_at, updated_at)
        VALUES (?, ?, ?, 'Corporate Standard Price Book 2026', '2026-01-01', 'active', 1, ?, ?, ?)
    """, (pb_id, org_id, branches[0][0], creator_id, now_iso(-96), now_iso()))

    pb_items = [
        (f"pbi_{pb_id}_local_sedan", pb_id, "local", "sedan", 180000, 1800, 2400, 15000),
        (f"pbi_{pb_id}_local_suv", pb_id, "local", "suv", 240000, 2400, 3000, 20000),
        (f"pbi_{pb_id}_airport_sedan", pb_id, "airport", "sedan", 220000, 2000, 2400, 15000),
        (f"pbi_{pb_id}_airport_suv", pb_id, "airport", "suv", 300000, 2800, 3200, 20000),
        (f"pbi_{pb_id}_outstation_sedan", pb_id, "outstation", "sedan", 350000, 1600, 0, 0),
    ]
    for pbi_id, pbid, dtype, vgrp, base, pkm, phr, wait in pb_items:
        conn.execute("""
            INSERT OR REPLACE INTO domain_price_book_items(id, price_book_id, duty_type, vehicle_group, base_paise, per_km_paise, per_hour_paise, waiting_paise, tax_rate_bps, rules_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1800, '{}', ?)
        """, (pbi_id, pbid, dtype, vgrp, base, pkm, phr, wait, now_iso(-96)))

    # 11. Corporate Employees
    employees = [
        (f"emp_{prefix}_1", "E-1001", "Dr. Arvind Swaminathan", "arvind.s@northstar.example", "+91 98801 12345", "Engineering", "CC-ENG-01"),
        (f"emp_{prefix}_2", "E-1002", "Pooja Hegde", "pooja.h@infosys.example", "+91 98802 23456", "Operations", "CC-OPS-02"),
        (f"emp_{prefix}_3", "E-1003", "Karthik Narayanan", "karthik.n@wipro.example", "+91 98803 34567", "Sales", "CC-SALES-03"),
        (f"emp_{prefix}_4", "E-1004", "Sunita Roy", "sunita.r@tcs.example", "+91 98804 45678", "Consulting", "CC-CONS-04"),
        (f"emp_{prefix}_5", "E-1005", "Tanvi Sengupta", "tanvi.s@gs.example", "+91 98805 56789", "Investment Banking", "CC-IB-05"),
    ]
    for eid, code, name, email, phone, dept, cc in employees:
        conn.execute("""
            INSERT OR REPLACE INTO domain_employees(id, organization_id, employee_code, full_name, email, phone, department, cost_center, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
        """, (eid, org_id, code, name, email, phone, dept, cc, now_iso(-48), now_iso()))

    conn.commit()
    print(f"SUCCESS: Seeded tenant {org_id} with full operational data!")

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # Seed org_axiom_logistics
    seed_organization(conn, "org_axiom_logistics", creator_id="usr_abhijith_test")
    
    # Also seed any other vendor organization if present
    other_orgs = conn.execute("SELECT id FROM organizations WHERE kind = 'vendor' AND id != 'org_demo_blueorbit'").fetchall()
    for row in other_orgs:
        if row["id"] != "org_axiom_logistics":
            seed_organization(conn, row["id"])

    conn.close()

if __name__ == "__main__":
    main()
