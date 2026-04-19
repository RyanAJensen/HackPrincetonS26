from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from runtime.dedalus_machine_worker import _run


class DedalusMachineWorkerTests(unittest.TestCase):
    def test_healthcheck_mode_does_not_require_model_execution(self) -> None:
        with patch.dict(
            os.environ,
            {"DEDALUS_API_KEY": "dsk-test", "K2_API_KEY": "ifm-test", "LLM_BACKEND": "k2"},
            clear=False,
        ):
            result = asyncio.run(_run({"operation": "healthcheck"}))

        self.assertTrue(result["ok"])
        self.assertIn("IncidentParserOutput", result["response_models"])
        self.assertIn("LeanPlannerOutput", result["response_models"])
        self.assertTrue(result["dedalus_api_key_present"])
        self.assertTrue(result["k2_api_key_present"])
        self.assertEqual(result["llm_backend"], "k2")

    def test_k2_execution_returns_validated_payload(self) -> None:
        fake_response = type(
            "Resp",
            (),
            {
                "raise_for_status": lambda self: None,
                "json": lambda self: {
                    "choices": [
                        {
                            "message": {
                                "content": '{"significant_change":true,"affected_sections":["routing"],'
                                '"reasoning":"Water rose above the bridge deck.","update_context":"Bridge closed."}'
                            }
                        }
                    ]
                },
            },
        )()

        fake_client = type(
            "FakeAsyncClient",
            (),
            {
                "__init__": lambda self, *args, **kwargs: None,
                "__aenter__": AsyncMock(return_value=None),
                "__aexit__": AsyncMock(return_value=None),
                "post": AsyncMock(return_value=fake_response),
            },
        )()

        class _AsyncClientFactory:
            def __init__(self, *args, **kwargs) -> None:
                self._client = fake_client

            async def __aenter__(self):
                return self._client

            async def __aexit__(self, exc_type, exc, tb):
                return False

        payload = {
            "operation": "run_llm",
            "backend": "k2",
            "prompt": "prompt",
            "system": "system",
            "response_model": "ReplanContextOutput",
            "model": "MBZUAI-IFM/K2-Think-v2",
        }
        with patch.dict(
            os.environ,
            {"DEDALUS_API_KEY": "dsk-test", "K2_API_KEY": "ifm-test", "LLM_BACKEND": "k2"},
            clear=False,
        ), patch("runtime.dedalus_machine_worker.httpx.AsyncClient", _AsyncClientFactory):
            result = asyncio.run(_run(payload))

        self.assertTrue(result["significant_change"])
        self.assertEqual(result["affected_sections"], ["routing"])

    def test_k2_execution_supports_lean_response_models(self) -> None:
        fake_response = type(
            "Resp",
            (),
            {
                "raise_for_status": lambda self: None,
                "json": lambda self: {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"summary":"Bridge response plan","total_patients":4,"critical":1,'
                                    '"moderate":2,"minor":1,"facility_assignments":[{"hospital":"PMC",'
                                    '"patients":2,"strain":"elevated","reason":"closest trauma access"}],'
                                    '"distribution_note":"Send critical first.","immediate_actions":["Assign triage"],'
                                    '"short_term_actions":["Open treatment area"],"priorities":["Life safety"],'
                                    '"key_decision":"Use west approach","replan_if":"Bridge closes",'
                                    '"missing_info":["Confirm second ambulance"],'
                                    '"triage_critical_action":"Load critical patient first",'
                                    '"triage_moderate_action":"Stage moderate patients",'
                                    '"triage_minor_action":"Hold minor patients",'
                                    '"primary_route":"Route A","alternate_route":"Route B"}'
                                )
                            }
                        }
                    ]
                },
            },
        )()

        fake_client = type(
            "FakeAsyncClient",
            (),
            {
                "__init__": lambda self, *args, **kwargs: None,
                "__aenter__": AsyncMock(return_value=None),
                "__aexit__": AsyncMock(return_value=None),
                "post": AsyncMock(return_value=fake_response),
            },
        )()

        class _AsyncClientFactory:
            def __init__(self, *args, **kwargs) -> None:
                self._client = fake_client

            async def __aenter__(self):
                return self._client

            async def __aexit__(self, exc_type, exc, tb):
                return False

        payload = {
            "operation": "run_llm",
            "backend": "k2",
            "prompt": "prompt",
            "system": "system",
            "response_model": "LeanPlannerOutput",
            "model": "MBZUAI-IFM/K2-Think-v2",
        }
        with patch.dict(
            os.environ,
            {"DEDALUS_API_KEY": "dsk-test", "K2_API_KEY": "ifm-test", "LLM_BACKEND": "k2"},
            clear=False,
        ), patch("runtime.dedalus_machine_worker.httpx.AsyncClient", _AsyncClientFactory):
            result = asyncio.run(_run(payload))

        self.assertEqual(result["summary"], "Bridge response plan")
        self.assertEqual(result["facility_assignments"][0]["hospital"], "PMC")


if __name__ == "__main__":
    unittest.main()
