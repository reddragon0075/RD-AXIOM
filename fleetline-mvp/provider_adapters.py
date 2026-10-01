"""Mock-first provider contracts for the Axiom Fleet domain core.

The local backend uses these deterministic adapters until project credentials are
available. Production implementations should keep the same method contracts and
move secrets/server calls behind an Edge Function or backend worker.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderResult:
    ok: bool
    status: str
    provider: str
    reference: str
    payload: dict[str, Any]


class MockPaymentProvider:
    name = "mock_payment"

    def create_payment(self, *, amount_paise: int, currency: str = "INR", idempotency_key: str | None = None, metadata: dict[str, Any] | None = None) -> ProviderResult:
        if amount_paise <= 0:
            raise ValueError("amount_paise must be positive")
        key = idempotency_key or f"{amount_paise}:{time.time_ns()}"
        reference = "mock_pay_" + hashlib.sha256(key.encode()).hexdigest()[:18]
        return ProviderResult(True, "succeeded", self.name, reference, {
            "amount_paise": amount_paise,
            "currency": currency,
            "idempotency_key": idempotency_key,
            "metadata": metadata or {},
        })

    def verify_webhook(self, payload: dict[str, Any], signature: str | None = None) -> ProviderResult:
        reference = str(payload.get("reference") or payload.get("id") or "mock_webhook")
        return ProviderResult(True, "verified", self.name, reference, {"signature_valid": True, "payload": payload})


class MockMessagingProvider:
    name = "mock_messaging"

    def send(self, *, channel: str, recipient: str, template: str, variables: dict[str, Any] | None = None, idempotency_key: str | None = None) -> ProviderResult:
        key = idempotency_key or f"{channel}:{recipient}:{template}:{time.time_ns()}"
        reference = "mock_msg_" + hashlib.sha256(key.encode()).hexdigest()[:18]
        return ProviderResult(True, "queued", self.name, reference, {
            "channel": channel,
            "recipient": recipient,
            "template": template,
            "variables": variables or {},
        })


class MockTelephonyProvider:
    name = "mock_telephony"

    def create_masked_call(self, *, from_number: str, to_number: str, context: str, idempotency_key: str | None = None) -> ProviderResult:
        key = idempotency_key or f"{from_number}:{to_number}:{context}:{time.time_ns()}"
        reference = "mock_call_" + hashlib.sha256(key.encode()).hexdigest()[:18]
        return ProviderResult(True, "queued", self.name, reference, {
            "from": from_number,
            "to": to_number,
            "context": context,
            "masked": True,
        })


class MockMapsProvider:
    name = "mock_maps"

    def geocode(self, query: str) -> ProviderResult:
        digest = hashlib.sha256(query.strip().lower().encode()).digest()
        latitude = round(8 + digest[0] / 255 * 22, 6)
        longitude = round(68 + digest[1] / 255 * 30, 6)
        return ProviderResult(True, "resolved", self.name, "mock_geo_" + digest.hex()[:16], {
            "query": query,
            "latitude": latitude,
            "longitude": longitude,
        })

    def route(self, *, pickup: dict[str, Any], dropoff: dict[str, Any], waypoints: list[dict[str, Any]] | None = None) -> ProviderResult:
        points = [pickup, *(waypoints or []), dropoff]
        return ProviderResult(True, "estimated", self.name, "mock_route_" + hashlib.sha256(repr(points).encode()).hexdigest()[:16], {
            "points": points,
            "distance_km": max(1, len(points) * 7),
            "duration_minutes": max(10, len(points) * 24),
            "polyline": "mock-polyline",
        })

    def places(self, *, query: str, location: dict[str, Any] | None = None) -> ProviderResult:
        """Google Places-compatible contract without making a network call."""
        digest = hashlib.sha256(query.strip().lower().encode()).hexdigest()
        latitude = round(8 + int(digest[:2], 16) / 255 * 22, 6)
        longitude = round(68 + int(digest[2:4], 16) / 255 * 30, 6)
        return ProviderResult(True, "resolved", self.name, "mock_place_" + digest[:16], {
            "query": query,
            "location": location or {},
            "predictions": [{
                "place_id": "mock_place_id_" + digest[:18],
                "description": query.strip(),
                "location": {"latitude": latitude, "longitude": longitude},
                "provider": self.name,
            }],
        })

    def navigation(self, *, pickup: dict[str, Any], dropoff: dict[str, Any], waypoints: list[dict[str, Any]] | None = None, mode: str = "driving") -> ProviderResult:
        routed = self.route(pickup=pickup, dropoff=dropoff, waypoints=waypoints)
        return ProviderResult(routed.ok, "ready", self.name, "mock_nav_" + hashlib.sha256(repr([pickup, dropoff, waypoints, mode]).encode()).hexdigest()[:16], {
            **routed.payload,
            "mode": mode,
            "deep_link": "https://maps.google.com/?api=1&destination=" + str(dropoff.get("label") or dropoff.get("latitude") or ""),
        })


class MockEInvoiceProvider:
    name = "mock_einvoice"

    def issue(self, *, invoice_number: str, total_paise: int, gstin: str | None = None, idempotency_key: str | None = None) -> ProviderResult:
        key = idempotency_key or invoice_number
        reference = "mock_irn_" + hashlib.sha256(key.encode()).hexdigest()[:24]
        return ProviderResult(True, "issued", self.name, reference, {
            "invoice_number": invoice_number,
            "total_paise": total_paise,
            "gstin": gstin or "",
            "qr_payload": f"AXIOM|{invoice_number}|{total_paise}|{reference}",
        })

    def cancel(self, *, irn: str, reason: str) -> ProviderResult:
        return ProviderResult(True, "cancelled", self.name, irn, {"reason": reason})


class MockHRMSProvider:
    """Deterministic HRMS boundary; replace with a signed webhook/worker adapter in production."""
    name = "mock_hrms"

    def sync(self, *, records: list[dict[str, Any]], idempotency_key: str | None = None) -> ProviderResult:
        key = idempotency_key or repr(records)
        reference = "mock_hrms_" + hashlib.sha256(key.encode()).hexdigest()[:18]
        return ProviderResult(True, "accepted", self.name, reference, {"records_received": len(records), "idempotency_key": idempotency_key})


class MockGPSProvider:
    """Deterministic telematics boundary for signed position batches."""
    name = "mock_gps"

    def ingest(self, *, positions: list[dict[str, Any]], idempotency_key: str | None = None) -> ProviderResult:
        key = idempotency_key or repr(positions)
        reference = "mock_gps_" + hashlib.sha256(key.encode()).hexdigest()[:18]
        return ProviderResult(True, "accepted", self.name, reference, {"positions_received": len(positions), "idempotency_key": idempotency_key})


class MockStorageProvider:
    name = "mock_storage"

    def register_attachment(self, *, organization_id: str, entity_type: str, entity_id: str, filename: str, content_type: str, size_bytes: int) -> ProviderResult:
        safe_name = filename.replace("/", "_").replace("\\", "_")
        path = f"mock/{organization_id}/{entity_type}/{entity_id}/{safe_name}"
        return ProviderResult(True, "registered", self.name, path, {
            "storage_path": path,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "signed_url": f"/mock-storage/{path}",
        })


@dataclass
class ProviderRegistry:
    payments: MockPaymentProvider
    messaging: MockMessagingProvider
    telephony: MockTelephonyProvider
    maps: MockMapsProvider
    einvoice: MockEInvoiceProvider
    storage: MockStorageProvider
    hrms: MockHRMSProvider
    gps: MockGPSProvider

    @classmethod
    def mock(cls) -> "ProviderRegistry":
        return cls(
            payments=MockPaymentProvider(),
            messaging=MockMessagingProvider(),
            telephony=MockTelephonyProvider(),
            maps=MockMapsProvider(),
            einvoice=MockEInvoiceProvider(),
            storage=MockStorageProvider(),
            hrms=MockHRMSProvider(),
            gps=MockGPSProvider(),
        )


DEFAULT_PROVIDERS = ProviderRegistry.mock()
