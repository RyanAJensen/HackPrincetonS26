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
    runtime: str = "local"  # "local" (K2) | "dedalus" (DedalusRunner) | "swarm" (Dedalus Machines)
    machine_id: Optional[str] = None  # Dedalus machine ID when swarm runtime is active
    input_snapshot: Optional[dict] = None
    output_artifact: Optional[dict] = None
    error_message: Optional[str] = None
    error_kind: Optional[str] = None
    retry_count: int = 0
    latency_ms: Optional[int] = None
    required: bool = False
    degraded: bool = False
    fallback_used: bool = False
    log_entries: list[str] = Field(default_factory=list)

    def as_failure(self) -> "AgentFailure | None":
        if self.status != AgentStatus.FAILED:
            return None
        return AgentFailure(
            agent_type=self.agent_type,
            status=self.status,
            required=self.required,
            error_kind=self.error_kind,
            error_message=self.error_message,
            retry_count=self.retry_count,
            latency_ms=self.latency_ms,
            degraded=self.degraded,
            fallback_used=self.fallback_used,
        )


class AgentFailure(BaseModel):
    agent_type: AgentType
    status: AgentStatus = AgentStatus.FAILED
    required: bool
    error_kind: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    latency_ms: Optional[int] = None
    degraded: bool = False
    fallback_used: bool = False
