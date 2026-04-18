from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class SeverityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(str, Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    ACTIVE = "active"
    REPLANNING = "replanning"
    RESOLVED = "resolved"


class Resource(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    role: str
    available: bool = True
    location: Optional[str] = None
    contact: Optional[str] = None


class Incident(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    incident_type: str
    report: str
    location: str
    severity_hint: Optional[SeverityLevel] = None
    resources: list[Resource] = Field(default_factory=list)
    status: IncidentStatus = IncidentStatus.PENDING
    current_plan_version: int = 0


class IncidentCreate(BaseModel):
    incident_type: str
    report: str
    location: str
    severity_hint: Optional[SeverityLevel] = None
    resources: list[Resource] = Field(default_factory=list)


class IncidentUpdate(BaseModel):
    update_text: str
    updated_resources: Optional[list[Resource]] = None
