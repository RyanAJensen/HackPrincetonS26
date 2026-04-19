"""Shared Dedalus client configuration helpers."""
from __future__ import annotations

import os
from typing import Optional


DEDALUS_PROVIDER_ENV_VARS = (
    "DEDALUS_PROVIDER",
    "DEDALUS_PROVIDER_KEY",
    "DEDALUS_PROVIDER_MODEL",
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


def describe_dedalus_billing_mode() -> str:
    if dedalus_byok_configured():
        provider = os.getenv("DEDALUS_PROVIDER") or "provider inferred from model"
        return f"BYOK via {provider}"
    return "Dedalus-managed API credits"


def machine_worker_env_lines(api_key: str) -> str:
    """Build the remote `.env` content needed by the machine worker."""
    lines = [f"DEDALUS_API_KEY={api_key}"]
    for key in DEDALUS_PROVIDER_ENV_VARS:
        value = os.getenv(key)
        if value:
            lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"
