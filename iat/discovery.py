"""Machine-readable discovery contracts for AI clients."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from iat.config import IAT_NETWORK, IAT_VERSION


DISCOVERY_VERSION = "2026-07-01"

_MANIFEST: dict[str, Any] = {
    "schema_version": DISCOVERY_VERSION,
    "protocol": {
        "name": "IAT Protocol",
        "version": IAT_VERSION,
        "description": "Economic execution and settlement protocol for autonomous agents",
        "status": "advanced_prototype",
    },
    "discovery": {
        "manifest": "/.well-known/iat.json",
        "capabilities": "/v1/capabilities",
        "openapi": "/openapi-public.json",
        "llms": "/llms.txt",
    },
    "buyer": {
        "dashboard": "/buyer/dashboard",
        "services": "/services",
        "create_order": "/create-order",
        "verify_payment": "/buyer/verify-payment",
        "wallet_auth_challenge": "/payments/v1/universal/wallet-auth/challenge",
        "wallet_auth_session": "/payments/v1/universal/wallet-auth/session",
        "purchase_policy": "/payments/v1/universal/buyer/purchase-policy",
        "intent_preview": "/payments/v1/universal/buyer/intents/preview",
        "intent_commit": "/payments/v1/universal/buyer/intents/commit",
        "intent_checkout_prepare": "/payments/v1/universal/buyer/intents/checkout/prepare",
        "intent_checkout_submit": "/payments/v1/universal/buyer/intents/checkout/submit",
        "intent_checkout_confirm": "/payments/v1/universal/buyer/intents/checkout/confirm",
        "universal_checkout_quote": "/payments/v1/universal/quote",
        "universal_checkout_prepare": "/payments/v1/universal/{quote_id}/prepare",
        "universal_checkout_authorize": "/payments/v1/universal/{quote_id}/authorize",
        "universal_checkout_submit": "/payments/v1/universal/{quote_id}/submit",
        "universal_checkout_confirm": "/payments/v1/universal/{quote_id}/confirm",
        "universal_checkout_deliver": "/payments/v1/universal/{quote_id}/deliver",
        "universal_delivery_destination": "/payments/v1/universal/{quote_id}/delivery-destination",
        "universal_delivery_decision": "/payments/v1/universal/{quote_id}/delivery/decision",
        "universal_checkout_compensation": "/payments/v1/universal/{quote_id}/compensation/request",
        "universal_checkout_status": "/payments/v1/universal/{quote_id}",
    },
    "seller": {
        "discovery": "/seller/v1/discovery",
        "readiness": "/seller/v1/readiness",
        "competitive_intelligence": "/seller/v1/intelligence/analyze",
        "demand_forecast": "/seller/v1/intelligence/demand/forecast",
        "economics": "/seller/v1/economics/estimate",
        "integration_contract": "/seller/v1/integration-contract",
        "register": "/seller/register",
        "register_agent": "/seller/register-agent",
        "catalog": "/seller/catalog/items",
        "dashboard": "/seller/dashboard",
    },
    "sandbox": {
        "offers": "/sandbox/v1/offers",
        "preview": "/sandbox/v1/preview",
        "purchase": "/sandbox/v1/purchase",
        "order": "/sandbox/v1/orders/{order_id}",
        "feedback": "/sandbox/v1/orders/{order_id}/feedback",
        "funds_required": False,
        "production_side_effects": False,
    },
    "intelligence": {
        "simulate_decision": "/intelligence/v1/decisions/simulate",
        "engine_version": "iat_decision_core_v2",
        "policy_version": "iat_decision_policy_v2",
        "explainable": True,
        "production_side_effects": False,
    },
    "growth": {
        "pilot": "/growth/v1/pilot",
        "pilot_method": "POST",
        "pilot_status": "open_on_solana_devnet",
        "invitation_response": "/growth/v1/respond",
        "authentication": "invitation_hmac_token",
        "response_types": [
            "interested",
            "not_interested",
            "needs_info",
            "integrated",
            "opt_out",
        ],
        "maximum_outreach_frequency": "once_per_24_hours",
    },
    "goia": {
        "manifest": "/.well-known/goia.json",
        "prospecting_sources": "/goia/v1/prospecting/sources",
        "prospecting_status": "/goia/v1/prospecting/status",
        "prospecting_review_queue": "/goia/v1/prospecting/review-queue",
        "ranking_policy": "/goia/v1/policies/ranking",
        "validate_search_intent": "/goia/v1/contracts/search-intent/validate",
        "validate_offer_observation": "/goia/v1/contracts/offer-observation/validate",
        "validate_provider": "/goia/v1/contracts/provider/validate",
        "validate_openai_compatible_runtime": "/goia/v1/contracts/runtime/openai-compatible/validate",
        "validate_mcp_runtime": "/goia/v1/contracts/runtime/mcp/validate",
        "reference_runtime_health": "/goia/v1/reference-runtime/health",
        "reference_runtime_models": "/goia/v1/reference-runtime/v1/models",
        "reference_runtime_chat": "/goia/v1/reference-runtime/v1/chat/completions",
        "reference_runtime_auth": "bearer",
        "reference_mcp": "/goia/v1/reference-mcp",
        "reference_mcp_health": "/goia/v1/reference-mcp/health",
        "validate_catalog": "/goia/v1/contracts/catalog/validate",
        "search": "/goia/v1/search",
        "status": "local_index_pilot",
        "search_available": True,
        "crawl_available": False,
        "controlled_collection_worker": True,
        "governance_decisions_audited": True,
        "collection_enabled_by_default": False,
        "autonomous_review_required_before_publication": True,
        "human_operation_required": False,
        "emergency_admin_override_supported": True,
        "autonomous_recovery": True,
        "autonomous_provider_source_discovery": True,
        "anonymous_demand_aggregation": True,
        "autonomous_partnership_gap_detection": True,
        "explicit_partnership_opt_in": True,
        "self_hosted_partnership_verification": True,
        "verified_opt_in_required_for_outreach_authorization": True,
        "autonomous_partnership_proposal_preparation": True,
        "partnership_proposal_delivery_enabled": False,
        "partnership_delivery_lifecycle": True,
        "partnership_delivery_adapter_bundled": True,
        "partnership_transport_signature": "ed25519",
        "partnership_dispatcher_service": True,
        "merchant_opt_out_global_precedence": True,
        "authenticated_merchant_partnership_responses": True,
        "accepted_response_activates_commission": False,
        "accepted_response_changes_ranking": False,
        "structured_partner_prospect_discovery": True,
        "prospect_domains_fetched": False,
        "outreach_triggered": False,
        "index_scope": "controlled_catalogs_only",
        "production_side_effects": False,
    },
    "settlement": {
        "network": "solana",
        "rpc": IAT_NETWORK,
        "asset": "IAT",
        "modes": ["direct", "escrow"],
        "checkout_inputs": "configured_solana_assets",
        "hybrid_routes": ["treasury", "raydium", "fail_closed"],
        "treasury_program": "iat_checkout_v1",
        "atomic_treasury_execution": True,
        "finalized_confirmation_required": True,
        "global_transaction_replay_protection": True,
        "buyer_wallet_signature_required": True,
        "server_custody": False,
    },
    "security": {
        "sandbox_isolation": True,
        "bounded_adaptation": True,
        "self_modifying_code": False,
        "admin_fail_closed": True,
        "human_approval_supported": True,
    },
    "compatibility": {
        "formats": ["application/json"],
        "minimum_python": "3.10",
        "sdk": "iat-protocol",
    },
}


def build_discovery_manifest() -> dict[str, Any]:
    """Return a fresh manifest so callers cannot mutate global protocol state."""
    return deepcopy(_MANIFEST)


def build_capabilities_document() -> dict[str, Any]:
    """Describe stable capabilities and the safety boundary around each one."""
    return {
        "status": "ok",
        "schema_version": DISCOVERY_VERSION,
        "capabilities": [
            {
                "id": "service_discovery",
                "stability": "stable",
                "autonomous": True,
                "side_effects": False,
            },
            {
                "id": "offer_comparison",
                "stability": "stable",
                "autonomous": True,
                "explainable": True,
                "side_effects": False,
            },
            {
                "id": "multi_objective_decision_simulation",
                "stability": "beta",
                "autonomous": True,
                "explainable": True,
                "auditable": True,
                "side_effects": False,
            },
            {
                "id": "sandbox_purchase",
                "stability": "stable",
                "autonomous": True,
                "funds_required": False,
                "production_side_effects": False,
            },
            {
                "id": "production_purchase",
                "stability": "beta",
                "autonomous": True,
                "funds_required": True,
                "human_approval_supported": True,
            },
            {
                "id": "hybrid_universal_checkout",
                "stability": "beta",
                "autonomous": True,
                "routes": ["treasury", "raydium", "fail_closed"],
                "order_bound": True,
                "custodial": False,
                "buyer_wallet_signature_required": True,
            },
            {
                "id": "bounded_reputation_learning",
                "stability": "beta",
                "autonomous": True,
                "sandbox_only": True,
                "self_modifying_code": False,
            },
            {
                "id": "seller_readiness_assessment",
                "stability": "stable",
                "autonomous": True,
                "account_required": False,
                "production_side_effects": False,
            },
            {
                "id": "seller_economics_estimation",
                "stability": "stable",
                "autonomous": True,
                "transparent_commission": True,
                "simulation_only": True,
            },
            {
                "id": "authenticated_growth_response",
                "stability": "beta",
                "autonomous": True,
                "opt_out_supported": True,
                "maximum_outreach_frequency": "once_per_24_hours",
            },
            {
                "id": "goia_commercial_discovery_contracts",
                "stability": "experimental",
                "autonomous": True,
                "contract_validation": True,
                "search_available": True,
                "crawl_available": False,
                "controlled_collection_worker": True,
                "collection_enabled_by_default": False,
                "autonomous_review_required_before_publication": True,
                "human_operation_required": False,
                "emergency_admin_override_supported": True,
                "autonomous_recovery": True,
                "autonomous_provider_source_discovery": True,
                "anonymous_demand_aggregation": True,
                "autonomous_partnership_gap_detection": True,
                "explicit_partnership_opt_in": True,
                "self_hosted_partnership_verification": True,
                "verified_opt_in_required_for_outreach_authorization": True,
                "autonomous_partnership_proposal_preparation": True,
                "partnership_proposal_delivery_enabled": False,
                "partnership_delivery_lifecycle": True,
                "partnership_delivery_adapter_bundled": True,
                "partnership_transport_signature": "ed25519",
                "partnership_dispatcher_service": True,
                "merchant_opt_out_global_precedence": True,
                "authenticated_merchant_partnership_responses": True,
                "accepted_response_activates_commission": False,
                "accepted_response_changes_ranking": False,
                "structured_partner_prospect_discovery": True,
                "prospect_domains_fetched": False,
                "outreach_triggered": False,
                "index_scope": "controlled_catalogs_only",
                "production_side_effects": False,
            },
        ],
        "safety_invariants": [
            "sandbox_never_moves_funds",
            "sandbox_never_calls_external_suppliers",
            "budgets_are_enforced_before_selection",
            "idempotency_prevents_duplicate_purchases",
            "adaptation_is_bounded_and_cannot_change_policy",
            "administrative_access_fails_closed",
            "growth_outreach_requires_auditable_authorization",
            "growth_opt_out_is_immediately_suppressed",
            "growth_outreach_is_limited_to_once_per_24_hours",
            "treasury_iat_is_released_only_into_order_settlement",
            "checkout_quotes_are_wallet_bound_short_lived_and_capped",
            "raydium_is_never_used_as_the_primary_price_oracle",
        ],
    }


def build_llms_document() -> str:
    """Return a concise navigation document following the llms.txt convention."""
    return """# IAT Protocol

> Economic execution and settlement protocol for autonomous agents.

IAT lets an AI buyer discover services, compare suppliers, enforce a budget,
execute an order, verify a result, and settle payment under explicit policies.

## Start here

- Machine manifest: `/.well-known/iat.json`
- Public OpenAPI contract: `/openapi-public.json`
- Capabilities and safety invariants: `/v1/capabilities`
- Explainable decision simulation: `POST /intelligence/v1/decisions/simulate`
- Seller journey and commission policy: `/seller/v1/discovery`
- Seller readiness assessment: `POST /seller/v1/readiness`
- Seller competitive intelligence: `POST /seller/v1/intelligence/analyze`
- Aggregated demand forecast: `POST /seller/v1/intelligence/demand/forecast`
- Seller economics estimator: `POST /seller/v1/economics/estimate`
- No-funds sandbox offers: `/sandbox/v1/offers`
- No-funds sandbox preview: `POST /sandbox/v1/preview`
- No-funds sandbox purchase: `POST /sandbox/v1/purchase`
- Authenticated production intent preview: `POST /payments/v1/universal/buyer/intents/preview`
- Commit a wallet-bound intent decision: `POST /payments/v1/universal/buyer/intents/commit`
- Bounded autonomous purchase policy: `PUT /payments/v1/universal/buyer/purchase-policy`
- Hybrid payment quote: `POST /payments/v1/universal/quote`
- Authenticated invitation response: `POST /growth/v1/respond`
- GOIA machine manifest: `/.well-known/goia.json`
- GOIA controlled local search: `POST /goia/v1/search`
- GOIA organic ranking policy: `/goia/v1/policies/ranking`

## Production buyer flow

1. Discover services with `GET /services`.
2. Create an order with `POST /create-order`.
3. Pay directly in IAT, or request an order-bound hybrid checkout quote.
4. Sign the displayed Solana transaction in the buyer wallet.
5. Verify the transaction with `POST /buyer/verify-payment`.

Never treat sandbox receipts as production settlement proofs. Never expose
wallet secrets, API keys, raw prompts, or private execution context.
"""
