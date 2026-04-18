"""
Dedalus Persistent Agent Swarm Runtime.

Architecture — 3 long-lived machines, each with a dedicated ICS role:

  ┌─────────────────────────────────────────────────────────────┐
  │  Situation Unit Machine       (role: situation)             │
  │    → incident_parser                                        │
  │    → geocode + FEMA context                                 │
  ├─────────────────────────────────────────────────────────────┤
  │  Intelligence Machine         (role: intelligence)          │
  │    → risk_assessor   ← K2 Think V2 deep reasoning          │
  │    → action_planner  ← K2 Think V2 routing + triage        │
  │    artifacts accumulate across replans on this machine      │
  ├─────────────────────────────────────────────────────────────┤
  │  Communications Machine       (role: communications)        │
  │    → communications_agent                                   │
  │    → public advisories, EMS briefs, hospital notifications  │
  └─────────────────────────────────────────────────────────────┘

Machine lifecycle:
  • Machines are created once per role, stored in SQLite swarm_machines table
  • Reused across all incidents and replans — never destroyed by this runtime
  • Sleeping machines are woken; terminal machines are cleared and recreated
  • If a role's machine is not reachable, that agent runs as dedalus_degraded

Runtime labels:
  "dedalus"          — machine healthy, input + output artifacts stored on machine
  "dedalus_degraded" — machine assigned but not running (LLM ran locally, no artifacts)
  "local"            — DEDALUS_API_KEY not set or SDK not installed

Environment:
  DEDALUS_API_KEY    — required for Dedalus runtime
  DEDALUS_PROJECT_ID — defaults to "sentinel"
  REQUIRE_DEDALUS    — if "true", raise at startup when Dedalus unavailable
"""
from __future__ import annotations
import asyncio
import json
import os
import traceback
from datetime import datetime, timezone
from typing import Callable, Awaitable

from models.agent import AgentRun, AgentStatus
from db import (
    save_agent_run,
    get_swarm_machine, save_swarm_machine, clear_swarm_machine, list_swarm_machines,
)
from runtime.base import AgentRuntime

try:
    import dedalus_sdk
    DEDALUS_AVAILABLE = True
except ImportError:
    DEDALUS_AVAILABLE = False

# Swarm role definitions — order matters for creation priority
SWARM_ROLES = ["situation", "intelligence", "communications"]

# Agent type → swarm role
AGENT_ROLE_MAP: dict[str, str] = {
    "incident_parser": "situation",
    "risk_assessor":   "intelligence",
    "action_planner":  "intelligence",
    "communications":  "communications",
}

# Human-readable role labels for logs
ROLE_LABELS: dict[str, str] = {
    "situation":       "Situation Unit",
    "intelligence":    "Intelligence / K2 Think V2",
    "communications":  "Communications Officer",
}

# K2 Think V2 is the core reasoning engine for these roles
K2_REASONING_ROLES = {"intelligence"}

_MACHINE_MEMORY_MIB = 512
_MACHINE_STORAGE_GIB = 1
_MACHINE_VCPU = 0.25

_MACHINE_READY_TIMEOUT_S = 50.0
_MACHINE_POLL_INTERVAL_S = 2.0


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3] + "Z"


def _dump_machine_status(machine) -> dict:
    """Extract all diagnostic fields from a Dedalus machine object."""
    info: dict = {"machine_id": machine.machine_id}
    status = machine.status
    if status:
        for attr in ("phase", "message", "error", "reason", "revision",
                     "node_name", "started_at", "stopped_at"):
            val = getattr(status, attr, None)
            if val is not None:
                info[attr] = str(val)
        try:
            for k, v in vars(status).items():
                if k not in info and v is not None and not k.startswith("_"):
                    info[k] = str(v)
        except TypeError:
            pass
    return info


class DedalusAgentRuntime(AgentRuntime):
    """
    Persistent swarm runtime. Routes each agent type to its designated
    long-lived Dedalus machine. Machines are shared across all incidents.
    """

    def __init__(self):
        self.api_key = os.getenv("DEDALUS_API_KEY")
        self.project_id = os.getenv("DEDALUS_PROJECT_ID", "sentinel")
        self._client: "dedalus_sdk.AsyncDedalus | None" = None

        require = os.getenv("REQUIRE_DEDALUS", "").lower() == "true"
        if require:
            if not DEDALUS_AVAILABLE:
                raise RuntimeError("REQUIRE_DEDALUS=true but dedalus_sdk is not installed")
            if not self.api_key:
                raise RuntimeError("REQUIRE_DEDALUS=true but DEDALUS_API_KEY is not set")

        if DEDALUS_AVAILABLE and self.api_key:
            existing = list_swarm_machines()
            existing_summary = ", ".join(f"{r}={mid[:8]}" for r, mid in existing.items()) if existing else "none"
            print(
                f"[Swarm] Dedalus SDK ready | key={self.api_key[:8]}… | project={self.project_id}\n"
                f"[Swarm] Registered machines: {existing_summary}\n"
                f"[Swarm] Role map: situation→parser | intelligence→risk+planner (K2 Think V2) | communications→comms"
            )
        elif not self.api_key:
            print("[Swarm] DEDALUS_API_KEY not set — local fallback")
        else:
            print("[Swarm] dedalus_sdk not installed — local fallback")

    def _get_client(self) -> "dedalus_sdk.AsyncDedalus | None":
        if not DEDALUS_AVAILABLE or not self.api_key:
            return None
        if self._client is None:
            self._client = dedalus_sdk.AsyncDedalus(api_key=self.api_key)
            print("[Swarm] Dedalus client initialized")
        return self._client

    def runtime_name(self) -> str:
        return "dedalus" if self._get_client() else "local"

    # ------------------------------------------------------------------
    # Swarm machine lifecycle
    # ------------------------------------------------------------------

    async def _get_or_create_swarm_machine(self, role: str, log: list[str]) -> tuple[str, bool]:
        """
        Get or create the persistent machine for a swarm role.
        Returns (machine_id, is_new).

        Strategy:
          1. Check SQLite for registered machine
          2. Verify it's not in a terminal state
          3. If terminal or missing: scan existing Dedalus machines for reuse before creating
          4. Create new only if no reusable machine exists
        """
        client = self._get_client()
        role_label = ROLE_LABELS.get(role, role)

        cached = get_swarm_machine(role)
        if cached:
            log.append(f"[{_ts()}] [Dedalus API] machines.retrieve — verifying {role_label} machine {cached[:12]}")
            try:
                m = await client.machines.retrieve(machine_id=cached)
                phase = m.status.phase if m.status else "unknown"
                if phase not in ("destroyed", "failed", "destroying"):
                    log.append(f"[{_ts()}] Resumed {role_label} machine {cached[:12]} (phase={phase})")
                    print(f"  [Swarm] {role_label}: resumed machine {cached[:12]} (phase={phase})")
                    return cached, False
                else:
                    details = _dump_machine_status(m)
                    log.append(f"[{_ts()}] {role_label} machine {cached[:12]} terminal (phase={phase}) — clearing. {details}")
                    print(f"  [Swarm] {role_label}: machine {cached[:12]} is {phase}, clearing cache")
                    clear_swarm_machine(role)
            except Exception as e:
                log.append(f"[{_ts()}] Could not verify {role_label} machine: {e} — clearing")
                clear_swarm_machine(role)

        # Attempt to create a new machine for this role
        log.append(f"[{_ts()}] [Dedalus API] machines.create for role={role} (memory={_MACHINE_MEMORY_MIB}MiB vcpu={_MACHINE_VCPU})")
        print(f"  [Swarm] {role_label}: creating new machine")
        try:
            machine = await client.machines.create(
                memory_mib=_MACHINE_MEMORY_MIB,
                storage_gib=_MACHINE_STORAGE_GIB,
                vcpu=_MACHINE_VCPU,
            )
            machine_id = machine.machine_id
            save_swarm_machine(role, machine_id)
            log.append(f"[{_ts()}] [Dedalus API] {role_label} machine created: {machine_id}")
            print(f"  [Swarm] {role_label}: machine created {machine_id}")
            return machine_id, True

        except Exception as e:
            err_str = str(e)
            is_quota = "MACHINE_QUOTA_EXCEEDED" in err_str or "409" in err_str
            reason = "quota exceeded" if is_quota else f"create failed: {e}"
            log.append(f"[{_ts()}] [Dedalus API] machines.create FAILED ({reason}) — scanning for reuse")
            print(f"  [Swarm] {role_label}: creation failed ({reason}), scanning for existing machines")

            # Scan all machines, prefer running ones not already assigned to another role
            try:
                log.append(f"[{_ts()}] [Dedalus API] machines.list")
                page = await client.machines.list()
                assigned = set(list_swarm_machines().values())
                candidates: list[tuple] = []
                async for m in page:
                    phase = m.status.phase if m.status else "unknown"
                    if phase not in ("destroyed", "failed", "destroying"):
                        # Prefer unassigned machines but will share if necessary
                        candidates.append((m, phase, m.machine_id not in assigned))

                if candidates:
                    # Sort: unassigned running first, then unassigned any, then assigned running
                    candidates.sort(key=lambda x: (not x[2], x[1] != "running"))
                    chosen_m, chosen_phase, unassigned = candidates[0]
                    machine_id = chosen_m.machine_id
                    save_swarm_machine(role, machine_id)
                    shared_note = "" if unassigned else " (shared with another role)"
                    log.append(f"[{_ts()}] [Dedalus API] Reusing machine {machine_id[:12]} for {role_label} (phase={chosen_phase}{shared_note})")
                    print(f"  [Swarm] {role_label}: reusing machine {machine_id[:12]} (phase={chosen_phase}{shared_note})")
                    return machine_id, False
                else:
                    log.append(f"[{_ts()}] [Dedalus API] machines.list returned 0 usable machines")
                    print(f"  [Swarm] {role_label}: no usable machines found")
            except Exception as list_err:
                log.append(f"[{_ts()}] [Dedalus API] machines.list FAILED: {list_err}")

            raise

    async def _wait_for_running(self, machine_id: str, role: str, log: list[str]) -> bool:
        """
        Wake machine if sleeping. Poll until running or timeout.
        Clears swarm cache on terminal state. Returns True only when running.
        """
        client = self._get_client()
        role_label = ROLE_LABELS.get(role, role)
        deadline = asyncio.get_event_loop().time() + _MACHINE_READY_TIMEOUT_S
        last_phase = None

        while asyncio.get_event_loop().time() < deadline:
            try:
                log.append(f"[{_ts()}] [Dedalus API] machines.retrieve {machine_id[:12]} ({role_label})")
                machine = await client.machines.retrieve(machine_id=machine_id)
                phase = machine.status.phase if machine.status else "unknown"
            except Exception as e:
                log.append(f"[{_ts()}] Status check failed: {e}")
                return False

            if phase != last_phase:
                log.append(f"[{_ts()}] {role_label} machine phase: {phase}")
                print(f"  [Swarm] {role_label} ({machine_id[:12]}) → {phase}")
                last_phase = phase

            if phase == "running":
                return True

            if phase == "sleeping":
                try:
                    revision = machine.status.revision if machine.status else ""
                    log.append(f"[{_ts()}] [Dedalus API] machines.wake {machine_id[:12]}")
                    await client.machines.wake(machine_id=machine_id, if_match=revision)
                    log.append(f"[{_ts()}] Wake signal sent to {role_label} machine")
                    print(f"  [Swarm] {role_label}: wake signal sent to {machine_id[:12]}")
                except Exception as e:
                    log.append(f"[{_ts()}] Wake failed: {e}")

            elif phase in ("failed", "destroyed", "destroying"):
                details = _dump_machine_status(machine)
                log.append(f"[{_ts()}] {role_label} machine TERMINAL phase={phase} — {json.dumps(details)}")
                print(f"  [Swarm] {role_label}: machine {machine_id[:12]} terminal ({phase}) — clearing swarm cache")
                print(f"  [Swarm] Status details: {details}")
                clear_swarm_machine(role)
                return False

            await asyncio.sleep(_MACHINE_POLL_INTERVAL_S)

        log.append(f"[{_ts()}] {role_label} machine did not reach running state within {_MACHINE_READY_TIMEOUT_S:.0f}s")
        print(f"  [Swarm] {role_label}: timeout waiting for {machine_id[:12]}")
        return False

    async def _write_artifact(
        self, machine_id: str, role: str, filename: str, data: dict, log: list[str]
    ) -> bool:
        """Write JSON artifact to /workspace/<filename> on machine. Returns True on success."""
        client = self._get_client()
        role_label = ROLE_LABELS.get(role, role)
        try:
            payload = json.dumps(data, default=str)
            log.append(f"[{_ts()}] [Dedalus API] executions.create stdin→/workspace/{filename} ({len(payload)}B) on {role_label}")
            execution = await client.machines.executions.create(
                machine_id=machine_id,
                command=["bash", "-c", f"mkdir -p /workspace && cat > /workspace/{filename}"],
                stdin=payload,
                timeout_ms=15_000,
            )
            log.append(f"[{_ts()}] [Dedalus API] ✓ Artifact /workspace/{filename} stored on {role_label} machine (exec {execution.execution_id[:12]})")
            print(f"  [Swarm] {role_label}: artifact /workspace/{filename} stored")
            return True
        except Exception as e:
            log.append(f"[{_ts()}] Artifact write FAILED ({filename}): {e}")
            print(f"  [Swarm] {role_label}: artifact write FAILED {filename}: {e}")
            return False

    # ------------------------------------------------------------------
    # Main execute entrypoint
    # ------------------------------------------------------------------

    async def execute(
        self,
        run: AgentRun,
        fn: Callable[[AgentRun], Awaitable[dict]],
    ) -> AgentRun:
        client = self._get_client()
        if not client:
            return await self._local_fallback(run, fn)

        role = AGENT_ROLE_MAP.get(run.agent_type, "situation")
        role_label = ROLE_LABELS.get(role, role)
        is_k2_reasoning = role in K2_REASONING_ROLES

        run.status = AgentStatus.RUNNING
        run.started_at = datetime.utcnow()
        log = run.log_entries

        engine_note = "K2 Think V2 — deep multi-step reasoning" if is_k2_reasoning else "K2 Think V2"
        log.append(f"[{_ts()}] Unit: {role_label} | Engine: {engine_note} | Agent: {run.agent_type}")

        machine_id: str | None = None
        is_machine_healthy = False

        try:
            # 1. Get or create the swarm machine for this role
            machine_id, is_new = await self._get_or_create_swarm_machine(role, log)
            run.machine_id = machine_id
            state_note = "created" if is_new else "resumed"
            log.append(f"[{_ts()}] Swarm machine {state_note}: {machine_id} (role={role})")
            save_agent_run(run)

            # 2. Wait for running state
            log.append(f"[{_ts()}] Waiting for {role_label} machine to reach running state…")
            is_machine_healthy = await self._wait_for_running(machine_id, role, log)

            if is_machine_healthy:
                run.runtime = "dedalus"
                # 3. Persist input artifact
                input_file = f"{run.agent_type}_input_v{run.plan_version}.json"
                await self._write_artifact(machine_id, role, input_file, {
                    "run_id": run.id,
                    "incident_id": run.incident_id,
                    "agent_type": run.agent_type,
                    "plan_version": run.plan_version,
                    "role": role,
                    "engine": engine_note,
                    "input_snapshot": run.input_snapshot,
                }, log)
            else:
                run.runtime = "dedalus_degraded"
                log.append(
                    f"[{_ts()}] {role_label} machine not running — runtime=dedalus_degraded "
                    f"(machine {machine_id[:12]} assigned; LLM executes locally; artifacts deferred)"
                )

            # 4. Execute agent function (LLM call via K2 Think V2)
            engine_tag = " [K2 Think V2 reasoning]" if is_k2_reasoning else ""
            log.append(f"[{_ts()}] {run.agent_type}{engine_tag} LLM call start (runtime={run.runtime})")
            save_agent_run(run)

            result = await fn(run)

            run.output_artifact = result
            run.status = AgentStatus.COMPLETED
            run.completed_at = datetime.utcnow()
            log.append(f"[{_ts()}] {run.agent_type} LLM call complete")

            # 5. Persist output artifact
            if is_machine_healthy:
                output_file = f"{run.agent_type}_output_v{run.plan_version}.json"
                await self._write_artifact(machine_id, role, output_file, {
                    "run_id": run.id,
                    "agent_type": run.agent_type,
                    "plan_version": run.plan_version,
                    "role": role,
                    "output": result,
                }, log)
                log.append(f"[{_ts()}] {role_label} machine state updated (v{run.plan_version} artifacts stored)")

        except Exception as e:
            run.status = AgentStatus.FAILED
            run.completed_at = datetime.utcnow()
            run.error_message = str(e)
            log.append(f"[{_ts()}] FAILED: {e}")
            log.append(traceback.format_exc())

        save_agent_run(run)
        return run

    # ------------------------------------------------------------------
    # Local fallback
    # ------------------------------------------------------------------

    async def _local_fallback(self, run: AgentRun, fn: Callable) -> AgentRun:
        run.runtime = "local"
        run.status = AgentStatus.RUNNING
        run.started_at = datetime.utcnow()
        run.log_entries.append(f"[{_ts()}] DEDALUS_API_KEY not configured — running locally")
        save_agent_run(run)
        try:
            result = await fn(run)
            run.output_artifact = result
            run.status = AgentStatus.COMPLETED
            run.completed_at = datetime.utcnow()
            run.log_entries.append(f"[{_ts()}] Completed (local runtime)")
        except Exception as e:
            run.status = AgentStatus.FAILED
            run.completed_at = datetime.utcnow()
            run.error_message = str(e)
            run.log_entries.append(f"[{_ts()}] FAILED: {e}")
            run.log_entries.append(traceback.format_exc())
        save_agent_run(run)
        return run
