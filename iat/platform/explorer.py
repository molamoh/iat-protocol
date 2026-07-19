from __future__ import annotations

from typing import Any, Callable

from iat.platform.config import EXPLORER_VERSION, normalize_event_limit
from iat.platform.events import list_public_protocol_events
from iat.platform.gateway import sanitize_public_value
from iat.platform.models import build_platform_component, build_platform_response


Provider = Callable[[], Any]


def _read_component(
    name: str,
    provider: Provider | None,
    *,
    source: str,
) -> dict[str, Any]:
    if provider is None:
        return build_platform_component(
            name=name,
            status="unavailable",
            data=None,
            source=source,
            reason="provider_not_connected",
        )

    try:
        raw_data = provider()

        return build_platform_component(
            name=name,
            status="online",
            data=sanitize_public_value(raw_data),
            source=source,
        )
    except Exception as exc:
        return build_platform_component(
            name=name,
            status="degraded",
            data=None,
            source=source,
            reason=f"{type(exc).__name__}: {exc}",
        )


def build_protocol_explorer_snapshot(
    *,
    network_provider: Provider | None = None,
    stats_provider: Provider | None = None,
    marketplace_provider: Provider | None = None,
    orders_provider: Provider | None = None,
    event_limit: int | None = None,
) -> dict[str, Any]:
    """
    Build one read-only public snapshot from existing protocol providers.

    Providers are injected to avoid circular imports and to preserve the
    authority of the existing protocol modules.
    """
    normalized_event_limit = normalize_event_limit(event_limit)

    components = {
        "network": _read_component(
            "network",
            network_provider,
            source="existing_network_status",
        ),
        "economy": _read_component(
            "economy",
            stats_provider,
            source="existing_stats",
        ),
        "marketplace": _read_component(
            "marketplace",
            marketplace_provider,
            source="existing_marketplace",
        ),
        "orders": _read_component(
            "orders",
            orders_provider,
            source="existing_orders",
        ),
        "events": _read_component(
            "events",
            lambda: list_public_protocol_events(normalized_event_limit),
            source="iat_action_runtime_event_bus_v1",
        ),
    }

    component_statuses = {
        component.get("status")
        for component in components.values()
    }

    if component_statuses == {"online"}:
        explorer_status = "online"
    elif "online" in component_statuses:
        explorer_status = "degraded"
    else:
        explorer_status = "unavailable"

    return build_platform_response(
        platform=EXPLORER_VERSION,
        status=explorer_status,
        data={
            "read_only": True,
            "authority": "iat_foundation",
            "components": components,
        },
    )
