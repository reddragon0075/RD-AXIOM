"""Focused regression coverage for the booking/allotment parity slice.

The test uses the real local SQLite schema and handlers, not mocks, so the
same tenant, audit and idempotency boundaries exercised by the HTTP server are
covered without requiring a running process.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


DB_FILE = Path(tempfile.gettempdir()) / "axiom_booking_allotment_smoke.sqlite3"
for suffix in ("", "-wal", "-shm"):
    try:
        (Path(str(DB_FILE) + suffix)).unlink()
    except FileNotFoundError:
        pass
os.environ["AXIOM_DB_PATH"] = str(DB_FILE)
os.environ["AXIOM_TEST_FIXTURES"] = "1"

from server import db_connection, initialize_database  # noqa: E402
from backend_booking_parity import handle_booking_parity  # noqa: E402
from backend_domain import _create_driver, _create_vehicle, DomainError, new_id, now_iso  # noqa: E402
from backend_finance_parity import handle_finance_parity  # noqa: E402


ORG = "org_demo_blueorbit"
IP = "booking-smoke"


def main() -> None:
    initialize_database()
    with db_connection() as conn:
        user = dict(conn.execute("SELECT * FROM users WHERE email = 'admin@blueorbit.in'").fetchone())
        customer_id = "cust_demo_northstar"
        booking_payload = {
            "booking_reference": "SMOKE-PARENT",
            "customer_id": customer_id,
            "passenger_name": "Smoke Passenger",
            "scheduled_at": "2030-10-01T10:00:00Z",
            "pickup": {"label": "Bengaluru", "city": "bengaluru"},
            "dropoff": {"label": "Airport"},
            "duty_type": "local",
            "booking_type": "parent",
            "allotment_mode": "owned",
            "flat_rate_paise": 1200,
            "idempotency_key": "smoke-create-parent-v1",
        }
        created = handle_booking_parity(conn, user, "POST", "/api/bookings", booking_payload, IP)
        parent_id = created["item"]["id"]
        replay = handle_booking_parity(conn, user, "POST", "/api/bookings", booking_payload, IP)
        assert replay.get("idempotent_replay") is True and replay["item"]["id"] == parent_id

        children = handle_booking_parity(conn, user, "POST", f"/api/bookings/{parent_id}/split", {"dates": ["2030-10-02T10:00:00Z", "2030-10-03T10:00:00Z"]}, IP)
        assert children["count"] == 2 and all(item["parent_booking_id"] == parent_id for item in children["items"])
        assert len(handle_booking_parity(conn, user, "GET", f"/api/bookings/{parent_id}/children", {}, IP)["items"]) == 2

        confirmed = handle_booking_parity(conn, user, "POST", f"/api/bookings/{parent_id}/confirm", {"idempotency_key": "smoke-confirm-v1"}, IP)
        assert confirmed["item"]["confirmation_status"] == "confirmed"
        assert handle_booking_parity(conn, user, "POST", f"/api/bookings/{parent_id}/confirm", {"idempotency_key": "smoke-confirm-v1"}, IP)["idempotent_replay"] is True
        handle_booking_parity(conn, user, "POST", f"/api/bookings/{parent_id}/briefing", {"briefing": {"dispatch": "Call passenger"}}, IP)
        handle_booking_parity(conn, user, "POST", f"/api/bookings/{parent_id}/advance", {"amount_paise": 5000, "idempotency_key": "smoke-advance-v1"}, IP)
        attachment = handle_booking_parity(conn, user, "POST", f"/api/bookings/{parent_id}/attachments", {"filename": "voucher.pdf", "content": "proof"}, IP)
        assert attachment["item"]["sha256"]
        exported = handle_booking_parity(conn, user, "GET", f"/api/bookings/{parent_id}/export", {}, IP)
        assert "SMOKE-PARENT" in exported["content"] and exported["count"] == 3

        contract = handle_booking_parity(conn, user, "POST", "/api/pricing/contracts", {"name": "Smoke customer v1", "customer_id": customer_id, "status": "active", "version": 1}, IP)["item"]
        handle_booking_parity(conn, user, "POST", f"/api/pricing/contracts/{contract['id']}/rules", {"duty_type": "local", "package_minutes": 30, "base_paise": 1000, "extra_half_hour_paise": 200, "auto_switch": {"rules": [{"max_minutes": 60, "duty_type": "airport"}]}}, IP)
        handle_booking_parity(conn, user, "POST", "/api/fuel-rates", {"city": "bengaluru", "fuel_type": "petrol", "price_paise": 11000}, IP)
        handle_booking_parity(conn, user, "POST", "/api/fuel-surcharge-rules", {"customer_id": customer_id, "included_fuel_price_paise": 10000, "average_km_per_litre": 10}, IP)
        quote = handle_booking_parity(conn, user, "POST", "/api/pricing/quote", {"booking_id": parent_id, "duration_minutes": 90, "distance_km": 100}, IP)
        assert quote["item"]["duty_type"] == "local" and quote["item"]["breakdown"]["fuel_surcharge"]["amount_paise"] == 10000

        driver = _create_driver(conn, user, {"full_name": "Smoke Driver", "phone": "+919999999999", "city": "Bengaluru"}, IP)["item"]
        vehicle = _create_vehicle(conn, user, {"registration_number": "KA99SMOKE", "vehicle_group": "executive", "city": "Bengaluru"}, IP)["item"]
        allotted = handle_booking_parity(conn, user, "POST", f"/api/bookings/{parent_id}/allot-all", {"driver_id": driver["id"], "vehicle_id": vehicle["id"], "allotment_mode": "owned", "idempotency_key": "smoke-allot-v1"}, IP)
        assert allotted["count"] == 3 and all(item.get("duty") for item in allotted["items"])
        duty_id = allotted["items"][0]["duty"]["id"]
        arrival = handle_booking_parity(conn, user, "POST", f"/api/duties/{duty_id}/arrival", {"idempotency_key": "smoke-arrival-v1"}, IP)
        assert arrival["item"]["arrival_status"] == "arrived"

        supplier_id = new_id("supplier")
        conn.execute("INSERT INTO domain_suppliers(id, organization_id, name, supplier_type, created_at, updated_at) VALUES (?, ?, ?, 'company', ?, ?)", (supplier_id, ORG, "Smoke Supplier", now_iso(), now_iso()))
        supplier_contract = handle_booking_parity(conn, user, "POST", "/api/pricing/contracts", {"name": "Smoke supplier v1", "contract_type": "supplier", "supplier_id": supplier_id, "status": "active", "version": 1}, IP)["item"]
        handle_booking_parity(conn, user, "POST", f"/api/pricing/contracts/{supplier_contract['id']}/rules", {"duty_type": "local", "base_paise": 2200}, IP)
        supplier_quote = handle_booking_parity(conn, user, "POST", "/api/pricing/quote", {"supplier_id": supplier_id, "pricing_scope": "supplier", "duty_type": "local"}, IP)
        assert supplier_quote["item"]["contract_id"] == supplier_contract["id"] and supplier_quote["item"]["total_paise"] == 2200
        supplier_booking = handle_booking_parity(conn, user, "POST", "/api/bookings", {**booking_payload, "booking_reference": "SMOKE-SUPPLIER", "scheduled_at": "2030-11-01T10:00:00Z", "idempotency_key": "smoke-supplier-booking"}, IP)["item"]
        dispatch = handle_booking_parity(conn, user, "POST", f"/api/bookings/{supplier_booking['id']}/dispatch", {"allotment_mode": "company_supplier", "supplier_id": supplier_id, "idempotency_key": "smoke-dispatch-v1"}, IP)
        assert dispatch["item"]["allotment_mode"] == "company_supplier"
        response = handle_booking_parity(conn, user, "POST", f"/api/booking-dispatches/{dispatch['item']['id']}/respond", {"response_status": "accepted"}, IP)
        assert response["item"]["response_status"] == "accepted"

        invite_id = new_id("network_invite"); profile_id = new_id("network_profile")
        conn.execute("INSERT INTO domain_network_invites(id, organization_id, vendor_organization_id, vendor_name, invite_email, status, expires_at, created_by, created_at, accepted_at) VALUES (?, ?, ?, ?, ?, 'accepted', ?, ?, ?, ?)", (invite_id, ORG, "org_demo_network_supplier", "Invited Network Supplier", "network@example.com", "2030-12-01T00:00:00Z", user["id"], now_iso(), now_iso()))
        conn.execute("INSERT INTO domain_network_vendor_profiles(id, organization_id, vendor_organization_id, vendor_name, status, invite_id, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?)", (profile_id, ORG, "org_demo_network_supplier", "Invited Network Supplier", invite_id, user["id"], now_iso(), now_iso()))
        network_booking = handle_booking_parity(conn, user, "POST", "/api/bookings", {**booking_payload, "booking_reference": "SMOKE-NETWORK", "scheduled_at": "2030-11-02T10:00:00Z", "idempotency_key": "smoke-network-booking"}, IP)["item"]
        network_dispatch = handle_booking_parity(conn, user, "POST", f"/api/bookings/{network_booking['id']}/dispatch", {"allotment_mode": "network", "network_vendor_profile_id": profile_id, "idempotency_key": "smoke-network-dispatch-v1"}, IP)
        assert network_dispatch["item"]["network_vendor_profile_id"] == profile_id

        temporary = handle_booking_parity(conn, user, "POST", f"/api/bookings/{supplier_booking['id']}/temporary-passenger", {"passenger": {"name": "Visitor"}, "expires_at": "2030-11-01T12:00:00Z"}, IP)
        temporary_allot = handle_booking_parity(conn, user, "POST", f"/api/bookings/{supplier_booking['id']}/temporary-allotment", {"allotment_mode": "network", "expires_at": "2030-11-01T12:00:00Z"}, IP)
        assert temporary["item"]["status"] == "active" and temporary_allot["item"]["status"] == "active"

        # A completed duty gets an invoice surcharge line from the same rule.
        invoice_duty = conn.execute("SELECT * FROM domain_duties WHERE id = ?", (duty_id,)).fetchone()
        conn.execute("UPDATE domain_duties SET status = 'completed', completed_at = ?, calculation_snapshot_json = ? WHERE id = ?", (now_iso(), '{"subtotal_paise":10000,"tax_paise":1800,"total_paise":11800,"distance_km":100}', duty_id))
        invoice = handle_finance_parity(conn, user, "POST", "/api/invoices/generate", {"mode": "per_duty", "duty_ids": [duty_id], "idempotency_key": "smoke-invoice-v1"}, IP)
        generated = invoice["invoices"][0]
        assert generated["fuel_surcharge_paise"] == 10000
        assert any(line["code"] == "fuel_surcharge" for line in generated["lines"])

        # Cross-tenant ownership is enforced on both ordinary and lifecycle routes.
        other = dict(user); other["organization_id"] = "org_not_theirs"
        try:
            handle_booking_parity(conn, other, "POST", f"/api/bookings/{parent_id}/confirm", {}, IP)
        except DomainError as exc:
            assert exc.status == 404
        else:
            raise AssertionError("cross-tenant booking action was accepted")

        print("RESULT booking allotment smoke test passed")


if __name__ == "__main__":
    main()
