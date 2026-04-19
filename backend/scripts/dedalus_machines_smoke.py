from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")
os.environ.setdefault("DEDALUS_DCS_DEBUG", "true")
os.environ.setdefault("DEDALUS_MACHINE_COMMAND_TRANSPORT", "ssh")

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agents.schemas import LeanParserOutput, LeanPlannerOutput, ReplanContextOutput
from runtime.dedalus_dcs import DedalusMachinesClient
from runtime.dedalus_machine_runtime import DedalusMachineSwarmRuntime


async def main() -> int:
    api_key = os.getenv("DEDALUS_API_KEY")
    if not api_key:
        print("[machines-smoke] DEDALUS_API_KEY is not set")
        return 1

    client = DedalusMachinesClient(api_key)
    desired_vcpu = float(os.getenv("DEDALUS_MACHINE_VCPU", "1.0"))
    desired_memory_mib = int(os.getenv("DEDALUS_MACHINE_MEMORY_MIB", "1024"))
    desired_storage_gib = int(os.getenv("DEDALUS_MACHINE_STORAGE_GIB", "10"))
    machines = await client.list_machines()
    print(f"[machines-smoke] visible machines={len(machines)}")
    for machine in machines[:4]:
        phase = machine.status.phase if machine.status else "unknown"
        print(f"[machines-smoke] {machine.machine_id} phase={phase} vcpu={machine.vcpu}")

    runtime = DedalusMachineSwarmRuntime()
    machine_id = os.getenv("DEDALUS_MACHINE_ID")
    if not machine_id:
        machine_id = await runtime._adopt_existing_machine("Smoke Probe", exclude_machine_ids=set())
    print(
        f"[machines-smoke] command_transport={client.command_transport} "
        f"ssh_material_dir={client._ssh_material_dir}"
    )
    async def _create_machine() -> str:
        print(
            "[machines-smoke] Creating a worker machine "
            f"({desired_vcpu} vCPU / {desired_memory_mib} MiB / {desired_storage_gib} GiB)"
        )
        try:
            created = await client.create_machine(
                vcpu=desired_vcpu,
                memory_mib=desired_memory_mib,
                storage_gib=desired_storage_gib,
            )
        except Exception as exc:
            detail = str(exc)
            if "MACHINE_QUOTA_EXCEEDED" not in detail and "machine quota exceeded" not in detail:
                raise
            adopted = await runtime._adopt_existing_machine("Smoke Probe", exclude_machine_ids=set())
            if adopted is not None:
                print(f"[machines-smoke] adopted existing machine_id={adopted} after quota exceeded")
                return adopted
            raise
        ready = await client.wait_for_machine_phase(created.machine_id, timeout_s=180)
        print(f"[machines-smoke] created machine_id={ready.machine_id}")
        return ready.machine_id

    if not machine_id:
        machine_id = await _create_machine()
    else:
        print(f"[machines-smoke] using machine_id={machine_id}")

    print(f"[machines-smoke] waiting for command readiness machine_id={machine_id}")
    try:
        probe_elapsed = await runtime.wait_for_machine_command_ready(
            machine_id,
            timeout_s=min(runtime.command_ready_timeout_s, max(15.0, runtime.reuse_probe_max_s + 3.0)),
        )
        if probe_elapsed > runtime.reuse_probe_max_s:
            print(
                f"[machines-smoke] reused machine command probe too slow "
                f"({probe_elapsed:.1f}s > {runtime.reuse_probe_max_s:.1f}s); creating fresh machine"
            )
            machine_id = await _create_machine()
            print(f"[machines-smoke] waiting for command readiness machine_id={machine_id}")
            await runtime.wait_for_machine_command_ready(
                machine_id,
                timeout_s=max(runtime.command_ready_timeout_s, runtime.machine_ready_timeout_s),
            )
    except Exception as exc:
        print(f"[machines-smoke] machine_id={machine_id} not command-ready: {exc}")
        machine_id = await _create_machine()
        print(f"[machines-smoke] waiting for command readiness machine_id={machine_id}")
        await runtime.wait_for_machine_command_ready(
            machine_id,
            timeout_s=max(runtime.command_ready_timeout_s, runtime.machine_ready_timeout_s),
        )
    output = await client.run_command(machine_id, ["pwd"], timeout_s=60)
    print(
        f"[machines-smoke] execution machine_id={machine_id} "
        f"stdout={output.stdout.strip()!r} stderr={(output.stderr or '').strip()!r}"
    )

    print(f"[machines-smoke] checking worker health machine_id={machine_id}")
    worker = await runtime.run_worker_healthcheck(machine_id)
    print(
        "[machines-smoke] worker health "
        f"machine_id={machine_id} ok={worker.get('ok')} "
        f"llm_backend={worker.get('llm_backend')} "
        f"k2_api_key_present={worker.get('k2_api_key_present')} "
        f"dedalus_sdk_available={worker.get('dedalus_sdk_available')} "
        f"pydantic_available={worker.get('pydantic_available')} "
        f"provider_key_present={worker.get('provider_key_present')}"
    )

    if worker.get("llm_backend") == "k2" and worker.get("k2_api_key_present"):
        print(f"[machines-smoke] running structured K2 probe machine_id={machine_id}")
        llm_stdout = await runtime.run_prompt_on_machine(
            machine_id=machine_id,
            prompt=(
                "Update: Washington Road bridge is closed to ambulances. "
                "Return a replan context marking routing and transport affected."
            ),
            system="Return only the requested structured JSON.",
            caller="machines_smoke",
            response_model=ReplanContextOutput,
            timeout_seconds=45,
        )
        print(f"[machines-smoke] K2 probe result {llm_stdout.strip()!r}")

        print(f"[machines-smoke] running lean parser probe machine_id={machine_id}")
        parser_stdout = await runtime.run_prompt_on_machine(
            machine_id=machine_id,
            prompt=(
                "Incident type: Flash flood / mass casualty\n"
                "Location: Washington Road at Lake Carnegie Bridge, Princeton, NJ\n"
                "Report: Four patients involved. One unresponsive elderly female, one head trauma, "
                "two ambulatory on vehicle roofs. Water is rising and bridge access is constrained. "
                "A second surge may arrive in 20 minutes.\n"
                "Resources: 2 ALS units, 1 rescue company, Princeton Medical Center 9 minutes primary, "
                "RWJ 18 minutes alternate."
            ),
            system="Return only the requested structured JSON.",
            caller="machines_smoke_parser",
            response_model=LeanParserOutput,
            timeout_seconds=30,
        )
        print(f"[machines-smoke] lean parser result {parser_stdout.strip()!r}")

        print(f"[machines-smoke] running lean planner probe machine_id={machine_id}")
        planner_stdout = await runtime.run_prompt_on_machine(
            machine_id=machine_id,
            prompt=(
                "Decision state:\n"
                "Patients: total=4 critical=1 moderate=1 minor=2\n"
                "Hazards: floodwater, vehicle entrapment, bridge access constraint\n"
                "Primary route: Washington Rd westbound to Princeton Medical Center, 9 min\n"
                "Alternate route: Harrison St detour, 14 min\n"
                "Hospitals: Princeton Medical Center (Trauma II), Robert Wood Johnson (Trauma I)\n"
                "Need concise operations plan with facility assignments and immediate actions."
            ),
            system="Return only the requested structured JSON.",
            caller="machines_smoke_planner",
            response_model=LeanPlannerOutput,
            timeout_seconds=30,
        )
        print(f"[machines-smoke] lean planner result {planner_stdout.strip()!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
