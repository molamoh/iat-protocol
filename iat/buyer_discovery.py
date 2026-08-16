"""Safe mapping from verified marketplace records to explainable decisions."""

from __future__ import annotations

import json
from typing import Any

from iat.intelligence.decision_core import DecisionPolicy, evaluate_candidates


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    try:
        decoded = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item) for item in decoded if str(item)] if isinstance(decoded, list) else []


def _score(value: Any, *, default: float = 0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if 0 <= number <= 1:
        number *= 100
    return max(0, min(100, number))


def build_buyer_intent_preview(
    records: list[dict[str, Any]],
    *,
    wallet: str,
    service: str,
    goal: str,
    maximum_price: float,
    strategy: str,
    required_capabilities: list[str],
    now: int | None = None,
) -> dict[str, Any]:
    candidates = []
    for row in records:
        successes = max(0, int(row.get("successful_orders") or 0))
        failures = max(0, int(row.get("failed_orders") or 0))
        observed = successes + failures
        reliability = (
            successes / observed * 100 if observed else _score(row.get("reputation"), default=50)
        )
        capabilities = sorted(set(_json_list(row.get("capabilities")) + _json_list(row.get("specialties"))))
        candidates.append({
            "candidate_id": str(row.get("seller_agent_id") or ""),
            "price": float(row.get("unit_price") or 0),
            "quality": _score(row.get("reputation"), default=50),
            "trust": _score(row.get("seller_trust_score"), default=0),
            "reliability": reliability,
            "latency_score": _score(row.get("runtime_health_score"), default=0),
            "capabilities": capabilities,
            "facts": {
                "catalog_item_id": row.get("catalog_item_id"),
                "title": row.get("title"),
                "service": row.get("service_type") or row.get("service"),
                "currency": row.get("currency"),
                "catalog_verification": row.get("catalog_verification_status"),
                "runtime_validation": row.get("runtime_validation_status"),
                "capacity_per_day": row.get("capacity_per_day"),
                "capacity_per_order": row.get("capacity_per_order"),
            },
        })
    result = evaluate_candidates(
        candidates,
        policy=DecisionPolicy(
            strategy=strategy,
            maximum_price=maximum_price,
            required_capabilities=tuple(required_capabilities),
        ),
        decision_type="buyer_intent_marketplace_preview",
        context={
            "buyer_wallet": wallet,
            "service": service,
            "goal_digest_scope": "request_only",
            "goal_length": len(goal),
        },
        now=now,
    )
    result["production_side_effects"] = False
    result["funds_reserved"] = False
    result["selection_is_quote"] = False
    result["next_action"] = "create_order_from_selected_catalog" if result.get("selected") else "refine_intent"
    return result

