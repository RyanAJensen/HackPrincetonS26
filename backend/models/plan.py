from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import uuid


# ── Shared primitives ────────────────────────────────────────────────────────

class ActionItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    assigned_to: Optional[str] = None
    timeframe: Optional[str] = None
    priority: int = 1


class Assumption(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    impact: str
    confidence: float


class CommunicationDraft(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    audience: str
    channel: str
    subject: Optional[str] = None
    body: str
    urgency: str = "normal"


class RoleAssignment(BaseModel):
    role: str
    assigned_to: str
    responsibilities: list[str]


# ── Patient flow & facility coordination ─────────────────────────────────────

class FacilityAssignment(BaseModel):
    """Routing decision: which patients go to which hospital and why."""
    hospital: str
    patients_assigned: int = 0
    # normal | elevated | critical
    capacity_strain: str = "normal"
    # patient severity types being sent here, e.g. ["critical", "moderate"]
    patient_types: list[str] = Field(default_factory=list)
    routing_reason: str = ""
    reroute_trigger: str = ""


class PatientFlowSummary(BaseModel):
    """Top-level patient distribution overview for the command dashboard."""
    total_incoming: int = 0
    critical: int = 0
    moderate: int = 0
    minor: int = 0
    facility_assignments: list[FacilityAssignment] = Field(default_factory=list)
    bottlenecks: list[str] = Field(default_factory=list)
    distribution_rationale: str = ""


class Tradeoff(BaseModel):
    """An explicit decision tradeoff surfaced by the Operations Planner."""
    description: str
    option_a: str
    option_b: str
    recommendation: str


class DecisionPoint(BaseModel):
    """A key coordination decision with reasoning and replan trigger."""
    decision: str
    reason: str
    assumption: str = ""
    replan_trigger: str = ""


# ── Legacy triage models (kept for compatibility) ─────────────────────────────

class MedicalImpact(BaseModel):
    affected_population: str = ""
    estimated_injured: str = ""
    critical: int = 0
    moderate: int = 0
    minor: int = 0
    at_risk_groups: list[str] = Field(default_factory=list)


class TriagePriority(BaseModel):
    priority: int
    label: str
    estimated_count: int = 0
    required_response: str = ""
    required_action: str = ""


class PatientTransport(BaseModel):
    primary_facilities: list[str] = Field(default_factory=list)
    alternate_facilities: list[str] = Field(default_factory=list)
    transport_routes: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    fallback_if_primary_unavailable: str = ""


# ── Plan version ──────────────────────────────────────────────────────────────

class PlanVersion(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    incident_id: str
    version: int
    created_at: datetime = Field(default_factory=datetime.utcnow)
    trigger: str  # "initial" or update text

    # ── Core decision outputs ──
    incident_summary: str
    operational_period: str = ""

    # Patient flow overview (primary dashboard section)
    patient_flow: Optional[PatientFlowSummary] = None

    # Triage priorities (capacity-constrained)
    triage_priorities: list[TriagePriority] = Field(default_factory=list)

    # Coordination decisions with rationale
    decision_points: list[DecisionPoint] = Field(default_factory=list)

    # Explicit tradeoffs
    tradeoffs: list[Tradeoff] = Field(default_factory=list)

    # Immediate actions
    immediate_actions: list[ActionItem] = Field(default_factory=list)
    short_term_actions: list[ActionItem] = Field(default_factory=list)
    ongoing_actions: list[ActionItem] = Field(default_factory=list)

    # Objectives & priorities
    incident_objectives: list[str] = Field(default_factory=list)
    operational_priorities: list[str] = Field(default_factory=list)

    # Comms
    communications: list[CommunicationDraft] = Field(default_factory=list)

    # Situation status
    confirmed_facts: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)

    # Risk
    assessed_severity: str = "unknown"
    confidence_score: float = 0.7
    risk_notes: list[str] = Field(default_factory=list)
    safety_considerations: list[str] = Field(default_factory=list)

    # Resource assignments
    resource_assignments: Optional[dict] = None
    role_assignments: list[RoleAssignment] = Field(default_factory=list)

    # Legacy medical impact (kept for API compat)
    medical_impact: Optional[MedicalImpact] = None
    patient_transport: Optional[PatientTransport] = None

    # Diff metadata
    diff_summary: Optional[str] = None
    changed_sections: Optional[list[str]] = None

    # External enrichment
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
    # What changed in patient flow / facility assignments
    flow_changes: list[str] = Field(default_factory=list)
