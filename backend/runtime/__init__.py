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
        return DedalusMachineSwarmRuntime()
    return DedalusAgentRuntime()
