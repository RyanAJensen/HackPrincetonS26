"""
OpenFEMA service — disaster declaration context for New Jersey.

Fetches recent FEMA disaster declarations for NJ to provide historical hazard
grounding for the Situation Unit's incident brief. No API key required.
"""
from __future__ import annotations
import httpx
from typing import Optional

FEMA_API = "https://www.fema.gov/api/open/v2/disasterDeclarationsSummaries"


async def get_nj_hazard_context() -> dict:
    """
    Return recent NJ FEMA disaster declarations relevant to campus incidents.
    Focus on declared disaster types that match known campus risk categories.
    """
    try:
        async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "Unilert/1.0"}) as client:
            r = await client.get(FEMA_API, params={
                "state": "NJ",
                "limit": 10,
                "sort": "-declarationDate",
                "$select": "disasterNumber,declarationTitle,incidentType,declarationDate,incidentBeginDate,declaredCountyArea",
                "$filter": "state eq 'NJ'",
            })
            if r.status_code != 200:
                return {"available": False, "declarations": [], "context_notes": []}

        records = r.json().get("DisasterDeclarationsSummaries", [])
        declarations = []
        for rec in records[:5]:
            declarations.append({
                "disaster_number": rec.get("disasterNumber"),
                "title": rec.get("declarationTitle", ""),
                "type": rec.get("incidentType", ""),
                "date": rec.get("declarationDate", "")[:10],
                "counties": rec.get("declaredCountyArea", ""),
            })

        # Derive context notes for the Situation Unit
        incident_types = [d["type"] for d in declarations]
        context_notes = []
        if "Flood" in incident_types or "Severe Storm" in incident_types:
            context_notes.append("NJ has recent FEMA flood/storm declarations — drainage and access route flooding is a credible risk")
        if "Severe Ice Storm" in incident_types or "Snow" in incident_types:
            context_notes.append("NJ has recent FEMA winter storm declarations — ice and snow impacting roads is precedented")
        if not context_notes:
            context_notes.append(f"Most recent NJ FEMA declaration: {declarations[0]['title']} ({declarations[0]['date']})" if declarations else "No recent NJ declarations found")

        return {
            "available": True,
            "declarations": declarations,
            "context_notes": context_notes,
        }
    except Exception:
        return {"available": False, "declarations": [], "context_notes": []}
