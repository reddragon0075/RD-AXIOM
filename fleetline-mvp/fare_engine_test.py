"""Comprehensive test suite for Axiom Fleet Fare Engine & Rate Card Resolver."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fare_engine import (
    FARE_ENGINE_VERSION,
    FareError,
    TelemetryData,
    calc_percentage_bps,
    calculate_fare,
    calculate_optimal_local_fare,
    calculate_outstation_fare,
    calculate_airport_fare,
    calculate_fuel_surcharge,
    calculate_dual_ledger_settlement,
)
from fare_resolver import (
    resolve_billed_vehicle_group,
    resolve_rate_card_context,
    TIER_LABELS,
)


def test_local_fare_standard():
    telemetry = {
        "billing_mode": "P2P",
        "reporting_km": 10000,
        "releasing_km": 10050,  # 50 km (10 km extra over 40 km)
        "duration_minutes": 270,  # 4h 30m (30 mins extra over 240 mins)
        "toll_paise": 15000,
        "parking_paise": 5000,
        "reimbursements_taxable": False,
    }
    rule = {
        "fare_mode": "local",
        "package_name": "4Hr 40Km",
        "package_minutes": 240,
        "included_km": 40,
        "base_paise": 150000,  # 1500.00 INR
        "extra_km_paise": 1800,  # 18.00 INR/km
        "extra_hour_paise": 20000,  # 200.00 INR/hr
        "grace_period_minutes": 15,  # 30m > 15m -> 1 hr extra billed
        "slab_switch_mode": "NONE",
        "tax_rate_bps": 500,  # 5% GST
    }

    result = calculate_fare(telemetry, rule)

    assert result["engine_version"] == FARE_ENGINE_VERSION
    assert result["duty_mode"] == "local"

    # Base: 1500.00, Extra KM: 10 * 18 = 180.00, Extra Time: 1h * 200 = 200.00
    # Transport Subtotal = 150000 + 18000 + 20000 = 188000 paise (₹1,880.00)
    assert result["transport_subtotal_paise"] == 188000

    # Reimbursements: 150 + 50 = 20000 paise (₹200.00)
    assert result["reimbursements_paise"] == 20000

    # Taxable Base is transport subtotal (reimbursements_taxable=False)
    assert result["taxable_base_paise"] == 188000
    # 5% of 188000 = 9400 paise (₹94.00)
    assert result["tax_paise"] == 9400

    # CGST + SGST
    assert len(result["tax_lines"]) == 2
    assert result["tax_lines"][0]["tax_amount_paise"] == 4700
    assert result["tax_lines"][1]["tax_amount_paise"] == 4700

    # Grand Total: 188000 + 20000 + 9400 = 217400 paise (₹2,174.00)
    assert result["total_fare_paise"] == 217400


def test_auto_slab_optimization_upgrade_only():
    """Customer booked 4Hr 40Km, but duty ran 7 hours 45 mins and 75 km.

    On 4Hr 40Km:
      Base: ₹1,400.00
      Extra KM: (75 - 40) = 35 km * ₹18/km = ₹630.00
      Extra Time: (465 - 240) = 225m -> 4 hrs * ₹200 = ₹800.00
      Total on 4Hr 40Km = ₹2,830.00

    Sibling Slab 8Hr 80Km on Rate Card:
      Base: ₹2,400.00
      Extra KM: 0 km (75 <= 80)
      Extra Time: 0 hr (465 <= 480)
      Total on 8Hr 80Km = ₹2,400.00

    Savings = ₹430.00! Engine should automatically switch to 8Hr 80Km.
    """
    slabs = [
        {
            "id": "slab-4x40",
            "package_name": "4Hr 40Km",
            "package_minutes": 240,
            "included_km": 40,
            "base_paise": 140000,
            "extra_km_paise": 1800,
            "extra_hour_paise": 20000,
            "grace_period_minutes": 15,
            "slab_switch_mode": "UPGRADE_ONLY",
        },
        {
            "id": "slab-8x80",
            "package_name": "8Hr 80Km",
            "package_minutes": 480,
            "included_km": 80,
            "base_paise": 240000,
            "extra_km_paise": 1800,
            "extra_hour_paise": 20000,
            "grace_period_minutes": 15,
            "slab_switch_mode": "UPGRADE_ONLY",
        },
    ]

    telemetry = {
        "billing_mode": "P2P",
        "reporting_km": 20000,
        "releasing_km": 20075,  # 75 km
        "duration_minutes": 465,  # 7h 45m
    }

    result = calculate_fare(telemetry, slabs[0], candidate_slabs=slabs)
    opt = result["explanation"]["slab_optimization"]

    assert opt["was_switched"] is True
    assert opt["booked_slab"] == "4Hr 40Km"
    assert opt["selected_slab"] == "8Hr 80Km"
    assert opt["savings_paise"] == 43000  # ₹430.00 savings
    assert result["transport_subtotal_paise"] == 240000  # Charged the cheaper base of ₹2,400.00


def test_outstation_daily_min_and_batta():
    telemetry = {
        "billing_mode": "P2P",
        "reporting_km": 50000,
        "releasing_km": 50420,  # 420 km actual
        "calendar_days": 2,  # 2 days * 250 min km = 500 km guaranteed
        "night_hours_count": 1,  # 1 night driving block
    }
    rule = {
        "fare_mode": "outstation",
        "min_km_per_day": 250,
        "rate_per_km_paise": 1600,  # ₹16.00 / km
        "driver_day_allowance_paise": 40000,  # ₹400 / day
        "driver_night_allowance_paise": 35000,  # ₹350 / night
        "tax_rate_bps": 500,
    }

    result = calculate_fare(telemetry, rule)
    out_b = result["explanation"]["outstation_breakdown"]

    assert out_b["effective_km"] == 420.0
    assert out_b["guaranteed_km"] == 500.0
    assert out_b["chargeable_km"] == 500.0  # 500 km charged due to 250km/day min guarantee

    # KM Charge: 500 * 1600 = 800000 paise (₹8,000.00)
    assert out_b["km_charge_paise"] == 800000

    # 2 days batta = 2 * 400 = 80000 paise (₹800.00)
    assert out_b["total_day_batta_paise"] == 80000

    # 1 night allowance = 35000 paise (₹350.00)
    assert out_b["total_night_allowance_paise"] == 35000

    # Transport Subtotal = 8000 + 800 + 350 = ₹9,150.00 (915000 paise)
    assert result["transport_subtotal_paise"] == 915000


def test_airport_transfer_with_waiting():
    telemetry = {
        "billing_mode": "P2P",
        "reporting_km": 1000,
        "releasing_km": 1045,
        "waiting_minutes": 75,  # 75 mins - 45 mins free = 30 mins billable
        "toll_paise": 12000,  # Airport toll ₹120
    }
    rule = {
        "fare_mode": "airport",
        "flat_rate_paise": 180000,  # ₹1,800.00
        "free_waiting_minutes": 45,
        "waiting_paise_per_hour": 30000,  # ₹300.00 / hr -> 30 mins = ₹150.00
        "tax_rate_bps": 500,
    }

    result = calculate_fare(telemetry, rule)

    # Base ₹1,800 + Waiting ₹150 = ₹1,950 transport subtotal
    assert result["transport_subtotal_paise"] == 195000
    assert result["reimbursements_paise"] == 12000
    assert result["total_fare_paise"] == 195000 + 12000 + calc_percentage_bps(195000, 500)


def test_dynamic_fuel_surcharge():
    # 200 km, base diesel rate ₹90/L, current rate ₹96/L (Δ ₹6), mileage benchmark 12 km/L
    # Surcharge = (200 * 6.00) / 12 = ₹100.00 (10000 paise)
    rule = {
        "base_fuel_rate_paise": 9000,
        "mileage_km_per_litre": 12.0,
    }
    res = calculate_fuel_surcharge(200.0, rule, current_fuel_rate_paise=9600)

    assert res["active"] is True
    assert res["fuel_delta_paise"] == 600
    assert res["amount_paise"] == 10000  # ₹100.00


def test_garage_to_garage_shed_capping():
    # P2P: 10020 to 10080 = 60 km
    # Garage Out: 10000 -> Front shed = 20 km
    # Garage In: 10110 -> Back shed = 30 km
    # Total shed = 50 km. But rate card caps max shed KM at 25 km!
    # Effective KM should be 60 + 25 = 85 km (not full 110 km garage km).
    telemetry = TelemetryData.from_payload({
        "billing_mode": "G2G",
        "garage_out_km": 10000,
        "reporting_km": 10020,
        "releasing_km": 10080,
        "garage_in_km": 10110,
    })

    assert telemetry.p2p_km == 60.0
    assert telemetry.garage_km == 110.0
    assert telemetry.shed_km == 50.0

    # With 25 km cap
    assert telemetry.effective_km(max_shed_km=25.0) == 85.0
    # Without cap
    assert telemetry.effective_km(max_shed_km=None) == 110.0


def test_dual_ledger_settlement_and_pnl():
    telemetry = {
        "billing_mode": "P2P",
        "reporting_km": 10000,
        "releasing_km": 10080,  # 80 km
        "duration_minutes": 480,  # 8 hrs
        "toll_paise": 15000,
    }
    client_profile = {
        "fare_mode": "local",
        "package_name": "8Hr 80Km",
        "package_minutes": 480,
        "included_km": 80,
        "base_paise": 320000,  # Client billed ₹3,200.00
        "tax_rate_bps": 500,
    }
    supplier_profile = {
        "fare_mode": "local",
        "package_name": "8Hr 80Km",
        "package_minutes": 480,
        "included_km": 80,
        "base_paise": 220000,  # Supplier paid ₹2,200.00
        "tax_rate_bps": 500,
    }

    settlement = calculate_dual_ledger_settlement(telemetry, client_profile, supplier_profile)
    pnl = settlement["settlement_pnl"]

    # Revenue (excl tax): 3200 + 150 toll = 335000 paise (₹3,350.00)
    # Cost (excl tax): 2200 + 150 toll = 235000 paise (₹2,350.00)
    # Net Profit = ₹1,000.00 (100000 paise)
    assert pnl["net_revenue_paise"] == 335000
    assert pnl["net_cost_paise"] == 235000
    assert pnl["gross_profit_paise"] == 100000
    assert pnl["gross_margin_percentage"] == round((1000 / 3350) * 100, 2)
    assert pnl["is_profitable"] is True


def test_hierarchical_rate_card_resolution_waterfall():
    rules = [
        # Tier 4: Global Default
        {"id": "r-tier4", "tenant_id": "tenant-1", "entity_type": "DEFAULT", "entity_id": None, "city_id": None, "vehicle_group_id": "SEDAN", "fare_mode": "local", "base_paise": 100000},
        # Tier 3: City Default (Mumbai)
        {"id": "r-tier3", "tenant_id": "tenant-1", "entity_type": "DEFAULT", "entity_id": None, "city_id": "mumbai", "vehicle_group_id": "SEDAN", "fare_mode": "local", "base_paise": 120000},
        # Tier 2: Entity Global (Client-X)
        {"id": "r-tier2", "tenant_id": "tenant-1", "entity_type": "CLIENT", "entity_id": "cust-x", "city_id": None, "vehicle_group_id": "SEDAN", "fare_mode": "local", "base_paise": 140000},
        # Tier 1: Entity + City (Client-X in Bengaluru)
        {"id": "r-tier1", "tenant_id": "tenant-1", "entity_type": "CLIENT", "entity_id": "cust-x", "city_id": "bengaluru", "vehicle_group_id": "SEDAN", "fare_mode": "local", "base_paise": 160000},
    ]

    # 1. Exact match in Bengaluru -> Should pick Tier 1
    t1 = resolve_rate_card_context(rules, tenant_id="tenant-1", ledger_side="RECEIVABLE", entity_id="cust-x", city_id="bengaluru", requested_vehicle_group="SEDAN")
    assert t1["resolution_trace"]["resolution_tier"] == TIER_LABELS[1]
    assert t1["id"] == "r-tier1"

    # 2. Match in Pune (Client-X has no Pune rate, but has global rate) -> Should pick Tier 2
    t2 = resolve_rate_card_context(rules, tenant_id="tenant-1", ledger_side="RECEIVABLE", entity_id="cust-x", city_id="pune", requested_vehicle_group="SEDAN")
    assert t2["resolution_trace"]["resolution_tier"] == TIER_LABELS[2]
    assert t2["id"] == "r-tier2"

    # 3. Match in Mumbai for Client-Y (has no dedicated rate) -> Should pick Tier 3 (Mumbai Default)
    t3 = resolve_rate_card_context(rules, tenant_id="tenant-1", ledger_side="RECEIVABLE", entity_id="cust-y", city_id="mumbai", requested_vehicle_group="SEDAN")
    assert t3["resolution_trace"]["resolution_tier"] == TIER_LABELS[3]
    assert t3["id"] == "r-tier3"

    # 4. Match in Delhi for Client-Y -> Falls back to Tier 4 (Global Default)
    t4 = resolve_rate_card_context(rules, tenant_id="tenant-1", ledger_side="RECEIVABLE", entity_id="cust-y", city_id="delhi", requested_vehicle_group="SEDAN")
    assert t4["resolution_trace"]["resolution_tier"] == TIER_LABELS[4]
    assert t4["id"] == "r-tier4"


def test_vehicle_upgrade_protection():
    # Customer requested SEDAN, but fleet allotted SUV
    # Receivable (Customer): must resolve to SEDAN unless charge_upgrade_to_client is True
    vg_cust = resolve_billed_vehicle_group(ledger_side="RECEIVABLE", requested_vehicle_group="SEDAN", allotted_vehicle_group="SUV", charge_upgrade_to_client=False)
    assert vg_cust == "SEDAN"

    # If customer explicitly requested to be charged for upgrade
    vg_cust_up = resolve_billed_vehicle_group(ledger_side="RECEIVABLE", requested_vehicle_group="SEDAN", allotted_vehicle_group="SUV", charge_upgrade_to_client=True)
    assert vg_cust_up == "SUV"

    # Payable (Supplier): must resolve to the actual vehicle dispatched (SUV)
    vg_supp = resolve_billed_vehicle_group(ledger_side="PAYABLE", requested_vehicle_group="SEDAN", allotted_vehicle_group="SUV")
    assert vg_supp == "SUV"


if __name__ == "__main__":
    test_local_fare_standard()
    test_auto_slab_optimization_upgrade_only()
    test_outstation_daily_min_and_batta()
    test_airport_transfer_with_waiting()
    test_dynamic_fuel_surcharge()
    test_garage_to_garage_shed_capping()
    test_dual_ledger_settlement_and_pnl()
    test_hierarchical_rate_card_resolution_waterfall()
    test_vehicle_upgrade_protection()
    print("ALL FARE ENGINE & RATE CARD RESOLVER TESTS PASSED SUCCESSFULLY!")
