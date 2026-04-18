from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class MedicalImpact(BaseModel):
    affected_population: str = ""
    estimated_injured: str = ""       # e.g. "10–25"
    critical: int = 0
    moderate: int = 0
    minor: int = 0
    at_risk_groups: list[str] = Field(default_factory=list)


class TriagePriority(BaseModel):
    priority: int                      # 1, 2, or 3
    label: str                         # e.g. "critical / life-threatening"
    estimated_count: int = 0
    required_response: str = ""       # immediate transport | on-site stabilization | monitoring / delayed transport
    required_action: str = ""         # operational detail (kept for API compat)


class PatientTransport(BaseModel):
    primary_facilities: list[str] = Field(default_factory=list)
    alternate_facilities: list[str] = Field(default_factory=list)
    transport_routes: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    fallback_if_primary_unavailable: str = ""  # ArcGIS alternate / manual routing


class ActionItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    assigned_to: Optional[str] = None
    timeframe: Optional[str] = None
    priority: int = 1  # 1=highest


class RoleAssignment(BaseModel):
    role: str
    assigned_to: str
    responsibilities: list[str]


class CommunicationDraft(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    audience: str
    channel: str
    subject: Optional[str] = None
    body: str
    urgency: str = "normal"


class Assumption(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    impact: str
    confidence: float


class PlanVersion(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    incident_id: str
    version: int
    created_at: datetime = Field(default_factory=datetime.utcnow)
    trigger: str  # "initial" | update text

    # IAP Section 1 — Incident Overview
    incident_summary: str
    operational_period: str = ""

    # IAP Section 2 — Incident Objectives (from Intelligence/Planning)
    incident_objectives: list[str] = Field(default_factory=list)

    # IAP Section 3 — Operational Priorities
    operational_priorities: list[str] = Field(default_factory=list)

    # IAP Section 4 — Execution Plan (three phases)
    immediate_actions: list[ActionItem]       # 0–10 min
    short_term_actions: list[ActionItem]      # 10–30 min
    ongoing_actions: list[ActionItem]         # 30–120 min

    # IAP Section 5 — Resource Assignments (ICS sections)
    resource_assignments: Optional[dict] = None  # {operations, logistics, communications, command}
    role_assignments: list[RoleAssignment] = Field(default_factory=list)  # legacy compat

    # IAP Section 6 — Safety
    safety_considerations: list[str] = Field(default_factory=list)

    # IAP Section 7 — Communications
    communications: list[CommunicationDraft]

    # IAP Section 8 — Situation Status
    confirmed_facts: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    assumptions: list[Assumption]
    missing_information: list[str]

    # IAP Section 9 — Medical Triage
    medical_impact: Optional[MedicalImpact] = None
    triage_priorities: list[TriagePriority] = Field(default_factory=list)
    patient_transport: Optional[PatientTransport] = None

    # Meta
    assessed_severity: str
    confidence_score: float
    risk_notes: list[str]

    # Diff
    diff_summary: Optional[str] = None
    changed_sections: Optional[list[str]] = None

    # External data enrichment
    external_context: Optional[dict] = None


class PlanDiff(BaseModel):
    from_version: int
    to_version: int
    summary: str
    changed_sections: list[str]
    added_actions: list[ActionItem]
    removed_actions: list[ActionItem]
    modified_actions: list[dict]
    updated_priorities: Optional[list[str]] = None
    updated_role_assignments: Optional[list[RoleAssignment]] = None
