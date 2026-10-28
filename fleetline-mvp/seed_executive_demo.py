#!/usr/bin/env python3
"""Axiom Mobility Executive Demo Seeder.

Populates the platform database with a rich, realistic 'Day-in-the-Life' Demo State
for live executive walkthroughs and investor demonstrations:

1. 3 Website Prospects (NEW and CONTACTED states with real Indian corporate profiles & sales notes)
2. 4 Active Corporate/Vendor Tenants (with users, fleet, and Money Owed to Axiom Mobility)
   - 3 Healthy Tenants
   - 1 Overdue Delinquent Tenant (Speedway Logistics) in SOFT_BLOCKED state ready for live 1-click unblock
3. Live Operations Data in VendorCommandDashboard.js:
   - 5 ACTIVE/dispatched trips across different tariff models (HR/KM slab, Outstation, Zone Rings, Package, Day Rate)
   - 1 Algorithmic Trust Auditor Discrepancy (Duty DT-8819: trust_score 65, 48 km odo vs 29 km GPS)
   - 1 SLA Pre-Cog Radar Alert (Duty DT-9104: 12 min to pickup with Silk Board congestion + 3 fast backups)
   - 1 Night-Shift Guardian Route (Duty DT-9106: female solo night commute requiring escort validation)
"""

from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from server import initialize_database, DB_PATH


def now_iso(offset_minutes: float = 0, offset_hours: float = 0, offset_days: float = 0) -> str:
    target = datetime.now(timezone.utc) + timedelta(days=offset_days, hours=offset_hours, minutes=offset_minutes)
    return target.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def seed_executive_demo(conn: sqlite3.Connection):
    print("============================================================")
    print("AXIOM MOBILITY: SEEDING EXECUTIVE DEMO ENVIRONMENT")
    print("============================================================")

    now = now_iso()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # -------------------------------------------------------------
    # 1. Seed 3 Website Prospects (Sales CRM Pipeline)
    # -------------------------------------------------------------
    print("-> Seeding Website Prospects (Sales CRM Pipeline)...")
    prospects = [
        (
            "prsp_demo_tcs",
            "Rohan Nambiar",
            "Tata Consultancy Services (E-City)",
            "rohan.nambiar@tcs-mobility.in",
            "+919845012345",
            "Evaluating replacing vendor fleet with 80 dedicated cabs across Bangalore Whitefield & Electronic City campuses.",
            "WEBSITE",
            "NEW",
            json.dumps([
                {"timestamp": now_iso(offset_hours=-3), "author": "WEBSITE_INQUIRY", "note": "Direct inquiry submitted from website commercial landing page."}
            ]),
            "sales@axiomfleet.in",
            None,
            now_iso(offset_hours=-3),
            now_iso(offset_hours=-3),
        ),
        (
            "prsp_demo_infosys",
            "Ananya Deshmukh",
            "Infosys BPM Hub",
            "ananya.deshmukh@infosysbpm.com",
            "+919820067890",
            "Require daily safe night-shift transport for 120 women employees with verified security escorts and GPS geofence tracking.",
            "REFERRAL",
            "QUALIFIED",
            json.dumps([
                {"timestamp": now_iso(offset_days=-1, offset_hours=-4), "author": "sales@axiomfleet.in", "note": "Held introductory discovery call with Ananya; verified 120-employee night transport scope; sending tariff proposal."},
                {"timestamp": now_iso(offset_hours=-2), "author": "sales@axiomfleet.in", "note": "Qualified budget: ₹18 Lakhs/month. Ready for 1-click tenant onboarding."}
            ]),
            "sales@axiomfleet.in",
            None,
            now_iso(offset_days=-1),
            now_iso(offset_hours=-2),
        ),
        (
            "prsp_demo_wipro",
            "Karthik Sundaram",
            "Wipro Sarjapur Tech Campus",
            "karthik.s@wiprocampus.in",
            "+919880098765",
            "Requesting pricing matrix for executive airport transfers and inter-city outstation client shuttles.",
            "WEBSITE",
            "NEW",
            json.dumps([
                {"timestamp": now_iso(offset_hours=-1), "author": "WEBSITE_INQUIRY", "note": "Website form inquiry requesting corporate airport and outstation tariff cards."}
            ]),
            "sales@axiomfleet.in",
            None,
            now_iso(offset_hours=-1),
            now_iso(offset_hours=-1),
        ),
    ]

    for p in prospects:
        conn.execute(
            """INSERT OR REPLACE INTO prospects (
                id, contact_name, company_name, email, mobile_number, message,
                source, status, sales_notes, assigned_sales_rep, converted_tenant_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            p,
        )

    # -------------------------------------------------------------
    # 2. Seed 4 Active Corporate/Vendor Tenants (Company Overview & Receivables)
    # -------------------------------------------------------------
    print("-> Seeding Corporate/Vendor Tenants & Receivables Ledger...")
    tenants = [
        {
            "id": "org_demo_blueline",
            "name": "BlueLine Mobility Services (Blr)",
            "status": "ACTIVE",
            "credit_limit": 1500000,
            "billed": 12800000,
            "paid": 11400000,
            "owed": 1400000,
            "days_overdue": 5,
            "due_date": now_iso(offset_days=7)[:10],
            "reason": "",
        },
        {
            "id": "org_demo_aeroshuttle",
            "name": "AeroShuttle Express Pvt Ltd",
            "status": "ACTIVE",
            "credit_limit": 2500000,
            "billed": 24500000,
            "paid": 22000000,
            "owed": 2500000,
            "days_overdue": 0,
            "due_date": now_iso(offset_days=14)[:10],
            "reason": "",
        },
        {
            "id": "org_demo_metrofleet",
            "name": "MetroFleet Corporate Cabs",
            "status": "ACTIVE",
            "credit_limit": 1000000,
            "billed": 7200000,
            "paid": 7200000,
            "owed": 0,
            "days_overdue": 0,
            "due_date": now_iso(offset_days=21)[:10],
            "reason": "",
        },
        {
            "id": "org_demo_speedway",
            "name": "Speedway Logistics & Fleet",
            "status": "SOFT_BLOCKED",
            "credit_limit": 500000,
            "billed": 18500000,
            "paid": 14700000,
            "owed": 3800000,
            "days_overdue": 48,
            "due_date": now_iso(offset_days=-48)[:10],
            "reason": "Overdue balance of ₹38,000 exceeds credit limit ₹5,000 and is 48 days past invoice due date.",
        },
    ]

    for t in tenants:
        conn.execute(
            """INSERT OR REPLACE INTO organizations (id, kind, name, phone, city, gstin, created_at)
               VALUES (?, 'vendor', ?, '+918069008800', 'Bengaluru', '29ABCDE1234F1Z5', ?)""",
            (t["id"], t["name"], now),
        )

        admin_email = f"admin@{t['id'].replace('org_demo_', '')}.in"
        conn.execute(
            """INSERT OR REPLACE INTO users (id, email, password_hash, password_salt, role, full_name, organization_id, status, created_at)
               VALUES (?, ?, 'hash', 'salt', 'vendor', ?, ?, 'active', ?)""",
            (f"usr_{t['id']}_admin", admin_email, f"{t['name']} Admin", t["id"], now),
        )

        conn.execute(
            """INSERT OR REPLACE INTO tenant_billing_accounts (
                tenant_id, tenant_name, account_status, block_reason, blocked_at, blocked_by,
                total_billed_paise, total_paid_paise, outstanding_balance_paise,
                credit_limit_paise, next_due_date, days_overdue, auto_block_on_overdue,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (
                t["id"],
                t["name"],
                t["status"],
                t["reason"],
                now if t["status"] != "ACTIVE" else None,
                "SYSTEM_DUNNING" if t["status"] != "ACTIVE" else None,
                t["billed"],
                t["paid"],
                t["owed"],
                t["credit_limit"],
                t["due_date"],
                t["days_overdue"],
                now,
                now,
            ),
        )

        # Seed initial receivables ledger entries
        conn.execute(
            """INSERT OR REPLACE INTO axiom_receivable_ledger (
                id, tenant_id, entry_type, reference_id, amount_paise, description, payment_method, created_by, created_at
            ) VALUES (?, ?, 'INVOICE', ?, ?, 'Monthly SaaS Platform License & Fleet Telematics', '', 'system', ?)""",
            (f"rec_inv_{t['id']}", t["id"], f"INV-2026-{t['id'][:6]}", t["billed"], now_iso(offset_days=-15)),
        )
        if t["paid"] > 0:
            conn.execute(
                """INSERT OR REPLACE INTO axiom_receivable_ledger (
                    id, tenant_id, entry_type, reference_id, amount_paise, description, payment_method, created_by, created_at
                ) VALUES (?, ?, 'PAYMENT', ?, ?, 'NEFT/UPI Bank Settlement', 'NEFT', 'system', ?)""",
                (f"rec_pay_{t['id']}", t["id"], f"TXN-2026-{t['id'][:6]}", t["paid"], now_iso(offset_days=-5)),
            )

    # -------------------------------------------------------------
    # 3. Seed Fleet & Live Operations for BlueLine Mobility
    # -------------------------------------------------------------
    print("-> Seeding Active Fleet, Drivers & Live Operations...")
    main_org = "org_demo_blueline"

    drivers = [
        ("drv_demo_ramesh", "Ramesh Kumar", "+919845044911", "KA-01-MJ-4491", "active"),
        ("drv_demo_kiran", "Kiran R.", "+919845090211", "KA-01-EQ-9021", "available"),
        ("drv_demo_suresh", "Suresh Gowda", "+919845055441", "KA-05-AB-1200", "active"),
        ("drv_demo_deepak", "Deepak Kumar", "+919845033201", "KA-05-NB-3320", "available"),
        ("drv_demo_manoj", "Manoj Patil", "+919845011881", "KA-04-MK-8877", "active"),
    ]
    for did, name, phone, vreg, st in drivers:
        conn.execute(
            """INSERT OR REPLACE INTO domain_drivers (id, organization_id, full_name, phone, license_number, license_expiry, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, '2030-01-01', ?, ?, ?)""",
            (did, main_org, name, phone, f"DL-{vreg.replace('-', '')}", st, now, now),
        )

    vehicles = [
        ("veh_demo_dzire", "KA-01-EQ-9021", "sedan", "Maruti Dzire ZXi", "active"),
        ("veh_demo_etios", "KA-01-MJ-4491", "sedan", "Toyota Etios GD", "active"),
        ("veh_demo_innova", "KA-05-AB-1200", "suv", "Toyota Innova Crysta", "active"),
        ("veh_demo_ertiga", "KA-05-NB-3320", "suv", "Maruti Ertiga Hybrid", "active"),
        ("veh_demo_city", "KA-04-MK-8877", "sedan", "Honda City ZX", "active"),
    ]
    for vid, reg, vtype, model, st in vehicles:
        conn.execute(
            """INSERT OR REPLACE INTO domain_vehicles (id, organization_id, registration_number, vehicle_type, make_model, insurance_expiry, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, '2030-01-01', ?, ?, ?)""",
            (vid, main_org, reg, vtype, model, st, now, now),
        )

    # -------------------------------------------------------------
    # 4. Seed 5 Live Active Duties across 5 Tariff Models
    # -------------------------------------------------------------
    print("-> Seeding 5 Active Trips across Multi-Tariff Models...")
    duties_meta = [
        # 1. HR/KM Slab (In Execution)
        {
            "duty_id": "DT-9101",
            "booking_id": "BK-9101",
            "passenger": "Aditya Roy (Amazon Tech)",
            "pickup": "Indiranagar 100ft Rd",
            "dropoff": "Whitefield ITPL",
            "driver_id": "drv_demo_ramesh",
            "vehicle_id": "veh_demo_etios",
            "status": "in_progress",
            "tariff_model": "slab",
            "scheduled_at": now_iso(offset_minutes=-35),
            "start_odo": 41200,
            "end_odo": None,
        },
        # 2. Outstation (In Execution)
        {
            "duty_id": "DT-9102",
            "booking_id": "BK-9102",
            "passenger": "Meera Sengupta (Flipkart Logistics)",
            "pickup": "Koramangala 4th Block",
            "dropoff": "Mysore Infy Campus",
            "driver_id": "drv_demo_suresh",
            "vehicle_id": "veh_demo_innova",
            "status": "in_progress",
            "tariff_model": "outstation",
            "scheduled_at": now_iso(offset_hours=-2),
            "start_odo": 68400,
            "end_odo": None,
        },
        # 3. Zone Ring Airport Transfer (Allotted)
        {
            "duty_id": "DT-9103",
            "booking_id": "BK-9103",
            "passenger": "Siddharth Nair (Goldman Sachs)",
            "pickup": "Electronic City Phase 1",
            "dropoff": "Bengaluru International Airport T2",
            "driver_id": "drv_demo_manoj",
            "vehicle_id": "veh_demo_city",
            "status": "allotted",
            "tariff_model": "zone_ring",
            "scheduled_at": now_iso(offset_minutes=25),
            "start_odo": 29100,
            "end_odo": None,
        },
        # 4. VIP Executive Package (Upcoming - SLA Radar Alert!)
        {
            "duty_id": "DT-9104",
            "booking_id": "BK-9104",
            "passenger": "Anita Sharma (VP Technology, IBM)",
            "pickup": "Silk Board Junction / HSR Layout",
            "dropoff": "Embassy GolfLinks (EGL) Dome",
            "driver_id": "drv_demo_suresh",
            "vehicle_id": "veh_demo_innova",
            "status": "allotted",
            "tariff_model": "package",
            "scheduled_at": now_iso(offset_minutes=12),
            "start_odo": 68550,
            "end_odo": None,
        },
        # 5. Day Rate Site Inspection (Dispatched)
        {
            "duty_id": "DT-9105",
            "booking_id": "BK-9105",
            "passenger": "Rajeev Mehra (L&T Construction)",
            "pickup": "Hebbal Flyover Office",
            "dropoff": "Devenahalli Industrial Corridor",
            "driver_id": "drv_demo_kiran",
            "vehicle_id": "veh_demo_dzire",
            "status": "dispatched",
            "tariff_model": "day_rate",
            "scheduled_at": now_iso(offset_minutes=45),
            "start_odo": 15400,
            "end_odo": None,
        },
    ]

    for d in duties_meta:
        conn.execute(
            """INSERT OR REPLACE INTO domain_bookings (
                id, organization_id, booking_reference, status, passenger_name, passenger_phone,
                passenger_email, pickup_json, dropoff_json, scheduled_at, duty_type, notes,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, 'assigned', ?, '+919988776655', 'guest@corp.com', ?, ?, ?, ?, 'Executive VIP Booking', 'sys_demo', ?, ?)""",
            (
                d["booking_id"],
                main_org,
                f"BK-{d['duty_id']}",
                d["passenger"],
                json.dumps({"address": d["pickup"], "lat": 12.9352, "lon": 77.6245}),
                json.dumps({"address": d["dropoff"], "lat": 12.9719, "lon": 77.6412}),
                d["scheduled_at"],
                d["tariff_model"],
                now,
                now,
            ),
        )

        conn.execute(
            """INSERT OR REPLACE INTO domain_duties (
                id, organization_id, booking_id, driver_id, vehicle_id, status,
                start_odometer, end_odometer, started_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                d["duty_id"],
                main_org,
                d["booking_id"],
                d["driver_id"],
                d["vehicle_id"],
                d["status"],
                d["start_odo"],
                d["end_odo"],
                d["scheduled_at"] if d["status"] == "in_progress" else None,
                now,
                now,
            ),
        )

    # -------------------------------------------------------------
    # 5. Seed Trip Flagged by Algorithmic Trust Auditor (DT-8819)
    # -------------------------------------------------------------
    print("-> Seeding Trust Score Discrepancy (Duty DT-8819: trust_score 65)...")
    audit_duty_id = "DT-8819"
    audit_booking_id = "BK-8819"

    conn.execute(
        """INSERT OR REPLACE INTO domain_bookings (
            id, organization_id, booking_reference, status, passenger_name, passenger_phone,
            passenger_email, pickup_json, dropoff_json, scheduled_at, duty_type, notes,
            created_by, created_at, updated_at
        ) VALUES (?, ?, 'BK-DT-8819', 'completed', 'Ramesh Kumar (Infosys BPM)', '+919845011999', 'ramesh@infosys.com', ?, ?, ?, 'local', 'Completed trip pending variance audit', 'sys_demo', ?, ?)""",
        (
            audit_booking_id,
            main_org,
            json.dumps({"address": "Koramangala 4th Block", "lat": 12.9352, "lon": 77.6245}),
            json.dumps({"address": "Whitefield ITPL", "lat": 12.9863, "lon": 77.7340}),
            now_iso(offset_hours=-2),
            now,
            now,
        ),
    )

    # Start odo: 88000, End odo: 88048 (48 km reported vs 29.0 km GPS expected -> +65.5% variance)
    conn.execute(
        """INSERT OR REPLACE INTO domain_duties (
            id, organization_id, booking_id, driver_id, vehicle_id, status,
            start_odometer, end_odometer, started_at, completed_at, calculation_snapshot_json,
            created_at, updated_at
        ) VALUES (?, ?, ?, 'drv_demo_ramesh', 'veh_demo_etios', 'completed', 88000, 88048, ?, ?, ?, ?, ?)""",
        (
            audit_duty_id,
            main_org,
            audit_booking_id,
            now_iso(offset_hours=-2),
            now_iso(offset_hours=-1),
            json.dumps({"subtotal_paise": 385000, "tax_paise": 19250, "total_paise": 404250, "distance_km": 48.0}),
            now,
            now,
        ),
    )

    audit_flags = [
        {
            "code": "ODOMETER_GPS_VARIANCE",
            "message": "Reported Odometer (48.0 km) exceeds expected route GPS distance (29.0 km) by 65.5% (+19.0 km).",
            "severity": "HIGH",
            "delta_km": 48.0,
            "expected_km": 29.0,
            "variance_pct": 65.5,
        }
    ]

    conn.execute(
        """INSERT OR REPLACE INTO domain_duty_trust_audits (
            id, organization_id, duty_id, trust_score, audit_status, audit_flags_json,
            odometer_distance_km, expected_distance_km, duration_hours, implied_speed_kmh,
            created_at, updated_at
        ) VALUES (?, ?, ?, 65, 'NEEDS_AUDIT', ?, 48.0, 29.0, 1.2, 40.0, ?, ?)""",
        (f"aud_{audit_duty_id}", main_org, audit_duty_id, json.dumps(audit_flags), now, now),
    )

    # -------------------------------------------------------------
    # 6. Seed Night-Shift Guardian Route (Solo Female Night Commute)
    # -------------------------------------------------------------
    print("-> Seeding Night-Shift Guardian Route (Priyanka Sen, Solo Night Commute)...")
    night_duty_id = "DT-9106"
    night_booking_id = "BK-9106"

    # Scheduled for 21:30 tonight (inside 20:00 - 06:00 night window)
    night_scheduled = f"{today_str}T21:30:00Z"
    conn.execute(
        """INSERT OR REPLACE INTO domain_bookings (
            id, organization_id, booking_reference, status, passenger_name, passenger_phone,
            passenger_email, pickup_json, dropoff_json, scheduled_at, duty_type, notes,
            created_by, created_at, updated_at
        ) VALUES (?, ?, 'BK-DT-9106', 'assigned', 'Priyanka Sen (Female Solo)', '+919844011223', 'priyanka.sen@accenture.com', ?, ?, ?, 'ets', 'Night Shift Employee Commute - POSH Escort Required', 'sys_demo', ?, ?)""",
        (
            night_booking_id,
            main_org,
            json.dumps({"address": "Bellandur EcoSpace", "lat": 12.9260, "lon": 77.6762}),
            json.dumps({"address": "BTM 2nd Stage", "lat": 12.9166, "lon": 77.6101}),
            night_scheduled,
            now,
            now,
        ),
    )

    conn.execute(
        """INSERT OR REPLACE INTO domain_duties (
            id, organization_id, booking_id, driver_id, vehicle_id, status,
            start_odometer, end_odometer, reporting_at, created_at, updated_at
        ) VALUES (?, ?, ?, 'drv_demo_kiran', 'veh_demo_dzire', 'assigned', 15600, NULL, ?, ?, ?)""",
        (night_duty_id, main_org, night_booking_id, night_scheduled, now, now),
    )

    conn.commit()

    print("============================================================")
    print("EXECUTIVE DEMO DATA SEEDED SUCCESSFULLY!")
    print(f"Database: {DB_PATH.resolve()}")
    print("1. 3 Website Prospects (TCS, Infosys BPM, Wipro)")
    print("2. 4 Commercial Tenants (BlueLine, AeroShuttle, MetroFleet, Speedway [Overdue/Blocked])")
    print("3. 5 Active Trips (DT-9101 to DT-9105 across Slab, Outstation, Zone Ring, Package, Day Rate)")
    print("4. 1 Algorithmic Trust Discrepancy (Duty DT-8819 ready for 1-click snap-to-GPS)")
    print("5. 1 SLA Radar Breach Alert (Duty DT-9104 in Silk Board traffic with 3 suggested backups)")
    print("6. 1 Night-Shift Guardian Route (Duty DT-9106 Priyanka Sen solo night escort)")
    print("============================================================")


if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    initialize_database()
    seed_executive_demo(conn)
    conn.close()
