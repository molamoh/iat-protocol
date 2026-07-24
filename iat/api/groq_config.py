"""Groq model configuration shared by every IAT intelligence workflow."""

from __future__ import annotations

import os
from typing import Any


GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"

# Keep this mapping after the provider shutdown date: an old Render variable must
# not silently route production traffic to a retired model.
GROQ_MODEL_REPLACEMENTS = {
    "llama-3.1-8b-instant": DEFAULT_GROQ_MODEL,
}

_GPT_OSS_REASONING_EFFORTS = {"low", "medium", "high"}


def configured_groq_model() -> str:
    """Return the configured model name, before compatibility migration."""
    return (os.getenv("GROQ_MODEL") or DEFAULT_GROQ_MODEL).strip() or DEFAULT_GROQ_MODEL


def effective_groq_model() -> str:
    """Return a production-safe model, upgrading known retired model IDs."""
    configured = configured_groq_model()
    return GROQ_MODEL_REPLACEMENTS.get(configured, configured)


def groq_json_request(
    messages: list[dict[str, str]],
    *,
    temperature: float,
) -> dict[str, Any]:
    """Build a JSON-mode chat request compatible with the active Groq model."""
    model = effective_groq_model()
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }

    if model.startswith("openai/gpt-oss-"):
        effort = (os.getenv("GROQ_REASONING_EFFORT") or "low").strip().lower()
        if effort not in _GPT_OSS_REASONING_EFFORTS:
            effort = "low"
        payload["reasoning_effort"] = effort
        # Groq requires parsed or hidden reasoning when JSON mode is enabled.
        payload["reasoning_format"] = "hidden"

    return payload


def groq_model_status() -> dict[str, Any]:
    """Expose safe diagnostics without leaking the Groq API key."""
    configured = configured_groq_model()
    effective = effective_groq_model()
    return {
        "configured_model": configured,
        "effective_model": effective,
        "automatically_migrated": configured != effective,
        "api_key_configured": bool(os.getenv("GROQ_API_KEY")),
    }
