"""
Simple in-memory store with SQLite persistence.
Organized so Postgres could replace the persistence layer without touching business logic.
"""
from __future__ import annotations
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from models.incident import Incident
from models.plan import PlanVersion
from models.agent import AgentRun

DEFAULT_DB_PATH = Path(__file__).parent / "sentinel.db"


def get_db_path() -> Path:
    raw = os.getenv("DB_PATH", "").strip()
    path = Path(raw).expanduser() if raw else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _sqlite_timeout_seconds() -> float:
    try:
        return float(os.getenv("SQLITE_TIMEOUT_SECONDS", "30"))
    except ValueError:
        return 30.0


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path(), timeout=_sqlite_timeout_seconds())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS plan_versions (
                id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_runs (
                id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                plan_version INTEGER NOT NULL,
                agent_type TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS incident_machines (
                incident_id TEXT PRIMARY KEY,
                machine_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS swarm_machines (
                role TEXT PRIMARY KEY,
                machine_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()


def probe_db() -> dict[str, object]:
    path = get_db_path()
    try:
        with _get_conn() as conn:
            conn.execute("SELECT 1").fetchone()
        return {
            "status": "ok",
            "path": str(path),
            "persistent": bool(os.getenv("DB_PATH")),
        }
    except Exception as exc:
        return {
            "status": "broken",
            "path": str(path),
            "persistent": bool(os.getenv("DB_PATH")),
            "error": str(exc),
        }


# --- Incident Machines (Dedalus persistent machine registry) ---

def get_incident_machine(incident_id: str) -> Optional[str]:
    """Return the Dedalus machine_id for this incident, or None."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT machine_id FROM incident_machines WHERE incident_id=?", (incident_id,)
        ).fetchone()
        return row["machine_id"] if row else None


def save_incident_machine(incident_id: str, machine_id: str):
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO incident_machines (incident_id, machine_id, created_at) VALUES (?, ?, ?)",
            (incident_id, machine_id, datetime.utcnow().isoformat())
        )
        conn.commit()


def clear_incident_machine(incident_id: str):
    """Remove the cached machine mapping for an incident (call when machine enters terminal state)."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM incident_machines WHERE incident_id=?", (incident_id,))
        conn.commit()


# --- Swarm Machines (persistent role-based machine pool) ---

def get_swarm_machine(role: str) -> Optional[str]:
    """Return the Dedalus machine_id assigned to a swarm role, or None."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT machine_id FROM swarm_machines WHERE role=?", (role,)
        ).fetchone()
        return row["machine_id"] if row else None


def save_swarm_machine(role: str, machine_id: str):
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO swarm_machines (role, machine_id, created_at) VALUES (?, ?, ?)",
            (role, machine_id, datetime.utcnow().isoformat())
        )
        conn.commit()


def clear_swarm_machine(role: str):
    """Remove a swarm machine assignment (call when machine enters terminal state)."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM swarm_machines WHERE role=?", (role,))
        conn.commit()


def list_swarm_machines() -> dict[str, str]:
    """Return {role: machine_id} for all registered swarm machines."""
    with _get_conn() as conn:
        rows = conn.execute("SELECT role, machine_id FROM swarm_machines").fetchall()
        return {r["role"]: r["machine_id"] for r in rows}


# --- Incidents ---

def save_incident(incident: Incident):
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO incidents (id, data, created_at) VALUES (?, ?, ?)",
            (incident.id, incident.model_dump_json(), incident.created_at.isoformat())
        )
        conn.commit()


def get_incident(incident_id: str) -> Optional[Incident]:
    with _get_conn() as conn:
        row = conn.execute("SELECT data FROM incidents WHERE id=?", (incident_id,)).fetchone()
        if row:
            return Incident.model_validate_json(row["data"])
    return None


def list_incidents() -> list[Incident]:
    with _get_conn() as conn:
        rows = conn.execute("SELECT data FROM incidents ORDER BY created_at DESC").fetchall()
        return [Incident.model_validate_json(r["data"]) for r in rows]


# --- Plan Versions ---

def save_plan_version(plan: PlanVersion):
    with _get_conn() as conn:
        conn.execute(
            "DELETE FROM plan_versions WHERE incident_id=? AND version=?",
            (plan.incident_id, plan.version),
        )
        conn.execute(
            "INSERT OR REPLACE INTO plan_versions (id, incident_id, version, data, created_at) VALUES (?, ?, ?, ?, ?)",
            (plan.id, plan.incident_id, plan.version, plan.model_dump_json(), plan.created_at.isoformat())
        )
        conn.commit()


def get_plan_version(incident_id: str, version: int) -> Optional[PlanVersion]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT data FROM plan_versions WHERE incident_id=? AND version=?",
            (incident_id, version)
        ).fetchone()
        if row:
            return PlanVersion.model_validate_json(row["data"])
    return None


def get_latest_plan(incident_id: str) -> Optional[PlanVersion]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT data FROM plan_versions WHERE incident_id=? ORDER BY version DESC LIMIT 1",
            (incident_id,)
        ).fetchone()
        if row:
            return PlanVersion.model_validate_json(row["data"])
    return None


def list_plan_versions(incident_id: str) -> list[PlanVersion]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT data FROM plan_versions WHERE incident_id=? ORDER BY version ASC",
            (incident_id,)
        ).fetchall()
        return [PlanVersion.model_validate_json(r["data"]) for r in rows]


# --- Agent Runs ---

def save_agent_run(run: AgentRun):
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO agent_runs (id, incident_id, plan_version, agent_type, data, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (run.id, run.incident_id, run.plan_version, run.agent_type, run.model_dump_json(), datetime.utcnow().isoformat())
        )
        conn.commit()


def list_agent_runs(incident_id: str, plan_version: Optional[int] = None) -> list[AgentRun]:
    with _get_conn() as conn:
        if plan_version is not None:
            rows = conn.execute(
                "SELECT data FROM agent_runs WHERE incident_id=? AND plan_version=? ORDER BY created_at ASC",
                (incident_id, plan_version)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT data FROM agent_runs WHERE incident_id=? ORDER BY created_at ASC",
                (incident_id,)
            ).fetchall()
        return [AgentRun.model_validate_json(r["data"]) for r in rows]
