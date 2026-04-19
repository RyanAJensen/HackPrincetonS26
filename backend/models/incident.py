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


class CommandMode(str, Enum):
    INVESTIGATIVE = "investigative"
    FAST_ATTACK = "fast_attack"
    COMMAND = "command"


class Resource(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    role: str
    available: bool = True
    deployment_status: str = "available"  # available | assigned | staged | requested | unavailable
    ics_group: Optional[str] = None
    location: Optional[str] = None
    contact: Optional[str] = None


class ICSRoleAssignment(BaseModel):
    role: str
    assigned_to: Optional[str] = None
    agency: Optional[str] = None
    active: bool = True
    responsibilities: list[str] = Field(default_factory=list)


class HospitalCapacity(BaseModel):
    """Current capacity status of a receiving facility."""
    name: str
    available_beds: Optional[int] = None
    total_beds: Optional[int] = None
    # normal | elevated | critical | diversion
    status: str = "normal"
    # trauma | burn | pediatric | decon | general
    specialty: Optional[str] = None
    distance_mi: Optional[float] = None
    eta_min: Optional[int] = None


class TriageCounts(BaseModel):
    critical: int = 0
    moderate: int = 0
    minor: int = 0


class IncidentLogEntry(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source: str = "field"
    category: str = "update"
    message: str


class Incident(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    incident_type: str
    report: str
    location: str
    severity_hint: Optional[SeverityLevel] = None
    hazards: list[str] = Field(default_factory=list)
    access_constraints: list[str] = Field(default_factory=list)
    estimated_patients: int = 0
    triage_counts: TriageCounts = Field(default_factory=TriageCounts)
    command_mode: Optional[CommandMode] = None
    command_post_established: bool = False
    unified_command: bool = False
    safety_officer_assigned: bool = False
    ics_organization: list[ICSRoleAssignment] = Field(default_factory=list)
    staging_area: Optional[str] = None
    operational_objectives: list[str] = Field(default_factory=list)
    resources: list[Resource] = Field(default_factory=list)
    assigned_resources: list[str] = Field(default_factory=list)
    staged_resources: list[str] = Field(default_factory=list)
    requested_resources: list[str] = Field(default_factory=list)
    out_of_service_resources: list[str] = Field(default_factory=list)
    transport_group_active: bool = False
    current_bottlenecks: list[str] = Field(default_factory=list)
    incident_log: list[IncidentLogEntry] = Field(default_factory=list)
    hospital_capacities: list[HospitalCapacity] = Field(default_factory=list)
    status: IncidentStatus = IncidentStatus.PENDING
    current_plan_version: int = 0


class IncidentCreate(BaseModel):
    incident_type: str
    report: str
    location: str
    severity_hint: Optional[SeverityLevel] = None
    hazards: list[str] = Field(default_factory=list)
    access_constraints: list[str] = Field(default_factory=list)
    command_mode: Optional[CommandMode] = None
    command_post_established: bool = False
    unified_command: bool = False
    safety_officer_assigned: bool = False
    ics_organization: list[ICSRoleAssignment] = Field(default_factory=list)
    staging_area: Optional[str] = None
    resources: list[Resource] = Field(default_factory=list)
    hospital_capacities: list[HospitalCapacity] = Field(default_factory=list)


class IncidentUpdate(BaseModel):
    update_text: str
    log_source: str = "field"
    hazards: Optional[list[str]] = None
    access_constraints: Optional[list[str]] = None
    estimated_patients: Optional[int] = None
    triage_counts: Optional[TriageCounts] = None
    command_mode: Optional[CommandMode] = None
    command_post_established: Optional[bool] = None
    unified_command: Optional[bool] = None
    safety_officer_assigned: Optional[bool] = None
    ics_organization: Optional[list[ICSRoleAssignment]] = None
    staging_area: Optional[str] = None
    operational_objectives: Optional[list[str]] = None
    updated_resources: Optional[list[Resource]] = None
    assigned_resources: Optional[list[str]] = None
    staged_resources: Optional[list[str]] = None
    requested_resources: Optional[list[str]] = None
    out_of_service_resources: Optional[list[str]] = None
    transport_group_active: Optional[bool] = None
    current_bottlenecks: Optional[list[str]] = None
    updated_hospital_capacities: Optional[list[HospitalCapacity]] = None
