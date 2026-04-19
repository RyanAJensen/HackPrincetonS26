from __future__ import annotations

from typing import Any

__all__ = ["generate_plan", "_generate_diff"]


def __getattr__(name: str) -> Any:
    if name == "generate_plan":
        from .orchestrator import generate_plan

        return generate_plan
    if name == "_generate_diff":
        from .orchestrator import _generate_diff

        return _generate_diff
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
