from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os

load_dotenv()  # loads backend/.env before anything else imports os.environ

from db import init_db
from api.routes import router

app = FastAPI(title="Unilert — Regional Emergency Response Coordination", version="1.0.0")

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
    k2_key = os.getenv("K2_API_KEY", "IFM-pB75TfFLX28aXCKQ")
    arcgis_key = os.getenv("ARC_GIS_API_KEY")
    print("=" * 60)
    print("Sentinel / Unilert — startup")
    print(f"  Runtime mode:       {runtime_mode}")
    print(f"  DEDALUS_API_KEY:    {'SET (' + dedalus_key[:8] + '...)' if dedalus_key else 'NOT SET — local fallback'}")
    print(f"  K2_API_KEY:         {'SET (' + k2_key[:8] + '...)' if k2_key else 'NOT SET — will fail'}")
    print(f"  ARC_GIS_API_KEY:    {'SET (' + arcgis_key[:8] + '...)' if arcgis_key else 'NOT SET — routing disabled'}")
    print("=" * 60)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
