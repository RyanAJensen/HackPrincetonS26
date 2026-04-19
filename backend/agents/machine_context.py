"""ContextVars for the active Dedalus Machines executor during swarm runtime."""
from __future__ import annotations

from contextvars import ContextVar
from typing import Protocol

from pydantic import BaseModel


class DedalusMachineExecutor(Protocol):
    async def run_prompt_on_machine(
        self,
        *,
        machine_id: str,
        prompt: str,
        system: str,
        caller: str,
        response_model: type[BaseModel] | None = None,
    ) -> str:
        """Execute one prompt on a specific Dedalus Machine and return stdout."""


dedalus_machine_executor_ctx: ContextVar[DedalusMachineExecutor | None] = ContextVar(
    "dedalus_machine_executor_ctx",
    default=None,
)
dedalus_machine_id_ctx: ContextVar[str | None] = ContextVar(
    "dedalus_machine_id_ctx",
    default=None,
)
