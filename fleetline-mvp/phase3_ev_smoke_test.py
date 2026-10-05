#!/usr/bin/env python3
"""Fresh SQLite smoke coverage for EV, charging and sustainability reporting contracts."""
from __future__ import annotations
import sys

import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def client():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def call(opener, base, method, route, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{base}{route}", data=body, method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with opener.open(request, timeout=8) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode())


def expect(condition, message):
    if not condition:
        raise AssertionError(message)
    print("PASS", message)


def signup(opener, base, email, name):
    status, result = call(opener, base, "POST", "/api/auth/signup", {
        "role": "vendor", "full_name": name, "email": email,
        "password": "phase3-ev-smoke-password", "organization_name": name + " Fleet",
        "city": "Bengaluru", "fleet_size": 12,
    })
    expect(status == 201 and result.get("user", {}).get("organization"), name + " signup succeeds")


def main():
    port = free_port(); base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="axiom-phase3-ev-") as temp:
        env = os.environ.copy(); env.update({"AXIOM_TEST_FIXTURES": "1", "PORT": str(port), "AXIOM_DB_PATH": str(Path(temp) / "ev.sqlite3")})
        process = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            probe = client()
            for _ in range(80):
                try:
                    if call(probe, base, "GET", "/api/health")[0] == 200: break
                except Exception: pass
                time.sleep(0.1)
            else: raise RuntimeError(process.stdout.read() if process.stdout else "backend did not start")

            tenant = client(); other = client()
            signup(tenant, base, "phase3.ev@example.com", "EV Smoke")
            signup(other, base, "phase3.ev.other@example.com", "EV Other")

            status, vehicle = call(tenant, base, "POST", "/api/vehicles", {
                "registration_number": "KA 99 EV 0001", "vehicle_type": "sedan", "vehicle_group": "EV executive",
                "make_model": "Axiom Volt", "city": "Bengaluru", "status": "available", "fuel_type": "ev",
                "ev_eligible": True, "battery_capacity_kwh": 60, "usable_range_km": 180,
                "energy_consumption_kwh_per_km": 0.16, "charging_connector": "CCS2",
                "charging_power_kw": 60, "seating_capacity": 4,
            })
            expect(status == 201 and vehicle["item"]["ev_eligible"] == 1, "EV vehicle persists additive eligibility fields")
            vehicle_id = vehicle["item"]["id"]

            status, station = call(tenant, base, "POST", "/api/phase3/sustainability/charging-stations", {
                "region_code": "IN-KA", "name": "Smoke fast charger", "location_label": "Bengaluru depot",
                "connector_types": ["CCS2"], "total_ports": 4, "available_ports": 2,
                "power_kw": 60, "energy_price_per_kwh_minor": 950,
            })
            expect(status == 200 and station["item"]["available_ports"] == 2 and station["audit_reference"], "charging station stores ports, connector, power, price and audit reference")
            station_id = station["item"]["id"]
            status, stations_other = call(other, base, "GET", "/api/phase3/sustainability/charging-stations")
            expect(status == 200 and not stations_other["items"], "charging stations are tenant isolated")

            status, eligibility = call(tenant, base, "POST", "/api/phase3/sustainability/ev-eligibility", {
                "vehicle_id": vehicle_id, "distance_km": 210, "passenger_count": 3,
                "reserve_pct": 15, "deadhead_km": 5, "charging_connector": "CCS2", "region_code": "IN-KA",
            })
            item = eligibility.get("item", {})
            expect(status == 200 and item["eligibility_status"] == "eligible_with_charge", "EV eligibility reports reserve range and compatible charging stop")
            expect(item["energy_kwh"] > 0 and item["energy_cost_minor"] > 0 and item["baseline_emissions_kg"] > item["emissions_kg"], "EV eligibility calculates energy cost and avoided emissions")

            status, booking = call(tenant, base, "POST", "/api/bookings", {
                "passenger_name": "EV Passenger", "pickup": {"label": "Bengaluru depot"},
                "dropoff": {"label": "Airport"}, "scheduled_at": "2026-09-22T09:00:00Z", "duty_type": "airport",
            })
            expect(status == 201, "EV smoke booking created")
            status, duty = call(tenant, base, "POST", "/api/duties", {"booking_id": booking["item"]["id"], "vehicle_id": vehicle_id, "reporting_at": "2026-09-22T09:00:00Z"})
            expect(status == 201, "EV smoke duty created with EV vehicle")
            duty_id = duty["item"]["id"]

            status, trip = call(tenant, base, "POST", "/api/phase3/sustainability/trips", {
                "duty_id": duty_id, "distance_km": 120, "passenger_count": 2,
                "charging_station_id": station_id, "charging_connector": "CCS2", "region_code": "IN-KA",
            })
            trip_item = trip.get("items", [{}])[0]
            expect(status == 200 and trip_item["fuel_type"] == "ev" and trip_item["energy_kwh"] > 0, "enriched sustainability trip stores EV energy evidence")
            expect(trip_item["emissions_per_passenger_km_g"] > 0 and trip_item["avoided_emissions_kg"] > 0 and trip_item["factor_version"] == "factor-v1", "trip stores intensity, baseline comparison and factor version")

            status, report = call(tenant, base, "GET", "/api/phase3/sustainability/report?region_code=IN-KA&period_start=2026-09-01&period_end=2026-09-30")
            expect(status == 200 and report["reporting_version"] == "sustainability-report-v2" and report["total_energy_kwh"] > 0, "period and regional report includes energy and report version")
            expect(report["audit_reference"], "report generation returns an audit reference")

            status, patched = call(tenant, base, "PATCH", f"/api/phase3/sustainability/charging-stations/{station_id}", {"available_ports": 1})
            expect(status == 200 and patched["item"]["available_ports"] == 1, "charging station availability can be updated")
            status, removed = call(tenant, base, "DELETE", f"/api/phase3/sustainability/charging-stations/{station_id}")
            expect(status == 200 and removed["item"]["status"] == "inactive", "charging station deactivation is auditable")
        finally:
            process.terminate(); process.wait(timeout=5)

    print("RESULT Phase 3 EV smoke test passed")


if __name__ == "__main__":
    main()
