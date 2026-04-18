"""
Sentinel IAP Orchestrator — 3-phase parallel execution on persistent Dedalus swarm.

Swarm machine layout:
  Situation Unit machine    → incident_parser
  Intelligence machine      → risk_assessor (K2 Think V2) → action_planner (K2 Think V2)
  Communications machine    → communications_agent

Execution flow:
  Phase 1 (parallel): Situation Unit + external context enrichment
  Phase 2:            Intelligence machine — risk_assessor (K2 deep reasoning)
  Phase 3 (parallel): Intelligence machine — action_planner (K2 routing + triage)
                      Communications machine — communications_agent

K2 Think V2 is the core reasoning engine for the Intelligence machine (risk + planner).
These are the two most analytically complex steps: threat escalation reasoning and
routing-aware operational planning under triage constraints.

Target total latency: ~45s (3 × ~15s LLM phases)
"""
from __future__ import annotations
import asyncio
import json
import time
import traceback as _traceback
from datetime import datetime
from typing import Optional

from models.incident import Incident
from models.plan import (
    PlanVersion, PlanDiff, ActionItem, CommunicationDraft, Assumption,
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
from runtime.dedalus_runtime import AGENT_ROLE_MAP, ROLE_LABELS
from db import save_agent_run, list_swarm_machines


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


def _print_swarm_truth(agent_runs: list[AgentRun], elapsed_ms: int) -> None:
    """Print an unambiguous Dedalus swarm status block at end of each analyze."""
    runtimes = {r.agent_type: r.runtime for r in agent_runs}
    machines = {r.agent_type: r.machine_id for r in agent_runs if r.machine_id}
    swarm = list_swarm_machines()  # role → machine_id from SQLite

    # Artifact counts per run
    def artifact_count(run: AgentRun) -> int:
        return sum(1 for e in (run.log_entries or []) if "✓ Artifact" in e)

    healthy = [r for r in agent_runs if r.runtime == "dedalus"]
    degraded = [r for r in agent_runs if r.runtime == "dedalus_degraded"]
    local = [r for r in agent_runs if r.runtime == "local"]

    if len(healthy) == len(agent_runs):
        status = f"HEALTHY — all {len(healthy)} agents on Dedalus machines ({elapsed_ms}ms)"
    elif degraded or healthy:
        status = f"PARTIAL — {len(healthy)} healthy / {len(degraded)} degraded / {len(local)} local ({elapsed_ms}ms)"
    else:
        status = f"FALLBACK — no Dedalus involvement ({elapsed_ms}ms)"

    print(f"\n{'─'*60}")
    print(f"  Dedalus Swarm: {status}")
    print(f"  Swarm machines registered:")
    for role, mid in swarm.items():
        print(f"    {ROLE_LABELS.get(role, role):<28} {mid[:12]} (role={role})")
    if not swarm:
        print("    (none)")
    print(f"  Per-agent:")
    for run in agent_runs:
        role = AGENT_ROLE_MAP.get(run.agent_type, "?")
        mid = machines.get(run.agent_type, "none")[:12]
        art = artifact_count(run)
        k2 = " [K2 Think V2]" if role == "intelligence" else ""
        print(f"    {run.agent_type:<22} runtime={run.runtime:<18} machine={mid}  artifacts={art}{k2}")
    print(f"{'─'*60}\n")


async def generate_plan(
    incident: Incident,
    version: int,
    update_text: Optional[str] = None,
    previous_plan: Optional[PlanVersion] = None,
) -> tuple[PlanVersion, list[AgentRun]]:
    runtime = get_runtime()
    agent_runs: list[AgentRun] = []
    resources_raw = [r.model_dump() for r in incident.resources]
    t_pipeline = time.monotonic()

    print(f"\n[{datetime.utcnow().strftime('%H:%M:%S')}] ═══ START ANALYZE incident={incident.id[:8]} v{version} ═══")
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Runtime: {runtime.runtime_name()} | Swarm machines: {list_swarm_machines()}")

    full_report = incident.report if not update_text else f"{incident.report}\n\nFIELD UPDATE: {update_text}"

    def _elapsed(t: float) -> str:
        return f"{int((time.monotonic() - t) * 1000)}ms"

    # ═══════════════════════════════════════════════════════════
    # PHASE 1 (parallel)
    # Situation Unit machine: incident_parser
    # External enrichment: geocode + weather + FEMA + routing
    # ═══════════════════════════════════════════════════════════
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] ── PHASE 1: Situation Unit + external context (parallel) ──")
    t1 = time.monotonic()

    run1 = _make_run(incident, version, AgentType.INCIDENT_PARSER, {
        "incident_type": incident.incident_type,
        "report": full_report,
        "location": incident.location,
        "severity_hint": incident.severity_hint,
        "resources": resources_raw,
        "external_context": {},
    })

    run1, ext_ctx = await asyncio.gather(
        runtime.execute(run1, run_incident_parser),
        gather_external_context(incident.location),
    )
    agent_runs.append(run1)
    parsed = run1.output_artifact or {}

    if run1.status.value == "failed":
        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] incident_parser FAILED ({_elapsed(t1)}): {run1.error_message}")
    else:
        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] PHASE 1 done ({_elapsed(t1)}) | parser={run1.runtime} machine={run1.machine_id[:12] if run1.machine_id else 'none'}")

    # ═══════════════════════════════════════════════════════════
    # PHASE 2
    # Intelligence machine: risk_assessor via K2 Think V2
    # Full weather + FEMA context feeds threat analysis.
    # Sequential: risk must complete before planner.
    # ═══════════════════════════════════════════════════════════
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] ── PHASE 2: Intelligence / K2 Think V2 — threat analysis ──")
    t2 = time.monotonic()

    run2 = _make_run(incident, version, AgentType.RISK_ASSESSOR, {
        "parsed_data": parsed,
        "resources": resources_raw,
        "external_context": ext_ctx,
    })
    run2 = await runtime.execute(run2, run_risk_assessor)
    agent_runs.append(run2)
    risk = run2.output_artifact or {}

    if run2.status.value == "failed":
        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] risk_assessor FAILED ({_elapsed(t2)}): {run2.error_message}")
    else:
        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] PHASE 2 done ({_elapsed(t2)}) | risk={run2.runtime} machine={run2.machine_id[:12] if run2.machine_id else 'none'}")

    # ═══════════════════════════════════════════════════════════
    # PHASE 3 (parallel)
    # Intelligence machine: action_planner (K2 Think V2)
    #   — routing-aware ops planning, triage, patient transport
    # Communications machine: communications_agent
    #   — uses parsed situation + risk severity (not planner output)
    #     to run in parallel; comms is formatting-heavy not logic-heavy
    # ═══════════════════════════════════════════════════════════
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] ── PHASE 3: Operations Planner (K2) + Communications (parallel) ──")
    t3 = time.monotonic()

    run3 = _make_run(incident, version, AgentType.ACTION_PLANNER, {
        "parsed_data": parsed,
        "risk_data": risk,
        "resources": resources_raw,
        "location": incident.location,
        "external_context": ext_ctx,
    })

    # Comms runs in parallel with planner on its own machine.
    # It receives the parsed situation + risk severity rather than waiting
    # for the planner's polished summary — acceptable for demo and real-world
    # use where speed matters. Key facts (location, hazards, injuries) are
    # all available from phase 1 + 2 outputs.
    preliminary_summary = (
        f"{incident.incident_type} at {incident.location}. "
        f"Affected: {parsed.get('affected_population', 'unknown')}. "
        + (f"Injuries: {parsed.get('medical_impact', {}).get('estimated_injured', 'unknown')}. " if parsed.get('medical_impact') else "")
        + f"Hazards: {', '.join(parsed.get('key_hazards', [])[:3])}."
    )
    run4 = _make_run(incident, version, AgentType.COMMUNICATIONS, {
        "incident_summary": preliminary_summary,
        "severity": risk.get("severity_level", "unknown"),
        "location": incident.location,
        "priorities": risk.get("incident_objectives", []),
        "missing_info": parsed.get("unknowns", []),
        "triage_priorities": [],  # planner not done yet; comms uses hazard context only
        "external_context": ext_ctx,
    })

    run3, run4 = await asyncio.gather(
        runtime.execute(run3, run_action_planner),
        runtime.execute(run4, run_communications_agent),
    )
    agent_runs.extend([run3, run4])
    plan_raw = run3.output_artifact or {}
    comms = run4.output_artifact or {}

    for label, run in [("action_planner", run3), ("communications", run4)]:
        if run.status.value == "failed":
            print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {label} FAILED: {run.error_message}")
        else:
            mid = run.machine_id[:12] if run.machine_id else "none"
            print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {label} ok | runtime={run.runtime} machine={mid}")

    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] PHASE 3 done ({_elapsed(t3)})")

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

    # --- External context summary for frontend ---
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
        "swarm_machines": {
            role: mid for role, mid in list_swarm_machines().items()
        },
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

    elapsed_ms = int((time.monotonic() - t_pipeline) * 1000)
    _print_swarm_truth(agent_runs, elapsed_ms)

    return plan, agent_runs
