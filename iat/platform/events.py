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
    recent_events = runtime_events.get("recent_events") or []

    if isinstance(recent_events, dict):
        normalized_events = []

        for event_id, event in recent_events.items():
            if not isinstance(event, dict):
                continue

            normalized_event = dict(event)
            normalized_event.setdefault("event_id", str(event_id))
            normalized_events.append(normalized_event)
    elif isinstance(recent_events, (list, tuple)):
        normalized_events = [
            dict(event)
            for event in recent_events
            if isinstance(event, dict)
        ]
    else:
        normalized_events = []

    return sanitize_public_value(
        {
            "status": runtime_events.get("status", "ok"),
            "source": "iat_action_runtime_event_bus_v1",
            "limit": normalized_limit,
            "events": normalized_events,
        }
    )
