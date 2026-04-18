"""
DedalusAgentRuntime: executes agents as persistent Dedalus Machine workflows.

Dedalus Machines give each agent a persistent, inspectable execution context
with artifact storage and structured state transitions. Each agent run maps to
one Dedalus machine instance; the machine ID is stored on AgentRun so it can
be resumed, inspected, or replayed.

Architecture:
  1. create_machine() → spawns a new Dedalus Machine with agent metadata
  2. execute_step()   → runs the agent function inside the machine context
  3. persist_artifact() → stores structured output in the machine's artifact store
  4. The machine stays alive for the incident lifecycle, enabling future queries

When DEDALUS_API_KEY is not set, this runtime transparently falls back to
LocalAgentRuntime so development works without credentials.
"""
from __future__ import annotations
import os
import traceback
import uuid
from datetime import datetime
from typing import Callable, Awaitable

from models.agent import AgentRun, AgentStatus
from db import save_agent_run
from runtime.base import AgentRuntime

# Dedalus SDK import — optional; falls back gracefully if not installed
try:
    import dedalus  # type: ignore
    DEDALUS_AVAILABLE = True
except ImportError:
    DEDALUS_AVAILABLE = False


class DedalusAgentRuntime(AgentRuntime):
    """
    Wraps each agent run in a Dedalus Machine workflow.
    Falls back to local in-process execution if Dedalus is unavailable.
    """

    def __init__(self):
        self.api_key = os.getenv("DEDALUS_API_KEY")
        self.project_id = os.getenv("DEDALUS_PROJECT_ID", "sentinel")
        self._client = None

    def _get_client(self):
        if self._client is None and DEDALUS_AVAILABLE and self.api_key:
            self._client = dedalus.Client(api_key=self.api_key, project=self.project_id)
        return self._client

    def runtime_name(self) -> str:
        client = self._get_client()
        return "dedalus" if client else "dedalus_fallback"

    async def _create_machine(self, run: AgentRun) -> str:
        """Create a Dedalus Machine for this agent run. Returns machine_id."""
        client = self._get_client()
        machine = await client.machines.create(
            name=f"sentinel-{run.agent_type}-{run.incident_id[:8]}",
            metadata={
                "incident_id": run.incident_id,
                "agent_type": run.agent_type,
                "plan_version": run.plan_version,
                "run_id": run.id,
            },
            tags=["sentinel", "campus-incident", run.agent_type],
        )
        return machine.id

    async def _persist_artifact(self, machine_id: str, artifact: dict):
        """Store agent output as a Dedalus Machine artifact."""
        client = self._get_client()
        await client.machines.artifacts.put(
            machine_id=machine_id,
            key="output",
            value=artifact,
        )

    async def execute(
        self,
        run: AgentRun,
        fn: Callable[[AgentRun], Awaitable[dict]],
    ) -> AgentRun:
        client = self._get_client()

        # Fall back to local execution if Dedalus is not configured
        if not client:
            return await self._local_fallback(run, fn)

        run.runtime = "dedalus"
        run.status = AgentStatus.RUNNING
        run.started_at = datetime.utcnow()

        try:
            machine_id = await self._create_machine(run)
            run.machine_id = machine_id
            run.log_entries.append(
                f"[{run.started_at.isoformat()}] Dedalus machine created: {machine_id}"
            )
            save_agent_run(run)

            result = await fn(run)

            await self._persist_artifact(machine_id, result)
            run.output_artifact = result
            run.status = AgentStatus.COMPLETED
            run.completed_at = datetime.utcnow()
            run.log_entries.append(
                f"[{run.completed_at.isoformat()}] Artifact persisted to machine {machine_id}"
            )

        except Exception as e:
            run.status = AgentStatus.FAILED
            run.completed_at = datetime.utcnow()
            run.error_message = str(e)
            run.log_entries.append(f"[{run.completed_at.isoformat()}] FAILED: {e}")
            run.log_entries.append(traceback.format_exc())

        save_agent_run(run)
        return run

    async def _local_fallback(self, run: AgentRun, fn):
        """Used when Dedalus credentials are absent — identical behavior, different label."""
        run.runtime = "dedalus_fallback"
        run.machine_id = f"local-{uuid.uuid4().hex[:8]}"
        run.status = AgentStatus.RUNNING
        run.started_at = datetime.utcnow()
        run.log_entries.append(
            f"[{run.started_at.isoformat()}] DEDALUS_API_KEY not set — running locally (machine_id={run.machine_id})"
        )
        save_agent_run(run)

        try:
            result = await fn(run)
            run.output_artifact = result
            run.status = AgentStatus.COMPLETED
            run.completed_at = datetime.utcnow()
            run.log_entries.append(f"[{run.completed_at.isoformat()}] Completed (fallback mode)")
        except Exception as e:
            run.status = AgentStatus.FAILED
            run.completed_at = datetime.utcnow()
            run.error_message = str(e)
            run.log_entries.append(f"[{run.completed_at.isoformat()}] FAILED: {e}")

        save_agent_run(run)
        return run
