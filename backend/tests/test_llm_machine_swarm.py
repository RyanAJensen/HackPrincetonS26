from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents.llm import call_llm
from agents.machine_context import dedalus_machine_executor_ctx, dedalus_machine_id_ctx
from agents.schemas import ReplanContextOutput


class FakeMachineExecutor:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    async def run_prompt_on_machine(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return json.dumps(self.payload)


class MachineSwarmLlmTests(unittest.IsolatedAsyncioTestCase):
    async def test_call_llm_prefers_machine_context(self) -> None:
        payload = ReplanContextOutput(
            significant_change=True,
            affected_sections=["operations"],
            reasoning="Road closures change the access plan.",
            update_context="Bridge approach flooded.",
        ).model_dump()
        executor = FakeMachineExecutor(payload)
        exec_token = dedalus_machine_executor_ctx.set(executor)
        machine_token = dedalus_machine_id_ctx.set("dm-test-machine")

        try:
            result = await call_llm(
                "Test prompt",
                caller="machine_replan",
                response_model=ReplanContextOutput,
            )
        finally:
            dedalus_machine_id_ctx.reset(machine_token)
            dedalus_machine_executor_ctx.reset(exec_token)

        self.assertEqual(result["affected_sections"], ["operations"])
        self.assertEqual(executor.calls[0]["machine_id"], "dm-test-machine")
        self.assertIs(executor.calls[0]["response_model"], ReplanContextOutput)
