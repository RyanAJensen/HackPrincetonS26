# Unilert — Live EMS / ICS Coordination on Dedalus Machines

Real-time emergency medical operations system for EMS supervisors, incident commanders, and hospital coordination leads.  
Built with Next.js, FastAPI, a deterministic ICS decision engine, Dedalus Machines agent swarming, and K2 Think V2.

---

## Project Structure

```
sentinel/
├── backend/
│   ├── main.py                   # FastAPI app entry point
│   ├── requirements.txt
│   ├── .env                      # ANTHROPIC_API_KEY, DEDALUS_API_KEY, etc.
│   ├── models/
│   │   ├── incident.py           # Incident, Resource, IncidentCreate
│   │   ├── plan.py               # PlanVersion, ActionItem, PlanDiff, etc.
│   │   └── agent.py              # AgentRun, AgentType, AgentStatus
│   ├── db/
│   │   └── store.py              # SQLite persistence (Postgres-swappable)
│   ├── agents/
│   │   ├── llm.py                # Strict structured LLM wrapper (K2 + Dedalus paths)
│   │   ├── prompts.py            # Prompt templates for each agent
│   │   ├── specialist_agents.py  # 4 agent functions
│   │   └── orchestrator.py       # Two-speed orchestration: local-first + swarm enrichment
│   ├── runtime/
│   │   ├── base.py               # AgentRuntime ABC
│   │   ├── local_runtime.py      # LocalAgentRuntime
│   │   ├── dedalus_runtime.py    # DedalusRunner runtime
│   │   └── dedalus_machine_runtime.py  # Dedalus Machines swarm runtime
│   ├── services/
│   │   ├── decision_engine.py    # Deterministic ICS / transport logic
│   │   ├── context_ingestion_service.py
│   │   ├── routing_service.py
│   │   └── hospital_directory_service.py
│   └── data/
│       └── seed.py               # Demo scenarios + campus resources
└── frontend/
    ├── app/
    │   ├── page.tsx              # Dashboard / incident list
    │   └── incidents/[id]/
    │       └── page.tsx          # Active incident view
    ├── components/sentinel/
    │   ├── AgentStatusPanel.tsx
    │   ├── ActionPlanPanel.tsx
    │   ├── CommunicationsPanel.tsx
    │   ├── PlanDiffPanel.tsx
    │   ├── ReplanForm.tsx
    │   ├── LocationPanel.tsx
    │   ├── PlanVersionHistory.tsx
    │   ├── SeverityBadge.tsx
    │   └── StatusBadge.tsx
    └── lib/
        └── api.ts                # Typed API client
```

---

## Setup

### Environment Variables

**Backend** (`backend/.env`):
```
DEDALUS_API_KEY=dsk-...          # Required for Dedalus Machines swarm mode
K2_API_KEY=ifm-...               # Required to make K2 Think V2 the swarm reasoning core
LLM_BACKEND=k2                   # Prefer K2 in local + remote machine workers
K2_MODEL=MBZUAI-IFM/K2-Think-v2
RUNTIME_MODE=swarm               # "swarm" | "dedalus" | "local"
ROUTING_PROVIDER=osrm
OSRM_BASE_URL=http://osrm:5000
```

**Frontend** (`frontend/.env.local`):
```
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

### Running

**Backend:**

Create the venv and install deps, then **always start the API with the venv interpreter** (`venv\Scripts\python.exe` on Windows, `venv/bin/python` on Mac/Linux). Do **not** run a globally installed `uvicorn` from PATH unless that `uvicorn` belongs to the same interpreter; reload subprocesses inherit `sys.executable`, and the Dedalus startup checks read the same environment as `dedalus_labs`.

```bash
cd backend
python -m venv venv
venv/Scripts/pip install -r requirements.txt   # Windows
# or: venv/bin/pip install -r requirements.txt  # Mac/Linux

# Set ANTHROPIC_API_KEY in .env, then (Windows cmd/PowerShell/Git Bash):
venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Windows shortcuts (from `backend/`): `start.cmd` or `.\start.ps1` (both call `venv\Scripts\python.exe -m uvicorn ...`). Git Bash:

```bash
cd backend && ./venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

---

## How Dedalus + K2 Are Integrated

Unilert uses a **two-speed architecture**:

1. **Immediate answer (2–5s)**: deterministic local normalization + decision engine produce the first ICS-safe operational answer.
2. **Swarm enrichment**: four specialist agents run on **Dedalus Machines** and progressively enhance the live decision surface:
   - `incident_parser`
   - `risk_assessor`
   - `action_planner`
   - `communications`

When `K2_API_KEY` is set, those machine workers use **K2 Think V2** as the core remote reasoning model. This keeps K2 central to the product instead of a side call, while preserving Dedalus Machines as the swarm execution layer.

If swarm enrichment is unavailable, the deterministic local decision surface still works and remains operationally useful.

---

## What Is Mocked vs Live

| Feature | Status |
|---|---|
| Incident creation | Live |
| Agent pipeline (4 agents) | Live (Dedalus Machines swarm, K2-capable) |
| Plan synthesis | Live |
| Plan diff generation | Live |
| Replanning | Live |
| Dedalus machine creation | Live if `DEDALUS_API_KEY` set |
| Map embed | Static OpenStreetMap (Princeton campus coordinates) |
| Resource assignment | Deterministic ICS decision engine + static/open context |

---

## Demo Script for Judges

1. Open `http://localhost:3000` — the **Dashboard** appears.
2. Click **"🔥 Dorm Fire – Whitman College"** demo scenario → click **▶ Run Analysis**.
3. Watch the **Agent Pipeline** panel on the left — 4 agents run sequentially with live status dots and Dedalus machine IDs.
4. The **Action Plan** appears: severity badge, top priorities, immediate actions, 30-min / 2-hour phases, role assignments.
5. Navigate to **Communications** tab — see responder brief, public advisory, admin update.
6. Go to **Submit Update** tab — click "Primary access road is blocked…" quick-fill → **Submit Update & Replan**.
7. Agents run again. The **Plan Diff** tab appears, highlighting added/removed actions and changed sections.
8. Click **Plan History** in the sidebar to compare v1 vs v2.

Key talking points:
- Each agent has a persistent Dedalus Machine with a traceable `machine_id`
- Plan diff shows exactly what changed and why
- System is framed as decision-support, not autonomous emergency control
- Architecture cleanly separates runtime (Dedalus / local), agents, and data layer
