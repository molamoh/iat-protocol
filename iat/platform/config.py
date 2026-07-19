import os


PLATFORM_VERSION = "iat_public_platform_v1"
EXPLORER_VERSION = "iat_protocol_explorer_v1"

DEFAULT_EXPLORER_EVENT_LIMIT = 50
MAX_EXPLORER_EVENT_LIMIT = 200


def platform_enabled() -> bool:
    value = str(os.getenv("IAT_PLATFORM_ENABLED", "true")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def normalize_event_limit(limit: int | None) -> int:
    try:
        normalized = int(limit or DEFAULT_EXPLORER_EVENT_LIMIT)
    except (TypeError, ValueError):
        normalized = DEFAULT_EXPLORER_EVENT_LIMIT

    return max(1, min(normalized, MAX_EXPLORER_EVENT_LIMIT))
