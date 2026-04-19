from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents.orchestrator import collect_agent_failures, generate_plan
from agents.llm import LLMStructuredError
from models.agent import AgentRun, AgentStatus, AgentType
from models.incident import Incident
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
    def __init__(self, *, parser_should_fail: bool = False, planner_should_fail: bool = False) -> None:
        self.parser_should_fail = parser_should_fail
        self.planner_should_fail = planner_should_fail
        self.action_planner_risk_data = None

    def runtime_name(self) -> str:
        return "local"

    async def execute(self, run: AgentRun, fn) -> AgentRun:
        run.runtime = "local"
        run.started_at = datetime.utcnow()
        run.completed_at = run.started_at + timedelta(milliseconds=25)
        run.latency_ms = 25

        if run.agent_type == AgentType.INCIDENT_PARSER:
            if self.parser_should_fail:
                run.status = AgentStatus.FAILED
                run.error_kind = "timeout"
                run.error_message = "incident_parser timed out"
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
        self.assertIsInstance(fake_runtime.action_planner_risk_data, str)
        self.assertIn("Risk assessment unavailable due to pending threat analysis", fake_runtime.action_planner_risk_data)

        risk_run = next(run for run in runs if run.agent_type == AgentType.RISK_ASSESSOR)
        comms_run = next(run for run in runs if run.agent_type == AgentType.COMMUNICATIONS)
        action_run = next(run for run in runs if run.agent_type == AgentType.ACTION_PLANNER)

        self.assertFalse(risk_run.required)
        self.assertTrue(risk_run.degraded)
        self.assertTrue(risk_run.fallback_used)
        self.assertEqual(risk_run.retry_count, 1)
        self.assertEqual(risk_run.error_kind, "timeout")

        self.assertFalse(comms_run.required)
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
        self.assertEqual(comms_run.status, AgentStatus.COMPLETED)
        self.assertTrue(comms_run.fallback_used)

        failures = collect_agent_failures(runs)
        self.assertIn(AgentType.ACTION_PLANNER, {failure.agent_type for failure in failures})


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
