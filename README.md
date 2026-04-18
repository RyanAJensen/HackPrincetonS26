# Unilert — Campus Incident Response Copilot

Adaptive AI-powered decision-support tool for campus emergency response.  
Built with Next.js, FastAPI, Claude, and Dedalus Machines.

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
│   │   ├── llm.py                # Anthropic API wrapper
│   │   ├── prompts.py            # Prompt templates for each agent
│   │   ├── specialist_agents.py  # 4 agent functions
│   │   └── orchestrator.py       # Sequential pipeline + plan synthesis + diff
│   ├── runtime/
│   │   ├── base.py               # AgentRuntime ABC
│   │   ├── local_runtime.py      # LocalAgentRuntime
│   │   └── dedalus_runtime.py    # DedalusAgentRuntime (falls back gracefully)
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
ANTHROPIC_API_KEY=sk-ant-...     # Required
DEDALUS_API_KEY=                 # Optional — falls back to local runtime
DEDALUS_PROJECT_ID=unilert
RUNTIME_MODE=dedalus             # "dedalus" | "local"
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

## How Dedalus Is Integrated

Each of the four specialist agents (Incident Parser, Risk Assessor, Action Planner, Communications) is executed through a `DedalusAgentRuntime`:

1. **Machine creation**: When an agent run starts, a Dedalus Machine is created with incident metadata attached (`incident_id`, `agent_type`, `plan_version`, `run_id`).
2. **Persistent state**: Each machine represents one agent execution and can be inspected, resumed, or replayed independently.
3. **Artifact persistence**: After the agent function completes, structured output is stored in the machine's artifact store via `artifacts.put(key="output", ...)`.
4. **Machine ID tracking**: The `machine_id` is stored on `AgentRun` and shown in the Agent Status Panel UI, making Dedalus visibility first-class.
5. **Graceful fallback**: If `DEDALUS_API_KEY` is not set, the runtime falls back to in-process execution with a synthetic `machine_id` (shown as `local-xxxxxxxx`).

The `AgentRuntime` ABC makes the runtime entirely swappable — set `RUNTIME_MODE=local` to bypass Dedalus entirely for development.

---

## What Is Mocked vs Live

| Feature | Status |
|---|---|
| Incident creation | Live |
| Agent pipeline (4 agents) | Live (calls Claude) |
| Plan synthesis | Live |
| Plan diff generation | Live |
| Replanning | Live |
| Dedalus machine creation | Live if `DEDALUS_API_KEY` set; mocked (local fallback) otherwise |
| Map embed | Static OpenStreetMap (Princeton campus coordinates) |
| Resource assignment | Seeded static data |

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
