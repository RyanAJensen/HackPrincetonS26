from __future__ import annotations

import inspect
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


class DedalusOutputError(RuntimeError):
    """Raised when a Dedalus runner result is unusable."""


class DedalusOutputValidationError(DedalusOutputError):
    """Raised when Dedalus structured output fails schema validation."""


def ensure_not_awaitable(value: Any, label: str) -> None:
    if inspect.isawaitable(value):
        raise DedalusOutputError(
            f"{label} is still awaitable/coroutine. "
            "DedalusRunner.run(...) must be awaited and result.final_output must be materialized before use."
        )


def extract_final_output(result: Any, caller: str) -> Any:
    ensure_not_awaitable(result, f"{caller} DedalusRunner result")

    if not hasattr(result, "final_output"):
        raise DedalusOutputError(f"{caller} DedalusRunner result is missing final_output")

    final_output = getattr(result, "final_output")
    ensure_not_awaitable(final_output, f"{caller} DedalusRunner result.final_output")

    if final_output is None:
        raise DedalusOutputError(f"{caller} DedalusRunner returned an empty final_output")

    return final_output


def validate_response_output(
    final_output: Any,
    response_model: type[ResponseModelT],
    caller: str,
) -> ResponseModelT:
    if isinstance(final_output, response_model):
        return final_output

    try:
        return response_model.model_validate(final_output)
    except ValidationError as exc:
        raise DedalusOutputValidationError(
            f"{caller} Dedalus structured output failed validation against "
            f"{response_model.__name__}: {exc}"
        ) from exc
