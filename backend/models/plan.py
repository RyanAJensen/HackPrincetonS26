from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import uuid

from models.incident import ICSRoleAssignment, IncidentLogEntry


# ── Shared primitives ────────────────────────────────────────────────────────

class ActionItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    assigned_to: Optional[str] = None
    timeframe: Optional[str] = None
    priority: int = 1


class OwnedOperationalAction(BaseModel):
    description: str
    owner_role: str
    owner_name: Optional[str] = None
    operational_group: Optional[str] = None
    timeframe: Optional[str] = None
    priority: int = 1
    contingency: Optional[str] = None
    critical: bool = False


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


class CommandRecommendations(BaseModel):
    command_mode: str = ""
    command_post_established: bool = False
    unified_command_recommended: bool = False
    safety_officer_recommended: bool = False
    public_information_officer_recommended: bool = False
    liaison_officer_recommended: bool = False
    operations_section_active: bool = False
    planning_section_active: bool = False
    logistics_section_active: bool = False
    finance_admin_section_active: bool = False
    triage_group_active: bool = False
    treatment_group_active: bool = False
    staging_area: str = ""
    transport_group_active: bool = False
    rationale: list[str] = Field(default_factory=list)


class CommandTransferSummary(BaseModel):
    command_mode: str = ""
    current_strategy: str = ""
    active_groups: list[str] = Field(default_factory=list)
    top_hazards: list[str] = Field(default_factory=list)
    next_decisions: list[str] = Field(default_factory=list)
    resource_status: list[str] = Field(default_factory=list)
    transfer_needs: list[str] = Field(default_factory=list)
    last_update: str = ""


class SpanOfControlWarning(BaseModel):
    supervisor_role: str
    direct_reports: int = 0
    recommended_structure: str
    reason: str
    severity: str = "advisory"


class AccountabilityIssue(BaseModel):
    kind: str
    severity: str
    message: str
    action_description: Optional[str] = None
    owner_role: Optional[str] = None


class AccountabilityReport(BaseModel):
    status: str = "ok"
    unowned_actions: list[str] = Field(default_factory=list)
    conflicting_assignments: list[str] = Field(default_factory=list)
    duplicate_assignments: list[str] = Field(default_factory=list)
    self_dispatch_risks: list[str] = Field(default_factory=list)
    issues: list[AccountabilityIssue] = Field(default_factory=list)


class MedicalOperationsBranch(BaseModel):
    group_name: str
    owner_role: str
    objectives: list[str] = Field(default_factory=list)
    actions: list[OwnedOperationalAction] = Field(default_factory=list)
    status: str = "active"


class MedicalOperationsSummary(BaseModel):
    triage: MedicalOperationsBranch
    treatment: MedicalOperationsBranch
    transport: MedicalOperationsBranch


class IncidentActionPlan(BaseModel):
    command_intent: str
    current_objectives: list[str] = Field(default_factory=list)
    organization: list[ICSRoleAssignment] = Field(default_factory=list)
    owned_actions: list[OwnedOperationalAction] = Field(default_factory=list)
    communications_plan: list[str] = Field(default_factory=list)
    responder_injury_contingency: list[str] = Field(default_factory=list)
    degradation_triggers: list[str] = Field(default_factory=list)
    operational_period: str = ""


class FallbackSummary(BaseModel):
    mode_active: bool = False
    safe_to_act_on: list[str] = Field(default_factory=list)
    unavailable_components: list[str] = Field(default_factory=list)
    unverified_assumptions: list[str] = Field(default_factory=list)


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
    command_recommendations: Optional[CommandRecommendations] = None
    owned_actions: dict[str, list[str]] = Field(default_factory=dict)
    owned_action_items: list[OwnedOperationalAction] = Field(default_factory=list)
    ics_organization: list[ICSRoleAssignment] = Field(default_factory=list)
    span_of_control: list[SpanOfControlWarning] = Field(default_factory=list)
    accountability: Optional[AccountabilityReport] = None
    medical_operations: Optional[MedicalOperationsSummary] = None
    iap: Optional[IncidentActionPlan] = None
    command_transfer_summary: Optional[CommandTransferSummary] = None

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

    # Live decision-surface metadata
    first_response_ready: bool = False
    enrichment_pending: bool = False
    fallback_mode: bool = False
    recommendation_confidence: float = 0.0
    route_confidence: str = "low"
    unavailable_components: list[str] = Field(default_factory=list)
    verified_information: list[str] = Field(default_factory=list)
    assumed_information: list[str] = Field(default_factory=list)
    fallback_summary: Optional[FallbackSummary] = None

    # External enrichment
    external_context: Optional[dict] = None
    incident_log: list[IncidentLogEntry] = Field(default_factory=list)


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
