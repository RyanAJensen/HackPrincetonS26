from __future__ import annotations
from datetime import datetime
import inspect
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, Any

from models.incident import Incident, IncidentCreate, IncidentUpdate, IncidentStatus
from models.plan import PlanVersion, PlanDiff
from models.agent import AgentFailure, AgentRun, AgentType
from agents.orchestrator import _generate_diff, collect_agent_failures, generate_plan
from agents.specialist_agents import run_incident_parser
from db import (
    save_incident, get_incident, list_incidents,
    save_plan_version, get_plan_version, get_latest_plan, list_plan_versions,
    save_agent_run, list_agent_runs,
)
from data.seed import DEMO_SCENARIOS, CAMPUS_RESOURCES
from runtime import get_runtime
from runtime.dedalus_client_config import dedalus_byok_configured
from runtime.dedalus_output import extract_final_output, validate_response_output

router = APIRouter()


def _http_status_for_runtime_error(exc: Exception) -> int:
    msg = str(exc)
    if "insufficient_balance" in msg or "Error code: 402" in msg:
        return 402
    if any(
        token in msg
        for token in (
            "Dedalus runtime requested",
            "Dedalus Machines runtime requested",
            "Dedalus Machines API",
            "DEDALUS_API_KEY",
            "dedalus_labs",
            "DedalusRunner(client)",
            "no DedalusRunner is available",
        )
    ):
        return 503
    return 500


def _augment_runtime_error_message(exc: Exception) -> str:
    msg = str(exc)
    if "insufficient_balance" in msg or "Error code: 402" in msg:
        if dedalus_byok_configured():
            return (
                f"{msg}. Dedalus routing reached a 402 even with BYOK configured; "
                "verify the upstream provider key and provider account balance."
            )
        return (
            f"{msg}. Dedalus Machine credits do not cover default DedalusRunner model calls. "
            "Add Dedalus API/model credits, or configure BYOK with "
            "DEDALUS_PROVIDER / DEDALUS_PROVIDER_KEY / DEDALUS_PROVIDER_MODEL."
        )
    return msg


class AnalysisResponse(BaseModel):
    incident: Incident
    plan: PlanVersion
    agent_runs: list[AgentRun]
    agent_failures: list[AgentFailure] = Field(default_factory=list)


class ReplanResponse(BaseModel):
    incident: Incident
    plan: PlanVersion
    diff: PlanDiff
    agent_runs: list[AgentRun]
    agent_failures: list[AgentFailure] = Field(default_factory=list)


class DebugDedalusSmokeOutput(BaseModel):
    ok: bool


@router.get("/health")
async def health():
    return {"status": "ok", "service": "unilert"}


# --- Incidents ---

@router.post("/incidents", response_model=Incident)
async def create_incident(body: IncidentCreate):
    incident = Incident(**body.model_dump())
    save_incident(incident)
    return incident


@router.get("/incidents", response_model=list[Incident])
async def get_incidents():
    return list_incidents()


@router.get("/incidents/{incident_id}", response_model=Incident)
async def get_incident_detail(incident_id: str):
    incident = get_incident(incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")
    return incident


# --- Analysis / Plan Generation ---

@router.post("/incidents/{incident_id}/analyze", response_model=AnalysisResponse)
async def analyze_incident(incident_id: str):
    incident = get_incident(incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")
    if incident.status == IncidentStatus.ANALYZING:
        raise HTTPException(409, "Analysis already in progress")

    incident.status = IncidentStatus.ANALYZING
    incident.updated_at = datetime.utcnow()
    save_incident(incident)

    try:
        version = incident.current_plan_version + 1
        plan, runs = await generate_plan(incident, version)

        incident.current_plan_version = version
        incident.status = IncidentStatus.ACTIVE
        incident.updated_at = datetime.utcnow()
        save_incident(incident)
        save_plan_version(plan)

        return AnalysisResponse(
            incident=incident,
            plan=plan,
            agent_runs=runs,
            agent_failures=collect_agent_failures(runs),
        )
    except Exception as e:
        incident.status = IncidentStatus.PENDING
        save_incident(incident)
        detail = _augment_runtime_error_message(e)
        raise HTTPException(_http_status_for_runtime_error(e), f"Analysis failed: {detail}")


# --- Replanning ---

@router.post("/incidents/{incident_id}/replan", response_model=ReplanResponse)
async def replan_incident(incident_id: str, body: IncidentUpdate):
    incident = get_incident(incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")
    if incident.status not in (IncidentStatus.ACTIVE, IncidentStatus.REPLANNING):
        raise HTTPException(409, "Incident is not active")

    previous_plan = get_latest_plan(incident_id)
    if not previous_plan:
        raise HTTPException(409, "No existing plan to update — run /analyze first")

    if body.updated_resources:
        incident.resources = body.updated_resources

    incident.status = IncidentStatus.REPLANNING
    incident.updated_at = datetime.utcnow()
    save_incident(incident)

    try:
        version = incident.current_plan_version + 1
        new_plan, runs = await generate_plan(incident, version, update_text=body.update_text, previous_plan=previous_plan)

        incident.current_plan_version = version
        incident.status = IncidentStatus.ACTIVE
        incident.updated_at = datetime.utcnow()
        save_incident(incident)
        save_plan_version(new_plan)

        diff = _generate_diff(previous_plan, new_plan)

        return ReplanResponse(
            incident=incident,
            plan=new_plan,
            diff=diff,
            agent_runs=runs,
            agent_failures=collect_agent_failures(runs),
        )
    except Exception as e:
        incident.status = IncidentStatus.ACTIVE
        save_incident(incident)
        detail = _augment_runtime_error_message(e)
        raise HTTPException(_http_status_for_runtime_error(e), f"Replanning failed: {detail}")


# --- Plan Versions ---

@router.get("/incidents/{incident_id}/plans", response_model=list[PlanVersion])
async def list_plans(incident_id: str):
    return list_plan_versions(incident_id)


@router.get("/incidents/{incident_id}/plans/{version}", response_model=PlanVersion)
async def get_plan(incident_id: str, version: int):
    plan = get_plan_version(incident_id, version)
    if not plan:
        raise HTTPException(404, "Plan version not found")
    return plan


@router.get("/incidents/{incident_id}/plans/{v1}/diff/{v2}", response_model=PlanDiff)
async def get_diff(incident_id: str, v1: int, v2: int):
    plan1 = get_plan_version(incident_id, v1)
    plan2 = get_plan_version(incident_id, v2)
    if not plan1 or not plan2:
        raise HTTPException(404, "One or both plan versions not found")
    return _generate_diff(plan1, plan2)


# --- Agent Runs ---

@router.get("/incidents/{incident_id}/agent-runs", response_model=list[AgentRun])
async def get_agent_runs(incident_id: str, plan_version: Optional[int] = None):
    return list_agent_runs(incident_id, plan_version)


# --- Demo ---

@router.get("/demo/scenarios")
async def list_demo_scenarios():
    return [{"id": s["id"], "label": s["label"]} for s in DEMO_SCENARIOS]


@router.post("/demo/scenarios/{scenario_id}/load", response_model=Incident)
async def load_demo_scenario(scenario_id: str):
    scenario = next((s for s in DEMO_SCENARIOS if s["id"] == scenario_id), None)
    if not scenario:
        raise HTTPException(404, "Demo scenario not found")
    incident = Incident(**scenario["incident"].model_dump())
    save_incident(incident)
    return incident


@router.get("/demo/resources")
async def list_campus_resources():
    return CAMPUS_RESOURCES


# --- Debug ---

@router.get("/debug/dedalus")
async def debug_dedalus():
    """Verify Dedalus runner or machines connectivity based on runtime mode."""
    import os
    api_key = os.getenv("DEDALUS_API_KEY")
    runtime_mode = os.getenv("RUNTIME_MODE", "dedalus")
    result: dict = {
        "sdk_available": False,
        "api_key_present": bool(api_key),
        "runtime": runtime_mode,
        "runner_smoke": None,
        "machines_smoke": None,
        "error": None,
    }

    if runtime_mode == "swarm":
        if not api_key:
            result["error"] = "DEDALUS_API_KEY not set"
            return result
        try:
            from runtime.dedalus_dcs import DedalusMachinesClient

            client = DedalusMachinesClient(api_key)
            machines = await client.list_machines()
            result["machines_smoke"] = {
                "visible_count": len(machines),
                "machines": [
                    {
                        "machine_id": machine.machine_id,
                        "phase": machine.status.phase if machine.status else "unknown",
                        "vcpu": machine.vcpu,
                    }
                    for machine in machines[:4]
                ],
            }
        except Exception as e:
            result["error"] = str(e)
        return result

    try:
        from dedalus_labs import AsyncDedalus, DedalusRunner
        result["sdk_available"] = True
    except ImportError as e:
        result["error"] = f"dedalus_labs not installed: {e}"
        return result

    if not api_key:
        result["error"] = "DEDALUS_API_KEY not set"
        return result

    try:
        client = AsyncDedalus(api_key=api_key)
        runner = DedalusRunner(client)
        params = inspect.signature(runner.run).parameters
        if "response_format" not in params and not any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
        ):
            raise RuntimeError("DedalusRunner.run does not support response_format for structured outputs")
        # Minimal runner invocation — confirms key + routing (not full agent JSON)
        smoke = await runner.run(
            input="Reply with ok=true and nothing else.",
            model=os.getenv("DEDALUS_DEBUG_MODEL", "anthropic/claude-sonnet-4-20250514"),
            instructions="You output JSON only.",
            max_steps=2,
            debug=True,
            verbose=True,
            response_format=DebugDedalusSmokeOutput,
        )
        out = validate_response_output(
            extract_final_output(smoke, "debug_dedalus"),
            DebugDedalusSmokeOutput,
            "debug_dedalus",
        )
        result["runner_smoke"] = {
            "final_output_preview": out.model_dump(),
            "final_output_type": type(getattr(smoke, "final_output", None)).__name__,
            "steps_used": getattr(smoke, "steps_used", None),
        }
    except Exception as e:
        result["error"] = str(e)

    return result


class DebugIncidentParserBody(BaseModel):
    """Minimal incident snapshot for isolated Situation Unit (incident_parser) run."""

    incident_type: str = "Isolated debug incident"
    report: str = (
        "Water main break at Main St. Two people with minor injuries. "
        "Scene accessible from east side only."
    )
    location: str = "Main Street & Oak Ave, Princeton NJ"
    severity_hint: Optional[str] = "high"
    resources: list[dict[str, Any]] = Field(default_factory=list)
    external_context: dict[str, Any] = Field(default_factory=dict)


@router.post("/debug/agents/incident-parser")
async def debug_incident_parser(body: DebugIncidentParserBody):
    """
    Run only the Situation Unit (incident_parser) through the same runtime.execute → call_llm path
    as production. Does not run other agents or the full orchestrator.
    Send JSON `{}` to use default scenario fields.
    """
    runtime = get_runtime()
    run = AgentRun(
        incident_id="debug-incident-parser",
        plan_version=1,
        agent_type=AgentType.INCIDENT_PARSER,
        input_snapshot={
            "incident_type": body.incident_type,
            "report": body.report,
            "location": body.location,
            "severity_hint": body.severity_hint,
            "resources": body.resources,
            "external_context": body.external_context,
        },
    )
    finished = await runtime.execute(run, run_incident_parser)
    return {
        "runtime": finished.runtime,
        "status": finished.status.value,
        "error_message": finished.error_message,
        "log_entries": finished.log_entries,
        "output_artifact": finished.output_artifact,
    }
