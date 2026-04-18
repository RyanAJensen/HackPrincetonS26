from __future__ import annotations
from datetime import datetime
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

from models.incident import Incident, IncidentCreate, IncidentUpdate, IncidentStatus
from models.plan import PlanVersion, PlanDiff
from models.agent import AgentRun
from agents.orchestrator import generate_plan, _generate_diff
from db import (
    save_incident, get_incident, list_incidents,
    save_plan_version, get_plan_version, get_latest_plan, list_plan_versions,
    save_agent_run, list_agent_runs,
)
from data.seed import DEMO_SCENARIOS, CAMPUS_RESOURCES
from runtime import get_runtime

router = APIRouter()


class AnalysisResponse(BaseModel):
    incident: Incident
    plan: PlanVersion
    agent_runs: list[AgentRun]


class ReplanResponse(BaseModel):
    incident: Incident
    plan: PlanVersion
    diff: PlanDiff
    agent_runs: list[AgentRun]


@router.get("/health")
async def health():
    return {"status": "ok", "service": "sentinel"}


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

        return AnalysisResponse(incident=incident, plan=plan, agent_runs=runs)
    except Exception as e:
        incident.status = IncidentStatus.PENDING
        save_incident(incident)
        raise HTTPException(500, f"Analysis failed: {e}")


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

        return ReplanResponse(incident=incident, plan=new_plan, diff=diff, agent_runs=runs)
    except Exception as e:
        incident.status = IncidentStatus.ACTIVE
        save_incident(incident)
        raise HTTPException(500, f"Replanning failed: {e}")


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
    """Probe Dedalus API directly — lists machines, confirms key is working."""
    import os
    api_key = os.getenv("DEDALUS_API_KEY")
    result: dict = {
        "sdk_available": False,
        "api_key_present": bool(api_key),
        "runtime": get_runtime().runtime_name(),
        "machines": [],
        "error": None,
    }

    try:
        import dedalus_sdk
        result["sdk_available"] = True
    except ImportError:
        result["error"] = "dedalus_sdk not installed"
        return result

    if not api_key:
        result["error"] = "DEDALUS_API_KEY not set"
        return result

    try:
        client = dedalus_sdk.AsyncDedalus(api_key=api_key)
        page = await client.machines.list()
        machines = []
        async for m in page:
            machines.append({
                "machine_id": m.machine_id,
                "phase": m.status.phase if m.status else "unknown",
            })
        result["machines"] = machines
        result["machine_count"] = len(machines)
    except Exception as e:
        result["error"] = str(e)

    return result
