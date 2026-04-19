from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class StrictSchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IncidentParserMedicalImpactOutput(StrictSchemaModel):
    affected_population: str
    estimated_injured: str
    critical: int
    moderate: int
    minor: int
    at_risk_groups: list[str]


class IncidentParserOutput(StrictSchemaModel):
    parsed_type: str
    confirmed_location: str
    operational_period: str
    affected_population: str
    key_hazards: list[str]
    immediate_life_safety_threat: bool
    infrastructure_impact: Optional[str]
    time_sensitivity: Literal["immediate", "urgent", "moderate", "low"]
    confirmed_facts: list[str]
    unknowns: list[str]
    location_notes: str
    medical_impact: IncidentParserMedicalImpactOutput


class RiskAssessorOutput(StrictSchemaModel):
    severity_level: Literal["low", "medium", "high", "critical"]
    confidence: float
    incident_objectives: list[str]
    primary_risks: list[str]
    safety_considerations: list[str]
    weather_driven_threats: list[str]
    replan_triggers: list[str]
    healthcare_risks: list[str]


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
    required_response: str
    required_action: str


class PatientTransportOutput(StrictSchemaModel):
    primary_facilities: list[str]
    alternate_facilities: list[str]
    transport_routes: list[str]
    constraints: list[str]
    fallback_if_primary_unavailable: str


class ActionPlannerOutput(StrictSchemaModel):
    incident_summary: str
    operational_priorities: list[str]
    immediate_actions: list[PlannerActionOutput]
    short_term_actions: list[PlannerActionOutput]
    ongoing_actions: list[PlannerActionOutput]
    resource_assignments: ResourceAssignmentsOutput
    primary_access_route: str
    alternate_access_route: str
    assumptions: list[PlannerAssumptionOutput]
    missing_information: list[str]
    triage_priorities: list[TriagePriorityOutput]
    patient_transport: PatientTransportOutput


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


class ReplanContextOutput(StrictSchemaModel):
    significant_change: bool
    affected_sections: list[str]
    reasoning: str
    update_context: str
