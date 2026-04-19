"""
Static hospital metadata service.

Represents a CMS-directory-style metadata layer: locations, facility types,
trauma metadata, and capabilities. This is not a live ED-capacity feed.
"""
from __future__ import annotations

from math import asin, cos, radians, sin, sqrt


HOSPITAL_DIRECTORY: list[dict] = [
    {
        "name": "Penn Medicine Princeton Medical Center",
        "address": "One Plainsboro Rd, Plainsboro, NJ",
        "lat": 40.3336,
        "lon": -74.6148,
        "facility_type": "Acute Care Hospital",
        "trauma_level": "II",
        "capabilities": ["trauma", "adult_ed", "critical_care"],
        "source": "cms_directory_stub",
    },
    {
        "name": "Robert Wood Johnson University Hospital",
        "address": "1 Robert Wood Johnson Pl, New Brunswick, NJ",
        "lat": 40.4894,
        "lon": -74.4518,
        "facility_type": "Academic Medical Center",
        "trauma_level": "I",
        "capabilities": ["trauma", "adult_ed", "critical_care", "specialty_surgery"],
        "source": "cms_directory_stub",
    },
    {
        "name": "Capital Health Regional Medical Center",
        "address": "750 Brunswick Ave, Trenton, NJ",
        "lat": 40.2304,
        "lon": -74.7521,
        "facility_type": "Regional Medical Center",
        "trauma_level": "II",
        "capabilities": ["trauma", "adult_ed", "cardiac"],
        "source": "cms_directory_stub",
    },
    {
        "name": "Saint Peter's University Hospital",
        "address": "254 Easton Ave, New Brunswick, NJ",
        "lat": 40.4978,
        "lon": -74.4476,
        "facility_type": "Acute Care Hospital",
        "trauma_level": None,
        "capabilities": ["adult_ed", "pediatric", "critical_care"],
        "source": "cms_directory_stub",
    },
    {
        "name": "Capital Health Hopewell",
        "address": "One Capital Way, Pennington, NJ",
        "lat": 40.2802,
        "lon": -74.7864,
        "facility_type": "Community Hospital",
        "trauma_level": None,
        "capabilities": ["adult_ed", "imaging"],
        "source": "cms_directory_stub",
    },
]


def _distance_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # Haversine distance in miles.
    radius_mi = 3958.8
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    lat1_rad = radians(lat1)
    lat2_rad = radians(lat2)
    a = sin(d_lat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(d_lon / 2) ** 2
    return 2 * radius_mi * asin(sqrt(a))


async def get_hospital_directory_context(lat: float, lon: float, *, limit: int = 5) -> dict:
    hospitals = []
    for item in HOSPITAL_DIRECTORY:
        distance = _distance_mi(lat, lon, item["lat"], item["lon"])
        enriched = {
            "name": item["name"],
            "address": item["address"],
            "distance_mi": round(distance, 1),
            "trauma_level": item["trauma_level"],
            "facility_type": item["facility_type"],
            "capabilities": item["capabilities"],
            "lat": item["lat"],
            "lon": item["lon"],
        }
        hospitals.append(enriched)
    hospitals.sort(key=lambda item: item["distance_mi"])
    return {
        "available": True,
        "source": "cms_directory_stub",
        "hospitals": hospitals[:limit],
    }
