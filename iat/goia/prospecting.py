"""Machine-readable passive prospecting source policy.

This registry describes discovery sources only. It never sends outreach and
does not grant permission to crawl a source outside its published policies.
"""

from __future__ import annotations

from typing import Any
import os
import time

import requests

from iat.goia.repository import upsert_external_prospect

_last_refresh_at = 0


_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "source_id": "huggingface_spaces",
        "host": "huggingface.co",
        "kind": "public_catalog_api",
        "entrypoint": "https://huggingface.co/api/spaces",
        "collection_mode": "passive_review_only",
        "requires_provider_opt_in": False,
        "outreach_enabled": False,
        "rate_limit_required": True,
    },
    {
        "source_id": "github_public_repositories",
        "host": "github.com",
        "kind": "public_repository_search",
        "entrypoint": "https://api.github.com/search/repositories",
        "collection_mode": "passive_review_only",
        "requires_provider_opt_in": False,
        "outreach_enabled": False,
        "rate_limit_required": True,
    },
    {
        "source_id": "mcp_catalog",
        "host": "mcpcatalog.dev",
        "kind": "public_agent_catalog",
        "entrypoint": "https://mcpcatalog.dev/servers",
        "collection_mode": "passive_review_only",
        "requires_provider_opt_in": False,
        "outreach_enabled": False,
        "rate_limit_required": True,
    },
)


def public_prospecting_sources() -> list[dict[str, Any]]:
    return [dict(source) for source in _SOURCES]


def prospecting_policy() -> dict[str, Any]:
    return {
        "status": "passive_discovery_only",
        "outreach_enabled": False,
        "provider_contact_requires_explicit_opt_in": True,
        "autonomous_review_required": True,
        "sources": public_prospecting_sources(),
    }


def refresh_public_prospects(limit: int = 10) -> dict[str, Any]:
    """Collect bounded public directory metadata; never sends outreach."""
    if os.getenv("IAT_GOIA_PUBLIC_DISCOVERY_ENABLED", "false").lower() != "true":
        return {"status": "disabled", "stored_count": 0, "outreach_triggered": False}
    global _last_refresh_at
    now = int(time.time())
    interval = max(300, min(int(os.getenv("IAT_GOIA_PUBLIC_DISCOVERY_INTERVAL_SECONDS", "900")), 86400))
    if now - _last_refresh_at < interval:
        return {"status": "throttled", "stored_count": 0, "outreach_triggered": False}
    _last_refresh_at = now
    bounded = max(1, min(int(limit), 20))
    stored = []
    headers = {"User-Agent": "GOIABot/0.1 (+https://iatprotocol.com)"}
    try:
        github = requests.get(
            "https://api.github.com/search/repositories",
            params={"q": "topic:ai-agent", "sort": "updated", "per_page": bounded},
            headers=headers, timeout=10,
        )
        github.raise_for_status()
        for item in github.json().get("items", []):
            stored.append(upsert_external_prospect({
                "source_id": "github_public_repositories",
                "source_url": item.get("html_url"),
                "name": item.get("full_name"),
                "description": item.get("description") or "Public AI agent repository",
                "observed_at": int(time.time()),
                "kind": "public_repository",
            }))
    except (requests.RequestException, ValueError):
        pass
    try:
        spaces = requests.get(
            "https://huggingface.co/api/spaces",
            params={"limit": bounded, "sort": "lastModified", "direction": -1},
            headers=headers, timeout=10,
        )
        spaces.raise_for_status()
        for item in spaces.json()[:bounded]:
            slug = item.get("id")
            if not slug:
                continue
            stored.append(upsert_external_prospect({
                "source_id": "huggingface_spaces",
                "source_url": f"https://huggingface.co/spaces/{slug}",
                "name": slug,
                "description": item.get("description") or "Public Hugging Face Space",
                "observed_at": int(time.time()),
                "kind": "public_space",
            }))
    except (requests.RequestException, ValueError):
        pass
    return {"status": "ok", "stored_count": len(stored), "outreach_triggered": False}
