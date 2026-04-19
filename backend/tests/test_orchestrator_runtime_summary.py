from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents.orchestrator import _print_swarm_truth
from models.agent import AgentRun, AgentStatus, AgentType


class OrchestratorRuntimeSummaryTests(unittest.TestCase):
    def test_failed_dedalus_run_is_not_reported_as_ok(self) -> None:
        run = AgentRun(
            incident_id="incident-1",
            plan_version=1,
            agent_type=AgentType.INCIDENT_PARSER,
            runtime="dedalus",
            status=AgentStatus.FAILED,
            required=True,
            error_message="Error code: 402 - insufficient_balance",
        )

        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_swarm_truth([run], 2466)

        output = buf.getvalue()
        self.assertIn("FAILED — 0/1 completed, 1 required failed", output)
        self.assertIn("1 DedalusRunner", output)
        self.assertNotIn("OK — all 1 agents via DedalusRunner", output)
