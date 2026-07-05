from typing import Any, Dict, List

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

    return {
        "status": "agent_selected",
        "reason": "foundation_selected_best_execution_agent",
        "selected_agent": ranked[0],
        "ranked_agents": ranked,
        "decision_layer": "foundation_decision_layer_v1",
        "context": context,
        "foundation_authority": True,
    }


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
