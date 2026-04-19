"""Dedalus Machines swarm runtime: one persistent VM per agent role."""
from __future__ import annotations

import base64
import json
import os
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from pydantic import BaseModel

from agents.machine_context import dedalus_machine_executor_ctx, dedalus_machine_id_ctx
from db import clear_swarm_machine, get_swarm_machine, save_agent_run, save_swarm_machine
from models.agent import AgentRun, AgentStatus
from runtime.base import AgentRuntime
from runtime.dedalus_client_config import describe_dedalus_billing_mode, machine_worker_env_lines
from runtime.dedalus_dcs import DedalusMachinesClient
from runtime.run_state import finalize_run_failure, finalize_run_success


MACHINE_ROLE_SPECS: dict[str, dict[str, str]] = {
    "incident_parser": {"key": "situation-unit", "label": "Situation Unit"},
    "risk_assessor": {"key": "threat-analysis-unit", "label": "Threat Analysis Unit"},
    "action_planner": {"key": "operations-planner", "label": "Operations Planner"},
    "communications": {"key": "communications-officer", "label": "Communications Officer"},
}

WORKER_ROOT = "/home/machine/unilert"
WORKER_FILENAME = "dedalus_machine_worker.py"
WORKER_VERSION = "1"


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
        self.vcpu = float(os.getenv("DEDALUS_MACHINE_VCPU", "0.25"))
        self.memory_mib = int(os.getenv("DEDALUS_MACHINE_MEMORY_MIB", "512"))
        self.storage_gib = int(os.getenv("DEDALUS_MACHINE_STORAGE_GIB", "1"))
        self.machine_ready_timeout_s = float(os.getenv("DEDALUS_MACHINE_READY_TIMEOUT_SECONDS", "180"))
        self.exec_timeout_s = float(os.getenv("DEDALUS_MACHINE_EXEC_TIMEOUT_SECONDS", "900"))
        self.bootstrap_timeout_s = float(os.getenv("DEDALUS_MACHINE_BOOTSTRAP_TIMEOUT_SECONDS", "600"))
        print(
            "[Dedalus] Mode: Dedalus Machines swarm — one persistent machine per specialist agent "
            f"({self.vcpu} vCPU / {self.memory_mib} MiB / {self.storage_gib} GiB, "
            f"worker billing={describe_dedalus_billing_mode()})"
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
    ) -> str:
        await self._bootstrap_machine(machine_id)
        payload = {
            "caller": caller,
            "prompt": prompt,
            "system": system,
            "response_model": response_model.__name__ if response_model else None,
            "model": os.getenv("DEDALUS_MODEL", "anthropic/claude-sonnet-4-20250514"),
            "max_steps": int(os.getenv("DEDALUS_MAX_STEPS", "5")),
            # Keep remote stdout clean so the worker can print raw JSON only.
            "debug": os.getenv("DEDALUS_MACHINE_RUNNER_DEBUG", "false").lower() in ("1", "true", "yes"),
            "verbose": os.getenv("DEDALUS_MACHINE_RUNNER_VERBOSE", "false").lower() in ("1", "true", "yes"),
        }
        payload_b64 = base64.b64encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")
        command = [
            "bash",
            "-lc",
            (
                "set -euo pipefail\n"
                'export PATH="$HOME/.local/bin:$PATH"\n'
                f'cd "{WORKER_ROOT}"\n'
                "set -a\n"
                f'. "{WORKER_ROOT}/.env"\n'
                "set +a\n"
                f'python3 "{WORKER_ROOT}/{WORKER_FILENAME}" --payload-b64 \'{payload_b64}\'\n'
            ),
        ]
        output = await self.client.run_command(
            machine_id,
            command,
            timeout_s=self.exec_timeout_s,
        )
        return output.stdout or ""

    async def _ensure_role_machine(self, role_key: str, role_label: str) -> str:
        machine_id = get_swarm_machine(role_key)
        if machine_id:
            try:
                machine = await self.client.retrieve_machine(machine_id)
                phase = machine.status.phase if machine.status else "unknown"
                if phase != "running":
                    try:
                        await self.client.wake_machine(machine_id)
                    except Exception:
                        pass
                    machine = await self.client.wait_for_machine_phase(
                        machine_id,
                        timeout_s=self.machine_ready_timeout_s,
                    )
                print(f"[Dedalus Machines] Reusing {role_label} machine {machine.machine_id}")
                return machine.machine_id
            except Exception as exc:
                clear_swarm_machine(role_key)
                print(f"[Dedalus Machines] Clearing stale machine mapping for {role_label}: {exc}")

        created = await self.client.create_machine(
            vcpu=self.vcpu,
            memory_mib=self.memory_mib,
            storage_gib=self.storage_gib,
        )
        ready = await self.client.wait_for_machine_phase(
            created.machine_id,
            timeout_s=self.machine_ready_timeout_s,
        )
        save_swarm_machine(role_key, ready.machine_id)
        print(f"[Dedalus Machines] Created {role_label} machine {ready.machine_id}")
        return ready.machine_id

    async def _bootstrap_machine(self, machine_id: str) -> None:
        worker_src = Path(__file__).with_name(WORKER_FILENAME).read_text()
        worker_b64 = base64.b64encode(worker_src.encode("utf-8")).decode("ascii")
        env_b64 = base64.b64encode(machine_worker_env_lines(self.api_key).encode("utf-8")).decode("ascii")
        command = [
            "bash",
            "-lc",
            (
                "set -euo pipefail\n"
                'export PATH="$HOME/.local/bin:$PATH"\n'
                f'ROOT="{WORKER_ROOT}"\n'
                'VERSION_FILE="$ROOT/.worker_version"\n'
                f'if [ -f "$VERSION_FILE" ] && [ "$(cat "$VERSION_FILE")" = "{WORKER_VERSION}" ]; then\n'
                "  python3 - <<'PY' >/dev/null 2>&1 && exit 0 || true\n"
                "import dedalus_labs, pydantic\n"
                "PY\n"
                "fi\n"
                'mkdir -p "$ROOT"\n'
                "python3 -m ensurepip --user >/dev/null 2>&1 || true\n"
                "python3 -m pip install --user --disable-pip-version-check --quiet "
                "\"dedalus_labs>=0.3.0\" \"pydantic>=2.10.0\"\n"
                "python3 - <<'PY'\n"
                "import base64\n"
                "from pathlib import Path\n"
                f'root = Path("{WORKER_ROOT}")\n'
                "root.mkdir(parents=True, exist_ok=True)\n"
                f'(root / "{WORKER_FILENAME}").write_text(base64.b64decode("{worker_b64}").decode("utf-8"))\n'
                f'(root / ".env").write_text(base64.b64decode("{env_b64}").decode("utf-8"))\n'
                f'(root / ".worker_version").write_text("{WORKER_VERSION}")\n'
                "PY\n"
                f'chmod 600 "{WORKER_ROOT}/.env"\n'
            ),
        ]
        started = time.monotonic()
        output = await self.client.run_command(
            machine_id,
            command,
            timeout_s=self.bootstrap_timeout_s,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        stdout = (output.stdout or "").strip()
        note = f" stdout={stdout[:120]!r}" if stdout else ""
        print(f"[Dedalus Machines] Bootstrap checked for {machine_id} ({elapsed_ms}ms){note}")
