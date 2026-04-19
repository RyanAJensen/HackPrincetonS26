import os
from runtime.base import AgentRuntime
from runtime.local_runtime import LocalAgentRuntime
from runtime.dedalus_runtime import DedalusAgentRuntime
from runtime.dedalus_machine_runtime import DedalusMachineSwarmRuntime


def get_runtime() -> AgentRuntime:
    """Return the runtime selected by RUNTIME_MODE."""
    runtime_mode = os.getenv("RUNTIME_MODE", "dedalus")
    if runtime_mode == "local":
        return LocalAgentRuntime()
    if runtime_mode == "swarm":
        try:
            return DedalusMachineSwarmRuntime()
        except Exception as e:
            print(f"[Runtime] Swarm init failed ({e}); falling back to local K2")
            return LocalAgentRuntime()
    try:
        return DedalusAgentRuntime()
    except Exception as e:
        print(f"[Runtime] Dedalus init failed ({e}); falling back to local K2")
        return LocalAgentRuntime()
