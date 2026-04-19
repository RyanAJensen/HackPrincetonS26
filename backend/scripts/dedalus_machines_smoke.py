from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.dedalus_dcs import DedalusMachinesClient


async def main() -> int:
    api_key = os.getenv("DEDALUS_API_KEY")
    if not api_key:
        print("[machines-smoke] DEDALUS_API_KEY is not set")
        return 1

    client = DedalusMachinesClient(api_key)
    machines = await client.list_machines()
    print(f"[machines-smoke] visible machines={len(machines)}")
    for machine in machines[:4]:
        phase = machine.status.phase if machine.status else "unknown"
        print(f"[machines-smoke] {machine.machine_id} phase={phase} vcpu={machine.vcpu}")

    machine_id = os.getenv("DEDALUS_MACHINE_ID") or (machines[0].machine_id if machines else None)
    if not machine_id:
        print("[machines-smoke] No machine available for execution smoke")
        return 0

    output = await client.run_command(machine_id, ["pwd"], timeout_s=60)
    print(f"[machines-smoke] execution machine_id={machine_id} stdout={output.stdout.strip()!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
