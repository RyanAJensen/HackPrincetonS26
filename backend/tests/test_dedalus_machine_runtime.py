from __future__ import annotations

import os
import sys
import tarfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from runtime.dedalus_dcs import DCSExecutionOutput
from runtime.dedalus_machine_runtime import DedalusMachineSwarmRuntime


class DedalusMachineRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def _make_runtime(self) -> DedalusMachineSwarmRuntime:
        fake_client = type("FakeDedalusClient", (), {"command_transport": "ssh"})()
        with patch.dict(os.environ, {"DEDALUS_API_KEY": "dsk-test"}, clear=False), patch(
            "runtime.dedalus_machine_runtime.DedalusMachinesClient",
            return_value=fake_client,
        ):
            return DedalusMachineSwarmRuntime()

    def test_build_wheelhouse_archive_contains_worker_wheels(self) -> None:
        runtime = self._make_runtime()

        archive_path = runtime._build_wheelhouse_archive()

        self.assertTrue(archive_path.exists())
        with tarfile.open(archive_path, "r:gz") as tar:
            names = tar.getnames()
        self.assertIn("dedalus_labs-0.3.0-py3-none-any.whl", names)
        self.assertIn("pydantic-2.13.2-py3-none-any.whl", names)

    async def test_invoke_worker_exports_vendor_pythonpath(self) -> None:
        runtime = self._make_runtime()
        run_command = AsyncMock(
            return_value=DCSExecutionOutput(execution_id="wssh-test", stdout='{"ok":true}', stderr="")
        )
        upload_file_via_ssh = AsyncMock(return_value=None)
        runtime.client = type(
            "FakeClient",
            (),
            {"run_command": run_command, "upload_file_via_ssh": upload_file_via_ssh},
        )()

        await runtime._invoke_worker("dm-test", {"operation": "healthcheck"}, timeout_s=10)

        script = run_command.await_args.args[1][2]
        self.assertIn('export PYTHONPATH="$ROOT/vendor/site${PYTHONPATH:+:$PYTHONPATH}"', script)
        self.assertIn("--payload-path", script)
        upload_args = upload_file_via_ssh.await_args.args
        self.assertEqual(upload_args[0], "dm-test")
        self.assertTrue(str(upload_args[2]).startswith("/dev/shm/"))

    async def test_run_prompt_on_machine_retries_transient_ssh_failures(self) -> None:
        runtime = self._make_runtime()
        runtime._bootstrap_machine = AsyncMock(return_value=None)
        runtime.wait_for_machine_command_ready = AsyncMock(return_value=None)
        runtime._invoke_worker = AsyncMock(
            side_effect=[
                RuntimeError("guest ssh session terminated unexpectedly [SSH_GUEST_SESSION_TERMINATED]"),
                DCSExecutionOutput(execution_id="wssh-test", stdout='{"ok":true}', stderr=""),
            ]
        )

        result = await runtime.run_prompt_on_machine(
            machine_id="dm-test",
            prompt="prompt",
            system="system",
            caller="incident_parser",
            response_model=None,
            timeout_seconds=20,
        )

        self.assertEqual(result, '{"ok":true}')
        self.assertEqual(runtime._invoke_worker.await_count, 2)
        runtime.wait_for_machine_command_ready.assert_awaited_once_with("dm-test")


if __name__ == "__main__":
    unittest.main()
