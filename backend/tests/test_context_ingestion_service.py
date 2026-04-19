from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.context_ingestion_service import gather_external_context


class ContextIngestionTests(unittest.IsolatedAsyncioTestCase):
    async def test_gather_external_context_combines_service_boundaries(self) -> None:
        with patch(
            "services.context_ingestion_service.geocode",
            AsyncMock(return_value={"lat": 40.35, "lon": -74.66, "display_address": "Princeton, NJ", "score": 98}),
        ), patch(
            "services.context_ingestion_service.get_nj_hazard_context",
            AsyncMock(return_value={"available": True, "context_notes": ["Recent flood declarations"], "declarations": []}),
        ), patch(
            "services.context_ingestion_service.get_weather_context",
            AsyncMock(return_value={"available": True, "alerts": [], "forecast": None, "risk": {"severity": "moderate"}}),
        ), patch(
            "services.context_ingestion_service.get_water_context",
            AsyncMock(return_value={"available": True, "nearest_gage": {"site_name": "Millstone", "distance_mi": 1.2}, "risk": {"severity": "high", "signals": ["USGS gage rising"], "replan_triggers": ["Reassess water rescue risk"]}}),
        ), patch(
            "services.context_ingestion_service.get_route_context",
            AsyncMock(return_value={"available": True, "provider": "osrm", "primary_route_steps": ["A", "B"], "alternate_route_steps": ["C"], "primary_duration_min": 12, "primary_distance_mi": 4.5}),
        ), patch(
            "services.context_ingestion_service.get_hospital_directory_context",
            AsyncMock(return_value={"available": True, "source": "cms_directory_stub", "hospitals": [{"name": "Penn Medicine Princeton Medical Center", "distance_mi": 4.2, "trauma_level": "II"}]}),
        ):
            context = await gather_external_context("Princeton, NJ")

        self.assertEqual(context["mapping"]["routing_provider"], "osrm")
        self.assertEqual(context["mapping"]["hospital_directory_source"], "cms_directory_stub")
        self.assertEqual(context["mapping"]["hospitals"][0]["name"], "Penn Medicine Princeton Medical Center")
        self.assertEqual(context["water"]["risk"]["severity"], "high")
        self.assertEqual(context["weather"]["risk"]["severity"], "moderate")


if __name__ == "__main__":
    unittest.main()
