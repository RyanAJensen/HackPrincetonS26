#!/usr/bin/env python3
"""
Standalone Dedalus smoke test — independent of FastAPI.

Run from repository root or backend directory:
  cd sentinel/backend
  python scripts/dedalus_smoke.py

Requires: pip install dedalus_labs python-dotenv
Env: DEDALUS_API_KEY in environment or backend/.env
"""
from __future__ import annotations

import asyncio
import gc
import os
import sys
import warnings
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from pydantic import BaseModel

from runtime.dedalus_output import extract_final_output, validate_response_output

class SmokeResponse(BaseModel):
    smoke_ok: bool
    note: str


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        env_path = BACKEND_ROOT / ".env"
        if env_path.is_file():
            load_dotenv(env_path)
            print(f"[smoke] Loaded {env_path}")
        else:
            print(f"[smoke] No {env_path} — using process environment only")
    except ImportError:
        print("[smoke] python-dotenv not installed — using process environment only")


async def main() -> int:
    _load_env()
    key = os.getenv("DEDALUS_API_KEY")
    print(f"[smoke] Python: {sys.executable}")
    print(f"[smoke] DEDALUS_API_KEY: {'set (' + key[:8] + '...)' if key else 'NOT SET'}")

    try:
        import dedalus_labs

        print(f"[smoke] dedalus_labs import OK: {getattr(dedalus_labs, '__file__', '?')}")
    except ImportError as e:
        print(f"[smoke] FATAL: dedalus_labs import failed: {e}")
        return 2

    from dedalus_labs import AsyncDedalus, DedalusRunner

    if not key:
        print("[smoke] FATAL: DEDALUS_API_KEY not set — cannot call runner")
        return 3

    model = os.getenv("DEDALUS_MODEL", "anthropic/claude-sonnet-4-20250514")
    try:
        client = AsyncDedalus(api_key=key)
        runner = DedalusRunner(client)
        print("[smoke] AsyncDedalus + DedalusRunner constructed OK")

        warnings.filterwarnings(
            "error",
            category=RuntimeWarning,
            message=r".*was never awaited.*",
        )

        result = await runner.run(
            input="Return smoke_ok=true and note=dedalus_smoke.",
            model=model,
            instructions="Return the structured response only. No markdown.",
            max_steps=3,
            debug=True,
            verbose=True,
            response_format=SmokeResponse,
        )
        structured = validate_response_output(
            extract_final_output(result, "dedalus_smoke"),
            SmokeResponse,
            "dedalus_smoke",
        )
        print("[smoke] awaited runner.run successfully")
        print(f"[smoke] final_output_type={type(getattr(result, 'final_output', None)).__name__}")
        print("[smoke] final_output:")
        print(structured.model_dump_json(indent=2))
        print(f"[smoke] steps_used={getattr(result, 'steps_used', None)}")
        del structured
        del result
        gc.collect()
        print("[smoke] no coroutine warnings detected")
        print("[smoke] SUCCESS")
        return 0
    except Exception as e:
        print(f"[smoke] FATAL: runner.run failed: {e!r}")
        import traceback

        traceback.print_exc()
        return 4


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
