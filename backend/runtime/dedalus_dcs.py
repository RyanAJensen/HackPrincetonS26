"""Small async client for Dedalus Cloud Services (Machines API)."""
from __future__ import annotations

import os
import time
import uuid
from typing import Any, Optional

import anyio
import httpx
from pydantic import BaseModel, Field


DEFAULT_DCS_BASE_URL = "https://dcs.dedaluslabs.ai/v1"


class DCSMachineStatus(BaseModel):
    phase: str
    reason: Optional[str] = None
    retryable: Optional[bool] = None
    revision: Optional[str] = None
    last_transition_at: Optional[str] = None
    last_progress_at: Optional[str] = None


class DCSMachine(BaseModel):
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
    execution_id: str
    machine_id: str
    status: str
    command: list[str]
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    exit_code: Optional[int] = None
    stdout_bytes: Optional[int] = None
    stderr_bytes: Optional[int] = None


class DCSExecutionOutput(BaseModel):
    execution_id: str
    stdout: str = ""
    stdout_bytes: Optional[int] = None
    stderr: Optional[str] = None
    stderr_bytes: Optional[int] = None


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

    def _headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {"x-api-key": self.api_key}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
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

        if response.is_error:
            detail = response.text.strip()
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
        return DCSMachine.model_validate(data)

    async def sleep_machine(self, machine_id: str) -> DCSMachine:
        data = await self._request(
            "POST",
            f"/machines/{machine_id}/sleep",
            idempotency_key=str(uuid.uuid4()),
        )
        return DCSMachine.model_validate(data)

    async def wake_machine(self, machine_id: str) -> DCSMachine:
        data = await self._request(
            "POST",
            f"/machines/{machine_id}/wake",
            idempotency_key=str(uuid.uuid4()),
        )
        return DCSMachine.model_validate(data)

    async def wait_for_machine_phase(
        self,
        machine_id: str,
        *,
        target_phase: str = "running",
        timeout_s: float = 180.0,
        poll_interval_s: float = 2.0,
    ) -> DCSMachine:
        started = time.monotonic()
        while True:
            machine = await self.retrieve_machine(machine_id)
            phase = machine.status.phase if machine.status else "unknown"
            if phase == target_phase:
                return machine
            if time.monotonic() - started > timeout_s:
                raise RuntimeError(
                    f"Dedalus machine {machine_id} did not reach phase={target_phase!r} "
                    f"within {int(timeout_s)}s (last phase={phase!r})"
                )
            await self._sleep(poll_interval_s)

    async def create_execution(self, machine_id: str, command: list[str]) -> DCSExecution:
        if not command or not all(isinstance(part, str) and part for part in command):
            raise RuntimeError("Dedalus Machines execution command must be a non-empty argv array")
        data = await self._request(
            "POST",
            f"/machines/{machine_id}/executions",
            json_body={"command": command},
            idempotency_key=str(uuid.uuid4()),
        )
        return DCSExecution.model_validate(data)

    async def retrieve_execution(self, machine_id: str, execution_id: str) -> DCSExecution:
        data = await self._request("GET", f"/machines/{machine_id}/executions/{execution_id}")
        return DCSExecution.model_validate(data)

    async def retrieve_execution_output(self, machine_id: str, execution_id: str) -> DCSExecutionOutput:
        data = await self._request("GET", f"/machines/{machine_id}/executions/{execution_id}/output")
        return DCSExecutionOutput.model_validate(data)

    async def run_command(
        self,
        machine_id: str,
        command: list[str],
        *,
        timeout_s: float = 900.0,
        poll_interval_s: float = 1.0,
    ) -> DCSExecutionOutput:
        execution = await self.create_execution(machine_id, command)
        started = time.monotonic()
        last_status = execution.status

        while True:
            current = await self.retrieve_execution(machine_id, execution.execution_id)
            last_status = current.status
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
                raise RuntimeError(
                    f"Dedalus machine execution timed out on {machine_id} after {int(timeout_s)}s "
                    f"(last status={last_status})"
                )
            await self._sleep(poll_interval_s)

    async def _sleep(self, seconds: float) -> None:
        await anyio.sleep(seconds)
