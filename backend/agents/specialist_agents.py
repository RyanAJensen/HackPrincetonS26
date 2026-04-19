"""
The four specialist agents. Each is a plain async function that takes an AgentRun
(with input_snapshot populated) and returns a dict artifact.
"""
from __future__ import annotations
import json
import os
from models.agent import AgentRun
from agents.llm import call_llm
from agents.prompts import (
    INCIDENT_PARSER_PROMPT,
    INCIDENT_PARSER_REDUCED_PROMPT,
    RISK_ASSESSOR_PROMPT,
    RISK_ASSESSOR_REDUCED_PROMPT,
    ACTION_PLANNER_PROMPT,
    ACTION_PLANNER_REDUCED_PROMPT,
    COMMUNICATIONS_PROMPT,
    LEAN_PARSER_PROMPT,
    LEAN_RISK_PROMPT,
    LEAN_PLANNER_PROMPT,
    LEAN_COORDINATION_PROMPT,
    LEAN_COMMS_PROMPT,
)
from agents.schemas import (
    ActionPlannerOutput,
    CommunicationsOutput,
    IncidentParserOutput,
    RiskAssessorOutput,
    LeanParserOutput,
    LeanRiskOutput,
    LeanPlannerOutput,
    LeanCoordinationOutput,
    LeanCommunicationsOutput,
)


def _fmt_hospital_capacities(capacities: list) -> str:
    if not capacities:
        return "No hospital capacity data provided"
    parts = []
    for h in capacities[:5]:
        if isinstance(h, dict):
            name = h.get("name", "Unknown")
            beds = h.get("available_beds")
            total = h.get("total_beds")
            status = h.get("status", "unknown")
            specialty = h.get("specialty", "")
            eta = h.get("eta_min")
            dist = h.get("distance_mi")
            bed_str = f"{beds}/{total} beds available" if beds is not None and total else (f"{beds} beds available" if beds is not None else "bed count unknown")
            eta_str = f" — ETA {eta} min" if eta else ""
            dist_str = f" — {dist} mi" if dist else ""
            spec_str = f" [{specialty}]" if specialty else ""
            parts.append(f"{name}{spec_str}: {status.upper()}, {bed_str}{dist_str}{eta_str}")
    return "\n".join(parts)


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


def _fmt_report_facts(report: str) -> str:
    parts = [segment.strip() for segment in report.replace("\n", " ").split(".") if segment.strip()]
    return ". ".join(parts[:6])


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


def _fmt_risk_facts(parsed: dict, *, compact: bool) -> str:
    medical = parsed.get("medical_impact") or {}
    facts = [
        f"Type: {parsed.get('parsed_type') or 'Unknown'}",
        f"Location: {parsed.get('confirmed_location') or 'Unknown'}",
        f"Hazards: {', '.join((parsed.get('key_hazards') or [])[:3]) or 'Unknown'}",
        f"Immediate life safety threat: {'yes' if parsed.get('immediate_life_safety_threat') else 'no'}",
        f"Affected population: {parsed.get('affected_population') or 'Unknown'}",
        (
            "Medical impact: "
            f"injured={medical.get('estimated_injured', 'unknown')}, "
            f"critical={medical.get('critical', 0)}, "
            f"moderate={medical.get('moderate', 0)}, "
            f"minor={medical.get('minor', 0)}"
        ),
    ]
    confirmed = (parsed.get("confirmed_facts") or [])[: (3 if compact else 5)]
    unknowns = (parsed.get("unknowns") or [])[: (2 if compact else 4)]
    if confirmed:
        facts.append("Confirmed facts: " + "; ".join(confirmed))
    if unknowns:
        facts.append("Critical unknowns: " + "; ".join(unknowns))
    return "\n".join(facts)


def _fmt_weather_summary(weather: dict) -> tuple[str, str]:
    alerts = weather.get("alerts", [])
    forecast = weather.get("forecast")
    risk = weather.get("risk", {})
    summary = (
        f"alerts={_fmt_alerts(alerts)} | "
        f"forecast={_fmt_forecast(forecast)} | "
        f"risk={risk.get('severity', 'none')}"
    )
    threats = "; ".join(risk.get("escalation_triggers", [])[:3]) or "None identified"
    return summary, threats


def _fmt_planner_facts(parsed: dict) -> str:
    medical = parsed.get("medical_impact") or {}
    lines = [
        f"Type: {parsed.get('parsed_type') or 'Unknown'}",
        f"Location: {parsed.get('confirmed_location') or 'Unknown'}",
        f"Operational period: {parsed.get('operational_period') or 'Unknown'}",
        f"Hazards: {', '.join((parsed.get('key_hazards') or [])[:3]) or 'Unknown'}",
        f"Affected population: {parsed.get('affected_population') or 'Unknown'}",
        f"Immediate life safety threat: {'yes' if parsed.get('immediate_life_safety_threat') else 'no'}",
        (
            "Medical impact: "
            f"injured={medical.get('estimated_injured', 'unknown')}, "
            f"critical={medical.get('critical', 0)}, "
            f"moderate={medical.get('moderate', 0)}, "
            f"minor={medical.get('minor', 0)}"
        ),
    ]
    confirmed = (parsed.get("confirmed_facts") or [])[:3]
    unknowns = (parsed.get("unknowns") or [])[:3]
    if confirmed:
        lines.append("Confirmed facts: " + "; ".join(confirmed))
    if unknowns:
        lines.append("Critical unknowns: " + "; ".join(unknowns))
    return "\n".join(lines)


def _fmt_planner_risk_context(risk_data: dict | str) -> str:
    if isinstance(risk_data, str):
        return risk_data
    if not risk_data:
        return "Risk assessment unavailable; use parser facts and conservative assumptions."
    fields = [
        f"Severity: {risk_data.get('severity_level', 'unknown')}",
        "Objectives: " + "; ".join((risk_data.get("incident_objectives") or [])[:3]),
        "Primary risks: " + "; ".join((risk_data.get("primary_risks") or [])[:3]),
        "Safety: " + "; ".join((risk_data.get("safety_considerations") or [])[:3]),
        "Replan triggers: " + "; ".join((risk_data.get("replan_triggers") or [])[:3]),
        "Healthcare risks: " + "; ".join((risk_data.get("healthcare_risks") or [])[:3]),
    ]
    return "\n".join(field for field in fields if not field.endswith(": "))


def _fmt_decision_state(decision_state: dict | None, *, compact: bool) -> str:
    if not decision_state:
        return "Decision state unavailable."
    counts = decision_state.get("counts") or {}
    flow = decision_state.get("patient_flow") or {}
    assignments = flow.get("facility_assignments") or []
    risk = decision_state.get("risk") or {}
    assignment_bits = []
    for item in assignments[: (2 if compact else 3)]:
        if not isinstance(item, dict):
            continue
        mix = "/".join(item.get("patient_types") or []) or "mixed"
        assignment_bits.append(f"{item.get('hospital', '?')}={item.get('patients_assigned', 0)} ({mix})")
    lines = [
        (
            f"Patients: total={counts.get('total', flow.get('total_incoming', 0))} "
            f"critical={counts.get('critical', flow.get('critical', 0))} "
            f"moderate={counts.get('moderate', flow.get('moderate', 0))} "
            f"minor={counts.get('minor', flow.get('minor', 0))}"
        ),
        f"Primary route: {decision_state.get('primary_access_route', 'unknown')}",
        f"Alternate route: {decision_state.get('alternate_access_route', 'unknown')}",
        "Allocation: " + ("; ".join(assignment_bits) if assignment_bits else "pending"),
        "Operational priorities: " + "; ".join((decision_state.get("operational_priorities") or [])[:3]),
        "Bottlenecks: " + "; ".join((flow.get("bottlenecks") or risk.get("capacity_bottlenecks") or [])[: (2 if compact else 4)]),
    ]
    if not compact:
        lines.append(
            "Transport constraints: "
            + "; ".join(((decision_state.get("patient_transport") or {}).get("constraints") or [])[:3])
        )
    return "\n".join(line for line in lines if not line.endswith(": "))


def _fmt_computed_risk(risk_data: dict | str, *, compact: bool) -> str:
    if isinstance(risk_data, str):
        return risk_data
    if not risk_data:
        return "Computed risk unavailable."
    fields = [
        f"Severity: {risk_data.get('severity_level', 'unknown')}",
        "Primary risks: " + "; ".join((risk_data.get("primary_risks") or [])[: (2 if compact else 4)]),
        "Capacity bottlenecks: " + "; ".join((risk_data.get("capacity_bottlenecks") or [])[: (2 if compact else 3)]),
        "Transport delays: " + "; ".join((risk_data.get("transport_delays") or [])[:2]),
        "Cascade risks: " + "; ".join((risk_data.get("cascade_risks") or [])[:2]),
        "Replan triggers: " + "; ".join((risk_data.get("replan_triggers") or [])[: (2 if compact else 4)]),
    ]
    return "\n".join(field for field in fields if not field.endswith(": "))


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
        hospital_capacity_summary=_fmt_hospital_capacities(inp.get("hospital_capacities", [])),
        geocode_summary=_fmt_geocode(mapping.get("geocode")),
        fema_context=_fmt_fema(fema),
    )
    run.log_entries.append("Calling LLM: situation_unit (incident_parser) with geocode + FEMA context")
    return await call_llm(
        prompt,
        caller="incident_parser",
        response_model=IncidentParserOutput,
        timeout_seconds=float(os.environ.get("INCIDENT_PARSER_TIMEOUT_SECONDS", "60")),
    )


async def run_incident_parser_reduced(run: AgentRun) -> dict:
    inp = run.input_snapshot
    ext = inp.get("external_context", {})
    mapping = ext.get("mapping", {})
    fema = ext.get("fema", {})

    prompt = INCIDENT_PARSER_REDUCED_PROMPT.format(
        incident_type=inp["incident_type"],
        location=inp["location"],
        severity_hint=inp.get("severity_hint") or "Not specified",
        resources=_fmt_resources(inp.get("resources", [])),
        report=_fmt_report_facts(inp["report"]),
        hospital_capacity_summary=_fmt_hospital_capacities(inp.get("hospital_capacities", [])),
        geocode_summary=_fmt_geocode(mapping.get("geocode")),
        fema_context=_fmt_fema(fema),
    )
    run.log_entries.append("Calling LLM: situation_unit reduced prompt after timeout")
    return await call_llm(
        prompt,
        caller="incident_parser",
        response_model=IncidentParserOutput,
        timeout_seconds=float(os.environ.get("INCIDENT_PARSER_REDUCED_TIMEOUT_SECONDS", "20")),
    )


async def run_risk_assessor(run: AgentRun) -> dict:
    inp = run.input_snapshot
    ext = inp.get("external_context", {})
    weather = ext.get("weather", {})
    alerts = weather.get("alerts", [])
    risk = weather.get("risk", {})
    prompt = RISK_ASSESSOR_PROMPT.format(
        decision_state=_fmt_decision_state(inp.get("decision_state", {}), compact=False),
        computed_risk=_fmt_computed_risk(inp.get("risk_data", {}), compact=False),
        resources=_fmt_resources(inp.get("resources", [])),
        alert_count=len(alerts),
        weather_alerts=_fmt_alerts(alerts),
        forecast_summary=_fmt_forecast(weather.get("forecast")),
        weather_risk_level=risk.get("severity", "none"),
        weather_escalation="; ".join(risk.get("escalation_triggers", [])[:3]) or "None identified",
    )
    run.log_entries.append("Calling LLM: threat_analysis_unit with compact essential incident facts")
    return await call_llm(
        prompt,
        caller="risk_assessor",
        response_model=RiskAssessorOutput,
        timeout_seconds=float(os.environ.get("RISK_ASSESSOR_TIMEOUT_SECONDS", "45")),
    )


async def run_risk_assessor_reduced(run: AgentRun) -> dict:
    inp = run.input_snapshot
    ext = inp.get("external_context", {})
    weather = ext.get("weather", {})
    alerts = weather.get("alerts", [])
    risk = weather.get("risk", {})
    prompt = RISK_ASSESSOR_REDUCED_PROMPT.format(
        decision_state=_fmt_decision_state(inp.get("decision_state", {}), compact=True),
        computed_risk=_fmt_computed_risk(inp.get("risk_data", {}), compact=True),
        resources=_fmt_resources(inp.get("resources", [])),
        alert_count=len(alerts),
        weather_alerts=_fmt_alerts(alerts),
        forecast_summary=_fmt_forecast(weather.get("forecast")),
        weather_risk_level=risk.get("severity", "none"),
        weather_escalation="; ".join(risk.get("escalation_triggers", [])[:3]) or "None identified",
    )
    run.log_entries.append("Calling LLM: threat_analysis_unit reduced prompt after timeout")
    return await call_llm(
        prompt,
        caller="risk_assessor",
        response_model=RiskAssessorOutput,
        timeout_seconds=float(os.environ.get("RISK_ASSESSOR_REDUCED_TIMEOUT_SECONDS", "25")),
    )


async def run_action_planner(run: AgentRun) -> dict:
    inp = run.input_snapshot
    ext = inp.get("external_context", {})
    mapping = ext.get("mapping", {})
    routing = mapping.get("routing")
    hospitals = mapping.get("hospitals")

    primary_route, route_duration, alternate_note = _fmt_route(routing)
    risk_context = _fmt_planner_risk_context(inp.get("risk_data", {}))

    prompt = ACTION_PLANNER_PROMPT.format(
        decision_state=_fmt_decision_state(inp.get("decision_state", {}), compact=False),
        computed_risk=_fmt_computed_risk(inp.get("computed_risk", inp.get("risk_data", {})), compact=False),
        risk_data=risk_context,
        resources=_fmt_resources(inp.get("resources", [])),
        location=inp["location"],
        primary_route=primary_route,
        route_duration=route_duration,
        alternate_route_note=alternate_note,
        hospital_context=_fmt_hospitals(hospitals),
        hospital_capacity_summary=_fmt_hospital_capacities(inp.get("hospital_capacities", [])),
    )
    run.log_entries.append("Calling LLM: operations_planner with ArcGIS routing + hospital context")
    return await call_llm(
        prompt,
        caller="action_planner",
        response_model=ActionPlannerOutput,
        timeout_seconds=float(os.environ.get("ACTION_PLANNER_TIMEOUT_SECONDS", "75")),
    )


async def run_action_planner_reduced(run: AgentRun) -> dict:
    inp = run.input_snapshot
    ext = inp.get("external_context", {})
    mapping = ext.get("mapping", {})
    routing = mapping.get("routing")
    hospitals = mapping.get("hospitals")
    primary_route, route_duration, alternate_note = _fmt_route(routing)

    prompt = ACTION_PLANNER_REDUCED_PROMPT.format(
        decision_state=_fmt_decision_state(inp.get("decision_state", {}), compact=True),
        risk_data=_fmt_planner_risk_context(inp.get("risk_data", {})),
        computed_risk=_fmt_computed_risk(inp.get("computed_risk", inp.get("risk_data", {})), compact=True),
        resources=_fmt_resources(inp.get("resources", [])),
        location=inp["location"],
        primary_route=primary_route,
        route_duration=route_duration,
        alternate_route_note=alternate_note,
        hospital_context=_fmt_hospitals(hospitals),
        hospital_capacity_summary=_fmt_hospital_capacities(inp.get("hospital_capacities", [])),
    )
    run.log_entries.append("Calling LLM: operations_planner reduced prompt after timeout")
    return await call_llm(
        prompt,
        caller="action_planner",
        response_model=ActionPlannerOutput,
        timeout_seconds=float(os.environ.get("ACTION_PLANNER_REDUCED_TIMEOUT_SECONDS", "45")),
    )


def _fmt_triage(triage: list | None) -> str:
    if not triage:
        return "No triage data available"
    parts = []
    for t in triage:
        if isinstance(t, dict):
            rr = t.get("required_response") or t.get("required_action", "")
            parts.append(
                f"P{t.get('priority', '?')} ({t.get('label', '')}): {t.get('estimated_count', 0)} pts — "
                f"response: {rr}"
            )
    return "; ".join(parts) if parts else "No triage data"


def _fmt_patient_transport(pt: dict | None) -> str:
    if not pt or not isinstance(pt, dict):
        return "Transport plan pending planner output"
    bits = []
    if pt.get("primary_facilities"):
        bits.append("Primary receiving: " + "; ".join(pt["primary_facilities"][:3]))
    if pt.get("alternate_facilities"):
        bits.append("Alternate: " + "; ".join(pt["alternate_facilities"][:2]))
    if pt.get("transport_routes"):
        bits.append("Routes: " + "; ".join(pt["transport_routes"][:2]))
    if pt.get("constraints"):
        bits.append("Constraints: " + "; ".join(pt["constraints"][:3]))
    if pt.get("fallback_if_primary_unavailable"):
        bits.append("Fallback: " + str(pt["fallback_if_primary_unavailable"])[:200])
    return " | ".join(bits) if bits else "No structured transport data"


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
    return await call_llm(
        prompt,
        caller="communications",
        response_model=CommunicationsOutput,
        timeout_seconds=float(os.environ.get("COMMUNICATIONS_TIMEOUT_SECONDS", "35")),
    )


async def run_communications_fallback(run: AgentRun) -> dict:
    inp = run.input_snapshot
    location = inp["location"]
    priorities = inp.get("priorities") or []
    triage = inp.get("triage_priorities") or []
    transport = inp.get("patient_transport") or {}
    transport_destinations = transport.get("primary_facilities", [])[:2]
    primary_destination = ", ".join(transport_destinations) or "nearest available receiving facility"
    triage_summary = _fmt_triage(triage)
    body_suffix = " Use conservative assumptions pending additional analysis."

    return {
        "ems_brief": {
            "audience": "EMS responders",
            "channel": "radio",
            "urgency": "immediate",
            "body": (
                f"EMS BRIEF — Respond to {location}. Priorities: {'; '.join(priorities[:2]) or 'life safety and triage'}. "
                f"Triage: {triage_summary}. Primary receiving: {primary_destination}.{body_suffix}"
            )[:220],
        },
        "hospital_notification": {
            "audience": "receiving hospitals",
            "channel": "hospital_radio",
            "urgency": "immediate",
            "subject": f"INCOMING PATIENTS: {inp.get('severity', 'incident').upper()} — {location} — ETA PENDING"[:120],
            "body": (
                f"Incident at {location}. Triage status: {triage_summary}. "
                f"Primary destinations: {primary_destination}. ETA updates to follow."
            )[:180],
        },
        "public_advisory": {
            "audience": "public",
            "channel": "emergency_alert",
            "urgency": "immediate",
            "subject": f"PUBLIC ADVISORY — {location}"[:120],
            "body": (
                f"Emergency operations are active at {location}. Avoid the area and keep access routes clear for responders. "
                f"Follow official instructions and seek care at {primary_destination} if directed."
            )[:220],
        },
        "administration_update": {
            "audience": "hospital command center",
            "channel": "email",
            "urgency": "normal",
            "subject": f"SURGE STATUS — {location}"[:120],
            "body": (
                f"Incident response remains active at {location}. Current priorities: {'; '.join(priorities[:3]) or 'life safety, access, and coordination'}. "
                f"Fallback communications issued while awaiting additional agent output."
            )[:240],
        },
    }


# ─── Compact context formatters (lean pipeline) ───────────────────────────────

def _fmt_situation_compact(parsed: dict) -> str:
    """~150 chars max. Replaces json.dumps(parsed_data, indent=2) (~2000 chars)."""
    c = parsed.get("critical", parsed.get("medical_impact", {}).get("critical", 0) if isinstance(parsed.get("medical_impact"), dict) else 0)
    mo = parsed.get("moderate", parsed.get("medical_impact", {}).get("moderate", 0) if isinstance(parsed.get("medical_impact"), dict) else 0)
    mi = parsed.get("minor", parsed.get("medical_impact", {}).get("minor", 0) if isinstance(parsed.get("medical_impact"), dict) else 0)
    total = parsed.get("incoming_patient_count", parsed.get("patient_count", c + mo + mi))
    hazards = ", ".join((parsed.get("key_hazards") or parsed.get("hazards") or [])[:3]) or "unknown"
    transport = (parsed.get("transport_status") or parsed.get("transport_note") or "unknown")[:80]
    hospitals = (parsed.get("hospital_capacity_notes") or parsed.get("hospital_notes") or "unknown")[:80]
    threat = "YES" if parsed.get("immediate_life_safety_threat") or parsed.get("immediate_threat") else "no"
    return (
        f"Patients: {total} (critical:{c} moderate:{mo} minor:{mi}) | "
        f"Immediate threat: {threat} | Hazards: {hazards} | "
        f"Transport: {transport} | Hospitals: {hospitals}"
    )


def _fmt_risk_compact(risk: dict) -> str:
    """~120 chars max."""
    sev = risk.get("severity_level") or risk.get("severity", "unknown")
    risks = "; ".join((risk.get("primary_risks") or risk.get("top_risks") or [])[:3])
    bottlenecks = "; ".join((risk.get("capacity_bottlenecks") or risk.get("bottlenecks") or [])[:2])
    return f"Severity: {sev.upper()} | Risks: {risks} | Bottlenecks: {bottlenecks}"


def _log_prompt_stats(run: "AgentRun", prompt: str, model: str) -> None:
    chars = len(prompt)
    est_tokens = chars // 4
    run.log_entries.append(
        f"[prompt] chars={chars} est_tokens={est_tokens} model={model}"
    )


# ─── Lean agent functions ──────────────────────────────────────────────────────

_LEAN_TIMEOUT = float(os.environ.get("LEAN_AGENT_TIMEOUT_SECONDS", "35"))
_LEAN_PARSER_TIMEOUT = float(os.environ.get("LEAN_PARSER_TIMEOUT_SECONDS", str(_LEAN_TIMEOUT)))
_LEAN_RISK_TIMEOUT = float(os.environ.get("LEAN_RISK_TIMEOUT_SECONDS", "35"))
_LEAN_PLANNER_TIMEOUT = float(os.environ.get("LEAN_PLANNER_TIMEOUT_SECONDS", "45"))
_LEAN_COMMS_TIMEOUT = float(os.environ.get("LEAN_COMMS_TIMEOUT_SECONDS", "25"))
_LEAN_FALLBACK_TIMEOUT = float(os.environ.get("LEAN_FALLBACK_TIMEOUT_SECONDS", "20"))


async def run_lean_parser(run: AgentRun) -> dict:
    inp = run.input_snapshot
    prompt = LEAN_PARSER_PROMPT.format(
        incident_type=inp["incident_type"],
        location=inp["location"],
        severity_hint=inp.get("severity_hint") or "Not specified",
        resources=_fmt_resources(inp.get("resources", [])),
        report=inp["report"][:1200],
        hospital_capacity_summary=_fmt_hospital_capacities(inp.get("hospital_capacities", [])),
    )
    _log_prompt_stats(run, prompt, "K2-Think-v2")
    run.log_entries.append("lean situation parser")
    return await call_llm(
        prompt,
        caller="incident_parser",
        response_model=LeanParserOutput,
        timeout_seconds=_LEAN_PARSER_TIMEOUT,
    )


async def run_lean_risk(run: AgentRun) -> dict:
    inp = run.input_snapshot
    decision_state_text = inp.get("decision_state_compact") or _fmt_decision_state(inp.get("decision_state", {}), compact=True)
    prompt = LEAN_RISK_PROMPT.format(
        decision_state=decision_state_text,
    )
    _log_prompt_stats(run, prompt, "K2-Think-v2")
    run.log_entries.append("lean risk assessor")
    return await call_llm(
        prompt,
        caller="risk_assessor",
        response_model=LeanRiskOutput,
        timeout_seconds=_LEAN_RISK_TIMEOUT,
    )


async def run_lean_planner(run: AgentRun) -> dict:
    inp = run.input_snapshot
    decision_state_text = inp.get("decision_state_compact") or _fmt_decision_state(inp.get("decision_state", {}), compact=True)
    risk_summary = inp.get("risk_summary_compact") or _fmt_risk_compact(inp.get("risk_data", {}))
    primary_route = inp.get("primary_route")
    route_duration = inp.get("route_duration")
    alternate_note = inp.get("alternate_route_note")
    hospital_context = inp.get("hospital_context")
    hospital_capacity_summary = inp.get("hospital_capacity_summary")
    if not primary_route or not route_duration or not alternate_note:
        ext = inp.get("external_context", {})
        mapping = ext.get("mapping", {})
        routing = mapping.get("routing")
        hospitals = mapping.get("hospitals")
        primary_route, route_duration, alternate_note = _fmt_route(routing)
        hospital_context = hospital_context or _fmt_hospitals(hospitals)
    hospital_context = hospital_context or "No hospital data available"
    hospital_capacity_summary = hospital_capacity_summary or _fmt_hospital_capacities(inp.get("hospital_capacities", []))
    prompt = LEAN_PLANNER_PROMPT.format(
        decision_state=decision_state_text,
        risk_summary=risk_summary,
        primary_route=primary_route,
        route_duration=route_duration,
        alternate_route_note=alternate_note,
        hospital_context=hospital_context,
        hospital_capacity_summary=hospital_capacity_summary,
    )
    _log_prompt_stats(run, prompt, "K2-Think-v2")
    run.log_entries.append("lean operations planner")
    return await call_llm(
        prompt,
        caller="action_planner",
        response_model=LeanPlannerOutput,
        timeout_seconds=_LEAN_PLANNER_TIMEOUT,
    )


async def run_coordination_engine(run: AgentRun) -> dict:
    """Fast Mode: single combined Situation+Risk+Plan call."""
    inp = run.input_snapshot
    ext = inp.get("external_context", {})
    mapping = ext.get("mapping", {})
    routing = mapping.get("routing")
    hospitals = mapping.get("hospitals")
    primary_route, route_duration, alternate_note = _fmt_route(routing)
    prompt = LEAN_COORDINATION_PROMPT.format(
        incident_type=inp["incident_type"],
        location=inp["location"],
        severity_hint=inp.get("severity_hint") or "Not specified",
        report=inp["report"][:1000],
        resources=_fmt_resources(inp.get("resources", [])),
        primary_route=primary_route,
        route_duration=route_duration,
        hospital_context=_fmt_hospitals(hospitals),
        hospital_capacity_summary=_fmt_hospital_capacities(inp.get("hospital_capacities", [])),
    )
    _log_prompt_stats(run, prompt, "K2-Think-v2")
    run.log_entries.append("fast mode coordination engine (situation+risk+plan combined)")
    return await call_llm(
        prompt,
        caller="action_planner",
        response_model=LeanCoordinationOutput,
        timeout_seconds=_LEAN_PLANNER_TIMEOUT,
    )


async def run_lean_comms(run: AgentRun) -> dict:
    inp = run.input_snapshot
    patient_summary = inp.get("patient_summary")
    priorities = inp.get("priorities_text")
    if not patient_summary or not priorities:
        plan = inp.get("plan_data", {})
        facilities = plan.get("facility_assignments", [])
        patient_summary = (
            f"total={plan.get('total_patients', 0)} "
            f"critical={plan.get('critical', 0)} "
            f"moderate={plan.get('moderate', 0)} "
            f"minor={plan.get('minor', 0)}"
        )
        if facilities:
            hosp_lines = "; ".join(f"{f.get('hospital', '?')}:{f.get('patients', f.get('patients_assigned', 0))}" for f in facilities[:3])
            patient_summary += f" → {hosp_lines}"
        priorities = "; ".join((plan.get("priorities") or plan.get("operational_priorities") or [])[:3])
    prompt = LEAN_COMMS_PROMPT.format(
        situation_summary=inp.get("situation_summary", inp.get("incident_summary", "Surge event")),
        severity=inp.get("severity", "high"),
        location=inp["location"],
        patient_summary=patient_summary,
        priorities=priorities or "patient safety, transport routing, hospital coordination",
    )
    _log_prompt_stats(run, prompt, "K2-Think-v2")
    run.log_entries.append("lean communications agent")
    return await call_llm(
        prompt,
        caller="communications",
        response_model=LeanCommunicationsOutput,
        timeout_seconds=_LEAN_COMMS_TIMEOUT,
    )
