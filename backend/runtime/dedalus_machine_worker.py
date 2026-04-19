"""Standalone worker uploaded to each Dedalus Machine for agent execution."""
from __future__ import annotations

import argparse
import asyncio
import base64
import inspect
import json
import os
import platform
from pathlib import Path
from typing import Literal, Optional

import httpx

WORKER_VERSION = "9"
WORKER_ROOT = Path(
    os.getenv(
        "DEDALUS_MACHINE_WORKER_ROOT",
        "/dev/shm/unilert",
    )
)

try:
    from pydantic import BaseModel, ConfigDict, Field

    PYDANTIC_IMPORT_ERROR: str | None = None
except Exception as exc:  # pragma: no cover - exercised on real machine bootstrap only
    BaseModel = object  # type: ignore[assignment]

    def ConfigDict(**kwargs):  # type: ignore[override]
        return dict(kwargs)

    def Field(*args, **kwargs):  # type: ignore[override]
        return kwargs.get("default")

    PYDANTIC_IMPORT_ERROR = str(exc)

try:
    from dedalus_labs import AsyncDedalus, DedalusRunner

    DEDALUS_IMPORT_ERROR: str | None = None
except Exception as exc:  # pragma: no cover - exercised on real machine bootstrap only
    AsyncDedalus = None  # type: ignore[assignment]
    DedalusRunner = None  # type: ignore[assignment]
    DEDALUS_IMPORT_ERROR = str(exc)


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


class LeanParserOutput(StrictSchemaModel):
    patient_count: int = 0
    critical: int = 0
    moderate: int = 0
    minor: int = 0
    affected_population: str = ""
    hazards: list[str] = Field(default_factory=list)
    transport_note: str = ""
    hospital_notes: str = ""
    unknowns: list[str] = Field(default_factory=list)
    immediate_threat: bool = False
    time_sensitivity: Literal["immediate", "urgent", "moderate", "low"] = "urgent"
    operational_period: str = ""


class LeanRiskOutput(StrictSchemaModel):
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    top_risks: list[str] = Field(default_factory=list)
    bottlenecks: list[str] = Field(default_factory=list)
    replan_triggers: list[str] = Field(default_factory=list)
    mutual_aid_needed: bool = False
    resource_adequacy: Literal["sufficient", "strained", "insufficient"] = "strained"


class LeanFacilityOutput(StrictSchemaModel):
    hospital: str
    patients: int = 0
    strain: Literal["normal", "elevated", "critical"] = "normal"
    reason: str = ""


class LeanPlannerOutput(StrictSchemaModel):
    summary: str = ""
    total_patients: int = 0
    critical: int = 0
    moderate: int = 0
    minor: int = 0
    facility_assignments: list[LeanFacilityOutput] = Field(default_factory=list)
    distribution_note: str = ""
    immediate_actions: list[str] = Field(default_factory=list)
    short_term_actions: list[str] = Field(default_factory=list)
    priorities: list[str] = Field(default_factory=list)
    key_decision: str = ""
    replan_if: str = ""
    missing_info: list[str] = Field(default_factory=list)
    triage_critical_action: str = ""
    triage_moderate_action: str = ""
    triage_minor_action: str = ""
    primary_route: str = ""
    alternate_route: str = ""


class LeanCoordinationOutput(StrictSchemaModel):
    patient_count: int = 0
    critical: int = 0
    moderate: int = 0
    minor: int = 0
    hazards: list[str] = Field(default_factory=list)
    transport_note: str = ""
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    top_risks: list[str] = Field(default_factory=list)
    bottlenecks: list[str] = Field(default_factory=list)
    summary: str = ""
    facility_assignments: list[LeanFacilityOutput] = Field(default_factory=list)
    immediate_actions: list[str] = Field(default_factory=list)
    priorities: list[str] = Field(default_factory=list)
    key_decision: str = ""
    primary_route: str = ""
    alternate_route: str = ""
    replan_if: str = ""


class LeanCommunicationsOutput(StrictSchemaModel):
    ems_brief: str
    hospital_note: str
    public_message: str
    admin_message: str


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
    "LeanParserOutput": LeanParserOutput,
    "LeanRiskOutput": LeanRiskOutput,
    "LeanPlannerOutput": LeanPlannerOutput,
    "LeanCoordinationOutput": LeanCoordinationOutput,
    "LeanCommunicationsOutput": LeanCommunicationsOutput,
    "ReplanContextOutput": ReplanContextOutput,
}

K2_API_URL_DEFAULT = "https://api.k2think.ai/v1/chat/completions"
K2_MODEL_DEFAULT = "MBZUAI-IFM/K2-Think-v2"
STRICT_JSON_DIRECTIVE = (
    "Do not include any explanation, reasoning, chain-of-thought, or preamble. "
    "Output ONLY valid JSON that matches the response schema exactly."
)
DEFAULT_JSON_SYSTEM = (
    "You are an emergency medical coordination specialist. "
    f"{STRICT_JSON_DIRECTIVE}"
)


def _accepts_argument(params: dict[str, inspect.Parameter], name: str) -> bool:
    if not params:
        return True
    if name in params:
        return True
    return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())


def _build_system_prompt(system: str) -> str:
    base = (system or DEFAULT_JSON_SYSTEM).strip()
    if STRICT_JSON_DIRECTIVE not in base:
        return f"{base}\n\n{STRICT_JSON_DIRECTIVE}"
    return base


def _strict_json_object(raw: object, source: str) -> dict:
    text = str(raw).strip() if raw is not None else ""
    if not text:
        raise RuntimeError(f"{source} returned an empty response")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{source} returned non-JSON output: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{source} returned non-object JSON")
    return parsed


def _validate_payload(payload: dict, response_model: type[BaseModel], source: str) -> dict:
    try:
        return response_model.model_validate(payload).model_dump()
    except Exception as exc:
        raise RuntimeError(
            f"{source} response failed validation against {response_model.__name__}: {exc}"
        ) from exc


def _resolve_backend(payload: dict) -> str:
    requested = str(payload.get("backend") or os.getenv("LLM_BACKEND") or "").strip().lower()
    if requested in {"k2", "dedalus"}:
        return requested
    if os.getenv("K2_API_KEY"):
        return "k2"
    return "dedalus"


def _load_machine_env() -> None:
    env_path = WORKER_ROOT / ".env"
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
    backend = _resolve_backend(payload)

    if payload.get("operation") == "healthcheck":
        return {
            "ok": True,
            "worker_version": WORKER_VERSION,
            "python_version": platform.python_version(),
            "llm_backend": backend,
            "k2_api_key_present": bool(os.getenv("K2_API_KEY")),
            "k2_model": os.getenv("K2_MODEL", K2_MODEL_DEFAULT),
            "dedalus_sdk_available": DEDALUS_IMPORT_ERROR is None,
            "dedalus_import_error": DEDALUS_IMPORT_ERROR,
            "pydantic_available": PYDANTIC_IMPORT_ERROR is None,
            "pydantic_import_error": PYDANTIC_IMPORT_ERROR,
            "dedalus_api_key_present": bool(os.getenv("DEDALUS_API_KEY")),
            "provider_key_present": bool(os.getenv("DEDALUS_PROVIDER_KEY")),
            "response_models": sorted(RESPONSE_MODELS.keys()),
        }

    if PYDANTIC_IMPORT_ERROR is not None:
        raise RuntimeError(f"pydantic is unavailable on the Dedalus machine: {PYDANTIC_IMPORT_ERROR}")

    model_name = payload.get("model") or (
        os.getenv("K2_MODEL", K2_MODEL_DEFAULT)
        if backend == "k2"
        else os.getenv("DEDALUS_MODEL", "anthropic/claude-sonnet-4-20250514")
    )
    prompt = payload["prompt"]
    system = _build_system_prompt(payload["system"])
    response_model_name = payload.get("response_model")
    response_model = RESPONSE_MODELS.get(response_model_name) if response_model_name else None
    timeout_seconds = float(payload.get("timeout_seconds") or os.getenv("DEDALUS_MACHINE_LLM_TIMEOUT_SECONDS", "90"))

    if backend == "k2":
        api_key = os.getenv("K2_API_KEY")
        if not api_key:
            raise RuntimeError("K2_API_KEY is not set on the Dedalus machine")
        if response_model is None:
            raise RuntimeError("K2 machine execution requires a structured response model")
        request_payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "schema": response_model.model_json_schema(),
                    "strict": True,
                },
            },
            "temperature": float(os.getenv("LLM_TEMPERATURE", "0")),
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            try:
                response = await client.post(
                    os.getenv("K2_API_URL", K2_API_URL_DEFAULT),
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=request_payload,
                )
                response.raise_for_status()
            except httpx.TimeoutException as exc:
                raise RuntimeError(f"K2 machine timed out after {int(timeout_seconds)}s") from exc
            except httpx.HTTPStatusError as exc:
                body = (exc.response.text or "").strip()
                detail = body[:240] if body else exc.response.reason_phrase
                raise RuntimeError(
                    f"K2 machine HTTP {exc.response.status_code}: {detail}"
                ) from exc
            except httpx.HTTPError as exc:
                detail = str(exc) or exc.__class__.__name__
                raise RuntimeError(f"K2 machine transport error: {detail}") from exc
            data = response.json()
        try:
            choices = data["choices"]
            message = choices[0]["message"]
            raw_content = message.get("content")
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("K2 machine response is missing choices/message content") from exc
        if isinstance(raw_content, list):
            raw_text = "".join(
                str(part.get("text", "")) if isinstance(part, dict) else str(part)
                for part in raw_content
            ).strip()
        else:
            raw_text = str(raw_content or "").strip()
        return _validate_payload(
            _strict_json_object(raw_text, "K2 machine"),
            response_model,
            "K2 machine",
        )

    api_key = os.getenv("DEDALUS_API_KEY")
    if not api_key:
        raise RuntimeError("DEDALUS_API_KEY is not set on the Dedalus machine")
    if AsyncDedalus is None or DedalusRunner is None:
        raise RuntimeError(
            f"dedalus_labs is unavailable on the Dedalus machine: {DEDALUS_IMPORT_ERROR or 'unknown import error'}"
        )

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
    if _accepts_argument(params, "temperature"):
        kwargs["temperature"] = float(os.getenv("LLM_TEMPERATURE", "0"))
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
    parser.add_argument("--payload-b64")
    parser.add_argument("--payload-path")
    args = parser.parse_args()
    if not args.payload_b64 and not args.payload_path:
        parser.error("one of --payload-b64 or --payload-path is required")
    if args.payload_b64:
        payload = json.loads(base64.b64decode(args.payload_b64).decode("utf-8"))
    else:
        payload = json.loads(Path(args.payload_path).read_text())
    try:
        result = asyncio.run(_run(payload))
    except Exception as exc:
        detail = str(exc) or repr(exc) or exc.__class__.__name__
        print(
            json.dumps(
                {"error": detail, "error_type": exc.__class__.__name__},
                separators=(",", ":"),
            )
        )
        return 1
    if isinstance(result, str):
        print(result)
    else:
        print(json.dumps(result, separators=(",", ":")))
    return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
