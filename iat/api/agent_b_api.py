import json
import os
import time
import uuid
import requests
import threading
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from fastapi import FastAPI, Header, Request
from pydantic import BaseModel, EmailStr, Field
from solders.pubkey import Pubkey
from spl.token.instructions import get_associated_token_address
from iat.transfer import send_iat
from iat.onchain import (
    verify_tx_signature,
    get_tx_details,
    get_iat_balance,
    extract_transfer_checked_info,
    extract_memo,
)

from iat.api.execution_engine import select_best_agent, compute_agent_score
from iat.api.buyer_intent import (
    normalize_buyer_intent,
    merge_buyer_intent_with_session,
    analyze_seller_risk_with_groq,
    forecast_seller_attack_vectors_with_groq,
)

from iat.api.multi_exec import extract_topics_from_result
from iat.api.db import compute_agent_topic_score_db

from iat.api.db import (
    update_agent_call_stats_db,
    update_agent_consensus_stats_db,
    apply_agent_risk_decay_db,
    reactivate_agent_db,
    rename_agent_db,
    set_agent_trust_db,
    slash_agent_stake_db,
    update_agent_volume_stats_db,
    recompute_agent_metrics_db,
    compute_dynamic_stake_required_db,
    get_network_economics_db,
    reset_agent_trust_db,
    init_db,
    create_order_db,
    get_order_db,
    list_orders_db,
    update_order_delivered_db,
    record_settlement_db,
    list_settlements_db,
    update_settlement_status_db,
    validate_settlement_transition,
    run_settlement_orchestrator_once_db,
    is_tx_processed_db,
    save_processed_tx_db,
    get_stats_db,
    init_agents_table,
    register_agent_db,
    list_agents_db,
    delete_agent_db,
    get_agent_db,
    find_related_sellers_db,
    build_seller_graph_context_db,
    enrich_seller_graph_db,
    detect_seller_cluster_db,
    record_cluster_snapshot_db,
    compute_cluster_forecast_db,
    run_seller_risk_orchestration_db,
    deactivate_adaptive_policy_db,
    compute_adaptive_defense_policy_db,
    get_active_adaptive_policy_db,
    compute_seller_fingerprints_db,
    store_threat_forecast_db,
    get_active_threat_memory_db,
    create_seller_db,
    get_seller_by_wallet_db,
    get_seller_by_email_db,
    get_seller_by_api_key_db,
    get_seller_db,
    list_sellers_db,
    authenticate_seller_api_key_db,
    approve_seller_db,
    reject_seller_db,
    apply_seller_risk_event_db,
    list_seller_agents_db,
    get_seller_agent_db,
    list_runtime_monitored_seller_agents_db,
    list_seller_governance_events_db,
    create_seller_api_key,
    create_seller_agent_db,
    update_seller_agent_runtime_status_db,
    reinforce_threat_memory_db,
    decay_threat_memory_db,
    propagate_threat_memory_db,
    get_conn,
    release_conn,
    qmark,
    get_agents_for_service_db,
    update_agent_reputation_db,
    get_network_status_db,
    create_factory_agent_db,
    update_order_db,
    list_buyers_db,
    get_buyer_db,
    is_buyer_banned_db,
    ban_buyer_db,
    unban_buyer_db,
    register_buyer_seen_db,
    update_order_buyer_wallet_db,
    create_agent_delegation_db,
    get_agent_delegation_db,
    list_agent_delegations_db,
    list_delegator_positions_db,
    get_agent_delegated_stake_total_db,
    save_buyer_session_db,
    get_buyer_session_db,
    save_buyer_conversation_session_db,
    get_buyer_conversation_session_db,
    cleanup_expired_buyer_sessions_db,
    create_seller_catalog_item_db,
    list_seller_catalog_items_db,
    get_seller_catalog_item_db,
    create_seller_agent_factory_request_db,
    list_seller_agent_factory_requests_db,
    get_seller_agent_factory_request_db,
    run_seller_agent_factory_review_db,
    store_seller_agent_factory_review_db,
    get_seller_agent_factory_reviews_db,
    evaluate_seller_agent_factory_reviews_db,
    approve_seller_agent_factory_request_db,
    manual_approve_seller_agent_factory_request_db,
    get_seller_agent_factory_approvals_db,
    store_seller_agent_sandbox_review_db,
    get_seller_agent_sandbox_reviews_db,
    evaluate_seller_agent_sandbox_reviews_db,
    approve_seller_agent_sandbox_request_db,
    get_seller_agent_sandbox_approvals_db,
    store_seller_agent_simulation_review_db,
    get_seller_agent_simulation_reviews_db,
    evaluate_seller_agent_simulation_reviews_db,
    approve_seller_agent_simulation_request_db,
    get_seller_agent_simulation_approvals_db,
    store_seller_agent_activation_governance_review_db,
    get_seller_agent_activation_governance_reviews_db,
    evaluate_seller_agent_activation_governance_reviews_db,
    approve_seller_agent_activation_request_db,
    manual_activate_seller_agent_db,
    get_seller_agent_activation_approvals_db,
    store_seller_agent_runtime_review_db,
    get_seller_agent_runtime_reviews_db,
    evaluate_seller_agent_runtime_reviews_db,
    create_seller_agent_runtime_action_db,
    get_seller_agent_runtime_actions_db,
    run_seller_agent_runtime_governance_db,
    get_seller_agent_runtime_governance_reviews_db,
    get_seller_runtime_risk_events_db,
    get_seller_runtime_summary_db,
    run_seller_agent_sandbox_review_db,
    run_seller_agent_simulation_review_db,
    run_seller_agent_generation_db,
    run_seller_agent_activation_review_db,
    recompute_seller_dynamic_agent_capacity_db,
    orchestrate_seller_runtime_governance_db,
    run_foundation_controlled_seller_execution_db,
    verify_seller_execution_result_db,
    run_foundation_decision_db,
    get_protocol_memory_db,
    search_protocol_memory_db,
    reinforce_protocol_memory_db,
    decay_protocol_memory_db,
    archive_protocol_memory_db,
    run_protocol_learning_cycle_db,
    build_protocol_strategy_context_db,
    store_protocol_knowledge_db,
    get_protocol_knowledge_db,
    promote_memory_to_knowledge_db,
    build_protocol_knowledge_context_db,
    store_protocol_hypothesis_db,
    get_protocol_hypotheses_db,
    evaluate_protocol_hypothesis_db,
    store_protocol_experiment_db,
    get_protocol_experiments_db,
    start_protocol_experiment_db,
    complete_protocol_experiment_db,
    store_protocol_adaptation_db,
    get_protocol_adaptations_db,
    approve_protocol_adaptation_db,
    reject_protocol_adaptation_db,
    apply_protocol_adaptation_db,
    get_protocol_rollbacks_db,
    rollback_protocol_adaptation_db,
    store_protocol_adaptation_review_db,
    get_protocol_adaptation_reviews_db,
    evaluate_protocol_adaptation_reviews_db,
    store_protocol_adaptation_monitor_db,
    get_protocol_adaptation_monitors_db,
    evaluate_protocol_adaptation_monitor_db,
    run_protocol_adaptation_monitoring_cycle_db,
    store_protocol_rollback_review_db,
    get_protocol_rollback_reviews_db,
    evaluate_protocol_rollback_reviews_db,
    store_protocol_rollback_proposal_db,
    get_protocol_rollback_proposals_db,
)


class AgentTrustUpdate(BaseModel):
    agent_id: str
    trust_tier: str | None = None
    stake_amount: float | None = None
    stake_required: float | None = None
    risk_score: float | None = None



class AgentStakeVerifyRequest(BaseModel):
    agent_id: str
    tx_signature: str
    expected_amount: float = 0


class DelegationRequest(BaseModel):
    delegation_id: str
    agent_id: str
    delegator_wallet: str
    amount: float


app = FastAPI()

def require_admin_key(x_api_key):
    expected_key = os.getenv("IAT_ADMIN_API_KEY")

    # Security rule:
    # If no admin key is configured, admin access must be denied by default.
    if not expected_key:
        return False

    if not x_api_key:
        return False

    return x_api_key == expected_key



def payment_wallet_for(agent_wallet):
    escrow_wallet = os.getenv("IAT_ESCROW_WALLET")
    return escrow_wallet if escrow_wallet else agent_wallet


def payment_target():
    return "escrow" if os.getenv("IAT_ESCROW_WALLET") else "seller"


init_db()
init_agents_table()

WALLET_A = "DUtz7zHeVsd8mnJhWM52z5LsC9NqY6SVRjCBPgNM8Qrj"
IAT_MINT = "3vRGo1VpGbZH67Ur2UG7VNUqSqQyApLQEcCxgnqK4f4Z"
ORDER_TTL = 1800


SERVICES = {
    "risk_report": {
        "description": "BTC risk and volatility report",
        "sellers": [
            {
                "seller_id": "risk_agent_cheap",
                "seller_wallet": "3aK6yemWa3AJFszWu1eyvhoWK6czLRnvCc4bUHgQSvip",
                "price": 0.8,
                "reputation": 0.89,
                "available": True,
            }
        ],
    },
    "market_sentiment": {
        "description": "BTC market sentiment report",
        "sellers": [
            {
                "seller_id": "sentiment_agent_basic",
                "seller_wallet": "EPabAZ3CtMkbjduLrNcDZuXaEp37Ge9cmrnwWF9TY5wc",
                "price": 1.0,
                "reputation": 0.91,
                "available": True,
            }
        ],
    },
    "web_research": {
    "description": "General autonomous web research",
    "sellers": [],
    },
}


class RegisterAgentRequest(BaseModel):
    agent_id: str
    service: str
    url: str | None = None
    wallet: str
    agent_type: str = "standard"
    price: float
    reputation: float = 0.8
    available: bool = True
    stake_amount: float = 0
    stake_required: float = 10
    trust_tier: str = "free"
    capabilities: str = "[]"
    specialties: str = "[]"

    foundation_role: str | None = None
    foundation_priority: int | None = None


class LegacySellerRegisterRequest(BaseModel):
    seller_id: str
    business_name: str
    service: str
    url: str
    wallet: str

    product_description: str
    quality_claims: str = ""
    refund_policy: str = ""
    delivery_terms: str = ""

    capabilities: str = "[]"
    specialties: str = "[]"

    stake_amount: float = 0
    requested_price: float = 0

    proof_links: str = "[]"


class SellerCatalogItemRequest(BaseModel):
    item_type: str
    category: str
    title: str
    description: str

    service_type: str | None = None
    sku: str | None = None

    unit_price: float = 0
    currency: str = "IAT"

    stock_quantity: float = 0
    capacity_per_day: float = 0
    capacity_per_order: float = 0

    availability_status: str = "draft"

    delivery_terms: str = ""
    refund_policy: str = ""
    warranty_terms: str = ""
    quality_claims: str = ""

    source_documents: list | str = []
    proof_links: list | str = []

    metadata: dict | str = {}


class SellerAgentFactoryRequest(BaseModel):
    catalog_item_id: str
    requested_agent_name: str | None = None
    requested_prompt: str

    requested_agent_count: int = 1
    requested_specializations: list | str = []
    factory_plan: dict | str = {}

    metadata: dict | str = {}


class OrderRequest(BaseModel):
    service: str
    query: str | None = None
    buyer_wallet: str | None = None
    buyer_intent: dict | None = None
    requirements: dict | None = None
    buyer_context: dict | None = None
    locked_agent_id: str | None = None


class BuyerPreviewRequest(BaseModel):
    buyer_wallet: str
    prompt: str
    max_price: float | None = None
    session_id: str | None = None
    debug: bool = False


class BuyerConfirmRequest(BaseModel):
    buyer_wallet: str
    session_id: str
    max_price: float | None = None
    debug: bool = False


class InternalSellerSuccessRequest(BaseModel):
    order_reference: str | None = None
    amount_iat: float = 0
    quality_score: float = 1.0


class InternalSellerResultVerifyRequest(BaseModel):
    order_reference: str | None = None
    service: str
    result: dict


class InternalSellerExecuteRequest(BaseModel):
    order_reference: str | None = None
    service: str
    execution_context: dict
    foundation_context: dict | None = None


class SellerRehabilitationRequest(BaseModel):
    verdict: str = ""
    available: bool = True


class SellerReviewRequest(BaseModel):
    action: str
    verdict: str = ""
    risk_score: float | None = None
    trust_tier: str | None = None
    available: bool | None = None


class VerifyPaymentRequest(BaseModel):
    order_id: str
    tx_signature: str


def select_best_seller(service_name, order=None):
    dynamic_agents = get_agents_for_service_db(service_name)

    # Buyer-facing execution is foundation-only.
    # External seller agents must never directly access buyers.
    dynamic_agents = [
        a for a in dynamic_agents
        if str(a.get("agent_type", "")).lower() == "foundation"
    ]

    if not dynamic_agents:
        return None

    locked_agent_id = None
    if order:
        locked_agent_id = (
            order.get("locked_agent_id")
            or order.get("selected_agent_id")
        )

    if locked_agent_id:
        best_agent = next(
            (
                a for a in dynamic_agents
                if a.get("agent_id") == locked_agent_id
                and bool(a.get("available", True))
            ),
            None,
        )
    elif order:
        from iat.api.multi_exec import select_top_agents

        selected = select_top_agents(
            dynamic_agents,
            limit=1,
            order=order,
        )

        best_agent = selected[0] if selected else None
    else:
        best_agent = select_best_agent(dynamic_agents)

    if not best_agent:
        return None

    return {
        "seller_id": best_agent["agent_id"],
        "seller_wallet": best_agent["wallet"],
        "price": best_agent["price"],
        "reputation": best_agent["reputation"],
        "available": best_agent["available"],
        "url": best_agent["url"],
        "source": "dynamic_registry",
        "capabilities": best_agent.get("capabilities"),
        "specialties": best_agent.get("specialties"),
    }



def build_foundation_context(order):
    """
    Foundation-only trusted context builder.

    Future role:
    - web research
    - Groq normalization
    - source verification
    - anti-prompt-injection filtering
    - canonical market context
    - consensus preparation

    Seller agents must never directly access raw buyer requests.
    """

    buyer_intent = order.get("buyer_intent") or {}

    return {
        "generated_by": "iat_foundation_layer",
        "service": order.get("service"),
        "goal": buyer_intent.get("goal"),
        "requirements": order.get("requirements", {}),
        "required_capabilities": buyer_intent.get("required_capabilities", []),
        "preferred_specialties": buyer_intent.get("preferred_specialties", []),
        "consensus_preference": buyer_intent.get("consensus_preference"),
        "quality_preference": buyer_intent.get("quality_preference"),
        "trusted": True,
    }


def generate_service_result(service_name, query=None):
    if service_name == "risk_report":
        return {
            "type": "risk_analysis",
            "asset": "BTC",
            "risk_level": "medium",
            "volatility": "high",
            "recommendation": "reduce_leverage",
            "timestamp": int(time.time()),
        }

    if service_name == "market_sentiment":
        return {
            "type": "market_sentiment",
            "asset": "BTC",
            "sentiment": "cautiously_bullish",
            "fear_greed": "neutral_to_greed",
            "crowd_bias": "long_heavy",
            "timestamp": int(time.time()),
        }

    if service_name.startswith("hotel_search"):
        return {
            "type": "factory_generated_result",
            "service": service_name,
            "query": query or "hotel comparison",
            "location": "Paris",
            "results": [
                {
                    "name": "Hotel Example Central Paris",
                    "category": "comfort",
                    "score": 8.7,
                    "reason": "Good location and balanced price/value",
                },
                {
                    "name": "Hotel Example Boutique Paris",
                    "category": "boutique",
                    "score": 8.9,
                    "reason": "Higher guest satisfaction and quieter area",
                },
                {
                    "name": "Hotel Example Budget Paris",
                    "category": "budget",
                    "score": 8.1,
                    "reason": "Lower price with acceptable quality",
                },
            ],
            "note": "MVP factory response. Real hotel data requires external APIs or web agent.",
            "timestamp": int(time.time()),
        }

    return {
        "type": "factory_generated_result",
        "service": service_name,
        "query": query,
        "message": f"Auto-generated agent executed service: {service_name}",
        "note": "MVP dynamic factory response",
        "timestamp": int(time.time()),
    }




def _ensure_dict(value, default=None):
    default = default or {}

    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else default
        except Exception:
            return default

    return default


def run_foundation_supplier_pipeline(order):
    """
    Foundation-mediated supplier pipeline.

    Buyer never contacts sellers.
    Seller agents are internal suppliers only.
    Foundation agents keep final buyer delivery authority.
    """
    order = order or {}

    execution_context = _ensure_dict(order.get("execution_context"))
    buyer_intent = _ensure_dict(order.get("buyer_intent"))
    requirements = _ensure_dict(order.get("requirements"))

    foundation_task = (
        execution_context.get("task")
        or buyer_intent.get("goal")
        or order.get("query")
        or f"Execute service: {order.get('service')}"
    )

    sanitized_execution_context = {
        "task": foundation_task,
        "scope": requirements,
        "required_format": "structured_supplier_contribution",
        "service": order.get("service"),
        "trusted_input_only": True,
        "foundation_mediated": True,
        "buyer_data_stripped": True,
    }

    supplier_execution = run_foundation_controlled_seller_execution_db(
        service=order.get("service"),
        execution_context=sanitized_execution_context,
        specialization=None,
        order_id=order.get("order_id"),
    )

    if supplier_execution.get("status") != "ok":
        fallback = generate_service_result(
            order.get("service"),
            query=order.get("query"),
        )

        return {
            "status": "foundation_supplier_pipeline_fallback",
            "execution_mode": "foundation_supplier_pipeline",
            "reason": "no_eligible_internal_supplier_or_supplier_execution_failed",
            "buyer_delivery_authority": "foundation_only",
            "seller_role": "internal_supplier_only",
            "seller_direct_buyer_contact": False,
            "supplier_execution": supplier_execution,
            "foundation_fallback_result": fallback,
            "policy": {
                "buyer_never_contacts_seller": True,
                "seller_never_contacts_buyer": True,
                "seller_agents_are_suppliers_only": True,
                "buyer_satisfaction_priority": True,
                "foundation_agents_keep_final_authority": True,
                "protocol_core_sovereignty_reserved": True,
            },
        }

    verification = verify_seller_execution_result_db(
        supplier_execution.get("execution_session_id")
    )

    foundation_decision = run_foundation_decision_db(order.get("order_id"))

    try:
        from iat.api.multi_exec import build_foundation_buyer_report

        foundation_report = build_foundation_buyer_report(
            foundation_decision,
            fallback_delivery={
                "status": "success",
                "summary": "Foundation-mediated supplier execution completed.",
                "final_recommendation": "Use the Foundation decision and verified evidence as the buyer-facing delivery.",
                "confidence": (
                    foundation_decision.get("foundation_decision", {})
                    .get("decision_confidence", 0.5)
                    if isinstance(foundation_decision, dict)
                    else 0.5
                ),
                "sources": [],
            },
        )
    except Exception as exc:
        foundation_report = {
            "status": "success",
            "delivery_mode": "foundation_supplier_report_fallback",
            "summary": "Foundation-mediated supplier execution completed.",
            "foundation_report_error": str(exc),
        }

    return {
        "status": "foundation_supplier_pipeline_completed",
        "execution_mode": "foundation_supplier_pipeline",
        "buyer_delivery_authority": "foundation_only",
        "seller_role": "internal_supplier_only",
        "seller_direct_buyer_contact": False,
        "supplier_execution": supplier_execution,
        "supplier_verification": verification,
        "foundation_decision": foundation_decision,
        "result": foundation_report,
        "policy": {
            "buyer_never_contacts_seller": True,
            "seller_never_contacts_buyer": True,
            "seller_agents_are_suppliers_only": True,
            "foundation_agents_keep_final_authority": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }


def deliver_service(order, tx_signature):
    # Buyer delivery must only be executed by foundation agents.
    # Seller agents are never allowed to directly receive buyer requests.
    if str(order.get("seller_source") or "") == "dynamic_registry":
        agent = get_agent_db(order.get("seller_id"))
        if not agent or str(agent.get("agent_type", "")).lower() != "foundation":
            return {
                "error": "non_foundation_buyer_delivery_blocked",
                "message": "Buyer-facing delivery is restricted to protocol foundation agents.",
            }

    execution_mode = str(
        order.get("execution_mode") or "foundation_direct"
    ).lower()

    # Foundation-mediated supplier pipeline.
    # Buyer-facing delivery remains foundation-only.
    # Seller agents are internal suppliers and never receive raw buyer access.
    if execution_mode == "foundation_supplier_pipeline":
        return run_foundation_supplier_pipeline(order)

    # Foundation consensus execution pipeline.
    if execution_mode == "foundation_consensus":
        from iat.api.multi_exec import (
            compute_required_agent_count,
            select_top_agents,
            multi_call,
            select_best_result,
            build_final_buyer_delivery,
            compute_consensus_strength,
        )

        all_agents = get_agents_for_service_db(order.get("service"))

        foundation_agents = [
            a for a in all_agents
            if str(a.get("agent_type", "")).lower() == "foundation"
            and bool(a.get("available", True))
        ]

        required_count = compute_required_agent_count(order)

        selected_agents = select_top_agents(
            foundation_agents,
            limit=required_count,
            order=order,
        )

        results = multi_call(selected_agents, order)

        consensus_strength = compute_consensus_strength(results)

        best_result = select_best_result(results)

        if not best_result:
            return {
                "error": "consensus_failed",
                "message": "No valid consensus result produced.",
                "execution_mode": execution_mode,
                "agents_called": [
                    a.get("agent_id")
                    for a in selected_agents
                ],
            }

        final_delivery = build_final_buyer_delivery(
            best_result,
            results,
        )

        foundation_decision = run_foundation_decision_db(order.get("order_id"))

        try:
            from iat.api.multi_exec import build_foundation_buyer_report

            foundation_report = build_foundation_buyer_report(
                foundation_decision,
                fallback_delivery=final_delivery,
            )
        except Exception as exc:
            foundation_report = {
                **final_delivery,
                "delivery_mode": "foundation_report_fallback",
                "foundation_report_error": str(exc),
            }

        return {
            "status": "consensus_delivered",
            "execution_mode": execution_mode,
            "agents_called": [
                a.get("agent_id")
                for a in selected_agents
            ],
            "consensus_agents_count": len(selected_agents),
            "consensus_strength": consensus_strength,
            "foundation_decision": foundation_decision,
            "result": foundation_report,
        }

    if order.get("seller_url"):
        payload = {
            "order_id": order["order_id"],
            "tx_signature": tx_signature,
        }

        foundation_context = order.get("foundation_context") or build_foundation_context(order)
        execution_context = order.get("execution_context") or {}

        if not order.get("foundation_context"):
            order["foundation_context"] = foundation_context
            try:
                update_order_db(order.get("order_id"), order)
            except Exception as e:
                print("Foundation context persistence error:", e)

        payload["context"] = {
            "service": order.get("service"),
            "execution_mode": order.get("execution_mode", "foundation_direct"),
            "requirements": order.get("requirements", {}),
            "buyer_context": order.get("buyer_context", {}),
            "foundation_context": foundation_context,
            "execution_context": execution_context,
        }

        # Foundation agents are trusted protocol agents and may receive the buyer query.
        # Future seller agents must receive only sanitized execution_context.
        agent = get_agent_db(order.get("seller_id"))
        if agent and str(agent.get("agent_type", "")).lower() == "foundation":
            if order.get("query"):
                payload["query"] = order.get("query")

        try:
            r = requests.post(
                f"{order['seller_url']}/execute",
                json=payload,
                timeout=30,
            )

            if r.status_code == 200:
                response = r.json()
                return response.get("data", response)

            return {
                "error": "seller_node_error",
                "status_code": r.status_code,
                "body": r.text,
            }

        except Exception as e:
            return {
                "error": "seller_node_unreachable",
                "details": str(e),
            }

    return generate_service_result(order["service"], query=order.get("query"))





@app.post("/internal/seller/apply-risk-decay/{seller_id}")
def apply_seller_risk_decay(
    seller_id: str,
    payload: dict | None = None,
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    seller = get_agent_db(seller_id)

    if not seller:
        from iat.api.db import get_seller_db

        seller = get_seller_db(seller_id)

    if not seller:
        return {
            "status": "invalid_seller",
            "message": "Seller not found.",
        }

    payload = payload or {}

    reason = str(
        payload.get("reason", "stable_behavior")
    )

    result = apply_agent_risk_decay_db(
        seller_id,
        reason,
    )

    refreshed = get_agent_db(seller_id)

    return {
        "status": result.get("status"),
        "seller_id": seller_id,
        "reason": result.get("reason"),
        "old_risk_score": result.get("old_risk_score"),
        "new_risk_score": refreshed.get("risk_score"),
        "risk_decay_events": refreshed.get("risk_decay_events"),
    }


@app.post("/internal/seller/record-consensus-check/{seller_id}")
def record_seller_consensus_check(
    seller_id: str,
    payload: dict,
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    seller = get_agent_db(seller_id)

    if not seller:
        from iat.api.db import get_seller_db

        seller = get_seller_db(seller_id)

    if not seller:
        return {
            "status": "invalid_seller",
            "message": "Seller not found.",
        }

    consensus_score = float(
        payload.get("consensus_score", 0) or 0
    )

    result = update_agent_consensus_stats_db(
        seller_id,
        consensus_score,
    )

    refreshed = get_agent_db(seller_id)

    return {
        "status": "consensus_recorded",
        "seller_id": seller_id,
        "consensus_score": consensus_score,
        "divergence_detected": result.get("divergence_detected"),
        "consensus_checks": result.get("consensus_checks"),
        "consensus_disagreements": result.get("consensus_disagreements"),
        "consensus_disagreement_rate": result.get("consensus_disagreement_rate"),
        "risk_score": refreshed.get("risk_score"),
    }


@app.post("/internal/seller/record-success/{seller_id}")
def internal_record_seller_success(
    seller_id: str,
    req: InternalSellerSuccessRequest,
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    agent = get_agent_db(seller_id)

    if not agent:
        return {
            "status": "error",
            "message": "seller_not_found",
        }

    if str(agent.get("agent_type", "")).lower() == "foundation":
        return {
            "status": "blocked",
            "message": "foundation_agents_do_not_use_growth_system",
        }

    amount = float(req.amount_iat or 0)

    update_agent_reputation_db(
        seller_id,
        success=True
    )

    update_agent_volume_stats_db(
        seller_id,
        amount=amount,
        honest=True
    )

    metrics = recompute_agent_metrics_db(seller_id)

    refreshed = get_agent_db(seller_id)

    target_max_order_value = compute_max_order_value(refreshed)

    current_max_order_value = float(
        agent.get("max_order_value", 0)
        or agent.get("stake_amount", 0)
        or 0
    )

    if current_max_order_value <= 0:
        current_max_order_value = float(agent.get("stake_amount", 0) or 0)

    growth_rate = 0.10

    max_order_value = min(
        target_max_order_value,
        round(current_max_order_value * (1 + growth_rate), 6),
    )

    refreshed["max_order_value"] = max_order_value
    refreshed["last_volume_total"] = refreshed.get("honest_volume", 0)
    refreshed["last_max_order_value"] = max_order_value
    refreshed["velocity_updated_at"] = int(time.time())

    register_agent_db(refreshed)

    return {
        "status": "success_recorded",
        "seller_id": seller_id,
        "amount_iat": amount,
        "reputation": metrics.get("reputation"),
        "risk_score": metrics.get("risk_score"),
        "trust_tier": metrics.get("trust_tier"),
        "dynamic_stake_required": metrics.get("dynamic_stake_required"),
        "max_order_value": max_order_value,
        "success_count": refreshed.get("success_count"),
        "honest_volume": refreshed.get("honest_volume"),
    }


@app.post("/internal/seller/verify-result/{seller_id}")
def internal_verify_seller_result(
    seller_id: str,
    req: InternalSellerResultVerifyRequest,
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    seller = get_agent_db(seller_id)

    if not seller:
        from iat.api.db import get_seller_db

        seller = get_seller_db(seller_id)

    if not seller:
        return {
            "status": "invalid_seller",
            "message": "Seller not found.",
        }

    result = req.result or {}

    forbidden_patterns = [
        "buyer_wallet",
        "buyer_secret",
        "payment_secret",
        "seed_phrase",
        "private_key",
    ]

    suspicious_hits = []

    def recursive_scan(value):
        if isinstance(value, dict):
            for k, v in value.items():
                recursive_scan(k)
                recursive_scan(v)

        elif isinstance(value, list):
            for x in value:
                recursive_scan(x)

        elif isinstance(value, str):
            lower = value.lower()

            for p in forbidden_patterns:
                if p in lower:
                    suspicious_hits.append(p)

    recursive_scan(result)

    required_fields = [
        "summary",
        "confidence",
    ]

    missing_fields = [
        f for f in required_fields
        if f not in result
    ]

    score = 1.0

    if missing_fields:
        score -= 0.3

    if suspicious_hits:
        score -= 0.6

    score = max(0.0, round(score, 4))

    if suspicious_hits:
        verdict = "rejected"

    elif score < 0.5:
        verdict = "suspicious"

    else:
        verdict = "accepted"

    penalty_applied = False
    new_dynamic_stake_required = None

    if verdict in ["rejected", "suspicious"]:
        penalty_applied = True

        current_risk = float(seller.get("risk_score", 0) or 0)
        current_dynamic_stake = float(
            seller.get("dynamic_stake_required", 0)
            or seller.get("stake_required", 0)
            or 10
        )

        risk_increment = 0.25 if verdict == "rejected" else 0.10
        new_risk = min(1.0, current_risk + risk_increment)

        multiplier = 3.0 if verdict == "rejected" else 1.5
        new_dynamic_stake_required = round(
            max(current_dynamic_stake * multiplier, 10),
            6,
        )

        seller["risk_score"] = new_risk
        seller["dynamic_stake_required"] = new_dynamic_stake_required

        current_exposure = float(
            seller.get("max_order_value", 0)
            or seller.get("stake_amount", 0)
            or 0
        )

        exposure_penalty = 0.10 if verdict == "rejected" else 0.50

        seller["max_order_value"] = round(
            current_exposure * exposure_penalty,
            6,
        )

        seller["available"] = False
        seller["seller_status"] = "suspended"
        seller["foundation_verdict"] = (
            f"Seller result {verdict}. Dynamic stake increased before reactivation."
        )

        register_agent_db(seller)

    return {
        "status": "verified",
        "seller_id": seller_id,
        "verdict": verdict,
        "seller_result_score": score,
        "penalty_applied": penalty_applied,
        "dynamic_stake_required": new_dynamic_stake_required,
        "missing_fields": missing_fields,
        "suspicious_hits": suspicious_hits,
        "result_preview": {
            "summary": result.get("summary"),
            "confidence": result.get("confidence"),
        }
    }


@app.post("/internal/seller/execute/{seller_id}")
def internal_seller_execute(
    seller_id: str,
    req: InternalSellerExecuteRequest,
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    seller = get_agent_db(seller_id)

    if not seller:
        return {
            "status": "invalid_seller",
            "message": "Seller not found.",
        }

    if str(seller.get("agent_type", "")).lower() != "seller":
        return {
            "status": "invalid_agent_type",
            "message": "Only verified seller agents can be executed.",
        }

    if str(seller.get("verification_status", "")).lower() != "foundation_verified":
        return {
            "status": "seller_not_verified",
            "message": "Seller is not foundation verified.",
        }

    if not seller.get("available"):
        return {
            "status": "seller_unavailable",
            "message": "Seller is currently unavailable.",
        }

    execution_context = req.execution_context or {}

    forbidden_fields = [
        "buyer_prompt",
        "raw_prompt",
        "buyer_wallet",
        "buyer_secret",
        "tx_signature",
        "payment_secret",
    ]

    leaked_fields = [
        k for k in forbidden_fields
        if k in execution_context
    ]

    if leaked_fields:
        return {
            "status": "blocked",
            "message": "Forbidden buyer-sensitive fields detected.",
            "forbidden_fields": leaked_fields,
        }

    sanitized_payload = {
        "service": req.service,
        "order_reference": req.order_reference,
        "execution_context": execution_context,
        "foundation_context": req.foundation_context or {},
        "protocol_constraints": {
            "buyer_access": False,
            "web_access": False,
            "raw_prompt_access": False,
            "foundation_mediated": True,
        }
    }

    return {
        "status": "seller_execution_accepted",
        "seller_id": seller_id,
        "execution_mode": "foundation_mediated",
        "payload": sanitized_payload,
    }



def compute_seller_velocity_risk(seller):
    """
    Detect suspicious economic acceleration.
    Advisory only.
    """
    score = 0.0
    reasons = []

    current_volume = float(
        seller.get("honest_volume", 0) or 0
    )

    previous_volume = float(
        seller.get("last_volume_total", 0) or 0
    )

    current_exposure = float(
        seller.get("max_order_value", 0) or 0
    )

    previous_exposure = float(
        seller.get("last_max_order_value", 0) or 0
    )

    # Volume acceleration
    if previous_volume > 0:
        volume_growth = current_volume / previous_volume

        if volume_growth >= 10:
            score += 0.35
            reasons.append("extreme_volume_growth")

        elif volume_growth >= 5:
            score += 0.20
            reasons.append("high_volume_growth")

        elif volume_growth >= 2:
            score += 0.10
            reasons.append("moderate_volume_growth")

    # Exposure acceleration
    if previous_exposure > 0:
        exposure_growth = current_exposure / previous_exposure

        if exposure_growth >= 10:
            score += 0.40
            reasons.append("extreme_exposure_growth")

        elif exposure_growth >= 5:
            score += 0.25
            reasons.append("high_exposure_growth")

        elif exposure_growth >= 2:
            score += 0.10
            reasons.append("moderate_exposure_growth")

    score = round(min(score, 1.0), 4)

    if score >= 0.50:
        band = "high"
    elif score >= 0.20:
        band = "medium"
    else:
        band = "low"

    return {
        "velocity_risk_score": score,
        "risk_band": band,
        "reasons": reasons,
        "advisory_only": True,
    }


def compute_temporal_seller_risk(seller):
    """
    Temporal risk layer.
    Detects dormant accounts, recent failures, and suspicious recovery patterns.
    Advisory only.
    """
    now = int(time.time())

    score = 0.0
    reasons = []

    last_success_at = seller.get("last_success_at")
    last_failure_at = seller.get("last_failure_at")
    last_activity_at = seller.get("last_activity_at")

    seller_status = str(seller.get("seller_status", "") or "").lower()
    risk_score = float(seller.get("risk_score", 0) or 0)

    if last_failure_at:
        age = now - int(last_failure_at)

        if age < 86400:
            score += 0.30
            reasons.append("recent_failure_24h")

        elif age < 604800:
            score += 0.15
            reasons.append("recent_failure_7d")

    if last_activity_at:
        dormant_age = now - int(last_activity_at)

        if dormant_age > 60 * 60 * 24 * 90:
            score += 0.15
            reasons.append("dormant_90d")

        elif dormant_age > 60 * 60 * 24 * 30:
            score += 0.08
            reasons.append("dormant_30d")

    if seller_status in ["rehabilitated", "active"] and risk_score >= 0.25:
        score += 0.15
        reasons.append("active_with_elevated_risk")

    if seller_status in ["rejected", "suspended"]:
        score += 0.25
        reasons.append("currently_sanctioned")

    score = round(min(score, 1.0), 4)

    if score >= 0.50:
        band = "high"
    elif score >= 0.20:
        band = "medium"
    else:
        band = "low"

    return {
        "temporal_risk_score": score,
        "risk_band": band,
        "reasons": reasons,
        "advisory_only": True,
    }


def compute_cluster_risk_signal(seller):
    """
    Converts seller cluster detection into bounded local risk.
    Advisory only.
    """
    seller_id = seller.get("agent_id")

    cluster = detect_seller_cluster_db(seller_id)

    if not cluster:
        return {
            "cluster_risk_signal": 0.0,
            "risk_band": "low",
            "reasons": [],
            "advisory_only": True,
        }

    cluster_risk = float(
        cluster.get("cluster_risk_score", 0)
        or 0
    )

    coordination = float(
        cluster.get("coordination_probability", 0)
        or 0
    )

    member_count = int(
        cluster.get("member_count", 0)
        or 0
    )

    seller_status = str(seller.get("seller_status", "") or "").lower()
    risk_score = float(seller.get("risk_score", 0) or 0)

    is_directly_sanctioned = (
        seller_status in ["rejected", "suspended"]
        or risk_score >= 0.75
    )

    max_cluster_impact = 0.25 if is_directly_sanctioned else 0.10

    score = min(
        max_cluster_impact,
        round((cluster_risk * 0.6) + (coordination * 0.2), 4),
    )

    reasons = []

    if member_count >= 2:
        reasons.append(f"seller_cluster_members:{member_count}")

    if coordination >= 0.4:
        reasons.append("elevated_coordination_probability")

    if cluster_risk >= 0.25:
        reasons.append("elevated_cluster_risk")

    if score >= 0.18:
        band = "high"
    elif score >= 0.08:
        band = "medium"
    else:
        band = "low"

    return {
        "cluster_risk_signal": score,
        "risk_band": band,
        "reasons": reasons,
        "cluster": cluster,
        "advisory_only": True,
    }


def compute_threat_memory_risk(seller):
    """
    Converts active threat memory into a controlled local risk signal.
    Advisory only, explainable, and bounded.
    """
    seller_id = seller.get("agent_id")

    memories = get_active_threat_memory_db(
        scope="seller",
        subject_id=seller_id,
        limit=25,
    )

    score = 0.0
    reasons = []

    for memory in memories:
        confidence = float(memory.get("confidence", 0) or 0)
        strength = float(memory.get("memory_strength", 0.5) or 0.5)
        threat_level = str(memory.get("threat_level", "") or "").lower()
        attack_vector = memory.get("attack_vector")

        source = str(memory.get("source", "") or "").lower()

        min_confidence = 0.2 if source == "propagated" else 0.5

        if confidence < min_confidence:
            continue

        weight = confidence * strength

        if threat_level == "critical":
            score += 0.12 * weight
        elif threat_level == "high":
            score += 0.08 * weight
        elif threat_level == "medium":
            score += 0.04 * weight
        else:
            score += 0.02 * weight

        if attack_vector:
            reasons.append(f"active_threat_memory:{attack_vector}")

    score = round(min(score, 0.35), 4)

    if score >= 0.25:
        band = "high"
    elif score >= 0.10:
        band = "medium"
    else:
        band = "low"

    return {
        "threat_memory_risk_score": score,
        "risk_band": band,
        "reasons": reasons[:10],
        "active_memory_count": len(memories),
        "advisory_only": True,
    }


def compute_seller_pre_risk_score(seller, related_context=None):
    """
    Cheap deterministic seller risk pre-score.
    Advisory only. Final decision remains foundation/protocol.
    """
    related_context = related_context or {}

    score = 0.0
    reasons = []

    price = float(seller.get("price", 0) or 0)
    stake_amount = float(seller.get("stake_amount", 0) or 0)
    risk_score = float(seller.get("risk_score", 0) or 0)

    metadata = seller.get("seller_metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}

    proof_links = metadata.get("proof_links")
    product_description = metadata.get("product_description")
    refund_policy = metadata.get("refund_policy")
    delivery_terms = metadata.get("delivery_terms")

    if price >= 1000:
        score += 0.15
        reasons.append("high_price")

    if price >= 5000:
        score += 0.20
        reasons.append("very_high_price")

    if stake_amount <= 0:
        score += 0.20
        reasons.append("no_stake")

    elif price > 0 and stake_amount / price < 0.05:
        score += 0.15
        reasons.append("low_stake_relative_to_price")

    if not proof_links:
        score += 0.10
        reasons.append("missing_proof_links")

    if not product_description:
        score += 0.10
        reasons.append("missing_product_description")

    if not refund_policy:
        score += 0.05
        reasons.append("missing_refund_policy")

    if not delivery_terms:
        score += 0.05
        reasons.append("missing_delivery_terms")

    if risk_score >= 0.5:
        score += 0.25
        reasons.append("existing_high_risk_score")

    related_count = int(related_context.get("related_count", 0) or 0)
    related_sellers = related_context.get("related_sellers", []) or []

    if related_count >= 3:
        score += 0.10
        reasons.append("many_related_sellers")

    rejected_related = [
        r for r in related_sellers
        if str(r.get("seller_status", "")).lower() in ["rejected", "suspended"]
    ]

    if rejected_related:
        score += 0.25
        reasons.append("related_rejected_or_suspended_sellers")

    temporal = compute_temporal_seller_risk(seller)

    temporal_score = float(
        temporal.get("temporal_risk_score", 0)
        or 0
    )

    score += temporal_score * 0.5

    reasons.extend(
        temporal.get("reasons", [])
    )

    velocity = compute_seller_velocity_risk(seller)

    velocity_score = float(
        velocity.get("velocity_risk_score", 0)
        or 0
    )

    score += velocity_score * 0.5

    reasons.extend(
        velocity.get("reasons", [])
    )

    threat_memory = compute_threat_memory_risk(seller)

    threat_memory_score = float(
        threat_memory.get("threat_memory_risk_score", 0)
        or 0
    )

    score += threat_memory_score

    reasons.extend(
        threat_memory.get("reasons", [])
    )

    cluster_risk = compute_cluster_risk_signal(seller)

    cluster_score = float(
        cluster_risk.get("cluster_risk_signal", 0)
        or 0
    )

    score += cluster_score

    reasons.extend(
        cluster_risk.get("reasons", [])
    )

    score = round(min(score, 1.0), 4)

    if score >= 0.70:
        risk_band = "high"
    elif score >= 0.35:
        risk_band = "medium"
    else:
        risk_band = "low"

    return {
        "pre_risk_score": score,
        "risk_band": risk_band,
        "reasons": reasons,
        "advisory_only": True,
    }




@app.post("/admin/recompute-seller-fingerprints/{seller_id}")
def recompute_seller_fingerprints(
    seller_id: str,
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    seller = get_agent_db(seller_id)

    if not seller:
        return {
            "status": "invalid_seller",
            "message": "Seller not found.",
        }

    fingerprints = compute_seller_fingerprints_db(
        seller_id
    )

    refreshed = get_agent_db(seller_id)

    return {
        "status": "fingerprints_recomputed",
        "seller_id": seller_id,
        "fingerprints": fingerprints,
        "fingerprint_updated_at": refreshed.get(
            "fingerprint_updated_at"
        ),
    }





@app.post("/internal/threat-memory/reinforce/{memory_id}")
def reinforce_threat_memory(
    memory_id: int,
    observed: bool = True,
    reason: str = "",
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    result = reinforce_threat_memory_db(
        memory_id=memory_id,
        observed=observed,
        reason=reason,
    )

    refresh_result = None

    # Reload memory owner after reinforcement.
    memories = get_active_threat_memory_db(
        limit=100,
    )

    for memory in memories:
        if int(memory.get("id", 0) or 0) == int(memory_id):
            subject_id = memory.get("subject_id")
            if subject_id:
                refresh_result = refresh_adaptive_policy_for_seller(
                    subject_id
                )
            break

    result["adaptive_refresh"] = refresh_result

    return result




@app.post("/internal/threat-memory/propagate/{memory_id}")
def propagate_threat_memory(
    memory_id: int,
    max_confidence: float = 0.45,
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    result = propagate_threat_memory_db(
        memory_id=memory_id,
        max_confidence=max_confidence,
    )

    refresh_result = None

    subject_id = result.get("subject_id")

    if subject_id:
        refresh_result = refresh_adaptive_policy_for_seller(
            subject_id
        )

    result["adaptive_refresh"] = refresh_result

    return result


@app.post("/internal/threat-memory/decay")
def decay_threat_memory(
    scope: str | None = None,
    subject_id: str | None = None,
    min_age_seconds: int = 86400,
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    result = decay_threat_memory_db(
        scope=scope,
        subject_id=subject_id,
        min_age_seconds=min_age_seconds,
    )

    refresh_result = None

    if subject_id:
        refresh_result = refresh_adaptive_policy_for_seller(
            subject_id
        )

    result["adaptive_refresh"] = refresh_result

    return result


@app.get("/admin/threat-memory")
def admin_threat_memory(
    scope: str | None = None,
    subject_id: str | None = None,
    limit: int = 50,
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    memory = get_active_threat_memory_db(
        scope=scope,
        subject_id=subject_id,
        limit=limit,
    )

    return {
        "status": "ok",
        "count": len(memory),
        "memory": memory,
    }


@app.post("/admin/seller-threat-forecast/{seller_id}")
def admin_seller_threat_forecast(
    seller_id: str,
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    seller = get_agent_db(seller_id)

    if not seller:
        return {
            "status": "invalid_seller",
            "message": "Seller not found.",
        }

    fingerprints = compute_seller_fingerprints_db(seller_id)
    graph = build_seller_graph_context_db(seller_id)
    related = find_related_sellers_db(seller_id)

    active_threat_memory = get_active_threat_memory_db(
        scope="seller",
        subject_id=seller_id,
        limit=25,
    )

    threat_context = {
        "seller": seller,
        "active_threat_memory": active_threat_memory,
        "fingerprints": fingerprints,
        "graph": graph,
        "related_sellers": related,
        "mission": "forecast_future_attack_vectors_and_guardrails",
        "principle": "advisory_only_protocol_decides",
    }

    forecast = forecast_seller_attack_vectors_with_groq(
        threat_context
    )

    memory_result = store_threat_forecast_db(
        scope="seller",
        subject_id=seller_id,
        forecast=forecast,
    )

    seller["foundation_verdict"] = json.dumps({
        "threat_forecast": forecast,
        "previous_foundation_verdict": seller.get("foundation_verdict"),
    })

    register_agent_db(seller)

    return {
        "status": "threat_forecast_complete",
        "seller_id": seller_id,
        "forecast": forecast,
        "memory_result": memory_result,
    }





def refresh_adaptive_policy_for_seller(seller_id):
    """
    Recompute graph, cluster and adaptive policy for a seller.
    Autonomous defense refresh.
    """
    seller = get_agent_db(seller_id)

    if not seller:
        from iat.api.db import get_seller_db

        seller = get_seller_db(seller_id)

    if not seller:
        return {
            "status": "invalid_seller",
            "message": "Seller not found.",
        }

    graph_result = enrich_seller_graph_db(seller_id)

    cluster = detect_seller_cluster_db(seller_id)

    cluster_snapshot = record_cluster_snapshot_db(
        cluster,
        snapshot_reason="adaptive_policy_refresh",
        source="refresh_adaptive_policy_for_seller",
    )

    cluster_forecast = compute_cluster_forecast_db(
        cluster.get("cluster_id")
    )

    threat_memory = get_active_threat_memory_db(
        scope="seller",
        subject_id=seller_id,
        limit=100,
    )

    policy = compute_adaptive_defense_policy_db(
        scope="seller",
        service=seller.get("service"),
        cluster=cluster,
        threat_memory=threat_memory,
    )

    return {
        "status": "adaptive_policy_refreshed",
        "seller_id": seller_id,
        "graph": graph_result,
        "cluster": cluster,
        "cluster_snapshot": cluster_snapshot,
        "cluster_forecast": cluster_forecast,
        "policy": policy,
    }



@app.post("/internal/adaptive-defense/refresh/{seller_id}")
def internal_refresh_adaptive_defense(
    seller_id: str,
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return refresh_adaptive_policy_for_seller(
        seller_id
    )


@app.post("/admin/compute-adaptive-policy/{seller_id}")
def admin_compute_adaptive_policy(
    seller_id: str,
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    seller = get_agent_db(seller_id)

    if not seller:
        return {
            "status": "invalid_seller",
            "message": "Seller not found.",
        }

    cluster = detect_seller_cluster_db(
        seller_id
    )

    threat_memory = get_active_threat_memory_db(
        scope="seller",
        subject_id=seller_id,
        limit=100,
    )

    result = compute_adaptive_defense_policy_db(
        scope="seller",
        service=seller.get("service"),
        cluster=cluster,
        threat_memory=threat_memory,
    )

    return result


@app.post("/admin/detect-seller-cluster/{seller_id}")
def admin_detect_seller_cluster(
    seller_id: str,
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    seller = get_agent_db(seller_id)

    if not seller:
        return {
            "status": "invalid_seller",
            "message": "Seller not found.",
        }

    result = detect_seller_cluster_db(seller_id)

    return result


@app.post("/admin/enrich-seller-graph/{seller_id}")
def admin_enrich_seller_graph(
    seller_id: str,
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    seller = get_agent_db(seller_id)

    if not seller:
        return {
            "status": "invalid_seller",
            "message": "Seller not found.",
        }

    result = enrich_seller_graph_db(seller_id)

    return result


@app.get("/admin/seller-graph/{seller_id}")
def admin_seller_graph(
    seller_id: str,
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    seller = get_agent_db(seller_id)

    if not seller:
        return {
            "status": "invalid_seller",
            "message": "Seller not found.",
        }

    graph = build_seller_graph_context_db(
        seller_id
    )

    return {
        "status": "graph_loaded",
        "seller_id": seller_id,
        "graph": graph,
    }


def apply_foundation_decision_gate(
    seller,
    advisory,
    pre_risk,
):
    """
    Sovereign protocol decision gate.
    Groq is advisory only. Foundation/protocol decides final status.
    """
    recommendation = str(
        advisory.get("recommended_action", "manual_review")
    ).lower()

    pre_score = float(
        pre_risk.get("pre_risk_score", 0)
        or advisory.get("risk_score", 0)
        or 0
    )

    seller_status = str(
        seller.get("seller_status", "")
        or ""
    ).lower()

    direct_sanction = seller_status in [
        "rejected",
        "suspended",
    ]

    reasons = pre_risk.get("reasons", []) or []

    direct_fraud_signals = [
        r for r in reasons
        if r in [
            "currently_sanctioned",
            "related_rejected_or_suspended_sellers",
            "existing_high_risk_score",
        ]
    ]

    if recommendation == "reject":
        if direct_sanction:
            return {
                "final_action": "reject",
                "reason": "seller_already_sanctioned",
                "pre_risk_score": pre_score,
                "groq_recommendation": recommendation,
            }

        if pre_score >= 0.70 and direct_fraud_signals:
            return {
                "final_action": "reject",
                "reason": "high_pre_risk_with_direct_fraud_signals",
                "pre_risk_score": pre_score,
                "groq_recommendation": recommendation,
            }

        return {
            "final_action": "manual_review",
            "reason": "groq_reject_downgraded_without_strong_protocol_evidence",
            "pre_risk_score": pre_score,
            "groq_recommendation": recommendation,
        }

    if recommendation == "approve":
        return {
            "final_action": "pending_foundation_decision",
            "reason": "groq_approve_requires_protocol_confirmation",
            "pre_risk_score": pre_score,
            "groq_recommendation": recommendation,
        }

    return {
        "final_action": "manual_review",
        "reason": "default_manual_review",
        "pre_risk_score": pre_score,
        "groq_recommendation": recommendation,
    }


@app.post("/admin/seller-risk-review/{seller_id}")
def admin_seller_risk_review(
    seller_id: str,
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    seller = get_agent_db(seller_id)

    if not seller:
        return {
            "status": "invalid_seller",
            "message": "Seller not found.",
        }

    related_sellers_context = find_related_sellers_db(seller_id)

    seller_metadata = seller.get("seller_metadata") or {}

    if isinstance(seller_metadata, str):
        try:
            seller_metadata = json.loads(seller_metadata)
        except Exception:
            seller_metadata = {}

    seller_profile = {
        "seller_id": seller.get("agent_id"),
        "related_sellers_context": related_sellers_context,
        "business_name": seller_metadata.get("business_name"),
        "service": seller.get("service"),
        "url": seller.get("url"),
        "wallet": seller.get("wallet"),
        "price": seller.get("price"),
        "stake_amount": seller.get("stake_amount"),
        "trust_tier": seller.get("trust_tier"),
        "seller_status": seller.get("seller_status"),
        "verification_status": seller.get("verification_status"),
        "risk_score": seller.get("risk_score"),
        "reputation": seller.get("reputation"),
        "product_description": seller_metadata.get("product_description"),
        "quality_claims": seller_metadata.get("quality_claims"),
        "refund_policy": seller_metadata.get("refund_policy"),
        "delivery_terms": seller_metadata.get("delivery_terms"),
        "proof_links": seller_metadata.get("proof_links"),
        "requested_price": seller_metadata.get("requested_price"),
        "capabilities": seller.get("capabilities"),
        "specialties": seller.get("specialties"),
        "seller_metadata": seller_metadata,
    }

    pre_risk = compute_seller_pre_risk_score(
        seller,
        related_sellers_context,
    )

    pre_risk_score = float(
        pre_risk.get("pre_risk_score", 0)
        or 0
    )

    # Scalable architecture:
    # Cheap deterministic filters first.
    # AI review only if needed.

    if pre_risk_score < 0.25:
        advisory = {
            "provider": "pre_risk_engine",
            "seller_risk_level": "low",
            "risk_score": pre_risk_score,
            "recommended_action": "manual_review",
            "reasons": pre_risk.get("reasons", []),
            "red_flags": [],
            "missing_evidence": [],
            "confidence": 0.95,
            "groq_skipped": True,
        }

    else:
        advisory = analyze_seller_risk_with_groq(
            seller_profile
        )

        advisory["pre_risk"] = pre_risk

    seller["foundation_verdict"] = json.dumps(advisory)

    groq_risk_score = float(
        advisory.get("risk_score", 0.5) or 0.5
    )

    seller["risk_score"] = groq_risk_score

    foundation_decision = apply_foundation_decision_gate(
        seller,
        advisory,
        pre_risk,
    )

    final_action = foundation_decision.get(
        "final_action",
        "manual_review",
    )

    advisory["foundation_decision"] = foundation_decision

    if final_action == "reject":
        seller["seller_status"] = "rejected"
        seller["available"] = False

    elif final_action == "manual_review":
        seller["seller_status"] = "manual_review"
        seller["available"] = False

    else:
        seller["seller_status"] = "pending_foundation_decision"
        seller["available"] = False

    register_agent_db(seller)

    adaptive_refresh = refresh_adaptive_policy_for_seller(
        seller_id
    )

    return {
        "status": "risk_review_complete",
        "seller_id": seller_id,
        "seller_status": seller.get("seller_status"),
        "risk_score": seller.get("risk_score"),
        "groq_advisory": advisory,
        "adaptive_refresh": adaptive_refresh,
    }


@app.post("/admin/seller-rehabilitate/{seller_id}")
def admin_seller_rehabilitate(
    seller_id: str,
    req: SellerRehabilitationRequest,
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    seller = get_agent_db(seller_id)

    if not seller:
        return {
            "status": "invalid_seller",
            "message": "Seller not found.",
        }

    if str(seller.get("agent_type", "")).lower() != "seller":
        return {
            "status": "invalid_agent_type",
            "message": "Only seller agents can be rehabilitated.",
        }

    seller_status = str(seller.get("seller_status", "")).lower()

    if seller_status not in ["suspended", "stake_required", "exposure_limited"]:
        return {
            "status": "not_eligible",
            "message": "Seller is not currently eligible for rehabilitation.",
            "seller_status": seller.get("seller_status"),
        }

    required_stake = float(
        seller.get("dynamic_stake_required")
        or seller.get("stake_required")
        or compute_seller_required_stake(seller)
        or 0
    )

    current_stake = float(seller.get("stake_amount", 0) or 0)

    if current_stake < required_stake:
        seller["available"] = False
        seller["seller_status"] = "stake_required"
        seller["foundation_verdict"] = (
            f"Rehabilitation denied. Seller must lock at least {required_stake} IAT."
        )

        register_agent_db(seller)

        return {
            "status": "stake_required",
            "seller_id": seller_id,
            "stake_amount": current_stake,
            "required_stake": required_stake,
            "message": seller["foundation_verdict"],
        }

    # Rehabilitation rule:
    # The seller can return, but exposure remains limited.
    # Trust must be earned again slowly through successful executions.
    seller["seller_status"] = "active"
    seller["verification_status"] = "foundation_verified"
    seller["available"] = bool(req.available)
    seller["foundation_verified_at"] = int(time.time())
    seller["foundation_verdict"] = (
        req.verdict
        or "Seller rehabilitated after satisfying elevated stake requirement."
    )

    current_exposure = float(
        seller.get("max_order_value", 0)
        or seller.get("stake_amount", 0)
        or 0
    )

    # Do not restore full capacity instantly.
    seller["max_order_value"] = round(
        min(current_exposure, current_stake),
        6,
    )

    seller["buyer_access"] = 0
    seller["web_access"] = 0
    seller["raw_prompt_access"] = 0

    register_agent_db(seller)

    return {
        "status": "seller_rehabilitated",
        "seller_id": seller_id,
        "seller_status": seller.get("seller_status"),
        "available": bool(seller.get("available")),
        "stake_amount": current_stake,
        "required_stake": required_stake,
        "max_order_value": seller.get("max_order_value"),
        "risk_score": seller.get("risk_score"),
        "foundation_verdict": seller.get("foundation_verdict"),
    }


@app.post("/admin/seller-review/{seller_id}")
def admin_seller_review(seller_id: str, req: SellerReviewRequest, x_api_key: str | None = Header(default=None)):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    agent = get_agent_db(seller_id)

    if not agent:
        return {
            "status": "invalid_seller",
            "message": "Seller not found.",
        }

    if str(agent.get("agent_type", "")).lower() != "seller":
        return {
            "status": "rejected",
            "message": "Only seller agents can be reviewed through this endpoint.",
        }

    action = str(req.action or "").lower().strip()
    now = int(time.time())

    if action == "approve":
        agent["seller_status"] = "active"
        agent["verification_status"] = "foundation_verified"
        agent["available"] = True if req.available is None else bool(req.available)
        agent["foundation_verified_at"] = now
        agent["foundation_verdict"] = req.verdict or "Approved by protocol foundation review."
        agent["trust_tier"] = req.trust_tier or agent.get("trust_tier") or "verified"

    elif action == "reject":
        agent["seller_status"] = "rejected"
        agent["verification_status"] = "rejected"
        agent["available"] = False
        agent["foundation_verified_at"] = now
        agent["foundation_verdict"] = req.verdict or "Rejected by protocol foundation review."

    elif action == "suspend":
        agent["seller_status"] = "suspended"
        agent["verification_status"] = agent.get("verification_status") or "unverified"
        agent["available"] = False
        agent["foundation_verified_at"] = now
        agent["foundation_verdict"] = req.verdict or "Suspended by protocol foundation review."

    else:
        return {
            "status": "error",
            "message": "Invalid action. Use approve, reject, or suspend.",
        }

    if req.risk_score is not None:
        agent["risk_score"] = float(req.risk_score)

    # Critical security invariants:
    # sellers never get buyer access, web access, or raw prompt access.
    agent["buyer_access"] = 0
    agent["web_access"] = 0
    agent["raw_prompt_access"] = 0

    required_stake = compute_seller_required_stake(agent)
    current_stake = float(agent.get("stake_amount", 0) or 0)
    max_order_value = compute_max_order_value(agent)
    requested_price = float(agent.get("price", 0) or 0)

    agent["stake_required"] = required_stake
    agent["max_order_value"] = max_order_value

    if action == "approve" and current_stake < required_stake:
        agent["available"] = False
        agent["seller_status"] = "stake_required"
        agent["foundation_verdict"] = (
            f"Foundation verified, but seller must lock at least {required_stake} IAT before activation."
        )

    elif action == "approve" and requested_price > max_order_value:
        agent["available"] = False
        agent["seller_status"] = "exposure_limited"
        agent["foundation_verdict"] = (
            f"Foundation verified, but requested price {requested_price} IAT exceeds current max exposure {max_order_value} IAT."
        )

    register_agent_db(agent)

    return {
        "status": "seller_reviewed",
        "seller_id": seller_id,
        "action": action,
        "seller_status": agent.get("seller_status"),
        "verification_status": agent.get("verification_status"),
        "available": bool(agent.get("available")),
        "buyer_access": False,
        "web_access": False,
        "raw_prompt_access": False,
        "foundation_verdict": agent.get("foundation_verdict"),
    }


@app.post("/seller/register-legacy")
def seller_register_legacy(req: LegacySellerRegisterRequest):
    now = int(time.time())

    seller_metadata = {
        "business_name": req.business_name,
        "product_description": req.product_description,
        "quality_claims": req.quality_claims,
        "refund_policy": req.refund_policy,
        "delivery_terms": req.delivery_terms,
        "proof_links": req.proof_links,
        "requested_price": req.requested_price,
        "registered_via": "seller_register_v2",
        "registered_at": now,
    }

    agent = {
        "agent_id": req.seller_id,
        "service": req.service,
        "url": req.url,
        "wallet": req.wallet,
        "price": req.requested_price,
        "reputation": 0.5,
        "available": False,
        "agent_type": "seller",
        "stake_amount": req.stake_amount,
        "stake_required": max(10, req.requested_price * 0.2),
        "trust_tier": "pending",
        "capabilities": req.capabilities,
        "specialties": req.specialties,
        "seller_status": "pending_review",
        "verification_status": "unverified",
        "seller_metadata": seller_metadata,
        "buyer_access": 0,
        "web_access": 0,
        "raw_prompt_access": 0,
        "foundation_verified_at": None,
        "foundation_verdict": None,
    }

    register_agent_db(agent)

    return {
        "status": "pending_review",
        "seller_id": req.seller_id,
        "message": "Seller registered. The protocol foundation layer must verify this seller before activation.",
        "buyer_access": False,
        "web_access": False,
        "raw_prompt_access": False,
        "next_step": {
            "action": "foundation_review",
            "message": "A foundation verification process must approve the seller before it can participate in protocol-mediated execution.",
        },
    }


@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "IAT Protocol API is running",
    }


@app.get("/services")
def list_services():
    return {
        "status": "ok",
        "services": SERVICES,
    }


def refresh_agent_market_gate(agent_id):
    agent = get_agent_db(agent_id)

    if not agent:
        return None

    updated_agent = apply_seller_stake_gate(agent)
    register_agent_db(updated_agent)

    return get_agent_db(agent_id)


def compute_max_order_value(agent):
    stake_amount = float(agent.get("stake_amount", 0) or 0)
    reputation = float(agent.get("reputation", 0.5) or 0.5)
    risk_score = float(agent.get("risk_score", 0) or 0)

    trust_tier = str(agent.get("trust_tier", "free") or "free").lower()

    trust_multiplier = {
        "free": 2.0,
        "pending": 1.0,
        "verified": 8.0,
        "premium": 15.0,
        "institutional": 30.0,
    }.get(trust_tier, 2.0)

    reputation_multiplier = max(0.25, reputation)

    risk_penalty = max(0.10, 1.0 - risk_score)

    max_value = (
        stake_amount
        * trust_multiplier
        * reputation_multiplier
        * risk_penalty
    )

    policy = get_active_adaptive_policy_db(
        scope="seller",
        service=agent.get("service"),
    )

    if policy:
        exposure_multiplier = float(
            policy.get("exposure_multiplier", 1.0)
            or 1.0
        )

        max_value *= exposure_multiplier

    return round(max_value, 6)


def compute_seller_required_stake(agent):
    price = float(
        agent.get("price")
        or agent.get("requested_price")
        or 0
    )

    seller_metadata = agent.get("seller_metadata") or {}

    if isinstance(seller_metadata, str):
        try:
            import json
            seller_metadata = json.loads(seller_metadata)
        except Exception:
            seller_metadata = {}

    declared_product_value = float(
        seller_metadata.get("product_value_iat")
        or seller_metadata.get("estimated_value_iat")
        or price
        or 0
    )

    service = agent.get("service", "")

    risk_score = float(
        agent.get("risk_score", 0)
        or 0
    )

    trust_tier = str(agent.get("trust_tier", "free") or "free").lower()

    minimum_stake = 10.0

    # Capital-efficient collateral:
    # Stake is an entry/security bond, not full insurance.
    base_ratio = 0.05

    service_risk_multiplier = {
        "web_research": 1.0,
        "risk_report": 1.25,
        "financial_analysis": 1.5,
        "trading_signal": 2.5,
        "high_value_execution": 3.0,
    }.get(service, 1.0)

    trust_discount = {
        "free": 1.0,
        "pending": 1.25,
        "verified": 0.75,
        "premium": 0.50,
        "institutional": 0.35,
    }.get(trust_tier, 1.0)

    risk_multiplier = 1.0 + (risk_score * 3.0)

    economic_value = max(price, declared_product_value)

    required = max(
        minimum_stake,
        economic_value
        * base_ratio
        * service_risk_multiplier
        * trust_discount
        * risk_multiplier
    )

    return round(required, 6)


def apply_seller_stake_gate(agent):
    agent_type = agent.get("agent_type", "seller")

    if agent_type == "foundation":
        agent["available"] = True
        agent["stake_required"] = 0
        agent["max_order_value"] = None
        return agent

    stake_amount = float(agent.get("stake_amount", 0) or 0)

    protocol_required = compute_seller_required_stake(agent)
    seller_declared_required = float(agent.get("stake_required", 0) or 0)
    stake_required = max(protocol_required, seller_declared_required)

    agent["stake_required"] = stake_required

    max_order_value = compute_max_order_value(agent)
    agent["max_order_value"] = max_order_value

    price = float(agent.get("price", 0) or 0)

    if stake_amount < stake_required:
        agent["available"] = False
        agent["trust_tier"] = "stake_required"
    elif price > max_order_value:
        agent["available"] = False
        agent["trust_tier"] = "capacity_exceeded"
    else:
        agent["available"] = bool(agent.get("available", True))
        agent["trust_tier"] = agent.get("trust_tier", "staked")

    return agent


@app.post("/register-agent")
def register_agent(req: RegisterAgentRequest, x_api_key: str | None = Header(default=None)):
    agent = req.model_dump()

    if agent.get("agent_type") == "foundation":
        if not require_admin_key(x_api_key):
            return {
                "status": "error",
                "message": "unauthorized_foundation_agent_registration",
            }

    agent = apply_seller_stake_gate(agent)
    register_agent_db(agent)

    public_agent = {
        "agent_id": agent.get("agent_id"),
        "service": agent.get("service"),
        "price": agent.get("price"),
        "reputation": agent.get("reputation"),
        "available": agent.get("available"),
        "agent_type": agent.get("agent_type"),
        "capabilities": agent.get("capabilities"),
        "specialties": agent.get("specialties"),
    }

    return {
        "status": "registered",
        "agent": public_agent,
    }


@app.post("/agent-heartbeat")
def agent_heartbeat(req: RegisterAgentRequest, x_api_key: str | None = Header(default=None)):
    agent = req.model_dump()

    existing_agent = get_agent_db(agent.get("agent_id"))

    if existing_agent and existing_agent.get("agent_type") == "foundation":
        if not require_admin_key(x_api_key):
            return {
                "status": "error",
                "message": "unauthorized_foundation_agent_update",
            }

    if agent.get("agent_type") == "foundation":
        if not require_admin_key(x_api_key):
            return {
                "status": "error",
                "message": "unauthorized_foundation_agent_registration",
            }

    agent = apply_seller_stake_gate(agent)
    register_agent_db(agent)

    return {
        "status": "heartbeat_ok",
        "agent_id": agent["agent_id"],
        "agent_type": agent.get("agent_type"),
        "available": agent.get("available"),
        "stake_required": agent.get("stake_required"),
        "timestamp": int(time.time()),
    }




@app.post("/admin/disable-localhost-agents")
def admin_disable_localhost_agents(x_api_key: str | None = Header(default=None)):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    import sqlite3
    from iat.api.db import DB_PATH

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT agent_id, url
        FROM agents
        WHERE url LIKE 'http://localhost:%'
           OR url LIKE 'http://127.0.0.1:%'
    """)
    rows = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        UPDATE agents
        SET available = 0
        WHERE url LIKE 'http://localhost:%'
           OR url LIKE 'http://127.0.0.1:%'
    """)
    affected = cur.rowcount

    conn.commit()
    conn.close()

    return {
        "status": "ok",
        "disabled_count": affected,
        "disabled_agents": rows,
    }



@app.post("/admin/reactivate-agent/{agent_id}")
def admin_reactivate_agent(agent_id: str, x_api_key: str | None = Header(default=None)):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    agent = reactivate_agent_db(agent_id)

    if not agent:
        return {
            "status": "not_found",
            "agent_id": agent_id,
        }

    return {
        "status": "ok",
        "message": "agent_reactivated",
        "agent": agent,
    }


@app.delete("/admin/delete-agent/{agent_id}")
def admin_delete_agent(agent_id: str, x_api_key: str | None = Header(default=None)):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    try:
        deleted = delete_agent_db(agent_id)
    except Exception as e:
        return {
            "status": "error",
            "agent_id": agent_id,
            "error": str(e),
        }

    if not deleted:
        return {
            "status": "not_found",
            "agent_id": agent_id,
        }

    return {
        "status": "ok",
        "deleted_agent": deleted,
    }



@app.post("/admin/delegate-stake")
def admin_delegate_stake(req: DelegationRequest, x_api_key: str | None = Header(default=None)):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    agent = get_agent_db(req.agent_id)

    if not agent:
        return {
            "status": "not_found",
            "agent_id": req.agent_id,
        }

    if req.amount <= 0:
        return {
            "status": "rejected",
            "reason": "invalid_amount",
        }

    delegation = create_agent_delegation_db({
        "delegation_id": req.delegation_id,
        "agent_id": req.agent_id,
        "delegator_wallet": req.delegator_wallet,
        "amount": req.amount,
        "status": "locked",
    })

    return {
        "status": "ok",
        "message": "delegation_locked",
        "delegation": delegation,
    }


@app.get("/agents/{agent_id}/delegations")
def agent_delegations(agent_id: str):
    return {
        "status": "ok",
        "agent_id": agent_id,
        "delegations": list_agent_delegations_db(agent_id),
    }


@app.get("/delegators/{delegator_wallet}/positions")
def delegator_positions(delegator_wallet: str):
    return {
        "status": "ok",
        "delegator_wallet": delegator_wallet,
        "positions": list_delegator_positions_db(delegator_wallet),
    }


@app.get("/agents")
def list_agents(x_api_key: str | None = Header(default=None)):
    agents = list_agents_db()

    if require_admin_key(x_api_key):
        return {
            "status": "ok",
            "visibility": "admin",
            "agents": agents,
        }

    public_agents = []

    for agent in agents:
        public_agents.append({
            "service": agent.get("service"),
            "price_iat": agent.get("price"),
            "reputation": agent.get("reputation"),
            "available": agent.get("available"),
            "agent_type": agent.get("agent_type"),
            "capabilities": agent.get("capabilities"),
            "specialties": agent.get("specialties"),
            "trust_tier": agent.get("trust_tier"),
        })

    return {
        "status": "ok",
        "visibility": "public",
        "agents": public_agents,
    }


@app.get("/marketplace")
def marketplace(x_api_key: str | None = Header(default=None)):
    agents = list_agents_db()
    now = int(time.time())
    timeout = 120

    listings = []

    for agent in agents:
        online = agent["available"] and (now - int(agent["updated_at"]) <= timeout)

        from iat.api.multi_exec import compute_agent_market_score

        market_score = compute_agent_market_score(agent)

        own_stake = float(agent.get("stake_amount", 0) or 0)
        delegated_stake_total = get_agent_delegated_stake_total_db(agent["agent_id"])

        # Delegated stake is useful, but capped to avoid rented trust / cartel abuse.
        effective_delegated_stake = min(
            delegated_stake_total,
            own_stake * 0.40,
        )

        listing = {
            "service": agent["service"],
            "price_iat": agent["price"],
            "reputation": agent["reputation"],
            "score": compute_agent_score(agent),
            "market_score": market_score,
            "routing_status": "eligible" if online and market_score > -999 else "not_eligible",
            "trust_tier": agent.get("trust_tier"),
            "stake_status": agent.get("stake_status"),
            "stake_amount": agent.get("stake_amount"),
            "delegated_stake_total": delegated_stake_total,
            "effective_delegated_stake": effective_delegated_stake,
            "delegated_stake_cap_ratio": 0.40,
            "stake_required": agent.get("stake_required"),
            "stake_slashed_total": agent.get("stake_slashed_total"),
            "risk_score": agent.get("risk_score"),
            "status": "online" if online else "offline",
            "source": "dynamic_registry",
            "updated_at": agent["updated_at"],
        }

        if require_admin_key(x_api_key):
            listing["agent_id"] = agent["agent_id"]
            listing["url"] = agent["url"]
            listing["wallet"] = agent["wallet"]

        listings.append(listing)

    listings = sorted(
        listings,
        key=lambda x: (x["service"], x["status"] != "online", -x["market_score"]),
    )

    return {
        "status": "ok",
        "marketplace": {
            "total_agents": len(listings),
            "online_agents": len([a for a in listings if a["status"] == "online"]),
            "services": sorted(list(set(a["service"] for a in listings))),
            "listings": listings,
        },
    }



@app.get("/network-economics")
def network_economics():
    return {
        "status": "ok",
        "economics": get_network_economics_db(),
    }


@app.get("/network-status")
def network_status():
    return {
        "status": "ok",
        "data": get_network_status_db(),
    }


@app.get("/stats")
def stats():
    return {
        "status": "ok",
        "stats": get_stats_db(),
    }


@app.get("/orders")
def list_orders():
    return {
        "status": "ok",
        "orders": list_orders_db(),
    }


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    order = get_order_db(order_id)

    if not order:
        return {
            "status": "invalid_order",
        }

    return {
        "status": "ok",
        "order": order,
    }



def detect_buyer_service(prompt: str):
    """
    Generic marketplace service detection.

    IAT must not hardcode vertical business categories here.
    Domain-specific matching belongs to capability routing and specialty routing.
    """
    return "web_research"


def describe_buyer_delivery(service: str, prompt: str):
    if service == "web_research":
        return "Une recherche structurée avec sources, comparaison, critères de qualité, liens utiles et recommandation finale."

    if service == "risk_report":
        return "Une analyse de risque structurée avec facteurs principaux, niveau de risque, justification et recommandation synthétique."

    if service == "market_sentiment":
        return "Une synthèse du sentiment de marché avec signaux dominants, biais de foule et conclusion exploitable."

    return "Un résultat structuré adapté à votre demande."



def detect_purchase_type(prompt: str):
    text = (prompt or "").lower()

    if any(w in text for w in ["car", "voiture", "vehicle", "occasion", "used car"]):
        return "used_car_search"

    if any(w in text for w in ["hotel", "hôtel", "travel", "trip", "stay", "paris"]):
        return "hotel_search"

    if any(w in text for w in ["restaurant", "food", "dinner", "lunch"]):
        return "restaurant_search"

    return "general_research"


def extract_basic_requirements(prompt: str):
    text = (prompt or "").lower()
    requirements = {}

    if "paris" in text:
        requirements["location"] = "Paris"
    if "lyon" in text:
        requirements["location"] = "Lyon"

    if "toyota" in text:
        requirements["brand"] = "Toyota"
    if "hybrid" in text or "hybride" in text:
        requirements["fuel"] = "hybrid"
    if "automatic" in text or "automatique" in text or "auto" in text:
        requirements["transmission"] = "automatic"
    if "manual" in text or "manuelle" in text:
        requirements["transmission"] = "manual"

    if "city" in text or "ville" in text:
        requirements["usage"] = "city"
    if "family" in text or "famille" in text:
        requirements["usage"] = "family"

    import re

    km = re.findall(r"(\d{2,6})\s?(km|kilometers|kilometres)", text)
    if km:
        requirements["max_mileage"] = float(km[0][0])

    years = re.findall(r"(20\d{2}|19\d{2})", text)
    if years:
        requirements["min_year"] = int(years[0])

    amounts = re.findall(r"(\d{3,6})\s?(€|eur|euro|iat)?", text)
    if amounts:
        requirements["budget"] = float(amounts[0][0])

    return requirements


def buyer_missing_requirements(prompt: str, purchase_type: str):
    known = extract_basic_requirements(prompt)

    required_by_type = {
        "used_car_search": [
            "budget",
            "location",
            "fuel",
            "max_mileage",
            "min_year",
            "transmission",
            "usage",
        ],
        "hotel_search": [
            "location",
            "dates",
            "budget",
            "number_of_people",
            "quality_level",
        ],
        "restaurant_search": [
            "location",
            "budget",
            "cuisine",
            "date_or_time",
            "number_of_people",
        ],
        "general_research": [
            "topic",
            "depth",
            "deadline",
        ],
    }

    questions_by_field = {
        "budget": "What is your maximum budget?",
        "location": "Which city or country should we search in?",
        "fuel": "Do you prefer petrol, diesel, hybrid, electric, or no preference?",
        "max_mileage": "What maximum mileage do you accept?",
        "min_year": "What is the minimum year you want?",
        "transmission": "Do you want manual, automatic, or no preference?",
        "usage": "What is the main use: city, family, commuting, business, or long trips?",
        "dates": "What dates do you need?",
        "number_of_people": "How many people is this for?",
        "quality_level": "Do you prefer budget, balanced value, premium, or luxury?",
        "cuisine": "What cuisine or food style do you prefer?",
        "date_or_time": "For what date or time?",
        "topic": "What exact topic should be researched?",
        "depth": "Do you want a quick summary or a deep report?",
        "deadline": "When do you need the result?",
    }

    required = required_by_type.get(purchase_type, [])
    missing = [field for field in required if field not in known]

    return {
        "known_requirements": known,
        "missing_requirements": missing,
        "questions": [questions_by_field[f] for f in missing if f in questions_by_field],
    }



def buyer_topic_changed(previous_session, new_intent):
    if not previous_session or not new_intent:
        return False

    old_goal = str(previous_session.get("goal") or "").lower()
    old_type = str(previous_session.get("purchase_type") or "").lower()

    new_goal = str(new_intent.get("goal") or "").lower()
    new_type = str(new_intent.get("purchase_type") or "").lower()

    if not old_goal or not new_goal:
        return False

    same_type = old_type and new_type and old_type == new_type

    old_tokens = set(old_goal.replace(",", " ").split())
    new_tokens = set(new_goal.replace(",", " ").split())

    overlap = len(old_tokens.intersection(new_tokens)) / max(len(old_tokens.union(new_tokens)), 1)

    if not same_type and overlap < 0.20:
        return True

    return False


@app.post("/buyer/preview")
def buyer_preview(req: BuyerPreviewRequest):
    if is_buyer_banned_db(req.buyer_wallet):
        return {
            "status": "rejected",
            "message": "This wallet is not eligible to use the service currently.",
        }

    cleanup_expired_buyer_sessions_db(ttl_seconds=300)

    session_id = req.session_id or str(uuid.uuid4())

    previous_session = get_buyer_conversation_session_db(
        session_id,
        req.buyer_wallet,
        ttl_seconds=300,
    )

    intent = normalize_buyer_intent(
        req.prompt,
        previous_context=previous_session,
    )

    if buyer_topic_changed(previous_session, intent):
        session_id = str(uuid.uuid4())
        previous_session = None
        intent = normalize_buyer_intent(req.prompt)

    intent = merge_buyer_intent_with_session(
        previous_session,
        intent,
        req.prompt,
    )

    prompt_l = str(req.prompt or "").lower()

    # Buyer preference correction layer.
    # Generic: interprets quality/speed/trust/consensus language without
    # hardcoding vertical domains.
    if any(w in prompt_l for w in ["safest", "safe", "safety", "lowest risk", "risk-averse"]):
        intent["execution_strategy"] = "safest"

    if any(w in prompt_l for w in ["premium", "best quality", "highest quality", "deep"]):
        intent["quality_preference"] = "premium"

    if any(w in prompt_l for w in ["strict consensus", "strong consensus", "verified by multiple", "multi-agent consensus"]):
        intent["consensus_preference"] = "strict"

    if any(w in prompt_l for w in ["fast", "quick", "asap", "urgent"]):
        intent["max_latency_preference"] = "fast"

    if any(w in prompt_l for w in ["cheapest", "lowest price", "budget"]):
        intent["execution_strategy"] = "cheapest"

    save_buyer_conversation_session_db(
        session_id,
        req.buyer_wallet,
        {
            "goal": intent.get("goal"),
            "requirements": intent.get("requirements", {}),
            "purchase_type": intent.get("purchase_type"),
            "required_capabilities": intent.get("required_capabilities", []),
            "preferred_specialties": intent.get("preferred_specialties", []),
            "messages": intent.get("messages", []),
            "urgency": intent.get("urgency"),
            "quality_preference": intent.get("quality_preference"),
            "updated_from_prompt": req.prompt,
        }
    )

    clarification_questions = intent.get("questions") or []
    missing_requirements = intent.get("missing_requirements") or []

    # After merging session memory, remove missing fields already known.
    known_requirements = intent.get("requirements") or {}

    # Heuristic enrichment for general research clarification.
    # The LLM may understand the request but still return empty requirements.
    prompt_l = req.prompt.lower()
    goal_l = str(intent.get("goal") or "").lower()
    combined_l = f"{prompt_l} {goal_l}"

    purchase_type_l = str(intent.get("purchase_type") or "").lower()

    if purchase_type_l == "general_research":
        if "topic" not in known_requirements:
            if any(word in combined_l for word in ["btc", "bitcoin", "crypto", "liquidity", "sentiment", "risk", "market"]):
                known_requirements["topic"] = req.prompt

        if "depth" not in known_requirements:
            if any(word in combined_l for word in ["deep", "detailed", "full", "complete", "in-depth"]):
                known_requirements["depth"] = "deep"
            elif any(word in combined_l for word in ["quick", "summary", "brief"]):
                known_requirements["depth"] = "quick_summary"

        if "deadline" not in known_requirements:
            if any(word in combined_l for word in ["today", "now", "asap", "short-term", "short term"]):
                known_requirements["deadline"] = "today"

        intent["requirements"] = known_requirements

    aliases = {
        "budget": ["budget", "price", "price_range"],
        "country/location": ["country", "location", "region"],
        "location": ["country", "location", "region"],
        "intended usage": ["usage", "intended_usage"],
        "usage": ["usage", "intended_usage"],
        "main priorities": ["priorities", "battery_life", "camera", "storage"],
    }

    filtered_missing = []

    for field in missing_requirements:
        keys = aliases.get(field, [field])
        if not any(k in known_requirements for k in keys):
            filtered_missing.append(field)

    missing_requirements = filtered_missing

    if not missing_requirements:
        clarification_questions = []

    if missing_requirements or clarification_questions:

        save_buyer_conversation_session_db(
            session_id,
            req.buyer_wallet,
            {
                "goal": intent.get("goal"),
                "requirements": intent.get("requirements", {}),
                "purchase_type": intent.get("purchase_type"),
                "required_capabilities": intent.get("required_capabilities", []),
                "preferred_specialties": intent.get("preferred_specialties", []),
                "messages": intent.get("messages", []),
                "urgency": intent.get("urgency"),
                "quality_preference": intent.get("quality_preference"),
                "updated_from_prompt": req.prompt,
            }
        )

        return {
            "status": "needs_clarification",
            "protocol_language": intent.get("protocol_language", "en"),
            "session_id": session_id,
            "session_ttl_seconds": 300,
            "buyer_summary": {
                "request_understood": req.prompt,
                "detected_purchase_type": intent.get("purchase_type"),
                "goal": intent.get("goal"),
                "known_requirements": intent.get("requirements", {}),
                "missing_requirements": missing_requirements,
                "questions": clarification_questions,
                "confidence": intent.get("confidence"),
                "message": "We need a few more details to optimize routing and recommendation quality.",
            },
        }

    purchase_type = str(intent.get("purchase_type", "") or "").lower()

    service_mapping = {
        "car": "web_research",
        "used_car": "web_research",
        "used_car_search": "web_research",
        "vehicle": "web_research",
        "hotel": "web_research",
        "hotel_search": "web_research",
        "restaurant": "web_research",
        "restaurant_search": "web_research",
        "market_sentiment": "market_sentiment",
        "risk_report": "web_research",
    }

    service = service_mapping.get(
        purchase_type,
        detect_buyer_service(req.prompt),
    )

    agents = get_agents_for_service_db(service)

    if req.max_price is not None:
        agents = [
            a for a in agents
            if float(a.get("price", 0) or 0) <= float(req.max_price)
        ]

    available_agents = [
        a for a in agents
        if bool(a.get("available", True))
    ]

    from iat.api.multi_exec import (
        infer_required_capabilities,
        compute_capability_match_score,
        compute_specialty_match_score,
        compute_agent_market_score,
        compute_agent_trust_score,
        compute_buyer_agent_score,
        parse_json_list,
    )

    buyer_context = {
        "protocol_language": intent.get("protocol_language", "en"),
        "purchase_type": intent.get("purchase_type"),
        "goal": intent.get("goal"),
    }

    routing_order = {
        "query": req.prompt,
        "service": service,
        "buyer_intent": intent,
        "requirements": intent.get("requirements", {}),
        "buyer_context": buyer_context,
    }

    save_buyer_conversation_session_db(
        session_id,
        req.buyer_wallet,
        {
            "query": req.prompt,
            "service": service,
            "buyer_intent": intent,
            "goal": intent.get("goal"),
            "requirements": intent.get("requirements", {}),
            "purchase_type": intent.get("purchase_type"),
            "required_capabilities": intent.get("required_capabilities", []),
            "preferred_specialties": intent.get("preferred_specialties", []),
            "messages": intent.get("messages", []),
            "urgency": intent.get("urgency"),
            "quality_preference": intent.get("quality_preference"),
            "buyer_context": buyer_context,
            "updated_from_prompt": req.prompt,
        }
    )

    routing_preview = {
        "required_capabilities": infer_required_capabilities(routing_order),
        "top_candidate_agents": [
            {
                "agent_id": a.get("agent_id"),
                "capability_score": compute_capability_match_score(a, routing_order),
                "specialty_score": compute_specialty_match_score(a, routing_order),
                "market_score": compute_agent_market_score(a),
            }
            for a in sorted(
                available_agents,
                key=lambda x: (
                    compute_capability_match_score(x, routing_order),
                    compute_specialty_match_score(x, routing_order),
                    compute_agent_market_score(x),
                ),
                reverse=True,
            )[:5]
        ],
    }

    if not available_agents:
        return {
            "status": "no_offer_available",
            "buyer_summary": {
                "request_understood": req.prompt,
                "detected_service": service,
                "intent": intent,
                "reason": "Your request was understood, but no active provider is currently available for this category under the requested constraints.",
                "recommended_next_step": "Try a higher maximum price, broaden the criteria, or retry when more providers are available.",
            },
        }

    from iat.api.multi_exec import compute_agent_market_score

    strategy = str(intent.get("execution_strategy") or "balanced").lower()

    ranked = sorted(
        available_agents,
        key=lambda a: compute_buyer_agent_score(a, routing_order),
        reverse=True,
    )

    best = ranked[0]

    save_buyer_conversation_session_db(
        session_id,
        req.buyer_wallet,
        {
            "query": req.prompt,
            "service": service,
            "buyer_intent": intent,
            "goal": intent.get("goal"),
            "requirements": intent.get("requirements", {}),
            "purchase_type": intent.get("purchase_type"),
            "required_capabilities": intent.get("required_capabilities", []),
            "preferred_specialties": intent.get("preferred_specialties", []),
            "messages": intent.get("messages", []),
            "urgency": intent.get("urgency"),
            "quality_preference": intent.get("quality_preference"),
            "buyer_context": buyer_context,
            "selected_agent_id": best.get("agent_id"),
            "selected_price": float(best.get("price", 0) or 0),
            "updated_from_prompt": req.prompt,
        }
    )

    prices = [float(a.get("price", 0) or 0) for a in available_agents]

    recommended_price = float(best.get("price", 0) or 0)
    quality_score = round(min(max(float(best.get("reputation", 0.8) or 0.8), 0), 1), 3)
    value_score = round(compute_agent_market_score(best) / max(recommended_price, 0.001), 6)

    public_options = []

    for agent in ranked[:3]:
        agent_price = float(agent.get("price", 0) or 0)
        agent_quality = round(min(max(float(agent.get("reputation", 0.8) or 0.8), 0), 1), 3)

        public_options.append({
            "label": "Recommended provider" if agent == best else "Alternative provider",
            "price_iat": agent_price,
            "estimated_quality": "high" if agent_quality >= 0.85 else "medium",
            "quality_score": agent_quality,
            "strengths": [
                "Good match for the buyer request",
                "Available now",
                "Selected using capability, specialty, price, reputation and trust signals"
            ],
        })

    debug_payload = None

    if req.debug:
        debug_payload = {
            "selected_agent": best.get("agent_id"),
            "intent_strategy": intent.get("execution_strategy"),
            "intent_consensus": intent.get("consensus_preference"),
            "intent_quality": intent.get("quality_preference"),
            "routing_preview": routing_preview,
            "ranked_agents": [
                {
                    "agent_id": a.get("agent_id"),
                    "price": a.get("price"),
                    "reputation": a.get("reputation"),
                    "capability_score": compute_capability_match_score(a, routing_order),
                    "specialty_score": compute_specialty_match_score(a, routing_order),
                    "market_score": compute_agent_market_score(a),
                    "topic_score": compute_agent_topic_score_db(
                        a.get("agent_id"),
                        extract_topics_from_result(
                            {"data": {
                                "entities": [],
                                "claims": [],
                                "structured_signals": {},
                                "metrics": {},
                            }},
                            routing_order,
                        )
                    ),
                    "final_routing_score": compute_buyer_agent_score(a, routing_order),
                }
                for a in ranked[:5]
            ]
        }

    response = {
        "status": "preview",
        "session_id": session_id,
        "session_ttl_seconds": 300,
        "buyer_summary": {
            "request_understood": req.prompt,
            "expected_delivery": describe_buyer_delivery(service, req.prompt),
            "buyer_max_price_iat": req.max_price,
            "estimated_delivery_time": "A few seconds after confirmation",
        },
        "best_offer": {
            "price_iat": recommended_price,
            "estimated_quality": "high" if quality_score >= 0.85 else "medium",
            "quality_score": quality_score,
            "value_for_money": "excellent" if value_score >= 1 else "good",
            "why_this_offer": "This offer currently gives the best balance between request match, price, reputation, availability and reliability.",
        },
        "available_options": public_options,
        "next_step": {
            "action": "confirm_order",
            "message": "Confirm to prepare the order. Payment and delivery details will be handled by the protocol."
        }
    }

    if debug_payload:
        response["debug_routing"] = debug_payload

    return response



@app.post("/buyer/run-test")
def buyer_run_test(req: BuyerPreviewRequest):
    """
    Buyer-facing execution test.

    This endpoint is temporary for development, but its response shape is the
    target buyer experience: no internal agent IDs, no URLs, no wallets,
    no routing internals.
    """
    if is_buyer_banned_db(req.buyer_wallet):
        return {
            "status": "rejected",
            "message": "This wallet is not eligible to use the service currently.",
        }

    cleanup_expired_buyer_sessions_db(ttl_seconds=300)

    previous_session = get_buyer_conversation_session_db(
        req.session_id,
        req.buyer_wallet,
        ttl_seconds=300,
    )

    buyer_intent = normalize_buyer_intent(
        req.prompt,
        previous_context=previous_session,
    )

    if buyer_topic_changed(previous_session, buyer_intent):
        previous_session = None
        buyer_intent = normalize_buyer_intent(req.prompt)

    buyer_intent = merge_buyer_intent_with_session(
        previous_session,
        buyer_intent,
        req.prompt,
    )

    requirements = buyer_intent.get("requirements") or {}

    query_l = str(req.prompt or "").lower()
    goal_l = str(buyer_intent.get("goal") or "").lower()
    combined_l = f"{query_l} {goal_l}"

    if str(buyer_intent.get("purchase_type") or "").lower() == "general_research":
        if "topic" not in requirements:
            requirements["topic"] = req.prompt

        if "depth" not in requirements:
            if any(word in combined_l for word in ["deep", "detailed", "full", "complete", "in-depth"]):
                requirements["depth"] = "deep"
            elif any(word in combined_l for word in ["quick", "summary", "brief"]):
                requirements["depth"] = "quick_summary"

        if "deadline" not in requirements:
            if any(word in combined_l for word in ["today", "now", "asap", "short-term", "short term"]):
                requirements["deadline"] = "today"

        buyer_intent["requirements"] = requirements

    missing = []
    for field in ["topic", "depth", "deadline"]:
        if field not in requirements:
            missing.append(field)

    if missing:
        questions = {
            "topic": "What exact topic should be researched?",
            "depth": "Do you want a quick summary or a deep report?",
            "deadline": "When do you need the result?",
        }

        return {
            "status": "needs_clarification",
            "message": "A few details are needed before preparing the best result.",
            "missing_requirements": missing,
            "questions": [questions[m] for m in missing],
        }

    service = detect_buyer_service(req.prompt)

    from iat.api.multi_exec import multi_call, select_best_result, select_top_agents, extract_topics_from_result, compute_required_agent_count
    from iat.api.db import get_agents_for_service_db, compute_agent_topic_score_db

    agents = get_agents_for_service_db(service)

    if req.max_price is not None:
        agents = [
            a for a in agents
            if float(a.get("price", 0) or 0) <= float(req.max_price)
        ]

    full_query = buyer_intent.get("goal") or req.prompt

    if requirements:
        full_query = f"{full_query}\nRequirements: {requirements}"

    order = {
        "order_id": "buyer_run_test",
        "query": full_query,
        "service": service,
        "tx_signature": "INTERNAL_BUYER_RUN_TEST",
        "buyer_intent": buyer_intent,
        "requirements": requirements,
        "buyer_context": {
            "protocol_language": buyer_intent.get("protocol_language", "en"),
            "purchase_type": buyer_intent.get("purchase_type"),
            "goal": buyer_intent.get("goal"),
        },
    }

    selected_agents = select_top_agents(
        agents,
        limit=compute_required_agent_count(order),
        order=order,
    )

    if not selected_agents:
        return {
            "status": "no_offer_available",
            "message": "No provider is currently available for this request.",
        }

    results = multi_call(selected_agents, order)
    best = select_best_result(results)

    if not best:
        return {
            "status": "failed",
            "message": "No provider could produce a usable result.",
        }

    delivery = best.get("final_buyer_delivery") or {}

    return {
        "status": delivery.get("status", "success"),
        "summary": delivery.get("summary"),
        "recommendations": delivery.get("recommendations", []),
        "final_recommendation": delivery.get("final_recommendation"),
        "confidence": delivery.get("confidence", 0.5),
        "sources": delivery.get("sources", []),
    }


def make_buyer_order_response(order_response):
    if not isinstance(order_response, dict):
        return {
            "status": "error",
            "message": "Order could not be prepared.",
        }

    if order_response.get("status") in ["error", "rejected", "expired", "invalid_session"]:
        return order_response

    order_id = order_response.get("order_id")
    price = order_response.get("price")
    payment_target_value = (
        order_response.get("seller_wallet")
        or order_response.get("payment_target")
    )

    return {
        "status": "order_created",
        "order_id": order_id,
        "amount_iat": price,
        "payment": {
            "token": "IAT",
            "amount": price,
            "to": payment_target_value,
            "memo": order_id,
        },
        "next_step": {
            "action": "pay_and_verify",
            "message": "Send the exact IAT amount to the protocol payment address, then submit the transaction signature for verification.",
        },
        "expires_in_seconds": ORDER_TTL,
    }


@app.post("/buyer/confirm")
def buyer_confirm(req: BuyerConfirmRequest):
    session = get_buyer_conversation_session_db(
        req.session_id,
        req.buyer_wallet,
        ttl_seconds=300,
    )

    if not session:
        return {
            "status": "invalid_session",
            "reason": "buyer_session_not_found",
        }

    order_req = OrderRequest(
        service=session.get("service"),
        query=session.get("query"),
        buyer_wallet=req.buyer_wallet,
        buyer_intent=session.get("buyer_intent"),
        requirements=session.get("requirements"),
        buyer_context=session.get("buyer_context"),
        locked_agent_id=session.get("selected_agent_id"),
    )

    return make_buyer_order_response(create_order(order_req, internal_call=True))



@app.post("/create-order")
def create_order(req: OrderRequest, x_api_key: str | None = Header(default=None), internal_call: bool = False):
    print("ESCROW ENV:", os.getenv("IAT_ESCROW_WALLET"))
    if not internal_call and not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    buyer_wallet = req.buyer_wallet

    if buyer_wallet and is_buyer_banned_db(buyer_wallet):
        return {
            "status": "rejected",
            "reason": "buyer_blacklisted",
            "buyer_wallet": buyer_wallet,
        }

    buyer_intent = req.buyer_intent
    requirements = req.requirements
    buyer_context = req.buyer_context

    # Create-order must be independently intelligent.
    # If called directly without preview context, normalize the buyer query here
    # so routing is consistent with buyer/preview.
    if not buyer_intent:
        buyer_intent = normalize_buyer_intent(req.query)

    if not requirements:
        requirements = buyer_intent.get("requirements") or {}

    # Same generic research enrichment used by buyer preview.
    query_l = str(req.query or "").lower()
    goal_l = str(buyer_intent.get("goal") or "").lower()
    combined_l = f"{query_l} {goal_l}"
    purchase_type_l = str(buyer_intent.get("purchase_type") or "").lower()

    if purchase_type_l == "general_research":
        if "topic" not in requirements:
            if any(word in combined_l for word in ["btc", "bitcoin", "crypto", "liquidity", "sentiment", "risk", "market"]):
                requirements["topic"] = req.query

        if "depth" not in requirements:
            if any(word in combined_l for word in ["deep", "detailed", "full", "complete", "in-depth"]):
                requirements["depth"] = "deep"
            elif any(word in combined_l for word in ["quick", "summary", "brief"]):
                requirements["depth"] = "quick_summary"

        if "deadline" not in requirements:
            if any(word in combined_l for word in ["today", "now", "asap", "short-term", "short term"]):
                requirements["deadline"] = "today"

        buyer_intent["requirements"] = requirements

    if not buyer_context:
        buyer_context = {
            "protocol_language": buyer_intent.get("protocol_language", "en"),
            "purchase_type": buyer_intent.get("purchase_type"),
            "goal": buyer_intent.get("goal"),
        }

    routing_order = {
        "query": req.query,
        "service": req.service,
        "buyer_intent": buyer_intent,
        "requirements": requirements,
        "buyer_context": buyer_context,
        "locked_agent_id": req.locked_agent_id,
    }

    seller = select_best_seller(req.service, order=routing_order)

    if seller is None:
        return {
            "status": "unknown_service",
        }

    order_id = str(uuid.uuid4())
    now = int(time.time())

    consensus_preference = str(
        (buyer_intent or {}).get("consensus_preference") or "standard"
    ).lower()

    execution_mode = (
        "foundation_consensus"
        if consensus_preference == "strict"
        else "foundation_supplier_pipeline"
    )

    order = {
        "order_id": order_id,
        "service": req.service,
        "query": req.query,
        "price": seller["price"],
        "seller_id": seller["seller_id"],
        "seller_wallet": payment_wallet_for(seller["seller_wallet"]),
        "actual_agent_wallet": seller["seller_wallet"],
        "payment_target": payment_target(),
        "seller_url": seller.get("url") or "",
        "seller_source": seller.get("source"),
        "created_at": now,
        "updated_at": now,
        "status": "created",
        "tx_signature": None,
        "delivered_at": None,
        "delivery_result": None,
        "buyer_secret": str(uuid.uuid4()),
        "buyer_wallet": buyer_wallet,
        "buyer_intent": buyer_intent,
        "requirements": requirements,
        "buyer_context": buyer_context,
        "foundation_context": {},
        "execution_mode": execution_mode,
        "execution_context": {
            "service": req.service,
            "requirements": requirements,
            "trusted_input_only": True,
        },
        "used": False,
    }

    create_order_db(order_id, order)

    return {
        "order_id": order_id,
        "buyer_secret":
    order["buyer_secret"],
        "price": seller["price"],
        "seller_id": seller["seller_id"],
        "seller_wallet": payment_wallet_for(seller["seller_wallet"]),
        "actual_agent_wallet": seller["seller_wallet"],
        "payment_target": payment_target(),
        "seller_url": seller.get("url") or "",
        "seller_source": seller.get("source"),
    }


@app.post("/verify-payment-base")
def verify_payment(req: VerifyPaymentRequest, x_api_key: str | None = Header(default=None), deliver: bool = True):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}
    order = get_order_db(req.order_id)

    if not order:
        return {
            "status": "invalid_order",
        }

    if order.get("used"):
        return {
            "status": "already_used",
        }

    if int(time.time()) - int(order["created_at"]) > ORDER_TTL:
        return {
            "status": "expired_order",
        }

    if is_tx_processed_db(req.tx_signature):
        buyer_wallet = order.get("buyer_wallet")
        banned_buyer = None

        if buyer_wallet:
            banned_buyer = ban_buyer_db(
                buyer_wallet,
                reason="replay_tx_attempt",
            )

        return {
            "status": "tx_already_processed",
            "buyer_wallet": buyer_wallet,
            "buyer_banned": bool(banned_buyer),
            "ban_reason": "replay_tx_attempt" if banned_buyer else None,
        }

    if not verify_tx_signature(req.tx_signature):
        buyer_wallet = order.get("buyer_wallet")
        banned_buyer = None

        if buyer_wallet:
            banned_buyer = ban_buyer_db(
                buyer_wallet,
                reason="invalid_tx_signature",
            )

        return {
            "status": "invalid_signature",
            "buyer_wallet": buyer_wallet,
            "buyer_banned": bool(banned_buyer),
            "ban_reason": "invalid_tx_signature" if banned_buyer else None,
        }

    tx_details = get_tx_details(req.tx_signature)
    transfer_info = extract_transfer_checked_info(tx_details)
    memo = extract_memo(tx_details)

    buyer_wallet = None
    if transfer_info:
        buyer_wallet = transfer_info.get("authority")

    if buyer_wallet:
        try:
            register_buyer_seen_db(buyer_wallet)
            update_order_buyer_wallet_db(req.order_id, buyer_wallet)
            order["buyer_wallet"] = buyer_wallet
        except Exception as e:
            print("Buyer tracking error:", e)

    if not transfer_info:
        return {
            "status": "invalid_payment",
            "reason": "no_transfer_checked_found",
        }

    expected_ata = str(
        get_associated_token_address(
            Pubkey.from_string(order["seller_wallet"]),
            Pubkey.from_string(IAT_MINT),
        )
    )

    destination_value = transfer_info.get("destination")
    mint_value = transfer_info.get("mint")

    sender_ok = True
    receiver_ok = destination_value == expected_ata
    mint_ok = mint_value == IAT_MINT

    amount = transfer_info.get("ui_amount")
    if amount is None:
        amount = transfer_info.get("ui_amount_string")

    if amount is None and transfer_info.get("amount") is not None:
        # SPL raw amount uses token decimals. IAT has 8 decimals.
        amount = float(transfer_info.get("amount")) / 100000000

    try:
        amount_ok = float(amount) == float(order["price"])
    except Exception:
        amount_ok = False

    memo_text = str(memo)
    memo_ok = order["order_id"] in memo_text

    # Phantom-compatible mode:
    # Some wallets do not attach a real on-chain memo instruction.
    # In that case, payment is accepted only if receiver, mint, amount,
    # order status and tx replay checks are valid.
    memo_missing = memo is None or memo_text == "None"
    memo_required = os.getenv("IAT_REQUIRE_PAYMENT_MEMO", "false").lower() == "true"

    if memo_missing and not memo_required:
        memo_ok = True

    if sender_ok and receiver_ok and mint_ok and amount_ok and memo_ok:
        if not deliver:
            return {
                "status": "paid",
                "service": order["service"],
                "seller_id": order.get("seller_id"),
                "seller_source": order.get("seller_source"),
                "new_reputation": None,
                "data": None,
            }

        result = deliver_service(order, req.tx_signature)

        delivery_failed = isinstance(result, dict) and result.get("error") is not None

        if delivery_failed:
            update_agent_reputation_db(order.get("seller_id"), success=False)
            return {
                "status": "delivery_failed",
                "service": order["service"],
                "seller_id": order.get("seller_id"),
                "seller_source": order.get("seller_source"),
                "error": result,
            }

        new_reputation = None

        save_processed_tx_db(req.tx_signature)
        update_order_delivered_db(req.order_id, req.tx_signature, result)

        return {
            "status": "paid",
            "service": order["service"],
            "seller_id": order.get("seller_id"),
            "seller_source": order.get("seller_source"),
            "new_reputation": new_reputation,
            "data": result,
        }

    return {
        "status": "invalid_payment",
        "checks": {
            "sender_ok": sender_ok,
            "receiver_ok": receiver_ok,
            "mint_ok": mint_ok,
            "amount_ok": amount_ok,
            "memo_ok": memo_ok,
            "expected_ata": expected_ata,
            "actual_destination": destination_value,
            "expected_price": order["price"],
            "actual_amount": amount,
            "expected_memo": order["order_id"],
            "actual_memo": memo_text,
        },
    }



def make_buyer_payment_response(result):
    if not isinstance(result, dict):
        return {
            "status": "error",
            "message": "Payment could not be verified.",
        }

    status = result.get("status")

    if status in ["paid", "consensus_delivered"]:
        data = result.get("data") or result.get("result") or {}

        # Consensus delivery may return the buyer delivery under result.
        if isinstance(data, dict) and data.get("status") == "consensus_delivered":
            consensus_strength = data.get("consensus_strength")
            delivery = data.get("result") or {}

            return {
                "status": "delivered",
                "delivery_mode": "foundation_consensus",
                "summary": delivery.get("summary"),
                "recommendations": delivery.get("recommendations", []),
                "final_recommendation": delivery.get("final_recommendation"),
                "confidence": delivery.get("confidence", 0.5),
                "consensus_strength": consensus_strength,
                "consensus_agents_count": data.get("consensus_agents_count"),
                "agents_called": data.get("agents_called", []),
                "sources": delivery.get("sources", []),
            }

        delivery = data.get("final_buyer_delivery") if isinstance(data, dict) else None
        consensus_strength = data.get("consensus_strength") if isinstance(data, dict) else None

        if isinstance(delivery, dict):
            return {
                "status": "delivered",
                "summary": delivery.get("summary"),
                "recommendations": delivery.get("recommendations", []),
                "final_recommendation": delivery.get("final_recommendation"),
                "confidence": delivery.get("confidence", 0.5),
                "consensus_strength": consensus_strength,
                "sources": delivery.get("sources", []),
            }

        return {
            "status": "delivered",
            "summary": "Payment verified and service delivered.",
            "result": data,
        }

    if status in ["invalid_order", "expired_order", "already_used"]:
        return {
            "status": status,
            "message": "The order is not eligible for payment verification.",
        }

    if status in ["invalid_signature", "tx_already_processed"]:
        return {
            "status": status,
            "message": "The submitted transaction cannot be accepted.",
        }

    if status == "invalid_payment":
        return {
            "status": "invalid_payment",
            "message": "Payment verification failed. Please check amount, token, destination and memo.",
        }

    if status == "delivery_failed":
        return {
            "status": "delivery_failed",
            "message": "Payment was verified, but delivery failed. The order should be retried or escalated.",
        }

    return {
        "status": status or "unknown",
        "message": "Payment verification completed with a non-standard status.",
    }


@app.post("/admin/test-consensus-delivery/{order_id}")
def admin_test_consensus_delivery(order_id: str, x_api_key: str | None = Header(default=None)):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    order = get_order_db(order_id)

    if not order:
        return {
            "status": "invalid_order",
        }

    result = deliver_service(order, "DEV_TEST_TX")

    return {
        "status": "ok",
        "order_id": order_id,
        "execution_mode": order.get("execution_mode"),
        "result": result,
    }


@app.post("/admin/debug-consensus-raw/{order_id}")
def admin_debug_consensus_raw(order_id: str, x_api_key: str | None = Header(default=None)):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    order = get_order_db(order_id)

    if not order:
        return {
            "status": "invalid_order",
        }

    from iat.api.multi_exec import (
        select_top_agents,
        multi_call,
    )

    agents = get_agents_for_service_db(order.get("service"))

    selected_agents = select_top_agents(
        agents,
        limit=2,
        order=order,
    )

    results = multi_call(selected_agents, order)

    return {
        "status": "ok",
        "selected_agents": [
            a.get("agent_id")
            for a in selected_agents
        ],
        "raw_results": results,
    }


@app.post("/admin/test-buyer-consensus/{order_id}")
def admin_test_buyer_consensus(order_id: str, x_api_key: str | None = Header(default=None)):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    order = get_order_db(order_id)

    if not order:
        return {
            "status": "invalid_order",
        }

    result = deliver_service(order, "DEV_TEST_TX")

    wrapped = {
        "status": "paid",
        "data": result,
    }

    return make_buyer_payment_response(wrapped)


@app.post("/buyer/verify-payment")
def buyer_verify_payment(req: VerifyPaymentRequest):
    result = verify_payment(
        req,
        x_api_key=os.getenv("IAT_ADMIN_API_KEY"),
        deliver=True,
    )

    return make_buyer_payment_response(result)


@app.post("/request")
def request_endpoint(payload: dict):
    query = payload.get("query") or payload.get("input")

    if not query:
        return {
            "status": "error",
            "message": "Missing query",
        }

    return {
        "status": "ok",
        "type": "request_routing",
        "input": query,
        "selected_service": "web_research",
        "query": query,
        "next_action": {
            "method": "market.buy",
            "service": "web_research",
            "query": query
        }
    }



@app.post("/multi-call-test")
def multi_call_test(payload: dict):
    from iat.api.multi_exec import multi_call, select_best_result, select_top_agents, extract_topics_from_result, compute_required_agent_count, compute_consensus
    from iat.api.db import get_agents_for_service_db, compute_agent_topic_score_db

    service = payload.get("service")
    query = payload.get("query")

    if not service:
        return {"error": "missing service"}

    agents = get_agents_for_service_db(service)

    order = {
        "order_id": "test",
        "query": query,
        "service": service,
        "buyer_intent": normalize_buyer_intent(query),
    }

    order["requirements"] = order["buyer_intent"].get("requirements") or {}

    selected_agents = select_top_agents(
        agents,
        limit=compute_required_agent_count(order),
        order=order,
    )

    results = multi_call(selected_agents, order)
    best = select_best_result(results)
    consensus = compute_consensus(results)

    return {
        "status": "ok",
        "agents_called": len(selected_agents),
        "selected_agents": [a.get("agent_id") for a in selected_agents],
        "results": results,
        "best": best,
        "consensus": consensus,
    }



def force_agent_into_selection(selected_agents, all_agents, forced_agent_id, limit=3):
    if not forced_agent_id:
        return selected_agents

    forced = None
    for agent in all_agents:
        if agent.get("agent_id") == forced_agent_id:
            forced = agent
            break

    if not forced:
        return selected_agents

    # Remove duplicate if already present
    selected_agents = [
        a for a in selected_agents
        if a.get("agent_id") != forced_agent_id
    ]

    # Put forced agent first for debug, then keep limit
    return [forced] + selected_agents[: max(0, limit - 1)]



def execute_onchain_slash(agent_id, amount, order_id):
    treasury_wallet = os.getenv("IAT_SLASH_TREASURY_WALLET")
    escrow_key = os.getenv("IAT_ESCROW_KEYPAIR_JSON") or os.getenv("IAT_ESCROW_KEYPAIR_PATH")

    if not treasury_wallet:
        return {
            "status": "skipped",
            "reason": "slash_treasury_not_configured",
        }

    if not escrow_key:
        return {
            "status": "skipped",
            "reason": "escrow_key_not_configured",
        }

    if not amount or float(amount) <= 0:
        return {
            "status": "skipped",
            "reason": "no_amount_to_slash",
        }

    try:
        tx = send_iat(
            escrow_key,
            treasury_wallet,
            float(amount),
            memo_text=f"SLASH:{agent_id}:{order_id}",
        )

        return {
            "status": "sent",
            "tx_signature": tx,
            "to": treasury_wallet,
            "amount": float(amount),
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }





def safe_send_iat(
    from_keypair,
    to_wallet,
    amount,
    memo_text,
    sender_wallet=None,
):
    """
    Protocol-safe IAT transfer wrapper.

    This is the financial safety layer above raw send_iat().
    It validates inputs, checks balance when possible, sends the tx,
    verifies that the signature exists on-chain, and always returns
    a structured result.
    """
    result = {
        "status": "created",
        "to_wallet": to_wallet,
        "amount_iat": float(amount or 0),
        "memo_text": memo_text,
        "sender_wallet": sender_wallet,
        "tx_signature": None,
        "verified_onchain": False,
        "error": None,
    }

    try:
        if not from_keypair:
            result["status"] = "blocked"
            result["reason"] = "from_keypair_missing"
            return result

        if not to_wallet:
            result["status"] = "blocked"
            result["reason"] = "recipient_wallet_missing"
            return result

        try:
            Pubkey.from_string(str(to_wallet))
        except Exception:
            result["status"] = "blocked"
            result["reason"] = "recipient_wallet_invalid"
            return result

        amount = float(amount or 0)

        if amount <= 0:
            result["status"] = "blocked"
            result["reason"] = "amount_must_be_positive"
            return result

        if sender_wallet:
            try:
                balance = get_iat_balance(sender_wallet)
                result["sender_balance_iat"] = balance

                if balance is not None and float(balance) < amount:
                    result["status"] = "blocked"
                    result["reason"] = "insufficient_sender_iat_balance"
                    return result
            except Exception as balance_error:
                result["balance_check_error"] = str(balance_error)

        tx_signature = send_iat(
            from_keypair,
            to_wallet,
            amount,
            memo_text=memo_text,
        )

        result["tx_signature"] = tx_signature

        if not tx_signature:
            result["status"] = "error"
            result["reason"] = "send_iat_returned_empty_signature"
            return result

        # Give RPC a short moment to index transaction.
        time.sleep(2)

        verified = verify_tx_signature(tx_signature)

        result["verified_onchain"] = bool(verified)

        if verified:
            result["status"] = "sent_verified"
            result["reason"] = "transaction_sent_and_verified"
        else:
            result["status"] = "sent_unverified"
            result["reason"] = "transaction_sent_but_not_yet_verified"

        return result

    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)
        result["reason"] = "safe_send_iat_exception"
        return result



def execute_escrow_split_release(
    escrow_key,
    treasury_wallet,
    winner_wallet,
    commission_amount,
    seller_payout_amount,
    order_id,
):
    onchain_enabled = str(
        os.getenv("IAT_ENABLE_ONCHAIN_SETTLEMENT", "false")
    ).lower() == "true"

    result = {
        "settlement_execution_type": "escrow_split_release",
        "onchain_settlement_enabled": onchain_enabled,
        "order_id": order_id,
        "treasury_wallet": treasury_wallet,
        "winner_wallet": winner_wallet,
        "commission_amount_iat": float(commission_amount or 0),
        "seller_payout_amount_iat": float(seller_payout_amount or 0),
        "commission_tx_signature": None,
        "seller_payout_tx_signature": None,
    }

    if not onchain_enabled:
        result["status"] = "dry_run_ready"
        result["reason"] = "IAT_ENABLE_ONCHAIN_SETTLEMENT_not_enabled"
        return result

    if not escrow_key:
        result["status"] = "blocked"
        result["reason"] = "escrow_key_missing"
        return result

    if not treasury_wallet:
        result["status"] = "blocked"
        result["reason"] = "treasury_wallet_missing"
        return result

    if not winner_wallet:
        result["status"] = "blocked"
        result["reason"] = "winner_wallet_missing"
        return result

    try:
        if float(commission_amount or 0) > 0:
            commission_result = safe_send_iat(
                escrow_key,
                treasury_wallet,
                float(commission_amount),
                memo_text=f"COMMISSION:{order_id}",
                sender_wallet=os.getenv("IAT_ESCROW_WALLET"),
            )

            result["commission_transfer"] = commission_result
            result["commission_tx_signature"] = commission_result.get("tx_signature")

        if float(seller_payout_amount or 0) > 0:
            seller_result = safe_send_iat(
                escrow_key,
                winner_wallet,
                float(seller_payout_amount),
                memo_text=f"PAYOUT:{order_id}",
                sender_wallet=os.getenv("IAT_ESCROW_WALLET"),
            )

            result["seller_transfer"] = seller_result
            result["seller_payout_tx_signature"] = seller_result.get("tx_signature")

        commission_ok = (
            float(commission_amount or 0) <= 0
            or (
                result.get("commission_transfer", {}).get("status")
                in ["sent_verified", "sent_unverified"]
            )
        )

        seller_ok = (
            float(seller_payout_amount or 0) <= 0
            or (
                result.get("seller_transfer", {}).get("status")
                in ["sent_verified", "sent_unverified"]
            )
        )

        if not commission_ok or not seller_ok:
            result["status"] = "partial_failure"
            result["reason"] = "one_or_more_transfers_failed"
            return result

        result["status"] = "sent"
        result["reason"] = "escrow_split_release_executed"
        return result

    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)
        return result




def authorize_settlement_release(order_id):
    foundation_decision_result = run_foundation_decision_db(order_id)

    fd = (
        foundation_decision_result.get("foundation_decision", {})
        if isinstance(foundation_decision_result, dict)
        else {}
    )

    verdict = fd.get("foundation_verdict")
    confidence = float(fd.get("decision_confidence", 0) or 0)

    signals = fd.get("foundation_verification_signals") or {}
    verified_count = len(signals.get("verified_claims") or [])
    rejected_count = len(signals.get("rejected_claims") or [])

    release_authorized = (
        verdict == "foundation_verified_with_evidence"
        and confidence >= 0.70
        and verified_count > 0
        and rejected_count == 0
    )

    return {
        "authorization_type": "foundation_settlement_authorization",
        "release_authorized": bool(release_authorized),
        "authorized_by": "foundation" if release_authorized else None,
        "authorization_reason": (
            "foundation_verified_with_sufficient_confidence"
            if release_authorized
            else "foundation_authorization_requirements_not_met"
        ),
        "order_id": order_id,
        "foundation_verdict": verdict,
        "decision_confidence": confidence,
        "verified_claim_count": verified_count,
        "rejected_claim_count": rejected_count,
        "foundation_decision": foundation_decision_result,
    }



def payout_winner_if_escrow(order, best, agents):
    """
    Settlement safety layer.

    Current role:
    - prevent payout path from crashing
    - centralize escrow payout decision
    - prepare protocol commission / treasury split

    This function does NOT release funds unless escrow signing credentials
    are explicitly configured.
    """
    order = order or {}
    best = best or {}
    agents = agents or []

    winner_id = best.get("agent_id")
    order_id = order.get("order_id")
    amount = float(order.get("price", 0) or 0)

    escrow_wallet = os.getenv("IAT_ESCROW_WALLET")
    escrow_key = (
        os.getenv("IAT_ESCROW_KEYPAIR_JSON")
        or os.getenv("IAT_ESCROW_KEYPAIR_PATH")
    )

    protocol_commission_rate = float(
        os.getenv("IAT_PROTOCOL_COMMISSION_RATE", "0.10")
    )

    protocol_commission_rate = min(
        max(protocol_commission_rate, 0.0),
        0.50,
    )

    protocol_commission_amount = round(
        amount * protocol_commission_rate,
        6,
    )

    seller_payout_amount = round(
        max(amount - protocol_commission_amount, 0.0),
        6,
    )

    winner_agent = None

    for agent in agents:
        if agent.get("agent_id") == winner_id:
            winner_agent = agent
            break

    winner_wallet = (
        (winner_agent or {}).get("wallet")
        or best.get("wallet")
    )

    def finalize_settlement(result):
        try:
            record = record_settlement_db(order_id, result)
            if record:
                result["settlement_record"] = record
        except Exception as exc:
            result["settlement_record_error"] = str(exc)
        return result

    settlement = {
        "settlement_type": "escrow_winner_payout",
        "winner_payment_status": "pending_escrow_release",
        "order_id": order_id,
        "winner_id": winner_id,
        "winner_wallet": winner_wallet,
        "gross_amount_iat": amount,
        "protocol_commission_rate": protocol_commission_rate,
        "protocol_commission_amount_iat": protocol_commission_amount,
        "seller_payout_amount_iat": seller_payout_amount,
        "escrow_wallet_configured": bool(escrow_wallet),
        "escrow_signing_configured": bool(escrow_key),
        "protocol_treasury_wallet": os.getenv("IAT_PROTOCOL_TREASURY_WALLET"),
        "release_policy": {
            "seller_cannot_self_release": True,
            "protocol_controls_release": True,
            "release_requires_consensus_passed": True,
            "release_requires_foundation_delivery": True,
        },
    }

    if not winner_id:
        settlement["winner_payment_status"] = "blocked_no_winner"
        settlement["reason"] = "winner_agent_missing"
        return finalize_settlement(settlement)

    if not winner_wallet:
        settlement["winner_payment_status"] = "blocked_no_winner_wallet"
        settlement["reason"] = "winner_wallet_missing"
        return finalize_settlement(settlement)

    if amount <= 0:
        settlement["winner_payment_status"] = "no_payment_due"
        settlement["reason"] = "zero_amount_order"
        return finalize_settlement(settlement)

    if not escrow_wallet:
        settlement["winner_payment_status"] = "direct_payment_mode_no_escrow_release"
        settlement["reason"] = "escrow_wallet_not_configured"
        return finalize_settlement(settlement)

    if not escrow_key:
        settlement["winner_payment_status"] = "pending_manual_escrow_release"
        settlement["reason"] = "escrow_signing_key_not_configured"
        return finalize_settlement(settlement)

    settlement_authorization = authorize_settlement_release(order_id)
    settlement["settlement_authorization"] = settlement_authorization

    if settlement_authorization.get("release_authorized") is not True:
        settlement["winner_payment_status"] = "blocked_foundation_authorization"
        settlement["reason"] = settlement_authorization.get(
            "authorization_reason",
            "foundation_authorization_failed",
        )
        return finalize_settlement(settlement)

    treasury_wallet = os.getenv("IAT_PROTOCOL_TREASURY_WALLET")

    settlement_execution = execute_escrow_split_release(
        escrow_key=escrow_key,
        treasury_wallet=treasury_wallet,
        winner_wallet=winner_wallet,
        commission_amount=protocol_commission_amount,
        seller_payout_amount=seller_payout_amount,
        order_id=order_id,
    )

    settlement["settlement_execution"] = settlement_execution

    if settlement_execution.get("status") == "sent":
        settlement["winner_payment_status"] = "released_onchain"
        settlement["reason"] = "escrow_split_release_sent"
    elif settlement_execution.get("status") == "dry_run_ready":
        settlement["winner_payment_status"] = "ready_for_onchain_release_dry_run"
        settlement["reason"] = "onchain_settlement_disabled_dry_run"
    else:
        settlement["winner_payment_status"] = "blocked_or_failed_onchain_release"
        settlement["reason"] = settlement_execution.get("reason") or settlement_execution.get("error")

    return finalize_settlement(settlement)



@app.post("/verify-payment-multicall")
@app.post("/verify-payment")
def verify_payment_multicall(req: VerifyPaymentRequest, x_api_key: str | None = Header(default=None)):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}
    base = verify_payment(req, x_api_key=x_api_key, deliver=False)
    if base.get("status") == "already_used":
        order = get_order_db(req.order_id)
        if order and order.get("delivery_result"):
            return order["delivery_result"]
        return base

    if base.get("status") != "paid":
        return base

    order = get_order_db(req.order_id)
    if not order:
        return {"status": "invalid_order"}

    agents = get_agents_for_service_db(order["service"])
    if not agents:
        return {"status": "no_agents_available"}

    from iat.api.multi_exec import multi_call, select_best_result, select_top_agents, extract_topics_from_result, compute_required_agent_count

    paid_order = dict(order)
    paid_order["tx_signature"] = req.tx_signature

    selected_agents = select_top_agents(
        agents,
        limit=compute_required_agent_count(order),
        order=order,
    )

    # DEBUG ONLY: force one agent into execution when env var is set.
    # Example on Render env:
    # IAT_FORCE_AGENT_ID=web_agent_malicious
    # FORCE_AGENT disabled in production
    forced_agent_id = None
    selected_agents = force_agent_into_selection(
        selected_agents,
        agents,
        forced_agent_id,
        limit=3,
    )

    results = multi_call(selected_agents, paid_order)
    best = select_best_result(results)

    from iat.api.multi_exec import compute_consensus

    consensus = compute_consensus(results)

    if not best:
        return {
            "status": "multicall_failed",
            "results": results,
        }

    final_result = {
        "status": "paid_multicall_success",
        "service": order["service"],
        "query": order.get("query"),
        "tx_signature": req.tx_signature,
        "agents_called": len(selected_agents),
        "payment_result": base,
        "results": results,
        "best": best,
        "consensus": consensus,
    }

# --- SLASH suspicious agents ---
    suspicious = consensus.get("suspicious_agents", [])

    # Prevent double slashing same agent in same order
    suspicious = list(dict.fromkeys(suspicious))

    slashing_events = []
    economic_volume_updates = []
    order_value = float(order.get("price", 0) or 0)

    # Honest/fraud value accounting
    for r in results:
        aid = r.get("agent_id")
        if not aid:
            continue

        if aid in suspicious:
            econ = update_agent_volume_stats_db(aid, order_value, honest=False)
            if econ:
                economic_volume_updates.append(econ)
        elif r.get("success"):
            econ = update_agent_volume_stats_db(aid, order_value, honest=True)
            if econ:
                economic_volume_updates.append(econ)

    for agent_id in suspicious:
        update_agent_reputation_db(agent_id, success=False)

        try:
            slash_info = slash_agent_stake_db(
                agent_id,
                slash_ratio=0.10,
                reason="consensus_suspicious_agent",
            )
            if slash_info:
                refreshed_agent = refresh_agent_market_gate(agent_id)

                onchain = execute_onchain_slash(
                    agent_id,
                    slash_info.get("slashed_amount", 0),
                    req.order_id,
                )
                slash_info["onchain_slash"] = onchain
                slash_info["agent_after_slash"] = refreshed_agent
                slashing_events.append(slash_info)
        except Exception as e:
            print("Stake slashing error:", e)

# --- payout logic ---
    winner_id = best.get("agent_id") if best else None
    winner_score = float(best.get("selection_score", 0) or 0) if best else 0
    winner_details = best.get("selection_score_details", {}) if best else {}
    winner_is_suspicious = winner_id in suspicious if winner_id else True

    consensus_passed = consensus.get("status") == "passed"

    # Weak pass rule:
    # If consensus is globally suspicious but the selected winner has a strong
    # final score and is not individually suspicious, allow payout.
    weak_pass = (
        not consensus_passed
        and best is not None
        and not winner_is_suspicious
        and winner_score >= 0.75
    )

    if not consensus_passed and not weak_pass:
        payout_info = {
            "winner_payment_status": "blocked_by_consensus",
            "reason": "consensus_not_reached",
            "consensus": consensus,
            "winner_id": winner_id,
            "winner_selection_score": winner_score,
            "winner_score_details": winner_details,
            "slashed_agents": suspicious,
            "stake_slashing_events": slashing_events,
        }

    elif weak_pass:
        payout_info = {
            "winner_payment_status": "payout_due_weak_consensus",
            "reason": "weak_consensus_manual_review",
            "consensus": consensus,
            "winner_id": winner_id,
            "winner_selection_score": winner_score,
            "winner_score_details": winner_details,
            "slashed_agents": suspicious,
            "stake_slashing_events": slashing_events,
            "consensus_status": consensus.get("status"),
            "weak_pass": True,
        }

    else:
        payout_info = payout_winner_if_escrow(order, best, agents)

        payout_info["slashed_agents"] = suspicious
        payout_info["stake_slashing_events"] = slashing_events
        payout_info["consensus_status"] = consensus.get("status")
        payout_info["weak_pass"] = False
        payout_info["winner_selection_score"] = winner_score
        payout_info["winner_score_details"] = winner_details

        winner_reputation = None
        if winner_id:
            winner_reputation = update_agent_reputation_db(winner_id, success=True)
        payout_info["winner_new_reputation"] = winner_reputation
    
    final_result["economic_volume_updates"] = economic_volume_updates
    final_result["settlement"] = payout_info

    # --- recompute dynamic metrics ---
    recomputed_agents = []

    processed_agent_ids = set()

    for r in results:
        aid = r.get("agent_id")

        if not aid or aid in processed_agent_ids:
            continue

        processed_agent_ids.add(aid)

        try:
            metrics = recompute_agent_metrics_db(aid)

            if metrics:
                recomputed_agents.append(metrics)

        except Exception as e:
            print("Recompute metrics error:", e)

    final_result["recomputed_agents"] = recomputed_agents

    # --- LEARNING LAYER (call + win stats) ---
    agent_ids = [a.get("agent_id") for a in selected_agents]
    winner_id = best.get("agent_id") if best else None

    latencies = {
        r.get("agent_id"): r.get("latency", 0)
        for r in results
        if r.get("agent_id")
    }

    try:
        update_agent_call_stats_db(agent_ids, winner_id, latencies=latencies)
    except Exception as e:
        print("Learning layer error:", e)

    try:
        save_processed_tx_db(req.tx_signature)
    except Exception as e:
        print("Processed tx save error:", e)

    update_order_delivered_db(req.order_id, req.tx_signature, final_result)

    return final_result









class AdminSettlementStatusUpdateRequest(BaseModel):
    settlement_id: str
    next_status: str
    reason: str = "admin_transition_test"
    commission_tx_signature: str | None = None
    seller_payout_tx_signature: str | None = None


@app.post("/admin/settlement/update-status")
def admin_update_settlement_status(
    req: AdminSettlementStatusUpdateRequest,
    request: Request,
):
    expected_key = os.getenv("IAT_ADMIN_API_KEY")
    provided_key = request.headers.get("x-api-key")

    if expected_key and provided_key != expected_key:
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return update_settlement_status_db(
        settlement_id=req.settlement_id,
        next_status=req.next_status,
        reason=req.reason,
        commission_tx_signature=req.commission_tx_signature,
        seller_payout_tx_signature=req.seller_payout_tx_signature,
    )


@app.get("/admin/settlement/validate-transition")
def admin_validate_settlement_transition(
    current_status: str,
    next_status: str,
    request: Request,
):
    expected_key = os.getenv("IAT_ADMIN_API_KEY")
    provided_key = request.headers.get("x-api-key")

    if expected_key and provided_key != expected_key:
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return validate_settlement_transition(
        current_status,
        next_status,
    )




@app.post("/admin/settlement/orchestrator/run-once")
def admin_run_settlement_orchestrator_once(
    limit: int = 50,
    request: Request = None,
):
    expected_key = os.getenv("IAT_ADMIN_API_KEY")
    provided_key = request.headers.get("x-api-key") if request else None

    if expected_key and provided_key != expected_key:
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return run_settlement_orchestrator_once_db(
        limit=limit,
    )



@app.get("/admin/settlements")
def admin_list_settlements(
    limit: int = 20,
    request: Request = None,
):
    expected_key = os.getenv("IAT_ADMIN_API_KEY")
    provided_key = request.headers.get("x-api-key") if request else None

    if expected_key and provided_key != expected_key:
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return {
        "status": "ok",
        "count": len(list_settlements_db(limit)),
        "settlements": list_settlements_db(limit),
    }



@app.post("/admin/test-settlement-safety")
def admin_test_settlement_safety(request: Request):
    expected_key = os.getenv("IAT_ADMIN_API_KEY")
    provided_key = request.headers.get("x-api-key")

    if expected_key and provided_key != expected_key:
        return {
            "status": "error",
            "message": "unauthorized",
        }

    order = {
        "order_id": "ADMIN_SETTLEMENT_TEST",
        "price": 1.2,
    }

    best = {
        "agent_id": "foundation_web_research_1",
        "wallet": "IAT_PROTOCOL_CORE",
    }

    agents = [
        {
            "agent_id": "foundation_web_research_1",
            "wallet": "IAT_PROTOCOL_CORE",
        }
    ]

    return {
        "status": "ok",
        "settlement": payout_winner_if_escrow(order, best, agents),
    }



@app.post("/admin/test-onchain-slash-agent/{agent_id}")
def admin_test_onchain_slash_agent(agent_id: str, request: Request, amount: float = 0.1):
    expected_key = os.getenv("IAT_ADMIN_API_KEY")
    provided_key = request.headers.get("x-api-key")

    if expected_key and provided_key != expected_key:
        return {
            "status": "error",
            "message": "unauthorized",
        }

    onchain = execute_onchain_slash(
        agent_id,
        amount,
        order_id="ADMIN_TEST",
    )

    return {
        "status": "ok",
        "agent_id": agent_id,
        "amount": amount,
        "onchain_slash": onchain,
    }


@app.post("/admin/test-slash-agent/{agent_id}")
def admin_test_slash_agent(agent_id: str, request: Request, slash_ratio: float = 0.10):
    expected_key = os.getenv("IAT_ADMIN_API_KEY")
    provided_key = request.headers.get("x-api-key")

    if expected_key and provided_key != expected_key:
        return {
            "status": "error",
            "message": "unauthorized",
        }

    result = slash_agent_stake_db(
        agent_id,
        slash_ratio=slash_ratio,
        reason="admin_test_slash",
    )

    refreshed_agent = refresh_agent_market_gate(agent_id)

    if not result:
        return {
            "status": "error",
            "message": "agent_not_found",
            "agent_id": agent_id,
        }

    return {
        "status": "ok",
        "slash": result,
        "agent_after_slash": refreshed_agent,
    }




@app.post("/admin/test-lock-agent-stake/{agent_id}")
def admin_test_lock_agent_stake(
    agent_id: str,
    amount: float = 100,
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    agent = get_agent_db(agent_id)

    if not agent:
        return {
            "status": "not_found",
            "agent_id": agent_id,
        }

    conn = get_conn()
    cur = conn.cursor()
    pmark = qmark()
    now = int(time.time())

    cur.execute(f"""
    UPDATE agents
    SET stake_status = 'locked',
        stake_amount = {pmark},
        stake_locked_at = {pmark},
        stake_unlock_requested_at = NULL,
        updated_at = {pmark}
    WHERE agent_id = {pmark}
    """, (
        amount,
        now,
        now,
        agent_id,
    ))

    conn.commit()
    release_conn(conn)

    updated = get_agent_db(agent_id)

    return {
        "status": "ok",
        "message": "test_stake_locked",
        "agent": updated,
    }


@app.post("/admin/request-agent-unstake/{agent_id}")
def admin_request_agent_unstake(
    agent_id: str,
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    agent = get_agent_db(agent_id)

    if not agent:
        return {
            "status": "not_found",
            "agent_id": agent_id,
        }

    if agent.get("stake_status") != "locked":
        return {
            "status": "rejected",
            "reason": "stake_not_locked",
            "agent_id": agent_id,
            "stake_status": agent.get("stake_status"),
        }

    conn = get_conn()
    cur = conn.cursor()
    pmark = qmark()
    now = int(time.time())

    cur.execute(f"""
    UPDATE agents
    SET stake_status = 'unlock_requested',
        stake_unlock_requested_at = {pmark},
        available = 0,
        updated_at = {pmark}
    WHERE agent_id = {pmark}
    """, (
        now,
        now,
        agent_id,
    ))

    conn.commit()
    release_conn(conn)

    updated = get_agent_db(agent_id)

    return {
        "status": "ok",
        "message": "unstake_requested",
        "agent_id": agent_id,
        "cooldown_seconds": 86400,
        "agent": updated,
    }



@app.post("/admin/execute-agent-unstake/{agent_id}")
def admin_execute_agent_unstake(
    agent_id: str,
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    cooldown_seconds = 86400

    agent = get_agent_db(agent_id)

    if not agent:
        return {
            "status": "not_found",
            "agent_id": agent_id,
        }

    if agent.get("stake_status") != "unlock_requested":
        return {
            "status": "rejected",
            "reason": "unlock_not_requested",
            "stake_status": agent.get("stake_status"),
        }

    requested_at = int(agent.get("stake_unlock_requested_at") or 0)
    now = int(time.time())

    remaining = cooldown_seconds - (now - requested_at)

    if remaining > 0:
        return {
            "status": "cooldown_active",
            "remaining_seconds": remaining,
            "agent_id": agent_id,
        }

    conn = get_conn()
    cur = conn.cursor()
    pmark = qmark()

    cur.execute(f"""
    UPDATE agents
    SET stake_status = 'unstaked',
        stake_amount = 0,
        available = 0,
        updated_at = {pmark}
    WHERE agent_id = {pmark}
    """, (
        now,
        agent_id,
    ))

    conn.commit()
    release_conn(conn)

    updated = get_agent_db(agent_id)

    return {
        "status": "ok",
        "message": "unstake_executed",
        "agent": updated,
    }


@app.post("/admin/verify-agent-stake")
def admin_verify_agent_stake(req: AgentStakeVerifyRequest, request: Request):
    expected_key = os.getenv("IAT_ADMIN_API_KEY")
    provided_key = request.headers.get("x-api-key")

    if expected_key and provided_key != expected_key:
        return {
            "status": "error",
            "message": "unauthorized",
        }

    escrow_wallet = os.getenv("IAT_ESCROW_WALLET")

    if not escrow_wallet:
        return {
            "status": "error",
            "message": "escrow_wallet_not_configured",
        }

    tx_details = get_tx_details(req.tx_signature)

    if not tx_details:
        return {
            "status": "error",
            "message": "tx_not_found",
        }

    transfer = extract_transfer_checked_info(tx_details)
    memo = extract_memo(tx_details)

    if not transfer:
        return {
            "status": "error",
            "message": "transfer_not_found",
        }

    expected_ata = str(
        get_associated_token_address(
            Pubkey.from_string(escrow_wallet),
            Pubkey.from_string(IAT_MINT),
        )
    )

    actual_destination = transfer.get("destination")
    actual_mint = transfer.get("mint")
    actual_amount = float(transfer.get("ui_amount") or 0)

    memo_ok = memo is not None and f"STAKE:{req.agent_id}" in str(memo)
    receiver_ok = actual_destination == expected_ata
    mint_ok = actual_mint == IAT_MINT
    amount_ok = actual_amount >= float(req.expected_amount or 0)

    checks = {
        "receiver_ok": receiver_ok,
        "mint_ok": mint_ok,
        "amount_ok": amount_ok,
        "memo_ok": memo_ok,
        "expected_ata": expected_ata,
        "actual_destination": actual_destination,
        "expected_mint": IAT_MINT,
        "actual_mint": actual_mint,
        "expected_amount": req.expected_amount,
        "actual_amount": actual_amount,
        "expected_memo": f"STAKE:{req.agent_id}",
        "actual_memo": str(memo),
    }

    if not (receiver_ok and mint_ok and amount_ok and memo_ok):
        return {
            "status": "invalid_stake",
            "checks": checks,
        }

    # Tier by amount
    if actual_amount >= 1000:
        trust_tier = "premium"
    elif actual_amount >= 100:
        trust_tier = "standard"
    elif actual_amount >= 10:
        trust_tier = "recovery"
    else:
        trust_tier = "free"



@app.post("/internal/seller-risk/orchestrate/{agent_id}")
def internal_orchestrate_seller_risk(
    agent_id: str,
    x_api_key: str | None = Header(default=None),
):
    require_admin_key(x_api_key)

    result = run_seller_risk_orchestration_db(agent_id)

    return result


@app.post("/admin/adaptive-policy/deactivate")
def admin_deactivate_adaptive_policy(
    payload: dict,
    x_api_key: str | None = Header(default=None),
):
    require_admin_key(x_api_key)

    scope = payload.get("scope")
    service = payload.get("service")

    if not scope:
        return {
            "status": "error",
            "message": "missing_scope",
        }

    init_db()

    return deactivate_adaptive_policy_db(
        scope=scope,
        service=service,
    )


class SellerRegisterRequest(BaseModel):
    seller_name: str = Field(min_length=3, max_length=120)
    wallet: str = Field(min_length=8, max_length=256)
    email: EmailStr
    organization_name: str | None = Field(default=None, max_length=120)
    website: str | None = Field(default=None, max_length=500)
    support_email: EmailStr | None = None
    webhook_url: str | None = None
    metadata: dict | None = None


@app.post("/seller/register")
def seller_register(req: SellerRegisterRequest):
    init_db()

    seller_name = (req.seller_name or "").strip()
    wallet = (req.wallet or "").strip()
    email = str(req.email).strip().lower()

    if not seller_name:
        return {
            "status": "error",
            "message": "seller_name_required",
        }

    if not wallet:
        return {
            "status": "error",
            "message": "wallet_required",
        }

    if get_seller_by_wallet_db(wallet):
        return {
            "status": "error",
            "message": "seller_wallet_already_registered",
        }

    if get_seller_by_email_db(email):
        return {
            "status": "error",
            "message": "seller_email_already_registered",
        }

    seller_id = "seller_" + str(uuid.uuid4())
    api_key = create_seller_api_key()

    metadata = req.metadata or {}

    metadata.update({
        "organization_name": req.organization_name,
        "website": req.website,
        "support_email": str(req.support_email).lower() if req.support_email else None,
        "webhook_url": req.webhook_url,
    })

    result = create_seller_db({
        "seller_id": seller_id,
        "seller_name": seller_name,
        "wallet": wallet,
        "email": email,
        "api_key": api_key,
        "seller_status": "pending",
        "verification_status": "unverified",
        "trust_tier": "new",
        "max_agents_allowed": 5,
        "metadata": metadata,
    })

    if isinstance(result, dict) and result.get("status") == "error":
        return result

    return {
        "status": "ok",
        "seller": {
            "seller_id": result.get("seller_id"),
            "seller_name": result.get("seller_name"),
            "wallet": result.get("wallet"),
            "email": result.get("email"),
            "seller_status": result.get("seller_status"),
            "verification_status": result.get("verification_status"),
            "trust_tier": result.get("trust_tier"),
            "max_agents_allowed": result.get("max_agents_allowed"),
            "exposure_limit": result.get("exposure_limit"),
        },
        "api_key": result.get("api_key"),
        "message": "seller_registered_pending_protocol_review",
    }





def validate_seller_runtime(url):
    """
    Validate seller runtime before protocol integration.

    Sellers never interact directly with buyers.
    Therefore seller runtimes become part of the
    protocol execution surface.
    """

    if not url:
        return {
            "status": "error",
            "message": "missing_runtime_url",
        }

    parsed = urlparse(url)

    hostname = str(parsed.hostname or "").lower()

    blocked_hosts = [
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
    ]

    blocked_prefixes = [
        "10.",
        "192.168.",
        "172.16.",
        "172.17.",
        "172.18.",
        "172.19.",
    ]

    if hostname in blocked_hosts:
        return {
            "status": "error",
            "message": "localhost_runtime_not_allowed",
        }

    for prefix in blocked_prefixes:
        if hostname.startswith(prefix):
            return {
                "status": "error",
                "message": "private_network_runtime_not_allowed",
            }

    if parsed.scheme not in ["http", "https"]:
        return {
            "status": "error",
            "message": "invalid_runtime_scheme",
        }

    try:
        started = time.time()

        response = requests.get(
            url,
            timeout=5,
        )

        latency = round(time.time() - started, 3)

        if response.status_code != 200:
            return {
                "status": "error",
                "message": "runtime_invalid_http_status",
                "http_status": response.status_code,
            }

        content_type = str(
            response.headers.get("content-type", "")
        ).lower()

        runtime_health_score = 1.0

        if latency > 3:
            runtime_health_score -= 0.35
        elif latency > 1.5:
            runtime_health_score -= 0.15

        if "application/json" not in content_type:
            return {
                "status": "error",
                "message": "runtime_invalid_content_type",
                "http_status": response.status_code,
                "content_type": content_type,
            }

        runtime_health_score = max(
            0.0,
            min(runtime_health_score, 1.0),
        )

        return {
            "status": "ok",
            "runtime_validation_status": "validated",
            "runtime_latency": latency,
            "runtime_health_score": runtime_health_score,
            "http_status": response.status_code,
            "content_type": content_type,
        }

    except Exception as e:
        return {
            "status": "error",
            "message": "runtime_validation_failed",
            "error": str(e),
        }




class SellerRegisterAgentRequest(BaseModel):
    api_key: str = Field(min_length=16, max_length=200)
    agent_id: str = Field(min_length=3, max_length=120)
    service: str = Field(min_length=3, max_length=120)
    url: str = Field(min_length=8, max_length=500)
    wallet: str | None = Field(default=None, max_length=256)
    price: float = 1.0
    capabilities: list[str] = []
    specialties: list[str] = []
    metadata: dict | None = None


@app.post("/seller/register-agent")
def seller_register_agent(req: SellerRegisterAgentRequest):
    init_db()

    auth = authenticate_seller_api_key_db(req.api_key)

    if auth.get("status") != "ok":
        return auth

    seller = auth["seller"]

    seller_id = seller["seller_id"]
    seller_agent_id = "seller_agent_" + str(uuid.uuid4())

    runtime_validation = validate_seller_runtime(
        req.url.strip()
    )

    if runtime_validation.get("status") != "ok":
        return runtime_validation

    runtime_validation["runtime_last_checked_at"] = int(time.time())


    result = create_seller_agent_db({
        "seller_agent_id": seller_agent_id,
        "seller_id": seller_id,
        "agent_id": req.agent_id.strip(),
        "service": req.service.strip(),
        "url": req.url.strip(),
        "capabilities": req.capabilities,
        "specialties": req.specialties,
        "runtime_validation_status": runtime_validation.get("runtime_validation_status"),
        "runtime_health_score": runtime_validation.get("runtime_health_score"),
        "runtime_latency": runtime_validation.get("runtime_latency"),
        "runtime_last_checked_at": runtime_validation.get("runtime_last_checked_at"),
        "metadata": req.metadata or {},
    })

    if result.get("status") != "ok":
        return result

    seller_status = seller.get("seller_status", "pending")
    verification_status = seller.get("verification_status", "unverified")

    # Seller agents are registered into the legacy marketplace,
    # but they must not become buyer-routable until protocol verification.
    is_protocol_verified = (
        str(seller_status).lower() == "active"
        and str(verification_status).lower() == "foundation_verified"
    )

    registered_agent = {
        "agent_id": req.agent_id.strip(),
        "service": req.service.strip(),
        "url": req.url.strip(),
        "wallet": req.wallet or seller.get("wallet"),
        "agent_type": "seller",
        "price": float(req.price or 1.0),
        "available": is_protocol_verified,
        "seller_status": seller_status,
        "verification_status": verification_status,
        "seller_id": seller_id,
        "seller_agent_id": seller_agent_id,
        "capabilities": json.dumps(req.capabilities),
        "specialties": json.dumps(req.specialties),
    }

    try:
        register_agent_db(registered_agent)
        marketplace_registration = {
            "status": "ok",
            "message": "agent_registered_in_marketplace_registry",
        }
    except Exception as e:
        marketplace_registration = {
            "status": "error",
            "message": "marketplace_registry_registration_failed",
            "error": str(e),
        }

    return {
        "status": "ok",
        "marketplace_registration": marketplace_registration,
        "seller_id": seller_id,
        "seller_agent_id": seller_agent_id,
        "agent_id": req.agent_id.strip(),
        "message": "seller_agent_registered_under_protocol_governance",
    }


class SellerApprovalRequest(BaseModel):
    seller_id: str = Field(min_length=8, max_length=200)



def get_authenticated_seller_from_header(x_seller_api_key):
    if not x_seller_api_key:
        return None
    return get_seller_by_api_key_db(x_seller_api_key)


@app.post("/seller/catalog/items")
def seller_create_catalog_item(
    req: SellerCatalogItemRequest,
    x_seller_api_key: str | None = Header(default=None),
):
    seller = get_authenticated_seller_from_header(x_seller_api_key)
    if not seller:
        return {
            "status": "error",
            "message": "seller_auth_required",
        }

    if seller.get("seller_status") in ["banned", "rejected", "contained"]:
        return {
            "status": "error",
            "message": "seller_not_allowed",
            "seller_status": seller.get("seller_status"),
        }

    result = create_seller_catalog_item_db({
        "seller_id": seller["seller_id"],
        "item_type": req.item_type,
        "category": req.category,
        "title": req.title,
        "description": req.description,
        "service_type": req.service_type,
        "sku": req.sku,
        "unit_price": req.unit_price,
        "currency": req.currency,
        "stock_quantity": req.stock_quantity,
        "capacity_per_day": req.capacity_per_day,
        "capacity_per_order": req.capacity_per_order,
        "availability_status": req.availability_status,
        "delivery_terms": req.delivery_terms,
        "refund_policy": req.refund_policy,
        "warranty_terms": req.warranty_terms,
        "quality_claims": req.quality_claims,
        "source_documents": req.source_documents,
        "proof_links": req.proof_links,
        "metadata": req.metadata,
    })

    return result



@app.get("/seller/dashboard")
def seller_dashboard(
    x_seller_api_key: str | None = Header(default=None),
):
    seller = get_authenticated_seller_from_header(x_seller_api_key)
    if not seller:
        return {
            "status": "error",
            "message": "seller_auth_required",
        }

    seller_id = seller.get("seller_id")

    agents = list_seller_agents_db(seller_id)
    catalog_items = list_seller_catalog_items_db(seller_id)
    factory_requests = list_seller_agent_factory_requests_db(seller_id)
    governance_events = list_seller_governance_events_db(seller_id)
    runtime_risk_events = get_seller_runtime_risk_events_db(
        seller_id=seller_id,
        limit=20,
    )

    agents_list = agents.get("agents", []) if isinstance(agents, dict) else agents
    catalog_list = catalog_items.get("items", []) if isinstance(catalog_items, dict) else catalog_items
    factory_list = factory_requests.get("requests", []) if isinstance(factory_requests, dict) else factory_requests
    governance_list = governance_events.get("events", []) if isinstance(governance_events, dict) else governance_events
    runtime_risk_list = runtime_risk_events.get("events", [])

    all_orders = list_orders_db()
    seller_orders_list = [
        order for order in (all_orders or {}).values()
        if order.get("seller_id") == seller_id
    ]

    total_orders = len(seller_orders_list)
    delivered_orders = 0
    pending_orders = 0
    failed_orders = 0
    delivered_revenue_iat = 0.0
    pending_revenue_iat = 0.0
    order_status_counts = {}

    for order in seller_orders_list:
        order_status = str(order.get("status") or "unknown")
        order_status_counts[order_status] = order_status_counts.get(order_status, 0) + 1

        price = float(order.get("price", 0) or 0)

        if order_status == "delivered":
            delivered_orders += 1
            delivered_revenue_iat += price
        elif order_status in ["failed", "cancelled", "refunded"]:
            failed_orders += 1
        else:
            pending_orders += 1
            pending_revenue_iat += price

    success_rate_percent = round((delivered_orders / total_orders * 100), 2) if total_orders else 0
    average_delivered_order_value_iat = round((delivered_revenue_iat / delivered_orders), 4) if delivered_orders else 0

    runtime_summary = get_seller_runtime_summary_db(seller_id)

    exposure_limit = float(
        seller.get("dynamic_exposure_limit")
        or seller.get("exposure_limit")
        or 0
    )
    risk_score = float(seller.get("risk_score", 0) or 0)
    trust_score = float(seller.get("trust_score", 0) or 0)
    seller_status = str(seller.get("seller_status") or "").lower()

    exposure_state = "healthy"
    if exposure_limit <= 0:
        exposure_state = "restricted"
    if risk_score >= 0.75:
        exposure_state = "high_risk"
    if seller_status in ["restricted", "contained", "banned"]:
        exposure_state = "governance_limited"

    agent_status_counts = {}
    for agent in agents_list or []:
        status = str(agent.get("seller_agent_status") or "unknown")
        agent_status_counts[status] = agent_status_counts.get(status, 0) + 1

    catalog_status_counts = {}
    for item in catalog_list or []:
        status = str(item.get("availability_status") or "unknown")
        catalog_status_counts[status] = catalog_status_counts.get(status, 0) + 1

    factory_status_counts = {}
    for req in factory_list or []:
        status = str(req.get("factory_status") or "unknown")
        factory_status_counts[status] = factory_status_counts.get(status, 0) + 1

    next_required_actions = []

    seller_status = str(seller.get("seller_status") or "").lower()
    verification_status = str(seller.get("verification_status") or "").lower()

    if seller_status not in ["active", "approved"]:
        next_required_actions.append({
            "type": "seller_status",
            "action": "wait_for_or_request_seller_approval",
            "reason": f"seller_status={seller_status}",
        })

    if verification_status not in ["verified", "foundation_verified"]:
        next_required_actions.append({
            "type": "verification",
            "action": "complete_verification",
            "reason": f"verification_status={verification_status}",
        })

    if len(catalog_list or []) == 0:
        next_required_actions.append({
            "type": "catalog",
            "action": "create_catalog_item",
            "reason": "no_catalog_items",
        })

    if len(factory_list or []) == 0:
        next_required_actions.append({
            "type": "factory",
            "action": "request_agent_factory",
            "reason": "no_factory_requests",
        })

    if agent_status_counts.get("quarantined", 0) > 0:
        next_required_actions.append({
            "type": "runtime_governance",
            "action": "review_quarantined_agents",
            "reason": "one_or_more_agents_quarantined",
        })

    if (
        agent_status_counts.get("frozen", 0) > 0
        or agent_status_counts.get("capacity_frozen", 0) > 0
        or agent_status_counts.get("limited", 0) > 0
    ):
        next_required_actions.append({
            "type": "capacity",
            "action": "review_capacity_reduction",
            "reason": "one_or_more_agents_capacity_limited",
        })

    active_agents_count = int(seller.get("active_agents", 0) or 0)
    max_agents_allowed = int(seller.get("max_agents_allowed", 0) or 0)

    if active_agents_count > max_agents_allowed:
        next_required_actions.append({
            "type": "capacity",
            "action": "reduce_active_agents",
            "reason": "active_agents_exceed_dynamic_capacity",
            "active_agents": active_agents_count,
            "max_agents_allowed": max_agents_allowed,
        })

    return {
        "status": "ok",
        "seller": seller,
        "summary": {
            "max_agents_allowed": seller.get("max_agents_allowed"),
            "active_agents": seller.get("active_agents"),
            "risk_score": seller.get("risk_score"),
            "trust_score": seller.get("trust_score"),
            "exposure_limit": seller.get("exposure_limit"),
            "agent_status_counts": agent_status_counts,
            "catalog_count": len(catalog_list or []),
            "catalog_status_counts": catalog_status_counts,
            "factory_request_count": len(factory_list or []),
            "factory_status_counts": factory_status_counts,
            "governance_event_count": len(governance_list or []),
            "runtime_risk_event_count": len(runtime_risk_list or []),
        },
        "orders": {
            "total_orders": total_orders,
            "delivered_orders": delivered_orders,
            "pending_orders": pending_orders,
            "failed_orders": failed_orders,
            "status_counts": order_status_counts,
            "success_rate_percent": success_rate_percent,
        },
        "revenue": {
            "delivered_revenue_iat": round(delivered_revenue_iat, 4),
            "pending_revenue_iat": round(pending_revenue_iat, 4),
            "average_delivered_order_value_iat": average_delivered_order_value_iat,
        },
        "runtime": runtime_summary,
        "capacity": {
            "capacity_state": (
                "over_capacity" if active_agents_count > max_agents_allowed
                else "blocked" if max_agents_allowed == 0
                else "full" if active_agents_count >= max_agents_allowed
                else "healthy"
            ),
            "max_agents_allowed": max_agents_allowed,
            "active_agents": active_agents_count,
            "remaining_capacity": max(0, max_agents_allowed - active_agents_count),
            "over_capacity": max(0, active_agents_count - max_agents_allowed),
            "agent_status_counts": agent_status_counts,
        },
        "exposure": {
            "exposure_state": exposure_state,
            "dynamic_exposure_limit": exposure_limit,
            "risk_score": risk_score,
            "trust_score": trust_score,
        },
        "recent": {
            "factory_requests": (factory_list or [])[:10],
            "governance_events": (governance_list or [])[:10],
            "runtime_risk_events": runtime_risk_list[:10],
        },
        "next_required_actions": next_required_actions,
        "policy": {
            "seller_dashboard_is_read_only": True,
            "seller_cannot_self_approve": True,
            "seller_cannot_bypass_foundation_governance": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }




@app.get("/seller/catalog/item/{catalog_item_id}")
def seller_catalog_item_detail(
    catalog_item_id: str,
    x_seller_api_key: str | None = Header(default=None),
):
    seller = get_authenticated_seller_from_header(x_seller_api_key)
    if not seller:
        return {
            "status": "error",
            "message": "seller_auth_required",
        }

    seller_id = seller.get("seller_id")

    catalog_item = get_seller_catalog_item_db(catalog_item_id)

    if not catalog_item:
        return {
            "status": "error",
            "message": "catalog_item_not_found",
            "catalog_item_id": catalog_item_id,
        }

    if catalog_item.get("seller_id") != seller_id:
        return {
            "status": "error",
            "message": "catalog_item_not_owned_by_seller",
            "catalog_item_id": catalog_item_id,
        }

    factory_requests = list_seller_agent_factory_requests_db(seller_id)
    linked_factory_requests = [
        r for r in (factory_requests or [])
        if r.get("catalog_item_id") == catalog_item_id
    ]

    seller_agents = list_seller_agents_db(seller_id)
    linked_agents = []

    for agent in seller_agents or []:
        try:
            metadata = json.loads(agent.get("metadata") or "{}")
            if metadata.get("catalog_item_id") == catalog_item_id:
                linked_agents.append(agent)
        except Exception:
            pass

    return {
        "status": "ok",
        "seller_id": seller_id,
        "catalog_item_id": catalog_item_id,
        "catalog_item": catalog_item,
        "linked_factory_requests": linked_factory_requests,
        "linked_agents": linked_agents,
        "summary": {
            "factory_request_count": len(linked_factory_requests),
            "linked_agent_count": len(linked_agents),
            "active_linked_agents": len([
                a for a in linked_agents
                if a.get("seller_agent_status") == "active"
            ]),
            "limited_or_frozen_agents": len([
                a for a in linked_agents
                if a.get("seller_agent_status") in [
                    "limited",
                    "capacity_frozen",
                    "quarantined",
                    "throttled",
                ]
            ]),
        },
        "policy": {
            "seller_can_observe_catalog_item": True,
            "seller_cannot_self_verify_catalog_item": True,
            "seller_cannot_force_agent_creation": True,
            "seller_cannot_bypass_foundation_governance": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }



@app.get("/seller/catalog/items")
def seller_list_catalog_items(
    x_seller_api_key: str | None = Header(default=None),
):
    seller = get_authenticated_seller_from_header(x_seller_api_key)
    if not seller:
        return {
            "status": "error",
            "message": "seller_auth_required",
        }

    return {
        "status": "ok",
        "seller_id": seller["seller_id"],
        "items": list_seller_catalog_items_db(seller["seller_id"]),
    }


@app.post("/seller/agent-factory/requests")
def seller_create_agent_factory_request(
    req: SellerAgentFactoryRequest,
    x_seller_api_key: str | None = Header(default=None),
):
    seller = get_authenticated_seller_from_header(x_seller_api_key)
    if not seller:
        return {
            "status": "error",
            "message": "seller_auth_required",
        }

    if seller.get("seller_status") in ["banned", "rejected", "contained"]:
        return {
            "status": "error",
            "message": "seller_not_allowed",
            "seller_status": seller.get("seller_status"),
        }

    requested_agent_count = int(req.requested_agent_count or 1)

    if requested_agent_count < 1:
        return {
            "status": "error",
            "message": "requested_agent_count_invalid",
        }

    if requested_agent_count > int(seller.get("max_agents_allowed", 5) or 5):
        return {
            "status": "error",
            "message": "requested_agent_count_exceeds_seller_limit",
            "requested_agent_count": requested_agent_count,
            "max_agents_allowed": seller.get("max_agents_allowed"),
        }

    result = create_seller_agent_factory_request_db({
        "seller_id": seller["seller_id"],
        "catalog_item_id": req.catalog_item_id,
        "requested_agent_name": req.requested_agent_name,
        "requested_prompt": req.requested_prompt,
        "requested_agent_count": requested_agent_count,
        "requested_specializations": req.requested_specializations,
        "factory_plan": req.factory_plan,
        "factory_status": "requested",
        "sandbox_status": "not_started",
        "simulation_status": "not_started",
        "governance_status": "pending",
        "metadata": req.metadata,
    })

    return result



@app.get("/seller/agent-factory/request/{factory_request_id}")
def seller_agent_factory_request_detail(
    factory_request_id: str,
    x_seller_api_key: str | None = Header(default=None),
):
    seller = get_authenticated_seller_from_header(x_seller_api_key)
    if not seller:
        return {
            "status": "error",
            "message": "seller_auth_required",
        }

    seller_id = seller.get("seller_id")

    factory_request = get_seller_agent_factory_request_db(factory_request_id)

    if not factory_request:
        return {
            "status": "error",
            "message": "factory_request_not_found",
            "factory_request_id": factory_request_id,
        }

    if factory_request.get("seller_id") != seller_id:
        return {
            "status": "error",
            "message": "factory_request_not_owned_by_seller",
            "factory_request_id": factory_request_id,
        }

    factory_reviews = get_seller_agent_factory_reviews_db(
        factory_request_id=factory_request_id,
        limit=20,
    )

    factory_approvals = get_seller_agent_factory_approvals_db(
        factory_request_id=factory_request_id,
        limit=20,
    )

    sandbox_reviews = get_seller_agent_sandbox_reviews_db(
        factory_request_id=factory_request_id,
        limit=20,
    )

    sandbox_approvals = get_seller_agent_sandbox_approvals_db(
        factory_request_id=factory_request_id,
        limit=20,
    )

    simulation_reviews = get_seller_agent_simulation_reviews_db(
        factory_request_id=factory_request_id,
        limit=20,
    )

    simulation_approvals = get_seller_agent_simulation_approvals_db(
        factory_request_id=factory_request_id,
        limit=20,
    )

    generated_agents = []

    try:
        metadata = json.loads(factory_request.get("metadata") or "{}")
        if not isinstance(metadata, dict):
            metadata = {}
        generated_agents = metadata.get("generated_agents") or []
    except Exception:
        generated_agents = []

    return {
        "status": "ok",
        "seller_id": seller_id,
        "factory_request_id": factory_request_id,
        "factory_request": factory_request,
        "generated_agents": generated_agents,
        "reviews": {
            "factory": factory_reviews,
            "sandbox": sandbox_reviews,
            "simulation": simulation_reviews,
        },
        "approvals": {
            "factory": factory_approvals,
            "sandbox": sandbox_approvals,
            "simulation": simulation_approvals,
        },
        "policy": {
            "seller_can_observe_factory_request": True,
            "seller_cannot_approve_factory_request": True,
            "seller_cannot_run_sandbox_or_simulation": True,
            "seller_cannot_generate_agents_directly": True,
            "seller_cannot_bypass_foundation_governance": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }



@app.get("/seller/agent-factory/requests")
def seller_list_agent_factory_requests(
    x_seller_api_key: str | None = Header(default=None),
):
    seller = get_authenticated_seller_from_header(x_seller_api_key)
    if not seller:
        return {
            "status": "error",
            "message": "seller_auth_required",
        }

    return {
        "status": "ok",
        "seller_id": seller["seller_id"],
        "requests": list_seller_agent_factory_requests_db(seller["seller_id"]),
    }



@app.post("/admin/seller-agent-factory/review/{factory_request_id}")
def admin_review_seller_agent_factory_request(
    factory_request_id: str,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return run_seller_agent_factory_review_db(factory_request_id)



@app.post("/admin/seller-agent-factory/sandbox/{factory_request_id}")
def admin_run_seller_agent_factory_sandbox(
    factory_request_id: str,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return run_seller_agent_sandbox_review_db(factory_request_id)



@app.post("/admin/seller-agent-factory/simulation/{factory_request_id}")
def admin_run_seller_agent_factory_simulation(
    factory_request_id: str,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return run_seller_agent_simulation_review_db(factory_request_id)



@app.post("/admin/seller-agent-factory/generate/{factory_request_id}")
def admin_generate_seller_agents_from_factory_request(
    factory_request_id: str,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return run_seller_agent_generation_db(factory_request_id)



@app.post("/admin/seller-agent/activate/{seller_agent_id}")
def admin_activate_seller_agent(
    seller_agent_id: str,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return run_seller_agent_activation_review_db(seller_agent_id)



@app.post("/internal/seller/recompute-agent-capacity/{seller_id}")
def internal_recompute_seller_agent_capacity(
    seller_id: str,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return recompute_seller_dynamic_agent_capacity_db(seller_id)



@app.post("/internal/seller/runtime-orchestrator/{seller_id}")
def internal_seller_runtime_orchestrator(
    seller_id: str,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return orchestrate_seller_runtime_governance_db(seller_id)



class InternalSellerAgentExecuteRequest(BaseModel):
    service: str
    specialization: Optional[str] = None
    order_id: Optional[str] = None
    seller_agent_id: Optional[str] = None
    execution_context: Dict[str, Any] = {}


@app.post("/internal/seller-agent/execute")
def internal_seller_agent_execute(
    payload: InternalSellerAgentExecuteRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    execution_result = run_foundation_controlled_seller_execution_db(
        service=payload.service,
        specialization=payload.specialization,
        order_id=payload.order_id,
        seller_agent_id=payload.seller_agent_id,
        execution_context=payload.execution_context,
    )

    if execution_result.get("status") != "ok":
        return execution_result

    verification_result = verify_seller_execution_result_db(
        execution_result.get("execution_session_id")
    )

    return {
        "status": "ok",
        "execution": execution_result,
        "verification": verification_result,
    }




@app.get("/admin/protocol-memory")
def admin_protocol_memory(
    memory_type: str | None = None,
    scope: str | None = None,
    subject_id: str | None = None,
    status: str = "active",
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return get_protocol_memory_db(
        memory_type=memory_type,
        scope=scope,
        subject_id=subject_id,
        status=status,
        limit=limit,
    )


@app.get("/admin/protocol-memory/search")
def admin_protocol_memory_search(
    query: str,
    memory_type: str | None = None,
    scope: str | None = None,
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return search_protocol_memory_db(
        query=query,
        memory_type=memory_type,
        scope=scope,
        limit=limit,
    )


@app.post("/internal/protocol-memory/reinforce/{memory_id}")
def internal_protocol_memory_reinforce(
    memory_id: int,
    observed: bool = True,
    reason: str = "",
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return reinforce_protocol_memory_db(
        memory_id=memory_id,
        observed=observed,
        reason=reason,
    )


@app.post("/internal/protocol-memory/decay")
def internal_protocol_memory_decay(
    max_age_seconds: int = 604800,
    decay_amount: float = 0.03,
    limit: int = 500,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return decay_protocol_memory_db(
        max_age_seconds=max_age_seconds,
        decay_amount=decay_amount,
        limit=limit,
    )


@app.post("/internal/protocol-memory/archive/{memory_id}")
def internal_protocol_memory_archive(
    memory_id: int,
    reason: str = "manual_archive",
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return archive_protocol_memory_db(
        memory_id=memory_id,
        reason=reason,
    )


@app.post("/internal/protocol-memory/learning-cycle")
def internal_protocol_memory_learning_cycle(
    limit: int = 1000,
    auto_archive: bool = True,
    auto_decay: bool = True,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return run_protocol_learning_cycle_db(
        limit=limit,
        auto_archive=auto_archive,
        auto_decay=auto_decay,
    )


@app.get("/admin/protocol-strategy-context")
def admin_protocol_strategy_context(
    limit: int = 100,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return build_protocol_strategy_context_db(limit=limit)




class ProtocolKnowledgeCreateRequest(BaseModel):
    knowledge_type: str
    scope: str
    subject_id: str | None = None
    source_memory_id: int | None = None
    confidence: float = 0.8
    knowledge_strength: float = 0.75
    stability_score: float = 0.75
    knowledge_payload: dict = {}
    tags: list[str] = []
    metadata: dict = {}


@app.get("/admin/protocol-knowledge")
def admin_protocol_knowledge(
    knowledge_type: str | None = None,
    scope: str | None = None,
    subject_id: str | None = None,
    status: str = "active",
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return get_protocol_knowledge_db(
        knowledge_type=knowledge_type,
        scope=scope,
        subject_id=subject_id,
        status=status,
        limit=limit,
    )


@app.post("/internal/protocol-knowledge/store")
def internal_protocol_knowledge_store(
    req: ProtocolKnowledgeCreateRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return store_protocol_knowledge_db(
        knowledge_type=req.knowledge_type,
        scope=req.scope,
        subject_id=req.subject_id,
        source_memory_id=req.source_memory_id,
        confidence=req.confidence,
        knowledge_strength=req.knowledge_strength,
        stability_score=req.stability_score,
        knowledge_payload=req.knowledge_payload,
        tags=req.tags,
        metadata=req.metadata,
    )


@app.post("/internal/protocol-knowledge/promote-memory/{memory_id}")
def internal_protocol_knowledge_promote_memory(
    memory_id: int,
    force: bool = False,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return promote_memory_to_knowledge_db(
        memory_id=memory_id,
        force=force,
    )


@app.get("/admin/protocol-knowledge-context")
def admin_protocol_knowledge_context(
    limit: int = 100,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return build_protocol_knowledge_context_db(limit=limit)




class ProtocolHypothesisCreateRequest(BaseModel):
    hypothesis_type: str
    scope: str
    subject_id: str | None = None
    hypothesis: str
    rationale: str | None = None
    confidence: float = 0.5
    importance_score: float = 0.5
    metadata: dict = {}


class ProtocolHypothesisEvaluateRequest(BaseModel):
    observed_success: bool = True
    evaluation_note: str = ""


@app.get("/admin/protocol-hypotheses")
def admin_protocol_hypotheses(
    hypothesis_type: str | None = None,
    scope: str | None = None,
    subject_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return get_protocol_hypotheses_db(
        hypothesis_type=hypothesis_type,
        scope=scope,
        subject_id=subject_id,
        status=status,
        limit=limit,
    )


@app.post("/internal/protocol-hypotheses/store")
def internal_protocol_hypothesis_store(
    req: ProtocolHypothesisCreateRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return store_protocol_hypothesis_db(
        hypothesis_type=req.hypothesis_type,
        scope=req.scope,
        subject_id=req.subject_id,
        hypothesis=req.hypothesis,
        rationale=req.rationale,
        confidence=req.confidence,
        importance_score=req.importance_score,
        metadata=req.metadata,
    )


@app.post("/internal/protocol-hypotheses/evaluate/{hypothesis_id}")
def internal_protocol_hypothesis_evaluate(
    hypothesis_id: int,
    req: ProtocolHypothesisEvaluateRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return evaluate_protocol_hypothesis_db(
        hypothesis_id=hypothesis_id,
        observed_success=req.observed_success,
        evaluation_note=req.evaluation_note,
    )




class ProtocolExperimentCreateRequest(BaseModel):
    experiment_type: str
    scope: str
    objective: str
    hypothesis_id: int | None = None
    subject_id: str | None = None
    success_metric: str | None = None
    target_value: float | None = None
    confidence_before: float = 0
    metadata: dict = {}


class ProtocolExperimentStartRequest(BaseModel):
    note: str = ""


class ProtocolExperimentCompleteRequest(BaseModel):
    measured_value: float
    success: bool | None = None
    note: str = ""


@app.get("/admin/protocol-experiments")
def admin_protocol_experiments(
    experiment_type: str | None = None,
    scope: str | None = None,
    subject_id: str | None = None,
    status: str | None = None,
    hypothesis_id: int | None = None,
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return get_protocol_experiments_db(
        experiment_type=experiment_type,
        scope=scope,
        subject_id=subject_id,
        status=status,
        hypothesis_id=hypothesis_id,
        limit=limit,
    )


@app.post("/internal/protocol-experiments/store")
def internal_protocol_experiment_store(
    req: ProtocolExperimentCreateRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return store_protocol_experiment_db(
        experiment_type=req.experiment_type,
        scope=req.scope,
        objective=req.objective,
        hypothesis_id=req.hypothesis_id,
        subject_id=req.subject_id,
        success_metric=req.success_metric,
        target_value=req.target_value,
        confidence_before=req.confidence_before,
        metadata=req.metadata,
    )


@app.post("/internal/protocol-experiments/start/{experiment_id}")
def internal_protocol_experiment_start(
    experiment_id: int,
    req: ProtocolExperimentStartRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return start_protocol_experiment_db(
        experiment_id=experiment_id,
        note=req.note,
    )


@app.post("/internal/protocol-experiments/complete/{experiment_id}")
def internal_protocol_experiment_complete(
    experiment_id: int,
    req: ProtocolExperimentCompleteRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return complete_protocol_experiment_db(
        experiment_id=experiment_id,
        measured_value=req.measured_value,
        success=req.success,
        note=req.note,
    )




class ProtocolAdaptationCreateRequest(BaseModel):
    adaptation_type: str
    scope: str
    recommendation: str
    subject_id: str | None = None
    experiment_id: int | None = None
    hypothesis_id: int | None = None
    rationale: str | None = None
    proposed_change: dict = {}
    expected_impact: dict = {}
    safety_constraints: dict = {}
    confidence: float = 0.5
    risk_score: float = 0.0
    impact_score: float = 0.5
    metadata: dict = {}


class ProtocolAdaptationApproveRequest(BaseModel):
    approved_by: str = "iat_core"
    approval_note: str = ""


class ProtocolAdaptationRejectRequest(BaseModel):
    rejected_by: str = "iat_core"
    rejection_reason: str = ""


class ProtocolAdaptationApplyRequest(BaseModel):
    applied_by: str = "iat_core"
    apply_note: str = ""


@app.get("/admin/protocol-adaptations")
def admin_protocol_adaptations(
    adaptation_type: str | None = None,
    scope: str | None = None,
    subject_id: str | None = None,
    status: str | None = None,
    experiment_id: int | None = None,
    hypothesis_id: int | None = None,
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return get_protocol_adaptations_db(
        adaptation_type=adaptation_type,
        scope=scope,
        subject_id=subject_id,
        status=status,
        experiment_id=experiment_id,
        hypothesis_id=hypothesis_id,
        limit=limit,
    )


@app.post("/internal/protocol-adaptations/store")
def internal_protocol_adaptation_store(
    req: ProtocolAdaptationCreateRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return store_protocol_adaptation_db(
        adaptation_type=req.adaptation_type,
        scope=req.scope,
        recommendation=req.recommendation,
        subject_id=req.subject_id,
        experiment_id=req.experiment_id,
        hypothesis_id=req.hypothesis_id,
        rationale=req.rationale,
        proposed_change=req.proposed_change,
        expected_impact=req.expected_impact,
        safety_constraints=req.safety_constraints,
        confidence=req.confidence,
        risk_score=req.risk_score,
        impact_score=req.impact_score,
        metadata=req.metadata,
    )


@app.post("/internal/protocol-adaptations/approve/{adaptation_id}")
def internal_protocol_adaptation_approve(
    adaptation_id: int,
    req: ProtocolAdaptationApproveRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return approve_protocol_adaptation_db(
        adaptation_id=adaptation_id,
        approved_by=req.approved_by,
        approval_note=req.approval_note,
    )


@app.post("/internal/protocol-adaptations/reject/{adaptation_id}")
def internal_protocol_adaptation_reject(
    adaptation_id: int,
    req: ProtocolAdaptationRejectRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return reject_protocol_adaptation_db(
        adaptation_id=adaptation_id,
        rejected_by=req.rejected_by,
        rejection_reason=req.rejection_reason,
    )


@app.post("/internal/protocol-adaptations/apply/{adaptation_id}")
def internal_protocol_adaptation_apply(
    adaptation_id: int,
    req: ProtocolAdaptationApplyRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return apply_protocol_adaptation_db(
        adaptation_id=adaptation_id,
        applied_by=req.applied_by,
        apply_note=req.apply_note,
    )




class ProtocolRollbackExecuteRequest(BaseModel):
    executed_by: str = "iat_core"
    rollback_reason: str = ""


@app.get("/admin/protocol-rollbacks")
def admin_protocol_rollbacks(
    adaptation_id: int | None = None,
    scope: str | None = None,
    subject_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return get_protocol_rollbacks_db(
        adaptation_id=adaptation_id,
        scope=scope,
        subject_id=subject_id,
        status=status,
        limit=limit,
    )


@app.post("/internal/protocol-rollbacks/execute/{rollback_id}")
def internal_protocol_rollback_execute_by_id(
    rollback_id: int,
    req: ProtocolRollbackExecuteRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return rollback_protocol_adaptation_db(
        rollback_id=rollback_id,
        executed_by=req.executed_by,
        rollback_reason=req.rollback_reason,
    )


@app.post("/internal/protocol-rollbacks/execute-by-adaptation/{adaptation_id}")
def internal_protocol_rollback_execute_by_adaptation(
    adaptation_id: int,
    req: ProtocolRollbackExecuteRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return rollback_protocol_adaptation_db(
        adaptation_id=adaptation_id,
        executed_by=req.executed_by,
        rollback_reason=req.rollback_reason,
    )




class ProtocolAdaptationReviewCreateRequest(BaseModel):
    adaptation_id: int
    reviewer_type: str
    reviewer_id: str
    review_decision: str
    review_reason: str | None = None
    confidence_score: float = 0.0
    risk_score: float = 0.0
    metadata: dict = {}


@app.get("/admin/protocol-adaptation-reviews")
def admin_protocol_adaptation_reviews(
    adaptation_id: int | None = None,
    reviewer_type: str | None = None,
    reviewer_id: str | None = None,
    review_decision: str | None = None,
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return get_protocol_adaptation_reviews_db(
        adaptation_id=adaptation_id,
        reviewer_type=reviewer_type,
        reviewer_id=reviewer_id,
        review_decision=review_decision,
        limit=limit,
    )


@app.post("/internal/protocol-adaptation-reviews/store")
def internal_protocol_adaptation_review_store(
    req: ProtocolAdaptationReviewCreateRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return store_protocol_adaptation_review_db(
        adaptation_id=req.adaptation_id,
        reviewer_type=req.reviewer_type,
        reviewer_id=req.reviewer_id,
        review_decision=req.review_decision,
        review_reason=req.review_reason,
        confidence_score=req.confidence_score,
        risk_score=req.risk_score,
        metadata=req.metadata,
    )


@app.get("/admin/protocol-adaptation-reviews/evaluate/{adaptation_id}")
def admin_protocol_adaptation_reviews_evaluate(
    adaptation_id: int,
    min_reviews: int = 2,
    max_avg_risk: float = 0.60,
    min_avg_confidence: float = 0.65,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return evaluate_protocol_adaptation_reviews_db(
        adaptation_id=adaptation_id,
        min_reviews=min_reviews,
        max_avg_risk=max_avg_risk,
        min_avg_confidence=min_avg_confidence,
    )




class ProtocolAdaptationMonitorCreateRequest(BaseModel):
    adaptation_id: int
    scope: str
    subject_id: str | None = None
    metric_name: str
    baseline_value: float = 0
    current_value: float = 0
    threshold_value: float = 0
    metadata: dict = {}


class ProtocolAdaptationMonitorEvaluateRequest(BaseModel):
    current_value: float | None = None
    evaluation_note: str = ""


@app.get("/admin/protocol-adaptation-monitors")
def admin_protocol_adaptation_monitors(
    adaptation_id: int | None = None,
    scope: str | None = None,
    subject_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return get_protocol_adaptation_monitors_db(
        adaptation_id=adaptation_id,
        scope=scope,
        subject_id=subject_id,
        status=status,
        limit=limit,
    )


@app.post("/internal/protocol-adaptation-monitors/store")
def internal_protocol_adaptation_monitor_store(
    req: ProtocolAdaptationMonitorCreateRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return store_protocol_adaptation_monitor_db(
        adaptation_id=req.adaptation_id,
        scope=req.scope,
        subject_id=req.subject_id,
        metric_name=req.metric_name,
        baseline_value=req.baseline_value,
        current_value=req.current_value,
        threshold_value=req.threshold_value,
        metadata=req.metadata,
    )


@app.post("/internal/protocol-adaptation-monitors/evaluate/{monitor_id}")
def internal_protocol_adaptation_monitor_evaluate(
    monitor_id: int,
    req: ProtocolAdaptationMonitorEvaluateRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return evaluate_protocol_adaptation_monitor_db(
        monitor_id=monitor_id,
        current_value=req.current_value,
        evaluation_note=req.evaluation_note,
    )


@app.post("/internal/protocol-adaptation-monitoring/cycle")
def internal_protocol_adaptation_monitoring_cycle(
    limit: int = 100,
    include_warning: bool = True,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return run_protocol_adaptation_monitoring_cycle_db(
        limit=limit,
        include_warning=include_warning,
    )




class ProtocolRollbackReviewCreateRequest(BaseModel):
    rollback_id: int | None = None
    adaptation_id: int | None = None
    monitor_id: int | None = None
    reviewer_type: str
    reviewer_id: str
    review_decision: str
    review_reason: str | None = None
    confidence_score: float = 0.0
    risk_score: float = 0.0
    metadata: dict = {}


@app.get("/admin/protocol-rollback-reviews")
def admin_protocol_rollback_reviews(
    rollback_id: int | None = None,
    adaptation_id: int | None = None,
    monitor_id: int | None = None,
    reviewer_type: str | None = None,
    reviewer_id: str | None = None,
    review_decision: str | None = None,
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return get_protocol_rollback_reviews_db(
        rollback_id=rollback_id,
        adaptation_id=adaptation_id,
        monitor_id=monitor_id,
        reviewer_type=reviewer_type,
        reviewer_id=reviewer_id,
        review_decision=review_decision,
        limit=limit,
    )


@app.post("/internal/protocol-rollback-reviews/store")
def internal_protocol_rollback_review_store(
    req: ProtocolRollbackReviewCreateRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return store_protocol_rollback_review_db(
        rollback_id=req.rollback_id,
        adaptation_id=req.adaptation_id,
        monitor_id=req.monitor_id,
        reviewer_type=req.reviewer_type,
        reviewer_id=req.reviewer_id,
        review_decision=req.review_decision,
        review_reason=req.review_reason,
        confidence_score=req.confidence_score,
        risk_score=req.risk_score,
        metadata=req.metadata,
    )


@app.get("/admin/protocol-rollback-reviews/evaluate")
def admin_protocol_rollback_reviews_evaluate(
    rollback_id: int | None = None,
    adaptation_id: int | None = None,
    monitor_id: int | None = None,
    min_reviews: int = 2,
    max_avg_risk: float = 0.60,
    min_avg_confidence: float = 0.65,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return evaluate_protocol_rollback_reviews_db(
        rollback_id=rollback_id,
        adaptation_id=adaptation_id,
        monitor_id=monitor_id,
        min_reviews=min_reviews,
        max_avg_risk=max_avg_risk,
        min_avg_confidence=min_avg_confidence,
    )




class ProtocolRollbackProposalCreateRequest(BaseModel):
    rollback_id: int | None = None
    adaptation_id: int | None = None
    monitor_id: int | None = None
    scope: str
    subject_id: str | None = None
    proposal_reason: str
    confidence_score: float = 0.0
    risk_score: float = 0.0
    metadata: dict = {}


@app.get("/admin/protocol-rollback-proposals")
def admin_protocol_rollback_proposals(
    rollback_id: int | None = None,
    adaptation_id: int | None = None,
    monitor_id: int | None = None,
    scope: str | None = None,
    subject_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return get_protocol_rollback_proposals_db(
        rollback_id=rollback_id,
        adaptation_id=adaptation_id,
        monitor_id=monitor_id,
        scope=scope,
        subject_id=subject_id,
        status=status,
        limit=limit,
    )


@app.post("/internal/protocol-rollback-proposals/store")
def internal_protocol_rollback_proposal_store(
    req: ProtocolRollbackProposalCreateRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return store_protocol_rollback_proposal_db(
        rollback_id=req.rollback_id,
        adaptation_id=req.adaptation_id,
        monitor_id=req.monitor_id,
        scope=req.scope,
        subject_id=req.subject_id,
        proposal_reason=req.proposal_reason,
        confidence_score=req.confidence_score,
        risk_score=req.risk_score,
        metadata=req.metadata,
    )




class SellerAgentFactoryReviewRequest(BaseModel):
    factory_request_id: str
    seller_id: str | None = None

    reviewer_type: str
    reviewer_id: str

    review_decision: str
    review_reason: str | None = None

    confidence_score: float = 0.0
    risk_score: float = 0.0

    capability_score: float = 0.0
    policy_score: float = 0.0
    safety_score: float = 0.0

    metadata: dict = {}


@app.get("/admin/seller-agent-factory-reviews")
def admin_seller_agent_factory_reviews(
    factory_request_id: str | None = None,
    seller_id: str | None = None,
    reviewer_type: str | None = None,
    reviewer_id: str | None = None,
    review_decision: str | None = None,
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return get_seller_agent_factory_reviews_db(
        factory_request_id=factory_request_id,
        seller_id=seller_id,
        reviewer_type=reviewer_type,
        reviewer_id=reviewer_id,
        review_decision=review_decision,
        limit=limit,
    )


@app.post("/internal/seller-agent-factory-reviews/store")
def internal_seller_agent_factory_review_store(
    req: SellerAgentFactoryReviewRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return store_seller_agent_factory_review_db(
        factory_request_id=req.factory_request_id,
        seller_id=req.seller_id,
        reviewer_type=req.reviewer_type,
        reviewer_id=req.reviewer_id,
        review_decision=req.review_decision,
        review_reason=req.review_reason,
        confidence_score=req.confidence_score,
        risk_score=req.risk_score,
        capability_score=req.capability_score,
        policy_score=req.policy_score,
        safety_score=req.safety_score,
        metadata=req.metadata,
    )


@app.get("/admin/seller-agent-factory-reviews/evaluate/{factory_request_id}")
def admin_seller_agent_factory_reviews_evaluate(
    factory_request_id: str,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return evaluate_seller_agent_factory_reviews_db(
        factory_request_id=factory_request_id
    )




class SellerAgentFactoryApprovalRequest(BaseModel):
    approved_by: str = "iat_core"
    approval_reason: str = ""


@app.get("/admin/seller-agent-factory-approvals")
def admin_seller_agent_factory_approvals(
    factory_request_id: str | None = None,
    seller_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return get_seller_agent_factory_approvals_db(
        factory_request_id=factory_request_id,
        seller_id=seller_id,
        status=status,
        limit=limit,
    )


@app.post("/internal/seller-agent-factory-approvals/approve/{factory_request_id}")
def internal_seller_agent_factory_approve(
    factory_request_id: str,
    req: SellerAgentFactoryApprovalRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return approve_seller_agent_factory_request_db(
        factory_request_id=factory_request_id,
        approved_by=req.approved_by,
        approval_reason=req.approval_reason,
    )




class SellerAgentSandboxReviewRequest(BaseModel):
    factory_request_id: str
    seller_id: str | None = None

    reviewer_type: str
    reviewer_id: str

    review_decision: str
    review_reason: str | None = None

    confidence_score: float = 0.0
    risk_score: float = 0.0

    sandbox_score: float = 0.0
    policy_score: float = 0.0
    safety_score: float = 0.0

    metadata: dict = {}


class SellerAgentSandboxApprovalRequest(BaseModel):
    approved_by: str = "iat_core"
    approval_reason: str = ""



class SellerAgentSimulationReviewRequest(BaseModel):
    factory_request_id: str
    seller_id: str | None = None

    reviewer_type: str
    reviewer_id: str

    review_decision: str
    review_reason: str | None = None

    confidence_score: float = 0.0
    risk_score: float = 0.0

    simulation_score: float = 0.0
    policy_score: float = 0.0
    safety_score: float = 0.0

    metadata: dict = {}


class SellerAgentSimulationApprovalRequest(BaseModel):
    approved_by: str = "iat_core"
    approval_reason: str = ""



class SellerAgentActivationGovernanceReviewRequest(BaseModel):
    seller_agent_id: str
    agent_id: str | None = None
    seller_id: str | None = None

    reviewer_type: str
    reviewer_id: str

    review_decision: str
    review_reason: str | None = None

    confidence_score: float = 0.0
    risk_score: float = 0.0

    activation_score: float = 0.0
    policy_score: float = 0.0
    safety_score: float = 0.0

    metadata: dict = {}


class SellerAgentActivationApprovalRequest(BaseModel):
    approved_by: str = "iat_core"
    approval_reason: str = ""



class SellerAgentRuntimeReviewRequest(BaseModel):
    seller_agent_id: str
    agent_id: str | None = None
    seller_id: str | None = None

    reviewer_type: str
    reviewer_id: str

    review_decision: str
    review_reason: str | None = None

    confidence_score: float = 0.0
    risk_score: float = 0.0

    runtime_score: float = 0.0
    policy_score: float = 0.0
    safety_score: float = 0.0

    metadata: dict = {}


class SellerAgentRuntimeActionRequest(BaseModel):
    action_type: str
    action_reason: str = ""
    executed_by: str = "iat_core"
    severity: str = "medium"
    metadata: dict = {}




@app.get("/admin/seller-runtime-risk-events")
def admin_seller_runtime_risk_events(
    seller_id: str | None = None,
    seller_agent_id: str | None = None,
    source_action_type: str | None = None,
    severity: str | None = None,
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return get_seller_runtime_risk_events_db(
        seller_id=seller_id,
        seller_agent_id=seller_agent_id,
        source_action_type=source_action_type,
        severity=severity,
        limit=limit,
    )



@app.get("/admin/seller-agent-runtime-governance-reviews")
def admin_seller_agent_runtime_governance_reviews(
    seller_agent_id: str | None = None,
    seller_id: str | None = None,
    governance_status: str | None = None,
    recommended_action: str | None = None,
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return get_seller_agent_runtime_governance_reviews_db(
        seller_agent_id=seller_agent_id,
        seller_id=seller_id,
        governance_status=governance_status,
        recommended_action=recommended_action,
        limit=limit,
    )


@app.post("/internal/seller-agent-runtime-governance/run/{seller_agent_id}")
def internal_seller_agent_runtime_governance_run(
    seller_agent_id: str,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return run_seller_agent_runtime_governance_db(
        seller_agent_id=seller_agent_id
    )



@app.get("/admin/seller-agent-runtime-reviews")
def admin_seller_agent_runtime_reviews(
    seller_agent_id: str | None = None,
    agent_id: str | None = None,
    seller_id: str | None = None,
    reviewer_type: str | None = None,
    reviewer_id: str | None = None,
    review_decision: str | None = None,
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return get_seller_agent_runtime_reviews_db(
        seller_agent_id=seller_agent_id,
        agent_id=agent_id,
        seller_id=seller_id,
        reviewer_type=reviewer_type,
        reviewer_id=reviewer_id,
        review_decision=review_decision,
        limit=limit,
    )


@app.post("/internal/seller-agent-runtime-reviews/store")
def internal_seller_agent_runtime_review_store(
    req: SellerAgentRuntimeReviewRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return store_seller_agent_runtime_review_db(
        seller_agent_id=req.seller_agent_id,
        agent_id=req.agent_id,
        seller_id=req.seller_id,
        reviewer_type=req.reviewer_type,
        reviewer_id=req.reviewer_id,
        review_decision=req.review_decision,
        review_reason=req.review_reason,
        confidence_score=req.confidence_score,
        risk_score=req.risk_score,
        runtime_score=req.runtime_score,
        policy_score=req.policy_score,
        safety_score=req.safety_score,
        metadata=req.metadata,
    )


@app.get("/admin/seller-agent-runtime-reviews/evaluate/{seller_agent_id}")
def admin_seller_agent_runtime_reviews_evaluate(
    seller_agent_id: str,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return evaluate_seller_agent_runtime_reviews_db(
        seller_agent_id=seller_agent_id
    )


@app.get("/admin/seller-agent-runtime-actions")
def admin_seller_agent_runtime_actions(
    seller_agent_id: str | None = None,
    agent_id: str | None = None,
    seller_id: str | None = None,
    action_type: str | None = None,
    execution_status: str | None = None,
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return get_seller_agent_runtime_actions_db(
        seller_agent_id=seller_agent_id,
        agent_id=agent_id,
        seller_id=seller_id,
        action_type=action_type,
        execution_status=execution_status,
        limit=limit,
    )


@app.post("/internal/seller-agent-runtime-actions/execute/{seller_agent_id}")
def internal_seller_agent_runtime_action_execute(
    seller_agent_id: str,
    req: SellerAgentRuntimeActionRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return create_seller_agent_runtime_action_db(
        seller_agent_id=seller_agent_id,
        action_type=req.action_type,
        action_reason=req.action_reason,
        executed_by=req.executed_by,
        severity=req.severity,
        metadata=req.metadata,
    )



@app.get("/admin/seller-agent-activation-governance-reviews")
def admin_seller_agent_activation_governance_reviews(
    seller_agent_id: str | None = None,
    agent_id: str | None = None,
    seller_id: str | None = None,
    reviewer_type: str | None = None,
    reviewer_id: str | None = None,
    review_decision: str | None = None,
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return get_seller_agent_activation_governance_reviews_db(
        seller_agent_id=seller_agent_id,
        agent_id=agent_id,
        seller_id=seller_id,
        reviewer_type=reviewer_type,
        reviewer_id=reviewer_id,
        review_decision=review_decision,
        limit=limit,
    )


@app.post("/internal/seller-agent-activation-governance-reviews/store")
def internal_seller_agent_activation_governance_review_store(
    req: SellerAgentActivationGovernanceReviewRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return store_seller_agent_activation_governance_review_db(
        seller_agent_id=req.seller_agent_id,
        agent_id=req.agent_id,
        seller_id=req.seller_id,
        reviewer_type=req.reviewer_type,
        reviewer_id=req.reviewer_id,
        review_decision=req.review_decision,
        review_reason=req.review_reason,
        confidence_score=req.confidence_score,
        risk_score=req.risk_score,
        activation_score=req.activation_score,
        policy_score=req.policy_score,
        safety_score=req.safety_score,
        metadata=req.metadata,
    )


@app.get("/admin/seller-agent-activation-governance-reviews/evaluate/{seller_agent_id}")
def admin_seller_agent_activation_governance_reviews_evaluate(
    seller_agent_id: str,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return evaluate_seller_agent_activation_governance_reviews_db(
        seller_agent_id=seller_agent_id
    )


@app.get("/admin/seller-agent-activation-approvals")
def admin_seller_agent_activation_approvals(
    seller_agent_id: str | None = None,
    agent_id: str | None = None,
    seller_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return get_seller_agent_activation_approvals_db(
        seller_agent_id=seller_agent_id,
        agent_id=agent_id,
        seller_id=seller_id,
        status=status,
        limit=limit,
    )


@app.post("/internal/seller-agent-activation-approvals/approve/{seller_agent_id}")
def internal_seller_agent_activation_approve(
    seller_agent_id: str,
    req: SellerAgentActivationApprovalRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return approve_seller_agent_activation_request_db(
        seller_agent_id=seller_agent_id,
        approved_by=req.approved_by,
        approval_reason=req.approval_reason,
    )



@app.get("/admin/seller-agent-simulation-reviews")
def admin_seller_agent_simulation_reviews(
    factory_request_id: str | None = None,
    seller_id: str | None = None,
    reviewer_type: str | None = None,
    reviewer_id: str | None = None,
    review_decision: str | None = None,
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return get_seller_agent_simulation_reviews_db(
        factory_request_id=factory_request_id,
        seller_id=seller_id,
        reviewer_type=reviewer_type,
        reviewer_id=reviewer_id,
        review_decision=review_decision,
        limit=limit,
    )


@app.post("/internal/seller-agent-simulation-reviews/store")
def internal_seller_agent_simulation_review_store(
    req: SellerAgentSimulationReviewRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return store_seller_agent_simulation_review_db(
        factory_request_id=req.factory_request_id,
        seller_id=req.seller_id,
        reviewer_type=req.reviewer_type,
        reviewer_id=req.reviewer_id,
        review_decision=req.review_decision,
        review_reason=req.review_reason,
        confidence_score=req.confidence_score,
        risk_score=req.risk_score,
        simulation_score=req.simulation_score,
        policy_score=req.policy_score,
        safety_score=req.safety_score,
        metadata=req.metadata,
    )


@app.get("/admin/seller-agent-simulation-reviews/evaluate/{factory_request_id}")
def admin_seller_agent_simulation_reviews_evaluate(
    factory_request_id: str,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return evaluate_seller_agent_simulation_reviews_db(
        factory_request_id=factory_request_id
    )


@app.get("/admin/seller-agent-simulation-approvals")
def admin_seller_agent_simulation_approvals(
    factory_request_id: str | None = None,
    seller_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return get_seller_agent_simulation_approvals_db(
        factory_request_id=factory_request_id,
        seller_id=seller_id,
        status=status,
        limit=limit,
    )


@app.post("/internal/seller-agent-simulation-approvals/approve/{factory_request_id}")
def internal_seller_agent_simulation_approve(
    factory_request_id: str,
    req: SellerAgentSimulationApprovalRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return approve_seller_agent_simulation_request_db(
        factory_request_id=factory_request_id,
        approved_by=req.approved_by,
        approval_reason=req.approval_reason,
    )



@app.get("/admin/seller-agent-sandbox-reviews")
def admin_seller_agent_sandbox_reviews(
    factory_request_id: str | None = None,
    seller_id: str | None = None,
    reviewer_type: str | None = None,
    reviewer_id: str | None = None,
    review_decision: str | None = None,
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return get_seller_agent_sandbox_reviews_db(
        factory_request_id=factory_request_id,
        seller_id=seller_id,
        reviewer_type=reviewer_type,
        reviewer_id=reviewer_id,
        review_decision=review_decision,
        limit=limit,
    )


@app.post("/internal/seller-agent-sandbox-reviews/store")
def internal_seller_agent_sandbox_review_store(
    req: SellerAgentSandboxReviewRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return store_seller_agent_sandbox_review_db(
        factory_request_id=req.factory_request_id,
        seller_id=req.seller_id,
        reviewer_type=req.reviewer_type,
        reviewer_id=req.reviewer_id,
        review_decision=req.review_decision,
        review_reason=req.review_reason,
        confidence_score=req.confidence_score,
        risk_score=req.risk_score,
        sandbox_score=req.sandbox_score,
        policy_score=req.policy_score,
        safety_score=req.safety_score,
        metadata=req.metadata,
    )


@app.get("/admin/seller-agent-sandbox-reviews/evaluate/{factory_request_id}")
def admin_seller_agent_sandbox_reviews_evaluate(
    factory_request_id: str,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return evaluate_seller_agent_sandbox_reviews_db(
        factory_request_id=factory_request_id
    )


@app.get("/admin/seller-agent-sandbox-approvals")
def admin_seller_agent_sandbox_approvals(
    factory_request_id: str | None = None,
    seller_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return get_seller_agent_sandbox_approvals_db(
        factory_request_id=factory_request_id,
        seller_id=seller_id,
        status=status,
        limit=limit,
    )


@app.post("/internal/seller-agent-sandbox-approvals/approve/{factory_request_id}")
def internal_seller_agent_sandbox_approve(
    factory_request_id: str,
    req: SellerAgentSandboxApprovalRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return approve_seller_agent_sandbox_request_db(
        factory_request_id=factory_request_id,
        approved_by=req.approved_by,
        approval_reason=req.approval_reason,
    )



@app.post("/internal/foundation/decision/{order_id}")
def internal_foundation_decision(
    order_id: str,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    return run_foundation_decision_db(order_id)


@app.post("/admin/seller/approve")
def admin_approve_seller(
    req: SellerApprovalRequest,
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    return approve_seller_db(req.seller_id)



@app.get("/seller/my-agent/{seller_agent_id}")
def seller_my_agent_detail(
    seller_agent_id: str,
    api_key: str | None = None,
    x_seller_api_key: str | None = Header(default=None),
):
    effective_api_key = x_seller_api_key or api_key

    auth = authenticate_seller_api_key_db(effective_api_key)

    if auth.get("status") != "ok":
        return auth

    seller = auth.get("seller")
    seller_id = seller.get("seller_id")

    seller_agent = get_seller_agent_db(seller_agent_id)

    if not seller_agent:
        return {
            "status": "error",
            "message": "seller_agent_not_found",
            "seller_agent_id": seller_agent_id,
        }

    if seller_agent.get("seller_id") != seller_id:
        return {
            "status": "error",
            "message": "seller_agent_not_owned_by_seller",
            "seller_agent_id": seller_agent_id,
        }

    agent_id = seller_agent.get("agent_id")

    runtime_actions = get_seller_agent_runtime_actions_db(
        seller_agent_id=seller_agent_id,
        limit=20,
    )

    runtime_governance_reviews = get_seller_agent_runtime_governance_reviews_db(
        seller_agent_id=seller_agent_id,
        limit=20,
    )

    runtime_risk_events = get_seller_runtime_risk_events_db(
        seller_id=seller_id,
        seller_agent_id=seller_agent_id,
        limit=20,
    )

    activation_reviews = get_seller_agent_activation_governance_reviews_db(
        seller_agent_id=seller_agent_id,
        limit=20,
    )

    activation_approvals = get_seller_agent_activation_approvals_db(
        seller_agent_id=seller_agent_id,
        limit=20,
    )

    factory_request_id = None
    catalog_item_id = None

    try:
        metadata = json.loads(seller_agent.get("metadata") or "{}")
        if not isinstance(metadata, dict):
            metadata = {}
        factory_request_id = metadata.get("factory_request_id")
        catalog_item_id = metadata.get("catalog_item_id")
    except Exception:
        metadata = {}

    factory_request = None
    catalog_item = None

    if factory_request_id:
        factory_request = get_seller_agent_factory_request_db(factory_request_id)

    if catalog_item_id:
        catalog_item = get_seller_catalog_item_db(catalog_item_id)

    return {
        "status": "ok",
        "seller_id": seller_id,
        "seller_agent_id": seller_agent_id,
        "agent_id": agent_id,
        "seller_agent": seller_agent,
        "origin": {
            "factory_request_id": factory_request_id,
            "catalog_item_id": catalog_item_id,
            "factory_request": factory_request,
            "catalog_item": catalog_item,
        },
        "runtime": {
            "actions": runtime_actions,
            "governance_reviews": runtime_governance_reviews,
            "risk_events": runtime_risk_events,
        },
        "activation": {
            "governance_reviews": activation_reviews,
            "approvals": activation_approvals,
        },
        "policy": {
            "seller_can_observe_agent_detail": True,
            "seller_cannot_execute_runtime_action": True,
            "seller_cannot_self_approve_agent": True,
            "seller_cannot_bypass_foundation_governance": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }





@app.get("/seller/governance-history/{event_id}")
def seller_governance_event_detail(
    event_id: str,
    api_key: str | None = None,
    x_seller_api_key: str | None = Header(default=None),
):
    effective_api_key = x_seller_api_key or api_key

    auth = authenticate_seller_api_key_db(
        effective_api_key
    )

    if auth.get("status") != "ok":
        return auth

    seller = auth["seller"]
    seller_id = seller["seller_id"]

    events = list_seller_governance_events_db(
        seller_id=seller_id,
        limit=500,
    )

    for event in events.get("events", []):
        if event.get("event_id") == event_id:
            parsed_metadata = {}
            try:
                parsed_metadata = json.loads(event.get("metadata") or "{}")
            except Exception:
                parsed_metadata = {}

            return {
                "status": "ok",
                "seller_id": seller_id,
                "event_id": event_id,
                "event": event,
                "parsed_metadata": parsed_metadata,
                "policy": {
                    "seller_can_view_governance_event_detail": True,
                    "seller_cannot_modify_governance_event": True,
                    "seller_cannot_execute_governance_action": True,
                    "protocol_core_sovereignty_reserved": True,
                },
            }

    return {
        "status": "error",
        "message": "governance_event_not_found",
        "event_id": event_id,
    }





@app.get("/seller/risk-history/{event_id}")
def seller_risk_event_detail(
    event_id: int,
    api_key: str | None = None,
    x_seller_api_key: str | None = Header(default=None),
):
    effective_api_key = x_seller_api_key or api_key

    auth = authenticate_seller_api_key_db(
        effective_api_key
    )

    if auth.get("status") != "ok":
        return auth

    seller = auth["seller"]
    seller_id = seller["seller_id"]

    events = get_seller_runtime_risk_events_db(
        seller_id=seller_id,
        limit=500,
    )

    for event in events.get("events", []):
        if int(event.get("event_id") or 0) == int(event_id):
            parsed_metadata = {}
            try:
                parsed_metadata = json.loads(event.get("metadata") or "{}")
            except Exception:
                parsed_metadata = {}

            return {
                "status": "ok",
                "seller_id": seller_id,
                "event_id": event_id,
                "event": event,
                "parsed_metadata": parsed_metadata,
                "policy": {
                    "seller_can_view_risk_event_detail": True,
                    "seller_cannot_modify_risk_event": True,
                    "seller_cannot_execute_risk_action": True,
                    "protocol_core_sovereignty_reserved": True,
                },
            }

    return {
        "status": "error",
        "message": "risk_event_not_found",
        "event_id": event_id,
    }









def sanitize_order_for_seller(order):
    safe_order = dict(order or {})

    for sensitive_key in [
        "buyer_secret",
        "buyer_wallet",
        "buyer_context",
        "foundation_context",
        "execution_context",
    ]:
        safe_order.pop(sensitive_key, None)

    safe_order.pop("query", None)
    safe_order["query_redacted"] = True

    if safe_order.get("buyer_intent"):
        buyer_intent = safe_order.get("buyer_intent")
        safe_order["buyer_request_summary"] = {
            "service": buyer_intent.get("service") if isinstance(buyer_intent, dict) else None,
            "category": buyer_intent.get("category") if isinstance(buyer_intent, dict) else None,
            "capabilities": buyer_intent.get("capabilities") if isinstance(buyer_intent, dict) else None,
        }

    safe_order.pop("buyer_intent", None)

    if safe_order.get("requirements"):
        requirements = safe_order.get("requirements")
        safe_order["requirements_summary"] = {
            "keys": list(requirements.keys()) if isinstance(requirements, dict) else []
        }

    safe_order.pop("requirements", None)

    safe_order["buyer_data_redacted"] = True
    safe_order["seller_view_only"] = True

    return safe_order


@app.get("/seller/orders")
def seller_orders(
    limit: int = 50,
    api_key: str | None = None,
    x_seller_api_key: str | None = Header(default=None),
):
    effective_api_key = x_seller_api_key or api_key

    auth = authenticate_seller_api_key_db(
        effective_api_key
    )

    if auth.get("status") != "ok":
        return auth

    seller = auth["seller"]
    seller_id = seller["seller_id"]

    all_orders = list_orders_db()

    seller_orders_list = []

    for order_id, order in (all_orders or {}).items():
        if order.get("seller_id") == seller_id:
            seller_orders_list.append(order)

    seller_orders_list = sorted(
        seller_orders_list,
        key=lambda o: int(o.get("created_at", 0) or 0),
        reverse=True,
    )[: int(limit or 50)]

    redacted_orders = []

    for order in seller_orders_list:
        redacted_orders.append(sanitize_order_for_seller(order))

    seller_orders_list = redacted_orders

    status_counts = {}
    delivered_count = 0
    pending_count = 0
    total_volume = 0.0

    for order in seller_orders_list:
        status = str(order.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

        if status == "delivered":
            delivered_count += 1
            total_volume += float(order.get("price", 0) or 0)
        else:
            pending_count += 1

    return {
        "status": "ok",
        "seller_id": seller_id,
        "count": len(seller_orders_list),
        "summary": {
            "delivered_orders": delivered_count,
            "pending_orders": pending_count,
            "status_counts": status_counts,
            "total_delivered_volume_iat": total_volume,
        },
        "orders": seller_orders_list,
        "policy": {
            "seller_can_view_own_orders": True,
            "seller_cannot_view_other_seller_orders": True,
            "seller_cannot_modify_orders": True,
            "buyer_contact_hidden_from_seller": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }



@app.get("/seller/runtime-health")
def seller_runtime_health(
    api_key: str | None = None,
    x_seller_api_key: str | None = Header(default=None),
):
    effective_api_key = x_seller_api_key or api_key

    auth = authenticate_seller_api_key_db(
        effective_api_key
    )

    if auth.get("status") != "ok":
        return auth

    seller = auth["seller"]
    seller_id = seller["seller_id"]

    agents = list_seller_agents_db(seller_id)
    agents_list = agents.get("agents", []) if isinstance(agents, dict) else agents

    runtime_status_counts = {}
    runtime_health_scores = []
    unhealthy_agents = []
    pending_review_agents = []

    runtime_relevant_statuses = [
        "active",
        "throttled",
        "limited",
        "quarantined",
        "capacity_frozen",
    ]

    for agent in agents_list or []:
        seller_agent_status = str(
            agent.get("seller_agent_status") or "unknown"
        )

        runtime_status = str(
            agent.get("runtime_validation_status") or "unknown"
        )

        runtime_status_counts[runtime_status] = (
            runtime_status_counts.get(runtime_status, 0) + 1
        )

        if seller_agent_status not in runtime_relevant_statuses:
            pending_review_agents.append({
                "seller_agent_id": agent.get("seller_agent_id"),
                "agent_id": agent.get("agent_id"),
                "seller_agent_status": seller_agent_status,
                "runtime_validation_status": runtime_status,
            })
            continue

        health_score = float(
            agent.get("runtime_health_score", 0) or 0
        )

        runtime_health_scores.append(health_score)

        if (
            runtime_status not in ["validated", "runtime_throttled"]
            or health_score < 0.5
        ):
            unhealthy_agents.append({
                "seller_agent_id": agent.get("seller_agent_id"),
                "agent_id": agent.get("agent_id"),
                "seller_agent_status": seller_agent_status,
                "runtime_validation_status": runtime_status,
                "runtime_health_score": health_score,
                "runtime_failure_count": agent.get("runtime_failure_count"),
                "runtime_last_checked_at": agent.get("runtime_last_checked_at"),
            })

    average_runtime_health = 0.0
    if runtime_health_scores:
        average_runtime_health = round(
            sum(runtime_health_scores) / len(runtime_health_scores),
            4
        )

    runtime_state = "healthy"

    if not agents_list:
        runtime_state = "no_agents"
    elif average_runtime_health < 0.5:
        runtime_state = "degraded"
    elif len(unhealthy_agents) > 0:
        runtime_state = "partial_degradation"

    return {
        "status": "ok",
        "seller_id": seller_id,
        "runtime_state": runtime_state,
        "agent_count": len(agents_list or []),
        "average_runtime_health": average_runtime_health,
        "runtime_status_counts": runtime_status_counts,
        "runtime_relevant_agent_count": len(runtime_health_scores),
        "pending_review_agent_count": len(pending_review_agents),
        "pending_review_agents": pending_review_agents,
        "unhealthy_agents": unhealthy_agents,
        "policy": {
            "seller_can_view_runtime_health": True,
            "seller_cannot_self_validate_runtime": True,
            "seller_cannot_self_reactivate_runtime": True,
            "runtime_governance_controlled_by_protocol": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }



@app.get("/seller/exposure-status")
def seller_exposure_status(
    api_key: str | None = None,
    x_seller_api_key: str | None = Header(default=None),
):
    effective_api_key = x_seller_api_key or api_key

    auth = authenticate_seller_api_key_db(
        effective_api_key
    )

    if auth.get("status") != "ok":
        return auth

    seller = auth["seller"]

    seller_id = seller["seller_id"]

    exposure_limit = float(
        seller.get("dynamic_exposure_limit")
        or seller.get("exposure_limit")
        or 0
    )

    risk_score = float(
        seller.get("risk_score", 0) or 0
    )

    trust_score = float(
        seller.get("trust_score", 0) or 0
    )

    seller_status = str(
        seller.get("seller_status") or ""
    ).lower()

    exposure_state = "healthy"

    if exposure_limit <= 0:
        exposure_state = "restricted"

    if risk_score >= 0.75:
        exposure_state = "high_risk"

    if seller_status in [
        "restricted",
        "contained",
        "banned",
    ]:
        exposure_state = "governance_limited"

    metadata = {}
    try:
        metadata = json.loads(
            seller.get("metadata") or "{}"
        )
        if not isinstance(metadata, dict):
            metadata = {}
    except Exception:
        metadata = {}

    return {
        "status": "ok",
        "seller_id": seller_id,
        "seller_status": seller_status,
        "exposure_state": exposure_state,
        "dynamic_exposure_limit": exposure_limit,
        "risk_score": risk_score,
        "trust_score": trust_score,
        "metadata": metadata,
        "policy": {
            "seller_can_view_exposure_status": True,
            "seller_cannot_modify_exposure": True,
            "seller_cannot_self_raise_exposure": True,
            "exposure_controlled_by_protocol": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }



@app.get("/seller/capacity-status")
def seller_capacity_status(
    api_key: str | None = None,
    x_seller_api_key: str | None = Header(default=None),
):
    effective_api_key = x_seller_api_key or api_key

    auth = authenticate_seller_api_key_db(effective_api_key)

    if auth.get("status") != "ok":
        return auth

    seller = auth["seller"]
    seller_id = seller["seller_id"]

    agents = list_seller_agents_db(seller_id)
    agents_list = agents.get("agents", []) if isinstance(agents, dict) else agents

    agent_status_counts = {}
    for agent in agents_list or []:
        status = str(agent.get("seller_agent_status") or "unknown")
        agent_status_counts[status] = agent_status_counts.get(status, 0) + 1

    metadata = {}
    try:
        metadata = json.loads(seller.get("metadata") or "{}")
        if not isinstance(metadata, dict):
            metadata = {}
    except Exception:
        metadata = {}

    last_capacity_report = metadata.get("last_dynamic_capacity_report") or {}

    max_agents_allowed = int(seller.get("max_agents_allowed", 0) or 0)
    active_agents = int(seller.get("active_agents", 0) or 0)
    total_agents = int(seller.get("total_agents", 0) or 0)

    remaining_capacity = max(0, max_agents_allowed - active_agents)
    over_capacity = max(0, active_agents - max_agents_allowed)

    capacity_state = "healthy"
    if over_capacity > 0:
        capacity_state = "over_capacity"
    elif max_agents_allowed == 0:
        capacity_state = "blocked"
    elif remaining_capacity == 0:
        capacity_state = "full"

    return {
        "status": "ok",
        "seller_id": seller_id,
        "capacity_state": capacity_state,
        "max_agents_allowed": max_agents_allowed,
        "active_agents": active_agents,
        "total_agents": total_agents,
        "remaining_capacity": remaining_capacity,
        "over_capacity": over_capacity,
        "agent_status_counts": agent_status_counts,
        "last_dynamic_capacity_report": last_capacity_report,
        "policy": {
            "seller_can_view_capacity_status": True,
            "seller_cannot_modify_capacity": True,
            "seller_cannot_self_increase_capacity": True,
            "capacity_controlled_by_protocol": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }



@app.get("/seller/recovery-status")
def seller_recovery_status(
    api_key: str | None = None,
    x_seller_api_key: str | None = Header(default=None),
):
    effective_api_key = x_seller_api_key or api_key

    auth = authenticate_seller_api_key_db(effective_api_key)

    if auth.get("status") != "ok":
        return auth

    seller = auth["seller"]
    seller_id = seller["seller_id"]

    governance_events = list_seller_governance_events_db(
        seller_id=seller_id,
        limit=100,
    )

    risk_events = get_seller_runtime_risk_events_db(
        seller_id=seller_id,
        limit=100,
    )

    recent_governance = governance_events.get("events", [])
    recent_risk_events = risk_events.get("events", [])

    seller_status = str(seller.get("seller_status") or "").lower()
    risk_score = float(seller.get("risk_score", 0) or 0)
    max_agents_allowed = int(seller.get("max_agents_allowed", 0) or 0)
    active_agents = int(seller.get("active_agents", 0) or 0)

    blocked_statuses = ["banned", "rejected", "contained"]
    degraded_statuses = [
        "restricted",
        "limited",
        "watchlist",
        "contained",
    ]

    recovery_reasons = []

    if seller_status in blocked_statuses:
        recovery_reasons.append("seller_terminal_or_contained_status")

    if seller_status in degraded_statuses:
        recovery_reasons.append("seller_status_degraded")

    if risk_score >= 0.85:
        recovery_reasons.append("critical_risk_score_requires_foundation_review")
    elif risk_score >= 0.35:
        recovery_reasons.append("risk_score_above_recovery_threshold")

    if max_agents_allowed < active_agents:
        recovery_reasons.append("active_agents_exceed_current_capacity")

    has_recoverable_condition = any(
        reason in recovery_reasons
        for reason in [
            "seller_status_degraded",
            "risk_score_above_recovery_threshold",
            "active_agents_exceed_current_capacity",
        ]
    )

    can_request_recovery = (
        seller_status not in blocked_statuses
        and risk_score < 0.85
        and has_recoverable_condition
    )

    return {
        "status": "ok",
        "seller_id": seller_id,
        "seller_status": seller_status,
        "risk_score": risk_score,
        "max_agents_allowed": max_agents_allowed,
        "active_agents": active_agents,
        "can_request_recovery": can_request_recovery,
        "recovery_reasons": recovery_reasons,
        "recent_governance_events_count": len(recent_governance),
        "recent_risk_events_count": len(recent_risk_events),
        "policy": {
            "seller_can_view_recovery_status": True,
            "seller_can_request_recovery_separately": True,
            "seller_cannot_self_recover": True,
            "seller_cannot_self_reactivate_agents": True,
            "foundation_must_review_recovery": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }



@app.get("/seller/risk-history")
def seller_risk_history(
    limit: int = 50,
    api_key: str | None = None,
    x_seller_api_key: str | None = Header(default=None),
):
    effective_api_key = x_seller_api_key or api_key

    auth = authenticate_seller_api_key_db(
        effective_api_key
    )

    if auth.get("status") != "ok":
        return auth

    seller = auth["seller"]
    seller_id = seller["seller_id"]

    events = get_seller_runtime_risk_events_db(
        seller_id=seller_id,
        limit=limit,
    )

    return {
        "status": "ok",
        "seller_id": seller_id,
        "count": events.get("count", 0),
        "events": events.get("events", []),
        "policy": {
            "seller_can_view_risk_history": True,
            "seller_cannot_modify_risk_history": True,
            "seller_cannot_execute_risk_action": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }



@app.get("/seller/governance-history")
def seller_governance_history(
    limit: int = 50,
    api_key: str | None = None,
    x_seller_api_key: str | None = Header(default=None),
):
    effective_api_key = x_seller_api_key or api_key

    auth = authenticate_seller_api_key_db(
        effective_api_key
    )

    if auth.get("status") != "ok":
        return auth

    seller = auth["seller"]

    events = list_seller_governance_events_db(
        seller_id=seller["seller_id"],
        limit=limit,
    )

    return {
        "status": "ok",
        "seller_id": seller["seller_id"],
        "events": events.get("events", []),
        "count": len(events.get("events", [])),
        "policy": {
            "seller_can_view_governance_history": True,
            "seller_cannot_modify_governance_history": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }



@app.get("/seller/my-agents")
def seller_my_agents(
    api_key: str | None = None,
    x_seller_api_key: str | None = Header(default=None),
):
    effective_api_key = x_seller_api_key or api_key

    auth = authenticate_seller_api_key_db(effective_api_key)

    if auth.get("status") != "ok":
        return auth

    seller = auth.get("seller")
    seller_id = seller.get("seller_id")

    return {
        "status": "ok",
        "seller_id": seller_id,
        "seller_status": seller.get("seller_status"),
        "verification_status": seller.get("verification_status"),
        "agents": list_seller_agents_db(seller_id),
        "policy": {
            "seller_can_observe_agents": True,
            "seller_cannot_self_approve_agents": True,
            "seller_cannot_bypass_foundation_governance": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }



class SellerRejectRequest(BaseModel):
    seller_id: str = Field(min_length=8, max_length=200)
    reason: str = Field(default="foundation_rejected", max_length=500)


@app.post("/admin/seller/reject")
def admin_reject_seller(
    req: SellerRejectRequest,
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    return reject_seller_db(
        seller_id=req.seller_id,
        reason=req.reason,
    )

class SellerApproveOverrideRequest(BaseModel):
    seller_id: str = Field(min_length=8, max_length=200)
    reason: str = Field(min_length=10, max_length=500)


@app.post("/admin/seller/approve-override")
def admin_approve_seller_override(
    req: SellerApproveOverrideRequest,
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    return approve_seller_db(
        seller_id=req.seller_id,
        override_terminal=True,
    )


@app.get("/admin/seller/{seller_id}")
def admin_get_seller(
    seller_id: str,
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    seller = get_seller_db(seller_id)

    if not seller:
        return {
            "status": "error",
            "message": "seller_not_found",
            "seller_id": seller_id,
        }

    return {
        "status": "ok",
        "seller": seller,
    }


@app.get("/admin/seller/{seller_id}/governance-events")
def admin_seller_governance_events(
    seller_id: str,
    x_api_key: str = Header(default=""),
):
    require_admin_key(x_api_key)

    return {
        "status": "ok",
        "seller_id": seller_id,
        "events": list_seller_governance_events_db(seller_id),
    }



class AdminSellerRiskEventRequest(BaseModel):
    seller_id: str = Field(min_length=8, max_length=200)
    event_type: str = Field(default="manual_review", min_length=3, max_length=120)
    severity: float = Field(default=0.1, ge=0.0, le=1.0)
    reason: str = Field(default="admin seller risk event", min_length=5, max_length=500)


@app.post("/admin/seller/risk-event")
def admin_seller_risk_event(
    req: AdminSellerRiskEventRequest,
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    return apply_seller_risk_event_db(
        seller_id=req.seller_id,
        event_type=req.event_type,
        severity=req.severity,
        reason=req.reason,
    )



class AdminSellerAgentRuntimeUpdateRequest(BaseModel):
    seller_agent_id: str = Field(min_length=8, max_length=200)
    runtime_validation_status: str = Field(default="unknown", max_length=80)
    runtime_health_score: float = Field(default=0.0, ge=0.0, le=1.0)
    runtime_latency: float = Field(default=0.0, ge=0.0)


@app.post("/admin/seller-agent/runtime-status")
def admin_seller_agent_runtime_status(
    req: AdminSellerAgentRuntimeUpdateRequest,
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    return update_seller_agent_runtime_status_db(
        seller_agent_id=req.seller_agent_id,
        runtime_validation_status=req.runtime_validation_status,
        runtime_health_score=req.runtime_health_score,
        runtime_latency=req.runtime_latency,
    )




@app.get("/admin/seller-containment-events")
def admin_seller_containment_events(
    limit: int = 50,
    x_api_key: str = Header(None),
):
    require_admin_key(x_api_key)

    from iat.api.db import (
        list_seller_containment_events_db,
    )

    return list_seller_containment_events_db(
        limit=limit
    )


@app.post("/internal/runtime/heartbeat-scan")
def internal_runtime_heartbeat_scan(
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    agents = list_runtime_monitored_seller_agents_db()

    results = []

    for agent in agents:
        runtime = validate_seller_runtime(agent.get("url"))

        if runtime.get("status") == "ok":
            runtime_status = "validated"

            health_score = float(
                runtime.get("runtime_health_score", 0) or 0
            )

            latency = float(
                runtime.get("runtime_latency", 0) or 0
            )
        else:
            runtime_status = "dead"
            health_score = 0.0
            latency = 0.0

        update_result = update_seller_agent_runtime_status_db(
            seller_agent_id=agent.get("seller_agent_id"),
            runtime_validation_status=runtime_status,
            runtime_health_score=health_score,
            runtime_latency=latency,
        )

        results.append({
            "seller_agent_id": agent.get("seller_agent_id"),
            "agent_id": agent.get("agent_id"),
            "url": agent.get("url"),
            "runtime_probe": runtime,
            "update_result": update_result,
        })

    return {
        "status": "ok",
        "agents_scanned": len(results),
        "results": results,
    }




def runtime_heartbeat_governance_loop():
    while True:
        try:
            if str(os.getenv("IAT_ENABLE_AUTONOMOUS_SETTLEMENT_ORCHESTRATOR", "false")).lower() == "true":
                try:
                    settlement_run = run_settlement_orchestrator_once_db(limit=50)
                    print("[IAT_AUTONOMOUS_SETTLEMENT_ORCHESTRATOR]", settlement_run)
                except Exception as settlement_error:
                    print("[IAT_AUTONOMOUS_SETTLEMENT_ORCHESTRATOR_ERROR]", str(settlement_error))

            agents = list_runtime_monitored_seller_agents_db()

            for agent in agents:
                runtime = validate_seller_runtime(
                    agent.get("url")
                )

                if runtime.get("status") == "ok":
                    runtime_status = "validated"

                    health_score = float(
                        runtime.get(
                            "runtime_health_score",
                            0
                        ) or 0
                    )

                    latency = float(
                        runtime.get(
                            "runtime_latency",
                            0
                        ) or 0
                    )
                else:
                    runtime_status = "dead"
                    health_score = 0.0
                    latency = 0.0

                update_seller_agent_runtime_status_db(
                    seller_agent_id=agent.get(
                        "seller_agent_id"
                    ),
                    runtime_validation_status=runtime_status,
                    runtime_health_score=health_score,
                    runtime_latency=latency,
                )

                try:
                    from iat.api.db import (
                        compute_temporal_behavior_stability_db,
                        compute_autonomous_governance_recommendation_db,
                        compute_autonomous_recovery_recommendation_db,
                    )

                    seller_id = agent.get("seller_id")

                    if seller_id:

                        adaptive_refresh = refresh_adaptive_policy_for_seller(
                            seller_id
                        )

                        temporal = compute_temporal_behavior_stability_db(
                            seller_id,
                            window_days=30,
                        )

                        governance = compute_autonomous_governance_recommendation_db(
                            seller_id
                        )

                        recovery = compute_autonomous_recovery_recommendation_db(
                            seller_id
                        )

                        print(
                            "[IAT_AUTONOMOUS_GOVERNANCE]",
                            {
                                "seller_id": seller_id,
                                "temporal_reliability": temporal.get(
                                    "temporal_reliability"
                                ),
                                "governance_recommendation": governance.get(
                                    "recommendation"
                                ),
                                "recovery_recommendation": recovery.get(
                                    "recommendation"
                                ),
                                "cluster_id": (
                                    adaptive_refresh.get("cluster") or {}
                                ).get("cluster_id"),
                                "cluster_risk_score": (
                                    adaptive_refresh.get("cluster") or {}
                                ).get("cluster_risk_score"),
                                "forecast_risk": (
                                    adaptive_refresh.get("cluster_forecast") or {}
                                ).get("forecast_risk_score"),
                            }
                        )

                        try:
                            from iat.api.db import (
                                authorize_protocol_response_execution_db,
                                apply_controlled_protocol_response_db,
                                get_conn,
                                release_conn,
                                qmark,
                            )

                            conn = get_conn()
                            cur = conn.cursor()
                            p = qmark()

                            cur.execute(f"""
                            SELECT created_at
                            FROM seller_governance_events
                            WHERE seller_id = {p}
                              AND event_type = 'controlled_protocol_response_applied'
                            ORDER BY created_at DESC
                            LIMIT 1
                            """, (
                                seller_id,
                            ))

                            cooldown_row = cur.fetchone()
                            release_conn(conn)

                            cooldown_ok = True

                            if cooldown_row:
                                last_ts = int(
                                    cooldown_row["created_at"]
                                )

                                if int(time.time()) - last_ts < 3600:
                                    cooldown_ok = False

                            if cooldown_ok:
                                gate = authorize_protocol_response_execution_db(
                                    seller_id
                                )

                                if (
                                    gate.get("status") == "ok"
                                    and gate.get("auto_allowed") is True
                                    and gate.get("execution_mode") == "controlled_auto"
                                ):
                                    execution = apply_controlled_protocol_response_db(
                                        seller_id
                                    )

                                    print(
                                        "[IAT_AUTONOMOUS_SAFE_EXECUTION]",
                                        {
                                            "seller_id": seller_id,
                                            "execution": execution,
                                        }
                                    )

                        except Exception as execution_error:
                            print(
                                "[IAT_AUTONOMOUS_EXECUTION_ERROR]",
                                str(execution_error)
                            )

                except Exception as cognition_error:
                    print(
                        "[IAT_AUTONOMOUS_COGNITION_ERROR]",
                        str(cognition_error)
                    )

        except Exception as e:
            print(
                "[IAT_RUNTIME_HEARTBEAT_LOOP_ERROR]",
                str(e)
            )

        time.sleep(60)


@app.on_event("startup")
def start_runtime_governance_loop():
    thread = threading.Thread(
        target=runtime_heartbeat_governance_loop,
        daemon=True
    )

    thread.start()

    print(
        "[IAT] Runtime heartbeat governance loop started"
    )




@app.get("/admin/seller-risk-dashboard")
def admin_seller_risk_dashboard(
    limit: int = 100,
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    from iat.api.db import list_seller_risk_dashboard_db

    return list_seller_risk_dashboard_db(
        limit=limit
    )




class AdminSellerTrustRecomputeRequest(BaseModel):
    seller_id: str = Field(min_length=3, max_length=200)


@app.post("/admin/seller/recompute-trust")
def admin_seller_recompute_trust(
    req: AdminSellerTrustRecomputeRequest,
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    from iat.api.db import recompute_seller_trust_tier_db

    return recompute_seller_trust_tier_db(
        seller_id=req.seller_id
    )




class AdminSellerStatusUpdateRequest(BaseModel):
    seller_id: str = Field(min_length=3, max_length=200)
    next_status: str = Field(min_length=3, max_length=50)
    reason: str = "manual_governance"


@app.post("/admin/seller/update-status")
def admin_seller_update_status(
    req: AdminSellerStatusUpdateRequest,
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    from iat.api.db import update_seller_status_governed_db

    return update_seller_status_governed_db(
        seller_id=req.seller_id,
        next_status=req.next_status,
        reason=req.reason,
    )



class SellerRecoveryRequest(BaseModel):
    api_key: str = Field(min_length=10, max_length=300)
    requested_status: str = "watchlist"
    reason: str = Field(default="", max_length=2000)
    evidence: dict = {}


@app.post("/seller/request-recovery")
def seller_request_recovery(req: SellerRecoveryRequest):
    auth = authenticate_seller_api_key_db(req.api_key)

    if not auth:
        return {
            "status": "error",
            "message": "invalid_seller_api_key",
        }

    if auth.get("status") == "ok":
        seller_id = (auth.get("seller") or {}).get("seller_id")
    else:
        seller_id = auth.get("seller_id")

    from iat.api.db import create_seller_recovery_request_db

    return create_seller_recovery_request_db(
        seller_id=seller_id,
        requested_status=req.requested_status,
        reason=req.reason,
        evidence=req.evidence,
    )



class SellerRecoveryRequest(BaseModel):
    api_key: str = Field(min_length=10, max_length=300)
    requested_status: str = "watchlist"
    reason: str = Field(default="", max_length=2000)
    evidence: dict = {}


@app.post("/seller/request-recovery")
def seller_request_recovery(req: SellerRecoveryRequest):
    seller = authenticate_seller_api_key_db(req.api_key)

    if not seller:
        return {
            "status": "error",
            "message": "invalid_seller_api_key",
        }

    from iat.api.db import create_seller_recovery_request_db

    return create_seller_recovery_request_db(
        seller_id=seller.get("seller_id"),
        requested_status=req.requested_status,
        reason=req.reason,
        evidence=req.evidence,
    )



class AdminSellerRecoveryDecisionRequest(BaseModel):
    recovery_request_id: str = Field(min_length=10, max_length=300)
    decision: str = Field(min_length=6, max_length=20)
    admin_reason: str = Field(default="", max_length=2000)


@app.post("/admin/seller/recovery-decision")
def admin_seller_recovery_decision(
    req: AdminSellerRecoveryDecisionRequest,
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    from iat.api.db import decide_seller_recovery_request_db

    return decide_seller_recovery_request_db(
        recovery_request_id=req.recovery_request_id,
        decision=req.decision,
        admin_reason=req.admin_reason,
    )



@app.get("/admin/seller-governance-events")
def admin_seller_governance_events(
    seller_id: str = None,
    limit: int = 100,
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    from iat.api.db import list_seller_governance_events_db

    return list_seller_governance_events_db(
        seller_id=seller_id,
        limit=limit,
    )



@app.get("/admin/threat-memory-nodes")
def admin_threat_memory_nodes(
    limit: int = 100,
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    from iat.api.db import list_threat_memory_nodes_db

    return list_threat_memory_nodes_db(
        limit=limit,
    )



@app.get("/admin/seller/autonomous-governance-recommendation/{seller_id}")
def admin_seller_autonomous_governance_recommendation(
    seller_id: str,
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    from iat.api.db import compute_autonomous_governance_recommendation_db

    return compute_autonomous_governance_recommendation_db(
        seller_id
    )



@app.post("/admin/seller/record-autonomous-governance-recommendation/{seller_id}")
def admin_record_autonomous_governance_recommendation(
    seller_id: str,
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    from iat.api.db import record_autonomous_governance_recommendation_db

    return record_autonomous_governance_recommendation_db(
        seller_id
    )



@app.get("/admin/seller/simulate-protocol-response/{seller_id}")
def admin_simulate_protocol_response(
    seller_id: str,
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    from iat.api.db import simulate_protocol_response_impact_db

    return simulate_protocol_response_impact_db(
        seller_id
    )



@app.post("/admin/seller/record-protocol-response-simulation/{seller_id}")
def admin_record_protocol_response_simulation(
    seller_id: str,
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    from iat.api.db import record_protocol_response_simulation_db

    return record_protocol_response_simulation_db(
        seller_id
    )



@app.get("/admin/seller/autonomous-recovery-recommendation/{seller_id}")
def admin_autonomous_recovery_recommendation(
    seller_id: str,
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    from iat.api.db import compute_autonomous_recovery_recommendation_db

    return compute_autonomous_recovery_recommendation_db(
        seller_id
    )


@app.post("/admin/seller/record-autonomous-recovery-recommendation/{seller_id}")
def admin_record_autonomous_recovery_recommendation(
    seller_id: str,
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    from iat.api.db import record_autonomous_recovery_recommendation_db

    return record_autonomous_recovery_recommendation_db(
        seller_id
    )



@app.get("/admin/seller/simulate-rehabilitation/{seller_id}")
def admin_simulate_rehabilitation(
    seller_id: str,
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    from iat.api.db import simulate_rehabilitation_impact_db

    return simulate_rehabilitation_impact_db(
        seller_id
    )


@app.post("/admin/seller/record-rehabilitation-simulation/{seller_id}")
def admin_record_rehabilitation_simulation(
    seller_id: str,
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    from iat.api.db import record_rehabilitation_impact_simulation_db

    return record_rehabilitation_impact_simulation_db(
        seller_id
    )



@app.get("/admin/seller/rehabilitation-execution-gate/{seller_id}")
def admin_rehabilitation_execution_gate(
    seller_id: str,
    x_api_key: str = Header(default="")
):
    require_admin_key(x_api_key)

    from iat.api.db import authorize_rehabilitation_execution_db

    return authorize_rehabilitation_execution_db(
        seller_id
    )



@app.get("/admin/db-status")
def db_status_admin():
    from iat.api.db import USE_POSTGRES, DATABASE_URL, DB_PATH, get_conn, release_conn

    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1 AS ok")
        row = cur.fetchone()

        return {
            "status": "ok",
            "db_backend": "postgres" if USE_POSTGRES else "sqlite",
            "postgres_enabled": bool(USE_POSTGRES),
            "database_url_present": bool(DATABASE_URL),
            "sqlite_path": str(DB_PATH),
            "connection_test": dict(row) if isinstance(row, dict) else {"ok": row[0] if row else None},
        }
    except Exception as e:
        return {
            "status": "error",
            "db_backend": "postgres" if USE_POSTGRES else "sqlite",
            "postgres_enabled": bool(USE_POSTGRES),
            "database_url_present": bool(DATABASE_URL),
            "sqlite_path": str(DB_PATH),
            "error_type": type(e).__name__,
            "error": str(e),
        }
    finally:
        release_conn(conn)


@app.get("/seller/order/{order_id}")
def seller_order_detail(
    order_id: str,
    api_key: str | None = None,
    x_seller_api_key: str | None = Header(default=None),
):
    effective_api_key = x_seller_api_key or api_key

    auth = authenticate_seller_api_key_db(effective_api_key)

    if auth.get("status") != "ok":
        return auth

    seller = auth["seller"]
    seller_id = seller["seller_id"]

    order = get_order_db(order_id)

    if not order:
        return {
            "status": "error",
            "message": "order_not_found",
        }

    if order.get("seller_id") != seller_id:
        return {
            "status": "error",
            "message": "seller_order_access_denied",
            "policy": {
                "seller_can_view_own_orders": True,
                "seller_cannot_view_other_seller_orders": True,
                "buyer_contact_hidden_from_seller": True,
                "protocol_core_sovereignty_reserved": True,
            },
        }

    return {
        "status": "ok",
        "seller_id": seller_id,
        "order": sanitize_order_for_seller(order),
        "policy": {
            "seller_can_view_own_orders": True,
            "seller_cannot_view_other_seller_orders": True,
            "seller_cannot_modify_orders": True,
            "buyer_contact_hidden_from_seller": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }


@app.get("/seller/analytics")
def seller_analytics(
    api_key: str | None = None,
    x_seller_api_key: str | None = Header(default=None),
):
    effective_api_key = x_seller_api_key or api_key

    auth = authenticate_seller_api_key_db(effective_api_key)

    if auth.get("status") != "ok":
        return auth

    seller = auth["seller"]
    seller_id = seller["seller_id"]

    all_orders = list_orders_db()
    seller_orders_list = [
        order for order in (all_orders or {}).values()
        if order.get("seller_id") == seller_id
    ]

    total_orders = len(seller_orders_list)
    delivered_orders = 0
    pending_orders = 0
    failed_orders = 0
    total_revenue_iat = 0.0
    pending_revenue_iat = 0.0

    status_counts = {}

    for order in seller_orders_list:
        status = str(order.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

        price = float(order.get("price", 0) or 0)

        if status == "delivered":
            delivered_orders += 1
            total_revenue_iat += price
        elif status in ["failed", "cancelled", "refunded"]:
            failed_orders += 1
        else:
            pending_orders += 1
            pending_revenue_iat += price

    success_rate = round((delivered_orders / total_orders * 100), 2) if total_orders else 0
    average_order_value = round((total_revenue_iat / delivered_orders), 4) if delivered_orders else 0

    return {
        "status": "ok",
        "seller_id": seller_id,
        "analytics": {
            "orders": {
                "total_orders": total_orders,
                "delivered_orders": delivered_orders,
                "pending_orders": pending_orders,
                "failed_orders": failed_orders,
                "status_counts": status_counts,
            },
            "revenue": {
                "total_delivered_revenue_iat": round(total_revenue_iat, 4),
                "pending_revenue_iat": round(pending_revenue_iat, 4),
                "average_delivered_order_value_iat": average_order_value,
            },
            "performance": {
                "success_rate_percent": success_rate,
            },
            "seller_profile": {
                "seller_status": seller.get("seller_status"),
                "verification_status": seller.get("verification_status"),
                "trust_tier": seller.get("trust_tier"),
                "reputation": seller.get("reputation"),
                "risk_score": seller.get("risk_score"),
                "runtime_health_score": seller.get("runtime_health_score"),
                "max_agents_allowed": seller.get("max_agents_allowed"),
                "active_agents": seller.get("active_agents"),
                "exposure_limit": seller.get("exposure_limit"),
            },
        },
        "policy": {
            "seller_can_view_own_analytics": True,
            "seller_cannot_view_buyer_identity": True,
            "seller_cannot_view_other_seller_analytics": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }


@app.get("/seller/payouts")
def seller_payouts(
    api_key: str | None = None,
    x_seller_api_key: str | None = Header(default=None),
):
    effective_api_key = x_seller_api_key or api_key

    auth = authenticate_seller_api_key_db(effective_api_key)

    if auth.get("status") != "ok":
        return auth

    seller = auth["seller"]
    seller_id = seller["seller_id"]

    all_orders = list_orders_db()
    seller_orders_list = [
        order for order in (all_orders or {}).values()
        if order.get("seller_id") == seller_id
    ]

    delivered_iat = 0.0
    pending_iat = 0.0
    failed_iat = 0.0
    withheld_iat = 0.0

    payout_events = []

    for order in seller_orders_list:
        status = str(order.get("status") or "unknown")
        price = float(order.get("price", 0) or 0)

        if status == "delivered":
            delivered_iat += price
            payout_state = "earned_pending_payout"
        elif status in ["failed", "cancelled", "refunded"]:
            failed_iat += price
            payout_state = "not_payable"
        else:
            pending_iat += price
            payout_state = "pending_delivery_or_escrow"

        payout_events.append({
            "order_id": order.get("order_id"),
            "service": order.get("service"),
            "status": status,
            "amount_iat": price,
            "payout_state": payout_state,
            "created_at": order.get("created_at"),
            "delivered_at": order.get("delivered_at"),
        })

    risk_score = float(seller.get("risk_score", 0) or 0)
    seller_status = str(seller.get("seller_status") or "pending").lower()
    verification_status = str(seller.get("verification_status") or "unverified").lower()

    payout_hold_reasons = []

    if seller_status not in ["active", "approved"]:
        payout_hold_reasons.append("seller_not_active")

    if verification_status not in ["verified", "foundation_verified"]:
        payout_hold_reasons.append("seller_not_verified")

    if risk_score >= 0.75:
        payout_hold_reasons.append("high_risk_score")

    if seller_status in ["restricted", "contained", "banned", "rejected"]:
        payout_hold_reasons.append("governance_restricted_status")

    payout_eligible = len(payout_hold_reasons) == 0

    if not payout_eligible:
        withheld_iat = delivered_iat
        payable_iat = 0.0
    else:
        payable_iat = delivered_iat

    return {
        "status": "ok",
        "seller_id": seller_id,
        "payouts": {
            "currency": "IAT",
            "earned_iat": round(delivered_iat, 4),
            "pending_iat": round(pending_iat, 4),
            "failed_or_cancelled_iat": round(failed_iat, 4),
            "withheld_iat": round(withheld_iat, 4),
            "payable_iat": round(payable_iat, 4),
            "payout_eligible": payout_eligible,
            "hold_reasons": payout_hold_reasons,
        },
        "escrow": {
            "mode": "protocol_accounting_placeholder",
            "onchain_escrow_enabled": False,
            "future_onchain_escrow_required": True,
            "release_requires_protocol_confirmation": True,
            "seller_cannot_self_release_funds": True,
        },
        "events": sorted(
            payout_events,
            key=lambda e: int(e.get("created_at", 0) or 0),
            reverse=True,
        )[:50],
        "policy": {
            "seller_can_view_payouts": True,
            "seller_cannot_trigger_payout_directly": True,
            "seller_cannot_bypass_escrow": True,
            "protocol_controls_release": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }


@app.get("/admin/sellers/pending")
def admin_pending_sellers(
    limit: int = 100,
    x_api_key: str = Header(default="")
):
    if not require_admin_key(x_api_key):
        return {
            "status": "error",
            "message": "unauthorized",
        }

    sellers = list_sellers_db(limit=limit)

    pending_statuses = [
        "pending",
        "pending_review",
        "unverified",
        "watchlist",
    ]

    pending = []

    for seller in sellers:
        seller_status = str(seller.get("seller_status") or "").lower()
        verification_status = str(seller.get("verification_status") or "").lower()

        if (
            seller_status in pending_statuses
            or verification_status in ["unverified", "not_provided", "pending"]
        ):
            pending.append({
                "seller_id": seller.get("seller_id"),
                "seller_name": seller.get("seller_name"),
                "wallet": seller.get("wallet"),
                "email": seller.get("email"),
                "seller_status": seller.get("seller_status"),
                "verification_status": seller.get("verification_status"),
                "trust_tier": seller.get("trust_tier"),
                "reputation": seller.get("reputation"),
                "risk_score": seller.get("risk_score"),
                "trust_score": seller.get("trust_score"),
                "max_agents_allowed": seller.get("max_agents_allowed"),
                "active_agents": seller.get("active_agents"),
                "exposure_limit": seller.get("exposure_limit"),
                "created_at": seller.get("created_at"),
                "updated_at": seller.get("updated_at"),
            })

    return {
        "status": "ok",
        "count": len(pending),
        "sellers": pending,
        "policy": {
            "admin_can_review_pending_sellers": True,
            "seller_approval_requires_foundation_authority": True,
            "seller_cannot_self_approve": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }


class SellerAgentFactoryManualApproveRequest(BaseModel):
    approved_by: str = "iat_manual_foundation_governance"
    approval_reason: str = "manual_foundation_approval"


@app.post("/admin/seller-agent-factory/manual-approve/{factory_request_id}")
def admin_seller_agent_factory_manual_approve(
    factory_request_id: str,
    req: SellerAgentFactoryManualApproveRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return manual_approve_seller_agent_factory_request_db(
        factory_request_id=factory_request_id,
        approved_by=req.approved_by,
        approval_reason=req.approval_reason,
    )


class SellerAgentManualActivateRequest(BaseModel):
    approved_by: str = "iat_manual_activation_governance"
    approval_reason: str = "manual_activation_approval"


@app.post("/admin/seller-agent/manual-activate/{seller_agent_id}")
def admin_seller_agent_manual_activate(
    seller_agent_id: str,
    req: SellerAgentManualActivateRequest,
    x_api_key: str = Header(default=""),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    return manual_activate_seller_agent_db(
        seller_agent_id=seller_agent_id,
        approved_by=req.approved_by,
        approval_reason=req.approval_reason,
    )
