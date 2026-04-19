"""
USGS Water Data service.

Provides nearby stream gage context and simple flood-adjacent trend signals for
decision support. Failures degrade to an empty result.
"""
from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

import httpx


USGS_IV_URL = "https://waterservices.usgs.gov/nwis/iv/"


def _distance_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_mi = 3958.8
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    lat1_rad = radians(lat1)
    lat2_rad = radians(lat2)
    a = sin(d_lat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(d_lon / 2) ** 2
    return 2 * radius_mi * asin(sqrt(a))


def _trend(values: list[float]) -> str:
    if len(values) < 2:
        return "unknown"
    delta = values[-1] - values[0]
    if delta > 0.3:
        return "rising"
    if delta < -0.3:
        return "falling"
    return "steady"


def _water_risk(gage: dict | None) -> dict:
    if not gage:
        return {
            "severity": "none",
            "signals": [],
            "replan_triggers": [],
        }

    signals = []
    replan_triggers = []
    severity = "low"
    if gage.get("trend") == "rising":
        severity = "moderate"
        signals.append(f"USGS gage {gage['site_name']} is rising")
        replan_triggers.append("Rising USGS water levels may degrade access routes")
    if isinstance(gage.get("gage_height_ft"), (int, float)) and gage["gage_height_ft"] >= 8:
        severity = "high"
        signals.append(f"Gage height elevated at {gage['gage_height_ft']} ft")
        replan_triggers.append("Elevated gage height near incident corridor — reassess water rescue risk")
    if isinstance(gage.get("streamflow_cfs"), (int, float)) and gage["streamflow_cfs"] >= 2000:
        severity = "high"
        signals.append(f"Streamflow elevated at {gage['streamflow_cfs']} cfs")
        replan_triggers.append("High streamflow may worsen flooding and corridor access")

    return {
        "severity": severity,
        "signals": signals[:3],
        "replan_triggers": replan_triggers[:3],
    }


async def get_water_context(lat: float, lon: float) -> dict:
    bbox = f"{lon - 0.2:.4f},{lat - 0.2:.4f},{lon + 0.2:.4f},{lat + 0.2:.4f}"
    params = {
        "format": "json",
        "bBox": bbox,
        "parameterCd": "00060,00065",
        "siteStatus": "active",
        "period": "P2D",
    }
    try:
        async with httpx.AsyncClient(timeout=6, headers={"User-Agent": "Unilert/1.0"}) as client:
            response = await client.get(USGS_IV_URL, params=params)
            if response.status_code != 200:
                raise RuntimeError(f"USGS status {response.status_code}")
        time_series = response.json().get("value", {}).get("timeSeries", [])
    except Exception:
        return {
            "available": False,
            "nearest_gage": None,
            "risk": {"severity": "none", "signals": [], "replan_triggers": []},
        }

    gages: dict[str, dict] = {}
    for series in time_series:
        source = series.get("sourceInfo") or {}
        site_code = ((source.get("siteCode") or [{}])[0]).get("value")
        coords = (((source.get("geoLocation") or {}).get("geogLocation")) or {})
        site_lat = coords.get("latitude")
        site_lon = coords.get("longitude")
        if not site_code or site_lat is None or site_lon is None:
            continue
        entry = gages.setdefault(
            site_code,
            {
                "site_code": site_code,
                "site_name": source.get("siteName", site_code),
                "lat": site_lat,
                "lon": site_lon,
                "distance_mi": round(_distance_mi(lat, lon, site_lat, site_lon), 1),
                "streamflow_cfs": None,
                "gage_height_ft": None,
                "trend": "unknown",
            },
        )
        variable_code = (((series.get("variable") or {}).get("variableCode")) or [{}])[0].get("value")
        values = []
        for block in series.get("values", []):
            for value in block.get("value", []):
                try:
                    values.append(float(value.get("value")))
                except (TypeError, ValueError):
                    continue
        if variable_code == "00060" and values:
            entry["streamflow_cfs"] = round(values[-1], 1)
            entry["trend"] = _trend(values)
        if variable_code == "00065" and values:
            entry["gage_height_ft"] = round(values[-1], 2)
            entry["trend"] = _trend(values)

    nearest = None
    if gages:
        nearest = sorted(gages.values(), key=lambda item: item["distance_mi"])[0]

    return {
        "available": True,
        "nearest_gage": nearest,
        "risk": _water_risk(nearest),
    }
