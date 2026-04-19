"""Standalone worker uploaded to each Dedalus Machine for agent execution."""
from __future__ import annotations

import argparse
import asyncio
import base64
import inspect
import json
import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from dedalus_labs import AsyncDedalus, DedalusRunner


class StrictSchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IncidentParserMedicalImpactOutput(StrictSchemaModel):
    affected_population: str
    estimated_injured: str
    critical: int
    moderate: int
    minor: int
    at_risk_groups: list[str]


class IncidentParserOutput(StrictSchemaModel):
    parsed_type: str
    confirmed_location: str
    operational_period: str
    affected_population: str
    key_hazards: list[str]
    immediate_life_safety_threat: bool
    infrastructure_impact: Optional[str]
    time_sensitivity: Literal["immediate", "urgent", "moderate", "low"]
    confirmed_facts: list[str]
    unknowns: list[str]
    location_notes: str
    medical_impact: IncidentParserMedicalImpactOutput


class RiskAssessorOutput(StrictSchemaModel):
    severity_level: Literal["low", "medium", "high", "critical"]
    confidence: float
    incident_objectives: list[str]
    primary_risks: list[str]
    safety_considerations: list[str]
    weather_driven_threats: list[str]
    replan_triggers: list[str]
    healthcare_risks: list[str]


class PlannerActionOutput(StrictSchemaModel):
    description: str
    assigned_to: str
    timeframe: str


class ResourceAssignmentsOutput(StrictSchemaModel):
    operations: list[str]
    logistics: list[str]
    communications: list[str]
    command: list[str]


class PlannerAssumptionOutput(StrictSchemaModel):
    description: str
    impact: str
    confidence: float


class TriagePriorityOutput(StrictSchemaModel):
    priority: int
    label: str
    estimated_count: int
    required_response: str
    required_action: str


class PatientTransportOutput(StrictSchemaModel):
    primary_facilities: list[str]
    alternate_facilities: list[str]
    transport_routes: list[str]
    constraints: list[str]
    fallback_if_primary_unavailable: str


class ActionPlannerOutput(StrictSchemaModel):
    incident_summary: str
    operational_priorities: list[str]
    immediate_actions: list[PlannerActionOutput]
    short_term_actions: list[PlannerActionOutput]
    ongoing_actions: list[PlannerActionOutput]
    resource_assignments: ResourceAssignmentsOutput
    primary_access_route: str
    alternate_access_route: str
    assumptions: list[PlannerAssumptionOutput]
    missing_information: list[str]
    triage_priorities: list[TriagePriorityOutput]
    patient_transport: PatientTransportOutput


class EMSBriefOutput(StrictSchemaModel):
    audience: str
    channel: str
    urgency: str
    body: str


class DirectedCommunicationOutput(StrictSchemaModel):
    audience: str
    channel: str
    urgency: str
    subject: str
    body: str


class CommunicationsOutput(StrictSchemaModel):
    ems_brief: EMSBriefOutput
    hospital_notification: DirectedCommunicationOutput
    public_advisory: DirectedCommunicationOutput
    administration_update: DirectedCommunicationOutput


class ReplanContextOutput(StrictSchemaModel):
    significant_change: bool
    affected_sections: list[str]
    reasoning: str
    update_context: str


RESPONSE_MODELS: dict[str, type[BaseModel]] = {
    "IncidentParserOutput": IncidentParserOutput,
    "RiskAssessorOutput": RiskAssessorOutput,
    "ActionPlannerOutput": ActionPlannerOutput,
    "CommunicationsOutput": CommunicationsOutput,
    "ReplanContextOutput": ReplanContextOutput,
}


def _accepts_argument(params: dict[str, inspect.Parameter], name: str) -> bool:
    if not params:
        return True
    if name in params:
        return True
    return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())


def _load_machine_env() -> None:
    env_path = Path("/home/machine/unilert/.env")
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)


def _ensure_not_awaitable(value: object, label: str) -> None:
    if inspect.isawaitable(value):
        raise RuntimeError(f"{label} is awaitable; DedalusRunner.run(...) must be awaited")


def _build_client_kwargs(api_key: str) -> dict:
    kwargs = {"api_key": api_key}
    provider = os.getenv("DEDALUS_PROVIDER")
    provider_key = os.getenv("DEDALUS_PROVIDER_KEY")
    provider_model = os.getenv("DEDALUS_PROVIDER_MODEL")
    if provider:
        kwargs["provider"] = provider
    if provider_key:
        kwargs["provider_key"] = provider_key
    if provider_model:
        kwargs["provider_model"] = provider_model
    return kwargs


async def _run(payload: dict) -> object:
    _load_machine_env()

    api_key = os.getenv("DEDALUS_API_KEY")
    if not api_key:
        raise RuntimeError("DEDALUS_API_KEY is not set on the Dedalus machine")

    model_name = payload.get("model") or os.getenv("DEDALUS_MODEL", "anthropic/claude-sonnet-4-20250514")
    prompt = payload["prompt"]
    system = payload["system"]
    response_model_name = payload.get("response_model")
    response_model = RESPONSE_MODELS.get(response_model_name) if response_model_name else None

    client = AsyncDedalus(**_build_client_kwargs(api_key))
    runner = DedalusRunner(client)

    try:
        params = inspect.signature(runner.run).parameters
    except (TypeError, ValueError):
        params = {}

    kwargs: dict = {}
    if _accepts_argument(params, "model"):
        kwargs["model"] = model_name
    if _accepts_argument(params, "input"):
        kwargs["input"] = prompt
    if _accepts_argument(params, "messages") and "input" not in kwargs:
        kwargs["messages"] = [{"role": "user", "content": prompt}]
    if _accepts_argument(params, "instructions"):
        kwargs["instructions"] = system
    elif _accepts_argument(params, "system"):
        kwargs["system"] = system
    if _accepts_argument(params, "max_steps"):
        kwargs["max_steps"] = int(payload.get("max_steps", 5))
    if _accepts_argument(params, "debug"):
        kwargs["debug"] = bool(payload.get("debug", False))
    if _accepts_argument(params, "verbose"):
        kwargs["verbose"] = bool(payload.get("verbose", False))
    if response_model is not None:
        if response_model_name not in RESPONSE_MODELS:
            raise RuntimeError(f"Unknown response model requested on machine: {response_model_name}")
        kwargs["response_format"] = response_model

    pending = runner.run(**kwargs)
    if not inspect.isawaitable(pending):
        raise RuntimeError("DedalusRunner.run returned a non-awaitable result on the machine")

    result = await pending
    _ensure_not_awaitable(result, "runner result")
    final_output = getattr(result, "final_output", None)
    if final_output is None:
        raise RuntimeError("DedalusRunner result.final_output is missing")
    _ensure_not_awaitable(final_output, "runner result.final_output")

    if isinstance(final_output, BaseModel):
        return final_output.model_dump()
    if isinstance(final_output, dict):
        return final_output
    if isinstance(final_output, str):
        return final_output.strip()
    raise RuntimeError(f"Unsupported final_output type from machine worker: {type(final_output).__name__}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload-b64", required=True)
    args = parser.parse_args()
    payload = json.loads(base64.b64decode(args.payload_b64).decode("utf-8"))
    try:
        result = asyncio.run(_run(payload))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, separators=(",", ":")))
        return 1
    if isinstance(result, str):
        print(result)
    else:
        print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
