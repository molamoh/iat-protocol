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
        "services": "/services",
        "create_order": "/create-order",
        "verify_payment": "/buyer/verify-payment",
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
    "settlement": {
        "network": "solana",
        "rpc": IAT_NETWORK,
        "asset": "IAT",
        "modes": ["direct", "escrow"],
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
- Authenticated invitation response: `POST /growth/v1/respond`

## Production buyer flow

1. Discover services with `GET /services`.
2. Create an order with `POST /create-order`.
3. Transfer the requested IAT amount only after validating the order.
4. Verify the transaction with `POST /buyer/verify-payment`.

Never treat sandbox receipts as production settlement proofs. Never expose
wallet secrets, API keys, raw prompts, or private execution context.
"""
