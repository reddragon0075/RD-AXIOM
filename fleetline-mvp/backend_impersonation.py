"""Axiom Mobility (Fleetline) Cryptographic Impersonation & SaaS Management Service.

Provides:
1. 30-minute scoped Shadow JWT generation & cryptographic HMAC-SHA256 signing.
2. Shadow Session Lifecycle Management (Audit Log creation, mode switching, termination).
3. Read-Only Mutation Guardrail Middleware (blocks POST/PUT/DELETE for safe shadow inspection).
4. Multi-Tenant SaaS Subscriptions, SLA Tier mapping, Wallets, and Feature Flags API.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

SHADOW_SECRET = os.environ.get("AXIOM_SHADOW_SECRET", "axiom_shadow_jwt_secret_key_prod_2026")
DEFAULT_EXPIRY_SECONDS = 1800  # 30 minutes


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    padding = "=" * (4 - (len(s) % 4)) if len(s) % 4 != 0 else ""
    return base64.urlsafe_b64decode((s + padding).encode("utf-8"))


def mint_shadow_jwt(
    tenant_id: int,
    tenant_name: str,
    actor_admin_id: str,
    vendor_user_id: str,
    impersonation_mode: str = "READ_ONLY",
    expires_in_seconds: int = DEFAULT_EXPIRY_SECONDS
) -> Tuple[str, int]:
    """Generates a cryptographic 30-minute scoped Shadow JWT."""
    now_ts = int(time.time())
    exp_ts = now_ts + expires_in_seconds

    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
      "sub": vendor_user_id,
      "tenant_id": int(tenant_id),
      "tenant_name": tenant_name,
      "actor_admin_id": actor_admin_id,
      "impersonation_mode": impersonation_mode,
      "iat": now_ts,
      "exp": exp_ts,
      "iss": "axiom-fleet-superadmin"
    }

    hdr_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{hdr_b64}.{payload_b64}".encode("utf-8")
    sig = hmac.new(SHADOW_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = _b64url_encode(sig)

    token = f"{hdr_b64}.{payload_b64}.{sig_b64}"
    return token, exp_ts


def verify_shadow_jwt(token: str) -> Optional[Dict[str, Any]]:
    """Verifies and decodes a Shadow JWT. Returns payload if valid, None if expired or invalid."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        hdr_b64, payload_b64, sig_b64 = parts
        signing_input = f"{hdr_b64}.{payload_b64}".encode("utf-8")
        expected_sig = hmac.new(SHADOW_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()
        actual_sig = _b64url_decode(sig_b64)

        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        if payload.get("exp", 0) < int(time.time()):
            return None  # Expired

        return payload
    except Exception:
        return None


def initialize_impersonation_schema(conn: sqlite3.Connection) -> None:
    """Initializes SQLite schema for multi-tenant SaaS and impersonation logs."""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS tenant_subscriptions (
        tenant_id INTEGER PRIMARY KEY,
        tenant_uuid TEXT NOT NULL UNIQUE,
        tenant_name TEXT NOT NULL,
        plan_tier TEXT NOT NULL DEFAULT 'GROWTH',
        subscription_status TEXT NOT NULL DEFAULT 'ACTIVE',
        mrr_paise INTEGER NOT NULL DEFAULT 500000,
        billing_cycle TEXT NOT NULL DEFAULT 'MONTHLY',
        current_period_start TEXT NOT NULL,
        current_period_end TEXT NOT NULL,
        corporate_quota_total INTEGER NOT NULL DEFAULT 5,
        corporate_quota_used INTEGER NOT NULL DEFAULT 1,
        trip_quota_total INTEGER NOT NULL DEFAULT 100,
        trip_quota_used INTEGER NOT NULL DEFAULT 14,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS tenant_wallets (
        tenant_id INTEGER PRIMARY KEY,
        balance_paise INTEGER NOT NULL DEFAULT 0,
        currency TEXT NOT NULL DEFAULT 'INR',
        auto_recharge_enabled INTEGER NOT NULL DEFAULT 0,
        last_topup_at TEXT,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS tenant_feature_flags (
        tenant_id INTEGER PRIMARY KEY,
        network_exchange_enabled INTEGER NOT NULL DEFAULT 1,
        marketplace_enabled INTEGER NOT NULL DEFAULT 1,
        parse_ai_intake_enabled INTEGER NOT NULL DEFAULT 1,
        whatsapp_bot_enabled INTEGER NOT NULL DEFAULT 0,
        posh_compliance_enforced INTEGER NOT NULL DEFAULT 1,
        distance_fraud_gate_enforced INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS admin_impersonation_audit_logs (
        id TEXT PRIMARY KEY,
        actor_admin_id TEXT NOT NULL,
        actor_admin_email TEXT NOT NULL,
        target_tenant_id INTEGER NOT NULL,
        target_tenant_name TEXT NOT NULL,
        target_vendor_user_id TEXT NOT NULL,
        impersonation_mode TEXT NOT NULL DEFAULT 'READ_ONLY',
        reason_code TEXT,
        session_token_hash TEXT NOT NULL,
        ip_address TEXT NOT NULL,
        user_agent TEXT,
        started_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        ended_at TEXT,
        duration_seconds INTEGER,
        mutation_count INTEGER NOT NULL DEFAULT 0,
        session_status TEXT NOT NULL DEFAULT 'ACTIVE'
    );
    """)

    # Seed baseline fixtures if empty
    cur = conn.execute("SELECT count(*) FROM tenant_subscriptions")
    if cur.fetchone()[0] == 0:
        now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
        end_iso = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)).isoformat()
        tenants = [
            (169, "ten_zion_169", "Zion Travels", "GROWTH", "ACTIVE", 500000, "MONTHLY", now_iso, end_iso, 5, 1, 100, 14, 500, 1, 1, 1, 0),
            (170, "ten_apex_170", "Apex Cabs & Logistics", "ENTERPRISE", "ACTIVE", 2500000, "ANNUAL", now_iso, end_iso, 25, 18, 1500, 1120, 425000, 1, 1, 1, 1),
            (171, "ten_bluestar_171", "BlueStar Mobility", "GROWTH", "SLA_PROBATION", 500000, "MONTHLY", now_iso, end_iso, 5, 2, 100, 42, 120000, 0, 1, 1, 0),
            (172, "ten_garuda_172", "Garuda City Fleets", "SOLO", "TRIAL", 0, "MONTHLY", now_iso, end_iso, 1, 1, 20, 19, 0, 0, 0, 1, 0),
            (173, "ten_royal_173", "Royal Executive Rentals", "GROWTH", "PAST_DUE", 500000, "MONTHLY", now_iso, end_iso, 5, 3, 100, 88, 25000, 1, 1, 0, 0),
        ]
        for t in tenants:
            conn.execute("""
            INSERT INTO tenant_subscriptions (
                tenant_id, tenant_uuid, tenant_name, plan_tier, subscription_status, mrr_paise,
                billing_cycle, current_period_start, current_period_end, corporate_quota_total,
                corporate_quota_used, trip_quota_total, trip_quota_used, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (t[0], t[1], t[2], t[3], t[4], t[5], t[6], t[7], t[8], t[9], t[10], t[11], t[12], now_iso, now_iso))

            conn.execute("""
            INSERT INTO tenant_wallets (tenant_id, balance_paise, currency, updated_at)
            VALUES (?, ?, 'INR', ?)
            """, (t[0], t[13], now_iso))

            conn.execute("""
            INSERT INTO tenant_feature_flags (
                tenant_id, network_exchange_enabled, marketplace_enabled, parse_ai_intake_enabled,
                whatsapp_bot_enabled, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """, (t[0], t[14], t[15], t[16], t[17], now_iso))
        conn.commit()


def check_read_only_mutation_guard(
    method: str,
    path: str,
    shadow_payload: Optional[Dict[str, Any]]
) -> Optional[Tuple[int, Dict[str, Any]]]:
    """Inspects HTTP mutations during a shadow session.
    
    If in READ_ONLY shadow mode, returns HTTP 403 Forbidden on any write attempt.
    """
    if not shadow_payload:
        return None

    if shadow_payload.get("impersonation_mode") == "READ_ONLY":
        if method.upper() in ("POST", "PUT", "DELETE", "PATCH"):
            # Exclude session termination / mode update routes
            if path in ("/api/v1/admin/impersonate/end", "/api/v1/admin/impersonate/mode"):
                return None
            return (403, {
                "error": "READ_ONLY_SHADOW_MODE",
                "message": "Mutations blocked in read-only shadow session. Switch to Read-Write mode with a valid reason code to modify data.",
                "tenant_id": shadow_payload.get("tenant_id"),
                "actor_admin_id": shadow_payload.get("actor_admin_id")
            })
    return None


def handle_impersonation_api(
    conn: sqlite3.Connection,
    actor_user: Dict[str, Any],
    method: str,
    path: str,
    body: Dict[str, Any],
    ip_address: str = "127.0.0.1"
) -> Dict[str, Any]:
    """Controller for admin impersonation and SaaS tenant management."""
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()

    # RBAC Guard: Restrict SaaS Console and Impersonation APIs to verified superadmins and Axiom staff
    u_dict = dict(actor_user) if hasattr(actor_user, "keys") else (actor_user if isinstance(actor_user, dict) else {})
    is_admin = (
        u_dict.get("role") in ("admin", "superadmin")
        or u_dict.get("is_axiom_hq") is True
        or str(u_dict.get("email") or "").endswith(("@axiomfleet.in", "@axiomfleet.com"))
    )
    if not is_admin:
        return {
            "error": "FORBIDDEN",
            "message": "Super-Admin or Axiom HQ privileges required for SaaS management and impersonation.",
            "code": 403,
            "status": 403
        }

    # 1. POST /api/v1/admin/impersonate
    if path == "/api/v1/admin/impersonate" and method == "POST":
        target_tenant_id = int(body.get("tenant_id", 169))
        impersonation_mode = body.get("impersonation_mode", "READ_ONLY").upper()
        if impersonation_mode not in ("READ_ONLY", "READ_WRITE"):
            impersonation_mode = "READ_ONLY"
        reason_code = body.get("reason_code", "Support Troubleshooting")

        cur = conn.execute("SELECT tenant_id, tenant_name, tenant_uuid FROM tenant_subscriptions WHERE tenant_id = ?", (target_tenant_id,))
        row = cur.fetchone()
        if not row:
            t_name = f"Tenant #{target_tenant_id}"
            v_user = f"vendor_usr_{target_tenant_id}"
        else:
            t_name = row[1]
            v_user = f"usr_{row[2]}"

        u_dict = dict(actor_user) if hasattr(actor_user, "keys") else (actor_user if isinstance(actor_user, dict) else {})
        admin_id = u_dict.get("id", "usr_superadmin")
        admin_email = u_dict.get("email", "ops-head@axiomfleet.com")

        token, exp_ts = mint_shadow_jwt(target_tenant_id, t_name, admin_id, v_user, impersonation_mode)
        session_id = f"imp_{uuid.uuid4().hex[:12]}"
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        exp_iso = dt.datetime.fromtimestamp(exp_ts, dt.timezone.utc).isoformat()

        conn.execute("""
        INSERT INTO admin_impersonation_audit_logs (
            id, actor_admin_id, actor_admin_email, target_tenant_id, target_tenant_name,
            target_vendor_user_id, impersonation_mode, reason_code, session_token_hash,
            ip_address, started_at, expires_at, session_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE')
        """, (session_id, admin_id, admin_email, target_tenant_id, t_name, v_user, impersonation_mode, reason_code, token_hash, ip_address, now_iso, exp_iso))
        conn.commit()

        return {
            "ok": True,
            "session_id": session_id,
            "shadow_token": token,
            "expires_at": exp_iso,
            "expires_in_seconds": DEFAULT_EXPIRY_SECONDS,
            "impersonation_mode": impersonation_mode,
            "tenant": {
                "id": target_tenant_id,
                "name": t_name,
                "vendor_user_id": v_user
            },
            "message": f"Entering shadow session for {t_name} (#{target_tenant_id}). Every action is audit logged."
        }

    # 2. POST /api/v1/admin/impersonate/end
    elif path == "/api/v1/admin/impersonate/end" and method == "POST":
        session_id = body.get("session_id")
        if session_id:
            conn.execute("""
            UPDATE admin_impersonation_audit_logs
            SET session_status = 'ENDED_BY_USER', ended_at = ?
            WHERE id = ? AND session_status = 'ACTIVE'
            """, (now_iso, session_id))
            conn.commit()
        return {"ok": True, "message": "Shadow impersonation session terminated successfully."}

    # 3. POST /api/v1/admin/impersonate/mode
    elif path == "/api/v1/admin/impersonate/mode" and method == "POST":
        session_id = body.get("session_id")
        new_mode = body.get("impersonation_mode", "READ_ONLY").upper()
        reason_code = body.get("reason_code", "Support Mode Switch")
        if session_id and new_mode in ("READ_ONLY", "READ_WRITE"):
            conn.execute("""
            UPDATE admin_impersonation_audit_logs
            SET impersonation_mode = ?, reason_code = ?
            WHERE id = ? AND session_status = 'ACTIVE'
            """, (new_mode, reason_code, session_id))
            conn.commit()
        return {"ok": True, "impersonation_mode": new_mode, "message": f"Switched mode to {new_mode}."}

    # 4. GET /api/v1/admin/saas/tenants
    elif path == "/api/v1/admin/saas/tenants" and method == "GET":
        cur = conn.execute("""
        SELECT 
            s.tenant_id, s.tenant_uuid, s.tenant_name, s.plan_tier, s.subscription_status,
            s.mrr_paise, s.billing_cycle, s.current_period_end,
            s.corporate_quota_total, s.corporate_quota_used,
            s.trip_quota_total, s.trip_quota_used,
            w.balance_paise,
            f.network_exchange_enabled, f.marketplace_enabled, f.parse_ai_intake_enabled, f.whatsapp_bot_enabled
        FROM tenant_subscriptions s
        LEFT JOIN tenant_wallets w ON s.tenant_id = w.tenant_id
        LEFT JOIN tenant_feature_flags f ON s.tenant_id = f.tenant_id
        ORDER BY s.tenant_id ASC
        """)
        tenants = []
        for r in cur.fetchall():
            sla_tier = "PLATINUM"
            ota_pct = 98.4
            breaches = 0
            if r[4] == "SLA_PROBATION":
                sla_tier = "SILVER"
                ota_pct = 86.2
                breaches = 3
            elif r[3] == "SOLO":
                sla_tier = "GOLD"
                ota_pct = 94.1
                breaches = 1

            tenants.append({
                "tenant_id": r[0],
                "tenant_uuid": r[1],
                "tenant_name": r[2],
                "phone": "+91 98450 11223" if r[0] == 169 else "+91 97110 88231",
                "email": f"ops@{r[2].lower().replace(' ', '')[:10]}.in",
                "plan_tier": r[3],
                "subscription_status": r[4],
                "mrr_paise": r[5],
                "billing_cycle": r[6],
                "current_period_end": r[7][:10] if r[7] else "2026-04-23",
                "corporate_quota": {"total": r[8], "used": r[9]},
                "trip_quota": {"total": r[10], "used": r[11]},
                "wallet_balance_paise": r[12] or 0,
                "sla_tier": sla_tier,
                "ota_pct": ota_pct,
                "breaches_count": breaches,
                "features": {
                    "network": bool(r[13]),
                    "market": bool(r[14]),
                    "parse_ai": bool(r[15]),
                    "whatsapp_bot": bool(r[16])
                }
            })

        total_tenants = len(tenants)
        active_corporates = sum(t["corporate_quota"]["total"] for t in tenants)
        total_mrr_paise = sum(t["mrr_paise"] for t in tenants)
        gtv_paise = 1830408100  # ₹1,83,04,081 in paise
        sla_demoted_count = sum(1 for t in tenants if t["subscription_status"] == "SLA_PROBATION")

        return {
            "ok": True,
            "kpi_strip": {
                "active_corporates": 71,
                "corporates_monthly_delta": "+4 this mo",
                "active_vendor_subscriptions": 34,
                "churn_risk_count": 2,
                "mrr_paise": 30999700,
                "gtv_platform_paise": gtv_paise,
                "sla_demotions_today": sla_demoted_count,
                "pending_leads": 0
            },
            "tenants": tenants
        }

    # 5. POST /api/v1/admin/saas/tenants/<id>/flags
    elif path.startswith("/api/v1/admin/saas/tenants/") and path.endswith("/flags") and method == "POST":
        parts = path.split("/")
        tid = int(parts[6])
        flag_key = body.get("flag_key")
        flag_val = 1 if body.get("enabled") else 0
        column_map = {
            "network": "network_exchange_enabled",
            "market": "marketplace_enabled",
            "parse_ai": "parse_ai_intake_enabled",
            "whatsapp_bot": "whatsapp_bot_enabled"
        }
        if flag_key in column_map:
            conn.execute(f"UPDATE tenant_feature_flags SET {column_map[flag_key]} = ?, updated_at = ? WHERE tenant_id = ?", (flag_val, now_iso, tid))
            conn.commit()
            return {"ok": True, "tenant_id": tid, "flag": flag_key, "enabled": bool(flag_val)}
        return {"ok": False, "error": "Invalid flag key"}

    # 6. POST /api/v1/admin/saas/tenants/<id>/topup
    elif path.startswith("/api/v1/admin/saas/tenants/") and path.endswith("/topup") and method == "POST":
        parts = path.split("/")
        tid = int(parts[6])
        amount_paise = int(body.get("amount_paise", 50000))
        conn.execute("UPDATE tenant_wallets SET balance_paise = balance_paise + ?, updated_at = ? WHERE tenant_id = ?", (amount_paise, now_iso, tid))
        conn.commit()
        cur = conn.execute("SELECT balance_paise FROM tenant_wallets WHERE tenant_id = ?", (tid,))
        new_bal = cur.fetchone()[0]
        return {"ok": True, "tenant_id": tid, "new_balance_paise": new_bal}

    return {"error": "Route not found", "path": path}
