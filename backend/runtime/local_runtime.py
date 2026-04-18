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
            run.output_artifact = result
            run.status = AgentStatus.COMPLETED
            run.completed_at = datetime.utcnow()
            run.log_entries.append(f"[{run.completed_at.isoformat()}] Completed successfully")
        except Exception as e:
            run.status = AgentStatus.FAILED
            run.completed_at = datetime.utcnow()
            run.error_message = str(e)
            run.log_entries.append(f"[{run.completed_at.isoformat()}] FAILED: {e}")
            run.log_entries.append(traceback.format_exc())

        save_agent_run(run)
        return run
