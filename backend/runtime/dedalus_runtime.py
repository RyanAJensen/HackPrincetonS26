"""
Dedalus execution via DedalusRunner (official API) — no persistent machines, no filesystem artifacts.

Uses:
  from dedalus_labs import AsyncDedalus, DedalusRunner
  runner = DedalusRunner(AsyncDedalus(api_key=...))

Agents call `call_llm()` which reads the active runner from context (set during execute).
Replan / ad-hoc `call_llm` uses a process-wide shared runner when RUNTIME_MODE != local.

Runtime label:
  "dedalus" — DedalusRunner completed the agent step
  "local"   — explicit RUNTIME_MODE=local only
"""
from __future__ import annotations
import os
import traceback
from datetime import datetime
from typing import Callable, Awaitable, Any

from models.agent import AgentRun, AgentStatus
from db import save_agent_run
from runtime.base import AgentRuntime
from runtime.dedalus_client_config import build_dedalus_client_kwargs, describe_dedalus_billing_mode
from runtime.run_state import finalize_run_failure, finalize_run_success

DEDALUS_IMPORT_ERROR: str | None = None
try:
    from dedalus_labs import AsyncDedalus, DedalusRunner

    DEDALUS_LABS_AVAILABLE = True
except ImportError as _e:
    DEDALUS_IMPORT_ERROR = str(_e)
    AsyncDedalus = None  # type: ignore
    DedalusRunner = None  # type: ignore
    DEDALUS_LABS_AVAILABLE = False

# Agent type → ICS role label (logging only; no machine routing)
AGENT_ROLE_MAP: dict[str, str] = {
    "incident_parser": "situation",
    "risk_assessor": "intelligence",
    "action_planner": "operations",
    "communications": "communications",
}

ROLE_LABELS: dict[str, str] = {
    "situation": "Situation Unit",
    "intelligence": "Intelligence",
    "operations": "Operations Planner",
    "communications": "Communications Officer",
}

_shared_client: Any = None
_shared_runner: Any = None


def get_shared_dedalus_runner() -> Any | None:
    """
    Lazy singleton for replan / call_llm when outside AgentRuntime.execute.
    Returns None if API key missing or SDK unavailable.
    """
    global _shared_client, _shared_runner
    if not DEDALUS_LABS_AVAILABLE:
        return None
    api_key = os.getenv("DEDALUS_API_KEY")
    if not api_key:
        return None
    if _shared_runner is None:
        _shared_client = AsyncDedalus(**build_dedalus_client_kwargs(api_key))
        _shared_runner = DedalusRunner(_shared_client)
        print(
            "[Dedalus] DedalusRunner singleton initialized "
            f"(shared for replan + agents, billing={describe_dedalus_billing_mode()})"
        )
    return _shared_runner


class DedalusAgentRuntime(AgentRuntime):
    """Runs specialist agents through DedalusRunner; LLM path is wired in agents/llm.py."""

    def __init__(self) -> None:
        self.api_key = os.getenv("DEDALUS_API_KEY")
        self._client: Any = None
        self._runner: Any = None

        if not DEDALUS_LABS_AVAILABLE:
            detail = DEDALUS_IMPORT_ERROR or "unknown ImportError"
            raise RuntimeError(
                "Dedalus runtime requested but dedalus_labs is unavailable. "
                f"Import error: {detail}. Install dedalus_labs or set RUNTIME_MODE=local explicitly."
            )
        if not self.api_key:
            raise RuntimeError(
                "Dedalus runtime requested but DEDALUS_API_KEY is not set. "
                "Set DEDALUS_API_KEY or use RUNTIME_MODE=local explicitly."
            )

        print(
            "[Dedalus] Mode: DedalusRunner (AsyncDedalus) — no machine lifecycle, "
            "outputs from awaited result.final_output only; "
            f"billing={describe_dedalus_billing_mode()}"
        )

    def _ensure_runner(self) -> Any:
        if not DEDALUS_LABS_AVAILABLE or not self.api_key:
            raise RuntimeError("DedalusRunner requested but SDK or API key unavailable")
        if self._runner is None:
            self._client = AsyncDedalus(**build_dedalus_client_kwargs(self.api_key))
            self._runner = DedalusRunner(self._client)
            print("[Dedalus] DedalusRunner bound to DedalusAgentRuntime")
        return self._runner

    def runtime_name(self) -> str:
        return "dedalus"

    async def execute(
        self,
        run: AgentRun,
        fn: Callable[[AgentRun], Awaitable[dict]],
    ) -> AgentRun:
        from agents.dedalus_context import dedalus_runner_ctx

        runner = self._ensure_runner()
        token = dedalus_runner_ctx.set(runner)
        run.status = AgentStatus.RUNNING
        run.started_at = datetime.utcnow()
        run.runtime = "dedalus"
        run.machine_id = None
        role = AGENT_ROLE_MAP.get(run.agent_type, "situation")
        run.log_entries.append(
            f"DedalusRunner — role={ROLE_LABELS.get(role, role)} agent={run.agent_type} "
            f"(debug={os.getenv('DEDALUS_RUNNER_DEBUG', 'true')}, verbose={os.getenv('DEDALUS_RUNNER_VERBOSE', 'true')})"
        )
        save_agent_run(run)

        try:
            result = await fn(run)
            finalize_run_success(
                run,
                result,
                "DedalusRunner — agent completed; awaited result.final_output validated via structured output schema",
            )
        except Exception as e:
            finalize_run_failure(run, e, "DedalusRunner FAILED", traceback.format_exc())
        finally:
            dedalus_runner_ctx.reset(token)

        save_agent_run(run)
        return run
