"""
Dedalus execution via DedalusRunner (official API) — no persistent machines, no filesystem artifacts.

Uses:
  from dedalus_labs import AsyncDedalus, DedalusRunner
  runner = DedalusRunner(AsyncDedalus(api_key=...))

Agents call `call_llm()` which reads the active runner from context (set during execute).
Replan / ad-hoc `call_llm` uses a process-wide shared runner when RUNTIME_MODE != local.

Runtime label:
  "dedalus" — DedalusRunner completed the agent step
  "local"   — DEDALUS_API_KEY missing, dedalus_labs not installed, or RUNTIME_MODE=local
"""
from __future__ import annotations
import os
import traceback
from datetime import datetime
from typing import Callable, Awaitable, Any, Optional

from models.agent import AgentRun, AgentStatus
from db import save_agent_run
from runtime.base import AgentRuntime

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
    "action_planner": "intelligence",
    "communications": "communications",
}

ROLE_LABELS: dict[str, str] = {
    "situation": "Situation Unit",
    "intelligence": "Intelligence",
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
        _shared_client = AsyncDedalus(api_key=api_key)
        _shared_runner = DedalusRunner(_shared_client)
        print("[Dedalus] DedalusRunner singleton initialized (shared for replan + agents)")
    return _shared_runner


class DedalusAgentRuntime(AgentRuntime):
    """Runs specialist agents through DedalusRunner; LLM path is wired in agents/llm.py."""

    def __init__(self) -> None:
        self.api_key = os.getenv("DEDALUS_API_KEY")
        self._client: Any = None
        self._runner: Any = None

        require = os.getenv("REQUIRE_DEDALUS", "").lower() == "true"
        if require:
            if not DEDALUS_LABS_AVAILABLE:
                raise RuntimeError("REQUIRE_DEDALUS=true but dedalus_labs is not installed")
            if not self.api_key:
                raise RuntimeError("REQUIRE_DEDALUS=true but DEDALUS_API_KEY is not set")

        if DEDALUS_LABS_AVAILABLE and self.api_key:
            print(
                "[Dedalus] Mode: DedalusRunner (AsyncDedalus) — no machine lifecycle, "
                "outputs from result.final_output only"
            )
        elif not self.api_key:
            print("[Dedalus] DEDALUS_API_KEY not set — agent execution uses local runtime (K2)")
        else:
            detail = DEDALUS_IMPORT_ERROR or "unknown ImportError"
            print(
                "[Dedalus] dedalus_labs SDK unavailable — agent execution uses local runtime (K2). "
                f"Import error: {detail}"
            )

    def _ensure_runner(self) -> Any:
        if not DEDALUS_LABS_AVAILABLE or not self.api_key:
            raise RuntimeError("DedalusRunner requested but SDK or API key unavailable")
        if self._runner is None:
            self._client = AsyncDedalus(api_key=self.api_key)
            self._runner = DedalusRunner(self._client)
            print("[Dedalus] DedalusRunner bound to DedalusAgentRuntime")
        return self._runner

    def runtime_name(self) -> str:
        return "dedalus" if DEDALUS_LABS_AVAILABLE and self.api_key else "local"

    async def execute(
        self,
        run: AgentRun,
        fn: Callable[[AgentRun], Awaitable[dict]],
    ) -> AgentRun:
        if not DEDALUS_LABS_AVAILABLE or not self.api_key:
            strict = os.getenv("DEDALUS_STRICT", "").lower() in ("1", "true", "yes")
            if strict:
                raise RuntimeError(
                    "DEDALUS_STRICT: DedalusAgentRuntime cannot fall back to K2 — "
                    "install dedalus_labs, set DEDALUS_API_KEY, and ensure startup checks passed"
                )
            return await self._local_fallback(run, fn)

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
            run.output_artifact = result
            run.status = AgentStatus.COMPLETED
            run.completed_at = datetime.utcnow()
            run.log_entries.append("DedalusRunner — agent completed; output from result.final_output → parsed JSON")
        except Exception as e:
            run.status = AgentStatus.FAILED
            run.completed_at = datetime.utcnow()
            run.error_message = str(e)
            run.log_entries.append(f"DedalusRunner FAILED: {e}")
            run.log_entries.append(traceback.format_exc())
        finally:
            dedalus_runner_ctx.reset(token)

        save_agent_run(run)
        return run

    async def _local_fallback(self, run: AgentRun, fn: Callable) -> AgentRun:
        from agents.dedalus_context import dedalus_runner_ctx

        run.runtime = "local"
        run.status = AgentStatus.RUNNING
        run.started_at = datetime.utcnow()
        run.machine_id = None
        run.log_entries.append("Local runtime — K2 Think (no DedalusRunner context)")
        save_agent_run(run)
        token = dedalus_runner_ctx.set(None)
        try:
            result = await fn(run)
            run.output_artifact = result
            run.status = AgentStatus.COMPLETED
            run.completed_at = datetime.utcnow()
            run.log_entries.append("Completed (local runtime)")
        except Exception as e:
            run.status = AgentStatus.FAILED
            run.completed_at = datetime.utcnow()
            run.error_message = str(e)
            run.log_entries.append(f"FAILED: {e}")
            run.log_entries.append(traceback.format_exc())
        finally:
            dedalus_runner_ctx.reset(token)

        save_agent_run(run)
        return run
