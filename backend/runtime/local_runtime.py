"""
LocalAgentRuntime: runs agents in-process for development / fallback.
"""
from __future__ import annotations
import traceback
from datetime import datetime
from typing import Callable, Awaitable

from models.agent import AgentRun, AgentStatus
from db import save_agent_run
from runtime.base import AgentRuntime
from runtime.run_state import finalize_run_failure, finalize_run_success


class LocalAgentRuntime(AgentRuntime):
    def runtime_name(self) -> str:
        return "local"

    async def execute(
        self,
        run: AgentRun,
        fn: Callable[[AgentRun], Awaitable[dict]],
    ) -> AgentRun:
        run.runtime = "local"
        run.status = AgentStatus.RUNNING
        run.started_at = datetime.utcnow()
        run.log_entries.append(f"[{run.started_at.isoformat()}] Starting {run.agent_type} (local runtime)")
        save_agent_run(run)

        try:
            result = await fn(run)
            finalize_run_success(run, result, "Completed successfully")
        except Exception as e:
            finalize_run_failure(run, e, "FAILED", traceback.format_exc())

        save_agent_run(run)
        return run
