from __future__ import annotations

from typing import Any

from iat.platform.config import PLATFORM_VERSION, platform_enabled
from iat.platform.models import build_platform_response


SENSITIVE_KEYS = {
    "api_key",
    "seller_api_key",
    "x_api_key",
    "secret",
    "buyer_secret",
    "session_secret",
    "access_token",
    "refresh_token",
    "token",
    "private_key",
    "private_key_bytes",
    "seed",
    "mnemonic",
    "password",
    "authorization",
    "cookie",
    "raw_prompt",
    "buyer_raw_prompt",
    "prompt",
    "query",
    "goal",
    "messages",
    "requirements",
    "buyer_context",
    "foundation_context",
    "execution_context",
    "delivery_result",
    "internal_result",
    "evidence_package",
}


def sanitize_public_value(value: Any) -> Any:
    """
    Recursively remove protocol secrets from Platform responses.

    This is a defensive serializer only. It does not replace the authority
    and access-control rules of the protocol.
    """
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}

        for key, nested_value in value.items():
            normalized_key = str(key).strip().lower()

            if normalized_key in SENSITIVE_KEYS:
                continue

            sanitized[str(key)] = sanitize_public_value(nested_value)

        return sanitized

    if isinstance(value, list):
        return [sanitize_public_value(item) for item in value]

    if isinstance(value, tuple):
        return [sanitize_public_value(item) for item in value]

    return value


def build_public_platform_status(
    *,
    explorer_available: bool,
    stream_available: bool,
) -> dict[str, Any]:
    enabled = platform_enabled()

    return build_platform_response(
        platform=PLATFORM_VERSION,
        status="online" if enabled else "disabled",
        data={
            "enabled": enabled,
            "authority": "iat_foundation",
            "business_logic": False,
            "read_only": True,
            "capabilities": {
                "explorer": bool(explorer_available),
                "event_stream": bool(stream_available),
                "buyer_platform": False,
                "seller_platform": False,
                "developer_platform": False,
            },
        },
    )
