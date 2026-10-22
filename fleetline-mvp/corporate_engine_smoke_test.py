#!/usr/bin/env python3
"""End-to-end smoke coverage for Corporate Engine API (Bands, Waterfall, Demotion, REA)."""

from __future__ import annotations
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from backend_smoke_test import call, expect, free_port, make_client

ROOT = Path(__file__).resolve().parent


def main() -> None:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="axiom-corporate-engine-") as temp_dir:
        env = os.environ.copy()
        env.update({
            "PORT": str(port),
            "AXIOM_DB_PATH": str(Path(temp_dir) / "axiom.sqlite3"),
            "AXIOM_ALLOW_DEMO_ACCOUNT": "0",
        })
        process = subprocess.Popen(
            [sys.executable, "server.py"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            # Wait for server ready
            for _ in range(60):
                try:
                    status, _ = call(make_client(base)[1], base, "GET", "/api/health")
                    if status == 200:
                        break
                except Exception:
                    pass
                time.sleep(0.1)

            _, client = make_client(base)

            # 1. Signup vendor
            status, signup = call(
                client,
                base,
                "POST",
                "/api/auth/signup",
                {
                    "role": "vendor",
                    "email": "corporate.engine@example.com",
                    "password": "StrongPass123!",
                    "full_name": "Engine Admin",
                    "organization_name": "Axiom Corporate Org",
                    "city": "Bengaluru",
                },
            )
            expect(status == 201, "corporate engine authenticates vendor owner")

            # 2. Employee Bands API
            status, band_res = call(
                client,
                base,
                "POST",
                "/api/corporate/bands",
                {
                    "band_name": "L2-Senior-Manager",
                    "allowed_vehicle_groups": ["SEDAN", "EV_COMPACT"],
                    "extended_vehicle_groups": ["SUV_PRIME"],
                    "allowed_duty_types": ["AIRPORT_DROP", "8HR_80KM"],
                    "allowed_cities": ["Bengaluru", "Hyderabad"],
                    "allow_custom_passengers": False,
                    "enable_auto_allotment": True,
                    "skip_approval_start_hour": 21,
                    "skip_approval_end_hour": 6,
                },
            )
            expect(status == 200 and band_res.get("status") == "success", "employee band created")

            status, bands = call(client, base, "GET", "/api/corporate/bands")
            expect(status == 200 and len(bands["items"]) >= 1, "employee bands fetched")
            created_band = bands["items"][0]
            expect(created_band["band_name"] == "L2-Senior-Manager", "band attributes preserved")

            # 3. Evaluate Booking Policy API
            status, eval_res = call(
                client,
                base,
                "POST",
                "/api/corporate/evaluate-booking",
                {
                    "band": created_band,
                    "sla": {
                        "booking_lead_sla_mins": 60,
                        "cancellation_cutoff_sla_mins": 120,
                    },
                    "booking": {
                        "pickup_time": "2026-10-22T22:00:00Z",  # In night shift window (21 to 6)
                        "city": "Bengaluru",
                        "duty_type": "AIRPORT_DROP",
                        "vehicle_group": "SEDAN",
                        "requires_manager_approval": True,
                    },
                },
            )
            expect(status == 200 and eval_res["allowed"] is True, "policy evaluation allows valid booking")
            expect(eval_res["status"] == "CONFIRMED", "night shift booking auto-approves")

            # 4. Waterfall Rules & Queue Ranking API
            # Rule A: Tier 1, Target 70%, Current 60% -> Deficit 10%
            call(
                client,
                base,
                "POST",
                "/api/corporate/waterfall/rules",
                {
                    "supplier_id": "sup-vendor-a",
                    "supplier_name": "Swift Fleet",
                    "city": "Bengaluru",
                    "vehicle_group": "SEDAN",
                    "priority_tier": 1,
                    "target_allocation_pct": 70.0,
                    "current_month_share_pct": 60.0,
                    "reliability_score": 95.0,
                },
            )
            # Rule B: Tier 1, Target 30%, Current 10% -> Deficit 20% (Should rank first due to higher deficit)
            call(
                client,
                base,
                "POST",
                "/api/corporate/waterfall/rules",
                {
                    "supplier_id": "sup-vendor-b",
                    "supplier_name": "Express Cabs",
                    "city": "Bengaluru",
                    "vehicle_group": "SEDAN",
                    "priority_tier": 1,
                    "target_allocation_pct": 30.0,
                    "current_month_share_pct": 10.0,
                    "reliability_score": 90.0,
                },
            )

            status, queue_res = call(
                client,
                base,
                "POST",
                "/api/corporate/waterfall/queue",
                {"already_tried_supplier_ids": []},
            )
            expect(status == 200, "waterfall queue computed")
            queue = queue_res["queue"]
            expect(len(queue) >= 2, "waterfall queue contains eligible suppliers")
            expect(queue[0]["supplier_id"] == "sup-vendor-b", "supplier with highest share deficit ranks first")

            # 5. Demotion API
            status, demote_res = call(
                client,
                base,
                "POST",
                "/api/corporate/demotion/evaluate",
                {
                    "supplier_id": "sup-vendor-b",
                    "penalty_type": "TIMEOUT",
                    "recent_timeouts": 1,
                },
            )
            expect(status == 200, "penalty applied to supplier reliability")
            expect(demote_res["updated_score"] == 85.0, "penalty deducted 5 points from 90 to 85")

            # 6. REA Accounting Duality API
            status, rea_res = call(
                client,
                base,
                "POST",
                "/api/corporate/rea/duality",
                {
                    "booking_id": "bk-smoke-corp-001",
                    "corporate_name": "Acme Global India",
                    "supplier_name": "Swift Fleet",
                    "taxable_ar": 3500.0,
                    "gst_ar": 175.0,
                    "taxable_ap": 2800.0,
                    "gst_ap": 140.0,
                    "tolls": 250.0,
                },
            )
            expect(status == 200, "REA duality recorded")
            expect(rea_res["status"] == "BALANCED", "REA journal is mathematically balanced")
            expect(rea_res["total_debits"] == rea_res["total_credits"], "total debits equal total credits")
            expect(rea_res["gross_margin"] == 700.0, "gross margin calculated correctly")

            status, rea_list = call(client, base, "GET", "/api/corporate/rea/duality")
            expect(status == 200 and len(rea_list["items"]) >= 1, "REA dualities listed successfully")

            print("[PASS] ALL CORPORATE ENGINE SMOKE TESTS PASSED!")

        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except Exception:
                process.kill()


if __name__ == "__main__":
    main()
