"""ContextVar for the active DedalusRunner (set only during DedalusAgentRuntime.execute)."""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Optional

# DedalusRunner instance or None when using K2/local
dedalus_runner_ctx: ContextVar[Optional[Any]] = ContextVar("dedalus_runner", default=None)
