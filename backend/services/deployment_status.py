from __future__ import annotations

import os
from typing import Any

import httpx

from db import probe_db
from runtime.dedalus_client_config import (
    dedalus_byok_configured,
    describe_dedalus_billing_mode,
    describe_swarm_reasoning_mode,
    k2_configured,
    swarm_enrichment_backend_ready,
)
from runtime.dedalus_dcs import DedalusMachinesClient
from runtime.dedalus_runtime import DEDALUS_IMPORT_ERROR, DEDALUS_LABS_AVAILABLE
from runtime.dedalus_startup import verify_dedalus_runner_constructible


def _runtime_mode() -> str:
    return os.getenv("RUNTIME_MODE", "dedalus").strip().lower() or "dedalus"


def _allow_runtime_fallback() -> bool:
    return os.getenv("ALLOW_RUNTIME_FALLBACK_TO_LOCAL", "").lower() in ("1", "true", "yes")


async def _probe_osrm(base_url: str) -> dict[str, Any]:
    probe_url = f"{base_url.rstrip('/')}/nearest/v1/driving/-74.6580,40.3461"
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            response = await client.get(probe_url, params={"number": 1})
        if response.status_code == 200:
            return {"status": "ok", "base_url": base_url, "probe_url": probe_url}
        return {
            "status": "degraded",
            "base_url": base_url,
            "probe_url": probe_url,
            "detail": f"unexpected status {response.status_code}",
        }
    except Exception as exc:
        return {
            "status": "degraded",
            "base_url": base_url,
            "probe_url": probe_url,
            "detail": str(exc),
        }


async def _runtime_check(runtime_mode: str) -> dict[str, Any]:
    dedalus_key = bool(os.getenv("DEDALUS_API_KEY"))
    k2_key = bool(os.getenv("K2_API_KEY"))
    anthropic_key = bool(os.getenv("ANTHROPIC_API_KEY"))
    if runtime_mode == "local":
        ready = k2_key or anthropic_key
        return {
            "status": "ok" if ready else "broken",
            "mode": runtime_mode,
            "ready": ready,
            "llm_backend_available": ready,
            "detail": "local runtime requires K2_API_KEY or ANTHROPIC_API_KEY",
        }

    if runtime_mode == "dedalus":
        runner_ok, runner_msg = verify_dedalus_runner_constructible()
        ready = dedalus_key and DEDALUS_LABS_AVAILABLE and runner_ok
        return {
            "status": "ok" if ready else "broken",
            "mode": runtime_mode,
            "ready": ready,
            "dedalus_sdk_available": DEDALUS_LABS_AVAILABLE,
            "dedalus_import_error": DEDALUS_IMPORT_ERROR,
            "dedalus_api_key_present": dedalus_key,
            "runner_constructible": runner_ok,
            "detail": runner_msg,
        }

    if runtime_mode == "swarm":
        enrichment_ready = swarm_enrichment_backend_ready()
        if not dedalus_key:
            return {
                "status": "broken",
                "mode": runtime_mode,
                "ready": False,
                "dedalus_api_key_present": False,
                "detail": "DEDALUS_API_KEY is required for swarm mode",
            }
        try:
            client = DedalusMachinesClient(timeout=5)
            machines = await client.list_machines()
            return {
                "status": "ok" if enrichment_ready else "degraded",
                "mode": runtime_mode,
                "ready": True,
                "dedalus_api_key_present": True,
                "k2_api_key_present": k2_configured(),
                "dedalus_provider_key_present": dedalus_byok_configured(),
                "swarm_reasoning_backend": describe_swarm_reasoning_mode(),
                "swarm_enrichment_ready": enrichment_ready,
                "visible_machine_count": len(machines),
                "detail": (
                    "Dedalus Machines API reachable"
                    if enrichment_ready
                    else "Dedalus Machines API reachable; remote enrichment backend is not configured"
                ),
            }
        except Exception as exc:
            return {
                "status": "broken",
                "mode": runtime_mode,
                "ready": False,
                "dedalus_api_key_present": True,
                "detail": str(exc),
            }

    return {
        "status": "broken",
        "mode": runtime_mode,
        "ready": False,
        "detail": f"Unsupported RUNTIME_MODE={runtime_mode!r}",
    }


async def build_readiness_report() -> dict[str, Any]:
    runtime_mode = _runtime_mode()
    db_check = probe_db()
    runtime_check = await _runtime_check(runtime_mode)

    routing_provider = os.getenv("ROUTING_PROVIDER", "osrm").strip().lower() or "osrm"
    osrm_base_url = os.getenv("OSRM_BASE_URL", "http://osrm:5000")
    if routing_provider == "osrm":
        routing = await _probe_osrm(osrm_base_url)
        routing["required"] = False
        routing["provider"] = "osrm"
    else:
        routing = {
            "status": "degraded",
            "provider": routing_provider,
            "required": False,
            "detail": "OSRM disabled; routing will fall back to ArcGIS or unavailable context",
        }

    ready = db_check["status"] == "ok" and bool(runtime_check.get("ready"))
    degraded = (
        routing["status"] != "ok"
        or _allow_runtime_fallback()
        or runtime_check.get("status") == "degraded"
    )
    status = "ready" if ready and not degraded else ("degraded" if ready else "not_ready")

    return {
        "status": status,
        "service": "unilert-api",
        "runtime_mode": runtime_mode,
        "billing_mode": describe_dedalus_billing_mode(),
        "allow_runtime_fallback_to_local": _allow_runtime_fallback(),
        "checks": {
            "database": db_check,
            "runtime": runtime_check,
            "routing": routing,
        },
    }
