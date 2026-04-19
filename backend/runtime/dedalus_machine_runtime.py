"""Dedalus Machines swarm runtime: one persistent VM per agent role."""
from __future__ import annotations

import asyncio
import json
import os
import tarfile
import tempfile
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from pydantic import BaseModel

from agents.machine_context import dedalus_machine_executor_ctx, dedalus_machine_id_ctx
from db import clear_swarm_machine, get_swarm_machine, list_swarm_machines, save_agent_run, save_swarm_machine
from models.agent import AgentRun, AgentStatus
from runtime.base import AgentRuntime
from runtime.dedalus_client_config import (
    describe_dedalus_billing_mode,
    describe_swarm_reasoning_mode,
    machine_worker_env_lines,
    preferred_remote_reasoning_backend,
)
from runtime.dedalus_dcs import DedalusMachinesClient
from runtime.run_state import finalize_run_failure, finalize_run_success


MACHINE_ROLE_SPECS: dict[str, dict[str, str]] = {
    "incident_parser": {"key": "situation-unit", "label": "Situation Unit"},
    "risk_assessor": {"key": "threat-analysis-unit", "label": "Threat Analysis Unit"},
    "action_planner": {"key": "operations-planner", "label": "Operations Planner"},
    "communications": {"key": "communications-officer", "label": "Communications Officer"},
}

WORKER_ROOT = os.getenv("DEDALUS_MACHINE_WORKER_ROOT", "/dev/shm/unilert")
WORKER_FILENAME = "dedalus_machine_worker.py"
WORKER_VERSION = "9"
WHEELHOUSE_DIR = Path(__file__).with_name("dedalus_machine_wheels")
REMOTE_WHEELHOUSE_ARCHIVE = "/dev/shm/unilert-wheelhouse.tar.gz"
REMOTE_PAYLOAD_DIR = "/dev/shm"


class DedalusMachineSwarmRuntime(AgentRuntime):
    """Execute each specialist agent inside its own persistent Dedalus Machine."""

    def __init__(self) -> None:
        self.api_key = os.getenv("DEDALUS_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "Dedalus Machines runtime requested but DEDALUS_API_KEY is not set. "
                "Set DEDALUS_API_KEY or use RUNTIME_MODE=local or RUNTIME_MODE=dedalus explicitly."
            )
        self.client = DedalusMachinesClient(self.api_key)
        self.vcpu = float(os.getenv("DEDALUS_MACHINE_VCPU", "1.0"))
        self.memory_mib = int(os.getenv("DEDALUS_MACHINE_MEMORY_MIB", "1024"))
        self.storage_gib = int(os.getenv("DEDALUS_MACHINE_STORAGE_GIB", "10"))
        self.machine_ready_timeout_s = float(os.getenv("DEDALUS_MACHINE_READY_TIMEOUT_SECONDS", "120"))
        self.command_ready_timeout_s = float(os.getenv("DEDALUS_MACHINE_COMMAND_READY_TIMEOUT_SECONDS", "120"))
        self.exec_timeout_s = float(os.getenv("DEDALUS_MACHINE_EXEC_TIMEOUT_SECONDS", "180"))
        self.bootstrap_timeout_s = float(os.getenv("DEDALUS_MACHINE_BOOTSTRAP_TIMEOUT_SECONDS", "180"))
        self.command_ready_cache_ttl_s = float(os.getenv("DEDALUS_MACHINE_COMMAND_READY_CACHE_TTL_SECONDS", "300"))
        self.reuse_probe_max_s = float(os.getenv("DEDALUS_MACHINE_REUSE_PROBE_MAX_SECONDS", "12"))
        self._wheelhouse_archive_path: Path | None = None
        self._machine_ready_cache: dict[str, float] = {}
        print(
            "[Dedalus] Mode: Dedalus Machines swarm — one persistent machine per specialist agent "
            f"({self.vcpu} vCPU / {self.memory_mib} MiB / {self.storage_gib} GiB, "
            f"worker billing={describe_dedalus_billing_mode()}, "
            f"reasoning={describe_swarm_reasoning_mode()}, "
            f"command_transport={self.client.command_transport})"
        )

    @staticmethod
    def _is_transient_machine_ssh_error(exc: Exception) -> bool:
        detail = str(exc)
        return any(
            token in detail
            for token in (
                "SSH_GUEST_SESSION_TERMINATED",
                "SSH_GUEST_CONNECT_FAILED",
                "SSH_GUEST_AUTH_FAILED",
                "did not accept commands",
                "timed out on",
            )
        )

    @classmethod
    def _should_rebootstrap_machine_worker(cls, exc: Exception) -> bool:
        detail = str(exc)
        if cls._is_transient_machine_ssh_error(exc):
            return True
        return any(
            token in detail
            for token in (
                f"{WORKER_ROOT}: No such file or directory",
                f"{WORKER_FILENAME}: No such file or directory",
                '".env": No such file or directory',
                "No such file or directory",
            )
        )

    def runtime_name(self) -> str:
        return "swarm"

    async def execute(
        self,
        run: AgentRun,
        fn: Callable[[AgentRun], Awaitable[dict]],
    ) -> AgentRun:
        role_spec = MACHINE_ROLE_SPECS.get(run.agent_type.value)
        if role_spec is None:
            raise RuntimeError(f"No machine role mapping exists for agent type {run.agent_type}")

        machine_id = await self._ensure_role_machine(role_spec["key"], role_spec["label"])

        exec_token = dedalus_machine_executor_ctx.set(self)
        machine_token = dedalus_machine_id_ctx.set(machine_id)
        run.runtime = "swarm"
        run.machine_id = machine_id
        run.status = AgentStatus.RUNNING
        run.started_at = datetime.utcnow()
        run.log_entries.append(
            f"Dedalus Machines — role={role_spec['label']} agent={run.agent_type} machine_id={machine_id}"
        )
        save_agent_run(run)

        try:
            result = await fn(run)
            finalize_run_success(
                run,
                result,
                "Dedalus Machines — agent completed via persistent machine worker and structured output",
            )
        except Exception as exc:
            finalize_run_failure(run, exc, "Dedalus Machines FAILED", traceback.format_exc())
        finally:
            dedalus_machine_id_ctx.reset(machine_token)
            dedalus_machine_executor_ctx.reset(exec_token)

        save_agent_run(run)
        return run

    async def run_prompt_on_machine(
        self,
        *,
        machine_id: str,
        prompt: str,
        system: str,
        caller: str,
        response_model: type[BaseModel] | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        await self._bootstrap_machine(machine_id)
        backend = preferred_remote_reasoning_backend()
        requested_timeout = float(
            timeout_seconds if timeout_seconds is not None else os.getenv("DEDALUS_MACHINE_LLM_TIMEOUT_SECONDS", "90")
        )
        command_timeout = min(self.exec_timeout_s, max(15.0, requested_timeout + 10.0))
        payload = {
            "operation": "run_llm",
            "caller": caller,
            "backend": backend,
            "prompt": prompt,
            "system": system,
            "response_model": response_model.__name__ if response_model else None,
            "model": (
                os.getenv("K2_MODEL", "MBZUAI-IFM/K2-Think-v2")
                if backend == "k2"
                else os.getenv("DEDALUS_MODEL", "anthropic/claude-sonnet-4-20250514")
            ),
            "max_steps": int(os.getenv("DEDALUS_MAX_STEPS", "5")),
            "timeout_seconds": requested_timeout,
            # Keep remote stdout clean so the worker can print raw JSON only.
            "debug": os.getenv("DEDALUS_MACHINE_RUNNER_DEBUG", "false").lower() in ("1", "true", "yes"),
            "verbose": os.getenv("DEDALUS_MACHINE_RUNNER_VERBOSE", "false").lower() in ("1", "true", "yes"),
        }
        print(
            f"[Dedalus Machines] run_llm machine_id={machine_id} caller={caller} "
            f"backend={backend} model={payload['model']} timeout_s={int(requested_timeout)}"
        )
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                output = await self._invoke_worker(machine_id, payload, timeout_s=command_timeout)
                return output.stdout or ""
            except Exception as exc:
                last_exc = exc
                if attempt == 0 and self._should_rebootstrap_machine_worker(exc):
                    self._machine_ready_cache.pop(machine_id, None)
                    print(
                        f"[Dedalus Machines] retrying worker call after machine worker failure "
                        f"machine_id={machine_id} caller={caller}: {exc}"
                    )
                    await self.wait_for_machine_command_ready(machine_id)
                    await self._bootstrap_machine(machine_id)
                    continue
                raise
        assert last_exc is not None
        raise last_exc

    async def run_worker_healthcheck(self, machine_id: str) -> dict:
        last_exc: Exception | None = None
        output = None
        for attempt in range(2):
            try:
                await self._bootstrap_machine(machine_id)
                output = await self._invoke_worker(
                    machine_id,
                    {"operation": "healthcheck"},
                    timeout_s=min(self.exec_timeout_s, 120),
                )
                break
            except Exception as exc:
                last_exc = exc
                if attempt == 0 and self._should_rebootstrap_machine_worker(exc):
                    self._machine_ready_cache.pop(machine_id, None)
                    print(
                        f"[Dedalus Machines] retrying worker healthcheck after machine worker failure "
                        f"machine_id={machine_id}: {exc}"
                    )
                    await self.wait_for_machine_command_ready(machine_id)
                    await self._bootstrap_machine(machine_id)
                    continue
                raise
        if output is None:
            assert last_exc is not None
            raise last_exc
        stdout = (output.stdout or "").strip()
        if not stdout:
            raise RuntimeError(f"Dedalus machine worker healthcheck returned no output for {machine_id}")
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Dedalus machine worker healthcheck returned non-JSON output for {machine_id}: {stdout[:240]!r}"
            ) from exc

    async def _ensure_role_machine(self, role_key: str, role_label: str) -> str:
        machine_id = get_swarm_machine(role_key)
        if machine_id:
            try:
                machine = await self.client.retrieve_machine(machine_id)
                if (
                    machine.vcpu < self.vcpu
                    or machine.memory_mib < self.memory_mib
                    or machine.storage_gib < self.storage_gib
                ):
                    raise RuntimeError(
                        f"existing machine resources are below required spec "
                        f"({machine.vcpu} vCPU/{machine.memory_mib} MiB/{machine.storage_gib} GiB)"
                    )
                phase = machine.status.phase if machine.status else "unknown"
                if phase != "running":
                    raise RuntimeError(f"existing machine is not execution-ready (phase={phase})")
                cached_at = self._machine_ready_cache.get(machine.machine_id)
                probe_elapsed = 0.0
                if cached_at is None or (time.monotonic() - cached_at) > self.command_ready_cache_ttl_s:
                    probe_elapsed = await self.wait_for_machine_command_ready(
                        machine.machine_id,
                        timeout_s=min(self.command_ready_timeout_s, max(15.0, self.reuse_probe_max_s + 3.0)),
                    )
                    if probe_elapsed > self.reuse_probe_max_s:
                        raise RuntimeError(
                            f"existing machine command probe was too slow ({probe_elapsed:.1f}s > "
                            f"{self.reuse_probe_max_s:.1f}s)"
                        )
                print(f"[Dedalus Machines] Reusing {role_label} machine {machine.machine_id}")
                return machine.machine_id
            except Exception as exc:
                clear_swarm_machine(role_key)
                print(f"[Dedalus Machines] Clearing stale machine mapping for {role_label}: {exc}")

        reserved_machine_ids = set(list_swarm_machines().values())
        reserved_machine_ids.discard(machine_id)
        adopted_machine = await self._adopt_existing_machine(
            role_label,
            exclude_machine_ids=reserved_machine_ids,
        )
        if adopted_machine is not None:
            save_swarm_machine(role_key, adopted_machine)
            print(f"[Dedalus Machines] Adopted existing {role_label} machine {adopted_machine}")
            return adopted_machine

        try:
            created = await self.client.create_machine(
                vcpu=self.vcpu,
                memory_mib=self.memory_mib,
                storage_gib=self.storage_gib,
            )
            ready = await self.client.wait_for_machine_phase(
                created.machine_id,
                timeout_s=self.machine_ready_timeout_s,
            )
            await self.wait_for_machine_command_ready(
                ready.machine_id,
                timeout_s=max(self.command_ready_timeout_s, self.machine_ready_timeout_s),
            )
            save_swarm_machine(role_key, ready.machine_id)
            print(f"[Dedalus Machines] Created {role_label} machine {ready.machine_id}")
            return ready.machine_id
        except Exception as exc:
            detail = str(exc)
            if "MACHINE_QUOTA_EXCEEDED" not in detail and "machine quota exceeded" not in detail:
                raise
            print(
                f"[Dedalus Machines] Machine quota exceeded while creating {role_label}; "
                "searching for a reusable running machine"
            )
            adopted_machine = await self._adopt_existing_machine(
                role_label,
                exclude_machine_ids=set(),
            )
            if adopted_machine is not None:
                save_swarm_machine(role_key, adopted_machine)
                print(f"[Dedalus Machines] Adopted quota-recovery {role_label} machine {adopted_machine}")
                return adopted_machine
            raise

    async def _adopt_existing_machine(
        self,
        role_label: str,
        *,
        exclude_machine_ids: set[str],
    ) -> str | None:
        try:
            machines = await self.client.list_machines()
        except Exception as exc:
            print(f"[Dedalus Machines] Could not list existing machines for {role_label}: {exc}")
            return None
        candidates = [
            machine
            for machine in machines
            if machine.machine_id not in exclude_machine_ids
            and (machine.status.phase if machine.status else "unknown") == "running"
            and machine.vcpu >= self.vcpu
            and machine.memory_mib >= self.memory_mib
            and machine.storage_gib >= self.storage_gib
        ]
        candidates.sort(key=lambda machine: machine.created_at or "")
        for candidate in candidates:
            try:
                probe_elapsed = await self.wait_for_machine_command_ready(
                    candidate.machine_id,
                    timeout_s=min(self.command_ready_timeout_s, 20.0),
                )
                print(
                    f"[Dedalus Machines] Recovered {role_label} onto existing machine {candidate.machine_id} "
                    f"({probe_elapsed:.1f}s command probe)"
                )
                return candidate.machine_id
            except Exception as exc:
                print(
                    f"[Dedalus Machines] Existing machine {candidate.machine_id} not reusable for {role_label}: {exc}"
                )
        return None

    async def _bootstrap_machine(self, machine_id: str) -> None:
        check_script = (
            "set -euo pipefail\n"
            f'ROOT="{WORKER_ROOT}"\n'
            'VENDOR="$ROOT/vendor/site"\n'
            'VERSION_FILE="$ROOT/.worker_version"\n'
            f'if [ -f "$VERSION_FILE" ] && [ "$(cat "$VERSION_FILE")" = "{WORKER_VERSION}" ]; then\n'
            '  export PYTHONPATH="$VENDOR${PYTHONPATH:+:$PYTHONPATH}"\n'
            "  if python3 - <<'PY' >/dev/null 2>&1\n"
            "import dedalus_labs, pydantic, pydantic_core, httpx, anyio, jiter\n"
            "PY\n"
            "  then\n"
            "    echo ready\n"
            "    exit 0\n"
            "  fi\n"
            "fi\n"
            "echo missing\n"
        )
        status_output = await self.client.run_command(
            machine_id,
            ["bash", "-lc", check_script],
            timeout_s=min(self.bootstrap_timeout_s, 120),
        )
        if (status_output.stdout or "").strip() == "ready":
            print(f"[Dedalus Machines] Bootstrap already satisfied for {machine_id}")
            return

        archive_path = self._build_wheelhouse_archive()
        await self.client.upload_file_via_ssh(
            machine_id,
            archive_path,
            REMOTE_WHEELHOUSE_ARCHIVE,
            timeout_s=min(self.bootstrap_timeout_s, 300),
        )
        worker_src = Path(__file__).with_name(WORKER_FILENAME).read_text()
        worker_tmp_dir = Path(tempfile.mkdtemp(prefix="dedalus-worker-bootstrap-"))
        worker_tmp_path = worker_tmp_dir / WORKER_FILENAME
        env_tmp_path = worker_tmp_dir / "machine.env"
        worker_tmp_path.write_text(worker_src)
        env_tmp_path.write_text(machine_worker_env_lines(self.api_key))
        remote_worker_path = f"{REMOTE_PAYLOAD_DIR}/{uuid.uuid4().hex}-{WORKER_FILENAME}"
        remote_env_path = f"{REMOTE_PAYLOAD_DIR}/{uuid.uuid4().hex}.env"
        try:
            await self.client.upload_file_via_ssh(
                machine_id,
                worker_tmp_path,
                remote_worker_path,
                timeout_s=min(self.bootstrap_timeout_s, 180),
            )
            await self.client.upload_file_via_ssh(
                machine_id,
                env_tmp_path,
                remote_env_path,
                timeout_s=min(self.bootstrap_timeout_s, 120),
            )
        finally:
            try:
                worker_tmp_path.unlink(missing_ok=True)
                env_tmp_path.unlink(missing_ok=True)
                worker_tmp_dir.rmdir()
            except OSError:
                pass
        script = (
            "set -euo pipefail\n"
            f'ROOT="{WORKER_ROOT}"\n'
            'export DEDALUS_MACHINE_WORKER_ROOT="$ROOT"\n'
            'VENDOR="$ROOT/vendor/site"\n'
            'WHEELHOUSE="$ROOT/wheelhouse"\n'
            'VERSION_FILE="$ROOT/.worker_version"\n'
            f'REMOTE_WORKER="{remote_worker_path}"\n'
            f'REMOTE_ENV="{remote_env_path}"\n'
            'mkdir -p "$ROOT"\n'
            "python3 - <<'PY'\n"
            "import os\n"
            "import shutil\n"
            "import tarfile\n"
            "import zipfile\n"
            "from pathlib import Path\n"
            'root = Path(os.environ["DEDALUS_MACHINE_WORKER_ROOT"])\n'
            'archive = Path("' + REMOTE_WHEELHOUSE_ARCHIVE + '")\n'
            'wheelhouse = root / "wheelhouse"\n'
            'vendor = root / "vendor" / "site"\n'
            "if wheelhouse.exists():\n"
            "    shutil.rmtree(wheelhouse)\n"
            "if vendor.exists():\n"
            "    shutil.rmtree(vendor)\n"
            "wheelhouse.mkdir(parents=True, exist_ok=True)\n"
            "vendor.mkdir(parents=True, exist_ok=True)\n"
            'with tarfile.open(archive, "r:gz") as tf:\n'
            "    tf.extractall(wheelhouse)\n"
            "for wheel in sorted(wheelhouse.glob('*.whl')):\n"
            "    with zipfile.ZipFile(wheel) as zf:\n"
            "        zf.extractall(vendor)\n"
            "archive.unlink(missing_ok=True)\n"
            "PY\n"
            'export PYTHONPATH="$VENDOR${PYTHONPATH:+:$PYTHONPATH}"\n'
            'install -m 0644 "$REMOTE_WORKER" "$ROOT/' + WORKER_FILENAME + '"\n'
            'install -m 0600 "$REMOTE_ENV" "$ROOT/.env"\n'
            'rm -f "$REMOTE_WORKER" "$REMOTE_ENV"\n'
            f'printf "%s" "{WORKER_VERSION}" > "$ROOT/.worker_version"\n'
            'chmod 600 "$ROOT/.env"\n'
            "python3 - <<'PY'\n"
            "import dedalus_labs, pydantic, pydantic_core, httpx, anyio, jiter\n"
            "PY\n"
        )
        started = time.monotonic()
        output = await self.client.run_command(
            machine_id,
            ["bash", "-lc", script],
            timeout_s=self.bootstrap_timeout_s,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        stdout = (output.stdout or "").strip()
        note = f" stdout={stdout[:120]!r}" if stdout else ""
        print(f"[Dedalus Machines] Bootstrap checked for {machine_id} ({elapsed_ms}ms){note}")

    async def _invoke_worker(self, machine_id: str, payload: dict, *, timeout_s: float) -> object:
        payload_dir = Path(tempfile.mkdtemp(prefix="dedalus-payload-"))
        payload_path = payload_dir / "payload.json"
        payload_path.write_text(json.dumps(payload, separators=(",", ":")))
        remote_payload_path = f"{REMOTE_PAYLOAD_DIR}/{uuid.uuid4().hex}.json"
        await self.client.upload_file_via_ssh(
            machine_id,
            payload_path,
            remote_payload_path,
            timeout_s=min(timeout_s, 120.0),
        )
        script = (
            "set -euo pipefail\n"
            f'ROOT="{WORKER_ROOT}"\n'
            'export DEDALUS_MACHINE_WORKER_ROOT="$ROOT"\n'
            'export PYTHONPATH="$ROOT/vendor/site${PYTHONPATH:+:$PYTHONPATH}"\n'
            'cd "$ROOT"\n'
            "set -a\n"
            '. "$ROOT/.env"\n'
            "set +a\n"
            "set +e\n"
            f'python3 "$ROOT/{WORKER_FILENAME}" --payload-path "{remote_payload_path}"\n'
            'status=$?\n'
            "set -e\n"
            f'rm -f "{remote_payload_path}"\n'
            'exit "$status"\n'
        )
        try:
            return await self.client.run_command(machine_id, ["bash", "-lc", script], timeout_s=timeout_s)
        finally:
            try:
                payload_path.unlink(missing_ok=True)
                payload_dir.rmdir()
            except OSError:
                pass

    def _build_wheelhouse_archive(self) -> Path:
        if self._wheelhouse_archive_path and self._wheelhouse_archive_path.exists():
            return self._wheelhouse_archive_path
        if not WHEELHOUSE_DIR.exists():
            raise RuntimeError(
                f"Dedalus machine wheelhouse is missing at {WHEELHOUSE_DIR}. "
                "Download Linux cp312 wheels before running the machine worker."
            )
        wheels = sorted(WHEELHOUSE_DIR.glob("*.whl"))
        if not wheels:
            raise RuntimeError(
                f"Dedalus machine wheelhouse is empty at {WHEELHOUSE_DIR}. "
                "Download Linux cp312 wheels before running the machine worker."
            )
        archive_dir = Path(tempfile.mkdtemp(prefix="dedalus-wheelhouse-"))
        archive_path = archive_dir / "dedalus-machine-wheelhouse.tar.gz"
        with tarfile.open(archive_path, "w:gz") as tar:
            for wheel in wheels:
                tar.add(wheel, arcname=wheel.name)
        self._wheelhouse_archive_path = archive_path
        return archive_path

    async def wait_for_machine_command_ready(self, machine_id: str, timeout_s: float | None = None) -> float:
        deadline_s = float(timeout_s if timeout_s is not None else self.command_ready_timeout_s)
        started = time.monotonic()
        last_error: Exception | None = None
        attempt = 0
        while True:
            attempt += 1
            remaining = deadline_s - (time.monotonic() - started)
            if remaining <= 0:
                detail = str(last_error) if last_error else "machine never accepted command execution"
                raise RuntimeError(
                    f"Dedalus machine {machine_id} reached phase=running but did not accept commands "
                    f"within {int(deadline_s)}s: {detail}"
                )
            try:
                print(
                    f"[Dedalus Machines] command readiness probe machine_id={machine_id} "
                    f"attempt={attempt} remaining_s={int(remaining)}"
                )
                output = await self.client.run_command(
                    machine_id,
                    ["bash", "-lc", "echo ready"],
                    timeout_s=min(45, max(15, remaining)),
                )
                if (output.stdout or "").strip() == "ready":
                    self._machine_ready_cache[machine_id] = time.monotonic()
                    elapsed_s = time.monotonic() - started
                    print(
                        f"[Dedalus Machines] machine_id={machine_id} accepted command execution "
                        f"in {elapsed_s:.1f}s"
                    )
                    return elapsed_s
            except Exception as exc:
                last_error = exc
                print(f"[Dedalus Machines] command readiness probe failed machine_id={machine_id}: {exc}")
                await asyncio.sleep(5)
