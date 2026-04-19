from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import runtime
from runtime.local_runtime import LocalAgentRuntime


class RuntimeSelectionTests(unittest.TestCase):
    def test_explicit_swarm_does_not_silently_fallback_without_opt_in(self) -> None:
        env = {
            "RUNTIME_MODE": "swarm",
            "ALLOW_RUNTIME_FALLBACK_TO_LOCAL": "false",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "runtime.DedalusMachineSwarmRuntime",
            side_effect=RuntimeError("machines unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                runtime.get_runtime()

    def test_explicit_swarm_can_opt_in_to_local_fallback(self) -> None:
        env = {
            "RUNTIME_MODE": "swarm",
            "ALLOW_RUNTIME_FALLBACK_TO_LOCAL": "true",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "runtime.DedalusMachineSwarmRuntime",
            side_effect=RuntimeError("machines unavailable"),
        ):
            selected = runtime.get_runtime()

        self.assertIsInstance(selected, LocalAgentRuntime)


if __name__ == "__main__":
    unittest.main()
