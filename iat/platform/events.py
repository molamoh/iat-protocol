from __future__ import annotations

from typing import Any

from iat.action_engine.runtime_event_bus import inspect_runtime_event_bus
from iat.platform.config import normalize_event_limit
from iat.platform.gateway import sanitize_public_value


def list_public_protocol_events(limit: int | None = None) -> dict[str, Any]:
    """
    Public read-only adapter over the existing Action Runtime Event Bus.

    No second event bus is created here.
    """
    normalized_limit = normalize_event_limit(limit)
    runtime_events = inspect_runtime_event_bus(limit=normalized_limit)

    return sanitize_public_value(
        {
            "status": runtime_events.get("status", "ok"),
            "source": "iat_action_runtime_event_bus_v1",
            "limit": normalized_limit,
            "events": runtime_events.get("recent_events") or [],
        }
    )
