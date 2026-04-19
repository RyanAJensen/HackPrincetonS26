"""Small async client for Dedalus Cloud Services (Machines API)."""
from __future__ import annotations

import asyncio
import os
import shlex
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

import anyio
import httpx
from pydantic import BaseModel, Field, ConfigDict


DEFAULT_DCS_BASE_URL = "https://dcs.dedaluslabs.ai/v1"


class DCSMachineStatus(BaseModel):
    model_config = ConfigDict(extra="allow")
    phase: str
    reason: Optional[str] = None
    retryable: Optional[bool] = None
    revision: Optional[str] = None
    last_transition_at: Optional[str] = None
    last_progress_at: Optional[str] = None


class DCSMachine(BaseModel):
    model_config = ConfigDict(extra="allow")
    machine_id: str
    vcpu: float
    memory_mib: int
    storage_gib: int
    desired_state: Optional[str] = None
    status: Optional[DCSMachineStatus] = None
    created_at: Optional[str] = None


class DCSMachineList(BaseModel):
    items: list[DCSMachine] = Field(default_factory=list)


class DCSExecution(BaseModel):
    model_config = ConfigDict(extra="allow")
    execution_id: str
    machine_id: str
    status: str
    command: Optional[Union[list[str], str]] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    exit_code: Optional[int] = None
    stdout_bytes: Optional[int] = None
    stderr_bytes: Optional[int] = None


class DCSExecutionOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    execution_id: str
    stdout: str = ""
    stdout_bytes: Optional[int] = None
    stderr: Optional[str] = None
    stderr_bytes: Optional[int] = None


class DCSExecutionEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    sequence: Optional[int] = None
    type: str
    at: Optional[str] = None
    status: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class DCSExecutionEventList(BaseModel):
    items: list[DCSExecutionEvent] = Field(default_factory=list)


class DCSHostTrust(BaseModel):
    model_config = ConfigDict(extra="allow")
    kind: str
    host_pattern: str
    public_key: str


class DCSSSHConnection(BaseModel):
    model_config = ConfigDict(extra="allow")
    endpoint: str
    port: int
    ssh_username: str
    user_certificate: str
    host_trust: DCSHostTrust


class DCSSSHSession(BaseModel):
    model_config = ConfigDict(extra="allow")
    session_id: str
    machine_id: str
    status: str
    created_at: Optional[str] = None
    ready_at: Optional[str] = None
    expires_at: Optional[str] = None
    retry_after_ms: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    connection: Optional[DCSSSHConnection] = None


class DedalusMachinesClient:
    """Minimal Machines API client built from the documented DCS flow."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("DEDALUS_API_KEY")
        if not self.api_key:
            raise RuntimeError("DEDALUS_API_KEY is required for Dedalus Machines API access")
        self.base_url = (base_url or os.getenv("DEDALUS_DCS_BASE_URL") or DEFAULT_DCS_BASE_URL).rstrip("/")
        self.timeout = timeout or float(os.getenv("DEDALUS_DCS_TIMEOUT_SECONDS", "30"))
        self.org_id = (os.getenv("DEDALUS_ORG_ID") or "").strip() or None
        self.debug = os.getenv("DEDALUS_DCS_DEBUG", "").lower() in ("1", "true", "yes")
        self.command_transport = (os.getenv("DEDALUS_MACHINE_COMMAND_TRANSPORT") or "ssh").strip().lower()
        if self.command_transport not in {"ssh", "execution", "auto"}:
            raise RuntimeError(
                "DEDALUS_MACHINE_COMMAND_TRANSPORT must be one of: ssh, execution, auto"
            )
        self.ssh_connect_timeout_s = float(os.getenv("DEDALUS_SSH_CONNECT_TIMEOUT_SECONDS", "30"))
        ssh_dir = os.getenv("DEDALUS_SSH_MATERIAL_DIR")
        self._ssh_material_dir = Path(ssh_dir) if ssh_dir else Path(tempfile.mkdtemp(prefix="dedalus-ssh-"))
        self._ssh_material_dir.mkdir(parents=True, exist_ok=True)
        self._ssh_private_key = self._ssh_material_dir / "id_ed25519"
        self._ssh_public_key = self._ssh_material_dir / "id_ed25519.pub"
        self._ssh_key_lock = asyncio.Lock()

    def _headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {"x-api-key": self.api_key}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if self.org_id:
            headers["X-Dedalus-Org-Id"] = self.org_id
        return headers

    def _debug(self, event: str, **fields: object) -> None:
        if not self.debug:
            return
        parts = [f"[DCS {datetime.now(timezone.utc).isoformat()}] {event}"]
        for key, value in fields.items():
            if value is None:
                continue
            parts.append(f"{key}={value}")
        print(" ".join(parts))

    @staticmethod
    def _is_retryable_ssh_failure(detail: str) -> bool:
        return any(
            token in detail
            for token in (
                "SSH_GUEST_AUTH_FAILED",
                "SSH_GUEST_CONNECT_FAILED",
                "SSH_GUEST_SESSION_TERMINATED",
                "SSH_TUNNEL_NOT_READY",
            )
        )

    def _summarize_machine_data(self, data: Any) -> dict[str, object]:
        if not isinstance(data, dict):
            return {"raw_type": type(data).__name__}
        status = data.get("status") or {}
        return {
            "machine_id": data.get("machine_id"),
            "phase": status.get("phase"),
            "reason": status.get("reason"),
            "retryable": status.get("retryable"),
            "revision": status.get("revision"),
            "last_transition_at": status.get("last_transition_at"),
            "last_progress_at": status.get("last_progress_at"),
            "vcpu": data.get("vcpu"),
            "memory_mib": data.get("memory_mib"),
            "storage_gib": data.get("storage_gib"),
        }

    def _summarize_execution_data(self, data: Any) -> dict[str, object]:
        if not isinstance(data, dict):
            return {"raw_type": type(data).__name__}
        return {
            "execution_id": data.get("execution_id"),
            "machine_id": data.get("machine_id"),
            "status": data.get("status"),
            "created_at": data.get("created_at"),
            "started_at": data.get("started_at"),
            "completed_at": data.get("completed_at"),
            "exit_code": data.get("exit_code"),
            "queue_position": data.get("queue_position"),
            "retry_after_ms": data.get("retry_after_ms"),
            "reason": data.get("reason") or data.get("status_reason"),
            "error_code": data.get("error_code"),
            "error_message": data.get("error_message"),
        }

    def _summarize_ssh_session_data(self, data: Any) -> dict[str, object]:
        if not isinstance(data, dict):
            return {"raw_type": type(data).__name__}
        connection = data.get("connection") or {}
        host_trust = connection.get("host_trust") or {}
        return {
            "session_id": data.get("session_id"),
            "machine_id": data.get("machine_id"),
            "status": data.get("status"),
            "ready_at": data.get("ready_at"),
            "expires_at": data.get("expires_at"),
            "retry_after_ms": data.get("retry_after_ms"),
            "error_code": data.get("error_code"),
            "error_message": data.get("error_message"),
            "endpoint": connection.get("endpoint"),
            "port": connection.get("port"),
            "ssh_username": connection.get("ssh_username"),
            "host_trust_kind": host_trust.get("kind"),
            "host_pattern": host_trust.get("host_pattern"),
        }

    def _normalize_command(self, command: list[str] | str) -> list[str]:
        if isinstance(command, str):
            stripped = command.strip()
            if not stripped:
                raise RuntimeError("Dedalus machine command string must not be empty")
            return ["bash", "-lc", stripped]
        if not command or not all(isinstance(part, str) and part for part in command):
            raise RuntimeError("Dedalus machine command must be a non-empty argv array")
        return list(command)

    def shell_command(self, argv: list[str]) -> str:
        if not argv or not all(isinstance(part, str) and part for part in argv):
            raise RuntimeError("Dedalus Machines execution command must be a non-empty argv array")
        return shlex.join(argv)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        self._debug("request", method=method, path=path, json=json_body, idempotency_key=idempotency_key)
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            try:
                response = await client.request(
                    method,
                    path,
                    headers=self._headers(idempotency_key=idempotency_key),
                    json=json_body,
                )
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Dedalus Machines API request failed: {exc}") from exc

        self._debug(
            "response",
            method=method,
            path=path,
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
        )

        if response.is_error:
            detail = response.text.strip()
            self._debug("response_error", method=method, path=path, body=detail[:800])
            raise RuntimeError(
                f"Dedalus Machines API {method} {self.base_url}{path} failed "
                f"({response.status_code}): {detail}"
            )

        if not response.content:
            return None

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()
        return response.text

    async def list_machines(self) -> list[DCSMachine]:
        data = await self._request("GET", "/machines")
        return DCSMachineList.model_validate(data).items

    async def retrieve_machine(self, machine_id: str) -> DCSMachine:
        data = await self._request("GET", f"/machines/{machine_id}")
        self._debug("machine_retrieved", **self._summarize_machine_data(data))
        return DCSMachine.model_validate(data)

    async def create_machine(self, *, vcpu: float, memory_mib: int, storage_gib: int) -> DCSMachine:
        data = await self._request(
            "POST",
            "/machines",
            json_body={
                "vcpu": vcpu,
                "memory_mib": memory_mib,
                "storage_gib": storage_gib,
            },
            idempotency_key=str(uuid.uuid4()),
        )
        self._debug("machine_created", **self._summarize_machine_data(data))
        return DCSMachine.model_validate(data)

    async def sleep_machine(self, machine_id: str) -> DCSMachine:
        raise RuntimeError(
            "Dedalus public sleep requires an If-Match ETag header; "
            "this client does not implement etag-based lifecycle mutation yet."
        )

    async def wake_machine(self, machine_id: str) -> DCSMachine:
        raise RuntimeError(
            "Dedalus public wake requires an If-Match ETag header; "
            "use SSH session readiness or preview readiness instead of calling wake_machine() directly."
        )

    async def wait_for_machine_phase(
        self,
        machine_id: str,
        *,
        target_phase: str = "running",
        timeout_s: float = 180.0,
        poll_interval_s: float = 2.0,
    ) -> DCSMachine:
        started = time.monotonic()
        last_signature: tuple[object, ...] | None = None
        while True:
            machine = await self.retrieve_machine(machine_id)
            phase = machine.status.phase if machine.status else "unknown"
            signature = (
                phase,
                machine.status.reason if machine.status else None,
                machine.status.last_transition_at if machine.status else None,
                machine.status.last_progress_at if machine.status else None,
            )
            if signature != last_signature:
                self._debug(
                    "machine_phase",
                    machine_id=machine_id,
                    phase=phase,
                    reason=machine.status.reason if machine.status else None,
                    last_transition_at=machine.status.last_transition_at if machine.status else None,
                    last_progress_at=machine.status.last_progress_at if machine.status else None,
                )
                last_signature = signature
            if phase == target_phase:
                return machine
            if time.monotonic() - started > timeout_s:
                raise RuntimeError(
                    f"Dedalus machine {machine_id} did not reach phase={target_phase!r} "
                    f"within {int(timeout_s)}s (last phase={phase!r})"
                )
            await self._sleep(poll_interval_s)

    async def create_execution(self, machine_id: str, command: list[str] | str) -> DCSExecution:
        normalized = self._normalize_command(command)
        data = await self._request(
            "POST",
            f"/machines/{machine_id}/executions",
            json_body={"command": normalized},
            idempotency_key=str(uuid.uuid4()),
        )
        self._debug("execution_created", command=normalized, **self._summarize_execution_data(data))
        return DCSExecution.model_validate(data)

    async def retrieve_execution(self, machine_id: str, execution_id: str) -> DCSExecution:
        data = await self._request("GET", f"/machines/{machine_id}/executions/{execution_id}")
        self._debug("execution_retrieved", **self._summarize_execution_data(data))
        return DCSExecution.model_validate(data)

    async def list_execution_events(self, machine_id: str, execution_id: str) -> list[DCSExecutionEvent]:
        data = await self._request("GET", f"/machines/{machine_id}/executions/{execution_id}/events")
        return DCSExecutionEventList.model_validate(data).items

    async def retrieve_execution_output(self, machine_id: str, execution_id: str) -> DCSExecutionOutput:
        data = await self._request("GET", f"/machines/{machine_id}/executions/{execution_id}/output")
        if isinstance(data, dict):
            self._debug(
                "execution_output",
                execution_id=execution_id,
                stdout_bytes=data.get("stdout_bytes"),
                stderr_bytes=data.get("stderr_bytes"),
        )
        return DCSExecutionOutput.model_validate(data)

    async def create_ssh_session(self, machine_id: str, public_key: str) -> DCSSSHSession:
        if not public_key.strip():
            raise RuntimeError("Dedalus machine SSH public key must not be empty")
        data = await self._request(
            "POST",
            f"/machines/{machine_id}/ssh",
            json_body={"public_key": public_key},
            idempotency_key=str(uuid.uuid4()),
        )
        self._debug("ssh_session_created", **self._summarize_ssh_session_data(data))
        return DCSSSHSession.model_validate(data)

    async def retrieve_ssh_session(self, machine_id: str, session_id: str) -> DCSSSHSession:
        data = await self._request("GET", f"/machines/{machine_id}/ssh/{session_id}")
        self._debug("ssh_session_retrieved", **self._summarize_ssh_session_data(data))
        return DCSSSHSession.model_validate(data)

    async def wait_for_ssh_session_ready(
        self,
        machine_id: str,
        session_id: str,
        *,
        timeout_s: float = 120.0,
        poll_interval_s: float = 1.0,
    ) -> DCSSSHSession:
        started = time.monotonic()
        last_signature: tuple[object, ...] | None = None
        while True:
            session = await self.retrieve_ssh_session(machine_id, session_id)
            signature = (
                session.status,
                session.ready_at,
                session.retry_after_ms,
                session.error_code,
                session.error_message,
            )
            if signature != last_signature:
                self._debug("ssh_session_status", **self._summarize_ssh_session_data(session.model_dump()))
                last_signature = signature
            if session.status == "ready":
                return session
            if session.status in {"failed", "closed", "expired"}:
                raise RuntimeError(
                    f"Dedalus machine SSH session {session_id} failed for {machine_id} "
                    f"(status={session.status}, error_code={session.error_code}, "
                    f"error_message={session.error_message})"
                )
            if time.monotonic() - started > timeout_s:
                raise RuntimeError(
                    f"Dedalus machine SSH session {session_id} did not become ready within {int(timeout_s)}s "
                    f"(last status={session.status}, error_code={session.error_code})"
                )
            await self._sleep(max(poll_interval_s, (session.retry_after_ms or 0) / 1000))

    async def _ensure_ssh_keypair(self) -> str:
        async with self._ssh_key_lock:
            if self._ssh_private_key.exists() and self._ssh_public_key.exists():
                return self._ssh_public_key.read_text().strip()
            proc = await asyncio.create_subprocess_exec(
                "ssh-keygen",
                "-t",
                "ed25519",
                "-N",
                "",
                "-f",
                str(self._ssh_private_key),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                detail = (stderr or stdout).decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"Failed to generate Dedalus SSH keypair: {detail}")
            return self._ssh_public_key.read_text().strip()

    def _known_hosts_line(self, host_trust: DCSHostTrust) -> str:
        prefix = "@cert-authority " if host_trust.kind == "cert_authority" else ""
        return f"{prefix}{host_trust.host_pattern} {host_trust.public_key}\n"

    def _write_ssh_session_materials(self, session: DCSSSHSession) -> tuple[Path, Path]:
        if session.connection is None:
            raise RuntimeError(f"Dedalus machine SSH session {session.session_id} is missing connection details")
        session_dir = self._ssh_material_dir / session.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        cert_path = session_dir / "user-cert.pub"
        known_hosts_path = session_dir / "known_hosts"
        cert_path.write_text(session.connection.user_certificate.rstrip() + "\n")
        known_hosts_path.write_text(self._known_hosts_line(session.connection.host_trust))
        os.chmod(cert_path, 0o600)
        os.chmod(known_hosts_path, 0o600)
        return cert_path, known_hosts_path

    def _build_ssh_argv(
        self,
        *,
        session: DCSSSHSession,
        cert_path: Path,
        known_hosts_path: Path,
        remote_command: str,
    ) -> list[str]:
        if session.connection is None:
            raise RuntimeError(f"Dedalus machine SSH session {session.session_id} is missing connection details")
        return [
            "ssh",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={known_hosts_path}",
            "-o",
            f"CertificateFile={cert_path}",
            "-o",
            f"ConnectTimeout={max(5, int(self.ssh_connect_timeout_s))}",
            "-i",
            str(self._ssh_private_key),
            "-p",
            str(session.connection.port),
            f"{session.connection.ssh_username}@{session.connection.endpoint}",
            remote_command,
        ]

    async def _warm_ssh_session(
        self,
        machine_id: str,
        session: DCSSSHSession,
        cert_path: Path,
        known_hosts_path: Path,
        *,
        timeout_s: float,
    ) -> None:
        if session.connection is None:
            raise RuntimeError(f"Dedalus machine SSH session {session.session_id} is missing connection details")
        started = time.monotonic()
        attempt = 0
        last_error: RuntimeError | None = None
        remote_command = self.shell_command(["bash", "-lc", "echo tunnel-ready"])
        while True:
            attempt += 1
            remaining = timeout_s - (time.monotonic() - started)
            if remaining <= 0:
                if last_error is not None:
                    raise last_error
                raise RuntimeError(
                    f"Dedalus machine SSH session {session.session_id} never became guest-ready for {machine_id}"
                )
            ssh_argv = self._build_ssh_argv(
                session=session,
                cert_path=cert_path,
                known_hosts_path=known_hosts_path,
                remote_command=remote_command,
            )
            per_attempt_timeout = min(remaining, max(8.0, min(15.0, remaining)))
            self._debug(
                "ssh_tunnel_probe_start",
                machine_id=machine_id,
                session_id=session.session_id,
                endpoint=session.connection.endpoint,
                username=session.connection.ssh_username,
                timeout_s=round(per_attempt_timeout, 1),
                attempt=attempt,
            )
            try:
                proc = await asyncio.create_subprocess_exec(
                    *ssh_argv,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                raise RuntimeError(
                    "OpenSSH client is required for Dedalus machine command transport. "
                    "Install openssh-client in the API container."
                ) from exc
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=per_attempt_timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                last_error = RuntimeError(
                    f"Dedalus machine SSH tunnel warmup timed out on {machine_id} "
                    f"(session_id={session.session_id})"
                )
                self._debug("ssh_tunnel_probe_retry", machine_id=machine_id, reason=str(last_error), attempt=attempt)
                await self._sleep(min(3.0, max(1.0, remaining / 4)))
                continue
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            preview = (stderr.strip() or stdout.strip())[:500]
            self._debug(
                "ssh_tunnel_probe_complete",
                machine_id=machine_id,
                session_id=session.session_id,
                exit_code=proc.returncode,
                stdout_preview=stdout.strip()[:160] or None,
                stderr_preview=stderr.strip()[:160] or None,
                attempt=attempt,
            )
            if proc.returncode == 0:
                return
            last_error = RuntimeError(
                f"Dedalus machine SSH tunnel is not yet ready on {machine_id} "
                f"(session_id={session.session_id}, exit_code={proc.returncode})"
                + (f": {preview}" if preview else "")
            )
            if not self._is_retryable_ssh_failure(preview):
                raise last_error
            self._debug("ssh_tunnel_probe_retry", machine_id=machine_id, reason=preview[:200], attempt=attempt)
            await self._sleep(min(3.0, max(1.0, remaining / 4)))

    async def _prepare_ssh_transport(
        self,
        machine_id: str,
        *,
        timeout_s: float,
    ) -> tuple[DCSSSHSession, Path, Path]:
        public_key = await self._ensure_ssh_keypair()
        session = await self.create_ssh_session(machine_id, public_key)
        session = await self.wait_for_ssh_session_ready(
            machine_id,
            session.session_id,
            timeout_s=min(timeout_s, 120.0),
        )
        if session.connection is None:
            raise RuntimeError(f"Dedalus machine SSH session {session.session_id} is missing connection details")
        cert_path, known_hosts_path = self._write_ssh_session_materials(session)
        await self._warm_ssh_session(
            machine_id,
            session,
            cert_path,
            known_hosts_path,
            timeout_s=min(timeout_s, max(20.0, self.ssh_connect_timeout_s + 15.0)),
        )
        return session, cert_path, known_hosts_path

    async def _run_command_via_ssh(
        self,
        machine_id: str,
        command: list[str] | str,
        *,
        timeout_s: float,
    ) -> DCSExecutionOutput:
        normalized = self._normalize_command(command)
        remote_command = self.shell_command(normalized)
        last_error: RuntimeError | None = None
        for attempt in range(2):
            session, cert_path, known_hosts_path = await self._prepare_ssh_transport(
                machine_id,
                timeout_s=timeout_s,
            )
            assert session.connection is not None
            ssh_argv = self._build_ssh_argv(
                session=session,
                cert_path=cert_path,
                known_hosts_path=known_hosts_path,
                remote_command=remote_command,
            )
            self._debug(
                "ssh_exec_start",
                machine_id=machine_id,
                session_id=session.session_id,
                endpoint=session.connection.endpoint,
                username=session.connection.ssh_username,
                command=normalized,
                timeout_s=timeout_s,
                attempt=attempt + 1,
            )
            started = time.monotonic()
            try:
                proc = await asyncio.create_subprocess_exec(
                    *ssh_argv,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                raise RuntimeError(
                    "OpenSSH client is required for Dedalus machine command transport. "
                    "Install openssh-client in the API container."
                ) from exc
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
            except asyncio.TimeoutError as exc:
                proc.kill()
                await proc.communicate()
                last_error = RuntimeError(
                    f"Dedalus machine SSH command timed out on {machine_id} after {int(timeout_s)}s "
                    f"(session_id={session.session_id})"
                )
                if attempt == 0:
                    self._debug("ssh_exec_retry", machine_id=machine_id, reason=str(last_error))
                    continue
                raise last_error from exc
            elapsed_ms = int((time.monotonic() - started) * 1000)
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            self._debug(
                "ssh_exec_complete",
                machine_id=machine_id,
                session_id=session.session_id,
                exit_code=proc.returncode,
                latency_ms=elapsed_ms,
                stdout_preview=stdout.strip()[:200] or None,
                stderr_preview=stderr.strip()[:200] or None,
                attempt=attempt + 1,
            )
            if proc.returncode == 0:
                return DCSExecutionOutput(
                    execution_id=session.session_id,
                    stdout=stdout,
                    stderr=stderr,
                    stdout_bytes=len(stdout_bytes),
                    stderr_bytes=len(stderr_bytes),
                )
            preview = (stderr.strip() or stdout.strip())[:500]
            last_error = RuntimeError(
                f"Dedalus machine SSH command failed on {machine_id} "
                f"(session_id={session.session_id}, exit_code={proc.returncode})"
                + (f": {preview}" if preview else "")
            )
            if attempt == 0 and self._is_retryable_ssh_failure(preview):
                self._debug("ssh_exec_retry", machine_id=machine_id, reason=preview[:200])
                continue
            raise last_error
        assert last_error is not None
        raise last_error

    async def upload_file_via_ssh(
        self,
        machine_id: str,
        local_path: str | Path,
        remote_path: str,
        *,
        timeout_s: float = 300.0,
    ) -> None:
        local_file = Path(local_path)
        if not local_file.exists() or not local_file.is_file():
            raise RuntimeError(f"Dedalus machine upload source does not exist: {local_file}")
        payload = local_file.read_bytes()
        last_error: RuntimeError | None = None
        for attempt in range(2):
            session, cert_path, known_hosts_path = await self._prepare_ssh_transport(
                machine_id,
                timeout_s=timeout_s,
            )
            assert session.connection is not None
            ssh_argv = self._build_ssh_argv(
                session=session,
                cert_path=cert_path,
                known_hosts_path=known_hosts_path,
                remote_command=self.shell_command(["bash", "-lc", f"cat > {shlex.quote(remote_path)}"]),
            )
            self._debug(
                "ssh_upload_start",
                machine_id=machine_id,
                session_id=session.session_id,
                endpoint=session.connection.endpoint,
                username=session.connection.ssh_username,
                local_path=local_file,
                remote_path=remote_path,
                timeout_s=timeout_s,
                attempt=attempt + 1,
            )
            started = time.monotonic()
            try:
                proc = await asyncio.create_subprocess_exec(
                    *ssh_argv,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                raise RuntimeError(
                    "OpenSSH client is required for Dedalus machine file upload. "
                    "Install openssh-client in the API container."
                ) from exc
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(input=payload), timeout=timeout_s)
            except asyncio.TimeoutError as exc:
                proc.kill()
                await proc.communicate()
                last_error = RuntimeError(
                    f"Dedalus machine SSH upload timed out on {machine_id} after {int(timeout_s)}s "
                    f"(session_id={session.session_id}, local_path={local_file.name})"
                )
                if attempt == 0:
                    self._debug("ssh_upload_retry", machine_id=machine_id, reason=str(last_error))
                    continue
                raise last_error from exc
            elapsed_ms = int((time.monotonic() - started) * 1000)
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            self._debug(
                "ssh_upload_complete",
                machine_id=machine_id,
                session_id=session.session_id,
                exit_code=proc.returncode,
                latency_ms=elapsed_ms,
                local_bytes=local_file.stat().st_size,
                remote_path=remote_path,
                stderr_preview=stderr.strip()[:200] or None,
                attempt=attempt + 1,
            )
            if proc.returncode == 0:
                return
            preview = (stderr.strip() or stdout.strip())[:500]
            last_error = RuntimeError(
                f"Dedalus machine SSH upload failed on {machine_id} "
                f"(session_id={session.session_id}, exit_code={proc.returncode}, remote_path={remote_path})"
                + (f": {preview}" if preview else "")
            )
            if attempt == 0 and self._is_retryable_ssh_failure(preview):
                self._debug("ssh_upload_retry", machine_id=machine_id, reason=preview[:200])
                continue
            raise last_error
        assert last_error is not None
        raise last_error

    async def _run_command_via_execution(
        self,
        machine_id: str,
        command: list[str] | str,
        *,
        timeout_s: float = 900.0,
        poll_interval_s: float = 1.0,
    ) -> DCSExecutionOutput:
        execution = await self.create_execution(machine_id, command)
        started = time.monotonic()
        last_status = execution.status
        last_signature: tuple[object, ...] | None = None
        self._debug(
            "execution_poll_start",
            machine_id=machine_id,
            execution_id=execution.execution_id,
            command=command,
            command_type=type(command).__name__,
            timeout_s=timeout_s,
        )

        while True:
            current = await self.retrieve_execution(machine_id, execution.execution_id)
            last_status = current.status
            signature = (
                current.status,
                current.started_at,
                current.completed_at,
                getattr(current, "queue_position", None),
                getattr(current, "retry_after_ms", None),
                getattr(current, "reason", None),
                getattr(current, "status_reason", None),
                getattr(current, "error_code", None),
                getattr(current, "error_message", None),
            )
            if signature != last_signature:
                self._debug(
                    "execution_status",
                    machine_id=machine_id,
                    execution_id=current.execution_id,
                    status=current.status,
                    started_at=current.started_at,
                    completed_at=current.completed_at,
                    queue_position=getattr(current, "queue_position", None),
                    retry_after_ms=getattr(current, "retry_after_ms", None),
                    reason=getattr(current, "reason", None) or getattr(current, "status_reason", None),
                    error_code=getattr(current, "error_code", None),
                    error_message=getattr(current, "error_message", None),
                )
                last_signature = signature
            if current.status == "succeeded":
                return await self.retrieve_execution_output(machine_id, current.execution_id)
            if current.status in {"failed", "cancelled"}:
                preview = ""
                try:
                    output = await self.retrieve_execution_output(machine_id, current.execution_id)
                    preview = (output.stdout or output.stderr or "").strip()
                except Exception:
                    preview = ""
                detail = (
                    f"Dedalus machine execution failed on {machine_id} "
                    f"(status={current.status}, exit_code={current.exit_code})"
                )
                if preview:
                    detail += f": {preview[:500]}"
                raise RuntimeError(detail)
            if time.monotonic() - started > timeout_s:
                event_preview = ""
                try:
                    events = await self.list_execution_events(machine_id, current.execution_id)
                    compact = [f"{ev.sequence}:{ev.type}:{ev.status or ev.error_code or 'n/a'}" for ev in events[-5:]]
                    if compact:
                        event_preview = ", ".join(compact)
                except Exception:
                    event_preview = ""
                try:
                    machine = await self.retrieve_machine(machine_id)
                    machine_phase = machine.status.phase if machine.status else "unknown"
                    machine_reason = machine.status.reason if machine.status else None
                except Exception:
                    machine_phase = "unknown"
                    machine_reason = None
                raise RuntimeError(
                    f"Dedalus machine execution timed out on {machine_id} after {int(timeout_s)}s "
                    f"(last status={last_status}, machine_phase={machine_phase}, machine_reason={machine_reason})"
                    + (f", events=[{event_preview}]" if event_preview else "")
                )
            await self._sleep(poll_interval_s)

    async def run_command(
        self,
        machine_id: str,
        command: list[str] | str,
        *,
        timeout_s: float = 900.0,
        poll_interval_s: float = 1.0,
    ) -> DCSExecutionOutput:
        self._debug(
            "run_command",
            machine_id=machine_id,
            transport=self.command_transport,
            command=self._normalize_command(command),
            timeout_s=timeout_s,
        )
        if self.command_transport == "execution":
            return await self._run_command_via_execution(
                machine_id,
                command,
                timeout_s=timeout_s,
                poll_interval_s=poll_interval_s,
            )
        if self.command_transport == "auto":
            try:
                return await self._run_command_via_ssh(machine_id, command, timeout_s=timeout_s)
            except Exception as exc:
                self._debug("ssh_transport_failed", machine_id=machine_id, error=str(exc)[:300])
                return await self._run_command_via_execution(
                    machine_id,
                    command,
                    timeout_s=timeout_s,
                    poll_interval_s=poll_interval_s,
                )
        return await self._run_command_via_ssh(machine_id, command, timeout_s=timeout_s)

    async def _sleep(self, seconds: float) -> None:
        await anyio.sleep(seconds)
