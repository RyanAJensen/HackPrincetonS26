"""
AgentRuntime abstract base class.
All agent execution goes through this interface so Dedalus and local modes are swappable.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Callable, Awaitable

from models.agent import AgentRun


class AgentRuntime(ABC):
    """Execute an agent function with persistent state and logging."""

    @abstractmethod
    async def execute(
        self,
        run: AgentRun,
        fn: Callable[[AgentRun], Awaitable[dict]],
    ) -> AgentRun:
        """
        Run fn(run) and return the updated AgentRun with output_artifact populated.
        Implementations handle persistence, logging, and error handling.
        """
        ...

    @abstractmethod
    def runtime_name(self) -> str:
        ...
