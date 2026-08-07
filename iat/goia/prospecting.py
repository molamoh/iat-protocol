"""Machine-readable passive prospecting source policy.

This registry describes discovery sources only. It never sends outreach and
does not grant permission to crawl a source outside its published policies.
"""

from __future__ import annotations

from typing import Any


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
