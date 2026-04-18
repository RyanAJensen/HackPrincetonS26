"""
ArcGIS service — geocoding and routing.

Geocodes incident locations to coordinates, then computes primary and alternate
access routes from the regional EOC. Route data feeds directly into the
Operations Planner so action items reference real road conditions.

Fails gracefully: returns None fields on any network or API error.
"""
from __future__ import annotations
import asyncio
import os
import httpx
from typing import Optional

# Regional Emergency Operations Center as the default origin for all routes
EOC_ORIGIN = "-74.6580,40.3461"  # lon,lat for ArcGIS

GEOCODE_URL = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
ROUTE_URL   = "https://route.arcgis.com/arcgis/rest/services/World/Route/NAServer/Route_World/solve"


def _api_key() -> Optional[str]:
    return os.getenv("ARC_GIS_API_KEY")


async def geocode(location: str) -> Optional[dict]:
    """Return {lat, lon, display_address, score} or None."""
    key = _api_key()
    if not key:
        return None
    try:
        query = location
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(GEOCODE_URL, params={
                "f": "json",
                "singleLine": query,
                "maxLocations": 1,
                "token": key,
            })
        data = r.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return None
        best = candidates[0]
        loc = best.get("location", {})
        return {
            "lat": loc.get("y"),
            "lon": loc.get("x"),
            "display_address": best.get("address", location),
            "score": best.get("score", 0),
        }
    except Exception:
        return None


async def get_routes(destination_lon: float, destination_lat: float) -> Optional[dict]:
    """
    Compute primary and alternate routes from campus security HQ to incident.
    Returns {primary_route, alternate_route, primary_duration_min, primary_distance_mi}.
    """
    key = _api_key()
    if not key:
        return None
    try:
        stops = f"{EOC_ORIGIN};{destination_lon},{destination_lat}"
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(ROUTE_URL, params={
                "f": "json",
                "token": key,
                "stops": stops,
                "returnDirections": "true",
                "directionsLanguage": "en",
                "findBestSequence": "false",
                "preserveFirstStop": "true",
                "preserveLastStop": "true",
                "returnRoutes": "true",
                "outputLines": "esriNAOutputLineTrueShapeWithMeasure",
            })
        data = r.json()

        routes = data.get("routes", {}).get("features", [])
        directions = data.get("directions", [{}])
        if not routes:
            return None

        route_attrs = routes[0].get("attributes", {})
        total_minutes = route_attrs.get("Total_TravelTime", 0)
        total_miles = route_attrs.get("Total_Miles", 0)

        # Extract step-by-step directions
        steps = []
        for feature in directions[0].get("features", []):
            text = feature.get("attributes", {}).get("text", "")
            if text and not text.lower().startswith("head") or len(steps) < 6:
                steps.append(text)
        steps = steps[:6]  # keep concise

        # Extract route geometry (line) for potential map display
        geometry = routes[0].get("geometry")

        return {
            "primary_route_steps": steps,
            "primary_duration_min": round(total_minutes, 1),
            "primary_distance_mi": round(total_miles, 2),
            "route_geometry": geometry,
            "origin": "Regional EOC",
        }
    except Exception:
        return None


# Hardcoded nearby hospitals for Princeton NJ area (fallback when ArcGIS Places unavailable)
_NJ_HOSPITALS = [
    {"name": "Penn Medicine Princeton Medical Center", "address": "One Plainsboro Rd, Plainsboro, NJ", "distance_mi": 4.2, "trauma_level": "II"},
    {"name": "Robert Wood Johnson University Hospital", "address": "1 Robert Wood Johnson Pl, New Brunswick, NJ", "distance_mi": 14.5, "trauma_level": "I"},
    {"name": "Capital Health Regional Medical Center", "address": "750 Brunswick Ave, Trenton, NJ", "distance_mi": 12.8, "trauma_level": "II"},
    {"name": "University Medical Center of Princeton", "address": "253 Witherspoon St, Princeton, NJ", "distance_mi": 1.1, "trauma_level": None},
]

PLACES_URL = "https://places.arcgis.com/arcgis/rest/services/WorldPlaces/PlacesServer/findPlacesNearPoint"


async def get_nearby_hospitals(lat: float, lon: float, radius_km: float = 20) -> list[dict]:
    """
    Find nearby hospitals via ArcGIS Places API. Falls back to hardcoded NJ hospitals.
    Returns list of {name, distance_mi, trauma_level}.
    """
    key = _api_key()
    if key:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get(PLACES_URL, params={
                    "f": "json",
                    "token": key,
                    "x": lon,
                    "y": lat,
                    "radius": int(radius_km * 1000),
                    "categoryIds": "15000",  # Health & Medicine
                    "pageSize": 5,
                })
            data = r.json()
            places = data.get("results", [])
            hospitals = []
            for p in places:
                attrs = p.get("attributes", {})
                name = attrs.get("PlaceName") or attrs.get("name", "")
                dist_m = p.get("distance", 0)
                if name and ("hospital" in name.lower() or "medical" in name.lower() or "health" in name.lower()):
                    hospitals.append({
                        "name": name,
                        "distance_mi": round(dist_m / 1609.34, 1),
                        "trauma_level": None,
                    })
            if hospitals:
                return hospitals[:4]
        except Exception:
            pass
    return _NJ_HOSPITALS


async def get_location_context(location: str) -> dict:
    """
    Full enrichment: geocode, route, and nearby hospitals.
    """
    geo = await geocode(location)
    routing = None
    hospitals = None
    if geo and geo.get("lat") and geo.get("lon"):
        routing, hospitals = await asyncio.gather(
            get_routes(geo["lon"], geo["lat"]),
            get_nearby_hospitals(geo["lat"], geo["lon"]),
            return_exceptions=True,
        )
        if isinstance(routing, Exception):
            routing = None
        if isinstance(hospitals, Exception):
            hospitals = _NJ_HOSPITALS
    else:
        hospitals = _NJ_HOSPITALS

    return {
        "geocode": geo,
        "routing": routing,
        "hospitals": hospitals,
        "available": bool(geo),
    }
