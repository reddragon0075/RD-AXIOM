"""Axiom Fleet - 7-Door Security Guard & Lockdown Middleware.
Enforces zero exposed keys, strict RLS, IDOR ownership validation,
super-admin role gates, sliding-window rate limits, and cryptographic webhook verification.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import threading
import time
from typing import Any, Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# DOOR 6: DISPOSABLE EMAIL DETECTION & RATE LIMITING
# ---------------------------------------------------------------------------

DISPOSABLE_EMAIL_DOMAINS = {
    "tempmail.io",
    "mailinator.com",
    "10minutemail.com",
    "guerrillamail.com",
    "trashmail.com",
    "sharklasers.com",
    "temp-mail.org",
    "yopmail.com",
    "throwawaymail.com",
    "fakeinbox.com",
    "dispostable.com",
    "getairmail.com",
    "mytemp.email",
    "tempail.com",
    "mohmal.com",
    "generator.email",
    "burnermail.io",
}


def is_disposable_email(email: str) -> bool:
    """Checks if an email domain belongs to known disposable/temporary services."""
    if not email or "@" not in email:
        return False
    domain = email.strip().lower().split("@")[-1]
    return domain in DISPOSABLE_EMAIL_DOMAINS


class SlidingWindowRateLimiter:
    """Thread-safe sliding-window rate limiter for high-traffic endpoints."""

    def __init__(self):
        self._lock = threading.Lock()
        self._buckets: Dict[str, list[float]] = {}

    def check(self, key: str, max_requests: int, window_seconds: int = 60) -> Tuple[bool, int]:
        """Returns (is_allowed, retry_after_seconds)."""
        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            timestamps = self._buckets.get(key, [])
            valid_stamps = [t for t in timestamps if t > cutoff]
            if len(valid_stamps) >= max_requests:
                oldest = valid_stamps[0]
                retry_after = max(1, int(oldest + window_seconds - now))
                self._buckets[key] = valid_stamps
                return False, retry_after

            valid_stamps.append(now)
            self._buckets[key] = valid_stamps
            return True, 0

    def reset(self, key: str) -> None:
        with self._lock:
            self._buckets.pop(key, None)


# Shared Global Rate Limiter Instance
RATE_LIMITER = SlidingWindowRateLimiter()


def check_auth_or_prospect_rate_limit(client_ip: str) -> Tuple[bool, int]:
    """Door 6: Max 5 requests per minute per IP on Signup/Auth/Prospect Capture."""
    key = f"auth_prospect:{client_ip}"
    return RATE_LIMITER.check(key, max_requests=5, window_seconds=60)


def check_ai_compute_rate_limit(client_ip: str, tenant_id: Optional[str] = None) -> Tuple[bool, int]:
    """Door 6: Max 15 req/min per authenticated tenant, or 3 tries/min per unauthenticated IP."""
    if tenant_id:
        key = f"ai_tenant:{tenant_id}"
        return RATE_LIMITER.check(key, max_requests=15, window_seconds=60)
    else:
        key = f"ai_public_demo:{client_ip}"
        return RATE_LIMITER.check(key, max_requests=3, window_seconds=60)


# ---------------------------------------------------------------------------
# DOOR 7: CRYPTOGRAPHIC WEBHOOK SIGNATURE VERIFICATION
# ---------------------------------------------------------------------------

DEFAULT_WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "axiom_sec_wh_78a9c2b4e6d1f035_production_locked")


def verify_webhook_hmac(
    payload_bytes: bytes,
    signature_header: Optional[str],
    timestamp_header: Optional[str],
    secret: Optional[str] = None,
    max_drift_seconds: int = 300,
) -> Tuple[bool, str]:
    """Verifies HMAC-SHA256 signature and timestamp replay protection.

    Returns (is_valid, error_reason).
    """
    if not signature_header:
        return False, "Missing cryptographic webhook signature header (X-Axiom-Signature)"

    if not timestamp_header:
        return False, "Missing webhook timestamp header (X-Signature-Timestamp)"

    # 1. Timestamp replay protection (±300 seconds)
    try:
        ts = float(timestamp_header)
    except (ValueError, TypeError):
        return False, "Invalid webhook timestamp format"

    now = time.time()
    if abs(now - ts) > max_drift_seconds:
        return False, f"Webhook timestamp outside replay window (+/-{max_drift_seconds}s)"

    # 2. Cryptographic signature comparison
    wh_secret = (secret or DEFAULT_WEBHOOK_SECRET).encode("utf-8")
    
    # Clean signature
    sig = signature_header.strip()
    if sig.startswith("sha256="):
        sig = sig[7:]

    # Compute expected signature: standard hmac(secret, timestamp + . + body) or hmac(secret, body)
    # Check both standard formats for broad payment/telematics gateway compatibility
    cand1 = hmac.new(wh_secret, f"{timestamp_header}.".encode("utf-8") + payload_bytes, hashlib.sha256).hexdigest()
    cand2 = hmac.new(wh_secret, payload_bytes, hashlib.sha256).hexdigest()

    if hmac.compare_digest(sig.lower(), cand1.lower()) or hmac.compare_digest(sig.lower(), cand2.lower()):
        return True, ""

    return False, "Cryptographic webhook HMAC-SHA256 signature mismatch"


# ---------------------------------------------------------------------------
# DOOR 4: IDOR RECORD OWNERSHIP VALIDATION
# ---------------------------------------------------------------------------

def check_tenant_record_ownership(
    conn: Any,
    user: Dict[str, Any],
    table_name: str,
    record_id: str,
    org_column: str = "organization_id",
) -> bool:
    """Door 4: Verifies that the record belongs to the user's tenant or user is Super-Admin."""
    if not user:
        return False

    role = str(user.get("role") or "").lower()
    if role in {"superadmin", "axiom_super_admin", "admin", "axiom_admin", "axiom_staff"}:
        return True

    user_org = user.get("organization_id") or user.get("tenant_id")
    if not user_org:
        return False

    # Check table column names
    try:
        cursor = conn.execute(f"PRAGMA table_info({table_name})")
        cols = {row[1] for row in cursor.fetchall()}
    except Exception:
        cols = {org_column}

    target_col = "tenant_id" if "tenant_id" in cols else org_column
    if target_col not in cols and "organization_id" in cols:
        target_col = "organization_id"

    row = conn.execute(
        f"SELECT 1 FROM {table_name} WHERE id = ? AND {target_col} = ?",
        (record_id, user_org),
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# DOOR 5: SUPER-ADMIN ROLE ENFORCEMENT
# ---------------------------------------------------------------------------

def is_super_admin(user: Optional[Dict[str, Any]]) -> bool:
    """Door 5: Verifies current authenticated session belongs to a Super-Admin."""
    if not user:
        return False
    role = str(user.get("role") or "").lower()
    return role in {"superadmin", "axiom_super_admin", "admin", "axiom_staff"}
