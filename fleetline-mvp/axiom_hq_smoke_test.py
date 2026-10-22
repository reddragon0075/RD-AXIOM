#!/usr/bin/env python3
"""Focused smoke test for Axiom HQ Super-Admin Control Plane."""

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
    with tempfile.TemporaryDirectory(prefix="axiom-hq-test-") as temp_dir:
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
            for _ in range(60):
                try:
                    status, _ = call(make_client(base)[1], base, "GET", "/api/health")
                    if status == 200:
                        break
                except Exception:
                    pass
                time.sleep(0.1)

            _, client_vendor = make_client(base)
            _, client_corp = make_client(base)
            _, client_hq = make_client(base)

            # 1. Sign up normal vendor
            call(
                client_vendor,
                base,
                "POST",
                "/api/auth/signup",
                {
                    "role": "vendor",
                    "email": "vendor.owner@externalfleet.com",
                    "password": "StrongPass123!",
                    "full_name": "External Vendor",
                    "organization_name": "External Cabs",
                    "city": "Bengaluru",
                },
            )

            # Security assertion: External vendor MUST be blocked (403) from HQ endpoints
            status, denied = call(client_vendor, base, "GET", "/api/axiom-hq/vendors")
            expect(status == 403, f"External vendor must receive 403 Forbidden on HQ vendors, got {status}")

            status, denied2 = call(client_vendor, base, "GET", "/api/axiom-hq/corporates")
            expect(status == 403, f"External vendor must receive 403 Forbidden on HQ corporates, got {status}")

            # 2. Sign up corporate admin
            call(
                client_corp,
                base,
                "POST",
                "/api/auth/signup",
                {
                    "role": "corporate",
                    "email": "corporate.lead@clientcorp.com",
                    "password": "StrongPass123!",
                    "full_name": "Corporate Admin",
                    "organization_name": "Client Corp",
                    "city": "Bengaluru",
                },
            )

            # Security assertion: Corporate admin MUST be blocked (403) from HQ endpoints
            status, denied_corp = call(client_corp, base, "GET", "/api/axiom-hq/vendors")
            expect(status == 403, f"Corporate admin must receive 403 Forbidden on HQ vendors, got {status}")

            # 3. Authenticate internal Axiom HQ Employee (@axiomfleet.in)
            status, hq_signup = call(
                client_hq,
                base,
                "POST",
                "/api/auth/signup",
                {
                    "role": "vendor",
                    "email": "superadmin@axiomfleet.in",
                    "password": "StrongPass123!",
                    "full_name": "Axiom Super Admin",
                    "organization_name": "Axiom Fleet Global HQ",
                    "city": "Bengaluru",
                },
            )
            expect(status == 201, "Axiom HQ employee account authenticated")

            # 4. Axiom HQ accesses Vendor SaaS Lifecycles
            status, vendors_res = call(client_hq, base, "GET", "/api/axiom-hq/vendors")
            expect(status == 200, "Axiom HQ employee accesses vendor subscriptions")
            vendors = vendors_res["items"]
            expect(len(vendors) >= 3, "Baseline vendor partners present")

            swift = next(v for v in vendors if v["id"] == "ven_swift")
            expect(swift["joined_date"] == "2026-01-15", "Vendor joined date verified")
            expect(swift["saas_plan"] == "ENTERPRISE_WHITE_LABEL", "Vendor SaaS plan verified")
            expect(swift["next_payment_due_date"] == "2026-11-15", "Next payment date verified")
            expect(swift["payment_status"] == "ACTIVE_PAID", "Payment status verified")
            expect(swift["owned_corporate_portals_count"] == 2, "Vendor owned corporate portals count accurate")

            # 5. Axiom HQ accesses Corporate Portal Ownership Matrix
            status, corps_res = call(client_hq, base, "GET", "/api/axiom-hq/corporates")
            expect(status == 200, "Axiom HQ employee accesses corporate portal mapping")
            corporates = corps_res["items"]
            expect(len(corporates) >= 4, "Corporate portals present")

            northstar = next(c for c in corporates if c["id"] == "corp_northstar")
            expect(northstar["owning_vendor_id"] == "ven_swift", "Corporate portal correctly mapped to owning vendor ID")
            expect(northstar["owning_vendor_name"] == "Swift Fleet Mobility Ltd", "Corporate portal maps to owning vendor name")
            expect(northstar["portal_subdomain"] == "northstar.axiomfleet.in", "Portal subdomain verified")

            # 6. Axiom HQ triggers automated SaaS payment reminder
            status, reminder_res = call(client_hq, base, "POST", "/api/axiom-hq/vendors/ven_swift/payment-reminder")
            expect(status == 200, "Payment reminder dispatched")
            expect(reminder_res["status"] == "success", "Reminder status success")
            expect("WHATSAPP_BOT" in reminder_res["channels"], "WhatsApp bot channel triggered")

            # 7. Axiom HQ Platform KPIs
            status, kpis = call(client_hq, base, "GET", "/api/axiom-hq/kpis")
            expect(status == 200, "Platform KPIs retrieved")
            expect(kpis["total_vendors"] >= 3, "Total vendors count present")
            expect(kpis["total_corporate_portals"] >= 4, "Total corporate portals count present")
            expect(kpis["monthly_saas_mrr_inr"] > 0, "Monthly SaaS MRR verified")

            print("[PASS] ALL AXIOM HQ SUPER-ADMIN SMOKE TESTS PASSED!")

        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except Exception:
                process.kill()


if __name__ == "__main__":
    main()
