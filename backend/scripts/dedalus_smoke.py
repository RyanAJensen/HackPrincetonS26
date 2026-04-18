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
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent


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

        result = await runner.run(
            input='Reply with exactly this JSON and nothing else: {"smoke_ok": true, "note": "dedalus_smoke"}',
            model=model,
            instructions="You output JSON only. No markdown.",
            max_steps=3,
            debug=True,
            verbose=True,
        )
        raw = getattr(result, "final_output", None) or str(result)
        print("[smoke] --- raw result ---")
        print(raw)
        print("[smoke] --- end raw ---")
        print(f"[smoke] steps_used={getattr(result, 'steps_used', None)}")
        print("[smoke] SUCCESS")
        return 0
    except Exception as e:
        print(f"[smoke] FATAL: runner.run failed: {e!r}")
        import traceback

        traceback.print_exc()
        return 4


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
