"""
Context ingestion service.

This module is the explicit boundary between the orchestrator and external
data providers. It is designed to map cleanly to a separate container/service
later without changing the decision engine contract.
"""
from __future__ import annotations

import asyncio

from services.fema_service import get_nj_hazard_context
from services.hospital_directory_service import get_hospital_directory_context
from services.mapping_service import geocode
from services.routing_service import EOC_ORIGIN_LAT, EOC_ORIGIN_LON, get_route_context
from services.usgs_service import get_water_context
from services.weather_service import get_weather_context

# Princeton, NJ fallback coordinates when geocoding fails
PRINCETON_LAT = 40.3573
PRINCETON_LON = -74.6672


async def gather_external_context(location: str) -> dict:
    geocode_task = geocode(location)
    fema_task = get_nj_hazard_context()

    geo, fema = await asyncio.gather(geocode_task, fema_task, return_exceptions=True)
    if isinstance(geo, Exception):
        geo = None
    if isinstance(fema, Exception):
        fema = {"available": False, "declarations": [], "context_notes": []}

    lat = (geo or {}).get("lat") or PRINCETON_LAT
    lon = (geo or {}).get("lon") or PRINCETON_LON

    weather_task = get_weather_context(lat, lon)
    water_task = get_water_context(lat, lon)
    routing_task = get_route_context(lon, lat)
    hospitals_task = get_hospital_directory_context(lat, lon)

    weather, water, routing, hospitals = await asyncio.gather(
        weather_task,
        water_task,
        routing_task,
        hospitals_task,
        return_exceptions=True,
    )

    if isinstance(weather, Exception):
        weather = {"available": False, "alerts": [], "forecast": None, "risk": {}}
    if isinstance(water, Exception):
        water = {"available": False, "nearest_gage": None, "risk": {"severity": "none", "signals": [], "replan_triggers": []}}
    if isinstance(routing, Exception):
        routing = {"available": False, "provider": "unavailable", "primary_route_steps": [], "alternate_route_steps": []}
    if isinstance(hospitals, Exception):
        hospitals = {"available": False, "source": "unavailable", "hospitals": []}

    return {
        "mapping": {
            "available": bool(geo),
            "geocode": geo,
            "routing": routing,
            "hospitals": hospitals.get("hospitals", []),
            "routing_provider": routing.get("provider"),
            "hospital_directory_source": hospitals.get("source"),
            "origin": {"lat": EOC_ORIGIN_LAT, "lon": EOC_ORIGIN_LON, "label": "Regional EOC"},
        },
        "weather": weather,
        "water": water,
        "fema": fema,
        "coordinates": {"lat": lat, "lon": lon},
    }


async def gather_immediate_context(location: str) -> dict:
    async def _timed(coro, default, timeout_s: float):
        try:
            return await asyncio.wait_for(coro, timeout=timeout_s)
        except Exception:
            return default

    geo = await _timed(geocode(location), None, 1.0)
    lat = (geo or {}).get("lat") or PRINCETON_LAT
    lon = (geo or {}).get("lon") or PRINCETON_LON

    routing_task = _timed(
        get_route_context(lon, lat),
        {"available": False, "provider": "unavailable", "primary_route_steps": [], "alternate_route_steps": []},
        1.5,
    )
    hospitals_task = _timed(
        get_hospital_directory_context(lat, lon),
        {"available": True, "source": "cms_directory_stub", "hospitals": []},
        1.5,
    )
    routing, hospitals = await asyncio.gather(routing_task, hospitals_task)

    return {
        "mapping": {
            "available": bool(geo),
            "geocode": geo,
            "routing": routing,
            "hospitals": hospitals.get("hospitals", []),
            "routing_provider": routing.get("provider"),
            "hospital_directory_source": hospitals.get("source"),
            "origin": {"lat": EOC_ORIGIN_LAT, "lon": EOC_ORIGIN_LON, "label": "Regional EOC"},
        },
        "weather": {"available": False, "alerts": [], "forecast": None, "risk": {}},
        "water": {"available": False, "nearest_gage": None, "risk": {"severity": "none", "signals": [], "replan_triggers": []}},
        "fema": {"available": False, "declarations": [], "context_notes": []},
        "coordinates": {"lat": lat, "lon": lon},
    }
