from typing import Any, Dict


DEFAULT_UNIFIED_TRUST_WEIGHTS = {
    "reputation": 0.20,
    "trust": 0.20,
    "risk": 0.20,
    "reliability": 0.20,
    "runtime_health": 0.10,
    "governance": 0.10,
}


def clamp_score(value, minimum=0.0, maximum=100.0):
    try:
        value = float(value or 0)
    except Exception:
        value = 0.0

    return max(minimum, min(maximum, value))


def compute_unified_trust_score(entity: Dict[str, Any], weights: Dict[str, float] = None) -> Dict[str, Any]:
    entity = entity or {}
    weights = weights or DEFAULT_UNIFIED_TRUST_WEIGHTS

    reputation = clamp_score(entity.get("reputation", 50))
    trust = clamp_score(entity.get("trust_score", entity.get("trust", 50)))
    risk = clamp_score(entity.get("risk_score", entity.get("risk", 50)))
    reliability = clamp_score(entity.get("reliability_score", entity.get("reliability", 50)))
    runtime_health = clamp_score(entity.get("runtime_health_score", entity.get("runtime_health", 50)))
    governance = clamp_score(entity.get("governance_score", entity.get("governance", 50)))

    risk_inverse = 100 - risk

    final_score = (
        reputation * weights.get("reputation", 0.20)
        + trust * weights.get("trust", 0.20)
        + risk_inverse * weights.get("risk", 0.20)
        + reliability * weights.get("reliability", 0.20)
        + runtime_health * weights.get("runtime_health", 0.10)
        + governance * weights.get("governance", 0.10)
    )

    final_score = round(clamp_score(final_score), 6)

    if final_score >= 80:
        tier = "excellent"
    elif final_score >= 65:
        tier = "good"
    elif final_score >= 45:
        tier = "medium"
    elif final_score >= 25:
        tier = "weak"
    else:
        tier = "danger"

    return {
        "status": "ok",
        "engine": "iat_unified_trust_engine_v1",
        "entity_id": entity.get("entity_id"),
        "entity_type": entity.get("entity_type"),
        "score": final_score,
        "tier": tier,
        "components": {
            "reputation": reputation,
            "trust": trust,
            "risk": risk,
            "risk_inverse": risk_inverse,
            "reliability": reliability,
            "runtime_health": runtime_health,
            "governance": governance,
        },
        "weights": weights,
    }


def inspect_unified_trust_engine() -> Dict[str, Any]:
    return {
        "status": "ok",
        "engine": "iat_unified_trust_engine_v1",
        "weights": DEFAULT_UNIFIED_TRUST_WEIGHTS,
        "supported_entities": [
            "foundation_agent",
            "seller_agent",
            "buyer_agent",
            "runtime_worker",
            "seller",
            "buyer",
            "service",
        ],
    }
