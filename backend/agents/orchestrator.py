"""
Orchestrates the four specialist agents sequentially, preceded by external data
enrichment (ArcGIS, NWS, OpenFEMA). External context flows into every agent prompt.
"""
from __future__ import annotations
import json
from datetime import datetime
from typing import Optional

from models.incident import Incident
from models.plan import (
    PlanVersion, PlanDiff, ActionItem, RoleAssignment, CommunicationDraft, Assumption,
    MedicalImpact, TriagePriority, PatientTransport,
)
from models.agent import AgentRun, AgentType
from agents.specialist_agents import (
    run_incident_parser, run_risk_assessor, run_action_planner, run_communications_agent
)
from agents.llm import call_llm
from agents.prompts import REPLAN_CONTEXT_PROMPT
from services import gather_external_context
from runtime import get_runtime
from db import save_agent_run


def _make_run(incident: Incident, version: int, agent_type: AgentType, snapshot: dict) -> AgentRun:
    return AgentRun(
        incident_id=incident.id,
        plan_version=version,
        agent_type=agent_type,
        input_snapshot=snapshot,
    )


def _parse_action_items(raw: list) -> list[ActionItem]:
    items = []
    for i, item in enumerate(raw or []):
        if isinstance(item, str):
            items.append(ActionItem(description=item, priority=i + 1))
        else:
            items.append(ActionItem(
                description=item.get("description", ""),
                assigned_to=item.get("assigned_to"),
                timeframe=item.get("timeframe"),
                priority=i + 1,
            ))
    return items


def _parse_assumptions(raw: list) -> list[Assumption]:
    result = []
    for item in raw or []:
        if isinstance(item, dict):
            result.append(Assumption(
                description=item.get("description", ""),
                impact=item.get("impact", "Unknown"),
                confidence=float(item.get("confidence", 0.5)),
            ))
        elif isinstance(item, str):
            result.append(Assumption(description=item, impact="Unknown", confidence=0.5))
    return result


def _parse_communications(comms_artifact: dict) -> list[CommunicationDraft]:
    drafts = []
    for key in ["ems_brief", "hospital_notification", "public_advisory", "administration_update"]:
        item = comms_artifact.get(key)
        if item and isinstance(item, dict):
            drafts.append(CommunicationDraft(
                audience=item.get("audience", key),
                channel=item.get("channel", ""),
                subject=item.get("subject"),
                body=item.get("body", ""),
                urgency=item.get("urgency", "normal"),
            ))
    return drafts


def _parse_medical_impact(raw: dict | None) -> MedicalImpact | None:
    if not raw or not isinstance(raw, dict):
        return None
    return MedicalImpact(
        affected_population=raw.get("affected_population", ""),
        estimated_injured=raw.get("estimated_injured", ""),
        critical=int(raw.get("critical", 0)),
        moderate=int(raw.get("moderate", 0)),
        minor=int(raw.get("minor", 0)),
        at_risk_groups=raw.get("at_risk_groups", []),
    )


def _parse_triage_priorities(raw: list | None) -> list[TriagePriority]:
    if not raw:
        return []
    result = []
    for item in raw:
        if isinstance(item, dict):
            result.append(TriagePriority(
                priority=int(item.get("priority", 1)),
                label=item.get("label", ""),
                estimated_count=int(item.get("estimated_count", 0)),
                required_action=item.get("required_action", ""),
            ))
    return result


def _parse_patient_transport(raw: dict | None) -> PatientTransport | None:
    if not raw or not isinstance(raw, dict):
        return None
    return PatientTransport(
        primary_facilities=raw.get("primary_facilities", []),
        alternate_facilities=raw.get("alternate_facilities", []),
        transport_routes=raw.get("transport_routes", []),
        constraints=raw.get("constraints", []),
    )


def _all_actions(plan: PlanVersion) -> list[ActionItem]:
    return plan.immediate_actions + plan.short_term_actions + plan.ongoing_actions


def _generate_diff(prev: PlanVersion, curr: PlanVersion) -> PlanDiff:
    prev_descs = {a.description for a in _all_actions(prev)}
    curr_descs = {a.description for a in _all_actions(curr)}

    added = [a for a in _all_actions(curr) if a.description not in prev_descs]
    removed = [a for a in _all_actions(prev) if a.description not in curr_descs]

    changed_sections = []
    if prev.operational_priorities != curr.operational_priorities:
        changed_sections.append("operational_priorities")
    if [a.description for a in prev.immediate_actions] != [a.description for a in curr.immediate_actions]:
        changed_sections.append("immediate_actions")
    if [a.description for a in prev.short_term_actions] != [a.description for a in curr.short_term_actions]:
        changed_sections.append("short_term_actions")
    if [a.description for a in prev.ongoing_actions] != [a.description for a in curr.ongoing_actions]:
        changed_sections.append("ongoing_actions")
    if prev.assessed_severity != curr.assessed_severity:
        changed_sections.append("severity")

    return PlanDiff(
        from_version=prev.version,
        to_version=curr.version,
        summary=curr.diff_summary or f"IAP revised (v{prev.version} → v{curr.version})",
        changed_sections=changed_sections or ["general"],
        added_actions=added,
        removed_actions=removed,
        modified_actions=[],
        updated_priorities=curr.operational_priorities if "operational_priorities" in changed_sections else None,
    )


async def generate_plan(
    incident: Incident,
    version: int,
    update_text: Optional[str] = None,
    previous_plan: Optional[PlanVersion] = None,
) -> tuple[PlanVersion, list[AgentRun]]:
    runtime = get_runtime()
    agent_runs: list[AgentRun] = []
    resources_raw = [r.model_dump() for r in incident.resources]

    # --- Gather external context BEFORE any agent runs ---
    ext_ctx = await gather_external_context(incident.location)

    full_report = incident.report if not update_text else f"{incident.report}\n\nFIELD UPDATE: {update_text}"

    # --- Agent 1: Planning Section (Incident Parser) ---
    run1 = _make_run(incident, version, AgentType.INCIDENT_PARSER, {
        "incident_type": incident.incident_type,
        "report": full_report,
        "location": incident.location,
        "severity_hint": incident.severity_hint,
        "resources": resources_raw,
        "external_context": ext_ctx,
    })
    run1 = await runtime.execute(run1, run_incident_parser)
    agent_runs.append(run1)
    parsed = run1.output_artifact or {}

    # --- Agent 2: Intelligence/Planning Section (Risk Assessor) ---
    run2 = _make_run(incident, version, AgentType.RISK_ASSESSOR, {
        "parsed_data": parsed,
        "resources": resources_raw,
        "external_context": ext_ctx,
    })
    run2 = await runtime.execute(run2, run_risk_assessor)
    agent_runs.append(run2)
    risk = run2.output_artifact or {}

    # --- Agent 3: Operations Section (Action Planner) ---
    run3 = _make_run(incident, version, AgentType.ACTION_PLANNER, {
        "parsed_data": parsed,
        "risk_data": risk,
        "resources": resources_raw,
        "location": incident.location,
        "external_context": ext_ctx,
    })
    run3 = await runtime.execute(run3, run_action_planner)
    agent_runs.append(run3)
    plan_raw = run3.output_artifact or {}

    # --- Agent 4: Public Information Officer (Communications) ---
    run4 = _make_run(incident, version, AgentType.COMMUNICATIONS, {
        "incident_summary": plan_raw.get("incident_summary", ""),
        "severity": risk.get("severity_level", "unknown"),
        "location": incident.location,
        "priorities": plan_raw.get("operational_priorities", []),
        "missing_info": plan_raw.get("missing_information", []),
        "triage_priorities": plan_raw.get("triage_priorities", []),
        "external_context": ext_ctx,
    })
    run4 = await runtime.execute(run4, run_communications_agent)
    agent_runs.append(run4)
    comms = run4.output_artifact or {}

    # --- Diff context for replanning ---
    diff_summary = None
    changed_sections = None
    if update_text and previous_plan:
        try:
            replan_meta = await call_llm(REPLAN_CONTEXT_PROMPT.format(
                original_summary=previous_plan.incident_summary,
                original_priorities=json.dumps(previous_plan.operational_priorities),
                update_text=update_text,
            ))
            diff_summary = replan_meta.get("reasoning", "")
            changed_sections = replan_meta.get("affected_sections", [])
        except Exception:
            diff_summary = f"IAP revised based on field update: {update_text}"

    # --- Build external context summary for the frontend ---
    weather = ext_ctx.get("weather", {})
    mapping = ext_ctx.get("mapping", {})
    fema = ext_ctx.get("fema", {})
    geo = mapping.get("geocode")
    routing = mapping.get("routing")
    hospitals = mapping.get("hospitals", [])
    alerts = weather.get("alerts", [])
    forecast = weather.get("forecast")

    ext_summary = {
        "geocoded": bool(geo),
        "coordinates": ext_ctx.get("coordinates"),
        "display_address": geo.get("display_address") if geo else None,
        "weather_alerts": [
            {"event": a["event"], "severity": a["severity"], "headline": a["headline"][:100]}
            for a in alerts[:3]
        ],
        "alert_count": len(alerts),
        "forecast": {
            "temperature_f": forecast.get("temperature_f") if forecast else None,
            "short_forecast": forecast.get("short_forecast") if forecast else None,
            "wind_speed": forecast.get("wind_speed") if forecast else None,
        } if forecast else None,
        "weather_risk": weather.get("risk", {}).get("severity", "none"),
        "routing": {
            "duration_min": routing.get("primary_duration_min") if routing else None,
            "distance_mi": routing.get("primary_distance_mi") if routing else None,
            "steps": (routing.get("primary_route_steps") or [])[:3] if routing else [],
            "origin": routing.get("origin") if routing else None,
        } if routing else None,
        "fema_context": fema.get("context_notes", [])[:2],
        "weather_driven_threats": risk.get("weather_driven_threats", []),
        "replan_triggers": risk.get("replan_triggers", []),
        "primary_access_route": plan_raw.get("primary_access_route"),
        "alternate_access_route": plan_raw.get("alternate_access_route"),
        "healthcare_risks": risk.get("healthcare_risks", []),
        "hospitals": [
            {"name": h.get("name", ""), "distance_mi": h.get("distance_mi"), "trauma_level": h.get("trauma_level")}
            for h in hospitals[:4]
        ],
    }

    plan = PlanVersion(
        incident_id=incident.id,
        version=version,
        trigger=update_text or "initial",

        incident_summary=plan_raw.get("incident_summary", ""),
        operational_period=parsed.get("operational_period", ""),

        incident_objectives=risk.get("incident_objectives", []),
        operational_priorities=plan_raw.get("operational_priorities", []),

        immediate_actions=_parse_action_items(plan_raw.get("immediate_actions", [])),
        short_term_actions=_parse_action_items(plan_raw.get("short_term_actions", [])),
        ongoing_actions=_parse_action_items(plan_raw.get("ongoing_actions", [])),

        resource_assignments=plan_raw.get("resource_assignments"),

        safety_considerations=risk.get("safety_considerations", []),

        communications=_parse_communications(comms),

        confirmed_facts=parsed.get("confirmed_facts", []),
        unknowns=parsed.get("unknowns", []),
        assumptions=_parse_assumptions(plan_raw.get("assumptions", [])),
        missing_information=plan_raw.get("missing_information", []),

        assessed_severity=risk.get("severity_level", "unknown"),
        confidence_score=float(risk.get("confidence", 0.7)),
        risk_notes=risk.get("primary_risks", []),

        medical_impact=_parse_medical_impact(parsed.get("medical_impact")),
        triage_priorities=_parse_triage_priorities(plan_raw.get("triage_priorities")),
        patient_transport=_parse_patient_transport(plan_raw.get("patient_transport")),

        diff_summary=diff_summary,
        changed_sections=changed_sections,
        external_context=ext_summary,
    )

    return plan, agent_runs
