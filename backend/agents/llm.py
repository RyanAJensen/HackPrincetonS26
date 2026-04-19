"""Strict JSON LLM wrapper with schema validation, bounded retries, and safe logs."""
from __future__ import annotations

import inspect
import json
import os
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any, Optional

import httpx
from pydantic import BaseModel, ValidationError

from agents.dedalus_context import dedalus_runner_ctx
from agents.machine_context import dedalus_machine_executor_ctx, dedalus_machine_id_ctx
from runtime.dedalus_output import (
    DedalusOutputError,
    DedalusOutputValidationError,
    extract_final_output,
    validate_response_output,
)

K2_API_URL = "https://api.k2think.ai/v1/chat/completions"
K2_MODEL = "MBZUAI-IFM/K2-Think-v2"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"
ANTHROPIC_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_VALIDATION_RETRIES = 2

STRICT_JSON_DIRECTIVE = (
    "Do not include any explanation, reasoning, chain-of-thought, or preamble. "
    "Output ONLY valid JSON that matches the response schema exactly."
)
DEFAULT_JSON_SYSTEM = (
    "You are an emergency medical coordination specialist. "
    f"{STRICT_JSON_DIRECTIVE}"
)

_api_key: Optional[str] = None


class LLMResponseValidationError(RuntimeError):
    """Raised when model output is not strict JSON or fails schema validation."""


class LLMStructuredError(RuntimeError):
    """Structured terminal error for the LLM pipeline."""

    def __init__(
        self,
        *,
        caller: str,
        source: str,
        kind: str,
        retry_count: int,
        detail: str,
    ) -> None:
        self.caller = caller
        self.source = source
        self.kind = kind
        self.retry_count = retry_count
        self.detail = detail
        super().__init__(
            f"{caller}: {detail} "
            f"(source={source}, kind={kind}, retry_count={retry_count})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "caller": self.caller,
            "source": self.source,
            "kind": self.kind,
            "retry_count": self.retry_count,
            "detail": self.detail,
        }


@dataclass
class ReliabilityStats:
    total_calls: int = 0
    successful_calls: int = 0
    first_pass_successes: int = 0
    retried_calls: int = 0
    total_latency_ms: int = 0

    def snapshot(self) -> dict[str, float | int]:
        total = self.total_calls or 1
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "first_pass_success_rate": self.first_pass_successes / total,
            "avg_latency": self.total_latency_ms / total,
            "retry_rate": self.retried_calls / total,
        }


_RELIABILITY_LOCK = Lock()
_RELIABILITY: dict[str, ReliabilityStats] = {}


def reset_llm_reliability_tracking() -> None:
    with _RELIABILITY_LOCK:
        _RELIABILITY.clear()


def get_llm_reliability_snapshot() -> dict[str, dict[str, float | int]]:
    with _RELIABILITY_LOCK:
        return {caller: stats.snapshot() for caller, stats in _RELIABILITY.items()}


def _record_reliability(
    caller: str,
    *,
    latency_ms: int,
    retry_count: int,
    success: bool,
) -> None:
    with _RELIABILITY_LOCK:
        stats = _RELIABILITY.setdefault(caller, ReliabilityStats())
        stats.total_calls += 1
        stats.total_latency_ms += latency_ms
        if success:
            stats.successful_calls += 1
            if retry_count == 0:
                stats.first_pass_successes += 1
        if retry_count > 0:
            stats.retried_calls += 1


def _log_result(
    source: str,
    caller: str,
    *,
    latency_ms: int,
    success: bool,
    retry_count: int,
    error_kind: Optional[str] = None,
) -> None:
    msg = (
        f"  [{source}] agent={caller} latency_ms={latency_ms} "
        f"success={'true' if success else 'false'} retry_count={retry_count}"
    )
    if error_kind:
        msg += f" error={error_kind}"
    print(msg)


def _finalize_success(source: str, caller: str, started_at: float, retry_count: int) -> None:
    latency_ms = int((time.monotonic() - started_at) * 1000)
    _record_reliability(caller, latency_ms=latency_ms, retry_count=retry_count, success=True)
    _log_result(source, caller, latency_ms=latency_ms, success=True, retry_count=retry_count)


def _raise_terminal_error(
    source: str,
    caller: str,
    *,
    started_at: float,
    retry_count: int,
    kind: str,
    exc: Exception,
) -> None:
    latency_ms = int((time.monotonic() - started_at) * 1000)
    _record_reliability(caller, latency_ms=latency_ms, retry_count=retry_count, success=False)
    _log_result(
        source,
        caller,
        latency_ms=latency_ms,
        success=False,
        retry_count=retry_count,
        error_kind=kind,
    )
    raise LLMStructuredError(
        caller=caller,
        source=source,
        kind=kind,
        retry_count=retry_count,
        detail=str(exc),
    ) from exc


def get_api_key() -> str:
    global _api_key
    if _api_key is None:
        _api_key = os.environ.get("K2_API_KEY")
    if not _api_key:
        raise RuntimeError(
            "K2 local runtime requested but K2_API_KEY is not set. "
            "Set K2_API_KEY in backend/.env or switch RUNTIME_MODE away from local."
        )
    return _api_key


def _use_anthropic_backend() -> bool:
    """Prefer Claude if ANTHROPIC_API_KEY is set in local mode (much faster than K2)."""
    backend = os.getenv("LLM_BACKEND", "").lower()
    if backend == "k2":
        return False
    if backend == "anthropic":
        return True
    # Auto-select: prefer Anthropic if key is available
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _require_response_model(
    response_model: Optional[type[BaseModel]],
) -> type[BaseModel]:
    if response_model is None:
        raise RuntimeError("call_llm requires a response_model for strict structured output")
    return response_model


def _use_dedalus_runner_for_llm() -> bool:
    from agents.dedalus_context import is_dedalus_auth_failed
    return os.getenv("RUNTIME_MODE", "dedalus") != "local" and not is_dedalus_auth_failed()


def _allow_runtime_fallback() -> bool:
    return os.getenv("ALLOW_RUNTIME_FALLBACK_TO_LOCAL", "").lower() in ("1", "true", "yes")


def _get_runner_for_call() -> Any | None:
    runner = dedalus_runner_ctx.get()
    if runner is not None:
        return runner
    if not _use_dedalus_runner_for_llm():
        return None
    try:
        from runtime.dedalus_runtime import get_shared_dedalus_runner

        return get_shared_dedalus_runner()
    except ImportError:
        return None


def _get_machine_executor_for_call() -> tuple[Any | None, str | None]:
    executor = dedalus_machine_executor_ctx.get()
    machine_id = dedalus_machine_id_ctx.get()
    if executor is None and machine_id is None:
        return None, None
    if executor is None or machine_id is None:
        raise RuntimeError("Dedalus Machines context is incomplete for call_llm")
    return executor, machine_id


def _build_system_prompt(system: str) -> str:
    base = (system or DEFAULT_JSON_SYSTEM).strip()
    if STRICT_JSON_DIRECTIVE not in base:
        return f"{base}\n\n{STRICT_JSON_DIRECTIVE}"
    return base


def _build_json_schema_response_format(
    response_model: type[BaseModel],
) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": response_model.__name__,
            "schema": response_model.model_json_schema(),
            "strict": True,
        },
    }


def _strict_json_object(raw: Any, caller: str, source: str) -> dict[str, Any]:
    text = str(raw).strip() if raw is not None else ""
    if not text:
        raise LLMResponseValidationError(f"{caller}: {source} returned an empty response")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMResponseValidationError(
            f"{caller}: {source} returned non-JSON output: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise LLMResponseValidationError(f"{caller}: {source} returned non-object JSON")
    return parsed


def _validate_payload(
    payload: dict[str, Any],
    response_model: type[BaseModel],
    caller: str,
    source: str,
) -> dict[str, Any]:
    try:
        return response_model.model_validate(payload).model_dump()
    except ValidationError as exc:
        raise LLMResponseValidationError(
            f"{caller}: {source} response failed validation against "
            f"{response_model.__name__}: {exc}"
        ) from exc


def _coerce_response_payload(
    raw_output: Any,
    response_model: type[BaseModel],
    caller: str,
    source: str,
) -> dict[str, Any]:
    if isinstance(raw_output, response_model):
        return raw_output.model_dump()
    if isinstance(raw_output, BaseModel):
        return _validate_payload(raw_output.model_dump(), response_model, caller, source)
    if isinstance(raw_output, dict):
        return _validate_payload(raw_output, response_model, caller, source)
    if isinstance(raw_output, str):
        return _validate_payload(
            _strict_json_object(raw_output, caller, source),
            response_model,
            caller,
            source,
        )

    try:
        structured = validate_response_output(raw_output, response_model, caller)
    except DedalusOutputValidationError as exc:
        raise LLMResponseValidationError(str(exc)) from exc
    except ValidationError as exc:
        raise LLMResponseValidationError(
            f"{caller}: {source} response failed validation against "
            f"{response_model.__name__}: {exc}"
        ) from exc
    except Exception as exc:
        raise LLMResponseValidationError(
            f"{caller}: {source} returned unsupported output type "
            f"{type(raw_output).__name__}: {exc}"
        ) from exc
    return structured.model_dump()


def _extract_k2_message_content(data: dict[str, Any], caller: str) -> str:
    try:
        choices = data["choices"]
        message = choices[0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMResponseValidationError(
            f"{caller}: LLM/K2 response is missing choices/message content"
        ) from exc

    content = message.get("content")
    if content is None:
        raise LLMResponseValidationError(f"{caller}: LLM/K2 response is missing message.content")
    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(str(part.get("text", "")))
            elif isinstance(part, str):
                text_parts.append(part)
        return "".join(text_parts).strip()
    return str(content).strip()


def _accepts_argument(params: dict[str, inspect.Parameter], name: str) -> bool:
    if not params:
        return True
    if name in params:
        return True
    return any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values())


async def _call_dedalus_runner(
    runner: object,
    prompt: str,
    system: str,
    caller: str,
    response_model: Optional[type[BaseModel]] = None,
) -> dict[str, Any]:
    response_model = _require_response_model(response_model)
    sys = _build_system_prompt(system)
    model = os.getenv("DEDALUS_MODEL", "anthropic/claude-sonnet-4-20250514")
    debug = os.getenv("DEDALUS_RUNNER_DEBUG", "false").lower() in ("1", "true", "yes")
    verbose = os.getenv("DEDALUS_RUNNER_VERBOSE", "false").lower() in ("1", "true", "yes")
    max_steps = int(os.getenv("DEDALUS_MAX_STEPS", "5"))
    temperature = float(os.getenv("LLM_TEMPERATURE", "0"))
    started_at = time.monotonic()

    try:
        params = inspect.signature(runner.run).parameters
    except (TypeError, ValueError):
        params = {}

    if not _accepts_argument(params, "response_format"):
        raise RuntimeError(
            "DedalusRunner.run does not accept response_format. "
            "Upgrade dedalus_labs to a version that supports structured outputs."
        )

    last_validation_error: Optional[Exception] = None
    for attempt in range(MAX_VALIDATION_RETRIES + 1):
        try:
            kwargs: dict[str, Any] = {"response_format": response_model}
            if _accepts_argument(params, "model"):
                kwargs["model"] = model
            if _accepts_argument(params, "input"):
                kwargs["input"] = prompt
            elif _accepts_argument(params, "messages"):
                kwargs["messages"] = [{"role": "user", "content": prompt}]
            if _accepts_argument(params, "instructions"):
                kwargs["instructions"] = sys
            elif _accepts_argument(params, "system"):
                kwargs["system"] = sys
            if _accepts_argument(params, "max_steps"):
                kwargs["max_steps"] = max_steps
            if _accepts_argument(params, "debug"):
                kwargs["debug"] = debug
            if _accepts_argument(params, "verbose"):
                kwargs["verbose"] = verbose
            if _accepts_argument(params, "temperature"):
                kwargs["temperature"] = temperature

            pending = runner.run(**kwargs)
            if not inspect.isawaitable(pending):
                raise DedalusOutputError(
                    "DedalusRunner.run returned a non-awaitable result while using AsyncDedalus"
                )

            result = await pending
            final_output = extract_final_output(result, caller)
            payload = _coerce_response_payload(final_output, response_model, caller, "DedalusRunner")
            _finalize_success("DedalusRunner", caller, started_at, attempt)
            return payload
        except LLMResponseValidationError as exc:
            last_validation_error = exc
            if attempt == MAX_VALIDATION_RETRIES:
                break
            continue
        except Exception as exc:
            exc_str = str(exc)
            is_auth = "401" in exc_str or "invalid_api_key" in exc_str or "Key inactive" in exc_str
            if is_auth and _allow_runtime_fallback():
                from agents.dedalus_context import mark_dedalus_auth_failed
                mark_dedalus_auth_failed()
                print(f"[LLM] Dedalus auth error ({caller}) — switching to local K2 for all calls")
                return await _call_k2_local(
                    prompt, system, caller,
                    response_model=response_model,
                    timeout_seconds=None,
                )
            _raise_terminal_error(
                "DedalusRunner",
                caller,
                started_at=started_at,
                retry_count=attempt,
                kind="runtime_error",
                exc=exc,
            )

    assert last_validation_error is not None
    _raise_terminal_error(
        "DedalusRunner",
        caller,
        started_at=started_at,
        retry_count=MAX_VALIDATION_RETRIES,
        kind="validation_failed",
        exc=last_validation_error,
    )
    raise AssertionError("unreachable")


async def _call_dedalus_machine(
    executor: object,
    machine_id: str,
    prompt: str,
    system: str,
    caller: str,
    response_model: Optional[type[BaseModel]] = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    response_model = _require_response_model(response_model)
    sys = _build_system_prompt(system)
    started_at = time.monotonic()

    last_validation_error: Optional[Exception] = None
    for attempt in range(MAX_VALIDATION_RETRIES + 1):
        try:
            raw_stdout = await executor.run_prompt_on_machine(
                machine_id=machine_id,
                prompt=prompt,
                system=sys,
                caller=caller,
                response_model=response_model,
                timeout_seconds=timeout_seconds,
            )
            payload = _coerce_response_payload(raw_stdout, response_model, caller, "DedalusMachine")
            _finalize_success("DedalusMachine", caller, started_at, attempt)
            return payload
        except LLMResponseValidationError as exc:
            last_validation_error = exc
            if attempt == MAX_VALIDATION_RETRIES:
                break
            continue
        except Exception as exc:
            _raise_terminal_error(
                "DedalusMachine",
                caller,
                started_at=started_at,
                retry_count=attempt,
                kind="runtime_error",
                exc=exc,
            )

    assert last_validation_error is not None
    _raise_terminal_error(
        "DedalusMachine",
        caller,
        started_at=started_at,
        retry_count=MAX_VALIDATION_RETRIES,
        kind="validation_failed",
        exc=last_validation_error,
    )
    raise AssertionError("unreachable")


async def _call_k2_local(
    prompt: str,
    system: str,
    caller: str,
    response_model: Optional[type[BaseModel]] = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    response_model = _require_response_model(response_model)
    sys = _build_system_prompt(system)
    started_at = time.monotonic()
    timeout_seconds = timeout_seconds or float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))
    payload = {
        "model": K2_MODEL,
        "messages": [
            {"role": "system", "content": sys},
            {"role": "user", "content": prompt},
        ],
        "response_format": _build_json_schema_response_format(response_model),
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0")),
        "stream": False,
    }

    last_validation_error: Optional[Exception] = None
    for attempt in range(MAX_VALIDATION_RETRIES + 1):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    K2_API_URL,
                    headers={
                        "Authorization": f"Bearer {get_api_key()}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=timeout_seconds,
                )
                response.raise_for_status()
                data = response.json()

            raw_content = _extract_k2_message_content(data, caller)
            parsed = _strict_json_object(raw_content, caller, "LLM/K2")
            result = _validate_payload(parsed, response_model, caller, "LLM/K2")
            _finalize_success("LLM/K2", caller, started_at, attempt)
            return result
        except LLMResponseValidationError as exc:
            last_validation_error = exc
            if attempt == MAX_VALIDATION_RETRIES:
                break
            continue
        except httpx.TimeoutException as exc:
            timeout_error = RuntimeError(f"{caller}: LLM/K2 timed out after {int(timeout_seconds)}s")
            _raise_terminal_error(
                "LLM/K2",
                caller,
                started_at=started_at,
                retry_count=attempt,
                kind="timeout",
                exc=timeout_error,
            )
        except Exception as exc:
            _raise_terminal_error(
                "LLM/K2",
                caller,
                started_at=started_at,
                retry_count=attempt,
                kind="runtime_error",
                exc=exc,
            )

    assert last_validation_error is not None
    _raise_terminal_error(
        "LLM/K2",
        caller,
        started_at=started_at,
        retry_count=MAX_VALIDATION_RETRIES,
        kind="validation_failed",
        exc=last_validation_error,
    )
    raise AssertionError("unreachable")


async def _call_claude_local(
    prompt: str,
    system: str,
    caller: str,
    response_model: Optional[type[BaseModel]] = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    response_model = _require_response_model(response_model)
    sys = _build_system_prompt(system)
    started_at = time.monotonic()
    timeout_seconds = timeout_seconds or float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    model = os.getenv("ANTHROPIC_MODEL", ANTHROPIC_DEFAULT_MODEL)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set; cannot use Anthropic backend")

    # Embed schema in system prompt so Claude outputs valid JSON
    schema_str = json.dumps(response_model.model_json_schema(), separators=(",", ":"))
    full_system = f"{sys}\n\nYou MUST output valid JSON matching this schema exactly:\n{schema_str}"

    payload = {
        "model": model,
        "max_tokens": 2048,
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0")),
        "system": full_system,
        "messages": [{"role": "user", "content": prompt}],
    }

    last_validation_error: Optional[Exception] = None
    for attempt in range(MAX_VALIDATION_RETRIES + 1):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    ANTHROPIC_API_URL,
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": ANTHROPIC_API_VERSION,
                        "content-type": "application/json",
                    },
                    json=payload,
                    timeout=timeout_seconds,
                )
                response.raise_for_status()
                data = response.json()

            # Extract text content from Anthropic response format
            content_blocks = data.get("content", [])
            raw_text = ""
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    raw_text += block.get("text", "")
            raw_text = raw_text.strip()

            # Strip markdown code fences if present
            if raw_text.startswith("```"):
                lines = raw_text.split("\n")
                raw_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

            parsed = _strict_json_object(raw_text, caller, "LLM/Anthropic")
            result = _validate_payload(parsed, response_model, caller, "LLM/Anthropic")
            _finalize_success("LLM/Anthropic", caller, started_at, attempt)
            return result
        except LLMResponseValidationError as exc:
            last_validation_error = exc
            if attempt == MAX_VALIDATION_RETRIES:
                break
            continue
        except httpx.TimeoutException as exc:
            timeout_error = RuntimeError(f"{caller}: LLM/Anthropic timed out after {int(timeout_seconds)}s")
            _raise_terminal_error(
                "LLM/Anthropic", caller, started_at=started_at,
                retry_count=attempt, kind="timeout", exc=timeout_error,
            )
        except Exception as exc:
            _raise_terminal_error(
                "LLM/Anthropic", caller, started_at=started_at,
                retry_count=attempt, kind="runtime_error", exc=exc,
            )

    assert last_validation_error is not None
    _raise_terminal_error(
        "LLM/Anthropic", caller, started_at=started_at,
        retry_count=MAX_VALIDATION_RETRIES, kind="validation_failed",
        exc=last_validation_error,
    )
    raise AssertionError("unreachable")


async def call_llm(
    prompt: str,
    system: str = "",
    caller: str = "llm",
    response_model: Optional[type[BaseModel]] = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    machine_executor, machine_id = _get_machine_executor_for_call()
    if machine_executor is not None and machine_id is not None:
        return await _call_dedalus_machine(
            machine_executor,
            machine_id,
            prompt,
            system,
            caller,
            response_model=response_model,
            timeout_seconds=timeout_seconds,
        )

    dedalus_requested = _use_dedalus_runner_for_llm()
    runner = _get_runner_for_call()
    if dedalus_requested:
        if runner is None:
            raise RuntimeError(
                "Dedalus runtime requested but no DedalusRunner is available. "
                "Set DEDALUS_API_KEY or use RUNTIME_MODE=local explicitly."
            )
        return await _call_dedalus_runner(
            runner,
            prompt,
            system,
            caller,
            response_model=response_model,
        )

    if _use_anthropic_backend():
        return await _call_claude_local(
            prompt, system, caller,
            response_model=response_model,
            timeout_seconds=timeout_seconds,
        )

    return await _call_k2_local(
        prompt,
        system,
        caller,
        response_model=response_model,
        timeout_seconds=timeout_seconds,
    )
