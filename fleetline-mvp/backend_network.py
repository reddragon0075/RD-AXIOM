"""Closed, tenant-scoped Axiom Network MVP domain for the local fallback.

The Network is deliberately additive to the existing edge/offer/bid/settlement
routes.  It governs a buyer requirement through immutable versions, deterministic
eligibility, explainable matching, confidential quote snapshots, comparison,
approval, contract/SLA checks, activation into Fleet records, scorecards and
settlement evidence.  Supabase parity lives in the accompanying migration.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
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
    now_iso,
    new_id,
)


NETWORK_PREFIX = "/api/network/v1"


def initialize_network_schema(conn: sqlite3.Connection) -> None:
    """Create only additive local tables; never alter the compatibility schema."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS domain_network_feature_flags (
            organization_id TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1,
            mode TEXT NOT NULL DEFAULT 'closed_invite_only',
            updated_by TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_network_invites (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            vendor_organization_id TEXT,
            vendor_name TEXT NOT NULL DEFAULT '',
            invite_email TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            expires_at TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            accepted_at TEXT,
            revoked_at TEXT,
            idempotency_key TEXT,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_network_programs (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            settings_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, code)
        );
        CREATE TABLE IF NOT EXISTS domain_network_requirements (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            program_id TEXT NOT NULL,
            reference TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            current_version INTEGER,
            current_version_id TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, reference)
        );
        CREATE TABLE IF NOT EXISTS domain_network_requirement_versions (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            requirement_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            payload_json TEXT NOT NULL DEFAULT '{}',
            change_note TEXT NOT NULL DEFAULT '',
            created_by TEXT,
            created_at TEXT NOT NULL,
            published_at TEXT,
            UNIQUE(organization_id, requirement_id, version)
        );
        CREATE TABLE IF NOT EXISTS domain_network_vendor_profiles (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            vendor_organization_id TEXT NOT NULL,
            vendor_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            cities_json TEXT NOT NULL DEFAULT '[]',
            service_types_json TEXT NOT NULL DEFAULT '[]',
            vehicle_types_json TEXT NOT NULL DEFAULT '[]',
            capabilities_json TEXT NOT NULL DEFAULT '[]',
            capacity_json TEXT NOT NULL DEFAULT '{}',
            compliance_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            invite_id TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, vendor_organization_id)
        );
        CREATE TABLE IF NOT EXISTS domain_network_match_runs (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            requirement_id TEXT NOT NULL,
            requirement_version_id TEXT NOT NULL,
            rules_version TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'completed',
            rules_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            idempotency_key TEXT,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_network_candidates (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            match_run_id TEXT NOT NULL,
            requirement_id TEXT NOT NULL,
            vendor_profile_id TEXT NOT NULL,
            eligible INTEGER NOT NULL DEFAULT 0,
            exclusion_reasons_json TEXT NOT NULL DEFAULT '[]',
            score_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE(match_run_id, vendor_profile_id)
        );
        CREATE TABLE IF NOT EXISTS domain_network_quotes (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            requirement_id TEXT NOT NULL,
            vendor_profile_id TEXT NOT NULL,
            bidder_organization_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'submitted',
            current_version INTEGER NOT NULL DEFAULT 0,
            current_version_id TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, requirement_id, vendor_profile_id)
        );
        CREATE TABLE IF NOT EXISTS domain_network_quote_versions (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            quote_id TEXT NOT NULL,
            requirement_id TEXT NOT NULL,
            vendor_profile_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'submitted',
            payload_json TEXT NOT NULL DEFAULT '{}',
            assumptions_json TEXT NOT NULL DEFAULT '{}',
            submitted_by TEXT,
            submitted_at TEXT NOT NULL,
            idempotency_key TEXT,
            UNIQUE(organization_id, idempotency_key),
            UNIQUE(quote_id, version)
        );
        CREATE TABLE IF NOT EXISTS domain_network_quote_line_items (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            quote_version_id TEXT NOT NULL,
            line_code TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            unit TEXT NOT NULL DEFAULT '',
            quantity REAL NOT NULL DEFAULT 1,
            unit_paise INTEGER NOT NULL DEFAULT 0,
            amount_paise INTEGER NOT NULL DEFAULT 0,
            tax_bps INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            UNIQUE(quote_version_id, line_code)
        );
        CREATE TABLE IF NOT EXISTS domain_network_record_versions (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            change_type TEXT NOT NULL DEFAULT 'snapshot',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, entity_type, entity_id, version)
        );
        CREATE TABLE IF NOT EXISTS domain_network_comparisons (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            requirement_id TEXT NOT NULL,
            match_run_id TEXT,
            status TEXT NOT NULL DEFAULT 'ready',
            quote_version_ids_json TEXT NOT NULL DEFAULT '[]',
            quote_snapshots_json TEXT NOT NULL DEFAULT '[]',
            rules_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            idempotency_key TEXT,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_network_awards (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            requirement_id TEXT NOT NULL,
            comparison_id TEXT NOT NULL,
            quote_version_id TEXT NOT NULL,
            vendor_profile_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending_approval',
            award_reason TEXT NOT NULL DEFAULT '',
            rejected_alternatives_json TEXT NOT NULL DEFAULT '[]',
            terms_json TEXT NOT NULL DEFAULT '{}',
            approved_by TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            approved_at TEXT,
            idempotency_key TEXT,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_network_contracts (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            award_id TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'draft',
            starts_at TEXT,
            ends_at TEXT,
            terms_json TEXT NOT NULL DEFAULT '{}',
            signed_by TEXT,
            signed_at TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_network_slas (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            contract_id TEXT NOT NULL,
            metric TEXT NOT NULL,
            target_value REAL NOT NULL DEFAULT 0,
            unit TEXT NOT NULL DEFAULT '',
            severity TEXT NOT NULL DEFAULT 'warning',
            evidence_required INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            UNIQUE(contract_id, metric)
        );
        CREATE TABLE IF NOT EXISTS domain_network_activation_checks (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            award_id TEXT NOT NULL,
            check_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            blocking INTEGER NOT NULL DEFAULT 1,
            evidence_json TEXT NOT NULL DEFAULT '{}',
            checked_by TEXT,
            checked_at TEXT,
            UNIQUE(award_id, check_key)
        );
        CREATE TABLE IF NOT EXISTS domain_network_service_orders (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            award_id TEXT NOT NULL UNIQUE,
            contract_id TEXT NOT NULL,
            requirement_id TEXT NOT NULL,
            vendor_profile_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            fleet_booking_id TEXT,
            fleet_duty_id TEXT,
            config_json TEXT NOT NULL DEFAULT '{}',
            activated_by TEXT,
            activated_at TEXT NOT NULL,
            idempotency_key TEXT,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_network_scorecards (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            service_order_id TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'submitted',
            metrics_json TEXT NOT NULL DEFAULT '{}',
            evidence_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            idempotency_key TEXT,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_network_settlements (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            service_order_id TEXT NOT NULL,
            scorecard_id TEXT,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            gross_paise INTEGER NOT NULL DEFAULT 0,
            deductions_paise INTEGER NOT NULL DEFAULT 0,
            net_paise INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'draft',
            evidence_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            idempotency_key TEXT,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_network_events (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            aggregate_type TEXT NOT NULL,
            aggregate_id TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_network_partner_directory (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            vendor_organization_id TEXT NOT NULL,
            vendor_profile_id TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL DEFAULT '',
            verification_status TEXT NOT NULL DEFAULT 'verified',
            verified_at TEXT,
            discovered_via TEXT NOT NULL DEFAULT 'invite',
            search_document_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, vendor_organization_id)
        );
        CREATE TABLE IF NOT EXISTS domain_network_associates (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            vendor_organization_id TEXT NOT NULL,
            invite_id TEXT NOT NULL UNIQUE,
            vendor_profile_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            buyer_contact TEXT NOT NULL DEFAULT '',
            vendor_contact TEXT NOT NULL DEFAULT '',
            acceptance_note TEXT NOT NULL DEFAULT '',
            accepted_by TEXT,
            accepted_at TEXT,
            rejected_at TEXT,
            revoked_at TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_network_contract_versions (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            contract_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            terms_json TEXT NOT NULL DEFAULT '{}',
            effective_from TEXT,
            effective_to TEXT,
            source TEXT NOT NULL DEFAULT 'network',
            supersedes_version_id TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            accepted_by TEXT,
            accepted_at TEXT,
            UNIQUE(contract_id, version)
        );
        CREATE TABLE IF NOT EXISTS domain_network_rate_cards (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            contract_version_id TEXT NOT NULL,
            rate_code TEXT NOT NULL,
            service_type TEXT NOT NULL DEFAULT '',
            vehicle_type TEXT NOT NULL DEFAULT '',
            city TEXT NOT NULL DEFAULT '',
            unit TEXT NOT NULL DEFAULT 'trip',
            amount_paise INTEGER NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT 'INR',
            effective_from TEXT,
            effective_to TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            terms_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(contract_version_id, rate_code)
        );
        CREATE TABLE IF NOT EXISTS domain_network_contract_syncs (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            contract_id TEXT NOT NULL,
            contract_version_id TEXT,
            direction TEXT NOT NULL DEFAULT 'outbound',
            status TEXT NOT NULL DEFAULT 'queued',
            source_version INTEGER,
            target_version INTEGER,
            change_summary_json TEXT NOT NULL DEFAULT '{}',
            provider_reference TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT,
            requested_by TEXT,
            acknowledged_by TEXT,
            requested_at TEXT NOT NULL,
            acknowledged_at TEXT,
            error TEXT NOT NULL DEFAULT '',
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_network_exchange_envelopes (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            service_order_id TEXT NOT NULL,
            exchange_type TEXT NOT NULL,
            direction TEXT NOT NULL DEFAULT 'outbound',
            status TEXT NOT NULL DEFAULT 'queued',
            schema_version TEXT NOT NULL DEFAULT 'v1',
            external_reference TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            attachments_json TEXT NOT NULL DEFAULT '[]',
            idempotency_key TEXT,
            sender_organization_id TEXT,
            recipient_organization_id TEXT,
            provider_reference TEXT NOT NULL DEFAULT '',
            created_by TEXT,
            created_at TEXT NOT NULL,
            sent_at TEXT,
            acknowledged_at TEXT,
            processed_at TEXT,
            error TEXT NOT NULL DEFAULT '',
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_network_sla_observations (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            service_order_id TEXT NOT NULL,
            sla_id TEXT,
            metric TEXT NOT NULL,
            target_value REAL NOT NULL DEFAULT 0,
            observed_value REAL NOT NULL DEFAULT 0,
            unit TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'met',
            severity TEXT NOT NULL DEFAULT 'warning',
            evidence_json TEXT NOT NULL DEFAULT '{}',
            observed_at TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'operator',
            idempotency_key TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_network_supplier_issues (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            service_order_id TEXT NOT NULL,
            vendor_profile_id TEXT,
            issue_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            severity TEXT NOT NULL DEFAULT 'medium',
            reason_code TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            evidence_json TEXT NOT NULL DEFAULT '{}',
            proposed_resolution_json TEXT NOT NULL DEFAULT '{}',
            resolution_json TEXT NOT NULL DEFAULT '{}',
            reported_by TEXT,
            assigned_to TEXT,
            due_at TEXT,
            resolved_by TEXT,
            resolved_at TEXT,
            idempotency_key TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_network_rate_discrepancies (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            service_order_id TEXT NOT NULL,
            contract_id TEXT,
            rate_card_id TEXT,
            issue_id TEXT,
            expected_paise INTEGER NOT NULL DEFAULT 0,
            actual_paise INTEGER NOT NULL DEFAULT 0,
            variance_paise INTEGER NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT 'INR',
            status TEXT NOT NULL DEFAULT 'open',
            reason TEXT NOT NULL DEFAULT '',
            evidence_json TEXT NOT NULL DEFAULT '{}',
            resolution_json TEXT NOT NULL DEFAULT '{}',
            idempotency_key TEXT,
            created_by TEXT,
            resolved_by TEXT,
            resolved_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS domain_network_settlement_resolutions (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            service_order_id TEXT,
            settlement_id TEXT NOT NULL,
            issue_id TEXT,
            discrepancy_id TEXT,
            status TEXT NOT NULL DEFAULT 'proposed',
            resolution_type TEXT NOT NULL DEFAULT 'adjustment',
            adjustment_paise INTEGER NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            evidence_json TEXT NOT NULL DEFAULT '{}',
            proposed_by TEXT,
            decided_by TEXT,
            decided_at TEXT,
            applied_at TEXT,
            idempotency_key TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(organization_id, idempotency_key)
        );
        CREATE INDEX IF NOT EXISTS idx_network_partner_directory_org_status ON domain_network_partner_directory(organization_id, verification_status, updated_at);
        CREATE INDEX IF NOT EXISTS idx_network_associates_org_status ON domain_network_associates(organization_id, status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_network_associates_vendor_status ON domain_network_associates(vendor_organization_id, status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_network_contract_versions_contract ON domain_network_contract_versions(contract_id, version DESC);
        CREATE INDEX IF NOT EXISTS idx_network_rate_cards_version ON domain_network_rate_cards(contract_version_id, status, rate_code);
        CREATE INDEX IF NOT EXISTS idx_network_contract_syncs_contract ON domain_network_contract_syncs(contract_id, requested_at DESC);
        CREATE INDEX IF NOT EXISTS idx_network_exchange_service_order ON domain_network_exchange_envelopes(service_order_id, exchange_type, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_network_sla_observations_order ON domain_network_sla_observations(service_order_id, observed_at DESC);
        CREATE INDEX IF NOT EXISTS idx_network_supplier_issues_order ON domain_network_supplier_issues(service_order_id, status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_network_rate_discrepancies_order ON domain_network_rate_discrepancies(service_order_id, status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_network_settlement_resolutions_settlement ON domain_network_settlement_resolutions(settlement_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_network_programs_org_status ON domain_network_programs(organization_id, status, updated_at);
        CREATE INDEX IF NOT EXISTS idx_network_requirements_org_status ON domain_network_requirements(organization_id, status, updated_at);
        CREATE INDEX IF NOT EXISTS idx_network_versions_requirement ON domain_network_requirement_versions(requirement_id, version DESC);
        CREATE INDEX IF NOT EXISTS idx_network_profiles_org_status ON domain_network_vendor_profiles(organization_id, status);
        CREATE INDEX IF NOT EXISTS idx_network_profiles_vendor_org ON domain_network_vendor_profiles(vendor_organization_id, status);
        CREATE INDEX IF NOT EXISTS idx_network_candidates_requirement ON domain_network_candidates(requirement_id, eligible, created_at);
        CREATE INDEX IF NOT EXISTS idx_network_quotes_requirement ON domain_network_quotes(organization_id, requirement_id, status);
        CREATE INDEX IF NOT EXISTS idx_network_quote_versions_quote ON domain_network_quote_versions(quote_id, version DESC);
        CREATE INDEX IF NOT EXISTS idx_network_quote_line_items_version ON domain_network_quote_line_items(quote_version_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_network_record_versions_entity ON domain_network_record_versions(organization_id, entity_type, entity_id, version DESC);
        CREATE INDEX IF NOT EXISTS idx_network_comparisons_requirement ON domain_network_comparisons(organization_id, requirement_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_network_awards_org_status ON domain_network_awards(organization_id, status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_network_checks_award ON domain_network_activation_checks(award_id, status);
        CREATE INDEX IF NOT EXISTS idx_network_service_orders_org_status ON domain_network_service_orders(organization_id, status, activated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_network_scorecards_service_order ON domain_network_scorecards(service_order_id, period_start DESC);
        CREATE INDEX IF NOT EXISTS idx_network_settlements_service_order ON domain_network_settlements(service_order_id, period_start DESC);
        CREATE INDEX IF NOT EXISTS idx_network_events_org_time ON domain_network_events(organization_id, created_at DESC);
        """
    )
    try:
        conn.execute("ALTER TABLE domain_network_settlement_resolutions ADD COLUMN service_order_id TEXT")
    except sqlite3.OperationalError:
        pass


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _norm_list(value) -> list[str]:
    return sorted({str(item).strip().casefold() for item in _json_list(value) if str(item).strip()})


def _json_object(value) -> dict:
    return value if isinstance(value, dict) else {}


def _payload_json(payload: dict, key: str, default=None):
    value = payload.get(key, default)
    if isinstance(value, (dict, list)):
        return value
    return default


def _positive_int(value, field: str, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise DomainError(400, f"{field} must be an integer", "validation_error") from exc
    if number < 0:
        raise DomainError(400, f"{field} cannot be negative", "validation_error")
    return number


def _limit(query: dict, default: int = 100) -> int:
    try:
        return min(max(int(query.get("limit", [default])[0] or default), 1), 500)
    except (ValueError, TypeError):
        return default


def _network_operator(user) -> None:
    _require_role(user, ("vendor", "corporate"))


def _network_org(user) -> str:
    _network_operator(user)
    return _org(user)


def _network_enabled(conn: sqlite3.Connection, org: str) -> bool:
    row = conn.execute("SELECT enabled FROM domain_network_feature_flags WHERE organization_id = ?", (org,)).fetchone()
    return row is None or bool(row["enabled"])


def _ensure_enabled(conn: sqlite3.Connection, org: str, user, *, allow_flag_route: bool = False) -> None:
    row = conn.execute("SELECT * FROM domain_network_feature_flags WHERE organization_id = ?", (org,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO domain_network_feature_flags(organization_id, enabled, mode, updated_by, updated_at) VALUES (?, 1, 'closed_invite_only', ?, ?)",
            (org, user["id"], now_iso()),
        )
        return
    if not row["enabled"] and not allow_flag_route:
        raise DomainError(403, "Axiom Network is disabled for this organization", "network_disabled")


def _owned(conn, table: str, entity_id: str, org: str, message: str = "Record not found"):
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ? AND organization_id = ?", (entity_id, org)).fetchone()
    if row is None:
        raise DomainError(404, message, "not_found")
    return row


def _row_json(row, fields: tuple[str, ...] = ()):
    item = _serialize(row)
    for field in fields:
        if field in item:
            item[field] = _json(item[field], {} if field.endswith("_json") and field not in ("exclusion_reasons_json",) else [])
    return item


def _emit(conn, user, event_type: str, aggregate_type: str, aggregate_id: str, ip: str, payload=None, organization_id: str | None = None) -> None:
    org = organization_id or _org(user)
    conn.execute(
        "INSERT INTO domain_network_events(id, organization_id, event_type, aggregate_type, aggregate_id, payload_json, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (new_id("network_event"), org, event_type, aggregate_type, aggregate_id, json.dumps(payload or {}), user["id"], now_iso()),
    )
    _audit(conn, user, f"network.{event_type}", aggregate_type, aggregate_id, ip, payload or {})


def _record_snapshot(conn, user, entity_type: str, entity_id: str, payload, change_type: str = "snapshot", organization_id: str | None = None) -> dict:
    org = organization_id or _org(user)
    next_version = conn.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 AS n FROM domain_network_record_versions WHERE organization_id = ? AND entity_type = ? AND entity_id = ?",
        (org, entity_type, entity_id),
    ).fetchone()["n"]
    record_id = new_id("network_version")
    conn.execute(
        "INSERT INTO domain_network_record_versions(id, organization_id, entity_type, entity_id, version, change_type, payload_json, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (record_id, org, entity_type, entity_id, int(next_version), change_type, json.dumps(payload or {}), user["id"], now_iso()),
    )
    return {"id": record_id, "version": int(next_version), "entity_type": entity_type, "entity_id": entity_id}


def _program_view(conn, row):
    item = _row_json(row, ("settings_json",))
    item["requirement_count"] = conn.execute("SELECT COUNT(*) AS n FROM domain_network_requirements WHERE program_id = ?", (row["id"],)).fetchone()["n"]
    return item


def _requirement_version(conn, requirement_id: str, version: int | None = None):
    if version is None:
        return conn.execute(
            "SELECT * FROM domain_network_requirement_versions WHERE requirement_id = ? ORDER BY version DESC LIMIT 1",
            (requirement_id,),
        ).fetchone()
    return conn.execute(
        "SELECT * FROM domain_network_requirement_versions WHERE requirement_id = ? AND version = ?",
        (requirement_id, version),
    ).fetchone()


def _requirement_view(conn, row, *, include_versions=True, include_payload=True):
    item = _row_json(row)
    if include_versions:
        versions = conn.execute(
            "SELECT * FROM domain_network_requirement_versions WHERE requirement_id = ? ORDER BY version DESC",
            (row["id"],),
        ).fetchall()
        item["versions"] = []
        for version in versions:
            version_item = _row_json(version, ("payload_json",))
            if not include_payload:
                version_item.pop("payload_json", None)
            item["versions"].append(version_item)
    return item


def _profile_view(row, *, include_compliance=True):
    fields = ("cities_json", "service_types_json", "vehicle_types_json", "capabilities_json", "capacity_json", "compliance_json", "metadata_json")
    item = _row_json(row, fields)
    if not include_compliance:
        item.pop("compliance_json", None)
        item.pop("metadata_json", None)
    return item


def _current_match(conn, requirement_id: str, org: str):
    return conn.execute(
        "SELECT * FROM domain_network_match_runs WHERE organization_id = ? AND requirement_id = ? ORDER BY created_at DESC LIMIT 1",
        (org, requirement_id),
    ).fetchone()


def _candidate_for(conn, requirement_id: str, vendor_profile_id: str):
    return conn.execute(
        """
        SELECT c.*, m.organization_id, m.requirement_id AS matched_requirement_id
        FROM domain_network_candidates c
        JOIN domain_network_match_runs m ON m.id = c.match_run_id
        WHERE c.requirement_id = ? AND c.vendor_profile_id = ?
        ORDER BY c.created_at DESC LIMIT 1
        """,
        (requirement_id, vendor_profile_id),
    ).fetchone()


def _candidate_view(conn, row):
    item = _row_json(row, ("exclusion_reasons_json", "score_json"))
    profile = conn.execute("SELECT * FROM domain_network_vendor_profiles WHERE id = ?", (row["vendor_profile_id"],)).fetchone()
    item["vendor_profile"] = _profile_view(profile, include_compliance=False) if profile else None
    return item


def _quote_view(conn, row, *, include_payload=False):
    item = _row_json(row)
    profile = conn.execute("SELECT id, vendor_name, vendor_organization_id, status FROM domain_network_vendor_profiles WHERE id = ?", (row["vendor_profile_id"],)).fetchone()
    item["vendor_profile"] = _serialize(profile) if profile else None
    version = conn.execute(
        "SELECT * FROM domain_network_quote_versions WHERE id = ?", (row["current_version_id"],)
    ).fetchone() if row["current_version_id"] else None
    if version:
        item["current_version"] = _row_json(version, ("payload_json", "assumptions_json")) if include_payload else {
            "id": version["id"],
            "version": version["version"],
            "status": version["status"],
            "submitted_at": version["submitted_at"],
        }
        if include_payload:
            item["current_version"]["line_items"] = [_row_json(line) for line in conn.execute("SELECT * FROM domain_network_quote_line_items WHERE quote_version_id = ? ORDER BY created_at", (version["id"],)).fetchall()]
    return item


def _comparison_view(conn, row):
    item = _row_json(row, ("quote_version_ids_json", "quote_snapshots_json", "rules_json"))
    return item


def _award_view(conn, row, include_private=True):
    item = _row_json(row, ("rejected_alternatives_json", "terms_json"))
    contract = conn.execute("SELECT * FROM domain_network_contracts WHERE award_id = ?", (row["id"],)).fetchone()
    item["contract"] = _row_json(contract, ("terms_json",)) if contract else None
    checks = conn.execute("SELECT * FROM domain_network_activation_checks WHERE award_id = ? ORDER BY check_key", (row["id"],)).fetchall()
    item["activation_checks"] = [_row_json(check, ("evidence_json",)) for check in checks]
    if include_private:
        quote = conn.execute("SELECT * FROM domain_network_quotes WHERE id = (SELECT quote_id FROM domain_network_quote_versions WHERE id = ?)", (row["quote_version_id"],)).fetchone()
        item["quote"] = _quote_view(conn, quote, include_payload=True) if quote else None
    return item


def _check_requirements_for_activation(conn, award_id: str):
    rows = conn.execute("SELECT * FROM domain_network_activation_checks WHERE award_id = ? AND blocking = 1", (award_id,)).fetchall()
    failed = [row["check_key"] for row in rows if row["status"] != "passed"]
    return rows, failed


def _seed_contract_sync_records(conn, user, contract_id: str, organization_id: str, terms: dict, created_at: str) -> str:
    """Create the first immutable contract/rate snapshot from award terms."""
    version_id = new_id("network_contract_version")
    conn.execute("INSERT INTO domain_network_contract_versions(id, organization_id, contract_id, version, status, terms_json, effective_from, effective_to, source, created_by, created_at) VALUES (?, ?, ?, 1, 'draft', ?, ?, ?, 'award', ?, ?)", (version_id, organization_id, contract_id, json.dumps(terms if isinstance(terms, dict) else {}), _text(terms, "starts_at") if isinstance(terms, dict) else None, _text(terms, "ends_at") if isinstance(terms, dict) else None, user["id"], created_at))
    raw_rates = terms.get("rate_cards", terms.get("rates", [])) if isinstance(terms, dict) else []
    if isinstance(raw_rates, dict): raw_rates = [raw_rates]
    if not isinstance(raw_rates, list): raw_rates = []
    for index, rate in enumerate(raw_rates):
        if not isinstance(rate, dict): continue
        code = _text(rate, "rate_code", _text(rate, "code", f"rate_{index + 1}", 80), 80)
        conn.execute("INSERT OR IGNORE INTO domain_network_rate_cards(id, organization_id, contract_version_id, rate_code, service_type, vehicle_type, city, unit, amount_paise, currency, effective_from, effective_to, status, terms_json, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)", (new_id("network_rate"), organization_id, version_id, code, _text(rate, "service_type", maximum=80), _text(rate, "vehicle_type", maximum=80), _text(rate, "city", maximum=80), _text(rate, "unit", "trip", 30), _positive_int(rate.get("amount_paise", rate.get("total_paise", 0)), "amount_paise"), _text(rate, "currency", "INR", 8), _text(rate, "effective_from", maximum=40) or None, _text(rate, "effective_to", maximum=40) or None, json.dumps(rate.get("terms") if isinstance(rate.get("terms"), dict) else {}), user["id"], created_at))
    return version_id


def _create_fleet_records(conn, user, award, contract, requirement, version, ip, activation_key=None):
    spec = _json(version["payload_json"], {})
    requirement_ref = requirement["reference"]
    suffix = award["id"][-8:].upper()
    booking_id = new_id("book")
    duty_id = new_id("duty")
    booking_reference = _text(spec, "booking_reference", f"NET-{requirement_ref}-{suffix}", 80)
    now = now_iso()
    pickup = spec.get("pickup") if isinstance(spec.get("pickup"), dict) else {"label": spec.get("pickup_label", "Network origin")}
    dropoff = spec.get("dropoff") if isinstance(spec.get("dropoff"), dict) else {"label": spec.get("dropoff_label", "Network destination")}
    scheduled_at = _text(spec, "scheduled_at", _text(spec, "start_at")) or None
    conn.execute(
        """
        INSERT INTO domain_bookings(
          id, organization_id, booking_reference, status, passenger_name, passenger_phone,
          pickup_json, dropoff_json, scheduled_at, duty_type, notes, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, 'confirmed', ?, ?, ?, ?, ?, 'network', ?, ?, ?, ?)
        """,
        (
            booking_id,
            requirement["organization_id"],
            booking_reference,
            _text(spec, "passenger_name", "Network service order", 160),
            _text(spec, "passenger_phone", maximum=40),
            json.dumps(pickup),
            json.dumps(dropoff),
            scheduled_at,
            f"Axiom Network award {award['id']}",
            user["id"],
            now,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO domain_duties(
          id, organization_id, booking_id, status, reporting_at, created_at, updated_at
        ) VALUES (?, ?, ?, 'draft', ?, ?, ?)
        """,
        (duty_id, requirement["organization_id"], booking_id, scheduled_at, now, now),
    )
    service_order_id = new_id("network_order")
    config = {
        "requirement_reference": requirement_ref,
        "requirement_version": version["version"],
        "vendor_profile_id": award["vendor_profile_id"],
        "network_award_id": award["id"],
        "fleet_booking_id": booking_id,
        "fleet_duty_id": duty_id,
        "spec": spec,
    }
    conn.execute(
        """
        INSERT INTO domain_network_service_orders(
          id, organization_id, award_id, contract_id, requirement_id, vendor_profile_id,
          status, fleet_booking_id, fleet_duty_id, config_json, activated_by, activated_at, idempotency_key
        ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
        """,
        (
            service_order_id,
            requirement["organization_id"],
            award["id"],
            contract["id"],
            requirement["id"],
            award["vendor_profile_id"],
            booking_id,
            duty_id,
            json.dumps(config),
            user["id"],
            now,
            activation_key,
        ),
    )
    vendor_profile = conn.execute("SELECT vendor_organization_id FROM domain_network_vendor_profiles WHERE id = ?", (award["vendor_profile_id"],)).fetchone()
    vendor_organization_id = vendor_profile["vendor_organization_id"] if vendor_profile else ""
    conn.execute("INSERT INTO domain_network_exchange_envelopes(id, organization_id, service_order_id, exchange_type, direction, status, schema_version, external_reference, payload_json, attachments_json, sender_organization_id, recipient_organization_id, provider_reference, created_by, created_at, sent_at) VALUES (?, ?, ?, 'booking', 'outbound', 'sent', 'v1', ?, ?, '[]', ?, ?, ?, ?, ?, ?)", (new_id("network_exchange"), requirement["organization_id"], service_order_id, booking_reference, json.dumps({"fleet_booking_id": booking_id, "booking_reference": booking_reference, "pickup": pickup, "dropoff": dropoff, "scheduled_at": scheduled_at}), requirement["organization_id"], vendor_organization_id, f"mock-exchange-booking-{service_order_id}", user["id"], now, now))
    return service_order_id, booking_id, duty_id


def _ensure_buyer(conn, entity_row, org: str):
    if entity_row["organization_id"] != org:
        raise DomainError(404, "Network record not found", "not_found")


def _access_requirement_for_user(conn, requirement_id: str, user):
    org = _org(user)
    requirement = conn.execute("SELECT * FROM domain_network_requirements WHERE id = ?", (requirement_id,)).fetchone()
    if not requirement:
        raise DomainError(404, "Network requirement not found", "not_found")
    if requirement["organization_id"] == org:
        return requirement, True
    if not _network_enabled(conn, requirement["organization_id"]):
        raise DomainError(404, "Network requirement not found", "not_found")
    candidate = conn.execute(
        """
        SELECT c.* FROM domain_network_candidates c
        JOIN domain_network_match_runs m ON m.id = c.match_run_id
        JOIN domain_network_vendor_profiles v ON v.id = c.vendor_profile_id
        WHERE c.requirement_id = ? AND c.eligible = 1 AND v.vendor_organization_id = ?
        ORDER BY c.created_at DESC LIMIT 1
        """,
        (requirement_id, org),
    ).fetchone()
    if not candidate:
        raise DomainError(404, "Network requirement not found", "not_found")
    return requirement, False


def _access_service_order_for_user(conn, service_order_id: str, user):
    org = _org(user)
    order = conn.execute("SELECT * FROM domain_network_service_orders WHERE id = ?", (service_order_id,)).fetchone()
    if not order:
        raise DomainError(404, "Network service order not found", "not_found")
    if order["organization_id"] == org:
        return order, True
    linked = conn.execute("SELECT 1 FROM domain_network_vendor_profiles WHERE id = ? AND vendor_organization_id = ?", (order["vendor_profile_id"], org)).fetchone()
    if not linked:
        raise DomainError(404, "Network service order not found", "not_found")
    return order, False


def _access_contract_for_user(conn, contract_id: str, user):
    org = _org(user)
    contract = conn.execute("SELECT * FROM domain_network_contracts WHERE id = ?", (contract_id,)).fetchone()
    if not contract:
        raise DomainError(404, "Network contract not found", "not_found")
    if contract["organization_id"] == org:
        return contract, True
    vendor = conn.execute("""
        SELECT v.id FROM domain_network_awards a
        JOIN domain_network_vendor_profiles v ON v.id = a.vendor_profile_id
        WHERE a.id = ? AND v.vendor_organization_id = ?
    """, (contract["award_id"], org)).fetchone()
    if not vendor:
        raise DomainError(404, "Network contract not found", "not_found")
    return contract, False


def _hard_match(spec: dict, profile) -> tuple[bool, list[str], dict]:
    required_cities = _norm_list(spec.get("cities") or spec.get("city") or spec.get("service_cities"))
    required_services = _norm_list(spec.get("service_types") or spec.get("service_type"))
    required_vehicles = _norm_list(spec.get("vehicle_types") or spec.get("vehicle_type"))
    required_capabilities = _norm_list(spec.get("required_capabilities") or spec.get("capabilities"))
    profile_cities = _norm_list(_json(profile["cities_json"], []))
    profile_services = _norm_list(_json(profile["service_types_json"], []))
    profile_vehicles = _norm_list(_json(profile["vehicle_types_json"], []))
    profile_capabilities = _norm_list(_json(profile["capabilities_json"], []))
    capacity = _json(profile["capacity_json"], {})
    compliance = _json(profile["compliance_json"], {})
    reasons = []
    if profile["status"] != "active":
        reasons.append("vendor_profile_not_active")
    if required_cities and profile_cities and not set(required_cities).intersection(profile_cities) and "all" not in profile_cities:
        reasons.append("city_not_served")
    if required_cities and not profile_cities:
        reasons.append("vendor_city_coverage_missing")
    if required_services and not set(required_services).intersection(profile_services) and "all" not in profile_services:
        reasons.append("service_type_not_supported")
    if required_vehicles and not set(required_vehicles).intersection(profile_vehicles) and "all" not in profile_vehicles:
        reasons.append("vehicle_type_not_supported")
    missing_capabilities = sorted(set(required_capabilities) - set(profile_capabilities))
    if missing_capabilities:
        reasons.append("required_capability_missing:" + ",".join(missing_capabilities))
    required_capacity = _positive_int(spec.get("capacity_required") or spec.get("passenger_capacity"), "capacity_required")
    available_capacity = _positive_int(capacity.get("passenger_capacity") or capacity.get("capacity"), "vendor_capacity")
    if required_capacity and available_capacity < required_capacity:
        reasons.append("capacity_insufficient")
    if str(compliance.get("status", "approved")).casefold() in {"blocked", "expired", "suspended", "rejected"}:
        reasons.append("compliance_not_current")
    expiry = str(compliance.get("valid_until") or compliance.get("insurance_valid_until") or "")[:10]
    if expiry and expiry < datetime.now(timezone.utc).date().isoformat():
        reasons.append("compliance_expired")
    components = {
        "city": 30 if required_cities and not any(reason in reasons for reason in ("city_not_served", "vendor_city_coverage_missing")) else (10 if not required_cities else 0),
        "service_type": 25 if required_services and "service_type_not_supported" not in reasons else (10 if not required_services else 0),
        "vehicle_type": 20 if required_vehicles and "vehicle_type_not_supported" not in reasons else (10 if not required_vehicles else 0),
        "capacity": 15 if not required_capacity else (15 if "capacity_insufficient" not in reasons else 0),
        "capabilities": 5 if not missing_capabilities else 0,
        "compliance": 5 if "compliance_not_current" not in reasons and "compliance_expired" not in reasons else 0,
    }
    score = sum(components.values()) if not reasons else 0
    return not reasons, reasons, {"total": score, "components": components, "rules": "hard_filters_v1_then_explainable_score_v1"}


def _quote_version_payload(payload: dict) -> tuple[dict, dict]:
    quote = _payload_json(payload, "quote", payload)
    if not isinstance(quote, dict):
        raise DomainError(400, "quote must be an object", "validation_error")
    total = _positive_int(quote.get("total_paise"), "total_paise")
    if total <= 0:
        raise DomainError(400, "total_paise must be greater than zero", "validation_error")
    line_items = quote.get("line_items")
    if line_items is not None and not isinstance(line_items, list):
        raise DomainError(400, "line_items must be a list", "validation_error")
    assumptions = _payload_json(payload, "assumptions", quote.get("assumptions", {}))
    return quote, assumptions if isinstance(assumptions, dict) else {}


def _status_transition(current: str, target: str, allowed: dict[str, set[str]]) -> None:
    if target == current:
        return
    if target not in allowed.get(current, set()):
        raise DomainError(409, f"Cannot transition from {current} to {target}", "invalid_transition")


def handle_network(conn: sqlite3.Connection, user, method: str, raw_route: str, payload: dict, ip: str):
    """Handle additive /api/network/v1 routes; return None for compatibility routes."""
    parsed = urlsplit(raw_route)
    route = parsed.path.rstrip("/") or "/"
    query = parse_qs(parsed.query)
    if not route.startswith(NETWORK_PREFIX):
        return None

    org = _network_org(user)
    suffix = route[len(NETWORK_PREFIX):] or "/"
    suffix = suffix.rstrip("/") or "/"

    # The module has a visible flag but remains closed/invite-only by design.
    if suffix == "/feature-flag":
        if method == "GET":
            _ensure_enabled(conn, org, user, allow_flag_route=True)
            row = conn.execute("SELECT * FROM domain_network_feature_flags WHERE organization_id = ?", (org,)).fetchone()
            return {"ok": True, "flag": _row_json(row), "mode": "closed_invite_only"}
        if method == "POST":
            enabled = payload.get("enabled")
            if not isinstance(enabled, bool):
                raise DomainError(400, "enabled must be boolean", "validation_error")
            _ensure_enabled(conn, org, user, allow_flag_route=True)
            conn.execute("UPDATE domain_network_feature_flags SET enabled = ?, updated_by = ?, updated_at = ? WHERE organization_id = ?", (1 if enabled else 0, user["id"], now_iso(), org))
            _audit(conn, user, "network.feature_flag.updated", "organization", org, ip, {"enabled": enabled})
            return {"ok": True, "enabled": enabled, "mode": "closed_invite_only"}
        raise DomainError(405, "Method not allowed", "method_not_allowed")

    _ensure_enabled(conn, org, user)

    # Invite-only partner directory. There is intentionally no public vendor
    # registration route; a profile must carry a tenant-owned invite.
    if suffix == "/invites" and method in {"GET", "POST"}:
        if method == "GET":
            rows = conn.execute("SELECT * FROM domain_network_invites WHERE organization_id = ? ORDER BY created_at DESC LIMIT ?", (org, _limit(query))).fetchall()
            return {"ok": True, "items": [_row_json(row) for row in rows]}
        key = _text(payload, "idempotency_key", maximum=160) or None
        if key:
            existing = conn.execute("SELECT * FROM domain_network_invites WHERE organization_id = ? AND idempotency_key = ?", (org, key)).fetchone()
            if existing:
                return {"ok": True, "duplicate": True, "item": _row_json(existing)}
        invite_id = new_id("network_invite")
        vendor_org = _text(payload, "vendor_organization_id", maximum=100) or None
        vendor_name = _text(payload, "vendor_name", maximum=160)
        email = _text(payload, "invite_email", maximum=254).lower()
        if not vendor_org and not email:
            raise DomainError(400, "vendor_organization_id or invite_email is required", "validation_error")
        expires = payload.get("expires_at") or (datetime.now(timezone.utc) + timedelta(days=14)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        now = now_iso()
        conn.execute("INSERT INTO domain_network_invites(id, organization_id, vendor_organization_id, vendor_name, invite_email, status, expires_at, created_by, created_at, idempotency_key) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)", (invite_id, org, vendor_org, vendor_name, email, expires, user["id"], now, key))
        conn.execute("INSERT INTO domain_network_associates(id, organization_id, vendor_organization_id, invite_id, status, buyer_contact, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)", (new_id("network_associate"), org, vendor_org or "", invite_id, email, user["id"], now, now))
        _emit(conn, user, "invite.created", "network_invite", invite_id, ip, {"vendor_organization_id": vendor_org, "invite_email": email})
        return {"ok": True, "item": _row_json(conn.execute("SELECT * FROM domain_network_invites WHERE id = ?", (invite_id,)).fetchone())}

    if suffix == "/partner-directory" and method == "GET":
        term = (_text(query, "q", maximum=120) or "").casefold()
        status_filter = _text(query, "status", maximum=30) or "verified"
        sql = "SELECT * FROM domain_network_partner_directory WHERE organization_id = ?"
        args = [org]
        if status_filter != "all":
            sql += " AND verification_status = ?"; args.append(status_filter)
        sql += " ORDER BY display_name COLLATE NOCASE LIMIT ?"; args.append(_limit(query))
        rows = conn.execute(sql, tuple(args)).fetchall()
        items = []
        for row in rows:
            item = _row_json(row, ("search_document_json",))
            if term and term not in (item.get("display_name") or "").casefold() and term not in json.dumps(item.get("search_document_json", {})).casefold():
                continue
            profile = conn.execute("SELECT * FROM domain_network_vendor_profiles WHERE id = ?", (row["vendor_profile_id"],)).fetchone()
            item["profile"] = _profile_view(profile) if profile else None
            items.append(item)
        return {"ok": True, "items": items, "count": len(items), "mode": "verified_invite_only"}

    if suffix == "/associates" and method == "GET":
        rows = conn.execute("SELECT * FROM domain_network_associates WHERE organization_id = ? OR vendor_organization_id = ? ORDER BY created_at DESC LIMIT ?", (org, org, _limit(query))).fetchall()
        return {"ok": True, "items": [_row_json(row, ("metadata_json",)) for row in rows]}

    associate_action = re.fullmatch(r"/associates/([^/]+)/(accept|reject|revoke)", suffix)
    if associate_action and method == "POST":
        associate = conn.execute("SELECT * FROM domain_network_associates WHERE id = ? AND (organization_id = ? OR vendor_organization_id = ?)", (associate_action.group(1), org, org)).fetchone()
        if not associate: raise DomainError(404, "Network associate not found", "not_found")
        action = associate_action.group(2)
        if action == "revoke" and associate["organization_id"] != org: raise DomainError(403, "Only the buyer tenant can revoke an associate", "role_forbidden")
        if associate["status"] != "pending" and action != "revoke": raise DomainError(409, "Only pending associates can change state", "invalid_transition")
        target = {"accept": "accepted", "reject": "rejected", "revoke": "revoked"}[action]
        now = now_iso()
        conn.execute("UPDATE domain_network_associates SET status = ?, accepted_by = ?, accepted_at = ?, rejected_at = ?, revoked_at = ?, acceptance_note = ?, updated_at = ? WHERE id = ?", (target, user["id"] if target == "accepted" else associate["accepted_by"], now if target == "accepted" else associate["accepted_at"], now if target == "rejected" else associate["rejected_at"], now if target == "revoked" else associate["revoked_at"], _text(payload, "acceptance_note", maximum=500), now, associate["id"]))
        conn.execute("UPDATE domain_network_invites SET status = ?, accepted_at = ?, revoked_at = ? WHERE id = ?", (target, now if target == "accepted" else None, now if target == "revoked" else None, associate["invite_id"]))
        _emit(conn, user, f"associate.{action}ed" if action != "revoke" else "associate.revoked", "network_associate", associate["id"], ip, {"invite_id": associate["invite_id"], "status": target}, organization_id=associate["organization_id"])
        return {"ok": True, "item": _row_json(conn.execute("SELECT * FROM domain_network_associates WHERE id = ?", (associate["id"],)).fetchone(), ("metadata_json",))}

    invite_match = re.fullmatch(r"/invites/([^/]+)/(revoke|accept|reject)", suffix)
    if invite_match and method == "POST":
        invite_row = conn.execute("SELECT * FROM domain_network_invites WHERE id = ? AND (organization_id = ? OR vendor_organization_id = ?)", (invite_match.group(1), org, org)).fetchone()
        if not invite_row: raise DomainError(404, "Network invite not found", "not_found")
        action = invite_match.group(2)
        if action == "revoke" and invite_row["organization_id"] != org: raise DomainError(403, "Only the buyer tenant can revoke an invite", "role_forbidden")
        if invite_row["status"] != "pending": raise DomainError(409, "Only pending invites can change state", "invalid_transition")
        associate = conn.execute("SELECT * FROM domain_network_associates WHERE invite_id = ?", (invite_row["id"],)).fetchone()
        target = {"accept": "accepted", "reject": "rejected", "revoke": "revoked"}[action]
        now = now_iso()
        conn.execute("UPDATE domain_network_invites SET status = ?, accepted_at = ?, revoked_at = ? WHERE id = ?", (target, now if target == "accepted" else None, now if target == "revoked" else None, invite_row["id"]))
        if associate:
            conn.execute("UPDATE domain_network_associates SET status = ?, accepted_by = ?, accepted_at = ?, rejected_at = ?, revoked_at = ?, acceptance_note = ?, updated_at = ? WHERE id = ?", (target, user["id"] if target == "accepted" else associate["accepted_by"], now if target == "accepted" else associate["accepted_at"], now if target == "rejected" else associate["rejected_at"], now if target == "revoked" else associate["revoked_at"], _text(payload, "acceptance_note", maximum=500), now, associate["id"]))
        _emit(conn, user, f"invite.{action}ed" if action != "revoke" else "invite.revoked", "network_invite", invite_row["id"], ip, {"status": target}, organization_id=invite_row["organization_id"])
        return {"ok": True, "item": _row_json(conn.execute("SELECT * FROM domain_network_invites WHERE id = ?", (invite_row["id"],)).fetchone())}

    if suffix == "/vendor-profiles" and method in {"GET", "POST"}:
        if method == "GET":
            rows = conn.execute("SELECT * FROM domain_network_vendor_profiles WHERE organization_id = ? OR vendor_organization_id = ? ORDER BY vendor_name", (org, org)).fetchall()
            return {"ok": True, "items": [_profile_view(row) for row in rows]}
        invite_id = _text(payload, "invite_id", maximum=100)
        invite = _owned(conn, "domain_network_invites", invite_id, org, "Network invite not found")
        if invite["status"] not in {"pending", "accepted"}:
            raise DomainError(409, "Invite is not available for a vendor profile", "invite_required")
        vendor_org = _text(payload, "vendor_organization_id", maximum=100) or invite["vendor_organization_id"]
        vendor_name = _text(payload, "vendor_name", maximum=160) or invite["vendor_name"]
        if not vendor_org or not vendor_name:
            raise DomainError(400, "vendor_organization_id and vendor_name are required", "validation_error")
        profile_id = new_id("network_vendor")
        now = now_iso()
        conn.execute(
            """
            INSERT INTO domain_network_vendor_profiles(
              id, organization_id, vendor_organization_id, vendor_name, status,
              cities_json, service_types_json, vehicle_types_json, capabilities_json,
              capacity_json, compliance_json, metadata_json, invite_id, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                org,
                vendor_org,
                vendor_name,
                _text(payload, "status", "active", 20) or "active",
                json.dumps(_json_list(payload.get("cities"))),
                json.dumps(_json_list(payload.get("service_types"))),
                json.dumps(_json_list(payload.get("vehicle_types"))),
                json.dumps(_json_list(payload.get("capabilities"))),
                json.dumps(_payload_json(payload, "capacity", {})),
                json.dumps(_payload_json(payload, "compliance", {"status": "approved"})),
                json.dumps(_payload_json(payload, "metadata", {})),
                invite_id,
                user["id"],
                now,
                now,
            ),
        )
        conn.execute("UPDATE domain_network_invites SET status = 'accepted', accepted_at = COALESCE(accepted_at, ?) WHERE id = ?", (now, invite_id))
        conn.execute("UPDATE domain_network_associates SET status = 'accepted', vendor_profile_id = ?, accepted_by = COALESCE(accepted_by, ?), accepted_at = COALESCE(accepted_at, ?), updated_at = ? WHERE invite_id = ?", (profile_id, user["id"], now, now, invite_id))
        conn.execute("INSERT INTO domain_network_partner_directory(id, organization_id, vendor_organization_id, vendor_profile_id, display_name, verification_status, verified_at, discovered_via, search_document_json, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'verified', ?, 'invite', ?, ?, ?, ?) ON CONFLICT(vendor_profile_id) DO UPDATE SET display_name=excluded.display_name, verification_status='verified', verified_at=COALESCE(domain_network_partner_directory.verified_at, excluded.verified_at), search_document_json=excluded.search_document_json, updated_at=excluded.updated_at", (new_id("network_directory"), org, vendor_org, profile_id, vendor_name, now, json.dumps({"cities": _json_list(payload.get("cities")), "service_types": _json_list(payload.get("service_types")), "vehicle_types": _json_list(payload.get("vehicle_types")), "capabilities": _json_list(payload.get("capabilities"))}), user["id"], now, now))
        _emit(conn, user, "vendor_profile.created", "vendor_profile", profile_id, ip, {"invite_id": invite_id, "vendor_organization_id": vendor_org})
        return {"ok": True, "item": _profile_view(conn.execute("SELECT * FROM domain_network_vendor_profiles WHERE id = ?", (profile_id,)).fetchone())}

    program_match = re.fullmatch(r"/programs(?:/([^/]+)(?:/(activate|pause))?)?", suffix)
    if program_match:
        program_id, action = program_match.groups()
        if not program_id and method in {"GET", "POST"}:
            if method == "GET":
                rows = conn.execute("SELECT * FROM domain_network_programs WHERE organization_id = ? ORDER BY created_at DESC LIMIT ?", (org, _limit(query))).fetchall()
                return {"ok": True, "items": [_program_view(conn, row) for row in rows]}
            code = _text(payload, "code", maximum=80)
            name = _text(payload, "name", maximum=160)
            if not code or not name:
                raise DomainError(400, "code and name are required", "validation_error")
            program_id = new_id("network_program")
            now = now_iso()
            status = _text(payload, "status", "active", 20) or "active"
            if status not in {"draft", "active"}:
                raise DomainError(400, "Program status must be draft or active", "validation_error")
            conn.execute("INSERT INTO domain_network_programs(id, organization_id, code, name, description, status, settings_json, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (program_id, org, code, name, _text(payload, "description", maximum=500), status, json.dumps(_payload_json(payload, "settings", {})), user["id"], now, now))
            _emit(conn, user, "program.created", "program", program_id, ip, {"code": code, "status": status})
            return {"ok": True, "item": _program_view(conn, conn.execute("SELECT * FROM domain_network_programs WHERE id = ?", (program_id,)).fetchone())}
        if program_id and action and method == "POST":
            program = _owned(conn, "domain_network_programs", program_id, org, "Network program not found")
            target = "active" if action == "activate" else "paused"
            _status_transition(program["status"], target, {"draft": {"active"}, "active": {"paused"}, "paused": {"active"}})
            conn.execute("UPDATE domain_network_programs SET status = ?, updated_at = ? WHERE id = ?", (target, now_iso(), program_id))
            _emit(conn, user, f"program.{action}d", "program", program_id, ip, {"status": target})
            return {"ok": True, "item": _program_view(conn, conn.execute("SELECT * FROM domain_network_programs WHERE id = ?", (program_id,)).fetchone())}
        if program_id and not action and method == "GET":
            return {"ok": True, "item": _program_view(conn, _owned(conn, "domain_network_programs", program_id, org, "Network program not found"))}

    requirements_collection = re.fullmatch(r"/programs/([^/]+)/requirements", suffix)
    if requirements_collection:
        program_id = requirements_collection.group(1)
        program = _owned(conn, "domain_network_programs", program_id, org, "Network program not found")
        if method == "GET":
            rows = conn.execute("SELECT * FROM domain_network_requirements WHERE organization_id = ? AND program_id = ? ORDER BY created_at DESC LIMIT ?", (org, program_id, _limit(query))).fetchall()
            return {"ok": True, "items": [_requirement_view(conn, row) for row in rows]}
        if method == "POST":
            if program["status"] != "active":
                raise DomainError(409, "Requirements can only be created in an active program", "program_not_active")
            reference = _text(payload, "reference", maximum=100)
            spec = _payload_json(payload, "spec", payload)
            if not reference or not isinstance(spec, dict):
                raise DomainError(400, "reference and spec are required", "validation_error")
            requirement_id = new_id("network_req")
            version_id = new_id("network_reqv")
            now = now_iso()
            conn.execute("INSERT INTO domain_network_requirements(id, organization_id, program_id, reference, status, current_version, current_version_id, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, 'draft', 1, ?, ?, ?, ?)", (requirement_id, org, program_id, reference, version_id, user["id"], now, now))
            conn.execute("INSERT INTO domain_network_requirement_versions(id, organization_id, requirement_id, version, status, payload_json, change_note, created_by, created_at) VALUES (?, ?, ?, 1, 'draft', ?, ?, ?, ?)", (version_id, org, requirement_id, json.dumps(spec), _text(payload, "change_note", maximum=300), user["id"], now))
            _emit(conn, user, "requirement.created", "requirement", requirement_id, ip, {"program_id": program_id, "version": 1})
            return {"ok": True, "item": _requirement_view(conn, conn.execute("SELECT * FROM domain_network_requirements WHERE id = ?", (requirement_id,)).fetchone())}

    if suffix == "/requirements" and method == "GET":
        rows = conn.execute(
            """
            SELECT DISTINCT r.*, v.id AS network_vendor_profile_id
            FROM domain_network_requirements r
            LEFT JOIN domain_network_candidates c ON c.requirement_id = r.id AND c.eligible = 1
            LEFT JOIN domain_network_vendor_profiles v ON v.id = c.vendor_profile_id
            WHERE r.organization_id = ? OR v.vendor_organization_id = ?
            ORDER BY r.updated_at DESC LIMIT ?
            """,
            (org, org, _limit(query)),
        ).fetchall()
        items = []
        for row in rows:
            is_buyer = row["organization_id"] == org
            item = _requirement_view(conn, row, include_payload=is_buyer)
            if not is_buyer:
                item["network_vendor_profile_id"] = row["network_vendor_profile_id"]
            items.append(item)
        return {"ok": True, "items": items}

    requirement_match = re.fullmatch(r"/requirements/([^/]+)(?:/(.*))?", suffix)
    if requirement_match:
        requirement_id, action_path = requirement_match.groups()
        action_path = action_path or ""
        requirement, is_buyer = _access_requirement_for_user(conn, requirement_id, user)
        if action_path == "" and method == "GET":
            return {"ok": True, "item": _requirement_view(conn, requirement, include_payload=is_buyer)}
        if action_path == "versions" and method == "POST":
            if not is_buyer:
                raise DomainError(403, "Only the buyer tenant can version a requirement", "role_forbidden")
            spec = _payload_json(payload, "spec", payload)
            if not isinstance(spec, dict):
                raise DomainError(400, "spec must be an object", "validation_error")
            latest = _requirement_version(conn, requirement_id)
            version = int(latest["version"] if latest else 0) + 1
            version_id = new_id("network_reqv")
            conn.execute("INSERT INTO domain_network_requirement_versions(id, organization_id, requirement_id, version, status, payload_json, change_note, created_by, created_at) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?)", (version_id, org, requirement_id, version, json.dumps(spec), _text(payload, "change_note", maximum=300), user["id"], now_iso()))
            conn.execute("UPDATE domain_network_requirements SET status = 'draft', current_version = ?, current_version_id = ?, updated_at = ? WHERE id = ?", (version, version_id, now_iso(), requirement_id))
            _emit(conn, user, "requirement.version_created", "requirement", requirement_id, ip, {"version": version})
            return {"ok": True, "item": _requirement_view(conn, conn.execute("SELECT * FROM domain_network_requirements WHERE id = ?", (requirement_id,)).fetchone())}
        publish_match = re.fullmatch(r"versions/(\d+)/publish", action_path)
        if publish_match and method == "POST":
            if not is_buyer:
                raise DomainError(403, "Only the buyer tenant can publish a requirement", "role_forbidden")
            version_number = int(publish_match.group(1))
            version = _requirement_version(conn, requirement_id, version_number)
            if not version:
                raise DomainError(404, "Requirement version not found", "not_found")
            conn.execute("UPDATE domain_network_requirement_versions SET status = 'superseded' WHERE requirement_id = ? AND status = 'published'", (requirement_id,))
            conn.execute("UPDATE domain_network_requirement_versions SET status = 'published', published_at = ? WHERE id = ?", (now_iso(), version["id"]))
            conn.execute("UPDATE domain_network_requirements SET status = 'published', current_version = ?, current_version_id = ?, updated_at = ? WHERE id = ?", (version_number, version["id"], now_iso(), requirement_id))
            _emit(conn, user, "requirement.published", "requirement", requirement_id, ip, {"version": version_number})
            return {"ok": True, "item": _requirement_view(conn, conn.execute("SELECT * FROM domain_network_requirements WHERE id = ?", (requirement_id,)).fetchone())}
        if action_path == "match" and method == "POST":
            if not is_buyer:
                raise DomainError(403, "Only the buyer tenant can run matching", "role_forbidden")
            key = _text(payload, "idempotency_key", maximum=160) or None
            if key:
                existing = conn.execute("SELECT * FROM domain_network_match_runs WHERE organization_id = ? AND idempotency_key = ?", (org, key)).fetchone()
                if existing:
                    candidates = conn.execute("SELECT * FROM domain_network_candidates WHERE match_run_id = ? ORDER BY eligible DESC, id", (existing["id"],)).fetchall()
                    return {"ok": True, "duplicate": True, "match": _row_json(existing, ("rules_json",)), "candidates": [_candidate_view(conn, row) for row in candidates]}
            if requirement["status"] not in {"published", "matched", "quoted", "award_pending", "awarded", "activated"}:
                raise DomainError(409, "Publish a requirement version before matching", "requirement_not_published")
            version = _requirement_version(conn, requirement_id, requirement["current_version"])
            if not version or version["status"] not in {"published", "superseded"}:
                raise DomainError(409, "The current requirement version is not published", "requirement_not_published")
            match_id = new_id("network_match")
            spec = _json(version["payload_json"], {})
            rules = {"version": "hard_filters_v1_then_explainable_score_v1", "order": ["status", "city", "service_type", "vehicle_type", "capacity", "capabilities", "compliance"]}
            conn.execute("INSERT INTO domain_network_match_runs(id, organization_id, requirement_id, requirement_version_id, rules_version, status, rules_json, created_by, created_at, completed_at, idempotency_key) VALUES (?, ?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?)", (match_id, org, requirement_id, version["id"], rules["version"], json.dumps(rules), user["id"], now_iso(), now_iso(), key))
            profiles = conn.execute("SELECT * FROM domain_network_vendor_profiles WHERE organization_id = ? ORDER BY vendor_name, id", (org,)).fetchall()
            for profile in profiles:
                eligible, reasons, score = _hard_match(spec, profile)
                conn.execute("INSERT INTO domain_network_candidates(id, organization_id, match_run_id, requirement_id, vendor_profile_id, eligible, exclusion_reasons_json, score_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (new_id("network_candidate"), org, match_id, requirement_id, profile["id"], 1 if eligible else 0, json.dumps(reasons), json.dumps(score), now_iso()))
            conn.execute("UPDATE domain_network_requirements SET status = 'matched', updated_at = ? WHERE id = ?", (now_iso(), requirement_id))
            _emit(conn, user, "matching.completed", "requirement", requirement_id, ip, {"match_run_id": match_id, "requirement_version": version["version"]})
            candidates = conn.execute("SELECT * FROM domain_network_candidates WHERE match_run_id = ? ORDER BY eligible DESC, json_extract(score_json, '$.total') DESC, id", (match_id,)).fetchall()
            return {"ok": True, "match": _row_json(conn.execute("SELECT * FROM domain_network_match_runs WHERE id = ?", (match_id,)).fetchone(), ("rules_json",)), "candidates": [_candidate_view(conn, row) for row in candidates]}
        if action_path == "quotes" and method in {"GET", "POST"}:
            if method == "GET":
                if is_buyer:
                    quotes = conn.execute("SELECT * FROM domain_network_quotes WHERE organization_id = ? AND requirement_id = ? ORDER BY updated_at DESC", (org, requirement_id)).fetchall()
                    return {"ok": True, "items": [_quote_view(conn, row, include_payload=False) for row in quotes], "confidential": True}
                quotes = conn.execute("SELECT * FROM domain_network_quotes WHERE organization_id = ? AND requirement_id = ? AND bidder_organization_id = ? ORDER BY updated_at DESC", (requirement["organization_id"], requirement_id, org)).fetchall()
                return {"ok": True, "items": [_quote_view(conn, row, include_payload=True) for row in quotes], "confidential": True}
            vendor_profile_id = _text(payload, "vendor_profile_id", maximum=100)
            profile = conn.execute("SELECT * FROM domain_network_vendor_profiles WHERE id = ?", (vendor_profile_id,)).fetchone()
            if not profile or profile["organization_id"] != requirement["organization_id"]:
                raise DomainError(404, "Network vendor profile not found", "not_found")
            if not is_buyer and profile["vendor_organization_id"] != org:
                raise DomainError(403, "This quote is not assigned to the signed-in vendor organization", "quote_forbidden")
            if is_buyer and profile["vendor_organization_id"] != org:
                raise DomainError(403, "Buyer-created quotes must use an in-tenant vendor profile", "quote_forbidden")
            candidate = _candidate_for(conn, requirement_id, vendor_profile_id)
            if not candidate or not candidate["eligible"]:
                raise DomainError(409, "Only eligible matched vendors may quote", "vendor_not_eligible")
            quote_data, assumptions = _quote_version_payload(payload)
            key = _text(payload, "idempotency_key", maximum=160) or None
            if key:
                existing = conn.execute("SELECT q.*, v.id AS version_id FROM domain_network_quotes q JOIN domain_network_quote_versions v ON v.id = q.current_version_id WHERE q.organization_id = ? AND v.idempotency_key = ?", (requirement["organization_id"], key)).fetchone()
                if existing:
                    return {"ok": True, "duplicate": True, "item": _quote_view(conn, existing, include_payload=True)}
            buyer_org = requirement["organization_id"]
            quote = conn.execute("SELECT * FROM domain_network_quotes WHERE organization_id = ? AND requirement_id = ? AND vendor_profile_id = ?", (buyer_org, requirement_id, vendor_profile_id)).fetchone()
            now = now_iso()
            if quote is None:
                quote_id = new_id("network_quote")
                conn.execute("INSERT INTO domain_network_quotes(id, organization_id, requirement_id, vendor_profile_id, bidder_organization_id, status, current_version, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'submitted', 0, ?, ?, ?)", (quote_id, buyer_org, requirement_id, vendor_profile_id, profile["vendor_organization_id"], user["id"], now, now))
                quote = conn.execute("SELECT * FROM domain_network_quotes WHERE id = ?", (quote_id,)).fetchone()
            version_number = int(quote["current_version"] or 0) + 1
            if quote["current_version_id"]:
                conn.execute("UPDATE domain_network_quote_versions SET status = 'superseded' WHERE id = ?", (quote["current_version_id"],))
            version_id = new_id("network_quotev")
            conn.execute("INSERT INTO domain_network_quote_versions(id, organization_id, quote_id, requirement_id, vendor_profile_id, version, status, payload_json, assumptions_json, submitted_by, submitted_at, idempotency_key) VALUES (?, ?, ?, ?, ?, ?, 'submitted', ?, ?, ?, ?, ?)", (version_id, buyer_org, quote["id"], requirement_id, vendor_profile_id, version_number, json.dumps(quote_data), json.dumps(assumptions), user["id"], now, key))
            line_items = quote_data.get("line_items") if isinstance(quote_data.get("line_items"), list) else []
            for index, line in enumerate(line_items, start=1):
                if not isinstance(line, dict):
                    continue
                code = _text(line, "code", f"line_{index}", 80) or f"line_{index}"
                quantity = float(line.get("quantity") or 1)
                unit_paise = _positive_int(line.get("unit_paise"), "unit_paise")
                amount_paise = _positive_int(line.get("amount_paise"), "amount_paise", int(round(quantity * unit_paise)))
                conn.execute("INSERT OR REPLACE INTO domain_network_quote_line_items(id, organization_id, quote_version_id, line_code, description, unit, quantity, unit_paise, amount_paise, tax_bps, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (new_id("network_line"), buyer_org, version_id, code, _text(line, "description", maximum=200), _text(line, "unit", maximum=40), quantity, unit_paise, amount_paise, _positive_int(line.get("tax_bps"), "tax_bps"), now))
            _record_snapshot(conn, user, "quote", quote["id"], {"version": version_number, "payload": quote_data, "assumptions": assumptions}, "submitted", buyer_org)
            conn.execute("UPDATE domain_network_quotes SET status = 'submitted', current_version = ?, current_version_id = ?, updated_at = ? WHERE id = ?", (version_number, version_id, now, quote["id"]))
            _emit(conn, user, "quote.submitted", "quote", quote["id"], ip, {"requirement_id": requirement_id, "version": version_number, "vendor_profile_id": vendor_profile_id}, buyer_org)
            return {"ok": True, "item": _quote_view(conn, conn.execute("SELECT * FROM domain_network_quotes WHERE id = ?", (quote["id"],)).fetchone(), include_payload=True)}

    comparisons_collection = re.fullmatch(r"/requirements/([^/]+)/comparisons", suffix)
    if comparisons_collection:
        requirement_id = comparisons_collection.group(1)
        requirement = _owned(conn, "domain_network_requirements", requirement_id, org, "Network requirement not found")
        if method == "GET":
            rows = conn.execute("SELECT * FROM domain_network_comparisons WHERE organization_id = ? AND requirement_id = ? ORDER BY created_at DESC", (org, requirement_id)).fetchall()
            return {"ok": True, "items": [_comparison_view(conn, row) for row in rows]}
        if method == "POST":
            key = _text(payload, "idempotency_key", maximum=160) or None
            if key:
                existing = conn.execute("SELECT * FROM domain_network_comparisons WHERE organization_id = ? AND idempotency_key = ?", (org, key)).fetchone()
                if existing:
                    return {"ok": True, "duplicate": True, "item": _comparison_view(conn, existing)}
            selected_ids = payload.get("quote_version_ids")
            if selected_ids is not None and not isinstance(selected_ids, list):
                raise DomainError(400, "quote_version_ids must be a list", "validation_error")
            query_sql = """
                SELECT v.*, q.status AS quote_status, q.current_version_id, q.vendor_profile_id AS quote_vendor_profile_id
                FROM domain_network_quote_versions v
                JOIN domain_network_quotes q ON q.id = v.quote_id
                WHERE v.organization_id = ? AND v.requirement_id = ? AND v.status = 'submitted'
            """
            params = [org, requirement_id]
            if selected_ids:
                placeholders = ",".join("?" for _ in selected_ids)
                query_sql += f" AND v.id IN ({placeholders})"
                params.extend(selected_ids)
            versions = conn.execute(query_sql, params).fetchall()
            if not versions:
                raise DomainError(409, "At least one submitted quote is required for comparison", "quotes_required")
            snapshots = []
            for version in versions:
                profile = conn.execute("SELECT id, vendor_name, vendor_organization_id FROM domain_network_vendor_profiles WHERE id = ?", (version["vendor_profile_id"],)).fetchone()
                quote_payload = _json(version["payload_json"], {})
                snapshots.append({"quote_version_id": version["id"], "version": version["version"], "vendor_profile": _serialize(profile), "quote": quote_payload, "assumptions": _json(version["assumptions_json"], {})})
            rules = {"version": "comparison_v1", "sort": ["total_paise_ascending", "match_score_descending", "vendor_name_ascending"]}
            comparison_id = new_id("network_compare")
            match = _current_match(conn, requirement_id, org)
            conn.execute("INSERT INTO domain_network_comparisons(id, organization_id, requirement_id, match_run_id, status, quote_version_ids_json, quote_snapshots_json, rules_json, created_by, created_at, idempotency_key) VALUES (?, ?, ?, ?, 'ready', ?, ?, ?, ?, ?, ?)", (comparison_id, org, requirement_id, match["id"] if match else None, json.dumps([version["id"] for version in versions]), json.dumps(snapshots), json.dumps(rules), user["id"], now_iso(), key))
            conn.execute("UPDATE domain_network_requirements SET status = 'quoted', updated_at = ? WHERE id = ?", (now_iso(), requirement_id))
            _emit(conn, user, "comparison.created", "comparison", comparison_id, ip, {"requirement_id": requirement_id, "quote_count": len(versions)})
            return {"ok": True, "item": _comparison_view(conn, conn.execute("SELECT * FROM domain_network_comparisons WHERE id = ?", (comparison_id,)).fetchone())}

    comparison_match = re.fullmatch(r"/comparisons/([^/]+)", suffix)
    if comparison_match and method == "GET":
        comparison = _owned(conn, "domain_network_comparisons", comparison_match.group(1), org, "Network comparison not found")
        return {"ok": True, "item": _comparison_view(conn, comparison)}

    awards_collection = re.fullmatch(r"/requirements/([^/]+)/awards", suffix)
    if awards_collection:
        requirement_id = awards_collection.group(1)
        requirement = _owned(conn, "domain_network_requirements", requirement_id, org, "Network requirement not found")
        if method == "GET":
            rows = conn.execute("SELECT * FROM domain_network_awards WHERE organization_id = ? AND requirement_id = ? ORDER BY created_at DESC", (org, requirement_id)).fetchall()
            return {"ok": True, "items": [_award_view(conn, row) for row in rows]}
        if method == "POST":
            comparison_id = _text(payload, "comparison_id", maximum=100)
            quote_version_id = _text(payload, "quote_version_id", maximum=100)
            comparison = _owned(conn, "domain_network_comparisons", comparison_id, org, "Network comparison not found")
            if comparison["requirement_id"] != requirement_id:
                raise DomainError(409, "Comparison does not belong to this requirement", "invalid_reference")
            quote_ids = _json(comparison["quote_version_ids_json"], [])
            if quote_version_id not in quote_ids:
                raise DomainError(409, "The selected quote is not in the comparison snapshot", "quote_not_in_comparison")
            version = conn.execute("SELECT * FROM domain_network_quote_versions WHERE id = ? AND requirement_id = ?", (quote_version_id, requirement_id)).fetchone()
            if not version:
                raise DomainError(404, "Quote version not found", "not_found")
            key = _text(payload, "idempotency_key", maximum=160) or None
            if key:
                existing = conn.execute("SELECT * FROM domain_network_awards WHERE organization_id = ? AND idempotency_key = ?", (org, key)).fetchone()
                if existing:
                    return {"ok": True, "duplicate": True, "item": _award_view(conn, existing)}
            award_id = new_id("network_award")
            conn.execute("INSERT INTO domain_network_awards(id, organization_id, requirement_id, comparison_id, quote_version_id, vendor_profile_id, status, award_reason, rejected_alternatives_json, terms_json, created_by, created_at, idempotency_key) VALUES (?, ?, ?, ?, ?, ?, 'pending_approval', ?, ?, ?, ?, ?, ?)", (award_id, org, requirement_id, comparison_id, quote_version_id, version["vendor_profile_id"], _text(payload, "award_reason", maximum=500), json.dumps([item for item in quote_ids if item != quote_version_id]), json.dumps(_payload_json(payload, "terms", {})), user["id"], now_iso(), key))
            conn.execute("UPDATE domain_network_requirements SET status = 'award_pending', updated_at = ? WHERE id = ?", (now_iso(), requirement_id))
            _record_snapshot(conn, user, "award", award_id, {"status": "pending_approval", "comparison_id": comparison_id, "quote_version_id": quote_version_id, "terms": _payload_json(payload, "terms", {})}, "created")
            _emit(conn, user, "award.created", "award", award_id, ip, {"requirement_id": requirement_id, "quote_version_id": quote_version_id, "status": "pending_approval"})
            return {"ok": True, "item": _award_view(conn, conn.execute("SELECT * FROM domain_network_awards WHERE id = ?", (award_id,)).fetchone())}

    award_match = re.fullmatch(r"/awards/([^/]+)(?:/(approve|activate|checks(?:/([^/]+))?))?", suffix)
    if award_match:
        award_id, action, check_key = award_match.groups()
        award = _owned(conn, "domain_network_awards", award_id, org, "Network award not found")
        if action is None and method == "GET":
            return {"ok": True, "item": _award_view(conn, award)}
        if action == "approve" and method == "POST":
            if award["status"] != "pending_approval":
                raise DomainError(409, "Only pending awards can be approved", "invalid_transition")
            now = now_iso()
            terms = _payload_json(payload, "terms", _json(award["terms_json"], {}))
            conn.execute("UPDATE domain_network_awards SET status = 'approved', terms_json = ?, approved_by = ?, approved_at = ? WHERE id = ?", (json.dumps(terms), user["id"], now, award_id))
            contract_id = new_id("network_contract")
            start_at = _text(payload, "starts_at", maximum=80) or None
            end_at = _text(payload, "ends_at", maximum=80) or None
            conn.execute("INSERT INTO domain_network_contracts(id, organization_id, award_id, status, starts_at, ends_at, terms_json, created_by, created_at, updated_at) VALUES (?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?)", (contract_id, org, award_id, start_at, end_at, json.dumps(terms), user["id"], now, now))
            _seed_contract_sync_records(conn, user, contract_id, org, terms, now)
            slas = terms.get("slas") if isinstance(terms, dict) else []
            if not isinstance(slas, list):
                slas = []
            if not slas:
                slas = [{"metric": "on_time_start_pct", "target_value": 95, "unit": "percent", "severity": "critical"}, {"metric": "proof_completion_pct", "target_value": 100, "unit": "percent", "severity": "critical"}]
            for sla in slas:
                if not isinstance(sla, dict) or not _text(sla, "metric", maximum=100):
                    continue
                sla_id = new_id("network_sla")
                metric = _text(sla, "metric", maximum=100)
                target_value = float(sla.get("target_value") or 0)
                unit = _text(sla, "unit", maximum=30)
                severity = _text(sla, "severity", "warning", 20)
                conn.execute("INSERT OR IGNORE INTO domain_network_slas(id, organization_id, contract_id, metric, target_value, unit, severity, evidence_required, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)", (sla_id, org, contract_id, metric, target_value, unit, severity, now))
                _record_snapshot(conn, user, "sla", sla_id, {"contract_id": contract_id, "metric": metric, "target_value": target_value, "unit": unit, "severity": severity}, "created")
            checks = [("contract_signed", 1), ("vendor_compliance", 1), ("capacity_confirmed", 1), ("dispatch_ready", 1)]
            for key, blocking in checks:
                conn.execute("INSERT OR IGNORE INTO domain_network_activation_checks(id, organization_id, award_id, check_key, status, blocking) VALUES (?, ?, ?, ?, 'pending', ?)", (new_id("network_check"), org, award_id, key, blocking))
            _record_snapshot(conn, user, "award", award_id, {"status": "approved", "contract_id": contract_id, "terms": terms}, "approved")
            _record_snapshot(conn, user, "contract", contract_id, {"status": "draft", "award_id": award_id, "terms": terms}, "created")
            conn.execute("UPDATE domain_network_quote_versions SET status = 'awarded' WHERE id = ?", (award["quote_version_id"],))
            conn.execute("UPDATE domain_network_quotes SET status = 'awarded', updated_at = ? WHERE current_version_id = ?", (now, award["quote_version_id"]))
            conn.execute("UPDATE domain_network_requirements SET status = 'awarded', updated_at = ? WHERE id = ?", (now, award["requirement_id"]))
            _emit(conn, user, "award.approved", "award", award_id, ip, {"contract_id": contract_id})
            return {"ok": True, "item": _award_view(conn, conn.execute("SELECT * FROM domain_network_awards WHERE id = ?", (award_id,)).fetchone())}
        if action and action.startswith("checks") and not check_key and method == "GET":
            checks = conn.execute("SELECT * FROM domain_network_activation_checks WHERE award_id = ? ORDER BY check_key", (award_id,)).fetchall()
            return {"ok": True, "items": [_row_json(row, ("evidence_json",)) for row in checks]}
        if action and action.startswith("checks") and check_key and method == "POST":
            if check_key not in {"contract_signed", "vendor_compliance", "capacity_confirmed", "dispatch_ready"}:
                raise DomainError(400, "Unknown activation check", "validation_error")
            target = _text(payload, "status", maximum=20)
            if target not in {"pending", "passed", "failed", "waived"}:
                raise DomainError(400, "Invalid activation check status", "validation_error")
            evidence = _payload_json(payload, "evidence", {})
            if target == "passed" and not evidence:
                raise DomainError(400, "Evidence is required when passing an activation check", "evidence_required")
            row = conn.execute("SELECT * FROM domain_network_activation_checks WHERE award_id = ? AND check_key = ?", (award_id, check_key)).fetchone()
            if not row:
                raise DomainError(404, "Activation check not found", "not_found")
            conn.execute("UPDATE domain_network_activation_checks SET status = ?, evidence_json = ?, checked_by = ?, checked_at = ? WHERE id = ?", (target, json.dumps(evidence), user["id"], now_iso(), row["id"]))
            _record_snapshot(conn, user, "activation_check", row["id"], {"award_id": award_id, "check_key": check_key, "status": target, "evidence": evidence}, target)
            _emit(conn, user, f"activation_check.{target}", "award", award_id, ip, {"check_key": check_key, "evidence": evidence})
            return {"ok": True, "item": _row_json(conn.execute("SELECT * FROM domain_network_activation_checks WHERE id = ?", (row["id"],)).fetchone(), ("evidence_json",))}
        if action == "activate" and method == "POST":
            if award["status"] != "approved":
                raise DomainError(409, "Only approved awards can activate Fleet service orders", "award_not_approved")
            existing = conn.execute("SELECT * FROM domain_network_service_orders WHERE award_id = ?", (award_id,)).fetchone()
            if existing:
                return {"ok": True, "duplicate": True, "item": _row_json(existing, ("config_json",))}
            _, failed = _check_requirements_for_activation(conn, award_id)
            if failed:
                raise DomainError(409, "Activation is blocked until all required checks pass: " + ", ".join(failed), "activation_blocked")
            contract = conn.execute("SELECT * FROM domain_network_contracts WHERE award_id = ?", (award_id,)).fetchone()
            if not contract or contract["status"] not in {"signed", "active"}:
                raise DomainError(409, "The Network contract must be signed before activation", "contract_not_signed")
            requirement = _owned(conn, "domain_network_requirements", award["requirement_id"], org)
            version = _requirement_version(conn, requirement["id"], requirement["current_version"])
            activation_key = _text(payload, "idempotency_key", maximum=160) or None
            service_order_id, booking_id, duty_id = _create_fleet_records(conn, user, award, contract, requirement, version, ip, activation_key)
            _record_snapshot(conn, user, "service_order", service_order_id, {"award_id": award_id, "contract_id": contract["id"], "fleet_booking_id": booking_id, "fleet_duty_id": duty_id, "status": "active"}, "activated")
            conn.execute("UPDATE domain_network_contracts SET status = 'active', updated_at = ? WHERE id = ?", (now_iso(), contract["id"]))
            conn.execute("UPDATE domain_network_requirements SET status = 'activated', updated_at = ? WHERE id = ?", (now_iso(), requirement["id"]))
            _emit(conn, user, "service_order.activated", "service_order", service_order_id, ip, {"award_id": award_id, "fleet_booking_id": booking_id, "fleet_duty_id": duty_id})
            item = conn.execute("SELECT * FROM domain_network_service_orders WHERE id = ?", (service_order_id,)).fetchone()
            return {"ok": True, "item": _row_json(item, ("config_json",)), "fleet": {"booking_id": booking_id, "duty_id": duty_id}}

    contract_collection = re.fullmatch(r"/contracts(?:/([^/]+)(?:/(versions|sync))?)?", suffix)
    if contract_collection:
        contract_id, contract_action = contract_collection.groups()
        if not contract_id and method == "GET":
            rows = conn.execute("SELECT * FROM domain_network_contracts WHERE organization_id = ? ORDER BY created_at DESC LIMIT ?", (org, _limit(query))).fetchall()
            return {"ok": True, "items": [_row_json(row, ("terms_json",)) for row in rows]}
        if contract_id:
            contract, is_buyer = _access_contract_for_user(conn, contract_id, user)
            if not contract_action and method == "GET":
                item = _row_json(contract, ("terms_json",))
                versions = conn.execute("SELECT * FROM domain_network_contract_versions WHERE contract_id = ? ORDER BY version DESC", (contract_id,)).fetchall()
                item["versions"] = [_row_json(row, ("terms_json",)) for row in versions]
                if versions:
                    item["rate_cards"] = [_row_json(row, ("terms_json",)) for row in conn.execute("SELECT * FROM domain_network_rate_cards WHERE contract_version_id = ? ORDER BY rate_code", (versions[0]["id"],)).fetchall()]
                return {"ok": True, "item": item}
            if contract_action == "versions" and method == "GET":
                rows = conn.execute("SELECT * FROM domain_network_contract_versions WHERE contract_id = ? ORDER BY version DESC", (contract_id,)).fetchall()
                return {"ok": True, "items": [_row_json(row, ("terms_json",)) for row in rows]}
            if contract_action == "versions" and method == "POST":
                target_action = _text(payload, "action", maximum=20) or "publish"
                if target_action == "accept":
                    version_id = _text(payload, "version_id", maximum=100)
                    version = conn.execute("SELECT * FROM domain_network_contract_versions WHERE id = ? AND contract_id = ?", (version_id, contract_id)).fetchone()
                    if not version: raise DomainError(404, "Contract version not found", "not_found")
                    if is_buyer: raise DomainError(403, "The vendor organization accepts a contract version", "role_forbidden")
                    now = now_iso(); conn.execute("UPDATE domain_network_contract_versions SET status = 'accepted', accepted_by = ?, accepted_at = ? WHERE id = ?", (user["id"], now, version_id))
                    conn.execute("UPDATE domain_network_contract_syncs SET status = 'acknowledged', acknowledged_by = ?, acknowledged_at = ? WHERE contract_version_id = ? AND status IN ('queued','sent')", (user["id"], now, version_id))
                    _emit(conn, user, "contract.version.accepted", "contract", contract_id, ip, {"version_id": version_id, "version": version["version"]}, contract["organization_id"])
                    return {"ok": True, "item": _row_json(conn.execute("SELECT * FROM domain_network_contract_versions WHERE id = ?", (version_id,)).fetchone(), ("terms_json",))}
                if not is_buyer: raise DomainError(403, "Only the buyer tenant can publish contract versions", "role_forbidden")
                terms = _payload_json(payload, "terms", {})
                if not isinstance(terms, dict): raise DomainError(400, "terms must be an object", "validation_error")
                latest = conn.execute("SELECT * FROM domain_network_contract_versions WHERE contract_id = ? ORDER BY version DESC LIMIT 1", (contract_id,)).fetchone()
                version_number = int(latest["version"] if latest else 0) + 1
                now = now_iso(); version_id = new_id("network_contract_version")
                conn.execute("INSERT INTO domain_network_contract_versions(id, organization_id, contract_id, version, status, terms_json, effective_from, effective_to, source, supersedes_version_id, created_by, created_at) VALUES (?, ?, ?, ?, 'published', ?, ?, ?, 'buyer', ?, ?, ?)", (version_id, contract["organization_id"], contract_id, version_number, json.dumps(terms), _text(payload, "effective_from", maximum=40) or None, _text(payload, "effective_to", maximum=40) or None, latest["id"] if latest else None, user["id"], now))
                rates = payload.get("rate_cards", terms.get("rate_cards", terms.get("rates", [])))
                if isinstance(rates, dict): rates = [rates]
                if not isinstance(rates, list): rates = []
                for index, rate in enumerate(rates):
                    if not isinstance(rate, dict): continue
                    code = _text(rate, "rate_code", _text(rate, "code", f"rate_{index + 1}", 80), 80)
                    conn.execute("INSERT INTO domain_network_rate_cards(id, organization_id, contract_version_id, rate_code, service_type, vehicle_type, city, unit, amount_paise, currency, effective_from, effective_to, status, terms_json, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)", (new_id("network_rate"), contract["organization_id"], version_id, code, _text(rate, "service_type", maximum=80), _text(rate, "vehicle_type", maximum=80), _text(rate, "city", maximum=80), _text(rate, "unit", "trip", 30), _positive_int(rate.get("amount_paise", rate.get("total_paise", 0)), "amount_paise"), _text(rate, "currency", "INR", 8), _text(rate, "effective_from", maximum=40) or None, _text(rate, "effective_to", maximum=40) or None, json.dumps(rate.get("terms") if isinstance(rate.get("terms"), dict) else {}), user["id"], now))
                key = _text(payload, "idempotency_key", maximum=160) or None
                if key:
                    existing = conn.execute("SELECT * FROM domain_network_contract_syncs WHERE organization_id = ? AND idempotency_key = ?", (contract["organization_id"], key)).fetchone()
                    if existing: return {"ok": True, "duplicate": True, "item": _row_json(existing, ("change_summary_json",))}
                sync_id = new_id("network_contract_sync"); conn.execute("INSERT INTO domain_network_contract_syncs(id, organization_id, contract_id, contract_version_id, direction, status, source_version, target_version, change_summary_json, provider_reference, idempotency_key, requested_by, requested_at) VALUES (?, ?, ?, ?, 'outbound', 'sent', ?, ?, ?, ?, ?, ?, ?)", (sync_id, contract["organization_id"], contract_id, version_id, version_number - 1 if latest else None, version_number, json.dumps({"rate_cards": len(rates), "terms": True}), f"mock-contract-sync-{sync_id}", key, user["id"], now))
                _emit(conn, user, "contract.version.published", "contract", contract_id, ip, {"version_id": version_id, "version": version_number, "sync_id": sync_id})
                return {"ok": True, "item": _row_json(conn.execute("SELECT * FROM domain_network_contract_versions WHERE id = ?", (version_id,)).fetchone(), ("terms_json",)), "sync": _row_json(conn.execute("SELECT * FROM domain_network_contract_syncs WHERE id = ?", (sync_id,)).fetchone(), ("change_summary_json",))}
            if contract_action == "sync" and method == "GET":
                rows = conn.execute("SELECT * FROM domain_network_contract_syncs WHERE contract_id = ? ORDER BY requested_at DESC", (contract_id,)).fetchall()
                return {"ok": True, "items": [_row_json(row, ("change_summary_json",)) for row in rows]}
            if contract_action == "sync" and method == "POST":
                if not is_buyer: raise DomainError(403, "Only the buyer tenant can request a contract synchronization", "role_forbidden")
                version_id = _text(payload, "version_id", maximum=100) or None
                version = conn.execute("SELECT * FROM domain_network_contract_versions WHERE id = ? AND contract_id = ?", (version_id, contract_id)).fetchone() if version_id else conn.execute("SELECT * FROM domain_network_contract_versions WHERE contract_id = ? ORDER BY version DESC LIMIT 1", (contract_id,)).fetchone()
                if not version: raise DomainError(404, "Contract version not found", "not_found")
                key = _text(payload, "idempotency_key", maximum=160) or None
                if key:
                    existing = conn.execute("SELECT * FROM domain_network_contract_syncs WHERE organization_id = ? AND idempotency_key = ?", (contract["organization_id"], key)).fetchone()
                    if existing: return {"ok": True, "duplicate": True, "item": _row_json(existing, ("change_summary_json",))}
                sync_id = new_id("network_contract_sync"); now = now_iso(); conn.execute("INSERT INTO domain_network_contract_syncs(id, organization_id, contract_id, contract_version_id, direction, status, source_version, target_version, change_summary_json, provider_reference, idempotency_key, requested_by, requested_at) VALUES (?, ?, ?, ?, 'outbound', 'sent', ?, ?, ?, ?, ?, ?, ?)", (sync_id, contract["organization_id"], contract_id, version_id, None, version["version"], json.dumps({"resend": True}), f"mock-contract-sync-{sync_id}", key, user["id"], now)); return {"ok": True, "item": _row_json(conn.execute("SELECT * FROM domain_network_contract_syncs WHERE id = ?", (sync_id,)).fetchone(), ("change_summary_json",))}

    exchange_collection = re.fullmatch(r"/service-orders/([^/]+)/exchanges", suffix)
    if exchange_collection:
        service_id = exchange_collection.group(1); order, is_buyer = _access_service_order_for_user(conn, service_id, user); owner_org = order["organization_id"]
        if method == "GET":
            rows = conn.execute("SELECT * FROM domain_network_exchange_envelopes WHERE organization_id = ? AND service_order_id = ? ORDER BY created_at DESC LIMIT ?", (owner_org, service_id, _limit(query))).fetchall()
            return {"ok": True, "items": [_row_json(row, ("payload_json", "attachments_json")) for row in rows]}
        if method == "POST":
            exchange_type = _text(payload, "exchange_type", maximum=30)
            if exchange_type not in {"booking", "duty_slip", "invoice", "operational_message"}: raise DomainError(400, "Unsupported Network exchange type", "validation_error")
            direction = _text(payload, "direction", "outbound" if is_buyer else "inbound", 20)
            if direction not in {"outbound", "inbound"}: raise DomainError(400, "direction must be inbound or outbound", "validation_error")
            key = _text(payload, "idempotency_key", maximum=160) or None
            if key:
                existing = conn.execute("SELECT * FROM domain_network_exchange_envelopes WHERE organization_id = ? AND idempotency_key = ?", (owner_org, key)).fetchone()
                if existing: return {"ok": True, "duplicate": True, "item": _row_json(existing, ("payload_json", "attachments_json"))}
            envelope_id = new_id("network_exchange"); now = now_iso(); envelope_status = "sent" if payload.get("send_now", True) else "queued"
            conn.execute("INSERT INTO domain_network_exchange_envelopes(id, organization_id, service_order_id, exchange_type, direction, status, schema_version, external_reference, payload_json, attachments_json, idempotency_key, sender_organization_id, recipient_organization_id, provider_reference, created_by, created_at, sent_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (envelope_id, owner_org, service_id, exchange_type, direction, envelope_status, _text(payload, "schema_version", "v1", 20), _text(payload, "external_reference", maximum=160), json.dumps(_payload_json(payload, "payload", {})), json.dumps(payload.get("attachments") if isinstance(payload.get("attachments"), list) else []), key, org if direction == "inbound" else owner_org, owner_org if direction == "inbound" else _text(payload, "recipient_organization_id", maximum=100), f"mock-exchange-{envelope_id}" if envelope_status == "sent" else "", user["id"], now, now if envelope_status == "sent" else None))
            _emit(conn, user, f"exchange.{exchange_type}.created", "exchange", envelope_id, ip, {"service_order_id": service_id, "direction": direction, "status": envelope_status}, owner_org)
            return {"ok": True, "item": _row_json(conn.execute("SELECT * FROM domain_network_exchange_envelopes WHERE id = ?", (envelope_id,)).fetchone(), ("payload_json", "attachments_json"))}

    exchange_action = re.fullmatch(r"/exchanges/([^/]+)/(acknowledge|reject|process)", suffix)
    if exchange_action and method == "POST":
        envelope = conn.execute("SELECT * FROM domain_network_exchange_envelopes WHERE id = ?", (exchange_action.group(1),)).fetchone()
        if not envelope: raise DomainError(404, "Network exchange not found", "not_found")
        _access_service_order_for_user(conn, envelope["service_order_id"], user)
        action = exchange_action.group(2); target = {"acknowledge": "acknowledged", "reject": "rejected", "process": "processed"}[action]
        if envelope["status"] in {"processed", "rejected"} and target != envelope["status"]: raise DomainError(409, "Exchange is already closed", "invalid_transition")
        now = now_iso(); error = _text(payload, "error", maximum=500) if target == "rejected" else ""
        conn.execute("UPDATE domain_network_exchange_envelopes SET status = ?, acknowledged_at = ?, processed_at = ?, error = ? WHERE id = ?", (target, now if target == "acknowledged" else envelope["acknowledged_at"], now if target == "processed" else envelope["processed_at"], error, envelope["id"]))
        _emit(conn, user, f"exchange.{target}", "exchange", envelope["id"], ip, {"service_order_id": envelope["service_order_id"], "error": error}, envelope["organization_id"])
        return {"ok": True, "item": _row_json(conn.execute("SELECT * FROM domain_network_exchange_envelopes WHERE id = ?", (envelope["id"],)).fetchone(), ("payload_json", "attachments_json"))}

    order_subresource = re.fullmatch(r"/service-orders/([^/]+)/(sla-observations|issues|rate-discrepancies|settlement-resolutions)", suffix)
    if order_subresource:
        service_id, resource = order_subresource.groups(); order, is_buyer = _access_service_order_for_user(conn, service_id, user); owner_org = order["organization_id"]
        table_map = {"sla-observations": "domain_network_sla_observations", "issues": "domain_network_supplier_issues", "rate-discrepancies": "domain_network_rate_discrepancies", "settlement-resolutions": "domain_network_settlement_resolutions"}
        table = table_map[resource]
        if method == "GET":
            rows = conn.execute(f"SELECT * FROM {table} WHERE organization_id = ? AND service_order_id = ? ORDER BY created_at DESC LIMIT ?", (owner_org, service_id, _limit(query))).fetchall()
            json_fields = {"domain_network_sla_observations": ("evidence_json",), "domain_network_supplier_issues": ("evidence_json", "proposed_resolution_json", "resolution_json"), "domain_network_rate_discrepancies": ("evidence_json", "resolution_json"), "domain_network_settlement_resolutions": ("evidence_json",)}[table]
            return {"ok": True, "items": [_row_json(row, json_fields) for row in rows]}
        if method == "POST":
            key = _text(payload, "idempotency_key", maximum=160) or None
            if key:
                existing = conn.execute(f"SELECT * FROM {table} WHERE organization_id = ? AND idempotency_key = ?", (owner_org, key)).fetchone()
                if existing: return {"ok": True, "duplicate": True, "item": _row_json(existing)}
            now = now_iso()
            if resource == "sla-observations":
                metric = _text(payload, "metric", maximum=100); target = float(payload.get("target_value") or 0); observed = float(payload.get("observed_value") or 0)
                if not metric: raise DomainError(400, "metric is required", "validation_error")
                observation_id = new_id("network_sla_observation"); status_value = _text(payload, "status", "met" if observed >= target else "breached", 20)
                conn.execute("INSERT INTO domain_network_sla_observations(id, organization_id, service_order_id, sla_id, metric, target_value, observed_value, unit, status, severity, evidence_json, observed_at, source, idempotency_key, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (observation_id, owner_org, service_id, _text(payload, "sla_id", maximum=100) or None, metric, target, observed, _text(payload, "unit", maximum=30), status_value, _text(payload, "severity", "warning", 20), json.dumps(_payload_json(payload, "evidence", {})), _text(payload, "observed_at", now, 40), _text(payload, "source", "operator", 30), key, user["id"], now))
                result_id, event_type = observation_id, "sla.observed"
            elif resource == "issues":
                issue_type = _text(payload, "issue_type", "operational", 30)
                if issue_type not in {"rejection", "sla_breach", "rate_discrepancy", "settlement_dispute", "operational"}: raise DomainError(400, "Unsupported supplier issue type", "validation_error")
                result_id = new_id("network_issue"); event_type = "supplier_issue.created"
                conn.execute("INSERT INTO domain_network_supplier_issues(id, organization_id, service_order_id, vendor_profile_id, issue_type, status, severity, reason_code, description, evidence_json, proposed_resolution_json, resolution_json, reported_by, assigned_to, due_at, idempotency_key, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, '{}', ?, ?, ?, ?, ?, ?)", (result_id, owner_org, service_id, order["vendor_profile_id"], issue_type, _text(payload, "severity", "medium", 20), _text(payload, "reason_code", maximum=80), _text(payload, "description", maximum=2000), json.dumps(_payload_json(payload, "evidence", {})), json.dumps(_payload_json(payload, "proposed_resolution", {})), user["id"], _text(payload, "assigned_to", maximum=100) or None, _text(payload, "due_at", maximum=40) or None, key, now, now))
            elif resource == "rate-discrepancies":
                expected = _positive_int(payload.get("expected_paise"), "expected_paise"); actual = _positive_int(payload.get("actual_paise"), "actual_paise"); result_id = new_id("network_rate_discrepancy"); event_type = "rate_discrepancy.created"
                conn.execute("INSERT INTO domain_network_rate_discrepancies(id, organization_id, service_order_id, contract_id, rate_card_id, issue_id, expected_paise, actual_paise, variance_paise, currency, status, reason, evidence_json, resolution_json, idempotency_key, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, '{}', ?, ?, ?)", (result_id, owner_org, service_id, _text(payload, "contract_id", maximum=100) or None, _text(payload, "rate_card_id", maximum=100) or None, _text(payload, "issue_id", maximum=100) or None, expected, actual, actual - expected, _text(payload, "currency", "INR", 8), _text(payload, "reason", maximum=500), json.dumps(_payload_json(payload, "evidence", {})), key, user["id"], now))
            else:
                settlement_id = _text(payload, "settlement_id", maximum=100)
                settlement = conn.execute("SELECT * FROM domain_network_settlements WHERE id = ? AND organization_id = ? AND service_order_id = ?", (settlement_id, owner_org, service_id)).fetchone()
                if not settlement: raise DomainError(404, "Network settlement not found", "not_found")
                result_id = new_id("network_settlement_resolution"); event_type = "settlement_resolution.proposed"
                conn.execute("INSERT INTO domain_network_settlement_resolutions(id, organization_id, service_order_id, settlement_id, issue_id, discrepancy_id, status, resolution_type, adjustment_paise, notes, evidence_json, proposed_by, idempotency_key, created_at) VALUES (?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?, ?)", (result_id, owner_org, service_id, settlement_id, _text(payload, "issue_id", maximum=100) or None, _text(payload, "discrepancy_id", maximum=100) or None, _text(payload, "resolution_type", "adjustment", 30), int(payload.get("adjustment_paise") or 0), _text(payload, "notes", maximum=2000), json.dumps(_payload_json(payload, "evidence", {})), user["id"], key, now))
            _emit(conn, user, event_type, resource, result_id, ip, {"service_order_id": service_id}, owner_org)
            return {"ok": True, "item": _row_json(conn.execute(f"SELECT * FROM {table} WHERE id = ?", (result_id,)).fetchone(), {"sla-observations": ("evidence_json",), "issues": ("evidence_json", "proposed_resolution_json", "resolution_json"), "rate-discrepancies": ("evidence_json", "resolution_json"), "settlement-resolutions": ("evidence_json",)}[resource])}

    issue_action = re.fullmatch(r"/(issues|rate-discrepancies|settlement-resolutions)/([^/]+)/(resolve|decide)", suffix)
    if issue_action and method == "POST":
        resource, entity_id, action = issue_action.groups(); table = {"issues": "domain_network_supplier_issues", "rate-discrepancies": "domain_network_rate_discrepancies", "settlement-resolutions": "domain_network_settlement_resolutions"}[resource]
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ? AND organization_id = ?", (entity_id, org)).fetchone()
        if not row:
            # vendor users may act through the linked service order
            row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (entity_id,)).fetchone()
            if row: _access_service_order_for_user(conn, row["service_order_id"], user) if "service_order_id" in row.keys() else None
        if not row: raise DomainError(404, "Network resolution record not found", "not_found")
        now = now_iso(); target = _text(payload, "status", "resolved" if resource != "settlement-resolutions" else "accepted", 20)
        if resource == "issues": conn.execute("UPDATE domain_network_supplier_issues SET status = ?, resolution_json = ?, resolved_by = ?, resolved_at = ?, updated_at = ? WHERE id = ?", (target, json.dumps(_payload_json(payload, "resolution", {})), user["id"], now if target in {"resolved", "closed"} else None, now, row["id"]))
        elif resource == "rate-discrepancies": conn.execute("UPDATE domain_network_rate_discrepancies SET status = ?, resolution_json = ?, resolved_by = ?, resolved_at = ? WHERE id = ?", (target, json.dumps(_payload_json(payload, "resolution", {})), user["id"], now if target == "resolved" else None, row["id"]))
        else: conn.execute("UPDATE domain_network_settlement_resolutions SET status = ?, notes = ?, decided_by = ?, decided_at = ?, applied_at = ? WHERE id = ?", (target, _text(payload, "notes", maximum=2000), user["id"], now, now if target == "applied" else None, row["id"]))
        _emit(conn, user, f"{resource}.{target}", resource, row["id"], ip, {"status": target}, org)
        return {"ok": True, "item": _row_json(conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row["id"],)).fetchone())}

    contract_match = re.fullmatch(r"/contracts/([^/]+)/sign", suffix)
    if contract_match and method == "POST":
        contract = _owned(conn, "domain_network_contracts", contract_match.group(1), org, "Network contract not found")
        if contract["status"] not in {"draft", "signed"}:
            raise DomainError(409, "Contract cannot be signed in its current state", "invalid_transition")
        evidence = _payload_json(payload, "evidence", {"signed_by": user["id"]})
        conn.execute("UPDATE domain_network_contracts SET status = 'signed', signed_by = ?, signed_at = ?, updated_at = ? WHERE id = ?", (user["id"], now_iso(), now_iso(), contract["id"]))
        award = conn.execute("SELECT * FROM domain_network_awards WHERE id = ?", (contract["award_id"],)).fetchone()
        check = conn.execute("SELECT * FROM domain_network_activation_checks WHERE award_id = ? AND check_key = 'contract_signed'", (contract["award_id"],)).fetchone()
        if check:
            conn.execute("UPDATE domain_network_activation_checks SET status = 'passed', evidence_json = ?, checked_by = ?, checked_at = ? WHERE id = ?", (json.dumps(evidence), user["id"], now_iso(), check["id"]))
            _record_snapshot(conn, user, "activation_check", check["id"], {"award_id": contract["award_id"], "check_key": "contract_signed", "status": "passed", "evidence": evidence}, "passed")
        _record_snapshot(conn, user, "contract", contract["id"], {"award_id": contract["award_id"], "status": "signed", "evidence": evidence}, "signed")
        _emit(conn, user, "contract.signed", "contract", contract["id"], ip, {"award_id": contract["award_id"]})
        return {"ok": True, "item": _row_json(conn.execute("SELECT * FROM domain_network_contracts WHERE id = ?", (contract["id"],)).fetchone(), ("terms_json",))}

    service_collection = re.fullmatch(r"/service-orders(?:/([^/]+))?", suffix)
    if service_collection and method == "GET":
        service_id = service_collection.group(1)
        if service_id:
            order = _owned(conn, "domain_network_service_orders", service_id, org, "Network service order not found")
            return {"ok": True, "item": _row_json(order, ("config_json",))}
        rows = conn.execute("SELECT * FROM domain_network_service_orders WHERE organization_id = ? ORDER BY activated_at DESC LIMIT ?", (org, _limit(query))).fetchall()
        return {"ok": True, "items": [_row_json(row, ("config_json",)) for row in rows]}

    scorecard_collection = re.fullmatch(r"/service-orders/([^/]+)/scorecards", suffix)
    if scorecard_collection and method in {"GET", "POST"}:
        service_id = scorecard_collection.group(1)
        _owned(conn, "domain_network_service_orders", service_id, org, "Network service order not found")
        if method == "GET":
            rows = conn.execute("SELECT * FROM domain_network_scorecards WHERE organization_id = ? AND service_order_id = ? ORDER BY period_start DESC", (org, service_id)).fetchall()
            return {"ok": True, "items": [_row_json(row, ("metrics_json", "evidence_json")) for row in rows]}
        metrics = _payload_json(payload, "metrics", {})
        evidence = _payload_json(payload, "evidence", {})
        if not evidence:
            raise DomainError(400, "Evidence is required for a scorecard", "evidence_required")
        key = _text(payload, "idempotency_key", maximum=160) or None
        if key:
            existing = conn.execute("SELECT * FROM domain_network_scorecards WHERE organization_id = ? AND idempotency_key = ?", (org, key)).fetchone()
            if existing:
                return {"ok": True, "duplicate": True, "item": _row_json(existing, ("metrics_json", "evidence_json"))}
        period_start = _text(payload, "period_start", maximum=40)
        period_end = _text(payload, "period_end", maximum=40)
        if not period_start or not period_end:
            raise DomainError(400, "period_start and period_end are required", "validation_error")
        scorecard_id = new_id("network_scorecard")
        conn.execute("INSERT INTO domain_network_scorecards(id, organization_id, service_order_id, period_start, period_end, status, metrics_json, evidence_json, created_by, created_at, idempotency_key) VALUES (?, ?, ?, ?, ?, 'submitted', ?, ?, ?, ?, ?)", (scorecard_id, org, service_id, period_start, period_end, json.dumps(metrics if isinstance(metrics, dict) else {}), json.dumps(evidence), user["id"], now_iso(), key))
        _record_snapshot(conn, user, "scorecard", scorecard_id, {"service_order_id": service_id, "period_start": period_start, "period_end": period_end, "metrics": metrics, "evidence": evidence}, "submitted")
        _emit(conn, user, "scorecard.submitted", "scorecard", scorecard_id, ip, {"service_order_id": service_id})
        return {"ok": True, "item": _row_json(conn.execute("SELECT * FROM domain_network_scorecards WHERE id = ?", (scorecard_id,)).fetchone(), ("metrics_json", "evidence_json"))}

    settlement_collection = re.fullmatch(r"/service-orders/([^/]+)/settlements", suffix)
    if settlement_collection and method in {"GET", "POST"}:
        service_id = settlement_collection.group(1)
        _owned(conn, "domain_network_service_orders", service_id, org, "Network service order not found")
        if method == "GET":
            rows = conn.execute("SELECT * FROM domain_network_settlements WHERE organization_id = ? AND service_order_id = ? ORDER BY period_start DESC", (org, service_id)).fetchall()
            return {"ok": True, "items": [_row_json(row, ("evidence_json",)) for row in rows]}
        gross = _positive_int(payload.get("gross_paise"), "gross_paise")
        deductions = _positive_int(payload.get("deductions_paise"), "deductions_paise")
        if deductions > gross:
            raise DomainError(400, "deductions_paise cannot exceed gross_paise", "validation_error")
        evidence = _payload_json(payload, "evidence", {})
        if not evidence:
            raise DomainError(400, "Evidence is required for settlement", "evidence_required")
        scorecard_id = _text(payload, "scorecard_id", maximum=100) or None
        if scorecard_id:
            scorecard = _owned(conn, "domain_network_scorecards", scorecard_id, org, "Network scorecard not found")
            if scorecard["service_order_id"] != service_id:
                raise DomainError(409, "Scorecard does not belong to this service order", "invalid_reference")
        key = _text(payload, "idempotency_key", maximum=160) or None
        if key:
            existing = conn.execute("SELECT * FROM domain_network_settlements WHERE organization_id = ? AND idempotency_key = ?", (org, key)).fetchone()
            if existing:
                return {"ok": True, "duplicate": True, "item": _row_json(existing, ("evidence_json",))}
        period_start = _text(payload, "period_start", maximum=40)
        period_end = _text(payload, "period_end", maximum=40)
        if not period_start or not period_end:
            raise DomainError(400, "period_start and period_end are required", "validation_error")
        settlement_id = new_id("network_settlement")
        conn.execute("INSERT INTO domain_network_settlements(id, organization_id, service_order_id, scorecard_id, period_start, period_end, gross_paise, deductions_paise, net_paise, status, evidence_json, created_by, created_at, idempotency_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?)", (settlement_id, org, service_id, scorecard_id, period_start, period_end, gross, deductions, gross - deductions, json.dumps(evidence), user["id"], now_iso(), key))
        _record_snapshot(conn, user, "settlement", settlement_id, {"service_order_id": service_id, "scorecard_id": scorecard_id, "gross_paise": gross, "deductions_paise": deductions, "net_paise": gross - deductions, "evidence": evidence}, "created")
        _emit(conn, user, "settlement.created", "settlement", settlement_id, ip, {"service_order_id": service_id, "net_paise": gross - deductions})
        return {"ok": True, "item": _row_json(conn.execute("SELECT * FROM domain_network_settlements WHERE id = ?", (settlement_id,)).fetchone(), ("evidence_json",))}

    if suffix == "/events" and method == "GET":
        rows = conn.execute("SELECT * FROM domain_network_events WHERE organization_id = ? ORDER BY created_at DESC LIMIT ?", (org, _limit(query))).fetchall()
        return {"ok": True, "items": [_row_json(row, ("payload_json",)) for row in rows]}

    # Compatibility Network routes (regions, scorecard formulas and older
    # lifecycle surfaces) are owned by the additive P0 handler. Returning None
    # here lets the shared dispatcher fall through instead of shadowing those
    # tenant-scoped contracts with a false 404.
    return None