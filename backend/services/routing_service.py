"""
Routing service with a container-friendly OSRM interface.

Primary path: self-hosted OSRM-compatible HTTP API.
Fallback: ArcGIS route service when configured.
"""
from __future__ import annotations

import os

import httpx

from services.mapping_service import get_routes as get_arcgis_routes


EOC_ORIGIN_LAT = float(os.getenv("EOC_ORIGIN_LAT", "40.3461"))
EOC_ORIGIN_LON = float(os.getenv("EOC_ORIGIN_LON", "-74.6580"))


def _provider() -> str:
    return os.getenv("ROUTING_PROVIDER", "osrm").strip().lower() or "osrm"


def _osrm_url() -> str:
    return os.getenv("OSRM_BASE_URL", "http://osrm:5000").rstrip("/")


def _step_text(step: dict) -> str:
    maneuver = (step.get("maneuver") or {}).get("type", "continue")
    name = step.get("name") or "unnamed road"
    return f"{maneuver} onto {name}".replace("_", " ")


def _route_summary(route: dict) -> tuple[float | None, float | None, list[str]]:
    duration_min = route.get("duration")
    distance_m = route.get("distance")
    steps: list[str] = []
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            text = _step_text(step)
            if text and text not in steps:
                steps.append(text)
            if len(steps) >= 6:
                break
        if len(steps) >= 6:
            break
    return (
        round(duration_min / 60, 1) if isinstance(duration_min, (int, float)) else None,
        round(distance_m / 1609.34, 2) if isinstance(distance_m, (int, float)) else None,
        steps[:6],
    )


async def _get_osrm_routes(destination_lon: float, destination_lat: float) -> dict | None:
    coords = f"{EOC_ORIGIN_LON},{EOC_ORIGIN_LAT};{destination_lon},{destination_lat}"
    url = f"{_osrm_url()}/route/v1/driving/{coords}"
    params = {
        "alternatives": "true",
        "overview": "false",
        "steps": "true",
        "annotations": "false",
    }
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            response = await client.get(url, params=params)
            if response.status_code != 200:
                return None
        payload = response.json()
        routes = payload.get("routes") or []
        if not routes:
            return None
        primary = routes[0]
        primary_duration, primary_distance, primary_steps = _route_summary(primary)
        alternate_steps: list[str] = []
        alternate_duration = None
        if len(routes) > 1:
            alternate_duration, _, alternate_steps = _route_summary(routes[1])
        return {
            "primary_route_steps": primary_steps,
            "alternate_route_steps": alternate_steps,
            "primary_duration_min": primary_duration,
            "primary_distance_mi": primary_distance,
            "alternate_duration_min": alternate_duration,
            "origin": "Regional EOC",
            "provider": "osrm",
            "available": True,
        }
    except Exception:
        return None


async def get_route_context(destination_lon: float, destination_lat: float) -> dict:
    provider = _provider()
    route_data = None

    if provider == "osrm":
        route_data = await _get_osrm_routes(destination_lon, destination_lat)

    if route_data is None:
        arcgis = await get_arcgis_routes(destination_lon, destination_lat)
        if arcgis:
            route_data = {
                **arcgis,
                "alternate_route_steps": [],
                "alternate_duration_min": None,
                "provider": "arcgis",
                "available": True,
            }

    if route_data is None:
        route_data = {
            "primary_route_steps": [],
            "alternate_route_steps": [],
            "primary_duration_min": None,
            "primary_distance_mi": None,
            "alternate_duration_min": None,
            "origin": "Regional EOC",
            "provider": provider,
            "available": False,
        }

    return route_data
