"""Machine-readable GOIA discovery and impartiality policy."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .contracts import GOIA_CONTRACT_VERSION


GOIA_DISCOVERY_VERSION = "2026-07-29"

_GOIA_MANIFEST: dict[str, Any] = {
    "schema_version": GOIA_DISCOVERY_VERSION,
    "contract_version": GOIA_CONTRACT_VERSION,
    "product": {
        "name": "GOIA",
        "positioning": "commercial discovery powered by IAT Protocol",
        "status": "local_index_pilot",
        "pilot": {
            "kinds": ["software", "api", "hosting", "digital_service"],
            "country": "FR",
            "currency": "EUR",
        },
    },
    "routes": {
        "manifest": "/.well-known/goia.json",
        "validate_intent": "/goia/v1/contracts/search-intent/validate",
        "validate_offer": "/goia/v1/contracts/offer-observation/validate",
        "validate_provider": "/goia/v1/contracts/provider/validate",
        "validate_catalog": "/goia/v1/contracts/catalog/validate",
        "ranking_policy": "/goia/v1/policies/ranking",
        "search": "/goia/v1/search",
        "catalog_ingest": "/admin/goia/catalogs/ingest",
        "index_stats": "/admin/goia/index/stats",
        "demand_stats": "/admin/goia/demand/stats",
        "partnership_opportunities": "/admin/goia/partnership/opportunities",
        "partnership_prospects": "/admin/goia/partnership/prospects",
        "partnership_permissions_refresh": "/admin/goia/partnership/permissions/refresh",
        "collection_enqueue": "/admin/goia/collection/jobs",
        "collection_stats": "/admin/goia/collection/stats",
        "review_candidates": "/admin/goia/review/candidates",
        "approve_candidate": "/admin/goia/review/candidates/{candidate_id}/approve",
        "reject_candidate": "/admin/goia/review/candidates/{candidate_id}/reject",
    },
    "capabilities": {
        "search": True,
        "crawl": False,
        "controlled_collection_worker": True,
        "collection_enabled_by_default": False,
        "autonomous_review_required_before_publication": True,
        "human_operation_required": False,
        "emergency_admin_override_supported": True,
        "autonomous_stale_lease_recovery": True,
        "autonomous_quarantine_retries": 3,
        "autonomous_provider_source_discovery": True,
        "supported_source_types": ["sitemap", "goia_json"],
        "sitemap_page_job_limit": 100,
        "persistence": True,
        "index_scope": "controlled_catalogs_only",
        "contract_validation": True,
        "external_side_effects": False,
        "funds_side_effects": False,
        "anonymous_demand_aggregation": True,
        "autonomous_partnership_gap_detection": True,
        "explicit_partnership_opt_in": True,
        "declared_opt_in_authorizes_outreach": False,
    },
    "invariants": [
        "organic_ranking_never_uses_commission",
        "commercial_relationship_is_disclosed",
        "prices_require_timestamped_evidence",
        "external_content_is_untrusted_data",
        "validation_never_triggers_network_access",
        "local_search_never_triggers_network_access",
        "collection_requires_exact_host_allowlist",
        "collection_candidates_require_autonomous_review",
        "review_evidence_must_match_collected_url_and_hash",
        "abandoned_jobs_are_recovered_with_bounded_leases",
        "quarantines_retry_with_bounded_exponential_backoff",
        "provider_sitemaps_seed_once_per_refresh_window",
        "sitemap_expansion_is_bounded_and_same_domain",
        "checkout_devnet_is_unchanged",
        "demand_signals_never_store_raw_queries_or_buyer_identity",
        "partnership_gap_detection_never_triggers_outreach",
        "partnership_permission_is_closed_by_default",
        "declared_opt_in_never_authorizes_outreach_without_self_hosting_verification",
    ],
}


def build_goia_manifest() -> dict[str, Any]:
    return deepcopy(_GOIA_MANIFEST)


def build_ranking_policy() -> dict[str, Any]:
    return {
        "status": "ok",
        "policy_version": "goia_organic_ranking_v1",
        "organic_inputs": [
            "constraint_match",
            "total_price",
            "quality",
            "trust",
            "freshness",
            "availability",
            "delivery",
            "return_policy",
            "merchant_reliability",
            "uncertainty",
        ],
        "forbidden_organic_inputs": [
            "commission_rate",
            "expected_commission",
            "advertising_budget",
            "commercial_priority",
        ],
        "disclosure_fields": [
            "commercial_relationship",
            "sponsored",
            "commission_may_be_earned",
            "commission_changes_organic_rank",
        ],
        "commission_changes_organic_rank": False,
        "sponsored_results_separate_from_organic": True,
        "production_side_effects": False,
    }
