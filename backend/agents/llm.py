"""K2 Think API wrapper with structured JSON output."""
from __future__ import annotations
import json
import os
import re
import time
import httpx

K2_API_URL = "https://api.k2think.ai/v1/chat/completions"
K2_MODEL = "MBZUAI-IFM/K2-Think-v2"

_api_key: str | None = None


def get_api_key() -> str:
    global _api_key
    if _api_key is None:
        _api_key = os.environ.get("K2_API_KEY", "IFM-pB75TfFLX28aXCKQ")
    return _api_key


async def call_llm(prompt: str, system: str = "", caller: str = "llm") -> dict:
    """Call K2 Think and parse JSON from the response. Retries once with a brevity hint on truncation."""
    sys = system or (
        "You are a campus emergency response specialist. "
        "Always respond with valid JSON only — no markdown, no prose, no code fences. "
        "Be concise: keep string values under 120 characters, lists under 8 items."
    )

    print(f"  [LLM] {caller} call start ({len(prompt)} chars)")
    t0 = time.monotonic()

    for attempt in range(2):
        user_content = prompt
        if attempt == 1:
            user_content = (
                prompt
                + "\n\nIMPORTANT: Your previous response was truncated. "
                "Be much more concise — max 6 items per list, max 80 chars per string value."
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
                    timeout=25.0,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException:
            elapsed = int((time.monotonic() - t0) * 1000)
            print(f"  [LLM] {caller} TIMEOUT after {elapsed}ms")
            raise

        text = data["choices"][0]["message"]["content"].strip()
        # K2-Think outputs a reasoning chain ending with </think> before the answer
        if "</think>" in text:
            text = text.split("</think>")[-1].strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        try:
            result = json.loads(text)
            elapsed = int((time.monotonic() - t0) * 1000)
            print(f"  [LLM] {caller} call success ({elapsed}ms)")
            return result
        except json.JSONDecodeError:
            if attempt == 1:
                elapsed = int((time.monotonic() - t0) * 1000)
                print(f"  [LLM] {caller} FAILED invalid JSON after retry ({elapsed}ms)")
                raise

    raise RuntimeError("LLM returned invalid JSON after retry")
