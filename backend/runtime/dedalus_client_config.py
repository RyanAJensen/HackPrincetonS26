"""Shared Dedalus client configuration helpers."""
from __future__ import annotations

import os
from typing import Optional


DEDALUS_PROVIDER_ENV_VARS = (
    "DEDALUS_PROVIDER",
    "DEDALUS_PROVIDER_KEY",
    "DEDALUS_PROVIDER_MODEL",
)

MACHINE_WORKER_ENV_VARS = (
    "K2_API_KEY",
    "K2_API_URL",
    "K2_MODEL",
    "LLM_BACKEND",
    *DEDALUS_PROVIDER_ENV_VARS,
)


def build_dedalus_client_kwargs(api_key: Optional[str] = None) -> dict[str, str]:
    """Build AsyncDedalus kwargs from standard env vars, including BYOK settings."""
    kwargs: dict[str, str] = {}
    resolved_api_key = api_key or os.getenv("DEDALUS_API_KEY")
    if resolved_api_key:
        kwargs["api_key"] = resolved_api_key

    provider = os.getenv("DEDALUS_PROVIDER")
    provider_key = os.getenv("DEDALUS_PROVIDER_KEY")
    provider_model = os.getenv("DEDALUS_PROVIDER_MODEL")

    if provider:
        kwargs["provider"] = provider
    if provider_key:
        kwargs["provider_key"] = provider_key
    if provider_model:
        kwargs["provider_model"] = provider_model

    return kwargs


def dedalus_byok_configured() -> bool:
    return bool(os.getenv("DEDALUS_PROVIDER_KEY"))


def k2_configured() -> bool:
    return bool(os.getenv("K2_API_KEY"))


def preferred_remote_reasoning_backend() -> str:
    backend = (os.getenv("LLM_BACKEND") or "").strip().lower()
    if backend == "k2":
        return "k2"
    if backend == "dedalus":
        return "dedalus"
    if k2_configured():
        return "k2"
    if dedalus_byok_configured():
        return "dedalus"
    return "dedalus"


def swarm_enrichment_backend_ready() -> bool:
    backend = preferred_remote_reasoning_backend()
    if backend == "k2":
        return k2_configured()
    return dedalus_byok_configured()


def describe_dedalus_billing_mode() -> str:
    if dedalus_byok_configured():
        provider = os.getenv("DEDALUS_PROVIDER") or "provider inferred from model"
        return f"BYOK via {provider}"
    return "Dedalus-managed API credits"


def describe_swarm_reasoning_mode() -> str:
    backend = preferred_remote_reasoning_backend()
    if backend == "k2":
        model = os.getenv("K2_MODEL") or "MBZUAI-IFM/K2-Think-v2"
        return f"K2 Think V2 ({model})"
    if dedalus_byok_configured():
        provider = os.getenv("DEDALUS_PROVIDER") or "provider inferred from model"
        model = os.getenv("DEDALUS_PROVIDER_MODEL") or os.getenv("DEDALUS_MODEL") or "provider model"
        return f"Dedalus Runner via {provider} ({model})"
    model = os.getenv("DEDALUS_MODEL") or "Dedalus-managed model"
    return f"Dedalus Runner via managed credits ({model})"


def machine_worker_env_lines(api_key: str) -> str:
    """Build the remote `.env` content needed by the machine worker."""
    lines = [f"DEDALUS_API_KEY={api_key}"]
    backend = (os.getenv("LLM_BACKEND") or "").strip().lower()
    if backend:
        lines.append(f"LLM_BACKEND={backend}")
    elif os.getenv("K2_API_KEY"):
        # Prefer K2 on Machines when it is available so swarm reasoning remains
        # Dedalus-hosted while K2 stays a first-class part of the product.
        lines.append("LLM_BACKEND=k2")
    for key in MACHINE_WORKER_ENV_VARS:
        if key == "LLM_BACKEND":
            continue
        value = os.getenv(key)
        if value:
            lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"
