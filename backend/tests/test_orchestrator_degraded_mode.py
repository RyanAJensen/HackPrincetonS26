from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents.orchestrator import collect_agent_failures, generate_initial_plan, generate_plan
from agents.llm import LLMStructuredError
from models.agent import AgentRun, AgentStatus, AgentType
from models.incident import Incident, HospitalCapacity
from runtime.local_runtime import LocalAgentRuntime


PARSER_OUTPUT = {
    "parsed_type": "Flash Flood",
    "confirmed_location": "Washington Road at Lake Carnegie Bridge, Princeton, NJ",
    "operational_period": "1400-1900",
    "affected_population": "6 people",
    "key_hazards": ["swift water", "vehicle entrapment"],
    "immediate_life_safety_threat": True,
    "infrastructure_impact": "Bridge access constrained",
    "time_sensitivity": "immediate",
    "confirmed_facts": ["Multiple stranded occupants", "Roadway flooding reported"],
    "unknowns": ["Exact patient count pending triage"],
    "location_notes": "Bridge approach may be impassable",
    "medical_impact": {
        "affected_population": "6 people",
        "estimated_injured": "2-4",
        "critical": 1,
        "moderate": 1,
        "minor": 2,
        "at_risk_groups": ["elderly"],
    },
}

PLANNER_OUTPUT = {
    "incident_summary": "Swift-water rescue in progress with medical transport planning underway.",
    "operational_priorities": [
        "1. Rescue and triage stranded occupants",
        "2. Maintain EMS access corridor",
        "3. Coordinate receiving hospitals",
    ],
    "immediate_actions": [
        {"description": "Deploy EMS to bridge approach", "assigned_to": "EMS Branch", "timeframe": "0-10 min"}
    ],
    "short_term_actions": [
        {"description": "Establish triage area", "assigned_to": "Medical Group", "timeframe": "10-30 min"}
    ],
    "ongoing_actions": [
        {"description": "Coordinate hospital handoff updates", "assigned_to": "Transport Officer", "timeframe": "30-120 min"}
    ],
    "resource_assignments": {
        "operations": ["EMS Unit 12 -> triage"],
        "logistics": ["Stage dry PPE"],
        "communications": ["Notify receiving hospitals"],
        "command": ["Maintain unified command"],
    },
    "primary_access_route": "Use northbound bridge approach",
    "alternate_access_route": "Use Mercer Street staging",
    "assumptions": [
        {"description": "Bridge remains passable for rescue units", "impact": "Reroute if false", "confidence": 0.4}
    ],
    "missing_information": ["Confirm exact patient acuity"],
    "triage_priorities": [
        {
            "priority": 1,
            "label": "critical / life-threatening",
            "estimated_count": 1,
            "required_response": "Immediate ALS transport",
            "required_action": "Transport to trauma-capable facility",
        }
    ],
    "patient_transport": {
        "primary_facilities": ["Penn Medicine Princeton Medical Center"],
        "alternate_facilities": ["Robert Wood Johnson University Hospital"],
        "transport_routes": ["Bridge scene -> Route 206 -> hospital"],
        "constraints": ["Flooded low-lying roads"],
        "fallback_if_primary_unavailable": "Divert to alternate trauma-capable facility",
    },
}


class FakeRuntime:
    def __init__(
        self,
        *,
        parser_should_fail: bool = False,
        planner_should_fail: bool = False,
        runtime_name: str = "local",
        parser_error_kind: str = "timeout",
        parser_error_message: str = "incident_parser timed out",
    ) -> None:
        self.parser_should_fail = parser_should_fail
        self.planner_should_fail = planner_should_fail
        self._runtime_name = runtime_name
        self.parser_error_kind = parser_error_kind
        self.parser_error_message = parser_error_message
        self.action_planner_risk_data = None
        self.action_planner_decision_state = None

    def runtime_name(self) -> str:
        return self._runtime_name

    async def execute(self, run: AgentRun, fn) -> AgentRun:
        run.runtime = "local"
        run.started_at = datetime.utcnow()
        run.completed_at = run.started_at + timedelta(milliseconds=25)
        run.latency_ms = 25

        if run.agent_type == AgentType.INCIDENT_PARSER:
            if self.parser_should_fail:
                run.status = AgentStatus.FAILED
                run.error_kind = self.parser_error_kind
                run.error_message = self.parser_error_message
            else:
                run.status = AgentStatus.COMPLETED
                run.output_artifact = PARSER_OUTPUT
            return run

        if run.agent_type == AgentType.RISK_ASSESSOR:
            run.status = AgentStatus.FAILED
            run.error_kind = "timeout"
            run.error_message = "risk_assessor timed out"
            return run

        if run.agent_type == AgentType.ACTION_PLANNER:
            self.action_planner_risk_data = run.input_snapshot["risk_data"]
            self.action_planner_decision_state = run.input_snapshot["decision_state"]
            if self.planner_should_fail:
                run.status = AgentStatus.FAILED
                run.error_kind = "runtime_error"
                run.error_message = "planner failed"
            else:
                run.status = AgentStatus.COMPLETED
                run.output_artifact = PLANNER_OUTPUT
            return run

        if run.agent_type == AgentType.COMMUNICATIONS:
            run.status = AgentStatus.FAILED
            run.error_kind = "timeout"
            run.error_message = "communications timed out"
            return run

        raise AssertionError(f"Unexpected agent type: {run.agent_type}")


class GracefulDegradationTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_initial_plan_extracts_flood_demo_counts_and_blocked_route(self) -> None:
        incident = Incident(
            incident_type="Flash Flood with Injuries / Access Limited",
            report=(
                "Heavy rainfall over the past 90 minutes has caused Washington Road to flood at the "
                "Lake Carnegie bridge crossing. Water depth is estimated at 18-24 inches and rising rapidly. "
                "Four individuals are trapped in two stalled vehicles — one is an elderly female (approx 70s) "
                "who is unresponsive; a second occupant has visible head trauma from the collision. "
                "Two additional people are ambulatory but stranded on the vehicle roofs. "
                "A bystander reports the elderly patient may be in cardiac arrest. "
                "Washington Road is the primary EMS corridor to the south side of the jurisdiction — "
                "current flooding has made it impassable to standard ambulances. "
                "A second water surge is anticipated within 20 minutes as upstream retention basins approach capacity. "
                "Penn Medicine Princeton Medical Center has radioed that their trauma bay is nearly full — "
                "only 8 beds remain and they have 2 incoming critical patients from an earlier MVA. "
                "Capital Health in Trenton has capacity but is 13 miles south."
            ),
            location="Washington Road at Lake Carnegie Bridge, Princeton, NJ",
            hospital_capacities=[
                HospitalCapacity(name="Penn Medicine Princeton Medical Center", available_beds=8, total_beds=42, status="elevated", specialty="trauma", distance_mi=4.2, eta_min=12),
                HospitalCapacity(name="Capital Health Regional — Trenton", available_beds=22, total_beds=80, status="normal", specialty="trauma", distance_mi=13.5, eta_min=28),
            ],
        )
        ext_ctx = {
            "mapping": {
                "routing": {"primary_route_steps": ["Washington Road", "Route 206"], "alternate_route_steps": [], "primary_duration_min": None, "provider": "osrm"},
                "hospitals": [
                    {"name": "Penn Medicine Princeton Medical Center", "distance_mi": 4.2, "trauma_level": "II"},
                    {"name": "Capital Health Regional Medical Center", "distance_mi": 12.8, "trauma_level": "II"},
                ],
                "routing_provider": "osrm",
                "hospital_directory_source": "cms_directory_stub",
            },
            "weather": {"alerts": [], "forecast": None, "risk": {}},
            "water": {"risk": {"severity": "high", "signals": ["Water level rising rapidly"], "replan_triggers": ["Second surge expected within 20 minutes"]}},
            "fema": {"available": False, "context_notes": []},
            "coordinates": {"lat": 40.35, "lon": -74.66},
        }

        with patch("agents.orchestrator.gather_immediate_context", AsyncMock(return_value=ext_ctx)):
            plan = await generate_initial_plan(incident, 1)

        self.assertEqual(plan.patient_flow.total_incoming, 4)
        self.assertEqual(plan.patient_flow.critical, 1)
        self.assertEqual(plan.patient_flow.moderate, 1)
        self.assertEqual(plan.patient_flow.minor, 2)
        self.assertEqual(plan.route_confidence, "low")
        self.assertIn("impassable", " ".join(plan.patient_transport.constraints).lower())
        self.assertEqual(plan.patient_transport.primary_facilities[0], "Penn Medicine Princeton Medical Center")
        self.assertTrue(any("alternate corridor" in action.description.lower() for action in plan.immediate_actions))
        self.assertEqual(len(plan.patient_flow.facility_assignments), 2)
        self.assertTrue(any("Capital Health" in assignment.hospital for assignment in plan.patient_flow.facility_assignments))

    async def test_generate_initial_plan_returns_local_first_operational_surface(self) -> None:
        incident = Incident(
            incident_type="Flash Flood",
            report="Multiple vehicles stranded near Lake Carnegie Bridge.",
            location="Princeton, NJ",
        )
        ext_ctx = {
            "mapping": {
                "routing": {"primary_route_steps": ["Route 206"], "alternate_route_steps": [], "primary_duration_min": 12, "provider": "osrm"},
                "hospitals": [{"name": "Penn Medicine Princeton Medical Center", "distance_mi": 4.2, "trauma_level": "II"}],
                "routing_provider": "osrm",
                "hospital_directory_source": "cms_directory_stub",
            },
            "weather": {"alerts": [], "forecast": None, "risk": {}},
            "water": {"risk": {"severity": "none", "signals": [], "replan_triggers": []}},
            "fema": {"available": False, "context_notes": []},
            "coordinates": {"lat": 40.35, "lon": -74.66},
        }

        with patch("agents.orchestrator.gather_immediate_context", AsyncMock(return_value=ext_ctx)):
            plan = await generate_initial_plan(incident, 1)

        self.assertTrue(plan.first_response_ready)
        self.assertTrue(plan.enrichment_pending)
        self.assertEqual(len(plan.immediate_actions), 3)
        self.assertGreater(len(plan.verified_information), 0)
        self.assertEqual(plan.communications, [])

    async def test_required_parser_timeout_uses_fallback_instead_of_raising(self) -> None:
        incident = Incident(
            incident_type="Flash Flood / Mass Casualty",
            report="Two vehicles stranded, one patient unresponsive, roadway flooded and impassable.",
            location="Washington Road at Lake Carnegie Bridge, Princeton, NJ",
        )
        fake_runtime = FakeRuntime(parser_should_fail=True)

        with patch("agents.orchestrator.get_runtime", return_value=fake_runtime):
            with patch("agents.orchestrator.gather_external_context", AsyncMock(return_value={})):
                with patch("agents.orchestrator.save_agent_run", lambda run: None):
                    plan, runs = await generate_plan(incident, 1)

        self.assertEqual(plan.incident_id, incident.id)
        parser_run = next(run for run in runs if run.agent_type == AgentType.INCIDENT_PARSER)
        self.assertEqual(parser_run.status, AgentStatus.FAILED)
        self.assertTrue(parser_run.required)
        self.assertTrue(parser_run.degraded)
        self.assertTrue(parser_run.fallback_used)
        self.assertEqual(plan.operational_period, "Next 2-4 hours (initial operational period)")
        self.assertGreater(len(plan.confirmed_facts), 0)
        self.assertIsNotNone(plan.iap)
        self.assertGreater(len(plan.ics_organization), 0)

    async def test_swarm_parser_transport_failure_does_not_skip_other_agents(self) -> None:
        incident = Incident(
            incident_type="Flash Flood / Mass Casualty",
            report="Two vehicles stranded, one patient unresponsive, roadway flooded and impassable.",
            location="Washington Road at Lake Carnegie Bridge, Princeton, NJ",
            hazards=["swift water"],
        )
        fake_runtime = FakeRuntime(
            parser_should_fail=True,
            runtime_name="swarm",
            parser_error_kind="runtime_error",
            parser_error_message=(
                "incident_parser: Dedalus machine SSH command failed on dm-test "
                "(session_id=wssh-test, exit_code=1): ssh session tunnel is not ready [SSH_TUNNEL_NOT_READY]"
            ),
        )

        with patch("agents.orchestrator.get_runtime", return_value=fake_runtime):
            with patch("agents.orchestrator.gather_external_context", AsyncMock(return_value={})):
                with patch("agents.orchestrator.save_agent_run", lambda run: None):
                    plan, runs = await generate_plan(incident, 1)

        self.assertEqual(plan.incident_id, incident.id)
        self.assertEqual(len(runs), 4)
        action_run = next(run for run in runs if run.agent_type == AgentType.ACTION_PLANNER)
        comms_run = next(run for run in runs if run.agent_type == AgentType.COMMUNICATIONS)
        self.assertIsNotNone(fake_runtime.action_planner_decision_state)
        self.assertEqual(action_run.status, AgentStatus.COMPLETED)
        self.assertEqual(comms_run.status, AgentStatus.FAILED)

    async def test_optional_agent_timeouts_return_plan_with_agent_failures(self) -> None:
        incident = Incident(
            incident_type="Flash Flood",
            report="Multiple vehicles stranded near Lake Carnegie Bridge.",
            location="Princeton, NJ",
        )
        fake_runtime = FakeRuntime()
        ext_ctx = {"weather": {"risk": {"escalation_triggers": ["Flooding may worsen access"]}}}

        with patch("agents.orchestrator.get_runtime", return_value=fake_runtime):
            with patch("agents.orchestrator.gather_external_context", AsyncMock(return_value=ext_ctx)):
                with patch("agents.orchestrator.save_agent_run", lambda run: None):
                    plan, runs = await generate_plan(incident, 1)

        self.assertEqual(plan.incident_id, incident.id)
        self.assertGreater(len(plan.communications), 0)
        self.assertIsInstance(fake_runtime.action_planner_risk_data, dict)
        self.assertIn(fake_runtime.action_planner_risk_data["severity_level"], {"high", "critical"})
        self.assertIsInstance(fake_runtime.action_planner_decision_state, dict)
        self.assertEqual(fake_runtime.action_planner_decision_state["patient_flow"]["total_incoming"], 4)
        self.assertIsNotNone(plan.accountability)
        self.assertEqual(plan.accountability.status, "ok")
        self.assertIsNotNone(plan.medical_operations)

        risk_run = next(run for run in runs if run.agent_type == AgentType.RISK_ASSESSOR)
        comms_run = next(run for run in runs if run.agent_type == AgentType.COMMUNICATIONS)
        action_run = next(run for run in runs if run.agent_type == AgentType.ACTION_PLANNER)

        self.assertFalse(risk_run.required)
        self.assertTrue(risk_run.degraded)
        self.assertTrue(risk_run.fallback_used)
        self.assertEqual(risk_run.retry_count, 0)
        self.assertEqual(risk_run.error_kind, "timeout")

        self.assertFalse(comms_run.required)
        self.assertEqual(comms_run.status, AgentStatus.FAILED)
        self.assertTrue(comms_run.degraded)
        self.assertTrue(comms_run.fallback_used)

        self.assertFalse(action_run.required)
        self.assertEqual(action_run.status, AgentStatus.COMPLETED)

        failures = collect_agent_failures(runs)
        self.assertEqual({failure.agent_type for failure in failures}, {AgentType.RISK_ASSESSOR, AgentType.COMMUNICATIONS})

    async def test_planner_failure_uses_fallback_instead_of_raising(self) -> None:
        incident = Incident(
            incident_type="Flash Flood",
            report="Multiple vehicles stranded near Lake Carnegie Bridge.",
            location="Princeton, NJ",
        )
        fake_runtime = FakeRuntime(planner_should_fail=True)

        with patch("agents.orchestrator.get_runtime", return_value=fake_runtime):
            with patch("agents.orchestrator.gather_external_context", AsyncMock(return_value={})):
                with patch("agents.orchestrator.save_agent_run", lambda run: None):
                    plan, runs = await generate_plan(incident, 1)

        self.assertEqual(plan.incident_id, incident.id)
        action_run = next(run for run in runs if run.agent_type == AgentType.ACTION_PLANNER)
        comms_run = next(run for run in runs if run.agent_type == AgentType.COMMUNICATIONS)
        self.assertEqual(action_run.status, AgentStatus.FAILED)
        self.assertFalse(action_run.required)
        self.assertTrue(action_run.degraded)
        self.assertTrue(action_run.fallback_used)
        self.assertIn("incident_summary", action_run.output_artifact or {})
        self.assertEqual(comms_run.status, AgentStatus.FAILED)
        self.assertTrue(comms_run.degraded)
        self.assertTrue(comms_run.fallback_used)
        self.assertIsNotNone(comms_run.output_artifact)

        failures = collect_agent_failures(runs)
        self.assertIn(AgentType.ACTION_PLANNER, {failure.agent_type for failure in failures})
        self.assertIn(AgentType.COMMUNICATIONS, {failure.agent_type for failure in failures})


class LocalRuntimeFailureMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_metadata_is_recorded_on_failed_run(self) -> None:
        runtime = LocalAgentRuntime()
        run = AgentRun(
            incident_id="incident-1",
            plan_version=1,
            agent_type=AgentType.RISK_ASSESSOR,
            required=False,
        )

        async def fail(_: AgentRun) -> dict:
            raise LLMStructuredError(
                caller="risk_assessor",
                source="LLM/K2",
                kind="timeout",
                retry_count=0,
                detail="timed out after 120s",
            )

        with patch("runtime.local_runtime.save_agent_run", lambda run: None):
            result = await runtime.execute(run, fail)

        self.assertEqual(result.status, AgentStatus.FAILED)
        self.assertEqual(result.error_kind, "timeout")
        self.assertEqual(result.retry_count, 0)
        self.assertIsNotNone(result.latency_ms)
