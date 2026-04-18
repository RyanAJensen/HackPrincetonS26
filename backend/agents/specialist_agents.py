"""
The four specialist agents. Each is a plain async function that takes an AgentRun
(with input_snapshot populated) and returns a dict artifact.
"""
from __future__ import annotations
import json
from models.agent import AgentRun
from agents.llm import call_llm
from agents.prompts import (
    INCIDENT_PARSER_PROMPT,
    RISK_ASSESSOR_PROMPT,
    ACTION_PLANNER_PROMPT,
    COMMUNICATIONS_PROMPT,
)


def _fmt_resources(resources: list) -> str:
    if not resources:
        return "None specified"
    return ", ".join(f"{r.get('name')} ({r.get('role')})" for r in resources)


def _fmt_geocode(geo: dict | None) -> str:
    if not geo:
        return "Geocoding unavailable — using reported location"
    return (
        f"{geo.get('display_address', 'Unknown')} "
        f"(lat {geo.get('lat', '?'):.4f}, lon {geo.get('lon', '?'):.4f}, "
        f"confidence score {geo.get('score', 0):.0f}/100)"
    )


def _fmt_fema(fema: dict | None) -> str:
    if not fema or not fema.get("available"):
        return "FEMA data unavailable"
    notes = fema.get("context_notes", [])
    decls = fema.get("declarations", [])[:2]
    parts = notes[:2]
    if decls:
        parts.append(f"Recent NJ declarations: " + "; ".join(d["title"] for d in decls))
    return " | ".join(parts) if parts else "No relevant FEMA context"


def _fmt_alerts(alerts: list) -> str:
    if not alerts:
        return "None — no active NWS alerts for this area"
    return "; ".join(f"{a['event']} ({a['severity']}): {a['headline'][:80]}" for a in alerts[:3])


def _fmt_forecast(forecast: dict | None) -> str:
    if not forecast:
        return "Forecast unavailable"
    parts = []
    if forecast.get("temperature_f"):
        parts.append(f"{forecast['temperature_f']}°F")
    if forecast.get("wind_speed"):
        parts.append(f"Wind {forecast['wind_speed']} {forecast.get('wind_direction', '')}")
    if forecast.get("short_forecast"):
        parts.append(forecast["short_forecast"])
    return ", ".join(parts) or "No forecast data"


def _fmt_route(routing: dict | None) -> tuple[str, str, str]:
    """Returns (primary_route, route_duration, alternate_note)."""
    if not routing:
        return "Route data unavailable", "Unknown", "No alternate route data"
    steps = routing.get("primary_route_steps", [])
    route_str = " → ".join(steps[:4]) if steps else "Route unavailable"
    duration = f"{routing.get('primary_duration_min', '?')} min ({routing.get('primary_distance_mi', '?')} mi)"
    return route_str, duration, "Request alternate route if primary becomes impassable"


def _fmt_hospitals(hospitals: list | None) -> str:
    if not hospitals:
        return "No hospital data available"
    parts = []
    for h in hospitals[:4]:
        trauma = f" [Trauma {h['trauma_level']}]" if h.get("trauma_level") else ""
        dist = f" — {h['distance_mi']} mi" if h.get("distance_mi") is not None else ""
        parts.append(f"{h['name']}{trauma}{dist}")
    return "; ".join(parts)


async def run_incident_parser(run: AgentRun) -> dict:
    inp = run.input_snapshot
    ext = inp.get("external_context", {})
    mapping = ext.get("mapping", {})
    fema = ext.get("fema", {})

    prompt = INCIDENT_PARSER_PROMPT.format(
        incident_type=inp["incident_type"],
        location=inp["location"],
        severity_hint=inp.get("severity_hint") or "Not specified",
        resources=_fmt_resources(inp.get("resources", [])),
        report=inp["report"],
        geocode_summary=_fmt_geocode(mapping.get("geocode")),
        fema_context=_fmt_fema(fema),
    )
    run.log_entries.append("Calling LLM: situation_unit (incident_parser) with geocode + FEMA context")
    return await call_llm(prompt)


async def run_risk_assessor(run: AgentRun) -> dict:
    inp = run.input_snapshot
    ext = inp.get("external_context", {})
    weather = ext.get("weather", {})
    alerts = weather.get("alerts", [])
    forecast = weather.get("forecast")
    risk = weather.get("risk", {})

    prompt = RISK_ASSESSOR_PROMPT.format(
        parsed_data=json.dumps(inp["parsed_data"], indent=2),
        resources=_fmt_resources(inp.get("resources", [])),
        alert_count=len(alerts),
        weather_alerts=_fmt_alerts(alerts),
        forecast_summary=_fmt_forecast(forecast),
        weather_risk_level=risk.get("severity", "none"),
        weather_escalation="; ".join(risk.get("escalation_triggers", ["None identified"])),
    )
    run.log_entries.append(f"Calling LLM: threat_analysis_unit with {len(alerts)} active NWS alert(s)")
    return await call_llm(prompt)


async def run_action_planner(run: AgentRun) -> dict:
    inp = run.input_snapshot
    ext = inp.get("external_context", {})
    mapping = ext.get("mapping", {})
    routing = mapping.get("routing")
    hospitals = mapping.get("hospitals")

    primary_route, route_duration, alternate_note = _fmt_route(routing)

    prompt = ACTION_PLANNER_PROMPT.format(
        parsed_data=json.dumps(inp["parsed_data"], indent=2),
        risk_data=json.dumps(inp["risk_data"], indent=2),
        resources=_fmt_resources(inp.get("resources", [])),
        location=inp["location"],
        primary_route=primary_route,
        route_duration=route_duration,
        alternate_route_note=alternate_note,
        route_notes="Route computed from Regional EOC to incident location via ArcGIS" if routing else "ArcGIS routing unavailable",
        hospital_context=_fmt_hospitals(hospitals),
    )
    run.log_entries.append("Calling LLM: operations_planner with ArcGIS routing + hospital context")
    return await call_llm(prompt)


def _fmt_triage(triage: list | None) -> str:
    if not triage:
        return "No triage data available"
    parts = []
    for t in triage:
        if isinstance(t, dict):
            parts.append(f"P{t.get('priority', '?')} {t.get('label', '')}: {t.get('estimated_count', 0)} patients — {t.get('required_action', '')}")
    return "; ".join(parts) if parts else "No triage data"


async def run_communications_agent(run: AgentRun) -> dict:
    inp = run.input_snapshot
    ext = inp.get("external_context", {})
    weather = ext.get("weather", {})
    mapping = ext.get("mapping", {})
    alerts = weather.get("alerts", [])
    routing = mapping.get("routing")

    alerts_summary = _fmt_alerts(alerts) if alerts else "No active weather alerts"
    conditions_summary = _fmt_forecast(weather.get("forecast"))
    route_summary = f"Primary route: {routing.get('primary_route_steps', ['Unknown'])[0] if routing and routing.get('primary_route_steps') else 'Not computed'}" if routing else "Route data unavailable"

    prompt = COMMUNICATIONS_PROMPT.format(
        incident_summary=inp["incident_summary"],
        severity=inp["severity"],
        location=inp["location"],
        priorities=json.dumps(inp["priorities"]),
        missing_info=json.dumps(inp.get("missing_info", [])),
        triage_summary=_fmt_triage(inp.get("triage_priorities")),
        weather_alerts_summary=alerts_summary,
        conditions_summary=conditions_summary,
        route_summary=route_summary,
    )
    run.log_entries.append("Calling LLM: communications_officer with triage + weather + route context")
    return await call_llm(prompt)
