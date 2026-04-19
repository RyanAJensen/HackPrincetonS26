from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
import sys

load_dotenv()  # loads backend/.env before anything else imports os.environ

from db import get_db_path, init_db
from api.routes import router
from runtime.dedalus_client_config import (
    describe_dedalus_billing_mode,
    describe_swarm_reasoning_mode,
    swarm_enrichment_backend_ready,
)
from runtime.dedalus_dcs import DedalusMachinesClient
from runtime.dedalus_startup import run_startup_dedalus_checks

app = FastAPI(title="Unilert — EMS & Hospital Coordination", version="1.0.0")

LOCAL_FRONTEND_ORIGIN_REGEX = (
    r"^https?://("
    r"localhost|127\.0\.0\.1|0\.0\.0\.0|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}|"
    r"[a-zA-Z0-9.-]+\.local"
    r")(?::\d+)?$"
)

cors_allow_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if origin.strip()
]
cors_allow_origin_regex = os.getenv("CORS_ALLOW_ORIGIN_REGEX", LOCAL_FRONTEND_ORIGIN_REGEX)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins,
    allow_origin_regex=cors_allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.on_event("startup")
async def startup():
    init_db()
    runtime_mode = os.getenv("RUNTIME_MODE", "dedalus")
    dedalus_key = os.getenv("DEDALUS_API_KEY")
    k2_key = os.getenv("K2_API_KEY")
    arcgis_key = os.getenv("ARC_GIS_API_KEY")
    routing_provider = os.getenv("ROUTING_PROVIDER", "osrm")
    osrm_base = os.getenv("OSRM_BASE_URL", "http://osrm:5000")
    strict = os.getenv("DEDALUS_STRICT", "").lower() in ("1", "true", "yes")
    allow_runtime_fallback = os.getenv("ALLOW_RUNTIME_FALLBACK_TO_LOCAL", "").lower() in ("1", "true", "yes")
    print("=" * 60)
    print("Unilert — startup")
    print(f"  Python executable:  {sys.executable}")
    print(f"  Runtime mode:       {runtime_mode}")
    print(f"  Billing mode:       {describe_dedalus_billing_mode()}")
    print(f"  Swarm reasoning:    {describe_swarm_reasoning_mode()}")
    print(f"  DEDALUS_STRICT:     {strict}")
    print(f"  Runtime fallback:   {allow_runtime_fallback}")
    print(f"  DEDALUS_API_KEY:    {'SET (' + dedalus_key[:8] + '...)' if dedalus_key else 'NOT SET'}")
    print(f"  K2_API_KEY:         {'SET (' + k2_key[:8] + '...)' if k2_key else 'NOT SET — will fail'}")
    print(f"  ARC_GIS_API_KEY:    {'SET (' + arcgis_key[:8] + '...)' if arcgis_key else 'NOT SET — routing disabled'}")
    print(f"  Routing provider:   {routing_provider} ({osrm_base if routing_provider == 'osrm' else 'fallback/ArcGIS'})")
    print(f"  DB_PATH:            {get_db_path()}")
    print(f"  CORS origins:       {', '.join(cors_allow_origins) if cors_allow_origins else 'none'}")
    if runtime_mode != "local" and not dedalus_key:
        print("  Dedalus status:     runtime requests Dedalus; analyze/replan will fail until DEDALUS_API_KEY is set")
    elif runtime_mode == "local":
        print("  Dedalus status:     explicit local mode enabled (K2 path)")
    elif runtime_mode == "swarm":
        print("  Dedalus status:     Dedalus Machines swarm mode enabled")
        if not swarm_enrichment_backend_ready():
            print("  Swarm warning:      remote enrichment backend is not configured;")
            print("                      local-first decisions will work but machine swarm reasoning will be degraded")
    dedalus_checks = run_startup_dedalus_checks()
    if runtime_mode == "dedalus":
        if not dedalus_key:
            raise RuntimeError(
                "RUNTIME_MODE=dedalus requires DEDALUS_API_KEY. "
                "Set DEDALUS_API_KEY or use RUNTIME_MODE=local explicitly."
            )
        if not dedalus_checks.get("dedalus_labs_import_ok"):
            raise RuntimeError(
                "RUNTIME_MODE=dedalus requires dedalus_labs to be importable in this interpreter. "
                f"Import error: {dedalus_checks.get('dedalus_import_error')}"
            )
        if not dedalus_checks.get("dedalus_runner_init_ok"):
            raise RuntimeError(
                "RUNTIME_MODE=dedalus requires DedalusRunner(client) to initialize successfully. "
                f"{dedalus_checks.get('dedalus_runner_message')}"
            )
    elif runtime_mode == "swarm":
        if not dedalus_key:
            raise RuntimeError(
                "RUNTIME_MODE=swarm requires DEDALUS_API_KEY. "
                "Set DEDALUS_API_KEY or use RUNTIME_MODE=local or RUNTIME_MODE=dedalus explicitly."
            )
        try:
            machines = await DedalusMachinesClient(dedalus_key).list_machines()
            print(f"  Dedalus Machines:   API reachable ({len(machines)} existing machine(s) visible)")
        except Exception as exc:
            raise RuntimeError(
                "RUNTIME_MODE=swarm requires access to Dedalus Machines API. "
                f"{exc}"
            ) from exc
    print("=" * 60)


if __name__ == "__main__":
    # Always use this interpreter: python main.py (same as sys.executable).
    # Do not run a globally installed `uvicorn` on PATH; it may not see the venv where dedalus_labs is installed.
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
