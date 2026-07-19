from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_platform_component(
    name: str,
    status: str,
    data: Any = None,
    *,
    source: str,
    public: bool = True,
    reason: str | None = None,
) -> dict[str, Any]:
    component = {
        "name": str(name),
        "status": str(status),
        "source": str(source),
        "public": bool(public),
        "data": data,
    }

    if reason:
        component["reason"] = str(reason)

    return component


def build_platform_response(
    *,
    platform: str,
    status: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": str(status),
        "platform": str(platform),
        "generated_at": utc_now_iso(),
        "data": data,
    }
