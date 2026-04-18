"""
Dedalus environment verification for FastAPI startup — import path, strict mode, runner smoke init.
Must mirror the import used in runtime.dedalus_runtime (top-level + AsyncDedalus / DedalusRunner).
"""
from __future__ import annotations

import importlib
import os
import sys
import traceback
from typing import Any

import runtime.dedalus_runtime as dedalus_runtime


def print_dedalus_runtime_diagnostics() -> None:
    """Definitive process identity for debugging wrong-interpreter / reload issues."""
    print("  [Dedalus verify] --- runtime diagnostics (this process) ---")
    print(f"  [Dedalus verify] sys.executable: {sys.executable}")
    print(f"  [Dedalus verify] sys.version: {sys.version.splitlines()[0]}")
    try:
        cwd = os.getcwd()
    except OSError as e:
        cwd = f"<os.getcwd() failed: {e}>"
    print(f"  [Dedalus verify] cwd: {cwd}")
    for i, p in enumerate(sys.path[:10]):
        print(f"  [Dedalus verify] sys.path[{i}]: {p}")
    if len(sys.path) > 10:
        print(f"  [Dedalus verify] ... ({len(sys.path) - 10} more path entries)")
    if getattr(sys, "argv", None):
        print(f"  [Dedalus verify] sys.argv[0]: {sys.argv[0]}")


def _verify_dedalus_sdk_import() -> tuple[bool, str, str | None]:
    """
    Same effective check as dedalus_runtime module load: ensure package and symbols import.

    Returns:
        (ok, message_or_path, error_detail_if_failed)
    """
    try:
        mod = importlib.import_module("dedalus_labs")
        pkg_file = getattr(mod, "__file__", None) or ""
        # Mirror runtime/dedalus_runtime.py — submodule errors must not look like "missing pip pkg"
        from dedalus_labs import AsyncDedalus, DedalusRunner  # noqa: F401

        _ = (AsyncDedalus, DedalusRunner)
        path_out = pkg_file or "imported (no __file__)"
        return True, path_out, None
    except ImportError as e:
        return False, str(e), str(e)
    except Exception as e:
        tb = traceback.format_exc()
        return False, f"{type(e).__name__}: {e}", tb


def verify_dedalus_runner_constructible() -> tuple[bool, str]:
    """Try AsyncDedalus + DedalusRunner without network call."""
    key = os.getenv("DEDALUS_API_KEY")
    if not key:
        return False, "DEDALUS_API_KEY not set - skip runner construction test"
    try:
        from dedalus_labs import AsyncDedalus, DedalusRunner

        client = AsyncDedalus(api_key=key)
        runner = DedalusRunner(client)
        _ = runner
        return True, "DedalusRunner(client) OK"
    except Exception as e:
        return False, f"DedalusRunner init failed: {e}"


def run_startup_dedalus_checks() -> dict[str, Any]:
    """
    Print verification logs and enforce DEDALUS_STRICT.

    Raises:
        RuntimeError: strict mode violations (app must not start).
    """
    strict = os.getenv("DEDALUS_STRICT", "").lower() in ("1", "true", "yes")
    runtime_mode = os.getenv("RUNTIME_MODE", "dedalus")
    key = os.getenv("DEDALUS_API_KEY")

    print_dedalus_runtime_diagnostics()

    ok, path_or_err, extra_detail = _verify_dedalus_sdk_import()
    print(
        "  [Dedalus verify] import dedalus_labs -> AsyncDedalus, DedalusRunner:",
        "OK" if ok else "FAILED",
    )
    if ok:
        print(f"  [Dedalus verify] dedalus_labs.__file__: {path_or_err}")
    else:
        print(f"  [Dedalus verify] import error: {path_or_err}")
        if extra_detail and extra_detail != path_or_err:
            print(f"  [Dedalus verify] detail:\n{extra_detail}")

    # Compare with module-import path used at import time (before this event in same process)
    legacy_flag = getattr(dedalus_runtime, "DEDALUS_LABS_AVAILABLE", None)
    legacy_err = getattr(dedalus_runtime, "DEDALUS_IMPORT_ERROR", None)
    print(
        "  [Dedalus verify] dedalus_runtime.DEDALUS_LABS_AVAILABLE (import-time):",
        legacy_flag,
    )
    if legacy_err:
        print(f"  [Dedalus verify] dedalus_runtime.DEDALUS_IMPORT_ERROR: {legacy_err}")
    if legacy_flag is not None and bool(legacy_flag) != ok:
        print(
            "  [Dedalus verify] NOTE: mismatch vs import-time — investigate reload / duplicate loads.",
            file=sys.stderr,
        )

    runner_ok = False
    runner_msg = "skipped"
    if ok:
        runner_ok, runner_msg = verify_dedalus_runner_constructible()
        print("  [Dedalus verify] DedalusRunner init:", runner_msg)

    # Strict: Dedalus expected but SDK missing when key is set and mode is dedalus
    dedalus_expected = runtime_mode == "dedalus" and bool(key)
    if strict and dedalus_expected and not ok:
        raise RuntimeError(
            "DEDALUS_STRICT: dedalus_labs SDK is not importable in this process "
            f"(RUNTIME_MODE=dedalus, DEDALUS_API_KEY is set). {path_or_err}. "
            "Use the venv interpreter (e.g. venv\\Scripts\\python.exe -m uvicorn ...), "
            "not a global `uvicorn` on PATH."
        )

    if strict:
        if not ok and not dedalus_expected:
            # Strict still requires SDK if user asked for strict globally
            raise RuntimeError(
                "DEDALUS_STRICT: dedalus_labs is not installed or not importable. "
                f"{path_or_err} Install: pip install dedalus_labs"
            )
        if ok and key and not runner_ok:
            raise RuntimeError(f"DEDALUS_STRICT: {runner_msg}")
        if ok and runtime_mode == "dedalus" and not key:
            raise RuntimeError(
                "DEDALUS_STRICT: RUNTIME_MODE=dedalus requires DEDALUS_API_KEY "
                "(use RUNTIME_MODE=local for K2-only development)"
            )

    if runtime_mode == "dedalus" and not ok:
        print(
            "  [Dedalus verify] WARNING: RUNTIME_MODE=dedalus but dedalus_labs SDK import failed — "
            "agents will fall back to K2 unless DEDALUS_STRICT is enabled (then startup fails).",
            file=sys.stderr,
        )

    if key and not ok:
        print(
            "  [Dedalus verify] WARNING: DEDALUS_API_KEY is set but dedalus_labs import failed.",
            file=sys.stderr,
        )

    return {
        "dedalus_labs_import_ok": ok,
        "dedalus_labs_path": path_or_err if ok else None,
        "dedalus_import_error": None if ok else path_or_err,
        "dedalus_runner_init_ok": runner_ok if ok else False,
        "dedalus_runner_message": runner_msg,
        "dedalus_strict": strict,
    }
