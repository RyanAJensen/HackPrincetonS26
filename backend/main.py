from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
import sys

load_dotenv()  # loads backend/.env before anything else imports os.environ

from db import init_db
from api.routes import router
from runtime.dedalus_client_config import describe_dedalus_billing_mode
from runtime.dedalus_dcs import DedalusMachinesClient
from runtime.dedalus_startup import run_startup_dedalus_checks

app = FastAPI(title="Unilert — EMS & Hospital Coordination", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
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
    strict = os.getenv("DEDALUS_STRICT", "").lower() in ("1", "true", "yes")
    print("=" * 60)
    print("Unilert — startup")
    print(f"  Python executable:  {sys.executable}")
    print(f"  Runtime mode:       {runtime_mode}")
    print(f"  Billing mode:       {describe_dedalus_billing_mode()}")
    print(f"  DEDALUS_STRICT:     {strict}")
    print(f"  DEDALUS_API_KEY:    {'SET (' + dedalus_key[:8] + '...)' if dedalus_key else 'NOT SET'}")
    print(f"  K2_API_KEY:         {'SET (' + k2_key[:8] + '...)' if k2_key else 'NOT SET — will fail'}")
    print(f"  ARC_GIS_API_KEY:    {'SET (' + arcgis_key[:8] + '...)' if arcgis_key else 'NOT SET — routing disabled'}")
    if runtime_mode != "local" and not dedalus_key:
        print("  Dedalus status:     runtime requests Dedalus; analyze/replan will fail until DEDALUS_API_KEY is set")
    elif runtime_mode == "local":
        print("  Dedalus status:     explicit local mode enabled (K2 path)")
    elif runtime_mode == "swarm":
        print("  Dedalus status:     Dedalus Machines swarm mode enabled")
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
