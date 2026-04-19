from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents.llm import (
    LLMResponseValidationError,
    LLMStructuredError,
    _strict_json_object,
    call_llm,
    get_llm_reliability_snapshot,
    reset_llm_reliability_tracking,
)
from agents.schemas import ReplanContextOutput


class FakeResponse:
    def __init__(self, data: dict, status_code: int = 200) -> None:
        self._data = data
        self.status_code = status_code
        self.request = httpx.Request("POST", "https://api.k2think.ai/v1/chat/completions")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "request failed",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )

    def json(self) -> dict:
        return self._data


class FakeAsyncClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.requests: list[dict] = []

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def post(self, url: str, *, headers: dict, json: dict, timeout: float) -> FakeResponse:
        self.requests.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return self.responses[len(self.requests) - 1]


class StrictJsonTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_llm_reliability_tracking()

    def test_rejects_reasoning_preamble_even_if_json_follows(self) -> None:
        with self.assertRaisesRegex(LLMResponseValidationError, "non-JSON output"):
            _strict_json_object(
                'We need to produce output first.\n{"significant_change": true}',
                caller="incident_parser",
                source="LLM/K2",
            )

    async def test_local_runtime_uses_json_schema_and_retries_without_recovery(self) -> None:
        responses = [
            FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    'We need to produce output first.\n'
                                    '{"significant_change": true, "affected_sections": ["communications"], '
                                    '"reasoning": "x", "update_context": "y"}'
                                )
                            }
                        }
                    ]
                }
            ),
            FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"significant_change": true, '
                                    '"affected_sections": ["communications"], '
                                    '"reasoning": "Flooding changes hospital messaging.", '
                                    '"update_context": "Hospitals need updated ETAs."}'
                                )
                            }
                        }
                    ]
                }
            ),
        ]
        fake_client = FakeAsyncClient(responses)

        with patch.dict("os.environ", {"RUNTIME_MODE": "local", "K2_API_KEY": "test-key"}, clear=False):
            with patch("agents.llm.httpx.AsyncClient", return_value=fake_client):
                result = await call_llm(
                    "Return the replan metadata.",
                    caller="strict_local",
                    response_model=ReplanContextOutput,
                )

        self.assertEqual(result["affected_sections"], ["communications"])
        self.assertEqual(len(fake_client.requests), 2)
        self.assertEqual(
            fake_client.requests[0]["json"]["response_format"]["type"],
            "json_schema",
        )
        self.assertTrue(
            fake_client.requests[0]["json"]["response_format"]["json_schema"]["strict"]
        )
        self.assertIn(
            "Do not include any explanation, reasoning, chain-of-thought, or preamble.",
            fake_client.requests[0]["json"]["messages"][0]["content"],
        )

        metrics = get_llm_reliability_snapshot()["strict_local"]
        self.assertEqual(metrics["retry_rate"], 1.0)
        self.assertEqual(metrics["first_pass_success_rate"], 0.0)

    async def test_local_runtime_returns_structured_error_after_retry_exhaustion(self) -> None:
        responses = [
            FakeResponse({"choices": [{"message": {"content": "reasoning before json"}}]}),
            FakeResponse({"choices": [{"message": {"content": "still not json"}}]}),
            FakeResponse({"choices": [{"message": {"content": "no json here either"}}]}),
        ]
        fake_client = FakeAsyncClient(responses)

        with patch.dict("os.environ", {"RUNTIME_MODE": "local", "K2_API_KEY": "test-key"}, clear=False):
            with patch("agents.llm.httpx.AsyncClient", return_value=fake_client):
                with self.assertRaises(LLMStructuredError) as ctx:
                    await call_llm(
                        "Return the replan metadata.",
                        caller="strict_failure",
                        response_model=ReplanContextOutput,
                    )

        self.assertEqual(ctx.exception.kind, "validation_failed")
        self.assertEqual(ctx.exception.retry_count, 2)
        self.assertEqual(len(fake_client.requests), 3)
