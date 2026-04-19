from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class StrictSchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ─── Situation Unit output ────────────────────────────────────────────────────

class IncidentParserMedicalImpactOutput(StrictSchemaModel):
    affected_population: str
    estimated_injured: str
    critical: int
    moderate: int
    minor: int
    at_risk_groups: list[str]


class IncidentParserOutput(StrictSchemaModel):
    # Core situation
    incoming_patient_count: int = 0
    critical: int = 0
    moderate: int = 0
    minor: int = 0
    affected_population: str
    estimated_injured: str = ""
    at_risk_groups: list[str] = Field(default_factory=list)
    # Legacy fields kept for orchestrator compat
    parsed_type: str = ""
    confirmed_location: str = ""
    operational_period: str
    key_hazards: list[str]
    immediate_life_safety_threat: bool
    infrastructure_impact: Optional[str] = None
    time_sensitivity: Literal["immediate", "urgent", "moderate", "low"]
    # Transport and capacity context
    transport_status: str = ""
    hospital_capacity_notes: str = ""
    confirmed_facts: list[str]
    unknowns: list[str]
    location_notes: str
    medical_impact: IncidentParserMedicalImpactOutput


# ─── Intelligence Unit output (K2 Think V2) ──────────────────────────────────

class RiskAssessorOutput(StrictSchemaModel):
    severity_level: Literal["low", "medium", "high", "critical"]
    confidence: float
    incident_objectives: list[str]
    primary_risks: list[str]
    safety_considerations: list[str]
    weather_driven_threats: list[str]
    replan_triggers: list[str]
    healthcare_risks: list[str]
    # New decision-focused fields
    capacity_bottlenecks: list[str] = Field(default_factory=list)
    transport_delays: list[str] = Field(default_factory=list)
    cascade_risks: list[str] = Field(default_factory=list)
    decision_triggers: list[str] = Field(default_factory=list)
    resource_adequacy: str = "sufficient"
    resource_gaps: list[str] = Field(default_factory=list)
    estimated_duration_hours: float = 2.0
    mutual_aid_needed: bool = False


# ─── Operations Planner output (K2 Think V2) ─────────────────────────────────

class PlannerActionOutput(StrictSchemaModel):
    description: str
    assigned_to: str
    timeframe: str


class ResourceAssignmentsOutput(StrictSchemaModel):
    operations: list[str]
    logistics: list[str]
    communications: list[str]
    command: list[str]


class PlannerAssumptionOutput(StrictSchemaModel):
    description: str
    impact: str
    confidence: float


class TriagePriorityOutput(StrictSchemaModel):
    priority: int
    label: str
    estimated_count: int
    required_response: str = ""
    required_action: str


class PatientTransportOutput(StrictSchemaModel):
    primary_facilities: list[str]
    alternate_facilities: list[str]
    transport_routes: list[str]
    constraints: list[str]
    fallback_if_primary_unavailable: str = ""


class FacilityAssignmentOutput(StrictSchemaModel):
    hospital: str
    patients_assigned: int
    capacity_strain: Literal["normal", "elevated", "critical"]
    patient_types: list[str]
    routing_reason: str
    reroute_trigger: str


class PatientFlowOutput(StrictSchemaModel):
    total_incoming: int
    critical: int
    moderate: int
    minor: int
    distribution_rationale: str
    bottlenecks: list[str]
    facility_assignments: list[FacilityAssignmentOutput]


class DecisionPointOutput(StrictSchemaModel):
    decision: str
    reason: str
    assumption: str
    replan_trigger: str


class TradeoffOutput(StrictSchemaModel):
    description: str
    option_a: str
    option_b: str
    recommendation: str


class ActionPlannerOutput(StrictSchemaModel):
    incident_summary: str
    # Core decision outputs
    patient_flow: PatientFlowOutput
    decision_points: list[DecisionPointOutput]
    tradeoffs: list[TradeoffOutput]
    # Priorities and actions
    operational_priorities: list[str]
    immediate_actions: list[PlannerActionOutput]
    short_term_actions: list[PlannerActionOutput]
    ongoing_actions: list[PlannerActionOutput]
    # Legacy resource assignments
    resource_assignments: ResourceAssignmentsOutput
    primary_access_route: str
    alternate_access_route: str
    assumptions: list[PlannerAssumptionOutput]
    missing_information: list[str]
    triage_priorities: list[TriagePriorityOutput]
    patient_transport: PatientTransportOutput


# ─── Communications Officer output ───────────────────────────────────────────

class EMSBriefOutput(StrictSchemaModel):
    audience: str
    channel: str
    urgency: str
    body: str


class DirectedCommunicationOutput(StrictSchemaModel):
    audience: str
    channel: str
    urgency: str
    subject: str
    body: str


class CommunicationsOutput(StrictSchemaModel):
    ems_brief: EMSBriefOutput
    hospital_notification: DirectedCommunicationOutput
    public_advisory: DirectedCommunicationOutput
    administration_update: DirectedCommunicationOutput


# ─── Lean schemas (fast mode / optimized pipeline) ───────────────────────────
# These are what the LLM actually generates. Orchestrator maps them to PlanVersion.

class LeanParserOutput(StrictSchemaModel):
    """Compact situation parser output — ~60% smaller than IncidentParserOutput."""
    patient_count: int = 0
    critical: int = 0
    moderate: int = 0
    minor: int = 0
    affected_population: str = ""
    hazards: list[str] = Field(default_factory=list)
    transport_note: str = ""
    hospital_notes: str = ""
    unknowns: list[str] = Field(default_factory=list)
    immediate_threat: bool = False
    time_sensitivity: Literal["immediate", "urgent", "moderate", "low"] = "urgent"
    operational_period: str = ""


class LeanRiskOutput(StrictSchemaModel):
    """Compact risk output — 3 lists max 3 items each."""
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    top_risks: list[str] = Field(default_factory=list)
    bottlenecks: list[str] = Field(default_factory=list)
    replan_triggers: list[str] = Field(default_factory=list)
    mutual_aid_needed: bool = False
    resource_adequacy: Literal["sufficient", "strained", "insufficient"] = "strained"


class LeanFacilityOutput(StrictSchemaModel):
    hospital: str
    patients: int = 0
    strain: Literal["normal", "elevated", "critical"] = "normal"
    reason: str = ""


class LeanPlannerOutput(StrictSchemaModel):
    """Compact planner output — actions as strings, no nested objects."""
    summary: str = ""
    total_patients: int = 0
    critical: int = 0
    moderate: int = 0
    minor: int = 0
    facility_assignments: list[LeanFacilityOutput] = Field(default_factory=list)
    distribution_note: str = ""
    immediate_actions: list[str] = Field(default_factory=list)
    short_term_actions: list[str] = Field(default_factory=list)
    priorities: list[str] = Field(default_factory=list)
    key_decision: str = ""
    replan_if: str = ""
    missing_info: list[str] = Field(default_factory=list)
    triage_critical_action: str = ""
    triage_moderate_action: str = ""
    triage_minor_action: str = ""
    primary_route: str = ""
    alternate_route: str = ""


class LeanCoordinationOutput(StrictSchemaModel):
    """Combined Situation+Threat+Plan in one call (Fast Mode)."""
    # Situation
    patient_count: int = 0
    critical: int = 0
    moderate: int = 0
    minor: int = 0
    hazards: list[str] = Field(default_factory=list)
    transport_note: str = ""
    # Risk
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    top_risks: list[str] = Field(default_factory=list)
    bottlenecks: list[str] = Field(default_factory=list)
    # Plan
    summary: str = ""
    facility_assignments: list[LeanFacilityOutput] = Field(default_factory=list)
    immediate_actions: list[str] = Field(default_factory=list)
    priorities: list[str] = Field(default_factory=list)
    key_decision: str = ""
    replan_if: str = ""
    missing_info: list[str] = Field(default_factory=list)


class LeanCommunicationsOutput(StrictSchemaModel):
    """Compact comms — plain strings instead of nested objects."""
    ems_brief: str = ""
    hospital_notification: str = ""
    public_advisory: str = ""
    admin_update: str = ""


# ─── Replanning ───────────────────────────────────────────────────────────────

class ReplanContextOutput(StrictSchemaModel):
    significant_change: bool
    affected_sections: list[str]
    reasoning: str
    update_context: str
