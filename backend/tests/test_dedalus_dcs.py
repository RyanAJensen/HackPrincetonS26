from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from runtime.dedalus_dcs import DCSExecutionOutput, DedalusMachinesClient


class _FakeSession:
    def __init__(self, session_id: str = "wssh-test") -> None:
        self.session_id = session_id
        self.connection = type(
            "Conn",
            (),
            {
                "port": 22,
                "ssh_username": session_id,
                "endpoint": "ssh.dedaluslabs.ai",
            },
        )()


class _FakeProc:
    def __init__(self, *, returncode: int = 0, communicate_result: tuple[bytes, bytes] = (b"", b"")) -> None:
        self.returncode = returncode
        self.communicate = AsyncMock(return_value=communicate_result)
        self.kill = Mock(return_value=None)


class DedalusMachinesClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_execution_normalizes_string_command_to_argv(self) -> None:
        with patch.dict(os.environ, {"DEDALUS_API_KEY": "dsk-test"}, clear=False):
            client = DedalusMachinesClient("dsk-test")

        request_mock = AsyncMock(
            return_value={
                "execution_id": "wexec-test",
                "machine_id": "dm-test",
                "status": "queued",
                "command": ["bash", "-lc", "echo ready"],
                "created_at": "2026-04-19T00:00:00Z",
            }
        )

        with patch.object(client, "_request", request_mock):
            execution = await client.create_execution("dm-test", "echo ready")

        self.assertEqual(execution.command, ["bash", "-lc", "echo ready"])
        self.assertEqual(
            request_mock.await_args.kwargs["json_body"]["command"],
            ["bash", "-lc", "echo ready"],
        )

    async def test_run_command_defaults_to_ssh_transport(self) -> None:
        with patch.dict(os.environ, {"DEDALUS_API_KEY": "dsk-test"}, clear=False):
            client = DedalusMachinesClient("dsk-test")

        ssh_mock = AsyncMock(
            return_value=DCSExecutionOutput(execution_id="wssh-test", stdout="/home/machine\n", stderr="")
        )
        execution_mock = AsyncMock()

        with patch.object(client, "_run_command_via_ssh", ssh_mock), patch.object(
            client,
            "_run_command_via_execution",
            execution_mock,
        ):
            result = await client.run_command("dm-test", ["pwd"], timeout_s=10)

        self.assertEqual(result.stdout, "/home/machine\n")
        ssh_mock.assert_awaited_once()
        execution_mock.assert_not_called()

    def test_known_hosts_line_uses_cert_authority_prefix(self) -> None:
        with patch.dict(os.environ, {"DEDALUS_API_KEY": "dsk-test"}, clear=False):
            client = DedalusMachinesClient("dsk-test")

        host_trust = type(
            "HostTrust",
            (),
            {
                "kind": "cert_authority",
                "host_pattern": "ssh.dedaluslabs.ai",
                "public_key": "ssh-ed25519 AAAATEST",
            },
        )()

        line = client._known_hosts_line(host_trust)
        self.assertEqual(line, "@cert-authority ssh.dedaluslabs.ai ssh-ed25519 AAAATEST\n")

    def test_retryable_ssh_failure_detection(self) -> None:
        with patch.dict(os.environ, {"DEDALUS_API_KEY": "dsk-test"}, clear=False):
            client = DedalusMachinesClient("dsk-test")

        self.assertTrue(client._is_retryable_ssh_failure("guest ssh rejected the gateway certificate [SSH_GUEST_AUTH_FAILED]"))
        self.assertTrue(client._is_retryable_ssh_failure("failed to connect to guest ssh [SSH_GUEST_CONNECT_FAILED]"))
        self.assertTrue(client._is_retryable_ssh_failure("ssh session tunnel is not ready [SSH_TUNNEL_NOT_READY]"))
        self.assertFalse(client._is_retryable_ssh_failure("permission denied"))

    async def test_run_command_via_ssh_retries_after_timeout(self) -> None:
        with patch.dict(os.environ, {"DEDALUS_API_KEY": "dsk-test"}, clear=False):
            client = DedalusMachinesClient("dsk-test")

        prepare_mock = AsyncMock(
            side_effect=[
                (_FakeSession("wssh-timeout"), Path("/tmp/cert1"), Path("/tmp/known1")),
                (_FakeSession("wssh-ok"), Path("/tmp/cert2"), Path("/tmp/known2")),
            ]
        )
        first_proc = _FakeProc()
        second_proc = _FakeProc(communicate_result=(b"ready\n", b""))
        subprocess_mock = AsyncMock(side_effect=[first_proc, second_proc])

        attempts = 0

        async def _fake_wait_for(fut, timeout=None):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                fut.close()
                raise asyncio.TimeoutError()
            return await fut

        with patch.object(client, "_prepare_ssh_transport", prepare_mock), patch(
            "runtime.dedalus_dcs.asyncio.create_subprocess_exec",
            subprocess_mock,
        ), patch(
            "runtime.dedalus_dcs.asyncio.wait_for",
            _fake_wait_for,
        ):
            result = await client._run_command_via_ssh("dm-test", ["pwd"], timeout_s=10)

        self.assertEqual(result.stdout, "ready\n")
        self.assertEqual(subprocess_mock.await_count, 2)
        first_proc.kill.assert_called_once()


if __name__ == "__main__":
    unittest.main()
