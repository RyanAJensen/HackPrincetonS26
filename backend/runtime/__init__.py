import os
from runtime.base import AgentRuntime
from runtime.local_runtime import LocalAgentRuntime
from runtime.dedalus_runtime import DedalusAgentRuntime


def get_runtime() -> AgentRuntime:
    """Return DedalusAgentRuntime (falls back to local if unconfigured) or LocalAgentRuntime."""
    if os.getenv("RUNTIME_MODE", "dedalus") == "local":
        return LocalAgentRuntime()
    return DedalusAgentRuntime()
