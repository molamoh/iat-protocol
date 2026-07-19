from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from iat.platform.events import list_public_protocol_events


def iterate_protocol_events(limit: int | None = None) -> Iterator[dict[str, Any]]:
    """
    Initial synchronous stream adapter.

    WebSocket/SSE transport will consume this adapter later without changing
    the underlying Runtime Event Bus.
    """
    result = list_public_protocol_events(limit=limit)

    for event in result.get("events") or []:
        if isinstance(event, dict):
            yield event
