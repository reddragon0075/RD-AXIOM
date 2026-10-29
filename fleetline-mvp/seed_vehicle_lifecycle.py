import sqlite3
import uuid
from datetime import datetime, timedelta

def seed_lifecycle_data():
    conn = sqlite3.connect('fleetline-mvp/data/axiom_fleet.sqlite3')
    cur = conn.cursor()
    org_id = 'org_axiom_logistics'
    user_id = 'usr_abhijith_test'

    # Clear previous cost entries for this org to be idempotent
    cur.execute("DELETE FROM domain_cost_entries WHERE organization_id = ?", (org_id,))

    # 1. Update domain_vehicles with financial profiles
    vehicles_config = [
        {
            "reg": "KA 01 EK 1596",
            "make": "Maruti Suzuki Dzire",
            "purchase_price": 82000000, # ₹8,20,000
            "purchase_date": "2025-01-10",
            "down_payment": 15000000,   # ₹1,50,000
            "emi_monthly": 1680000,     # ₹16,800/mo
            "emi_tenure": 48,
            "emi_paid": 21,
            "insurance_annual": 2450000,# ₹24,500/yr
            "current_odo": 42150.0,
            "fitness_expiry": "2027-01-09",
            "permit_expiry": "2028-01-09"
        },
        {
            "reg": "KA 01 EQ 1002",
            "make": "Maruti Suzuki Dzire",
            "purchase_price": 76000000, # ₹7,60,000
            "purchase_date": "2024-03-15",
            "down_payment": 12000000,   # ₹1,20,000
            "emi_monthly": 1540000,     # ₹15,400/mo
            "emi_tenure": 36,
            "emi_paid": 31,
            "insurance_annual": 2200000,# ₹22,000/yr
            "current_odo": 68400.0,
            "fitness_expiry": "2026-03-14",
            "permit_expiry": "2027-03-14"
        },
        {
            "reg": "KA 01 EV 5500",
            "make": "Tata Tigor EV",
            "purchase_price": 124000000,# ₹12,40,000
            "purchase_date": "2025-06-01",
            "down_payment": 24000000,   # ₹2,40,000
            "emi_monthly": 2350000,     # ₹23,500/mo
            "emi_tenure": 48,
            "emi_paid": 16,
            "insurance_annual": 2800000,# ₹28,000/yr
            "current_odo": 29800.0,
            "fitness_expiry": "2027-05-31",
            "permit_expiry": "2028-05-31"
        },
        {
            "reg": "KA 02 MN 8899",
            "make": "Maruti Suzuki Ertiga",
            "purchase_price": 115000000,# ₹11,50,000
            "purchase_date": "2024-08-20",
            "down_payment": 20000000,   # ₹2,00,000
            "emi_monthly": 2280000,     # ₹22,800/mo
            "emi_tenure": 48,
            "emi_paid": 26,
            "insurance_annual": 3100000,# ₹31,000/yr
            "current_odo": 58900.0,
            "fitness_expiry": "2026-08-19",
            "permit_expiry": "2027-08-19"
        },
        {
            "reg": "KA 05 SP 8107",
            "make": "Toyota Innova Crysta",
            "purchase_price": 0, # Supplier vehicle
            "purchase_date": "2023-11-01",
            "down_payment": 0,
            "emi_monthly": 0,
            "emi_tenure": 0,
            "emi_paid": 0,
            "insurance_annual": 0,
            "current_odo": 84200.0,
            "fitness_expiry": "2026-10-31",
            "permit_expiry": "2027-10-31"
        },
        {
            "reg": "KA 05 SP 2164",
            "make": "Toyota Innova Crysta",
            "purchase_price": 0, # Supplier vehicle
            "purchase_date": "2023-11-01",
            "down_payment": 0,
            "emi_monthly": 0,
            "emi_tenure": 0,
            "emi_paid": 0,
            "insurance_annual": 0,
            "current_odo": 91500.0,
            "fitness_expiry": "2026-10-31",
            "permit_expiry": "2027-10-31"
        }
    ]

    for cfg in vehicles_config:
        cur.execute("""
            UPDATE domain_vehicles
            SET purchase_price_paise = ?,
                purchase_date = ?,
                down_payment_paise = ?,
                emi_monthly_paise = ?,
                emi_tenure_months = ?,
                emi_paid_months = ?,
                insurance_annual_paise = ?,
                current_odometer_km = ?,
                fitness_expiry = ?,
                permit_expiry = ?
            WHERE organization_id = ? AND registration_number = ?
        """, (
            cfg["purchase_price"], cfg["purchase_date"], cfg["down_payment"],
            cfg["emi_monthly"], cfg["emi_tenure"], cfg["emi_paid"],
            cfg["insurance_annual"], cfg["current_odo"], cfg["fitness_expiry"],
            cfg["permit_expiry"], org_id, cfg["reg"]
        ))

    # Helper to insert cost entries
    def add_cost(veh_id, category, amount_paise, date_str, notes, cost_type="vehicle"):
        cost_id = f"cost_{uuid.uuid4().hex[:12]}"
        cur.execute("""
            INSERT INTO domain_cost_entries (
                id, organization_id, cost_type, category, amount_paise,
                vehicle_id, duty_id, supplier_bill_id, status, attachment_json,
                notes, created_by, created_at, expense_date
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, 'paid', '{}', ?, ?, ?, ?)
        """, (cost_id, org_id, cost_type, category, amount_paise, veh_id, notes, user_id, date_str + "T10:00:00Z", date_str))

    # Get vehicle IDs
    veh_map = {row[0]: row[1] for row in cur.execute("SELECT registration_number, id FROM domain_vehicles WHERE organization_id = ?", (org_id,)).fetchall()}

    # 2. Add realistic expense items for KA 01 EK 1596 (Our primary test vehicle)
    if "KA 01 EK 1596" in veh_map:
        v_id = veh_map["KA 01 EK 1596"]
        # Down payment
        add_cost(v_id, "down_payment", 15000000, "2025-01-10", "Initial down payment to dealer")
        # Insurance (Year 1 and Year 2)
        add_cost(v_id, "insurance", 2450000, "2025-01-12", "HDFC ERGO Comprehensive Policy Year 1")
        add_cost(v_id, "insurance", 2450000, "2026-01-15", "HDFC ERGO Comprehensive Renewal Year 2")
        # Maintenance & Service
        add_cost(v_id, "maintenance", 420000, "2025-04-10", "1st Periodic Service (10,000 km) - Engine Oil & Filter")
        add_cost(v_id, "maintenance", 650000, "2025-08-22", "2nd Periodic Service (20,000 km) - Brake pads & Alignment")
        add_cost(v_id, "maintenance", 510000, "2025-12-15", "3rd Periodic Service (30,000 km) - Oil, Coolant, AC Service")
        add_cost(v_id, "maintenance", 890000, "2026-05-18", "4th Major Service (40,000 km) - Spark plugs, Transmission oil")
        # Tires
        add_cost(v_id, "tire_battery", 1850000, "2026-06-25", "Set of 4 Bridgestone 185/65 R15 tires replacement")
        # Road Permit & Fitness
        add_cost(v_id, "permit_tax", 850000, "2025-01-15", "Karnataka All India Tourist Permit fee")
        # Fuel entries (Monthly aggregates)
        months_fuel = [
            ("2026-06-30", 1240000, "June 2026 Fleet Card Fuel (Petrol)"),
            ("2026-07-31", 1380000, "July 2026 Fleet Card Fuel (Petrol)"),
            ("2026-08-31", 1450000, "August 2026 Fleet Card Fuel (Petrol)"),
            ("2026-09-30", 1520000, "September 2026 Fleet Card Fuel (Petrol)"),
            ("2026-10-25", 1410000, "October 2026 Fleet Card Fuel (Petrol)")
        ]
        for f_date, f_paise, f_notes in months_fuel:
            add_cost(v_id, "fuel", f_paise, f_date, f_notes)
        # EMI entries (21 months: from Jan 2025 to Sep 2026)
        start_dt = datetime(2025, 2, 5)
        for i in range(21):
            emi_dt = start_dt + timedelta(days=i*30)
            add_cost(v_id, "emi", 1680000, emi_dt.strftime("%Y-%m-%d"), f"HDFC Bank Auto Loan EMI #{i+1}/48")
        # Allocated Driver Cost
        add_cost(v_id, "driver_cost", 1346000, "2026-10-28", "Aarav Sharma October 2026 Duty Trip Earnings (17 trips)")

    # 3. Add realistic expense items for KA 01 EQ 1002 (Older vehicle, already reached breakeven!)
    if "KA 01 EQ 1002" in veh_map:
        v_id = veh_map["KA 01 EQ 1002"]
        add_cost(v_id, "down_payment", 12000000, "2024-03-15", "Initial down payment")
        add_cost(v_id, "insurance", 2200000, "2024-03-20", "ICICI Lombard Year 1")
        add_cost(v_id, "insurance", 2100000, "2025-03-20", "ICICI Lombard Year 2")
        add_cost(v_id, "insurance", 1950000, "2026-03-20", "ICICI Lombard Year 3")
        add_cost(v_id, "maintenance", 1250000, "2025-06-10", "Clutch plate overhaul & general service")
        add_cost(v_id, "maintenance", 780000, "2026-04-12", "Suspension bushings & brake pads")
        add_cost(v_id, "tire_battery", 1600000, "2025-09-10", "4 Tires replacement (MRF ZVTS)")
        add_cost(v_id, "fuel", 3800000, "2026-09-30", "Q3 2026 Aggregate Fuel")

    # 4. Add for Tata Tigor EV (KA 01 EV 5500)
    if "KA 01 EV 5500" in veh_map:
        v_id = veh_map["KA 01 EV 5500"]
        add_cost(v_id, "down_payment", 24000000, "2025-06-01", "EV Down Payment")
        add_cost(v_id, "insurance", 2800000, "2025-06-05", "Bajaj Allianz EV Zero Dep Year 1")
        add_cost(v_id, "fuel", 480000, "2026-10-20", "Jio-BP Pulse Fast Charging Station logs")
        add_cost(v_id, "maintenance", 350000, "2026-03-15", "EV Periodic Inspection & Cabin Filter")

    conn.commit()
    total_costs = cur.execute("SELECT COUNT(*), SUM(amount_paise) FROM domain_cost_entries WHERE organization_id = ?", (org_id,)).fetchone()
    print(f"Seeding completed! Inserted {total_costs[0]} cost entries totaling Rs. {total_costs[1]/100:,.2f}")

if __name__ == "__main__":
    seed_lifecycle_data()
