from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from runtime.dedalus_client_config import (
    build_dedalus_client_kwargs,
    dedalus_byok_configured,
    describe_dedalus_billing_mode,
    describe_swarm_reasoning_mode,
    k2_configured,
    machine_worker_env_lines,
    swarm_enrichment_backend_ready,
)


class DedalusClientConfigTests(unittest.TestCase):
    def test_builds_byok_kwargs_from_env(self) -> None:
        env = {
            "DEDALUS_API_KEY": "dsk-test",
            "DEDALUS_PROVIDER": "anthropic",
            "DEDALUS_PROVIDER_KEY": "sk-ant-test",
            "DEDALUS_PROVIDER_MODEL": "claude-sonnet-test",
        }
        with patch.dict("os.environ", env, clear=False):
            kwargs = build_dedalus_client_kwargs()
            self.assertEqual(kwargs["api_key"], "dsk-test")
            self.assertEqual(kwargs["provider"], "anthropic")
            self.assertEqual(kwargs["provider_key"], "sk-ant-test")
            self.assertEqual(kwargs["provider_model"], "claude-sonnet-test")
            self.assertTrue(dedalus_byok_configured())
            self.assertIn("BYOK", describe_dedalus_billing_mode())

    def test_machine_worker_env_lines_include_byok(self) -> None:
        env = {
            "DEDALUS_PROVIDER": "openai",
            "DEDALUS_PROVIDER_KEY": "sk-openai-test",
            "DEDALUS_PROVIDER_MODEL": "gpt-4o",
        }
        with patch.dict("os.environ", env, clear=False):
            blob = machine_worker_env_lines("dsk-test")
            self.assertIn("DEDALUS_API_KEY=dsk-test", blob)
            self.assertIn("DEDALUS_PROVIDER=openai", blob)
            self.assertIn("DEDALUS_PROVIDER_KEY=sk-openai-test", blob)
            self.assertIn("DEDALUS_PROVIDER_MODEL=gpt-4o", blob)

    def test_machine_worker_env_lines_default_to_k2_when_available(self) -> None:
        env = {
            "K2_API_KEY": "ifm-test",
            "K2_MODEL": "MBZUAI-IFM/K2-Think-v2",
        }
        with patch.dict("os.environ", env, clear=False):
            blob = machine_worker_env_lines("dsk-test")
            self.assertIn("DEDALUS_API_KEY=dsk-test", blob)
            self.assertIn("LLM_BACKEND=k2", blob)
            self.assertIn("K2_API_KEY=ifm-test", blob)
            self.assertIn("K2_MODEL=MBZUAI-IFM/K2-Think-v2", blob)
            self.assertTrue(k2_configured())
            self.assertTrue(swarm_enrichment_backend_ready())
            self.assertIn("K2 Think V2", describe_swarm_reasoning_mode())
