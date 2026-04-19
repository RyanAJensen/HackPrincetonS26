"""ContextVar for the active DedalusRunner (set only during DedalusAgentRuntime.execute)."""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Optional

# DedalusRunner instance or None when using K2/local
dedalus_runner_ctx: ContextVar[Optional[Any]] = ContextVar("dedalus_runner", default=None)

# Set to True when Dedalus returns a 401 — disables runner for subsequent calls
_dedalus_auth_failed: bool = False


def mark_dedalus_auth_failed() -> None:
    global _dedalus_auth_failed
    _dedalus_auth_failed = True
    print("[Dedalus] Auth failure recorded — all subsequent calls will use local K2")


def is_dedalus_auth_failed() -> bool:
    return _dedalus_auth_failed
