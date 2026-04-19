from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.decision_engine import build_decision_state, validate_decision_state


class DecisionEngineTests(unittest.TestCase):
    def test_build_decision_state_handles_impassable_primary_corridor_and_preserves_reported_patient_count(self) -> None:
        parsed = {
            "incoming_patient_count": 4,
            "critical": 1,
            "moderate": 1,
            "minor": 2,
            "key_hazards": ["flooding", "secondary water surge", "vehicle entrapment"],
            "immediate_life_safety_threat": True,
            "transport_status": "Primary corridor impassable to standard ambulances",
            "infrastructure_impact": "Primary corridor impassable to standard ambulances",
            "location_notes": "Washington Road flooding has made the primary corridor impassable to standard ambulances",
            "unknowns": ["Confirm exact vehicle occupancy"],
        }
        ext_ctx = {
            "mapping": {
                "routing": {
                    "primary_route_steps": ["Washington Rd", "Route 206", "Hospital Access"],
                    "primary_duration_min": None,
                    "alternate_route_steps": [],
                },
                "hospitals": [
                    {"name": "Penn Medicine Princeton Medical Center", "distance_mi": 4.2, "trauma_level": "II"},
                    {"name": "Capital Health Regional Medical Center", "distance_mi": 12.8, "trauma_level": "II"},
                ],
            },
            "weather": {"risk": {"weather_threats": [], "escalation_triggers": []}},
            "water": {"risk": {"severity": "high", "signals": ["Water level rising rapidly"], "replan_triggers": ["Second surge expected within 20 minutes"]}},
        }
        hospital_capacities = [
            {"name": "Penn Medicine Princeton Medical Center", "status": "elevated", "available_beds": 8, "total_beds": 42, "specialty": "trauma", "distance_mi": 4.2},
            {"name": "Capital Health Regional — Trenton", "status": "normal", "available_beds": 22, "total_beds": 80, "specialty": "trauma", "distance_mi": 13.5},
            {"name": "Robert Wood Johnson University Hospital", "status": "critical", "available_beds": 5, "total_beds": 35, "specialty": "trauma", "distance_mi": 9.1},
        ]
        resources = [
            {"name": "EMS Unit 12", "role": "EMS", "available": True},
            {"name": "EMS Unit 8 — Advanced Life Support", "role": "EMS / ALS", "available": True},
            {"name": "Engine Co. 7", "role": "Fire Rescue", "available": True},
        ]

        decision_state = build_decision_state(
            incident_type="Flash Flood with Injuries / Access Limited",
            location="Washington Road at Lake Carnegie Bridge, Princeton, NJ",
            parsed=parsed,
            ext_ctx=ext_ctx,
            resources=resources,
            hospital_capacities=hospital_capacities,
        )

        validate_decision_state(decision_state)

        self.assertEqual(decision_state["patient_flow"]["total_incoming"], 4)
        self.assertEqual(decision_state["patient_flow"]["minor"], 2)
        self.assertTrue(decision_state["route_evaluation"]["primary_blocked"])
        self.assertIn("impassable", " ".join(decision_state["route_evaluation"]["constraints"]).lower())
        self.assertIn("alternate transport corridor", " ".join(decision_state["operational_priorities"]).lower())

        assignments = decision_state["patient_flow"]["facility_assignments"]
        self.assertEqual(sum(item["patients_assigned"] for item in assignments), 4)
        self.assertEqual(len(assignments), 2)
        self.assertIn("Penn Medicine Princeton Medical Center", {item["hospital"] for item in assignments})
        self.assertTrue(any("Capital Health" in item["hospital"] for item in assignments))
        self.assertEqual(decision_state["patient_transport"]["primary_facilities"][0], "Penn Medicine Princeton Medical Center")
        self.assertIn("alternate", decision_state["medical_operations"]["transport"]["actions"][0]["description"].lower())

    def test_build_decision_state_allocates_all_patients_and_prefers_viable_capacity(self) -> None:
        parsed = {
            "incoming_patient_count": 4,
            "critical": 1,
            "moderate": 2,
            "minor": 1,
            "key_hazards": ["swift water", "vehicle entrapment"],
            "immediate_life_safety_threat": True,
            "unknowns": ["Exact vehicle occupancy pending"],
        }
        ext_ctx = {
            "mapping": {
                "routing": {
                    "primary_route_steps": ["Washington Rd", "Route 206", "Hospital Access"],
                    "primary_duration_min": 18,
                },
                "hospitals": [
                    {"name": "Penn Medicine Princeton Medical Center", "distance_mi": 4.2, "trauma_level": "II"},
                    {"name": "Regional Trauma Center", "distance_mi": 8.1, "trauma_level": "I"},
                ],
            },
            "weather": {
                "risk": {
                    "weather_threats": ["Rain reduces throughput"],
                    "escalation_triggers": ["Flooding may worsen access"],
                }
            },
        }
        hospital_capacities = [
            {"name": "Penn Medicine Princeton Medical Center", "status": "critical", "available_beds": 1, "total_beds": 10},
            {"name": "Regional Trauma Center", "status": "normal", "available_beds": 6, "total_beds": 20},
        ]
        resources = [
            {"name": "EMS Unit 12", "role": "EMS", "available": True},
            {"name": "Engine Co. 7", "role": "Fire Rescue", "available": True},
        ]

        decision_state = build_decision_state(
            incident_type="Flash Flood",
            location="Princeton, NJ",
            parsed=parsed,
            ext_ctx=ext_ctx,
            resources=resources,
            hospital_capacities=hospital_capacities,
        )

        validate_decision_state(decision_state)

        assignments = decision_state["patient_flow"]["facility_assignments"]
        self.assertEqual(decision_state["patient_flow"]["total_incoming"], 4)
        self.assertEqual(sum(item["patients_assigned"] for item in assignments), 4)
        self.assertEqual(assignments[0]["hospital"], "Regional Trauma Center")
        self.assertIn("Flooding may worsen access", decision_state["risk"]["replan_triggers"])
        self.assertEqual(decision_state["patient_transport"]["primary_facilities"][0], "Regional Trauma Center")
        self.assertEqual(decision_state["command_recommendations"]["command_mode"], "command")
        self.assertTrue(decision_state["command_recommendations"]["safety_officer_recommended"])
        self.assertTrue(decision_state["transport_group_active"])
        self.assertIn("command", decision_state["owned_actions"])
        self.assertGreater(len(decision_state["owned_action_items"]), 0)
        self.assertEqual(decision_state["accountability"]["status"], "ok")
        self.assertEqual(decision_state["medical_operations"]["triage"]["owner_role"], "Triage Unit Leader")
        self.assertEqual(decision_state["medical_operations"]["treatment"]["owner_role"], "Treatment Unit Leader")
        self.assertEqual(decision_state["medical_operations"]["transport"]["owner_role"], "Transport Officer")
        self.assertGreater(len(decision_state["ics_organization"]), 0)
        self.assertEqual(decision_state["iap"]["organization"][0]["role"], "Incident Commander")
        self.assertGreater(decision_state["risk"]["risk_score"], 0)
        self.assertEqual(decision_state["command_transfer_summary"]["command_mode"], "command")

    def test_build_decision_state_generates_span_of_control_warnings_for_complex_incident(self) -> None:
        parsed = {
            "incoming_patient_count": 9,
            "critical": 2,
            "moderate": 4,
            "minor": 3,
            "key_hazards": ["flooding", "blocked roadway", "vehicle entrapment"],
            "immediate_life_safety_threat": True,
            "unknowns": ["Secondary access condition pending"],
        }
        ext_ctx = {
            "mapping": {
                "routing": {
                    "primary_route_steps": ["Route 1", "Washington Rd", "Hospital Access"],
                    "primary_duration_min": 22,
                },
                "hospitals": [
                    {"name": "Penn Medicine Princeton Medical Center", "distance_mi": 4.2, "trauma_level": "II"},
                    {"name": "Regional Trauma Center", "distance_mi": 8.1, "trauma_level": "I"},
                    {"name": "Capital Health Regional", "distance_mi": 12.4, "trauma_level": "II"},
                ],
            }
        }
        resources = [
            {"name": "Battalion 1", "role": "Command", "available": True, "deployment_status": "assigned"},
            {"name": "EMS Unit 12", "role": "EMS", "available": True, "deployment_status": "assigned"},
            {"name": "EMS Unit 15", "role": "EMS", "available": True, "deployment_status": "assigned"},
            {"name": "Engine Co. 7", "role": "Fire Rescue", "available": True, "deployment_status": "assigned"},
            {"name": "County Sheriff", "role": "Law", "available": True, "deployment_status": "assigned"},
            {"name": "Public Information Officer", "role": "PIO", "available": True, "deployment_status": "assigned"},
            {"name": "Emergency Operations Center", "role": "Planning", "available": True, "deployment_status": "staged"},
        ]

        decision_state = build_decision_state(
            incident_type="Flash Flood / MCI",
            location="Princeton, NJ",
            parsed=parsed,
            ext_ctx=ext_ctx,
            resources=resources,
            hospital_capacities=[],
        )

        validate_decision_state(decision_state)
        self.assertGreater(len(decision_state["span_of_control"]), 0)
        self.assertTrue(any(item["supervisor_role"] == "Incident Commander" for item in decision_state["span_of_control"]))
        self.assertEqual(decision_state["accountability"]["unowned_actions"], [])


if __name__ == "__main__":
    unittest.main()
