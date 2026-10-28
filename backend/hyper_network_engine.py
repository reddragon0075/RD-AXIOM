"""Axiom Mobility (Fleetline) Hyper-Network Engine Service Layer.

Provides direct access to:
1. Anti-Poaching Double-Blind Masking & Brand Injection
2. Timed Multi-Tier Waterfall State Machine
3. Wallet Escrow Hold & T+0 Instant Factoring Clearinghouse
4. Empty-Leg Return Deadhead Matchmaker
5. EV SoC Range Verification & Zero-Knowledge Compliance Seal Issuance
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add fleetline-mvp to path if needed
ROOT = Path(__file__).resolve().parent.parent
MVP_PATH = ROOT / "fleetline-mvp"
if str(MVP_PATH) not in sys.path:
    sys.path.insert(0, str(MVP_PATH))

from backend_hyper_network import (
    initialize_hyper_network_schema,
    post_duty_to_exchange,
    get_masked_exchange_feed,
    claim_network_duty,
    boost_surge_payout,
    allot_and_verify_compliance_passport,
    get_zk_compliance_proof,
    instant_t0_factoring_cashout,
    create_empty_leg_listing,
    match_empty_leg_corridors,
    get_demand_swarm_radar,
    handle_hyper_network,
)

__all__ = [
    "initialize_hyper_network_schema",
    "post_duty_to_exchange",
    "get_masked_exchange_feed",
    "claim_network_duty",
    "boost_surge_payout",
    "allot_and_verify_compliance_passport",
    "get_zk_compliance_proof",
    "instant_t0_factoring_cashout",
    "create_empty_leg_listing",
    "match_empty_leg_corridors",
    "get_demand_swarm_radar",
    "handle_hyper_network",
]
