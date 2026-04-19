from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.deployment_status import build_readiness_report


class DeploymentStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_swarm_ready_with_optional_routing_degraded(self) -> None:
        env = {
            "RUNTIME_MODE": "swarm",
            "DEDALUS_API_KEY": "dsk-test",
            "K2_API_KEY": "ifm-test",
            "ROUTING_PROVIDER": "osrm",
            "OSRM_BASE_URL": "http://osrm:5000",
            "ALLOW_RUNTIME_FALLBACK_TO_LOCAL": "false",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "services.deployment_status.probe_db",
            return_value={"status": "ok", "path": "/data/unilert.db", "persistent": True},
        ), patch(
            "services.deployment_status.DedalusMachinesClient.list_machines",
            AsyncMock(return_value=[]),
        ), patch(
            "services.deployment_status._probe_osrm",
            AsyncMock(return_value={"status": "degraded", "base_url": "http://osrm:5000", "detail": "unreachable"}),
        ):
            report = await build_readiness_report()

        self.assertEqual(report["status"], "degraded")
        self.assertEqual(report["checks"]["runtime"]["status"], "ok")
        self.assertEqual(report["checks"]["routing"]["status"], "degraded")

    async def test_swarm_without_remote_reasoning_backend_is_degraded(self) -> None:
        env = {
            "RUNTIME_MODE": "swarm",
            "DEDALUS_API_KEY": "dsk-test",
            "ALLOW_RUNTIME_FALLBACK_TO_LOCAL": "false",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "services.deployment_status.probe_db",
            return_value={"status": "ok", "path": "/data/unilert.db", "persistent": True},
        ), patch(
            "services.deployment_status.DedalusMachinesClient.list_machines",
            AsyncMock(return_value=[]),
        ), patch(
            "services.deployment_status._probe_osrm",
            AsyncMock(return_value={"status": "ok", "base_url": "http://osrm:5000"}),
        ):
            report = await build_readiness_report()

        self.assertEqual(report["status"], "degraded")
        self.assertEqual(report["checks"]["runtime"]["status"], "degraded")
        self.assertFalse(report["checks"]["runtime"]["swarm_enrichment_ready"])

    async def test_local_mode_without_llm_key_is_not_ready(self) -> None:
        env = {
            "RUNTIME_MODE": "local",
            "K2_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "ALLOW_RUNTIME_FALLBACK_TO_LOCAL": "false",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "services.deployment_status.probe_db",
            return_value={"status": "ok", "path": "/tmp/test.db", "persistent": False},
        ), patch(
            "services.deployment_status._probe_osrm",
            AsyncMock(return_value={"status": "ok", "base_url": "http://osrm:5000"}),
        ):
            report = await build_readiness_report()

        self.assertEqual(report["status"], "not_ready")
        self.assertEqual(report["checks"]["runtime"]["status"], "broken")


if __name__ == "__main__":
    unittest.main()
