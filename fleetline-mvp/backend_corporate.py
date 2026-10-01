"""Corporate-account and policy foundations for Axiom Fleet.

This module is deliberately additive.  The local SQLite implementation mirrors
Supabase tables/RPC boundaries so the hybrid UI can exercise the account setup,
visibility, policy, approval and allotment contracts without inventing
operational records.  Every query is scoped by the authenticated user's
organization.  Production should move the same transitions behind Supabase RLS
and server-side RPCs; the browser must never be the authorization boundary.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlsplit

from backend_domain import (
    DomainError,
    _assert_owned,
    _audit,
    _json,
    _org,
    _require_role,
    _serialize,
    _text,
    new_id,
    now_iso,
)


CORPORATE_PREFIX = "/api/corporate"
ACCOUNT_TYPES = {"admin", "employee_admin", "booker_passenger"}
ACCOUNT_STATUSES = {"draft", "setup", "active", "suspended", "archived"}
POLICY_STATUSES = {"draft", "active", "archived"}
APPROVAL_STATUSES = {"pending", "approved", "rejected", "auto_approved", "expired"}
MASTER_KINDS = {
    "duty_types",
    "vehicle_groups",
    "billing_items",
    "taxes",
    "company_scopes",
    "pricing_rules",
    "document_requirements",
}
SCOPE_KEYS = {
    "branch_ids",
    "customer_entity_ids",
    "sister_company_ids",
    "cities",
    "vehicle_group_codes",
    "duty_type_codes",
    "company_ids",
}
SCOPE_REQUEST_KEYS = {
    "branch_ids": "branch_id",
    "customer_entity_ids": "customer_entity_id",
    "sister_company_ids": "sister_company_id",
    "cities": "city",
    "vehicle_group_codes": "vehicle_group_code",
    "duty_type_codes": "duty_type_code",
    "company_ids": "company_id",
}
PERMISSION_KEYS = {
    "account.read",
    "account.manage",
    "people.read",
    "people.manage",
    "booking.create",
    "booking.cancel",
    "booking.approve",
    "policy.read",
    "policy.manage",
    "allotment.evaluate",
    "allotment.manage",
    "duty_slip.approve",
    "duty_slip.reject",
    "masters.read",
    "masters.manage",
}
DEFAULT_PERMISSIONS = {
    "admin": PERMISSION_KEYS,
    "employee_admin": {
        "account.read",
        "people.read",
        "people.manage",
        "booking.create",
        "booking.cancel",
        "booking.approve",
        "policy.read",
        "allotment.evaluate",
        "duty_slip.approve",
        "duty_slip.reject",
        "masters.read",
    },
    "booker_passenger": {
        "account.read",
        "booking.create",
        "booking.cancel",
        "allotment.evaluate",
        "duty_slip.approve",
        "duty_slip.reject",
        "policy.read",
    },
}


# ---------------------------------------------------------------------------
# Schema and small value helpers
# ---------------------------------------------------------------------------


def initialize_corporate_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS corporate_accounts (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            name TEXT NOT NULL,
            connection_type TEXT NOT NULL DEFAULT 'manual',
            external_account_id TEXT NOT NULL DEFAULT '',
            customer_id TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            copy_pricing INTEGER NOT NULL DEFAULT 0,
            visibility_json TEXT NOT NULL DEFAULT '{}',
            pricing_scope_json TEXT NOT NULL DEFAULT '{}',
            setup_snapshot_id TEXT,
            setup_version INTEGER NOT NULL DEFAULT 0,
            activated_at TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id)
        );
        CREATE INDEX IF NOT EXISTS idx_corporate_accounts_org_status
          ON corporate_accounts(organization_id, status);

        CREATE TABLE IF NOT EXISTS corporate_account_snapshots (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            copied_price_book_ids_json TEXT NOT NULL DEFAULT '[]',
            copied_at TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(account_id, version)
        );
        CREATE INDEX IF NOT EXISTS idx_corporate_account_snapshots_org
          ON corporate_account_snapshots(organization_id, account_id, version DESC);

        CREATE TABLE IF NOT EXISTS corporate_account_users (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            user_id TEXT,
            employee_id TEXT,
            email TEXT NOT NULL DEFAULT '',
            full_name TEXT NOT NULL DEFAULT '',
            account_type TEXT NOT NULL DEFAULT 'booker_passenger',
            permission_profile TEXT NOT NULL DEFAULT 'booker_passenger',
            grants_json TEXT NOT NULL DEFAULT '[]',
            denies_json TEXT NOT NULL DEFAULT '[]',
            visibility_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'invited',
            invited_by TEXT,
            activated_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(account_id, email),
            UNIQUE(account_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_corporate_account_users_org
          ON corporate_account_users(organization_id, account_id, status);

        CREATE TABLE IF NOT EXISTS corporate_policies (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            version INTEGER NOT NULL DEFAULT 1,
            booking_lead_time_minutes INTEGER,
            cancellation_cutoff_minutes INTEGER,
            approval_required INTEGER NOT NULL DEFAULT 0,
            approval_route_json TEXT NOT NULL DEFAULT '[]',
            supplier_mode TEXT NOT NULL DEFAULT 'any',
            allowed_supplier_ids_json TEXT NOT NULL DEFAULT '[]',
            auto_allotment_enabled INTEGER NOT NULL DEFAULT 0,
            allotment_rule_id TEXT,
            passenger_duty_slip_approval INTEGER NOT NULL DEFAULT 0,
            duty_slip_auto_approval_hours INTEGER NOT NULL DEFAULT 48,
            visibility_json TEXT NOT NULL DEFAULT '{}',
            rules_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(account_id, name, version)
        );
        CREATE INDEX IF NOT EXISTS idx_corporate_policies_org_account
          ON corporate_policies(organization_id, account_id, status, version DESC);

        CREATE TABLE IF NOT EXISTS corporate_allotment_rules (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            name TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'draft',
            priority INTEGER NOT NULL DEFAULT 100,
            supplier_ids_json TEXT NOT NULL DEFAULT '[]',
            vehicle_group_codes_json TEXT NOT NULL DEFAULT '[]',
            duty_type_codes_json TEXT NOT NULL DEFAULT '[]',
            cities_json TEXT NOT NULL DEFAULT '[]',
            required_document_types_json TEXT NOT NULL DEFAULT '[]',
            auto_allot INTEGER NOT NULL DEFAULT 0,
            fallback_supplier_id TEXT,
            max_attempts INTEGER NOT NULL DEFAULT 1,
            rules_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(account_id, name, version)
        );
        CREATE INDEX IF NOT EXISTS idx_corporate_allotment_rules_org
          ON corporate_allotment_rules(organization_id, account_id, status, priority, version DESC);

        CREATE TABLE IF NOT EXISTS corporate_masters (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'active',
            effective_from TEXT,
            effective_to TEXT,
            scope_json TEXT NOT NULL DEFAULT '{}',
            config_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, kind, code, version)
        );
        CREATE INDEX IF NOT EXISTS idx_corporate_masters_org_kind
          ON corporate_masters(organization_id, kind, status, code, version DESC);

        CREATE TABLE IF NOT EXISTS corporate_duty_slip_approvals (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            booking_id TEXT,
            duty_id TEXT,
            passenger_email TEXT NOT NULL DEFAULT '',
            passenger_name TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            action_token_hash TEXT NOT NULL,
            token_expires_at TEXT NOT NULL,
            auto_approve_at TEXT NOT NULL,
            decision_comment TEXT NOT NULL DEFAULT '',
            decision_reason TEXT NOT NULL DEFAULT '',
            decided_by TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            decided_at TEXT,
            UNIQUE(organization_id, action_token_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_corporate_duty_slip_approvals_org
          ON corporate_duty_slip_approvals(organization_id, account_id, status, auto_approve_at);

        CREATE TABLE IF NOT EXISTS corporate_policy_evaluations (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            policy_id TEXT,
            evaluation_type TEXT NOT NULL,
            outcome TEXT NOT NULL,
            request_hash TEXT NOT NULL DEFAULT '',
            request_json TEXT NOT NULL DEFAULT '{}',
            reasons_json TEXT NOT NULL DEFAULT '[]',
            result_json TEXT NOT NULL DEFAULT '{}',
            evaluated_by TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_corporate_policy_evaluations_org
          ON corporate_policy_evaluations(organization_id, account_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS corporate_idempotency_keys (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            key TEXT NOT NULL,
            route TEXT NOT NULL,
            result_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, key, route)
        );
        """
    )


def _parse_json_list(value: Any, field: str, *, maximum: int = 200) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise DomainError(400, f"{field} must be a list", "validation_error")
    if len(value) > maximum:
        raise DomainError(400, f"{field} has too many values", "validation_error")
    result: list[str] = []
    for raw in value:
        item = str(raw or "").strip()
        if not item:
            continue
        if len(item) > 160:
            raise DomainError(400, f"{field} contains a value that is too long", "validation_error")
        result.append(item)
    return list(dict.fromkeys(result))


def _json_object(value: Any, field: str, *, maximum: int = 50_000) -> dict:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise DomainError(400, f"{field} must be an object", "validation_error")
    encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    if len(encoded) > maximum:
        raise DomainError(400, f"{field} is too large", "validation_error")
    return value


def _bool(value: Any, field: str, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in {"true", "1", "yes", "on"}:
        return True
    if isinstance(value, str) and value.strip().lower() in {"false", "0", "no", "off"}:
        return False
    raise DomainError(400, f"{field} must be a boolean", "validation_error")


def _int(value: Any, field: str, *, default: int | None = None, maximum: int = 525_600) -> int | None:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        raise DomainError(400, f"{field} must be an integer", "validation_error")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise DomainError(400, f"{field} must be an integer", "validation_error") from exc
    if parsed < 0 or parsed > maximum:
        raise DomainError(400, f"{field} is outside the supported range", "validation_error")
    return parsed


def _parse_time(value: Any, field: str) -> datetime:
    if not value:
        raise DomainError(400, f"{field} is required", "validation_error")
    raw = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise DomainError(400, f"{field} must be an ISO timestamp", "validation_error") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _scope(value: Any, field: str = "scope") -> dict[str, list[str]]:
    raw = _json_object(value, field)
    unknown = set(raw) - SCOPE_KEYS
    if unknown:
        raise DomainError(400, f"{field} contains unsupported keys: {', '.join(sorted(unknown))}", "validation_error")
    return {key: _parse_json_list(raw.get(key), f"{field}.{key}") for key in SCOPE_KEYS if raw.get(key) not in (None, "")}


def _compact_scope(value: dict | None) -> dict[str, list[str]]:
    return {key: list(dict.fromkeys(str(item) for item in values if str(item).strip())) for key, values in (value or {}).items() if values}


def _scope_intersection(account_scope: dict, user_scope: dict, policy_scope: dict, request: dict) -> tuple[bool, list[dict]]:
    """Evaluate allow-list scopes without treating an empty scope as a block.

    Empty means no restriction at that layer.  A non-empty list at any layer
    restricts the request to that list; this makes the evaluation deterministic
    and explainable for admins and audit review.
    """
    labels = {
        "branch_ids": "branch",
        "customer_entity_ids": "customer entity",
        "sister_company_ids": "sister company",
        "cities": "city",
        "vehicle_group_codes": "vehicle group",
        "duty_type_codes": "duty type",
        "company_ids": "company",
    }
    reasons: list[dict] = []
    allowed = True
    for key in SCOPE_KEYS:
        requested = str(request.get(key) or request.get(SCOPE_REQUEST_KEYS.get(key, key)) or "").strip()
        if not requested:
            continue
        for source_name, source in (("account", account_scope), ("user", user_scope), ("policy", policy_scope)):
            values = source.get(key) or []
            if values and requested not in values:
                allowed = False
                reasons.append({"code": f"{source_name}_scope_denied", "severity": "block", "field": key, "message": f"The {labels[key]} is outside the {source_name} visibility scope."})
    return allowed, reasons


def _row(row, json_fields: tuple[str, ...] = ()) -> dict | None:
    return _serialize(row, json_fields)


def _account(conn, organization_id: str) -> Any:
    return conn.execute("SELECT * FROM corporate_accounts WHERE organization_id = ?", (organization_id,)).fetchone()


def _account_required(conn, organization_id: str) -> Any:
    row = _account(conn, organization_id)
    if row is None:
        raise DomainError(409, "Connect a corporate account before using this workflow", "corporate_account_required")
    return row


def _account_user(conn, account_id: str, user) -> Any:
    row = conn.execute(
        "SELECT * FROM corporate_account_users WHERE account_id = ? AND user_id = ? AND status = 'active'",
        (account_id, user["id"]),
    ).fetchone()
    if row:
        return row
    # Organization owners/admins retain an explicit admin identity on account
    # creation.  This fallback is only for legacy accounts created before the
    # corporate table existed; it does not cross the tenant boundary.
    if user["role"] in {"vendor", "corporate"}:
        return None
    return None


def _permission(user, account_user, key: str) -> bool:
    if user["role"] == "vendor" and account_user is None:
        return True
    if account_user is None:
        return False
    profile = account_user["permission_profile"] or account_user["account_type"]
    allowed = set(DEFAULT_PERMISSIONS.get(profile, DEFAULT_PERMISSIONS["booker_passenger"]))
    allowed.update(_json(account_user["grants_json"], []))
    denied = set(_json(account_user["denies_json"], []))
    return key in allowed and key not in denied


def _require_permission(conn, user, account, key: str) -> Any:
    member = _account_user(conn, account["id"], user)
    if not _permission(user, member, key):
        raise DomainError(403, f"This account user cannot perform {key}", "permission_denied")
    return member


def _active_policy(conn, account_id: str, policy_id: str | None = None) -> Any:
    if policy_id:
        row = conn.execute("SELECT * FROM corporate_policies WHERE id = ? AND account_id = ?", (policy_id, account_id)).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM corporate_policies WHERE account_id = ? AND status = 'active' ORDER BY version DESC, updated_at DESC LIMIT 1",
            (account_id,),
        ).fetchone()
    return row


def _policy_dict(policy) -> dict:
    if policy is None:
        return {}
    item = _row(policy, ("approval_route_json", "allowed_supplier_ids_json", "visibility_json", "rules_json")) or {}
    # Keep the response contract friendly: also expose the original JSON field
    # names to make local and Supabase adapters interchangeable.
    item["approval_route"] = item.pop("approval_route_json", [])
    item["allowed_supplier_ids"] = item.pop("allowed_supplier_ids_json", [])
    item["visibility"] = item.pop("visibility_json", {})
    item["rules"] = item.pop("rules_json", {})
    item["approval_required"] = bool(item.get("approval_required"))
    item["auto_allotment_enabled"] = bool(item.get("auto_allotment_enabled"))
    item["passenger_duty_slip_approval"] = bool(item.get("passenger_duty_slip_approval"))
    return item


def _account_dict(account) -> dict:
    item = _row(account, ("visibility_json", "pricing_scope_json")) or {}
    item["copy_pricing"] = bool(item.get("copy_pricing"))
    item["visibility"] = item.pop("visibility_json", {})
    item["pricing_scope"] = item.pop("pricing_scope_json", {})
    return item


def _user_dict(row) -> dict:
    item = _row(row, ("grants_json", "denies_json", "visibility_json")) or {}
    item["grants"] = item.pop("grants_json", [])
    item["denies"] = item.pop("denies_json", [])
    item["visibility"] = item.pop("visibility_json", {})
    return item


def _approval_dict(row, include_token: str | None = None) -> dict:
    item = _row(row) or {}
    item.pop("action_token_hash", None)
    if include_token:
        item["action_token"] = include_token
    return item


def _master_dict(row) -> dict:
    return _row(row, ("scope_json", "config_json")) or {}


def _idempotency_key(payload: dict) -> str:
    value = str(payload.get("idempotency_key") or "").strip()
    if len(value) > 160:
        raise DomainError(400, "idempotency_key is too long", "validation_error")
    return value


def _route_key(path: str) -> str:
    return urlsplit(path).path.rstrip("/") or "/"


def _replay_lookup(conn, organization_id: str, key: str, route: str) -> dict | None:
    if not key:
        return None
    row = conn.execute(
        "SELECT result_json FROM corporate_idempotency_keys WHERE organization_id = ? AND key = ? AND route = ?",
        (organization_id, key, route),
    ).fetchone()
    if not row:
        return None
    return {**(_json(row["result_json"], {}) or {}), "idempotent_replay": True}


def _replay_store(conn, organization_id: str, key: str, route: str, result: dict) -> dict:
    if key:
        conn.execute(
            "INSERT OR IGNORE INTO corporate_idempotency_keys(id, organization_id, key, route, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (new_id("idem"), organization_id, key, route, json.dumps(result, separators=(",", ":"), ensure_ascii=False), now_iso()),
        )
    return result


def _owned_ids(conn, table: str, ids: list[str], organization_id: str, field: str) -> None:
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id FROM {table} WHERE organization_id = ? AND id IN ({placeholders})",
        (organization_id, *ids),
    ).fetchall()
    found = {row["id"] for row in rows}
    missing = [item for item in ids if item not in found]
    if missing:
        raise DomainError(400, f"Unknown or out-of-scope {field}: {', '.join(missing[:5])}", "ownership_error")


def _activation_guard(conn, account) -> dict:
    reasons: list[dict] = []
    if not account["name"].strip():
        reasons.append({"code": "account_name_missing", "severity": "block", "message": "A corporate account name is required."})
    if not account["setup_snapshot_id"]:
        reasons.append({"code": "setup_snapshot_missing", "severity": "block", "message": "Complete the setup snapshot before activation."})
    if not account["external_account_id"] and account["connection_type"] != "manual":
        reasons.append({"code": "external_account_id_missing", "severity": "block", "message": "The connected account reference is required for this connection type."})
    return {"eligible": not reasons, "reasons": reasons}


# ---------------------------------------------------------------------------
# Account setup and account-user entitlements
# ---------------------------------------------------------------------------


def _account_summary(conn, user, account) -> dict:
    organization_id = account["organization_id"]
    snapshots = conn.execute(
        "SELECT * FROM corporate_account_snapshots WHERE account_id = ? AND organization_id = ? ORDER BY version DESC LIMIT 5",
        (account["id"], organization_id),
    ).fetchall()
    people = conn.execute(
        "SELECT * FROM corporate_account_users WHERE account_id = ? AND organization_id = ? ORDER BY created_at DESC",
        (account["id"], organization_id),
    ).fetchall()
    policies = conn.execute(
        "SELECT * FROM corporate_policies WHERE account_id = ? AND organization_id = ? ORDER BY status ASC, version DESC, created_at DESC",
        (account["id"], organization_id),
    ).fetchall()
    masters = conn.execute(
        "SELECT kind, COUNT(*) AS count FROM corporate_masters WHERE organization_id = ? AND status = 'active' GROUP BY kind ORDER BY kind",
        (organization_id,),
    ).fetchall()
    pending = conn.execute(
        "SELECT COUNT(*) AS count FROM corporate_duty_slip_approvals WHERE account_id = ? AND status = 'pending'",
        (account["id"],),
    ).fetchone()["count"]
    guard = _activation_guard(conn, account)
    readiness = {
        "account_connected": True,
        "setup_snapshot": bool(account["setup_snapshot_id"]),
        "active": account["status"] == "active",
        "active_policy": any(row["status"] == "active" for row in policies),
        "people": len(people) > 0,
        "versioned_masters": bool(masters),
        "passenger_duty_slip_policy": any(bool(row["passenger_duty_slip_approval"]) for row in policies if row["status"] == "active"),
    }
    completed = sum(1 for value in readiness.values() if value)
    return {
        "ok": True,
        "account": _account_dict(account),
        "setup_snapshots": [_row(row, ("snapshot_json", "copied_price_book_ids_json")) for row in snapshots],
        "users": [_user_dict(row) for row in people],
        "policies": [_policy_dict(row) for row in policies],
        "master_counts": {row["kind"]: row["count"] for row in masters},
        "pending_duty_slip_approvals": pending,
        "activation_guard": guard,
        "readiness": {**readiness, "completed": completed, "total": len(readiness), "percent": round(completed / len(readiness) * 100)},
    }


def _create_or_update_account(conn, user, payload: dict, ip: str, *, setup: bool = False) -> dict:
    organization_id = _org(user)
    _require_role(user)
    account = _account(conn, organization_id)
    name = _text(payload, "name", account["name"] if account else "", 160)
    if setup and not name:
        raise DomainError(400, "name is required for account setup", "validation_error")
    connection_type = _text(payload, "connection_type", account["connection_type"] if account else "manual", 40).lower()
    if connection_type not in {"manual", "customer", "supplier", "network", "api"}:
        raise DomainError(400, "Unsupported connection_type", "validation_error")
    external_account_id = _text(payload, "external_account_id", account["external_account_id"] if account else "", 160)
    customer_id = payload.get("customer_id", account["customer_id"] if account else None)
    customer_id = str(customer_id).strip() if customer_id else None
    if customer_id:
        _assert_owned(conn, "domain_customers", customer_id, organization_id)
    scope = _scope(payload.get("scope", _json(account["visibility_json"], {}) if account else {}), "scope")
    _owned_ids(conn, "domain_branches", scope.get("branch_ids", []), organization_id, "branches")
    _owned_ids(conn, "domain_customers", scope.get("customer_entity_ids", []), organization_id, "customer entities")
    pricing_scope = _json_object(payload.get("pricing_scope", _json(account["pricing_scope_json"], {}) if account else {}), "pricing_scope")
    copy_pricing = _bool(payload.get("copy_pricing", account["copy_pricing"] if account else False), "copy_pricing")
    source_price_book_ids = _parse_json_list(payload.get("source_price_book_ids"), "source_price_book_ids")
    _owned_ids(conn, "domain_price_books", source_price_book_ids, organization_id, "source price books")
    copied_pricing: list[dict] = []
    if copy_pricing:
        for price_book_id in source_price_book_ids:
            price_book = conn.execute("SELECT * FROM domain_price_books WHERE id = ? AND organization_id = ?", (price_book_id, organization_id)).fetchone()
            if price_book is None:
                raise DomainError(400, f"Unknown or out-of-scope source price book: {price_book_id}", "ownership_error")
            price_items = conn.execute("SELECT * FROM domain_price_book_items WHERE price_book_id = ? ORDER BY duty_type ASC, vehicle_group ASC, id ASC", (price_book_id,)).fetchall()
            copied_pricing.append({"price_book": _row(price_book), "items": [_row(item, ("rules_json",)) for item in price_items]})
    now = now_iso()
    if account is None:
        account_id = new_id("corp")
        conn.execute(
            """
            INSERT INTO corporate_accounts(
                id, organization_id, name, connection_type, external_account_id,
                customer_id, status, copy_pricing, visibility_json, pricing_scope_json,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (account_id, organization_id, name, connection_type, external_account_id, customer_id, "setup" if setup else "draft", int(copy_pricing), json.dumps(scope), json.dumps(pricing_scope), user["id"], now, now),
        )
        account = conn.execute("SELECT * FROM corporate_accounts WHERE id = ?", (account_id,)).fetchone()
        # The creating authenticated organization member receives an explicit
        # admin entitlement instead of an implicit global role.
        conn.execute(
            """
            INSERT INTO corporate_account_users(
                id, organization_id, account_id, user_id, email, full_name,
                account_type, permission_profile, status, invited_by, activated_at,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'admin', 'admin', 'active', ?, ?, ?, ?)
            """,
            (new_id("corpuser"), organization_id, account_id, user["id"], user["email"], user["full_name"], user["id"], now, now, now),
        )
    else:
        account_id = account["id"]
        new_status = account["status"] if not setup or account["status"] in {"active", "suspended"} else "setup"
        conn.execute(
            """
            UPDATE corporate_accounts
            SET name = ?, connection_type = ?, external_account_id = ?, customer_id = ?,
                status = ?, copy_pricing = ?, visibility_json = ?, pricing_scope_json = ?,
                updated_at = ?
            WHERE id = ? AND organization_id = ?
            """,
            (name, connection_type, external_account_id, customer_id, new_status, int(copy_pricing), json.dumps(scope), json.dumps(pricing_scope), now, account_id, organization_id),
        )
        account = conn.execute("SELECT * FROM corporate_accounts WHERE id = ?", (account_id,)).fetchone()

    if setup:
        version = int(account["setup_version"] or 0) + 1
        snapshot = {
            "account_id": account_id,
            "version": version,
            "connection_type": connection_type,
            "external_account_id": external_account_id,
            "customer_id": customer_id,
            "scope": scope,
            "pricing_scope": pricing_scope,
            "copy_pricing": copy_pricing,
            "source_price_book_ids": source_price_book_ids,
            "copied_pricing": copied_pricing,
            "captured_at": now,
        }
        snapshot_id = new_id("corpsnap")
        conn.execute(
            """
            INSERT INTO corporate_account_snapshots(
                id, organization_id, account_id, version, snapshot_json,
                copied_price_book_ids_json, copied_at, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (snapshot_id, organization_id, account_id, version, json.dumps(snapshot, separators=(",", ":")), json.dumps(source_price_book_ids), now if copy_pricing else None, user["id"], now),
        )
        conn.execute(
            "UPDATE corporate_accounts SET setup_snapshot_id = ?, setup_version = ?, updated_at = ? WHERE id = ? AND organization_id = ?",
            (snapshot_id, version, now, account_id, organization_id),
        )
        account = conn.execute("SELECT * FROM corporate_accounts WHERE id = ?", (account_id,)).fetchone()
        _audit(conn, user, "corporate.account.setup", "corporate_account", account_id, ip, {"version": version, "copy_pricing": copy_pricing, "source_price_book_count": len(source_price_book_ids)})
    else:
        _audit(conn, user, "corporate.account.connect", "corporate_account", account_id, ip, {"connection_type": connection_type})
    return _account_summary(conn, user, account)


def _handle_account(conn, user, method: str, route: str, payload: dict, ip: str, finish) -> dict | None:
    organization_id = _org(user)
    if route in {f"{CORPORATE_PREFIX}/account", f"{CORPORATE_PREFIX}/accounts"}:
        if method == "GET":
            account = _account(conn, organization_id)
            return {"ok": True, "account": None} if account is None else _account_summary(conn, user, account)
        if method in {"POST", "PATCH"}:
            _require_role(user)
            if method == "PATCH" and _account(conn, organization_id) is None:
                raise DomainError(404, "Corporate account not found", "not_found")
            return finish(_create_or_update_account(conn, user, payload, ip, setup=False))
    if route in {f"{CORPORATE_PREFIX}/account/setup", f"{CORPORATE_PREFIX}/accounts/setup"} and method == "POST":
        _require_role(user)
        return finish(_create_or_update_account(conn, user, payload, ip, setup=True))
    if route in {f"{CORPORATE_PREFIX}/account/activate", f"{CORPORATE_PREFIX}/accounts/activate"} and method == "POST":
        account = _account_required(conn, organization_id)
        _require_permission(conn, user, account, "account.manage")
        guard = _activation_guard(conn, account)
        if not guard["eligible"]:
            raise DomainError(409, "Corporate account is not ready for activation", "activation_blocked")
        now = now_iso()
        conn.execute("UPDATE corporate_accounts SET status = 'active', activated_at = ?, updated_at = ? WHERE id = ? AND organization_id = ?", (now, now, account["id"], organization_id))
        _audit(conn, user, "corporate.account.activate", "corporate_account", account["id"], ip, {"setup_version": account["setup_version"]})
        return finish(_account_summary(conn, user, conn.execute("SELECT * FROM corporate_accounts WHERE id = ?", (account["id"],)).fetchone()))
    if route in {f"{CORPORATE_PREFIX}/account/activation-guard", f"{CORPORATE_PREFIX}/accounts/activation-guard"} and method == "GET":
        account = _account(conn, organization_id)
        return {"ok": True, "guard": {"eligible": False, "reasons": [{"code": "account_missing", "severity": "block", "message": "Connect a corporate account first."}]}} if account is None else {"ok": True, "guard": _activation_guard(conn, account)}
    return None


def _handle_account_users(conn, user, method: str, route: str, payload: dict, ip: str, finish) -> dict | None:
    if not route.startswith(f"{CORPORATE_PREFIX}/users"):
        return None
    account = _account_required(conn, _org(user))
    if method == "GET" and route == f"{CORPORATE_PREFIX}/users":
        _require_permission(conn, user, account, "people.read")
        query = parse_qs(urlsplit(route if "?" not in route else route).query)
        rows = conn.execute("SELECT * FROM corporate_account_users WHERE account_id = ? AND organization_id = ? ORDER BY created_at DESC", (account["id"], account["organization_id"])).fetchall()
        return {"ok": True, "items": [_user_dict(row) for row in rows], "count": len(rows)}
    match = __import__("re").match(rf"^{CORPORATE_PREFIX}/users/([^/]+)(?:/(activate|deactivate))?$", route)
    if method == "POST" and route == f"{CORPORATE_PREFIX}/users":
        _require_permission(conn, user, account, "people.manage")
        email = _text(payload, "email", "", 254).lower()
        full_name = _text(payload, "full_name", email.split("@")[0] if email else "", 160)
        if not email or "@" not in email:
            raise DomainError(400, "A valid email is required", "validation_error")
        account_type = _text(payload, "account_type", "booker_passenger", 40).lower()
        if account_type not in ACCOUNT_TYPES:
            raise DomainError(400, "Unsupported account_type", "validation_error")
        grants = _parse_json_list(payload.get("grants"), "grants")
        denies = _parse_json_list(payload.get("denies"), "denies")
        invalid = (set(grants) | set(denies)) - PERMISSION_KEYS
        if invalid:
            raise DomainError(400, f"Unsupported permissions: {', '.join(sorted(invalid))}", "validation_error")
        visibility = _scope(payload.get("visibility", {}), "visibility")
        status = _text(payload, "status", "invited", 30).lower()
        if status not in {"invited", "active", "suspended"}:
            raise DomainError(400, "Unsupported user status", "validation_error")
        user_id = str(payload.get("user_id") or "").strip() or None
        if user_id:
            _assert_owned(conn, "users", user_id, account["organization_id"])
        now = now_iso()
        row_id = new_id("corpuser")
        conn.execute(
            """
            INSERT INTO corporate_account_users(
                id, organization_id, account_id, user_id, employee_id, email, full_name,
                account_type, permission_profile, grants_json, denies_json, visibility_json,
                status, invited_by, activated_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (row_id, account["organization_id"], account["id"], user_id, payload.get("employee_id"), email, full_name, account_type, _text(payload, "permission_profile", account_type, 40), json.dumps(grants), json.dumps(denies), json.dumps(visibility), status, user["id"], now if status == "active" else None, now, now),
        )
        _audit(conn, user, "corporate.user.invite", "corporate_account_user", row_id, ip, {"account_type": account_type, "status": status})
        return finish({"ok": True, "item": _user_dict(conn.execute("SELECT * FROM corporate_account_users WHERE id = ?", (row_id,)).fetchone())})
    if not match:
        return None
    user_id = match.group(1)
    account_user = conn.execute("SELECT * FROM corporate_account_users WHERE id = ? AND account_id = ? AND organization_id = ?", (user_id, account["id"], account["organization_id"])).fetchone()
    if account_user is None:
        raise DomainError(404, "Corporate account user not found", "not_found")
    action = match.group(2)
    if action:
        _require_permission(conn, user, account, "people.manage")
        next_status = "active" if action == "activate" else "suspended"
        conn.execute("UPDATE corporate_account_users SET status = ?, activated_at = coalesce(activated_at, ?), updated_at = ? WHERE id = ?", (next_status, now_iso() if next_status == "active" else None, now_iso(), user_id))
        _audit(conn, user, f"corporate.user.{action}", "corporate_account_user", user_id, ip, {"status": next_status})
        return finish({"ok": True, "item": _user_dict(conn.execute("SELECT * FROM corporate_account_users WHERE id = ?", (user_id,)).fetchone())})
    if method == "GET":
        _require_permission(conn, user, account, "people.read")
        return {"ok": True, "item": _user_dict(account_user)}
    if method == "PATCH":
        _require_permission(conn, user, account, "people.manage")
        updates: list[str] = []
        values: list[Any] = []
        if "account_type" in payload:
            value = _text(payload, "account_type", "", 40).lower()
            if value not in ACCOUNT_TYPES:
                raise DomainError(400, "Unsupported account_type", "validation_error")
            updates.extend(["account_type = ?", "permission_profile = ?"])
            values.extend([value, _text(payload, "permission_profile", value, 40)])
        if "grants" in payload:
            grants = _parse_json_list(payload.get("grants"), "grants")
            values.append(json.dumps(grants)); updates.append("grants_json = ?")
        if "denies" in payload:
            denies = _parse_json_list(payload.get("denies"), "denies")
            values.append(json.dumps(denies)); updates.append("denies_json = ?")
        if "visibility" in payload:
            values.append(json.dumps(_scope(payload.get("visibility"), "visibility"))); updates.append("visibility_json = ?")
        if "status" in payload:
            status = _text(payload, "status", "", 30).lower()
            if status not in {"invited", "active", "suspended"}:
                raise DomainError(400, "Unsupported user status", "validation_error")
            values.append(status); updates.append("status = ?")
            if status == "active":
                updates.append("activated_at = coalesce(activated_at, ?)"); values.append(now_iso())
        if not updates:
            raise DomainError(400, "No supported account-user fields supplied", "validation_error")
        updates.append("updated_at = ?"); values.append(now_iso()); values.append(user_id)
        conn.execute(f"UPDATE corporate_account_users SET {', '.join(updates)} WHERE id = ?", values)
        _audit(conn, user, "corporate.user.update", "corporate_account_user", user_id, ip, {"fields": sorted(payload)})
        return finish({"ok": True, "item": _user_dict(conn.execute("SELECT * FROM corporate_account_users WHERE id = ?", (user_id,)).fetchone())})
    return None


# ---------------------------------------------------------------------------
# Policies, visibility and booking/cancellation evaluation
# ---------------------------------------------------------------------------


def _policy_payload(payload: dict, existing=None) -> dict:
    account_id = existing["account_id"] if existing else str(payload.get("account_id") or "").strip()
    name = _text(payload, "name", existing["name"] if existing else "", 160)
    if not name:
        raise DomainError(400, "name is required", "validation_error")
    status = _text(payload, "status", existing["status"] if existing else "draft", 20).lower()
    if status not in POLICY_STATUSES:
        raise DomainError(400, "Unsupported policy status", "validation_error")
    approval_route = payload.get("approval_route", _json(existing["approval_route_json"], []) if existing else [])
    if not isinstance(approval_route, list):
        raise DomainError(400, "approval_route must be a list", "validation_error")
    allowed_supplier_ids = _parse_json_list(payload.get("allowed_supplier_ids", _json(existing["allowed_supplier_ids_json"], []) if existing else []), "allowed_supplier_ids")
    visibility = _scope(payload.get("visibility", _json(existing["visibility_json"], {}) if existing else {}), "visibility")
    rules = _json_object(payload.get("rules", _json(existing["rules_json"], {}) if existing else {}), "rules")
    supplier_mode = _text(payload, "supplier_mode", existing["supplier_mode"] if existing else "any", 30).lower()
    if supplier_mode not in {"any", "allowlist", "preferred", "requested_only"}:
        raise DomainError(400, "Unsupported supplier_mode", "validation_error")
    return {
        "name": name,
        "status": status,
        "booking_lead_time_minutes": _int(payload.get("booking_lead_time_minutes", existing["booking_lead_time_minutes"] if existing else None), "booking_lead_time_minutes", default=None),
        "cancellation_cutoff_minutes": _int(payload.get("cancellation_cutoff_minutes", existing["cancellation_cutoff_minutes"] if existing else None), "cancellation_cutoff_minutes", default=None),
        "approval_required": _bool(payload.get("approval_required", existing["approval_required"] if existing else False), "approval_required"),
        "approval_route": approval_route,
        "supplier_mode": supplier_mode,
        "allowed_supplier_ids": allowed_supplier_ids,
        "auto_allotment_enabled": _bool(payload.get("auto_allotment_enabled", existing["auto_allotment_enabled"] if existing else False), "auto_allotment_enabled"),
        "allotment_rule_id": str(payload.get("allotment_rule_id", existing["allotment_rule_id"] if existing else "") or "").strip() or None,
        "passenger_duty_slip_approval": _bool(payload.get("passenger_duty_slip_approval", existing["passenger_duty_slip_approval"] if existing else False), "passenger_duty_slip_approval"),
        "duty_slip_auto_approval_hours": _int(payload.get("duty_slip_auto_approval_hours", existing["duty_slip_auto_approval_hours"] if existing else 48), "duty_slip_auto_approval_hours", default=48, maximum=720),
        "visibility": visibility,
        "rules": rules,
    }


def _handle_policies(conn, user, method: str, route: str, payload: dict, ip: str, finish) -> dict | None:
    if not route.startswith(f"{CORPORATE_PREFIX}/policies"):
        return None
    account = _account_required(conn, _org(user))
    if route == f"{CORPORATE_PREFIX}/policies/evaluate" and method == "POST":
        return _evaluate_booking(conn, user, account, payload, ip, finish)
    if route == f"{CORPORATE_PREFIX}/policies" and method == "GET":
        _require_permission(conn, user, account, "policy.read")
        rows = conn.execute("SELECT * FROM corporate_policies WHERE account_id = ? AND organization_id = ? ORDER BY status ASC, version DESC, created_at DESC", (account["id"], account["organization_id"])).fetchall()
        return {"ok": True, "items": [_policy_dict(row) for row in rows], "count": len(rows)}
    if route == f"{CORPORATE_PREFIX}/policies" and method == "POST":
        _require_permission(conn, user, account, "policy.manage")
        data = _policy_payload(payload)
        _owned_ids(conn, "domain_suppliers", data["allowed_supplier_ids"], account["organization_id"], "suppliers")
        if data["allotment_rule_id"]:
            _assert_owned(conn, "corporate_allotment_rules", data["allotment_rule_id"], account["organization_id"])
        version = int(payload.get("version") or 1)
        if version < 1 or version > 10000:
            raise DomainError(400, "version is outside the supported range", "validation_error")
        policy_id = new_id("corppolicy")
        now = now_iso()
        conn.execute(
            """
            INSERT INTO corporate_policies(
                id, organization_id, account_id, name, status, version,
                booking_lead_time_minutes, cancellation_cutoff_minutes, approval_required,
                approval_route_json, supplier_mode, allowed_supplier_ids_json,
                auto_allotment_enabled, allotment_rule_id, passenger_duty_slip_approval,
                duty_slip_auto_approval_hours, visibility_json, rules_json,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (policy_id, account["organization_id"], account["id"], data["name"], data["status"], version, data["booking_lead_time_minutes"], data["cancellation_cutoff_minutes"], int(data["approval_required"]), json.dumps(data["approval_route"]), data["supplier_mode"], json.dumps(data["allowed_supplier_ids"]), int(data["auto_allotment_enabled"]), data["allotment_rule_id"], int(data["passenger_duty_slip_approval"]), data["duty_slip_auto_approval_hours"], json.dumps(data["visibility"]), json.dumps(data["rules"]), user["id"], now, now),
        )
        _audit(conn, user, "corporate.policy.create", "corporate_policy", policy_id, ip, {"version": version, "status": data["status"]})
        return finish({"ok": True, "item": _policy_dict(conn.execute("SELECT * FROM corporate_policies WHERE id = ?", (policy_id,)).fetchone())})
    match = __import__("re").match(rf"^{CORPORATE_PREFIX}/policies/([^/]+)$", route)
    if not match:
        return None
    policy_id = match.group(1)
    policy = conn.execute("SELECT * FROM corporate_policies WHERE id = ? AND account_id = ? AND organization_id = ?", (policy_id, account["id"], account["organization_id"])).fetchone()
    if policy is None:
        raise DomainError(404, "Corporate policy not found", "not_found")
    if method == "GET":
        _require_permission(conn, user, account, "policy.read")
        return {"ok": True, "item": _policy_dict(policy)}
    if method == "PATCH":
        _require_permission(conn, user, account, "policy.manage")
        data = _policy_payload(payload, policy)
        _owned_ids(conn, "domain_suppliers", data["allowed_supplier_ids"], account["organization_id"], "suppliers")
        if data["allotment_rule_id"]:
            _assert_owned(conn, "corporate_allotment_rules", data["allotment_rule_id"], account["organization_id"])
        version = int(policy["version"]) + (1 if payload.get("new_version") else 0)
        if payload.get("new_version"):
            new_id_value = new_id("corppolicy")
            now = now_iso()
            conn.execute(
                """
                INSERT INTO corporate_policies(
                    id, organization_id, account_id, name, status, version,
                    booking_lead_time_minutes, cancellation_cutoff_minutes, approval_required,
                    approval_route_json, supplier_mode, allowed_supplier_ids_json,
                    auto_allotment_enabled, allotment_rule_id, passenger_duty_slip_approval,
                    duty_slip_auto_approval_hours, visibility_json, rules_json,
                    created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (new_id_value, account["organization_id"], account["id"], data["name"], data["status"], version, data["booking_lead_time_minutes"], data["cancellation_cutoff_minutes"], int(data["approval_required"]), json.dumps(data["approval_route"]), data["supplier_mode"], json.dumps(data["allowed_supplier_ids"]), int(data["auto_allotment_enabled"]), data["allotment_rule_id"], int(data["passenger_duty_slip_approval"]), data["duty_slip_auto_approval_hours"], json.dumps(data["visibility"]), json.dumps(data["rules"]), user["id"], now, now),
            )
            _audit(conn, user, "corporate.policy.version", "corporate_policy", new_id_value, ip, {"from_policy_id": policy_id, "version": version})
            return finish({"ok": True, "item": _policy_dict(conn.execute("SELECT * FROM corporate_policies WHERE id = ?", (new_id_value,)).fetchone())})
        assignments = [
            "name = ?", "status = ?", "booking_lead_time_minutes = ?", "cancellation_cutoff_minutes = ?", "approval_required = ?", "approval_route_json = ?", "supplier_mode = ?", "allowed_supplier_ids_json = ?", "auto_allotment_enabled = ?", "allotment_rule_id = ?", "passenger_duty_slip_approval = ?", "duty_slip_auto_approval_hours = ?", "visibility_json = ?", "rules_json = ?", "updated_at = ?",
        ]
        values = [data["name"], data["status"], data["booking_lead_time_minutes"], data["cancellation_cutoff_minutes"], int(data["approval_required"]), json.dumps(data["approval_route"]), data["supplier_mode"], json.dumps(data["allowed_supplier_ids"]), int(data["auto_allotment_enabled"]), data["allotment_rule_id"], int(data["passenger_duty_slip_approval"]), data["duty_slip_auto_approval_hours"], json.dumps(data["visibility"]), json.dumps(data["rules"]), now_iso(), policy_id]
        conn.execute(f"UPDATE corporate_policies SET {', '.join(assignments)} WHERE id = ?", values)
        _audit(conn, user, "corporate.policy.update", "corporate_policy", policy_id, ip, {"fields": sorted(payload)})
        return finish({"ok": True, "item": _policy_dict(conn.execute("SELECT * FROM corporate_policies WHERE id = ?", (policy_id,)).fetchone())})
    return None


def _reason(code: str, message: str, severity: str = "warn", **extra) -> dict:
    return {"code": code, "message": message, "severity": severity, **extra}


def _evaluate_visibility(conn, user, account, payload: dict) -> dict:
    member = _account_user(conn, account["id"], user)
    account_scope = _json(account["visibility_json"], {})
    user_scope = _json(member["visibility_json"], {}) if member else {}
    policy_scope = _scope(payload.get("policy_scope", {}), "policy_scope")
    request = _json_object(payload.get("resource", payload), "resource")
    allowed, reasons = _scope_intersection(account_scope, user_scope, policy_scope, request)
    permission_key = str(payload.get("permission") or "").strip()
    if permission_key and not _permission(user, member, permission_key):
        allowed = False
        reasons.append(_reason("permission_denied", f"The account user does not have {permission_key}.", "block", permission=permission_key))
    return {"allowed": allowed, "outcome": "allow" if allowed else "block", "reasons": reasons, "scope": {"account": account_scope, "user": user_scope, "policy": policy_scope}}


def _evaluate_booking(conn, user, account, payload: dict, ip: str, finish) -> dict:
    action = str(payload.get("action") or "book").strip().lower()
    _require_permission(conn, user, account, "booking.cancel" if action in {"cancel", "cancellation"} else "booking.create")
    if account["status"] != "active":
        result = {"ok": True, "outcome": "block", "decision": "block", "reasons": [_reason("corporate_account_not_active", "The corporate account must be active before a booking can be evaluated.", "block")], "policy_id": None}
        return finish(result)
    policy_id = str(payload.get("policy_id") or "").strip() or None
    policy = _active_policy(conn, account["id"], policy_id)
    reasons: list[dict] = []
    supplier_candidates: list[dict] = []
    if policy is None:
        reasons.append(_reason("active_policy_missing", "No active booking policy is configured.", "block"))
    policy_scope = _json(policy["visibility_json"], {}) if policy else {}
    visibility = _evaluate_visibility(conn, user, account, {**payload, "policy_scope": policy_scope, "resource": payload})
    reasons.extend(visibility["reasons"])
    now = _now()
    scheduled_at = None
    if payload.get("scheduled_at"):
        scheduled_at = _parse_time(payload.get("scheduled_at"), "scheduled_at")
    if policy:
        lead = policy["booking_lead_time_minutes"]
        if action in {"book", "create", "request"} and lead is not None:
            if scheduled_at is None:
                reasons.append(_reason("scheduled_at_required", "The booking lead-time rule requires a scheduled_at timestamp.", "block"))
            elif (scheduled_at - now).total_seconds() < int(lead) * 60:
                reasons.append(_reason("booking_lead_time_sla", f"Bookings must be made at least {lead} minutes before pickup.", "block", required_minutes=lead))
        cutoff = policy["cancellation_cutoff_minutes"]
        if action in {"cancel", "cancellation"} and cutoff is not None:
            if scheduled_at is None:
                reasons.append(_reason("scheduled_at_required", "The cancellation cutoff rule requires a scheduled_at timestamp.", "block"))
            elif (scheduled_at - now).total_seconds() < int(cutoff) * 60:
                reasons.append(_reason("cancellation_cutoff", f"Cancellation is inside the {cutoff}-minute cutoff window.", "block", cutoff_minutes=cutoff, potential_charge=True))
        requested_supplier = str(payload.get("supplier_id") or "").strip()
        allowed_supplier_ids = _json(policy["allowed_supplier_ids_json"], [])
        if requested_supplier and allowed_supplier_ids and requested_supplier not in allowed_supplier_ids:
            reasons.append(_reason("supplier_not_allowed", "The requested supplier is outside the active policy allow-list.", "block", supplier_id=requested_supplier))
        if policy["supplier_mode"] == "allowlist" and not allowed_supplier_ids:
            reasons.append(_reason("supplier_allowlist_empty", "Supplier mode is allowlist but no supplier is configured.", "block"))
        if not requested_supplier and policy["auto_allotment_enabled"]:
            supplier_candidates = _supplier_candidates(conn, account["organization_id"], allowed_supplier_ids, payload)
            if not supplier_candidates:
                reasons.append(_reason("no_supplier_candidate", "Automatic allotment is enabled but no eligible supplier is available.", "block"))
            else:
                reasons.append(_reason("auto_allotment_candidates", "Eligible suppliers were resolved deterministically; no supplier was assigned by this evaluation.", "info", candidates=[item["id"] for item in supplier_candidates]))
        elif not requested_supplier and policy["supplier_mode"] == "requested_only":
            reasons.append(_reason("supplier_required", "This policy requires the requester to select a supplier.", "block"))
        if policy["approval_required"] and action in {"book", "create", "request"}:
            reasons.append(_reason("approval_required", "The booking must pass the configured approval route.", "approval", approval_route=_json(policy["approval_route_json"], [])))
    blocking = [item for item in reasons if item.get("severity") == "block"]
    approval = [item for item in reasons if item.get("severity") == "approval"]
    outcome = "block" if blocking else "needs_approval" if approval else "allow"
    request_body = {key: payload.get(key) for key in sorted(payload) if key not in {"action_token", "password"}}
    request_json = json.dumps(request_body, sort_keys=True, separators=(",", ":"), default=str)
    request_hash = _hash(request_json)
    result = {
        "ok": True,
        "outcome": outcome,
        "decision": outcome,
        "allowed": outcome == "allow",
        "policy_id": policy["id"] if policy else None,
        "policy_version": policy["version"] if policy else None,
        "reasons": reasons,
        "supplier_candidates": supplier_candidates,
        "deterministic": True,
        "evaluated_at": now_iso(),
    }
    conn.execute(
        "INSERT INTO corporate_policy_evaluations(id, organization_id, account_id, policy_id, evaluation_type, outcome, request_hash, request_json, reasons_json, result_json, evaluated_by, created_at) VALUES (?, ?, ?, ?, 'booking', ?, ?, ?, ?, ?, ?, ?)",
        (new_id("corpeval"), account["organization_id"], account["id"], policy["id"] if policy else None, outcome, request_hash, request_json, json.dumps(reasons), json.dumps(result), user["id"], now_iso()),
    )
    _audit(conn, user, "corporate.booking.evaluate", "corporate_policy", policy["id"] if policy else account["id"], ip, {"outcome": outcome, "request_hash": request_hash})
    return finish(result)


def require_corporate_booking_permission(conn, user, permission: str) -> None:
    account = _account(conn, _org(user))
    if account is not None and account["status"] == "active":
        _require_permission(conn, user, account, permission)


def evaluate_corporate_booking_write(conn, user, payload: dict, action: str, ip: str, booking=None) -> dict | None:
    """Evaluate an operational booking mutation at the local write boundary.

    The evaluator endpoint remains useful for previews, but active corporate
    accounts must also be enforced when a booking or cancellation is submitted
    through the ordinary domain API.  Tenants without an active corporate
    account retain the existing local workflow.
    """
    account = _account(conn, _org(user))
    if account is None or account["status"] != "active":
        return None
    request = dict(payload or {})
    request["action"] = action
    if not request.get("city") and isinstance(request.get("pickup"), dict):
        request["city"] = request["pickup"].get("city") or request["pickup"].get("label") or ""
    if not request.get("customer_entity_id") and request.get("customer_id"):
        request["customer_entity_id"] = request["customer_id"]
    if not request.get("duty_type_code") and request.get("duty_type"):
        request["duty_type_code"] = request["duty_type"]
    if booking is not None:
        request.setdefault("scheduled_at", booking["scheduled_at"])
        if not request.get("city"):
            pickup = _json(booking["pickup_json"], {})
            if isinstance(pickup, dict):
                request["city"] = pickup.get("city") or pickup.get("label") or ""
        request.setdefault("duty_type_code", booking["duty_type"] or "")
        request.setdefault("customer_entity_id", booking["customer_id"] or "")
    return _evaluate_booking(conn, user, account, request, ip, lambda result: result)


def apply_corporate_booking_decision(conn, user, booking_id: str, evaluation: dict, ip: str) -> dict:
    """Persist a policy-required approval state after booking creation."""
    if evaluation.get("outcome") != "needs_approval":
        return evaluation
    organization_id = _org(user)
    now = now_iso()
    conn.execute("UPDATE domain_bookings SET status = 'pending_approval', updated_at = ? WHERE id = ? AND organization_id = ?", (now, booking_id, organization_id))
    route = next((item.get("approval_route") for item in evaluation.get("reasons", []) if item.get("code") == "approval_required"), [])
    comment = json.dumps({"source": "corporate_policy", "policy_id": evaluation.get("policy_id"), "policy_version": evaluation.get("policy_version"), "approval_route": route}, separators=(",", ":"))
    conn.execute("INSERT INTO domain_booking_approvals(id, organization_id, booking_id, approver_id, status, comment, created_at, updated_at) VALUES (?, ?, ?, NULL, 'pending', ?, ?, ?)", (new_id("approval"), organization_id, booking_id, comment, now, now))
    _audit(conn, user, "corporate.booking.approval_required", "booking", booking_id, ip, {"policy_id": evaluation.get("policy_id"), "policy_version": evaluation.get("policy_version"), "approval_route": route})
    return {**evaluation, "booking_status": "pending_approval", "approval_route": route}


def _handle_visibility(conn, user, method: str, route: str, payload: dict, ip: str, finish) -> dict | None:
    if route not in {f"{CORPORATE_PREFIX}/visibility/evaluate", f"{CORPORATE_PREFIX}/permissions/evaluate"} or method not in {"GET", "POST"}:
        return None
    account = _account_required(conn, _org(user))
    result = _evaluate_visibility(conn, user, account, payload)
    return {"ok": True, **result}


def _supplier_candidates(conn, organization_id: str, allowed_ids: list[str], payload: dict) -> list[dict]:
    params: list[Any] = [organization_id]
    where = "organization_id = ? AND status = 'active'"
    if allowed_ids:
        where += f" AND id IN ({','.join('?' for _ in allowed_ids)})"
        params.extend(allowed_ids)
    rows = conn.execute(f"SELECT id, name, supplier_type, cities_json FROM domain_suppliers WHERE {where} ORDER BY name ASC, id ASC", params).fetchall()
    requested_city = str(payload.get("city") or "").strip().lower()
    result = []
    for row in rows:
        cities = [str(item).lower() for item in _json(row["cities_json"], [])]
        if requested_city and cities and requested_city not in cities:
            continue
        result.append({"id": row["id"], "name": row["name"], "supplier_type": row["supplier_type"], "match_reason": "allowlisted" if allowed_ids else "active_supplier"})
    return result


# ---------------------------------------------------------------------------
# Duty-slip approvals and signed-link lifecycle
# ---------------------------------------------------------------------------


def maybe_create_duty_slip_approval(conn, user, duty_id: str, ip: str) -> dict | None:
    """Create the first passenger slip when a governed duty closes.

    This hook is called by the local domain transition boundary, not by the
    browser.  It is idempotent per duty and deliberately does nothing when the
    corporate account/policy is not active or the source booking has no
    passenger email to receive a signed action link.
    """
    organization_id = _org(user)
    account = _account(conn, organization_id)
    if account is None or account["status"] != "active":
        return None
    policy = _active_policy(conn, account["id"])
    if not policy or not policy["passenger_duty_slip_approval"]:
        return None
    existing = conn.execute("SELECT * FROM corporate_duty_slip_approvals WHERE organization_id = ? AND account_id = ? AND duty_id = ? ORDER BY created_at DESC LIMIT 1", (organization_id, account["id"], duty_id)).fetchone()
    if existing:
        return {"item": _approval_dict(existing), "already_exists": True}
    duty = _assert_owned(conn, "domain_duties", duty_id, organization_id)
    booking = _assert_owned(conn, "domain_bookings", duty["booking_id"], organization_id)
    passenger_email = str(booking["passenger_email"] or "").strip().lower()
    # Do not send a link to an unverified/absent address.
    if not passenger_email:
        return {"blocked": True, "reason": "passenger_email_missing", "duty_id": duty_id}
    raw_token = secrets.token_urlsafe(32)
    created = _now()
    auto_at = created + timedelta(hours=int(policy["duty_slip_auto_approval_hours"] or 48))
    token_expires = created + timedelta(days=7)
    approval_id = new_id("slip")
    conn.execute("INSERT INTO corporate_duty_slip_approvals(id, organization_id, account_id, booking_id, duty_id, passenger_email, passenger_name, status, action_token_hash, token_expires_at, auto_approve_at, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)", (approval_id, organization_id, account["id"], booking["id"], duty_id, passenger_email, booking["passenger_name"], _hash(raw_token), _iso(token_expires), _iso(auto_at), user["id"], _iso(created)))
    _audit(conn, user, "corporate.duty_slip.request", "duty_slip_approval", approval_id, ip, {"source": "duty_completed", "auto_approve_at": _iso(auto_at)})
    row = conn.execute("SELECT * FROM corporate_duty_slip_approvals WHERE id = ?", (approval_id,)).fetchone()
    return {"item": _approval_dict(row, raw_token), "signed_link": f"/api/corporate/duty-slip-approvals/{approval_id}/action?token={raw_token}", "source": "duty_completed"}


def _handle_approvals(conn, user, method: str, route: str, payload: dict, ip: str, finish) -> dict | None:
    if not route.startswith(f"{CORPORATE_PREFIX}/duty-slip-approvals"):
        return None
    account = _account_required(conn, _org(user))
    if route == f"{CORPORATE_PREFIX}/duty-slip-approvals" and method == "GET":
        _require_permission(conn, user, account, "duty_slip.approve")
        status_filter = str(payload.get("status") or "").strip()
        sql = "SELECT * FROM corporate_duty_slip_approvals WHERE account_id = ? AND organization_id = ?"
        params: list[Any] = [account["id"], account["organization_id"]]
        if status_filter:
            sql += " AND status = ?"; params.append(status_filter)
        sql += " ORDER BY created_at DESC LIMIT 200"
        rows = conn.execute(sql, params).fetchall()
        return {"ok": True, "items": [_approval_dict(row) for row in rows], "count": len(rows)}
    if route == f"{CORPORATE_PREFIX}/duty-slip-approvals" and method == "POST":
        _require_permission(conn, user, account, "duty_slip.approve")
        policy = _active_policy(conn, account["id"])
        if not policy or not policy["passenger_duty_slip_approval"]:
            raise DomainError(409, "Passenger duty-slip approval is not enabled by the active policy", "duty_slip_policy_missing")
        booking_id = str(payload.get("booking_id") or "").strip() or None
        duty_id = str(payload.get("duty_id") or "").strip() or None
        if booking_id:
            _assert_owned(conn, "domain_bookings", booking_id, account["organization_id"])
        if duty_id:
            _assert_owned(conn, "domain_duties", duty_id, account["organization_id"])
        if not booking_id and not duty_id:
            raise DomainError(400, "booking_id or duty_id is required", "validation_error")
        email = _text(payload, "passenger_email", "", 254).lower()
        if not email or "@" not in email:
            raise DomainError(400, "A valid passenger_email is required", "validation_error")
        passenger_name = _text(payload, "passenger_name", "", 160)
        token = secrets.token_urlsafe(32)
        created = _now()
        token_expires = created + timedelta(days=7)
        auto_hours = int(policy["duty_slip_auto_approval_hours"] or 48)
        auto_at = created + timedelta(hours=auto_hours)
        approval_id = new_id("slip")
        conn.execute(
            "INSERT INTO corporate_duty_slip_approvals(id, organization_id, account_id, booking_id, duty_id, passenger_email, passenger_name, status, action_token_hash, token_expires_at, auto_approve_at, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)",
            (approval_id, account["organization_id"], account["id"], booking_id, duty_id, email, passenger_name, _hash(token), _iso(token_expires), _iso(auto_at), user["id"], _iso(created)),
        )
        _audit(conn, user, "corporate.duty_slip.request", "duty_slip_approval", approval_id, ip, {"booking_id": booking_id, "duty_id": duty_id, "auto_approve_at": _iso(auto_at)})
        row = conn.execute("SELECT * FROM corporate_duty_slip_approvals WHERE id = ?", (approval_id,)).fetchone()
        return finish({"ok": True, "item": _approval_dict(row, token), "signed_link": f"/api/corporate/duty-slip-approvals/{approval_id}/action?token={token}"})
    if route == f"{CORPORATE_PREFIX}/duty-slip-approvals/auto-approve" and method == "POST":
        _require_permission(conn, user, account, "duty_slip.approve")
        now = _iso(_now())
        rows = conn.execute("SELECT * FROM corporate_duty_slip_approvals WHERE account_id = ? AND organization_id = ? AND status = 'pending' AND auto_approve_at <= ? ORDER BY auto_approve_at ASC", (account["id"], account["organization_id"], now)).fetchall()
        changed = []
        for row in rows:
            conn.execute("UPDATE corporate_duty_slip_approvals SET status = 'auto_approved', decision_reason = '48_hour_expiry_auto_approval', decided_at = ? WHERE id = ? AND status = 'pending'", (now, row["id"]))
            changed.append(row["id"])
        if changed:
            _audit(conn, user, "corporate.duty_slip.auto_approve", "duty_slip_approval", account["id"], ip, {"approval_ids": changed, "count": len(changed)})
        return finish({"ok": True, "processed": len(changed), "approval_ids": changed, "reason": "48_hour_expiry_auto_approval"})
    match = __import__("re").match(rf"^{CORPORATE_PREFIX}/duty-slip-approvals/([^/]+)(?:/(approve|reject|action))?$", route)
    if not match:
        return None
    approval_id, action = match.group(1), match.group(2)
    row = conn.execute("SELECT * FROM corporate_duty_slip_approvals WHERE id = ? AND account_id = ? AND organization_id = ?", (approval_id, account["id"], account["organization_id"])).fetchone()
    if row is None:
        raise DomainError(404, "Duty-slip approval not found", "not_found")
    if method == "GET" and action is None:
        _require_permission(conn, user, account, "duty_slip.approve")
        return {"ok": True, "item": _approval_dict(row)}
    if action == "action" and method in {"GET", "POST"}:
        token = str(payload.get("action_token") or "").strip()
        if not token or not secrets.compare_digest(_hash(token), row["action_token_hash"]):
            raise DomainError(403, "The signed action link is invalid", "invalid_action_token")
        if _now() > _parse_time(row["token_expires_at"], "token_expires_at"):
            raise DomainError(410, "The signed action link has expired", "action_token_expired")
        action = str(payload.get("decision") or "").strip().lower() if method == "POST" else ""
        if action not in {"approve", "reject"}:
            return {"ok": True, "item": _approval_dict(row), "allowed_actions": ["approve", "reject"]}
    else:
        _require_permission(conn, user, account, "duty_slip.approve" if action == "approve" else "duty_slip.reject")
    if method != "POST" or action not in {"approve", "reject"}:
        return None
    if row["status"] != "pending":
        return {"ok": True, "item": _approval_dict(row), "already_decided": True}
    next_status = "approved" if action == "approve" else "rejected"
    comment = _text(payload, "comment", "", 500)
    now = now_iso()
    conn.execute("UPDATE corporate_duty_slip_approvals SET status = ?, decision_comment = ?, decision_reason = ?, decided_by = ?, decided_at = ? WHERE id = ? AND status = 'pending'", (next_status, comment, "passenger_action" if action == "approve" else "passenger_rejection", user["id"], now, approval_id))
    _audit(conn, user, f"corporate.duty_slip.{action}", "duty_slip_approval", approval_id, ip, {"comment_present": bool(comment)})
    return finish({"ok": True, "item": _approval_dict(conn.execute("SELECT * FROM corporate_duty_slip_approvals WHERE id = ?", (approval_id,)).fetchone())})


# ---------------------------------------------------------------------------
# Versioned masters and deterministic allotment/document guards
# ---------------------------------------------------------------------------


def _handle_masters(conn, user, method: str, route: str, payload: dict, ip: str, finish) -> dict | None:
    if not route.startswith(f"{CORPORATE_PREFIX}/masters"):
        return None
    account = _account_required(conn, _org(user))
    if method == "GET" and route == f"{CORPORATE_PREFIX}/masters":
        _require_permission(conn, user, account, "masters.read")
        kind = str(payload.get("kind") or "").strip()
        params: list[Any] = [account["organization_id"]]
        sql = "SELECT * FROM corporate_masters WHERE organization_id = ? AND status = 'active'"
        if kind:
            if kind not in MASTER_KINDS:
                raise DomainError(400, "Unsupported master kind", "validation_error")
            sql += " AND kind = ?"; params.append(kind)
        sql += " ORDER BY kind ASC, code ASC, version DESC"
        rows = conn.execute(sql, params).fetchall()
        # Latest version per logical master is the active read model.
        seen: set[tuple[str, str]] = set(); latest = []
        for row in rows:
            key = (row["kind"], row["code"])
            if key not in seen:
                seen.add(key); latest.append(_master_dict(row))
        return {"ok": True, "items": latest, "count": len(latest)}
    if method == "POST" and route == f"{CORPORATE_PREFIX}/masters":
        _require_permission(conn, user, account, "masters.manage")
        kind = _text(payload, "kind", "", 50).lower()
        if kind not in MASTER_KINDS:
            raise DomainError(400, "Unsupported master kind", "validation_error")
        code = _text(payload, "code", "", 80).upper()
        name = _text(payload, "name", "", 160)
        if not code or not name:
            raise DomainError(400, "code and name are required", "validation_error")
        scope = _scope(payload.get("scope", {}), "scope")
        config = _json_object(payload.get("config", {}), "config")
        previous = conn.execute("SELECT * FROM corporate_masters WHERE organization_id = ? AND kind = ? AND code = ? ORDER BY version DESC LIMIT 1", (account["organization_id"], kind, code)).fetchone()
        version = int(previous["version"]) + 1 if previous else 1
        now = now_iso()
        master_id = new_id("corpmaster")
        conn.execute("INSERT INTO corporate_masters(id, organization_id, kind, code, name, version, status, effective_from, effective_to, scope_json, config_json, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (master_id, account["organization_id"], kind, code, name, version, "active", payload.get("effective_from"), payload.get("effective_to"), json.dumps(scope), json.dumps(config), user["id"], now))
        _audit(conn, user, "corporate.master.version", "corporate_master", master_id, ip, {"kind": kind, "code": code, "version": version})
        return finish({"ok": True, "item": _master_dict(conn.execute("SELECT * FROM corporate_masters WHERE id = ?", (master_id,)).fetchone()), "previous_version": previous["id"] if previous else None})
    match = __import__("re").match(rf"^{CORPORATE_PREFIX}/masters/([^/]+)$", route)
    if not match:
        return None
    master_id = match.group(1)
    master = conn.execute("SELECT * FROM corporate_masters WHERE id = ? AND organization_id = ?", (master_id, account["organization_id"])).fetchone()
    if master is None:
        raise DomainError(404, "Corporate master record not found", "not_found")
    if method == "GET":
        _require_permission(conn, user, account, "masters.read")
        versions = conn.execute("SELECT * FROM corporate_masters WHERE organization_id = ? AND kind = ? AND code = ? ORDER BY version DESC", (account["organization_id"], master["kind"], master["code"])).fetchall()
        return {"ok": True, "item": _master_dict(master), "versions": [_master_dict(row) for row in versions]}
    if method == "PATCH":
        _require_permission(conn, user, account, "masters.manage")
        if payload.get("status") not in {None, "active", "archived"}:
            raise DomainError(400, "Unsupported master status", "validation_error")
        if payload.get("status") == "archived":
            conn.execute("UPDATE corporate_masters SET status = 'archived' WHERE id = ? AND organization_id = ?", (master_id, account["organization_id"]))
            _audit(conn, user, "corporate.master.archive", "corporate_master", master_id, ip, {})
            return finish({"ok": True, "item": _master_dict(conn.execute("SELECT * FROM corporate_masters WHERE id = ?", (master_id,)).fetchone())})
    return None


def _allotment_rule(conn, account, policy) -> Any:
    rule_id = policy["allotment_rule_id"] if policy else None
    if rule_id:
        return conn.execute("SELECT * FROM corporate_allotment_rules WHERE id = ? AND account_id = ? AND organization_id = ?", (rule_id, account["id"], account["organization_id"])).fetchone()
    return conn.execute("SELECT * FROM corporate_allotment_rules WHERE account_id = ? AND organization_id = ? AND status = 'active' ORDER BY priority ASC, version DESC LIMIT 1", (account["id"], account["organization_id"])).fetchone()


def _document_guard(conn, organization_id: str, vehicle_id: str | None, required_types: list[str]) -> list[dict]:
    if not required_types:
        return []
    reasons: list[dict] = []
    if not vehicle_id:
        return [_reason("vehicle_required_for_document_guard", "A vehicle is required to verify document validity.", "block", document_types=required_types)]
    _assert_owned(conn, "domain_vehicles", vehicle_id, organization_id)
    now = now_iso()
    for doc_type in required_types:
        row = conn.execute("SELECT * FROM domain_documents WHERE organization_id = ? AND entity_type = 'vehicle' AND entity_id = ? AND document_type = ? ORDER BY updated_at DESC, created_at DESC LIMIT 1", (organization_id, vehicle_id, doc_type)).fetchone()
        if row is None:
            reasons.append(_reason("document_missing", f"Required vehicle document {doc_type} is missing.", "block", document_type=doc_type))
            continue
        if row["status"] not in {"approved", "valid", "active"}:
            reasons.append(_reason("document_not_valid", f"Vehicle document {doc_type} is not approved or valid.", "block", document_type=doc_type, status=row["status"]))
            continue
        if row["expires_at"] and row["expires_at"] <= now:
            reasons.append(_reason("document_expired", f"Vehicle document {doc_type} has expired.", "block", document_type=doc_type, expires_at=row["expires_at"]))
    return reasons


def _handle_allotment(conn, user, method: str, route: str, payload: dict, ip: str, finish) -> dict | None:
    if route not in {f"{CORPORATE_PREFIX}/allotment/evaluate", f"{CORPORATE_PREFIX}/allotment/eligibility"} or method != "POST":
        return None
    account = _account_required(conn, _org(user))
    _require_permission(conn, user, account, "allotment.evaluate")
    policy = _active_policy(conn, account["id"], str(payload.get("policy_id") or "").strip() or None)
    rule = _allotment_rule(conn, account, policy)
    reasons: list[dict] = []
    if account["status"] != "active":
        reasons.append(_reason("corporate_account_not_active", "The corporate account is not active.", "block"))
    visibility = _evaluate_visibility(conn, user, account, payload)
    reasons.extend(visibility["reasons"])
    required_documents = _parse_json_list(payload.get("required_document_types", _json(rule["required_document_types_json"], []) if rule else []), "required_document_types")
    reasons.extend(_document_guard(conn, account["organization_id"], str(payload.get("vehicle_id") or "").strip() or None, required_documents))
    candidates: list[dict] = []
    allowed_supplier_ids = _json(policy["allowed_supplier_ids_json"], []) if policy else []
    if rule and _json(rule["supplier_ids_json"], []):
        allowed_supplier_ids = _json(rule["supplier_ids_json"], [])
    candidates = _supplier_candidates(conn, account["organization_id"], allowed_supplier_ids, payload)
    if not candidates:
        reasons.append(_reason("no_eligible_supplier", "No active supplier satisfies the deterministic allotment filters.", "block"))
    outcome = "block" if any(item["severity"] == "block" for item in reasons) else "allow"
    result = {"ok": True, "outcome": outcome, "eligible": outcome == "allow", "policy_id": policy["id"] if policy else None, "rule_id": rule["id"] if rule else None, "rule_version": rule["version"] if rule else None, "candidates": candidates, "reasons": reasons, "document_guard": {"required": required_documents, "passed": not any(item.get("code") in {"document_missing", "document_not_valid", "document_expired", "vehicle_required_for_document_guard"} for item in reasons)}, "deterministic": True, "evaluated_at": now_iso()}
    _audit(conn, user, "corporate.allotment.evaluate", "corporate_allotment_rule", rule["id"] if rule else account["id"], ip, {"outcome": outcome, "candidate_count": len(candidates)})
    return finish(result)


def _handle_allotment_rules(conn, user, method: str, route: str, payload: dict, ip: str, finish) -> dict | None:
    if route != f"{CORPORATE_PREFIX}/allotment/rules":
        return None
    account = _account_required(conn, _org(user))
    if method == "GET":
        _require_permission(conn, user, account, "allotment.evaluate")
        rows = conn.execute("SELECT * FROM corporate_allotment_rules WHERE account_id = ? AND organization_id = ? ORDER BY priority ASC, version DESC", (account["id"], account["organization_id"])).fetchall()
        return {"ok": True, "items": [_row(row, ("supplier_ids_json", "vehicle_group_codes_json", "duty_type_codes_json", "cities_json", "required_document_types_json", "rules_json")) for row in rows], "count": len(rows)}
    if method == "POST":
        _require_permission(conn, user, account, "allotment.manage")
        name = _text(payload, "name", "", 160)
        if not name:
            raise DomainError(400, "name is required", "validation_error")
        suppliers = _parse_json_list(payload.get("supplier_ids"), "supplier_ids")
        _owned_ids(conn, "domain_suppliers", suppliers, account["organization_id"], "suppliers")
        rule_status = _text(payload, "status", "draft", 20).lower()
        if rule_status not in {"draft", "active", "archived"}:
            raise DomainError(400, "Unsupported allotment rule status", "validation_error")
        fallback_supplier_id = str(payload.get("fallback_supplier_id") or "").strip() or None
        if fallback_supplier_id:
            _assert_owned(conn, "domain_suppliers", fallback_supplier_id, account["organization_id"])
        rule_id = new_id("allot")
        now = now_iso()
        conn.execute("INSERT INTO corporate_allotment_rules(id, organization_id, account_id, name, version, status, priority, supplier_ids_json, vehicle_group_codes_json, duty_type_codes_json, cities_json, required_document_types_json, auto_allot, fallback_supplier_id, max_attempts, rules_json, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (rule_id, account["organization_id"], account["id"], name, _int(payload.get("version"), "version", default=1, maximum=10000), rule_status, _int(payload.get("priority"), "priority", default=1000, maximum=100000), json.dumps(suppliers), json.dumps(_parse_json_list(payload.get("vehicle_group_codes"), "vehicle_group_codes")), json.dumps(_parse_json_list(payload.get("duty_type_codes"), "duty_type_codes")), json.dumps(_parse_json_list(payload.get("cities"), "cities")), json.dumps(_parse_json_list(payload.get("required_document_types"), "required_document_types")), int(_bool(payload.get("auto_allot"), "auto_allot")), fallback_supplier_id, _int(payload.get("max_attempts"), "max_attempts", default=1, maximum=20), json.dumps(_json_object(payload.get("rules", {}), "rules")), user["id"], now, now))
        _audit(conn, user, "corporate.allotment_rule.create", "corporate_allotment_rule", rule_id, ip, {"version": _int(payload.get("version"), "version", default=1, maximum=10000)})
        return finish({"ok": True, "item": _row(conn.execute("SELECT * FROM corporate_allotment_rules WHERE id = ?", (rule_id,)).fetchone(), ("supplier_ids_json", "vehicle_group_codes_json", "duty_type_codes_json", "cities_json", "required_document_types_json", "rules_json"))})
    return None


# ---------------------------------------------------------------------------
# Signed passenger action link (public token boundary)
# ---------------------------------------------------------------------------


def handle_corporate_public(conn, method: str, path: str, payload: dict, ip: str) -> dict | None:
    parsed = urlsplit(path)
    match = __import__("re").match(rf"^{CORPORATE_PREFIX}/duty-slip-approvals/([^/]+)/action$", parsed.path.rstrip("/"))
    if not match:
        return None
    approval_id = match.group(1)
    query = parse_qs(parsed.query)
    token = str(payload.get("action_token") or (query.get("token") or [""])[-1]).strip()
    if not token:
        raise DomainError(403, "A signed action token is required", "invalid_action_token")
    row = conn.execute("SELECT * FROM corporate_duty_slip_approvals WHERE id = ? AND action_token_hash = ?", (approval_id, _hash(token))).fetchone()
    if row is None:
        raise DomainError(403, "The signed action link is invalid", "invalid_action_token")
    if _now() > _parse_time(row["token_expires_at"], "token_expires_at"):
        raise DomainError(410, "The signed action link has expired", "action_token_expired")
    if method == "GET":
        return {"ok": True, "item": _approval_dict(row), "allowed_actions": ["approve", "reject"] if row["status"] == "pending" else []}
    if method != "POST":
        raise DomainError(405, "Signed action supports GET or POST", "method_not_allowed")
    decision = str(payload.get("decision") or "").strip().lower()
    if decision not in {"approve", "reject"}:
        raise DomainError(400, "decision must be approve or reject", "validation_error")
    if row["status"] != "pending":
        return {"ok": True, "item": _approval_dict(row), "already_decided": True}
    comment = _text(payload, "comment", "", 500)
    status_value = "approved" if decision == "approve" else "rejected"
    now = now_iso()
    conn.execute("UPDATE corporate_duty_slip_approvals SET status = ?, decision_comment = ?, decision_reason = ?, decided_at = ? WHERE id = ? AND status = 'pending'", (status_value, comment, "passenger_signed_link", now, approval_id))
    conn.execute("INSERT INTO audit_events(id, user_id, action, entity_type, entity_id, metadata_json, ip_address, created_at) VALUES (?, NULL, ?, ?, ?, ?, ?, ?)", (new_id("audit"), f"corporate.duty_slip.{decision}", "duty_slip_approval", approval_id, json.dumps({"source": "signed_link", "comment_present": bool(comment)}), ip, now))
    return {"ok": True, "item": _approval_dict(conn.execute("SELECT * FROM corporate_duty_slip_approvals WHERE id = ?", (approval_id,)).fetchone())}


# ---------------------------------------------------------------------------
# Public module dispatcher
# ---------------------------------------------------------------------------


def handle_corporate(conn, user, method: str, path: str, payload: dict, ip: str) -> dict | None:
    """Return a response for a corporate route, or None for another module."""
    parsed = urlsplit(path)
    route = parsed.path.rstrip("/") or "/"
    if not route.startswith(CORPORATE_PREFIX):
        return None
    query_payload = {key: values[-1] for key, values in parse_qs(parsed.query).items() if values}
    # Query parameters are deliberately copied only into the module-local
    # payload.  This keeps signed-link tokens and read filters available while
    # preserving the server's normal JSON-body contract.
    if query_payload:
        payload = {**query_payload, **payload}
    organization_id = _org(user)
    key = _idempotency_key(payload) if method in {"POST", "PATCH", "DELETE"} else ""
    replay = _replay_lookup(conn, organization_id, key, route)
    if replay is not None:
        return replay

    def finish(result: dict) -> dict:
        return _replay_store(conn, organization_id, key, route, result)

    # Dispatch the most specific routes first.  The handlers use their own
    # tenant-scoped ownership checks and return None when they do not match.
    for handler in (_handle_account, _handle_account_users, _handle_policies, _handle_visibility, _handle_approvals, _handle_masters, _handle_allotment, _handle_allotment_rules):
        result = handler(conn, user, method, route, payload, ip, finish)
        if result is not None:
            return result
    raise DomainError(404, "Corporate route not found", "not_found")
