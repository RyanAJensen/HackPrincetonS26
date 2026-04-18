"""
External data services. Each service is independently failable —
agents receive whatever data is available and degrade gracefully.
"""
import asyncio
from typing import Optional

from services.mapping_service import get_location_context
from services.weather_service import get_weather_context
from services.fema_service import get_nj_hazard_context

# Princeton, NJ fallback coordinates when geocoding fails
PRINCETON_LAT = 40.3573
PRINCETON_LON = -74.6672


async def gather_external_context(location: str) -> dict:
    """
    Run all three services concurrently. Returns a unified enrichment dict
    consumed by the agent pipeline. Any service failure returns empty data,
    never raises.
    """
    mapping_task = get_location_context(location)
    fema_task = get_nj_hazard_context()

    mapping, fema = await asyncio.gather(mapping_task, fema_task, return_exceptions=True)

    if isinstance(mapping, Exception):
        mapping = {"available": False, "geocode": None, "routing": None}
    if isinstance(fema, Exception):
        fema = {"available": False, "declarations": [], "context_notes": []}

    # Use geocoded coordinates for weather, fall back to Princeton center
    geo = (mapping or {}).get("geocode") or {}
    lat = geo.get("lat") or PRINCETON_LAT
    lon = geo.get("lon") or PRINCETON_LON

    weather = await get_weather_context(lat, lon)
    if isinstance(weather, Exception):
        weather = {"available": False, "alerts": [], "forecast": None, "risk": {}}

    return {
        "mapping": mapping,
        "weather": weather,
        "fema": fema,
        "coordinates": {"lat": lat, "lon": lon},
    }
