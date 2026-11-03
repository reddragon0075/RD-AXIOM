"""Axiom Mobility (Fleetline) - OpenStreetMap (OSM) & OSRM Spatial Service Layer.

Provides direct access to:
1. Multi-provider OSM Geocoding & Local Landmark Cache (<5ms).
2. OSRM Road Distance & Duration with 1.28x Indian Urban Tortuosity Fallback.
3. 3-Way Distance Fraud Auditor Map-Matching (`snapped_road_km`).
4. Phase 1.5 ETS Multi-Stop Sequence Optimizer with Night-Shift POSH Guard Auto-Swap.
5. In-Memory Thread-Safe TTLCache for Rate Cards & Geocoding Queries.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add fleetline-mvp to sys.path
mvp_dir = Path(__file__).resolve().parent.parent / "fleetline-mvp"
if str(mvp_dir) not in sys.path:
    sys.path.insert(0, str(mvp_dir))

from backend_osm_spatial import (
    initialize_osm_spatial_schema,
    haversine_distance,
    osm_geocode_autocomplete,
    osm_calculate_route,
    osm_map_match_breadcrumbs,
    optimize_ets_route,
    handle_osm_spatial_api,
    TTLCache,
    GLOBAL_OSM_CACHE,
    GLOBAL_RATE_CARD_CACHE,
)

__all__ = [
    "initialize_osm_spatial_schema",
    "haversine_distance",
    "osm_geocode_autocomplete",
    "osm_calculate_route",
    "osm_map_match_breadcrumbs",
    "optimize_ets_route",
    "handle_osm_spatial_api",
    "TTLCache",
    "GLOBAL_OSM_CACHE",
    "GLOBAL_RATE_CARD_CACHE",
]
