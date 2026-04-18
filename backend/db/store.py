"""
Simple in-memory store with SQLite persistence.
Organized so Postgres could replace the persistence layer without touching business logic.
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from models.incident import Incident
from models.plan import PlanVersion
from models.agent import AgentRun

DB_PATH = Path(__file__).parent / "sentinel.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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
        conn.commit()


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
