"""Hierarchical Rate Card & Tariff Rule Resolver for Axiom Fleet.

Implements the 4-Tier Waterfall Resolution:
  Tier 1: Entity (Customer/Supplier) + Specific Branch/City
  Tier 2: Entity Global Default (city_id IS NULL)
  Tier 3: Tenant Branch/City Default Rack Rate (entity_id IS NULL)
  Tier 4: Tenant Global Base Rate (entity_id IS NULL AND city_id IS NULL)

Also enforces Indecab-style Vehicle Upgrade protection:
- RECEIVABLE (Customer): Billed on requested_vehicle_group unless charge_upgrade_to_client=True
- PAYABLE (Supplier): Billed on allotted_vehicle_group (the actual vehicle dispatched)
"""

from __future__ import annotations

from typing import Any

try:
    from .fare_engine import FareError, _normalise_mode
except (ImportError, ValueError):
    from fare_engine import FareError, _normalise_mode


TIER_LABELS = {
    1: "TIER_1_ENTITY_CITY",
    2: "TIER_2_ENTITY_GLOBAL",
    3: "TIER_3_CITY_DEFAULT",
    4: "TIER_4_GLOBAL_DEFAULT",
}


def resolve_billed_vehicle_group(
    *,
    ledger_side: str,
    requested_vehicle_group: str,
    allotted_vehicle_group: str | None = None,
    charge_upgrade_to_client: bool = False,
) -> str:
    """Determine which vehicle group to look up on the rate card."""
    side = str(ledger_side or "RECEIVABLE").strip().upper()
    req_vg = str(requested_vehicle_group or "").strip()
    allot_vg = str(allotted_vehicle_group or req_vg).strip()

    if not req_vg:
        raise FareError("requested_vehicle_group is required", "missing_vehicle_group")

    if side == "RECEIVABLE":
        return allot_vg if charge_upgrade_to_client else req_vg
    return allot_vg


def resolve_rate_card_context(
    rate_rules: list[dict[str, Any]],
    *,
    tenant_id: str,
    ledger_side: str = "RECEIVABLE",
    entity_id: str | None = None,
    city_id: str | None = None,
    duty_date: str | None = None,
    fare_mode: str = "local",
    requested_vehicle_group: str,
    allotted_vehicle_group: str | None = None,
    charge_upgrade_to_client: bool = False,
    booked_package_name: str | None = None,
    booked_rule_id: str | None = None,
) -> dict[str, Any]:
    """Resolve the winning pricing profile and sibling candidate slabs from a
    list of rate-card/tariff-rule records using the 4-tier hierarchy.
    """
    normalised_mode = _normalise_mode(fare_mode)
    side = str(ledger_side or "RECEIVABLE").strip().upper()
    expected_entity_type = "CLIENT" if side == "RECEIVABLE" else "SUPPLIER"

    billed_vg = resolve_billed_vehicle_group(
        ledger_side=side,
        requested_vehicle_group=requested_vehicle_group,
        allotted_vehicle_group=allotted_vehicle_group,
        charge_upgrade_to_client=charge_upgrade_to_client,
    )

    matched_by_tier: dict[int, list[dict[str, Any]]] = {1: [], 2: [], 3: [], 4: []}

    for rule in rate_rules:
        if not isinstance(rule, dict):
            continue
        rule_tenant = str(rule.get("tenant_id") or rule.get("organization_id") or "")
        if rule_tenant != str(tenant_id):
            continue

        rule_entity_type = str(rule.get("entity_type") or "DEFAULT").upper()
        if rule_entity_type not in {expected_entity_type, "DEFAULT"}:
            continue

        if _normalise_mode(rule.get("fare_mode") or rule.get("duty_type")) != normalised_mode:
            continue
        if str(rule.get("vehicle_group_id") or rule.get("vehicle_group") or "") != billed_vg:
            continue

        # Date validity check (YYYY-MM-DD lexical comparison)
        if duty_date:
            eff_from = rule.get("effective_from")
            eff_to = rule.get("effective_to")
            if eff_from and str(duty_date) < str(eff_from):
                continue
            if eff_to and str(duty_date) > str(eff_to):
                continue

        r_entity = rule.get("entity_id") or None
        r_city = rule.get("city_id") or rule.get("branch_id") or None

        if entity_id and r_entity == entity_id and city_id and r_city == city_id:
            matched_by_tier[1].append(rule)
        elif entity_id and r_entity == entity_id and r_city is None:
            matched_by_tier[2].append(rule)
        elif r_entity is None and city_id and r_city == city_id:
            matched_by_tier[3].append(rule)
        elif r_entity is None and r_city is None:
            matched_by_tier[4].append(rule)

    winning_tier = next((tier for tier in (1, 2, 3, 4) if matched_by_tier[tier]), None)
    if winning_tier is None:
        raise FareError(
            f"No matching rate rule found across any fallback tier for vehicle_group={billed_vg}, mode={normalised_mode}",
            "rate_card_not_found",
        )

    tier_rules = sorted(
        matched_by_tier[winning_tier],
        key=lambda r: (int(r.get("package_minutes") or 0), float(r.get("included_km") or 0)),
    )

    # Select the booked slab within the winning tier
    booked_rule = None
    if booked_rule_id:
        booked_rule = next(
            (r for r in tier_rules if str(r.get("id") or r.get("rule_id")) == str(booked_rule_id)),
            None,
        )
    if not booked_rule and booked_package_name:
        target_name = booked_package_name.strip().lower()
        booked_rule = next(
            (r for r in tier_rules if str(r.get("package_name") or "").strip().lower() == target_name),
            None,
        )
    if not booked_rule:
        booked_rule = tier_rules[0]

    resolved_profile = dict(booked_rule)
    resolved_profile["candidate_slabs"] = tier_rules
    resolved_profile["resolution_trace"] = {
        "ledger_side": side,
        "resolution_tier": TIER_LABELS[winning_tier],
        "tier_priority": winning_tier,
        "requested_vehicle_group": requested_vehicle_group,
        "allotted_vehicle_group": allotted_vehicle_group or requested_vehicle_group,
        "billed_vehicle_group": billed_vg,
        "candidate_slab_count": len(tier_rules),
    }
    return resolved_profile


# Parameterized SQL query compatible with both SQLite and PostgreSQL/Supabase
WATERFALL_RATE_RESOLUTION_SQL = """
WITH ranked_rules AS (
    SELECT
        rc.id AS rate_card_id,
        rc.name AS rate_card_name,
        rc.currency,
        rc.slab_switch_mode,
        tr.*,
        CASE
            WHEN rc.entity_id = :entity_id AND rc.city_id = :city_id THEN 1
            WHEN rc.entity_id = :entity_id AND rc.city_id IS NULL THEN 2
            WHEN rc.entity_id IS NULL AND rc.city_id = :city_id THEN 3
            WHEN rc.entity_id IS NULL AND rc.city_id IS NULL THEN 4
        END AS tier_priority
    FROM rate_cards rc
    INNER JOIN tariff_rules tr ON tr.rate_card_id = rc.id
    WHERE rc.tenant_id = :tenant_id
      AND rc.entity_type IN (:entity_type, 'DEFAULT')
      AND (rc.entity_id = :entity_id OR rc.entity_id IS NULL)
      AND (rc.city_id = :city_id OR rc.city_id IS NULL)
      AND rc.is_active = 1
      AND rc.effective_from <= :duty_date
      AND (rc.effective_to IS NULL OR rc.effective_to >= :duty_date)
      AND tr.vehicle_group_id = :billed_vehicle_group_id
      AND tr.duty_type = :fare_mode
)
SELECT *
FROM ranked_rules
WHERE tier_priority = (SELECT MIN(tier_priority) FROM ranked_rules)
ORDER BY package_minutes ASC, included_km ASC;
"""


__all__ = [
    "TIER_LABELS",
    "WATERFALL_RATE_RESOLUTION_SQL",
    "resolve_billed_vehicle_group",
    "resolve_rate_card_context",
]
