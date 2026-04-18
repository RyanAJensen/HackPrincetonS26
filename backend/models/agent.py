from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field
import uuid


class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentType(str, Enum):
    INCIDENT_PARSER = "incident_parser"
    RISK_ASSESSOR = "risk_assessor"
    ACTION_PLANNER = "action_planner"
    COMMUNICATIONS = "communications"


class AgentRun(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    incident_id: str
    plan_version: int
    agent_type: AgentType
    status: AgentStatus = AgentStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    runtime: str = "local"  # "local" | "dedalus"
    machine_id: Optional[str] = None  # Dedalus machine ID if applicable
    input_snapshot: Optional[dict] = None
    output_artifact: Optional[dict] = None
    error_message: Optional[str] = None
    log_entries: list[str] = Field(default_factory=list)
