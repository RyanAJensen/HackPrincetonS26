from __future__ import annotations

import sys
import types
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents.dedalus_context import dedalus_runner_ctx
from agents.llm import LLMStructuredError, call_llm
from agents.schemas import ReplanContextOutput


class FakeDedalusRunner:
    def __init__(self, final_output):
        self.final_output = final_output
        self.calls: list[dict] = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        return types.SimpleNamespace(final_output=self.final_output, steps_used=1)


class DedalusAsyncPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_call_llm_requires_dedalus_when_runtime_mode_is_dedalus(self) -> None:
        with patch.dict("os.environ", {"RUNTIME_MODE": "dedalus"}, clear=False):
            token = dedalus_runner_ctx.set(None)
            try:
                with self.assertRaisesRegex(RuntimeError, "DedalusRunner"):
                    await call_llm(
                        "Test prompt",
                        caller="test_missing_dedalus_runner",
                        response_model=ReplanContextOutput,
                    )
            finally:
                dedalus_runner_ctx.reset(token)

    async def test_call_llm_awaits_runner_and_validates_structured_output(self) -> None:
        final_output = ReplanContextOutput(
            significant_change=True,
            affected_sections=["communications"],
            reasoning="Flooding update changes evacuation messaging.",
            update_context="Road closures confirmed by field report.",
        )
        runner = FakeDedalusRunner(final_output)
        token = dedalus_runner_ctx.set(runner)

        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", RuntimeWarning)
                result = await call_llm(
                    "Test prompt",
                    caller="test_replan",
                    response_model=ReplanContextOutput,
                )
            self.assertEqual(result["reasoning"], final_output.reasoning)
            self.assertIs(runner.calls[0]["response_format"], ReplanContextOutput)
            self.assertFalse(
                any("was never awaited" in str(w.message) for w in caught),
                "call_llm leaked an unawaited coroutine warning",
            )
        finally:
            dedalus_runner_ctx.reset(token)

    async def test_call_llm_rejects_coroutine_final_output(self) -> None:
        async def delayed_output():
            return {"bad": True}

        leaked = delayed_output()
        runner = FakeDedalusRunner(leaked)
        token = dedalus_runner_ctx.set(runner)

        try:
            with self.assertRaises(LLMStructuredError) as ctx:
                await call_llm(
                    "Test prompt",
                    caller="test_replan_coroutine",
                    response_model=ReplanContextOutput,
                )
            self.assertEqual(ctx.exception.kind, "runtime_error")
            self.assertIn("result.final_output", str(ctx.exception))
        finally:
            dedalus_runner_ctx.reset(token)
            leaked.close()
