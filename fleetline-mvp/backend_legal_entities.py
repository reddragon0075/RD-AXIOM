"""Axiom Fleet Multi-Brand & Multi-GSTIN Legal Entities ("My Companies") Controller.

Allows fleet operators to run multiple brand identities, distinct GSTINs,
independent invoice prefixes/sequences, and dedicated bank accounts under
a single vendor organization.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlsplit

from backend_domain import DomainError, _assert_owned, _audit, _org, _serialize, _text, new_id, now_iso

PREFIX = "/api/legal-entities"


def initialize_legal_entities_schema(conn: sqlite3.Connection) -> None:
    """Creates SQLite table for vendor multi-brand legal entities."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS domain_legal_entities (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            brand_name TEXT NOT NULL,
            legal_name TEXT NOT NULL,
            gstin TEXT NOT NULL DEFAULT '',
            pan TEXT NOT NULL DEFAULT '',
            state_code TEXT NOT NULL DEFAULT '',
            address TEXT NOT NULL DEFAULT '',
            city TEXT NOT NULL DEFAULT '',
            pincode TEXT NOT NULL DEFAULT '',
            bank_name TEXT NOT NULL DEFAULT '',
            account_number TEXT NOT NULL DEFAULT '',
            ifsc_code TEXT NOT NULL DEFAULT '',
            upi_id TEXT NOT NULL DEFAULT '',
            invoice_prefix TEXT NOT NULL DEFAULT 'INV/',
            next_invoice_number INTEGER NOT NULL DEFAULT 1001,
            logo_url TEXT NOT NULL DEFAULT '',
            is_default INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_legal_entities_org 
        ON domain_legal_entities(organization_id, is_active)
        """
    )
    conn.commit()


def _seed_default_entity_if_empty(conn: sqlite3.Connection, org_id: str) -> None:
    """Ensures every vendor organization has at least one default legal brand entity."""
    count = conn.execute(
        "SELECT count(*) FROM domain_legal_entities WHERE organization_id = ? AND is_active = 1",
        (org_id,),
    ).fetchone()[0]
    if count > 0:
        return

    # Look up organization details
    org_row = conn.execute("SELECT * FROM organizations WHERE id = ?", (org_id,)).fetchone()
    if not org_row:
        return
    org = dict(org_row)

    now = now_iso()
    entity_id = f"ent_{org_id[:8]}_primary"
    gstin = org.get("gstin") or ""
    pan = gstin[2:12] if len(gstin) >= 12 else ""
    state_code = gstin[:2] if len(gstin) >= 2 else "29"

    conn.execute(
        """
        INSERT OR REPLACE INTO domain_legal_entities (
            id, organization_id, brand_name, legal_name, gstin, pan,
            state_code, address, city, pincode, bank_name, account_number,
            ifsc_code, upi_id, invoice_prefix, next_invoice_number,
            logo_url, is_default, is_active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
        """,
        (
            entity_id,
            org_id,
            org.get("name") or "Primary Fleet Operations",
            org.get("name") or "Primary Fleet Pvt Ltd",
            gstin,
            pan,
            state_code,
            "Main Transport Hub",
            org.get("city") or "Bengaluru",
            "560001",
            "HDFC Bank",
            "50200012345678",
            "HDFC0000123",
            f"{org_id[:8]}@hdfcbank",
            f"{org.get('name', 'INV')[:3].upper()}/26-27/",
            1001,
            "axiom-fleet-logo.png",
            now,
            now,
        ),
    )
    conn.commit()


def handle_legal_entities(
    conn: sqlite3.Connection,
    user: Dict[str, Any],
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    remote_ip: str = "127.0.0.1",
) -> Optional[Dict[str, Any]]:
    """Handles /api/legal-entities routes for vendor multi-brand management."""
    parsed = urlsplit(path)
    clean_path = parsed.path.rstrip("/") or "/"
    org_id = _org(user)

    if not clean_path.startswith(PREFIX):
        return None

    _seed_default_entity_if_empty(conn, org_id)

    # 1. List all active legal entities / brands for this vendor
    if clean_path == PREFIX and method == "GET":
        cur = conn.execute(
            """
            SELECT * FROM domain_legal_entities 
            WHERE organization_id = ? AND is_active = 1
            ORDER BY is_default DESC, brand_name ASC
            """,
            (org_id,),
        )
        items = [dict(r) for r in cur.fetchall()]
        for it in items:
            it["is_default"] = bool(it["is_default"])
            it["is_active"] = bool(it["is_active"])
        return {"ok": True, "items": items, "count": len(items)}

    # 2. Create or Update a Legal Entity Brand
    if clean_path == PREFIX and method == "POST":
        data = payload or {}
        brand_name = _text(data, "brand_name")
        if not brand_name:
            raise DomainError(400, "brand_name is required", "missing_field")

        legal_name = _text(data, "legal_name", default=brand_name)
        gstin = str(data.get("gstin") or "").strip().upper()
        pan = str(data.get("pan") or (gstin[2:12] if len(gstin) >= 12 else "")).strip().upper()
        state_code = str(data.get("state_code") or (gstin[:2] if len(gstin) >= 2 else "")).strip()

        entity_id = data.get("id") or new_id("ent")
        is_default = 1 if data.get("is_default") else 0
        now = now_iso()

        # If setting as default, clear other default flags first
        if is_default == 1:
            conn.execute(
                "UPDATE domain_legal_entities SET is_default = 0 WHERE organization_id = ?",
                (org_id,),
            )

        conn.execute(
            """
            INSERT OR REPLACE INTO domain_legal_entities (
                id, organization_id, brand_name, legal_name, gstin, pan,
                state_code, address, city, pincode, bank_name, account_number,
                ifsc_code, upi_id, invoice_prefix, next_invoice_number,
                logo_url, is_default, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                entity_id,
                org_id,
                brand_name,
                legal_name,
                gstin,
                pan,
                state_code,
                _text(data, "address"),
                _text(data, "city", default="Bengaluru"),
                _text(data, "pincode", default="560001"),
                _text(data, "bank_name"),
                _text(data, "account_number"),
                _text(data, "ifsc_code"),
                _text(data, "upi_id"),
                _text(data, "invoice_prefix", default="INV/"),
                int(data.get("next_invoice_number") or 1001),
                _text(data, "logo_url", default="axiom-fleet-logo.png"),
                is_default,
                now,
                now,
            ),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM domain_legal_entities WHERE id = ?", (entity_id,)).fetchone()
        item = dict(row)
        item["is_default"] = bool(item["is_default"])
        item["is_active"] = bool(item["is_active"])
        return {"ok": True, "item": item, "status": "success"}

    # 3. Set a Legal Entity as Default
    set_default_match = re.match(r"^/api/legal-entities/([^/]+)/set-default$", clean_path)
    if set_default_match and method == "POST":
        ent_id = set_default_match.group(1)
        _assert_owned(conn, "domain_legal_entities", ent_id, org_id)

        conn.execute(
            "UPDATE domain_legal_entities SET is_default = 0 WHERE organization_id = ?",
            (org_id,),
        )
        conn.execute(
            "UPDATE domain_legal_entities SET is_default = 1, updated_at = ? WHERE id = ?",
            (now_iso(), ent_id),
        )
        conn.commit()
        return {"ok": True, "status": "success", "default_entity_id": ent_id}

    # 4. Generate Next Formatted Invoice Number & Increment Sequence
    next_inv_match = re.match(r"^/api/legal-entities/([^/]+)/next-invoice-number$", clean_path)
    if next_inv_match and method == "POST":
        ent_id = next_inv_match.group(1)
        row = _assert_owned(conn, "domain_legal_entities", ent_id, org_id)
        ent = dict(row)

        prefix = ent.get("invoice_prefix") or "INV/"
        num = int(ent.get("next_invoice_number") or 1001)
        formatted_invoice_number = f"{prefix}{num}"

        # Increment sequence
        conn.execute(
            "UPDATE domain_legal_entities SET next_invoice_number = ?, updated_at = ? WHERE id = ?",
            (num + 1, now_iso(), ent_id),
        )
        conn.commit()

        return {
            "ok": True,
            "entity_id": ent_id,
            "brand_name": ent["brand_name"],
            "gstin": ent["gstin"],
            "invoice_number": formatted_invoice_number,
            "next_sequence": num + 1,
        }

    # 5. Soft Delete / Archive a Brand Entity
    del_match = re.match(r"^/api/legal-entities/([^/]+)$", clean_path)
    if del_match and method == "DELETE":
        ent_id = del_match.group(1)
        _assert_owned(conn, "domain_legal_entities", ent_id, org_id)

        # Do not allow deleting if it's the only active entity
        active_count = conn.execute(
            "SELECT count(*) FROM domain_legal_entities WHERE organization_id = ? AND is_active = 1",
            (org_id,),
        ).fetchone()[0]
        if active_count <= 1:
            raise DomainError(400, "Cannot delete the only active legal entity brand", "cannot_delete_last_brand")

        conn.execute(
            "UPDATE domain_legal_entities SET is_active = 0, is_default = 0, updated_at = ? WHERE id = ?",
            (now_iso(), ent_id),
        )
        # Ensure at least one remaining entity is default
        has_default = conn.execute(
            "SELECT count(*) FROM domain_legal_entities WHERE organization_id = ? AND is_active = 1 AND is_default = 1",
            (org_id,),
        ).fetchone()[0]
        if has_default == 0:
            first_active = conn.execute(
                "SELECT id FROM domain_legal_entities WHERE organization_id = ? AND is_active = 1 LIMIT 1",
                (org_id,),
            ).fetchone()
            if first_active:
                conn.execute(
                    "UPDATE domain_legal_entities SET is_default = 1 WHERE id = ?",
                    (first_active[0],),
                )
        conn.commit()
        return {"ok": True, "status": "archived", "id": ent_id}

    return None
