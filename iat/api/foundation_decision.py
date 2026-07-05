from typing import Any, Dict, List
import hashlib
import time

from iat.api.execution_engine import rank_agents


def select_best_execution_agent(
    agents: List[Dict[str, Any]],
    context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    context = context if isinstance(context, dict) else {}

    ranked = rank_agents(agents or [])

    if not ranked:
        return {
            "status": "no_agent_available",
            "reason": "no_ranked_execution_agent",
            "selected_agent": None,
            "ranked_agents": [],
            "decision_layer": "foundation_decision_layer_v1",
            "context": context,
        }

    selected = ranked[0]

    decision_payload = {
        "execution_allowed": True,
        "selected_agent_id": selected.get("agent_id"),
        "selected_agent_score": selected.get("score"),
        "selected_agent_trust": {
            "trust_score": selected.get("trust_score"),
            "risk_score": selected.get("risk_score"),
            "runtime_health_score": selected.get("runtime_health_score"),
            "governance_score": selected.get("governance_score"),
            "reputation": selected.get("reputation"),
        },
        "decision_confidence": 1.0,
        "decision_source": "foundation",
        "routing_strategy": "best_ranked_agent",
        "requires_manual_review": False,
    }

    decision_payload["decision_timestamp"] = int(time.time())

    decision_payload["trust_snapshot"] = {
        "trust_score": selected.get("trust_score"),
        "risk_score": selected.get("risk_score"),
        "runtime_health_score": selected.get("runtime_health_score"),
        "governance_score": selected.get("governance_score"),
        "reputation": selected.get("reputation"),
        "score": selected.get("score"),
        "tier": (
            selected.get("unified_trust", {})
            .get("tier")
        ),
        "engine": "iat_unified_trust_engine_v1",
    }

    decision_payload["decision_hash"] = hashlib.sha256(
        repr(sorted(decision_payload.items())).encode()
    ).hexdigest()

    decision = {
        "status": "agent_selected",
        "reason": "foundation_selected_best_execution_agent",
        "selected_agent": selected,
        "ranked_agents": ranked,
        "decision_layer": "foundation_decision_layer_v1",
        "context": context,
        "foundation_authority": True,
        "decision": decision_payload,
        "audit": {
            "candidate_count": len(ranked),
            "ranking_engine": "execution_engine_v2",
            "trust_engine": "iat_unified_trust_engine_v1",
        },
    }

    return decision


def inspect_foundation_decision_layer() -> Dict[str, Any]:
    return {
        "status": "ok",
        "decision_layer": "foundation_decision_layer_v1",
        "capabilities": {
            "select_best_execution_agent": True,
            "uses_execution_engine": True,
            "uses_unified_trust_via_execution_engine": True,
            "foundation_authority": True,
        },
    }
