"""LLM calls: DedalusRunner when configured, else K2 Think API — JSON-only responses."""
from __future__ import annotations
import inspect
import json
import os
import re
import time
import httpx

from agents.dedalus_context import dedalus_runner_ctx

K2_API_URL = "https://api.k2think.ai/v1/chat/completions"
K2_MODEL = "MBZUAI-IFM/K2-Think-v2"

_api_key: str | None = None

DEFAULT_JSON_SYSTEM = (
    "You are an emergency medical coordination specialist. "
    "Your entire reply MUST be a single raw JSON object only. "
    "No markdown, no code fences, no explanations, no text before or after the JSON. "
    "Start with { and end with }. "
    "Be concise: string values under 120 characters, lists under 8 items."
)

_RAW_LOG_MAX = 8000


def get_api_key() -> str:
    global _api_key
    if _api_key is None:
        _api_key = os.environ.get("K2_API_KEY", "IFM-pB75TfFLX28aXCKQ")
    return _api_key


def _use_dedalus_runner_for_llm() -> bool:
    if os.getenv("RUNTIME_MODE", "dedalus") == "local":
        return False
    return bool(os.getenv("DEDALUS_API_KEY"))


def _get_runner_for_call():
    r = dedalus_runner_ctx.get()
    if r is not None:
        return r
    if not _use_dedalus_runner_for_llm():
        return None
    try:
        from runtime.dedalus_runtime import get_shared_dedalus_runner

        return get_shared_dedalus_runner()
    except ImportError:
        return None


def _strip_json_text(text: str) -> str:
    text = text.strip()
    if "</redacted_thinking>" in text:
        text = text.split("</redacted_thinking>")[-1].strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text, flags=re.IGNORECASE)
    text = text.strip()
    # Drop common lead-in lines before first {
    if "{" in text:
        idx = text.find("{")
        if idx > 0:
            prefix = text[:idx].strip()
            if prefix and not prefix.startswith("{"):
                text = text[idx:]
    return text


def _extract_first_json_object(text: str) -> str | None:
    """Find first balanced {...} substring; returns None if not found."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _parse_json_with_recovery(raw: str, caller: str, source: str) -> dict:
    """
    Try json.loads on sanitized text; then first JSON object extraction.
    Logs raw input on failure (truncated).
    """
    if raw is None or not str(raw).strip():
        print(f"  [{source}] {caller} empty or whitespace-only response")
        raise RuntimeError(f"{caller}: empty model response — cannot parse JSON")

    attempts: list[tuple[str, str]] = [
        ("strip+fences", _strip_json_text(raw)),
        ("first_json_object", ""),
    ]
    blob = _strip_json_text(raw)
    extracted = _extract_first_json_object(blob)
    if extracted:
        attempts[1] = ("first_json_object", extracted)

    last_err: Exception | None = None
    for label, text in attempts:
        if not text:
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            last_err = e
            continue

    preview = raw if len(raw) <= _RAW_LOG_MAX else raw[:_RAW_LOG_MAX] + "\n... [truncated]"
    print(f"  [{source}] {caller} JSON parse FAILED: {last_err}")
    print(f"  [{source}] {caller} raw response ({len(raw)} chars):\n{preview}")
    msg = str(last_err) if last_err else "no JSON object found"
    raise RuntimeError(f"{caller}: JSON parse failed — {msg}") from last_err


def _k2_extract_message_content(data: dict, caller: str) -> str:
    """Extract assistant text from K2 OpenAI-style response; log structure if empty."""
    try:
        choices = data.get("choices")
        if not choices:
            print(f"  [LLM/K2] {caller} response has no choices; keys={list(data.keys())}")
            return ""
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if content is None:
            print(f"  [LLM/K2] {caller} message.content is None; message keys={list(msg.keys())}")
            return ""
        if isinstance(content, list):
            # Some APIs return content parts
            parts = []
            for p in content:
                if isinstance(p, dict) and p.get("type") == "text":
                    parts.append(p.get("text", ""))
                elif isinstance(p, str):
                    parts.append(p)
            return "\n".join(parts).strip()
        return str(content).strip()
    except (IndexError, KeyError, TypeError) as e:
        print(f"  [LLM/K2] {caller} unexpected response shape: {e}; data snippet={str(data)[:500]}")
        return ""


async def _call_dedalus_runner(
    runner: object,
    prompt: str,
    system: str,
    caller: str,
) -> dict:
    sys = system or DEFAULT_JSON_SYSTEM
    model = os.getenv("DEDALUS_MODEL", "anthropic/claude-sonnet-4-20250514")
    debug = os.getenv("DEDALUS_RUNNER_DEBUG", "true").lower() in ("1", "true", "yes")
    verbose = os.getenv("DEDALUS_RUNNER_VERBOSE", "true").lower() in ("1", "true", "yes")
    max_steps = int(os.getenv("DEDALUS_MAX_STEPS", "5"))

    sig = inspect.signature(runner.run)
    params = sig.parameters
    run_method = runner.run
    is_async = inspect.iscoroutinefunction(run_method)

    user_prompt = prompt
    for attempt in range(2):
        kw: dict = {}
        if "model" in params:
            kw["model"] = model
        if "input" in params:
            kw["input"] = user_prompt
        if "messages" in params and "input" not in kw:
            kw["messages"] = [{"role": "user", "content": user_prompt}]
        if "instructions" in params:
            kw["instructions"] = sys
        elif "system" in params:
            kw["system"] = sys
        if "max_steps" in params:
            kw["max_steps"] = max_steps
        if "debug" in params:
            kw["debug"] = debug
        if "verbose" in params:
            kw["verbose"] = verbose

        print(
            f"  [DedalusRunner] {caller} run attempt {attempt + 1}/2 ({len(user_prompt)} chars) "
            f"model={model} max_steps={max_steps} debug={debug} verbose={verbose}"
        )
        t0 = time.monotonic()

        if is_async:
            result = await run_method(**kw)
        else:
            result = run_method(**kw)

        elapsed = int((time.monotonic() - t0) * 1000)
        final = getattr(result, "final_output", None)
        if final is None:
            final = getattr(result, "output", None)
        if final is None:
            final = str(result)

        raw_str = str(final)
        steps = getattr(result, "steps_used", None)
        print(
            f"  [DedalusRunner] {caller} done ({elapsed}ms) "
            f"steps_used={steps!r} final_output_len={len(raw_str)}"
        )
        print(f"  [DedalusRunner] {caller} raw final_output (preview 600 chars):\n{raw_str[:600]}")

        try:
            return _parse_json_with_recovery(raw_str, caller, "DedalusRunner")
        except (json.JSONDecodeError, RuntimeError):
            if attempt == 0:
                user_prompt = (
                    prompt
                    + "\n\nIMPORTANT: Respond with a single compact valid JSON object only — "
                    "max 6 items per list, max 80 chars per string value. Raw JSON only, no markdown."
                )
                continue
            print(f"  [DedalusRunner] {caller} FAILED invalid JSON after retry")
            raise

    raise RuntimeError("DedalusRunner returned invalid JSON")


async def call_llm(prompt: str, system: str = "", caller: str = "llm") -> dict:
    sys = system or DEFAULT_JSON_SYSTEM

    runner = _get_runner_for_call()
    if runner is not None:
        return await _call_dedalus_runner(runner, prompt, sys, caller)

    print(f"  [LLM/K2] {caller} call start ({len(prompt)} chars)")
    t0 = time.monotonic()

    for attempt in range(2):
        user_content = prompt
        if attempt == 1:
            user_content = (
                prompt
                + "\n\nIMPORTANT: Your entire reply must be one JSON object only. "
                "No prose. If you used markdown before, output raw JSON only now. "
                "Max 6 items per list, max 80 chars per string value."
            )

        payload = {
            "model": K2_MODEL,
            "messages": [
                {"role": "system", "content": sys},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    K2_API_URL,
                    headers={
                        "Authorization": f"Bearer {get_api_key()}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=60.0,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException:
            elapsed = int((time.monotonic() - t0) * 1000)
            print(f"  [LLM/K2] {caller} TIMEOUT after {elapsed}ms")
            raise

        raw_content = _k2_extract_message_content(data, caller)
        print(f"  [LLM/K2] {caller} raw message.content length={len(raw_content)}")
        preview = raw_content if len(raw_content) <= 1200 else raw_content[:1200] + "..."
        print(f"  [LLM/K2] {caller} raw (preview):\n{preview}")

        try:
            result = _parse_json_with_recovery(raw_content, caller, "LLM/K2")
            elapsed = int((time.monotonic() - t0) * 1000)
            print(f"  [LLM/K2] {caller} call success ({elapsed}ms)")
            return result
        except (json.JSONDecodeError, RuntimeError):
            if attempt == 1:
                elapsed = int((time.monotonic() - t0) * 1000)
                print(f"  [LLM/K2] {caller} FAILED invalid JSON after retry ({elapsed}ms)")
                raise

    raise RuntimeError("LLM returned invalid JSON after retry")
