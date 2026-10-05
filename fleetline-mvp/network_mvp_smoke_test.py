#!/usr/bin/env python3
"""Closed Axiom Network MVP contract test against the local SQLite backend."""

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
    jar = CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def call(opener, base: str, method: str, route: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        base + route,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with opener.open(request, timeout=8) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode())


def expect(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)
    print("PASS", message)


def signup(opener, base, role, email, organization_name, city):
    status, result = call(opener, base, "POST", "/api/auth/signup", {
        "role": role,
        "full_name": email.split("@")[0].replace(".", " ").title(),
        "email": email,
        "password": "network-pass-123",
        "phone": "+919900001111",
        "organization_name": organization_name,
        "city": city,
        "fleet_size": 20,
    })
    expect(status == 201, f"{role} signup succeeds")
    return result


def main():
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="axiom-network-") as temp_dir:
        env = os.environ.copy()
        env.update({"AXIOM_TEST_FIXTURES": "1", "PORT": str(port), "AXIOM_DB_PATH": str(Path(temp_dir) / "network.sqlite3")})
        process = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(60):
                try:
                    status, _ = call(client(), base, "GET", "/api/health")
                    if status == 200:
                        break
                except Exception:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError(process.stdout.read() if process.stdout else "server did not start")

            buyer = client()
            buyer_result = signup(buyer, base, "corporate", "network.buyer@example.com", "Network Buyer Co", "Bengaluru")
            buyer_org = buyer_result["user"]["organization"]["id"]
            vendor = client()
            vendor_result = signup(vendor, base, "vendor", "network.vendor@example.com", "Trusted Vendor Co", "Bengaluru")
            vendor_org = vendor_result["user"]["organization"]["id"]
            vendor_two = client()
            vendor_two_result = signup(vendor_two, base, "vendor", "network.vendor2@example.com", "Pune Vendor Co", "Pune")
            vendor_two_org = vendor_two_result["user"]["organization"]["id"]

            status, flag = call(buyer, base, "GET", "/api/network/v1/feature-flag")
            expect(status == 200 and flag["flag"]["enabled"] == 1, "Network MVP feature flag is enabled by default")
            status, _ = call(buyer, base, "POST", "/api/network/v1/feature-flag", {"enabled": False})
            expect(status == 200, "buyer can disable the feature flag")
            status, disabled = call(buyer, base, "GET", "/api/network/v1/programs")
            expect(status == 403 and disabled["code"] == "network_disabled", "disabled Network feature flag blocks the module")
            status, _ = call(buyer, base, "POST", "/api/network/v1/feature-flag", {"enabled": True})
            expect(status == 200, "buyer can re-enable the feature flag")

            status, program = call(buyer, base, "POST", "/api/network/v1/programs", {"code": "CORP_FY27", "name": "FY27 Corporate Mobility"})
            expect(status == 200 and program["item"]["status"] == "active", "buyer creates an active Network program")
            program_id = program["item"]["id"]

            status, invite = call(buyer, base, "POST", "/api/network/v1/invites", {"vendor_organization_id": vendor_org, "vendor_name": "Trusted Vendor Co", "idempotency_key": "invite-v1"})
            expect(status == 200 and invite["item"]["status"] == "pending", "buyer creates an invite-only vendor invite")
            invite_id = invite["item"]["id"]
            status, duplicate_invite = call(buyer, base, "POST", "/api/network/v1/invites", {"vendor_organization_id": vendor_org, "idempotency_key": "invite-v1"})
            expect(status == 200 and duplicate_invite.get("duplicate"), "invite creation is idempotent")

            status, profile = call(buyer, base, "POST", "/api/network/v1/vendor-profiles", {
                "invite_id": invite_id,
                "vendor_organization_id": vendor_org,
                "vendor_name": "Trusted Vendor Co",
                "cities": ["Bengaluru"],
                "service_types": ["employee_transport"],
                "vehicle_types": ["sedan"],
                "capabilities": ["gps", "safety_training"],
                "capacity": {"passenger_capacity": 35},
                "compliance": {"status": "approved", "valid_until": "2027-12-31"},
            })
            expect(status == 200 and profile["item"]["vendor_organization_id"] == vendor_org, "invited vendor profile is registered")
            profile_id = profile["item"]["id"]

            status, invite_two = call(buyer, base, "POST", "/api/network/v1/invites", {"vendor_organization_id": vendor_two_org, "vendor_name": "Pune Vendor Co"})
            status, profile_two = call(buyer, base, "POST", "/api/network/v1/vendor-profiles", {
                "invite_id": invite_two["item"]["id"],
                "vendor_organization_id": vendor_two_org,
                "vendor_name": "Pune Vendor Co",
                "cities": ["Pune"],
                "service_types": ["employee_transport"],
                "vehicle_types": ["sedan"],
                "capacity": {"passenger_capacity": 40},
                "compliance": {"status": "approved", "valid_until": "2027-12-31"},
            })
            expect(status == 200, "second invited vendor profile is registered")

            status, requirement = call(buyer, base, "POST", f"/api/network/v1/programs/{program_id}/requirements", {
                "reference": "REQ-BLR-001",
                "spec": {
                    "cities": ["Bengaluru"],
                    "service_types": ["employee_transport"],
                    "vehicle_types": ["sedan"],
                    "required_capabilities": ["gps"],
                    "capacity_required": 20,
                    "scheduled_at": "2026-10-01T08:00:00Z",
                    "pickup": {"label": "Whitefield"},
                    "dropoff": {"label": "Manyata Tech Park"},
                },
            })
            expect(status == 200 and requirement["item"]["status"] == "draft", "requirement starts in draft with version one")
            requirement_id = requirement["item"]["id"]
            status, published = call(buyer, base, "POST", f"/api/network/v1/requirements/{requirement_id}/versions/1/publish")
            expect(status == 200 and published["item"]["status"] == "published", "requirement version is explicitly published")

            status, match = call(buyer, base, "POST", f"/api/network/v1/requirements/{requirement_id}/match", {"idempotency_key": "match-v1"})
            expect(status == 200 and len(match["candidates"]) == 2, "matching evaluates every invited vendor profile")
            candidates = {item["vendor_profile_id"]: item for item in match["candidates"]}
            expect(candidates[profile_id]["eligible"] == 1, "hard eligibility admits the matching Bengaluru vendor")
            expect(candidates[profile_two["item"]["id"]]["eligible"] == 0 and "city_not_served" in candidates[profile_two["item"]["id"]]["exclusion_reasons_json"], "hard eligibility explains the Pune exclusion")
            status, duplicate_match = call(buyer, base, "POST", f"/api/network/v1/requirements/{requirement_id}/match", {"idempotency_key": "match-v1"})
            expect(status == 200 and duplicate_match.get("duplicate"), "matching replay is idempotent")

            status, vendor_requirement = call(vendor, base, "GET", f"/api/network/v1/requirements/{requirement_id}")
            expect(status == 200, "eligible vendor can read the operational requirement")
            expect(not vendor_requirement["item"]["versions"][0].get("payload_json"), "vendor read omits buyer version payload in the summary")
            status, vendor_requirements = call(vendor, base, "GET", "/api/network/v1/requirements")
            expect(status == 200 and any(item["id"] == requirement_id and item.get("network_vendor_profile_id") == profile_id for item in vendor_requirements["items"]), "vendor requirement workspace lists only eligible assignments")

            quote_payload = {"vendor_profile_id": profile_id, "idempotency_key": "quote-v1", "quote": {"total_paise": 125000, "currency": "INR", "line_items": [{"code": "monthly_route", "amount_paise": 125000}]}, "assumptions": {"fuel": "included"}}
            status, quote = call(vendor, base, "POST", f"/api/network/v1/requirements/{requirement_id}/quotes", quote_payload)
            expect(status == 200 and quote["item"]["current_version"]["payload_json"]["total_paise"] == 125000, "eligible vendor submits an immutable quote version")
            expect(quote["item"]["current_version"]["line_items"][0]["amount_paise"] == 125000, "quote line items are normalized under the immutable version")
            quote_id = quote["item"]["id"]
            status, duplicate_quote = call(vendor, base, "POST", f"/api/network/v1/requirements/{requirement_id}/quotes", quote_payload)
            expect(status == 200 and duplicate_quote.get("duplicate"), "quote submission is idempotent")
            status, excluded_quote = call(vendor_two, base, "POST", f"/api/network/v1/requirements/{requirement_id}/quotes", {"vendor_profile_id": profile_two["item"]["id"], "quote": {"total_paise": 99900}})
            expect(status == 404 and excluded_quote["code"] == "not_found", "ineligible vendor cannot discover or submit a quote")

            status, buyer_quotes = call(buyer, base, "GET", f"/api/network/v1/requirements/{requirement_id}/quotes")
            expect(status == 200 and buyer_quotes["confidential"], "buyer quote list is marked confidential")
            expect("payload_json" not in buyer_quotes["items"][0]["current_version"], "buyer list does not expose quote payload before comparison")
            status, vendor_compare = call(vendor, base, "GET", "/api/network/v1/comparisons/not-visible")
            expect(status == 404, "vendor cannot read an unrelated comparison")

            status, comparison = call(buyer, base, "POST", f"/api/network/v1/requirements/{requirement_id}/comparisons", {"quote_version_ids": [quote["item"]["current_version_id"]], "idempotency_key": "comparison-v1"})
            expect(status == 200 and comparison["item"]["quote_snapshots_json"][0]["quote"]["total_paise"] == 125000, "buyer comparison stores an immutable quote snapshot")
            comparison_id = comparison["item"]["id"]

            status, award = call(buyer, base, "POST", f"/api/network/v1/requirements/{requirement_id}/awards", {"comparison_id": comparison_id, "quote_version_id": quote["item"]["current_version_id"], "award_reason": "Best eligible total cost", "idempotency_key": "award-v1"})
            expect(status == 200 and award["item"]["status"] == "pending_approval", "award is created pending authorized approval")
            award_id = award["item"]["id"]
            status, blocked = call(buyer, base, "POST", f"/api/network/v1/awards/{award_id}/activate")
            expect(status == 409 and blocked["code"] == "award_not_approved", "activation blocks before award approval")

            status, approved = call(buyer, base, "POST", f"/api/network/v1/awards/{award_id}/approve", {"terms": {"slas": [{"metric": "on_time_start_pct", "target_value": 95, "unit": "percent", "severity": "critical"}]}})
            expect(status == 200 and approved["item"]["status"] == "approved", "authorized buyer approves award and creates contract checks")
            contract_id = approved["item"]["contract"]["id"]
            status, signed = call(buyer, base, "POST", f"/api/network/v1/contracts/{contract_id}/sign", {"evidence": {"document": "mock-contract-hash"}})
            expect(status == 200 and signed["item"]["status"] == "signed", "contract signature is audited")
            for check_key in ("vendor_compliance", "capacity_confirmed", "dispatch_ready"):
                status, check = call(buyer, base, "POST", f"/api/network/v1/awards/{award_id}/checks/{check_key}", {"status": "passed", "evidence": {"source": "mock_adapter", "check": check_key}})
                expect(status == 200 and check["item"]["status"] == "passed", f"activation check {check_key} records evidence")

            status, activated = call(buyer, base, "POST", f"/api/network/v1/awards/{award_id}/activate", {"idempotency_key": "activation-v1"})
            expect(status == 200 and activated["item"]["status"] == "active", "approved award activates a Fleet service order")
            expect(activated["fleet"]["booking_id"] and activated["fleet"]["duty_id"], "activation returns linked Fleet booking and duty ids")
            service_order_id = activated["item"]["id"]
            status, duplicate_activation = call(buyer, base, "POST", f"/api/network/v1/awards/{award_id}/activate", {"idempotency_key": "activation-v1"})
            expect(status == 200 and duplicate_activation.get("duplicate"), "service-order activation is idempotent")

            status, scorecard = call(buyer, base, "POST", f"/api/network/v1/service-orders/{service_order_id}/scorecards", {"period_start": "2026-10-01", "period_end": "2026-10-31", "metrics": {"on_time_start_pct": 98}, "evidence": {"gps_report": "mock://report/1"}, "idempotency_key": "scorecard-v1"})
            expect(status == 200 and scorecard["item"]["status"] == "submitted", "scorecard requires and stores evidence")
            scorecard_id = scorecard["item"]["id"]
            status, settlement = call(buyer, base, "POST", f"/api/network/v1/service-orders/{service_order_id}/settlements", {"scorecard_id": scorecard_id, "period_start": "2026-10-01", "period_end": "2026-10-31", "gross_paise": 125000, "deductions_paise": 5000, "evidence": {"scorecard_id": scorecard_id, "invoice": "mock-invoice-1"}, "idempotency_key": "settlement-v1"})
            expect(status == 200 and settlement["item"]["net_paise"] == 120000, "settlement is evidence-backed and calculates net")
            status, directory = call(buyer, base, "GET", "/api/network/v1/partner-directory")
            expect(status == 200 and any(item.get("vendor_profile_id") == profile_id for item in directory["items"]), "verified partner directory is invite-derived")
            status, associates = call(vendor, base, "GET", "/api/network/v1/associates")
            expect(status == 200 and any(item.get("invite_id") for item in associates["items"]), "associate acceptance workspace is visible to the invited vendor")
            status, version_sync = call(buyer, base, "POST", f"/api/network/v1/contracts/{contract_id}/versions", {"terms": {"rate_cards": [{"rate_code": "blr_sedan", "amount_paise": 125000, "city": "Bengaluru"}]}, "rate_cards": [{"rate_code": "blr_sedan", "amount_paise": 125000, "city": "Bengaluru"}], "idempotency_key": "contract-version-v2"})
            expect(status == 200 and version_sync["item"]["version"] == 2 and version_sync["sync"]["status"] == "sent", "contract and rate version synchronization is recorded")
            exchange_ids = []
            for exchange_type in ("booking", "duty_slip", "invoice", "operational_message"):
                status, exchange = call(buyer, base, "POST", f"/api/network/v1/service-orders/{service_order_id}/exchanges", {"exchange_type": exchange_type, "payload": {"reference": exchange_type}, "idempotency_key": f"exchange-{exchange_type}"})
                expect(status == 200 and exchange["item"]["status"] == "sent", f"{exchange_type} exchange envelope is sent")
                exchange_ids.append(exchange["item"]["id"])
            status, acknowledged = call(vendor, base, "POST", f"/api/network/v1/exchanges/{exchange_ids[0]}/acknowledge", {})
            expect(status == 200 and acknowledged["item"]["status"] == "acknowledged", "associate can acknowledge a booking exchange")
            status, sla = call(vendor, base, "POST", f"/api/network/v1/service-orders/{service_order_id}/sla-observations", {"metric": "on_time_start_pct", "target_value": 95, "observed_value": 90, "evidence": {"source": "mock"}, "idempotency_key": "sla-observation-v1"})
            expect(status == 200 and sla["item"]["status"] == "breached", "supplier SLA breach records evidence")
            status, issue = call(vendor, base, "POST", f"/api/network/v1/service-orders/{service_order_id}/issues", {"issue_type": "rejection", "reason_code": "vehicle_unavailable", "description": "Vehicle rejection before dispatch", "idempotency_key": "supplier-rejection-v1"})
            expect(status == 200 and issue["item"]["issue_type"] == "rejection", "supplier rejection is a tracked issue")
            status, discrepancy = call(buyer, base, "POST", f"/api/network/v1/service-orders/{service_order_id}/rate-discrepancies", {"expected_paise": 125000, "actual_paise": 135000, "reason": "Supplier invoice differs from synchronized rate", "idempotency_key": "rate-discrepancy-v1"})
            expect(status == 200 and discrepancy["item"]["variance_paise"] == 10000, "rate discrepancy captures variance")
            status, resolution = call(buyer, base, "POST", f"/api/network/v1/service-orders/{service_order_id}/settlement-resolutions", {"settlement_id": settlement["item"]["id"], "discrepancy_id": discrepancy["item"]["id"], "resolution_type": "credit_note", "adjustment_paise": 10000, "notes": "Apply supplier credit", "idempotency_key": "settlement-resolution-v1"})
            expect(status == 200 and resolution["item"]["status"] == "proposed", "settlement resolution can be proposed")
            status, decided = call(buyer, base, "POST", f"/api/network/v1/settlement-resolutions/{resolution['item']['id']}/decide", {"status": "accepted", "notes": "Accepted"})
            expect(status == 200 and decided["item"]["status"] == "accepted", "settlement resolution decision is auditable")
            status, events = call(buyer, base, "GET", "/api/network/v1/events")
            expect(status == 200 and any(event["event_type"] == "service_order.activated" for event in events["items"]), "Network events retain the Fleet activation audit trail")

            other_buyer = client()
            signup(other_buyer, base, "corporate", "network.other@example.com", "Other Buyer Co", "Chennai")
            status, isolated = call(other_buyer, base, "GET", f"/api/network/v1/requirements/{requirement_id}")
            expect(status == 404 and isolated["code"] == "not_found", "tenant isolation hides another buyer requirement")
            driver = client()
            status, _ = call(driver, base, "POST", "/api/auth/signup", {"role": "driver", "full_name": "Network Driver", "email": "network.driver@example.com", "password": "network-pass-123", "city": "Bengaluru"})
            expect(status == 201, "driver signup for role restriction succeeds")
            status, forbidden = call(driver, base, "GET", "/api/network/v1/programs")
            expect(status == 403 and forbidden["code"] == "role_forbidden", "driver role cannot access Network management")
            print("RESULT network MVP smoke test passed")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            if process.stdout:
                process.stdout.close()


if __name__ == "__main__":
    main()
