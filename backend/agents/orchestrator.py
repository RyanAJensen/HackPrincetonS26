"""
Unilert IAP Orchestrator — multi-phase execution across interchangeable runtimes.

Agents:
  incident_parser → Situation Unit
  risk_assessor   → Threat Analysis
  action_planner  → Operations Planner
  communications  → Communications Officer

Execution flow:
  Phase 1 (parallel): Situation Unit + external context enrichment
  Phase 2:            Threat Analysis (risk_assessor)
  Phase 3:            Operations Planner, then Communications (triage + transport aware)

Phase 3 runs Operations Planner first, then Communications.
"""
from __future__ import annotations
import asyncio
import json
import os
import time
import traceback as _traceback
from datetime import datetime
from typing import Any, Optional

from models.incident import Incident
from models.plan import (
    PlanVersion, PlanDiff, ActionItem, CommunicationDraft, Assumption,
    MedicalImpact, TriagePriority, PatientTransport,
    PatientFlowSummary, FacilityAssignment, DecisionPoint, Tradeoff,
)
from models.agent import AgentFailure, AgentRun, AgentType, AgentStatus
from agents.specialist_agents import (
    run_action_planner,
    run_action_planner_reduced,
    run_communications_agent,
    run_communications_fallback,
    run_incident_parser,
    run_incident_parser_reduced,
    run_risk_assessor,
    run_risk_assessor_reduced,
    run_lean_parser,
    run_lean_risk,
    run_lean_planner,
    run_coordination_engine,
    run_lean_comms,
    _fmt_situation_compact,
    _fmt_risk_compact,
)
from agents.llm import call_llm
from agents.prompts import REPLAN_CONTEXT_PROMPT
from agents.schemas import ReplanContextOutput
from services import gather_external_context
from runtime import get_runtime
from runtime.dedalus_runtime import AGENT_ROLE_MAP, ROLE_LABELS
from db import save_agent_run


REQUIRED_AGENT_TYPES = {
    AgentType.INCIDENT_PARSER,
}


def _make_run(incident: Incident, version: int, agent_type: AgentType, snapshot: dict) -> AgentRun:
    return AgentRun(
        incident_id=incident.id,
        plan_version=version,
        agent_type=agent_type,
        input_snapshot=snapshot,
        required=agent_type in REQUIRED_AGENT_TYPES,
    )


def collect_agent_failures(agent_runs: list[AgentRun]) -> list[AgentFailure]:
    failures: list[AgentFailure] = []
    for run in agent_runs:
        failure = run.as_failure()
        if failure is not None:
            failures.append(failure)
    return failures


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


def _parse_medical_impact(raw: dict | None, parsed_fallback: dict | None = None) -> MedicalImpact | None:
    if raw and isinstance(raw, dict) and any(
        raw.get(k) not in (None, "", [], 0) for k in ("affected_population", "estimated_injured", "critical", "moderate", "minor", "at_risk_groups")
    ):
        return MedicalImpact(
            affected_population=str(raw.get("affected_population", "")),
            estimated_injured=str(raw.get("estimated_injured", "")),
            critical=int(raw.get("critical", 0)),
            moderate=int(raw.get("moderate", 0)),
            minor=int(raw.get("minor", 0)),
            at_risk_groups=list(raw.get("at_risk_groups", [])),
        )
    if not parsed_fallback:
        return None
    ap = str(parsed_fallback.get("affected_population", "") or "")
    if not ap and not parsed_fallback.get("immediate_life_safety_threat"):
        return None
    return MedicalImpact(
        affected_population=ap or "Estimate pending field verification",
        estimated_injured="Unknown — confirm with EMS / triage lead",
        critical=1 if parsed_fallback.get("immediate_life_safety_threat") else 0,
        moderate=0,
        minor=0,
        at_risk_groups=[],
    )


def _parse_triage_priorities(raw: list | None) -> list[TriagePriority]:
    if not raw:
        return []
    result = []
    for item in raw:
        if isinstance(item, dict):
            rr = item.get("required_response") or item.get("required_action", "")
            ra = item.get("required_action", "") or rr
            result.append(TriagePriority(
                priority=int(item.get("priority", 1)),
                label=item.get("label", ""),
                estimated_count=int(item.get("estimated_count", 0)),
                required_response=str(rr),
                required_action=str(ra),
            ))
    return result


def _parse_patient_flow(raw: dict | None) -> PatientFlowSummary | None:
    if not raw or not isinstance(raw, dict):
        return None
    assignments = []
    for fa in raw.get("facility_assignments", []):
        if isinstance(fa, dict):
            assignments.append(FacilityAssignment(
                hospital=fa.get("hospital", ""),
                patients_assigned=int(fa.get("patients_assigned", 0)),
                capacity_strain=fa.get("capacity_strain", "normal"),
                patient_types=fa.get("patient_types", []),
                routing_reason=fa.get("routing_reason", ""),
                reroute_trigger=fa.get("reroute_trigger", ""),
            ))
    return PatientFlowSummary(
        total_incoming=int(raw.get("total_incoming", 0)),
        critical=int(raw.get("critical", 0)),
        moderate=int(raw.get("moderate", 0)),
        minor=int(raw.get("minor", 0)),
        facility_assignments=assignments,
        bottlenecks=raw.get("bottlenecks", []),
        distribution_rationale=raw.get("distribution_rationale", ""),
    )


def _parse_decision_points(raw: list | None) -> list[DecisionPoint]:
    result = []
    for item in raw or []:
        if isinstance(item, dict):
            result.append(DecisionPoint(
                decision=item.get("decision", ""),
                reason=item.get("reason", ""),
                assumption=item.get("assumption", ""),
                replan_trigger=item.get("replan_trigger", ""),
            ))
    return result


def _parse_tradeoffs(raw: list | None) -> list[Tradeoff]:
    result = []
    for item in raw or []:
        if isinstance(item, dict):
            result.append(Tradeoff(
                description=item.get("description", ""),
                option_a=item.get("option_a", ""),
                option_b=item.get("option_b", ""),
                recommendation=item.get("recommendation", ""),
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
        fallback_if_primary_unavailable=str(raw.get("fallback_if_primary_unavailable", "")),
    )


def _lean_parser_to_parsed(lean: dict) -> dict:
    """Map LeanParserOutput → structure expected by downstream agents."""
    return {
        "incoming_patient_count": lean.get("patient_count", 0),
        "critical": lean.get("critical", 0),
        "moderate": lean.get("moderate", 0),
        "minor": lean.get("minor", 0),
        "affected_population": lean.get("affected_population", "Unknown"),
        "key_hazards": lean.get("hazards", []),
        "transport_status": lean.get("transport_note", ""),
        "hospital_capacity_notes": lean.get("hospital_notes", ""),
        "immediate_life_safety_threat": lean.get("immediate_threat", False),
        "time_sensitivity": lean.get("time_sensitivity", "urgent"),
        "operational_period": lean.get("operational_period", ""),
        "confirmed_facts": [],
        "unknowns": lean.get("unknowns", []),
        "location_notes": "",
        "medical_impact": {
            "affected_population": lean.get("affected_population", ""),
            "estimated_injured": str(lean.get("patient_count", 0)),
            "critical": lean.get("critical", 0),
            "moderate": lean.get("moderate", 0),
            "minor": lean.get("minor", 0),
            "at_risk_groups": [],
        },
    }


def _lean_risk_to_risk(lean: dict) -> dict:
    """Map LeanRiskOutput → structure expected by downstream agents."""
    return {
        "severity_level": lean.get("severity", "medium"),
        "confidence": 0.7,
        "primary_risks": lean.get("top_risks", []),
        "capacity_bottlenecks": lean.get("bottlenecks", []),
        "replan_triggers": lean.get("replan_triggers", []),
        "incident_objectives": [],
        "safety_considerations": [],
        "healthcare_risks": lean.get("top_risks", []),
        "weather_driven_threats": [],
        "resource_adequacy": lean.get("resource_adequacy", "strained"),
        "resource_gaps": [],
        "mutual_aid_needed": lean.get("mutual_aid_needed", False),
        "estimated_duration_hours": 2.0,
        "decision_triggers": [],
        "transport_delays": [],
        "cascade_risks": [],
    }


def _lean_planner_to_plan_raw(lean: dict) -> dict:
    """Map LeanPlannerOutput → structure expected by PlanVersion builder."""
    facility_assignments = [
        {
            "hospital": f.get("hospital", ""),
            "patients_assigned": f.get("patients", 0),
            "capacity_strain": f.get("strain", "normal"),
            "patient_types": [],
            "routing_reason": f.get("reason", ""),
            "reroute_trigger": "",
        }
        for f in lean.get("facility_assignments", [])
    ]
    total = lean.get("total_patients", 0)
    return {
        "incident_summary": lean.get("summary", ""),
        "patient_flow": {
            "total_incoming": total,
            "critical": lean.get("critical", 0),
            "moderate": lean.get("moderate", 0),
            "minor": lean.get("minor", 0),
            "distribution_rationale": lean.get("distribution_note", ""),
            "bottlenecks": [],
            "facility_assignments": facility_assignments,
        },
        "operational_priorities": lean.get("priorities", []),
        "immediate_actions": [{"description": a, "assigned_to": "Operations", "timeframe": "0-10 min"} for a in lean.get("immediate_actions", [])],
        "short_term_actions": [{"description": a, "assigned_to": "Operations", "timeframe": "10-30 min"} for a in lean.get("short_term_actions", [])],
        "ongoing_actions": [],
        "decision_points": [{"decision": lean.get("key_decision", ""), "reason": "", "assumption": "", "replan_trigger": lean.get("replan_if", "")}] if lean.get("key_decision") else [],
        "tradeoffs": [],
        "triage_priorities": _build_lean_triage(lean),
        "patient_transport": {
            "primary_facilities": [f.get("hospital", "") for f in lean.get("facility_assignments", [])[:2]],
            "alternate_facilities": [],
            "transport_routes": [lean.get("primary_route", "")] if lean.get("primary_route") else [],
            "constraints": [],
        },
        "primary_access_route": lean.get("primary_route"),
        "alternate_access_route": lean.get("alternate_route"),
        "assumptions": [],
        "missing_information": lean.get("missing_info", []),
        "resource_assignments": {"operations": [], "logistics": [], "communications": [], "command": []},
    }


def _build_lean_triage(lean: dict) -> list[dict]:
    result = []
    if lean.get("triage_critical_action") and lean.get("critical", 0) > 0:
        result.append({"priority": 1, "label": "critical", "estimated_count": lean["critical"], "required_action": lean["triage_critical_action"], "required_response": "immediate"})
    if lean.get("triage_moderate_action") and lean.get("moderate", 0) > 0:
        result.append({"priority": 2, "label": "urgent", "estimated_count": lean["moderate"], "required_action": lean["triage_moderate_action"], "required_response": "urgent"})
    if lean.get("triage_minor_action") and lean.get("minor", 0) > 0:
        result.append({"priority": 3, "label": "minor", "estimated_count": lean["minor"], "required_action": lean["triage_minor_action"], "required_response": "monitoring"})
    return result


def _lean_coord_to_plan_raw(lean: dict) -> dict:
    """Map LeanCoordinationOutput → plan_raw structure."""
    facility_assignments = [
        {
            "hospital": f.get("hospital", ""),
            "patients_assigned": f.get("patients", 0),
            "capacity_strain": f.get("strain", "normal"),
            "patient_types": [],
            "routing_reason": f.get("reason", ""),
            "reroute_trigger": "",
        }
        for f in lean.get("facility_assignments", [])
    ]
    return {
        "incident_summary": lean.get("summary", ""),
        "patient_flow": {
            "total_incoming": lean.get("patient_count", 0),
            "critical": lean.get("critical", 0),
            "moderate": lean.get("moderate", 0),
            "minor": lean.get("minor", 0),
            "distribution_rationale": "",
            "bottlenecks": lean.get("bottlenecks", []),
            "facility_assignments": facility_assignments,
        },
        "operational_priorities": lean.get("priorities", []),
        "immediate_actions": [{"description": a, "assigned_to": "Operations", "timeframe": "0-10 min"} for a in lean.get("immediate_actions", [])],
        "short_term_actions": [],
        "ongoing_actions": [],
        "decision_points": [{"decision": lean.get("key_decision", ""), "reason": "", "assumption": "", "replan_trigger": lean.get("replan_if", "")}] if lean.get("key_decision") else [],
        "tradeoffs": [],
        "triage_priorities": [],
        "patient_transport": {"primary_facilities": [f.get("hospital", "") for f in lean.get("facility_assignments", [])[:2]], "alternate_facilities": [], "transport_routes": [], "constraints": []},
        "primary_access_route": None,
        "alternate_access_route": None,
        "assumptions": [],
        "missing_information": lean.get("missing_info", []),
        "resource_assignments": {"operations": [], "logistics": [], "communications": [], "command": []},
    }


def _lean_comms_to_comms(lean: dict) -> dict:
    """Map LeanCommunicationsOutput → CommunicationsOutput-compatible dict."""
    return {
        "ems_brief": {"audience": "EMS dispatch", "channel": "radio", "urgency": "immediate", "body": lean.get("ems_brief", "")},
        "hospital_notification": {"audience": "receiving hospitals", "channel": "hospital_radio", "urgency": "immediate", "subject": "INCOMING PATIENTS", "body": lean.get("hospital_notification", "")},
        "public_advisory": {"audience": "public", "channel": "emergency_alert", "urgency": "immediate", "subject": "EMERGENCY ADVISORY", "body": lean.get("public_advisory", "")},
        "administration_update": {"audience": "hospital command center", "channel": "email", "urgency": "normal", "subject": "SURGE STATUS", "body": lean.get("admin_update", "")},
    }


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
    if (prev.medical_impact and curr.medical_impact and prev.medical_impact.model_dump() != curr.medical_impact.model_dump()) or (
        (prev.medical_impact is None) != (curr.medical_impact is None)
    ):
        changed_sections.append("medical_impact")
    if [t.model_dump() for t in prev.triage_priorities] != [t.model_dump() for t in curr.triage_priorities]:
        changed_sections.append("triage_priorities")
    if (prev.patient_transport and curr.patient_transport and prev.patient_transport.model_dump() != curr.patient_transport.model_dump()) or (
        (prev.patient_transport is None) != (curr.patient_transport is None)
    ):
        changed_sections.append("patient_transport")
    return PlanDiff(
        from_version=prev.version,
        to_version=curr.version,
        summary=curr.diff_summary or f"IAP revised (v{prev.version} to v{curr.version})",
        changed_sections=changed_sections or ["general"],
        added_actions=added,
        removed_actions=removed,
        modified_actions=[],
        updated_priorities=curr.operational_priorities if "operational_priorities" in changed_sections else None,
    )


def _bool_flag(value: bool) -> str:
    return "true" if value else "false"


def _format_run_metadata(run: AgentRun) -> str:
    parts = [
        f"required={_bool_flag(run.required)}",
        f"degraded={_bool_flag(run.degraded)}",
        f"fallback_used={_bool_flag(run.fallback_used)}",
        f"retry_count={run.retry_count}",
        f"latency_ms={run.latency_ms if run.latency_ms is not None else '?'}",
    ]
    if run.error_kind:
        parts.append(f"error_kind={run.error_kind}")
    return " ".join(parts)


def _log_agent_outcome(run: AgentRun, *, label: str, elapsed: str) -> None:
    status = "FAILED" if run.status == AgentStatus.FAILED else "ok"
    detail = run.error_message if run.status == AgentStatus.FAILED else f"runtime={run.runtime}"
    print(
        f"[{datetime.utcnow().strftime('%H:%M:%S')}] {label} {status} ({elapsed}) | "
        f"{detail} | {_format_run_metadata(run)}"
    )


def _risk_unavailable_note(reason: str) -> str:
    return f"Risk assessment unavailable due to {reason}; use parser facts and conservative assumptions."


def _fallback_risk_context(parsed: dict, ext_ctx: dict, reason: str) -> dict:
    note = _risk_unavailable_note(reason)
    hazards = parsed.get("key_hazards", [])[:2]
    weather_risk = (ext_ctx.get("weather", {}).get("risk", {}) or {}).get("escalation_triggers", [])[:2]
    safety = []
    if hazards:
        safety.append(f"Confirm scene safety for {', '.join(hazards)} before EMS entry")
    if parsed.get("immediate_life_safety_threat"):
        safety.append("Prioritize life safety operations, rapid triage, and controlled access")
    if not safety:
        safety.append("Use parser facts and conservative assumptions until threat analysis is available")
    return {
        "risk_assessment_unavailable": note,
        "confidence": 0.0,
        "incident_objectives": [
            "Use parser facts and conservative assumptions until threat analysis is available"
        ],
        "primary_risks": [note],
        "safety_considerations": safety[:3],
        "weather_driven_threats": weather_risk,
        "replan_triggers": [
            "Reassess if access routes change, scene hazards worsen, or patient acuity increases"
        ],
        "healthcare_risks": [note],
    }


def _planner_risk_context(risk: dict) -> dict | str:
    note = risk.get("risk_assessment_unavailable")
    if note:
        return note
    return risk


def _fallback_plan_raw(parsed: dict, risk: dict, ext_ctx: dict, resources_raw: list[dict], location: str) -> dict:
    medical = parsed.get("medical_impact") or {}
    routing = (ext_ctx.get("mapping", {}) or {}).get("routing") or {}
    hospitals = ((ext_ctx.get("mapping", {}) or {}).get("hospitals") or [])[:3]
    primary_hospitals = [h.get("name", "") for h in hospitals if h.get("name")]
    estimated_critical = int(medical.get("critical", 0) or 0)
    estimated_moderate = int(medical.get("moderate", 0) or 0)
    estimated_minor = int(medical.get("minor", 0) or 0)
    summary_bits = [
        f"{parsed.get('parsed_type', 'Incident')} at {parsed.get('confirmed_location', location)}.",
        f"Hazards include {', '.join(parsed.get('key_hazards', [])[:2]) or 'scene hazards under assessment'}.",
    ]
    if medical:
        summary_bits.append(
            "Known medical impact: "
            f"critical={estimated_critical}, moderate={estimated_moderate}, minor={estimated_minor}."
        )
    note = risk.get("risk_assessment_unavailable")
    if note:
        summary_bits.append(note)

    operations = [f"{r.get('name')} -> scene operations" for r in resources_raw[:3] if r.get("name")]
    logistics = ["Stage equipment and dry PPE near access point"]
    communications = ["Notify receiving hospitals and update command on access changes"]
    command = ["Maintain unified command and re-evaluate conditions every 15 minutes"]

    return {
        "incident_summary": " ".join(summary_bits)[:360],
        "operational_priorities": (
            risk.get("incident_objectives")
            or [
                "1. Protect life safety and stabilize critical patients",
                "2. Maintain EMS access and triage flow",
                "3. Coordinate receiving hospitals and transport routes",
            ]
        )[:3],
        "immediate_actions": [
            {"description": "Deploy EMS and rescue units to the safest access point", "assigned_to": "Operations", "timeframe": "0–10 min"},
            {"description": "Extricate and triage life-threatening patients first", "assigned_to": "Medical Group", "timeframe": "0–10 min"},
            {"description": "Secure ingress and egress corridor for ambulances", "assigned_to": "Law/Fire", "timeframe": "0–10 min"},
        ],
        "short_term_actions": [
            {"description": "Establish triage and treatment area near stable access", "assigned_to": "Medical Group", "timeframe": "10–30 min"},
            {"description": "Confirm receiving hospitals and destination priorities", "assigned_to": "Transport Officer", "timeframe": "10–30 min"},
        ],
        "ongoing_actions": [
            {"description": "Coordinate hospital notifications and transport updates", "assigned_to": "Communications", "timeframe": "30–120 min"},
            {"description": "Reroute transport if access conditions change", "assigned_to": "Transport Officer", "timeframe": "30–120 min"},
        ],
        "resource_assignments": {
            "operations": operations or ["Assign available field units to rescue and triage"],
            "logistics": logistics,
            "communications": communications,
            "command": command,
        },
        "primary_access_route": " > ".join((routing.get("primary_route_steps") or [])[:3]) or "Use safest confirmed primary corridor",
        "alternate_access_route": "Use alternate corridor if flooding or blockage affects primary route",
        "assumptions": [
            {"description": "Primary access remains usable for EMS units", "impact": "If false, reroute transport immediately", "confidence": 0.4},
            {"description": "Hospital destination capacity remains available", "impact": "If false, divert to alternate facility", "confidence": 0.5},
        ],
        "missing_information": (parsed.get("unknowns") or ["Confirm patient counts and access conditions"])[:4],
        "triage_priorities": [
            {
                "priority": 1,
                "label": "critical / life-threatening",
                "estimated_count": estimated_critical,
                "required_response": "Immediate ALS transport",
                "required_action": "Stabilize and transport to highest-capability receiving facility",
            },
            {
                "priority": 2,
                "label": "urgent but stable",
                "estimated_count": estimated_moderate,
                "required_response": "Rapid on-site stabilization",
                "required_action": "Stabilize then transport when corridor is clear",
            },
            {
                "priority": 3,
                "label": "minor / delayed",
                "estimated_count": estimated_minor,
                "required_response": "Monitoring and delayed transport",
                "required_action": "Hold for evaluation or delayed transport",
            },
        ],
        "patient_transport": {
            "primary_facilities": primary_hospitals[:2] or ["Nearest available emergency department"],
            "alternate_facilities": primary_hospitals[2:] or ["Next-nearest capable receiving facility"],
            "transport_routes": [
                "Scene to primary facility via safest confirmed corridor",
            ],
            "constraints": [
                *risk.get("primary_risks", [])[:2],
                *risk.get("weather_driven_threats", [])[:1],
            ][:3],
            "fallback_if_primary_unavailable": "Use alternate access route and next available receiving facility",
        },
    }


def _fallback_incident_parse(incident: Incident, ext_ctx: dict) -> dict:
    report = incident.report or ""
    report_lower = report.lower()
    hazards: list[str] = []
    hazard_rules = [
        ("flood", "flooding"),
        ("swift water", "swift water"),
        ("surge", "secondary water surge"),
        ("stalled vehicle", "vehicle entrapment"),
        ("collision", "vehicle collision"),
        ("hazmat", "hazardous materials"),
        ("chlorine", "chlorine exposure"),
        ("respiratory", "respiratory compromise"),
        ("roof collapse", "structural collapse"),
        ("power is out", "power outage"),
        ("tree has fallen", "blocked roadway"),
        ("blocked", "route obstruction"),
    ]
    for needle, label in hazard_rules:
        if needle in report_lower and label not in hazards:
            hazards.append(label)
    if not hazards:
        hazards.append(incident.incident_type or "incident hazards")

    at_risk_groups: list[str] = []
    for needle, label in [
        ("elderly", "elderly"),
        ("child", "children"),
        ("children", "children"),
        ("personnel", "workers"),
        ("mobility", "mobility-limited"),
    ]:
        if needle in report_lower and label not in at_risk_groups:
            at_risk_groups.append(label)

    immediate_threat = any(
        token in report_lower
        for token in (
            "cardiac arrest",
            "unresponsive",
            "unconscious",
            "collapsed",
            "severe respiratory distress",
            "trapped",
            "rising rapidly",
            "second water surge",
            "unable to self-evacuate",
        )
    )

    infrastructure_impact = None
    if "impassable" in report_lower or "blocked" in report_lower:
        infrastructure_impact = "Primary access corridor impaired"
    elif "bridge" in report_lower:
        infrastructure_impact = "Bridge access constrained"
    elif "power is out" in report_lower:
        infrastructure_impact = "Utility outage affecting incident area"

    confirmed_facts = [
        f"Incident reported as {incident.incident_type}",
        f"Location reported as {incident.location}",
    ]
    if immediate_threat:
        confirmed_facts.append("Report indicates immediate life safety threat")
    if infrastructure_impact:
        confirmed_facts.append(infrastructure_impact)
    weather_alerts = (ext_ctx.get("weather", {}) or {}).get("alerts", [])
    if weather_alerts:
        first_alert = weather_alerts[0]
        confirmed_facts.append(f"Active weather alert: {first_alert.get('event', 'weather alert')}")

    unknowns = [
        "Confirm patient count and triage categories on arrival",
        "Confirm access route conditions for EMS ingress and egress",
    ]
    if "unaccounted for" in report_lower:
        unknowns.append("Confirm status and location of unaccounted personnel")

    estimated_critical = 1 if any(token in report_lower for token in ("cardiac arrest", "unresponsive", "unconscious")) else 0
    estimated_moderate = 1 if any(token in report_lower for token in ("head trauma", "fracture", "respiratory distress")) else 0
    estimated_minor = 1 if any(token in report_lower for token in ("ambulatory", "minor injur", "laceration")) else 0
    estimated_injured = "Unknown — field triage required"
    if estimated_critical or estimated_moderate or estimated_minor:
        total = estimated_critical + estimated_moderate + estimated_minor
        estimated_injured = str(total)

    coordinates = ext_ctx.get("coordinates")
    location_notes = "Use reported location until field verification"
    if coordinates:
        location_notes = f"Coordinates available near {incident.location}"
    if infrastructure_impact:
        location_notes += f"; {infrastructure_impact.lower()}"

    return {
        "parsed_type": incident.incident_type or "Incident",
        "confirmed_location": incident.location,
        "operational_period": "Next 2-4 hours (initial operational period)",
        "affected_population": "Unknown — field verification required",
        "key_hazards": hazards[:4],
        "immediate_life_safety_threat": immediate_threat,
        "infrastructure_impact": infrastructure_impact,
        "time_sensitivity": "immediate" if immediate_threat else "urgent",
        "confirmed_facts": confirmed_facts[:4],
        "unknowns": unknowns[:4],
        "location_notes": location_notes[:120],
        "medical_impact": {
            "affected_population": "Unknown — field verification required",
            "estimated_injured": estimated_injured,
            "critical": estimated_critical,
            "moderate": estimated_moderate,
            "minor": estimated_minor,
            "at_risk_groups": at_risk_groups[:4],
        },
    }


def _print_swarm_truth(agent_runs: list[AgentRun], elapsed_ms: int) -> None:
    """Print runtime truth at end of each analyze."""
    swarm = [r for r in agent_runs if r.runtime == "swarm"]
    dedalus = [r for r in agent_runs if r.runtime == "dedalus"]
    local = [r for r in agent_runs if r.runtime == "local"]
    completed = [r for r in agent_runs if r.status == AgentStatus.COMPLETED]
    failed = [r for r in agent_runs if r.status == AgentStatus.FAILED]
    failed_required = [r for r in failed if r.required and not r.fallback_used]
    failed_optional = [r for r in failed if not r.required and not r.fallback_used]
    failed_with_fallback = [r for r in failed if r.fallback_used]

    parts = []
    if swarm:
        parts.append(f"{len(swarm)} Dedalus Machines")
    if dedalus:
        parts.append(f"{len(dedalus)} DedalusRunner")
    if local:
        parts.append(f"{len(local)} local K2")
    runtime_summary = " / ".join(parts) if parts else "no agent runtime recorded"

    if failed_required:
        status = (
            f"FAILED — {len(completed)}/{len(agent_runs)} completed, "
            f"{len(failed_required)} required failed; runtimes: {runtime_summary} ({elapsed_ms}ms)"
        )
    elif failed_optional or failed_with_fallback:
        status = (
            f"DEGRADED — {len(completed)}/{len(agent_runs)} completed, "
            f"{len(failed_optional) + len(failed_with_fallback)} fallback/optional failed; "
            f"runtimes: {runtime_summary} ({elapsed_ms}ms)"
        )
    elif len(swarm) == len(agent_runs):
        status = f"OK — all {len(swarm)} agents via Dedalus Machines ({elapsed_ms}ms)"
    elif len(dedalus) == len(agent_runs):
        status = f"OK — all {len(dedalus)} agents via DedalusRunner ({elapsed_ms}ms)"
    elif local and not dedalus and not swarm:
        status = f"LOCAL - {len(local)} agents used K2 only ({elapsed_ms}ms)"
    else:
        status = f"MIXED — {runtime_summary} ({elapsed_ms}ms)"

    print(f"\n{'-'*60}")
    print(f"  Dedalus: {status}")
    print(f"  Per-agent:")
    for run in agent_runs:
        role = AGENT_ROLE_MAP.get(run.agent_type, "?")
        label = ROLE_LABELS.get(role, role)
        ok = "OK" if run.status == AgentStatus.COMPLETED else "!!"
        print(
            f"    {ok} {run.agent_type:<22} runtime={run.runtime:<10} {label} "
            f"{_format_run_metadata(run)}"
        )
    print(f"{'-'*60}\n")


def _raise_if_required_agent_failed(run: AgentRun, agent_runs: list[AgentRun], started_at: float) -> None:
    if run.status != AgentStatus.FAILED or not run.required or run.fallback_used:
        return
    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    _print_swarm_truth(agent_runs, elapsed_ms)
    role = AGENT_ROLE_MAP.get(run.agent_type, run.agent_type)
    label = ROLE_LABELS.get(role, role)
    detail = run.error_message or "unknown error"
    raise RuntimeError(f"{label} failed ({run.agent_type}, runtime={run.runtime}): {detail}")


def _build_ext_summary(ext_ctx: dict, runtime: Any, risk: dict) -> dict:
    weather = ext_ctx.get("weather", {})
    mapping = ext_ctx.get("mapping", {})
    fema = ext_ctx.get("fema", {})
    geo = mapping.get("geocode")
    routing = mapping.get("routing")
    hospitals = mapping.get("hospitals", [])
    alerts = weather.get("alerts", [])
    forecast = weather.get("forecast")
    return {
        "geocoded": bool(geo),
        "coordinates": ext_ctx.get("coordinates"),
        "display_address": geo.get("display_address") if geo else None,
        "weather_alerts": [{"event": a["event"], "severity": a["severity"], "headline": a["headline"][:100]} for a in alerts[:3]],
        "alert_count": len(alerts),
        "forecast": {"temperature_f": forecast.get("temperature_f"), "short_forecast": forecast.get("short_forecast"), "wind_speed": forecast.get("wind_speed")} if forecast else None,
        "weather_risk": weather.get("risk", {}).get("severity", "none"),
        "routing": {"duration_min": routing.get("primary_duration_min"), "distance_mi": routing.get("primary_distance_mi"), "steps": (routing.get("primary_route_steps") or [])[:3], "origin": routing.get("origin")} if routing else None,
        "fema_context": fema.get("context_notes", [])[:2],
        "weather_driven_threats": risk.get("weather_driven_threats", []),
        "replan_triggers": risk.get("replan_triggers", []),
        "healthcare_risks": risk.get("healthcare_risks", []),
        "hospitals": [{"name": h.get("name", ""), "distance_mi": h.get("distance_mi"), "trauma_level": h.get("trauma_level")} for h in hospitals[:4]],
        "dedalus_execution": {"dedalus": "DedalusRunner", "swarm": "Dedalus Machines", "local": "local"}.get(runtime.runtime_name(), runtime.runtime_name()),
    }


def _build_plan_version(
    incident: Any, version: int, update_text: Optional[str],
    parsed: dict, risk: dict, plan_raw: dict,
    comms_artifact: dict, diff_summary: Optional[str], changed_sections: Optional[list],
    ext_summary: dict,
) -> "PlanVersion":
    return PlanVersion(
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
        communications=_parse_communications(comms_artifact),
        confirmed_facts=parsed.get("confirmed_facts", []),
        unknowns=parsed.get("unknowns", []),
        assumptions=_parse_assumptions(plan_raw.get("assumptions", [])),
        missing_information=plan_raw.get("missing_information", []),
        assessed_severity=risk.get("severity_level", risk.get("severity", "unknown")),
        confidence_score=float(risk.get("confidence", 0.7)),
        risk_notes=risk.get("primary_risks", risk.get("top_risks", [])),
        patient_flow=_parse_patient_flow(plan_raw.get("patient_flow")),
        decision_points=_parse_decision_points(plan_raw.get("decision_points")),
        tradeoffs=_parse_tradeoffs(plan_raw.get("tradeoffs")),
        medical_impact=_parse_medical_impact(parsed.get("medical_impact"), parsed),
        triage_priorities=_parse_triage_priorities(plan_raw.get("triage_priorities")),
        patient_transport=_parse_patient_transport(plan_raw.get("patient_transport")),
        diff_summary=diff_summary,
        changed_sections=changed_sections,
        external_context=ext_summary,
    )


async def generate_plan_fast(
    incident: Incident,
    version: int,
    update_text: Optional[str] = None,
    previous_plan: Optional[PlanVersion] = None,
) -> tuple[PlanVersion, list[AgentRun]]:
    """
    Fast Mode: 2 agents total.
    Phase 1 (parallel): CoordinationEngine + external context
    Phase 2: Lean Communications
    Target: <25s total.
    """
    runtime = get_runtime()
    agent_runs: list[AgentRun] = []
    resources_raw = [r.model_dump() for r in incident.resources]
    hospital_capacities_raw = [h.model_dump() for h in incident.hospital_capacities]
    t_pipeline = time.monotonic()

    print(f"\n[{datetime.utcnow().strftime('%H:%M:%S')}] === FAST MODE ANALYZE incident={incident.id[:8]} v{version} ===")

    full_report = incident.report if not update_text else f"{incident.report}\n\nFIELD UPDATE: {update_text}"

    def _elapsed(t: float) -> str:
        return f"{int((time.monotonic() - t) * 1000)}ms"

    # Phase 1: CoordinationEngine + external context (parallel)
    t1 = time.monotonic()
    run1 = _make_run(incident, version, AgentType.ACTION_PLANNER, {
        "incident_type": incident.incident_type,
        "report": full_report,
        "location": incident.location,
        "severity_hint": incident.severity_hint,
        "resources": resources_raw,
        "hospital_capacities": hospital_capacities_raw,
        "external_context": {},
    })

    run1, ext_ctx = await asyncio.gather(
        runtime.execute(run1, run_coordination_engine),
        gather_external_context(incident.location),
    )
    run1.input_snapshot = {**(run1.input_snapshot or {}), "external_context": ext_ctx}

    if run1.status == AgentStatus.FAILED:
        run1.degraded = True
        run1.fallback_used = True
        run1.output_artifact = _fallback_plan_raw({}, {}, ext_ctx, resources_raw, incident.location)
        run1.log_entries.append("Coordination engine failed; using fallback")
        save_agent_run(run1)

    agent_runs.append(run1)
    coord_raw = run1.output_artifact or {}
    if run1.fallback_used:
        plan_raw = coord_raw
    else:
        plan_raw = _lean_coord_to_plan_raw(coord_raw)
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] coordination engine done ({_elapsed(t1)})")

    # Phase 2: Lean Communications
    t2 = time.monotonic()
    facility_strs = [
        f"{f.get('hospital', '')} ({f.get('patients_assigned', 0)} pts)"
        for f in plan_raw.get("patient_flow", {}).get("facility_assignments", [])[:3]
    ]
    run2 = _make_run(incident, version, AgentType.COMMUNICATIONS, {
        "situation_summary": (
            f"{incident.incident_type} at {incident.location}. "
            f"Patients: {coord_raw.get('patient_count', 0)} "
            f"(critical:{coord_raw.get('critical', 0)} moderate:{coord_raw.get('moderate', 0)} minor:{coord_raw.get('minor', 0)}). "
            f"Risks: {'; '.join(coord_raw.get('top_risks', [])[:2])}."
        ),
        "incident_summary": plan_raw.get("incident_summary", ""),
        "severity": coord_raw.get("severity", "high"),
        "location": incident.location,
        "priorities": plan_raw.get("operational_priorities", []),
        "plan_data": {**coord_raw, "facility_assignments": coord_raw.get("facility_assignments", [])},
        "external_context": ext_ctx,
    })

    if run1.fallback_used:
        run2.output_artifact = await run_communications_fallback(run2)
        run2.status = AgentStatus.COMPLETED
        run2.degraded = True
        run2.fallback_used = True
        run2.runtime = runtime.runtime_name()
        run2.started_at = run2.completed_at = datetime.utcnow()
        run2.latency_ms = 0
        save_agent_run(run2)
    else:
        run2 = await runtime.execute(run2, run_lean_comms)
        if run2.status == AgentStatus.FAILED:
            run2.degraded = True
            run2.fallback_used = True
            run2.output_artifact = await run_communications_fallback(run2)
            save_agent_run(run2)

    agent_runs.append(run2)
    comms_raw = run2.output_artifact or {}
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] communications done ({_elapsed(t2)})")

    # Map comms output
    if "ems_brief" in comms_raw and isinstance(comms_raw["ems_brief"], str):
        comms_artifact = _lean_comms_to_comms(comms_raw)
    else:
        comms_artifact = comms_raw

    # Build diff context if replanning
    diff_summary = None
    changed_sections = None
    if update_text and previous_plan:
        try:
            replan_meta = await call_llm(REPLAN_CONTEXT_PROMPT.format(
                original_summary=previous_plan.incident_summary,
                original_priorities=json.dumps(previous_plan.operational_priorities),
                update_text=update_text,
            ), caller="replan_context", response_model=ReplanContextOutput)
            diff_summary = replan_meta.get("reasoning", "")
            changed_sections = replan_meta.get("affected_sections", [])
        except Exception:
            diff_summary = f"Plan revised: {update_text}"

    ext_summary = _build_ext_summary(ext_ctx, runtime, {})
    parsed = _lean_parser_to_parsed(coord_raw)
    risk = _lean_risk_to_risk(coord_raw)

    plan = _build_plan_version(
        incident, version, update_text, parsed, risk, plan_raw,
        comms_artifact, diff_summary, changed_sections, ext_summary,
    )

    elapsed_ms = int((time.monotonic() - t_pipeline) * 1000)
    _print_swarm_truth(agent_runs, elapsed_ms)
    return plan, agent_runs


async def generate_plan(
    incident: Incident,
    version: int,
    update_text: Optional[str] = None,
    previous_plan: Optional[PlanVersion] = None,
) -> tuple[PlanVersion, list[AgentRun]]:
    fast_mode = os.environ.get("FAST_MODE", "1") not in ("0", "false", "no")
    if fast_mode:
        return await generate_plan_fast(incident, version, update_text, previous_plan)

    runtime = get_runtime()
    agent_runs: list[AgentRun] = []
    resources_raw = [r.model_dump() for r in incident.resources]
    t_pipeline = time.monotonic()

    print(f"\n[{datetime.utcnow().strftime('%H:%M:%S')}] === START ANALYZE incident={incident.id[:8]} v{version} ===")
    runtime_label = {
        "local": "local (K2 only)",
        "dedalus": "dedalus (DedalusRunner)",
        "swarm": "swarm (Dedalus Machines)",
    }.get(runtime.runtime_name(), runtime.runtime_name())
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Runtime: {runtime_label}")

    full_report = incident.report if not update_text else f"{incident.report}\n\nFIELD UPDATE: {update_text}"

    def _elapsed(t: float) -> str:
        return f"{int((time.monotonic() - t) * 1000)}ms"

    def _run_elapsed(run: AgentRun) -> str:
        return f"{run.latency_ms if run.latency_ms is not None else 0}ms"

    # ═══════════════════════════════════════════════════════════
    # PHASE 1 (parallel): Lean Situation + external context
    # ═══════════════════════════════════════════════════════════
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] -- PHASE 1: Situation Unit + external context (parallel) --")
    t1 = time.monotonic()

    hospital_capacities_raw = [h.model_dump() for h in incident.hospital_capacities]
    run1 = _make_run(incident, version, AgentType.INCIDENT_PARSER, {
        "incident_type": incident.incident_type,
        "report": full_report[:1500],
        "location": incident.location,
        "severity_hint": incident.severity_hint,
        "resources": resources_raw,
        "hospital_capacities": hospital_capacities_raw,
        "external_context": {},
    })

    run1, ext_ctx = await asyncio.gather(
        runtime.execute(run1, run_lean_parser),
        gather_external_context(incident.location),
    )
    run1.input_snapshot = {**(run1.input_snapshot or {}), "external_context": ext_ctx}
    if run1.status == AgentStatus.FAILED:
        run1.degraded = True
        run1.fallback_used = True
        run1.output_artifact = _lean_parser_to_parsed(_fallback_incident_parse(incident, ext_ctx))
        run1.log_entries.append("Situation parse failed; using fallback")
        save_agent_run(run1)
    agent_runs.append(run1)
    lean_parsed = run1.output_artifact or {}
    parsed = _lean_parser_to_parsed(lean_parsed) if lean_parsed.get("patient_count") is not None else lean_parsed

    _log_agent_outcome(run1, label="incident_parser", elapsed=_elapsed(t1))
    _raise_if_required_agent_failed(run1, agent_runs, t_pipeline)

    # ═══════════════════════════════════════════════════════════
    # PHASE 2 / 3a: Lean Risk + Lean Planner (parallel)
    # Risk gets compact situation summary only.
    # Planner gets compact situation + compact risk.
    # ═══════════════════════════════════════════════════════════
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] -- PHASE 2/3a: Lean Risk + Lean Planner (parallel) --")
    t23 = time.monotonic()

    fallback_risk = _fallback_risk_context(parsed, ext_ctx, "pending threat analysis")
    run2 = _make_run(incident, version, AgentType.RISK_ASSESSOR, {
        "parsed_data": parsed,
        "external_context": ext_ctx,
    })
    run3 = _make_run(incident, version, AgentType.ACTION_PLANNER, {
        "parsed_data": parsed,
        "risk_data": fallback_risk,
        "location": incident.location,
        "hospital_capacities": hospital_capacities_raw,
        "external_context": ext_ctx,
    })

    async def _execute_risk() -> AgentRun:
        local_run2 = await runtime.execute(run2, run_lean_risk)
        if local_run2.status == AgentStatus.FAILED:
            local_run2.degraded = True
            local_run2.fallback_used = True
            local_run2.output_artifact = _fallback_risk_context(parsed, ext_ctx, local_run2.error_kind or "failure")
            local_run2.log_entries.append("Lean risk assessor failed; using fallback")
            save_agent_run(local_run2)
        return local_run2

    async def _execute_planner() -> AgentRun:
        local_run3 = await runtime.execute(run3, run_lean_planner)
        if local_run3.status == AgentStatus.FAILED:
            local_run3.degraded = True
            local_run3.fallback_used = True
            local_run3.output_artifact = _fallback_plan_raw(parsed, {}, ext_ctx, resources_raw, incident.location)
            local_run3.log_entries.append("Lean planner failed; using fallback")
            save_agent_run(local_run3)
        return local_run3

    run2, run3 = await asyncio.gather(_execute_risk(), _execute_planner())

    agent_runs.append(run3)
    agent_runs.insert(1, run2)
    lean_risk = run2.output_artifact or {}
    lean_plan = run3.output_artifact or {}
    risk = _lean_risk_to_risk(lean_risk) if "severity" in lean_risk else lean_risk
    plan_raw = _lean_planner_to_plan_raw(lean_plan) if "immediate_actions" in lean_plan and isinstance(lean_plan.get("immediate_actions", [None])[0] if lean_plan.get("immediate_actions") else [None], str) else lean_plan
    _log_agent_outcome(run2, label="risk_assessor", elapsed=_run_elapsed(run2))
    _log_agent_outcome(run3, label="action_planner", elapsed=_run_elapsed(run3))

    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] -- PHASE 3b: Communications (lean) --")
    t3 = time.monotonic()
    run4 = _make_run(incident, version, AgentType.COMMUNICATIONS, {
        "situation_summary": _fmt_situation_compact(parsed),
        "incident_summary": plan_raw.get("incident_summary", ""),
        "severity": risk.get("severity_level", risk.get("severity", "unknown")),
        "location": incident.location,
        "priorities": plan_raw.get("operational_priorities", []),
        "plan_data": lean_plan,
        "external_context": ext_ctx,
    })
    if run3.fallback_used:
        run4.runtime = runtime.runtime_name()
        run4.started_at = datetime.utcnow()
        run4.output_artifact = await run_communications_fallback(run4)
        run4.completed_at = datetime.utcnow()
        run4.latency_ms = 0
        run4.status = AgentStatus.COMPLETED
        run4.degraded = True
        run4.fallback_used = True
        save_agent_run(run4)
    else:
        run4 = await runtime.execute(run4, run_lean_comms)
        if run4.status == AgentStatus.FAILED:
            run4.degraded = True
            run4.fallback_used = True
            run4.output_artifact = await run_communications_fallback(run4)
            save_agent_run(run4)
    agent_runs.append(run4)
    comms_raw4 = run4.output_artifact or {}
    if "ems_brief" in comms_raw4 and isinstance(comms_raw4.get("ems_brief"), str):
        comms_raw4 = _lean_comms_to_comms(comms_raw4)
    _log_agent_outcome(run4, label="communications", elapsed=_run_elapsed(run4))
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] PHASE 3 done ({_elapsed(t3)})")

    diff_summary = None
    changed_sections = None
    if update_text and previous_plan:
        try:
            replan_meta = await call_llm(REPLAN_CONTEXT_PROMPT.format(
                original_summary=previous_plan.incident_summary,
                original_priorities=json.dumps(previous_plan.operational_priorities),
                update_text=update_text,
            ), caller="replan_context", response_model=ReplanContextOutput)
            diff_summary = replan_meta.get("reasoning", "")
            changed_sections = replan_meta.get("affected_sections", [])
        except Exception:
            diff_summary = f"Plan revised: {update_text}"

    ext_summary = _build_ext_summary(ext_ctx, runtime, risk)
    ext_summary["primary_access_route"] = plan_raw.get("primary_access_route")
    ext_summary["alternate_access_route"] = plan_raw.get("alternate_access_route")

    plan = _build_plan_version(
        incident, version, update_text, parsed, risk, plan_raw,
        comms_raw4, diff_summary, changed_sections, ext_summary,
    )

    elapsed_ms = int((time.monotonic() - t_pipeline) * 1000)
    _print_swarm_truth(agent_runs, elapsed_ms)
    return plan, agent_runs
