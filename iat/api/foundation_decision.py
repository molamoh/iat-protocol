from typing import Any, Dict, List
import hashlib
import time

from iat.api.execution_engine import rank_agents
from iat.intelligence.decision_core import DecisionPolicy, evaluate_candidates


def _percent(value: Any, *, ratio: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if ratio and number <= 1:
        number *= 100
    return max(0.0, min(100.0, number))


def _shadow_intelligence_decision(ranked: List[Dict[str, Any]], context: Dict[str, Any]) -> dict:
    prices = [max(0.0, float(item.get("price_iat") or 0)) for item in ranked]
    maximum_price = max(prices + [1.0])
    candidates = []
    for item in ranked:
        risk = _percent(item.get("risk_score", 50))
        latency = max(0.0, float(item.get("latency") or 0))
        candidates.append({
            "candidate_id": str(item.get("agent_id") or item.get("id") or ""),
            "price": max(0.0, float(item.get("price_iat") or 0)),
            "quality": _percent(item.get("governance_score", 50)),
            "trust": _percent(item.get("trust_score", 50)),
            "reliability": _percent(item.get("success_rate", 0), ratio=True),
            "latency_score": max(0.0, min(100.0, 100 / (1 + latency / 1_000))),
            "capabilities": list(item.get("capabilities") or []),
            "facts": {"risk_score": risk, "foundation_score": item.get("score")},
        })
    return evaluate_candidates(
        candidates,
        policy=DecisionPolicy(strategy="safest", maximum_price=maximum_price),
        decision_type="select_execution_agent",
        context={"mode": "shadow", **context},
    )


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
    try:
        shadow = _shadow_intelligence_decision(ranked, context)
    except Exception as exc:
        shadow = {
            "status": "shadow_evaluation_failed",
            "error": type(exc).__name__,
            "production_side_effects": False,
        }
    shadow_selected_id = (shadow.get("selected") or {}).get("candidate_id")
    foundation_selected_id = selected.get("agent_id")

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
            "decision_intelligence_mode": "shadow",
            "decision_intelligence_diverged": (
                shadow["status"] != "shadow_evaluation_failed"
                and shadow_selected_id != foundation_selected_id
            ),
            "decision_intelligence_error": (
                shadow.get("error")
                if shadow["status"] == "shadow_evaluation_failed"
                else None
            ),
        },
        "decision_intelligence_shadow": shadow,
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
