from typing import Dict, Any


def _safe_float(value, default=0.0):
    try:
        return float(value if value is not None else default)
    except Exception:
        return default


def _clamp(value, lo=0.0, hi=1.0):
    return max(lo, min(hi, value))


def govern_economic_execution(order: Dict[str, Any], agent: Dict[str, Any] | None = None) -> Dict[str, Any]:
    order = dict(order or {})
    agent = dict(agent or {})

    price = _safe_float(order.get("price") or agent.get("price") or agent.get("price_iat"), 0.0)
    reputation = _safe_float(agent.get("reputation"), 0.5)
    risk_score = _safe_float(agent.get("risk_score"), 0.0)
    runtime_health = _safe_float(agent.get("runtime_health_score"), 1.0)

    if runtime_health > 1:
        runtime_health = runtime_health / 100.0

    trust_score = _safe_float(agent.get("trust_score") or agent.get("seller_trust_score"), 50.0)
    if trust_score > 1:
        trust_score = trust_score / 100.0

    stake_amount = _safe_float(agent.get("stake_amount"), 0.0)
    stake_required = max(
        _safe_float(agent.get("stake_required"), 0.0),
        _safe_float(agent.get("dynamic_stake_required"), 0.0),
    )

    order_value_risk = _clamp(price / 100.0)
    stake_gap = _clamp((stake_required - stake_amount) / max(stake_required, 1.0)) if stake_required > 0 else 0.0

    economic_risk = _clamp(
        (risk_score * 0.35)
        + ((1 - reputation) * 0.20)
        + ((1 - runtime_health) * 0.15)
        + ((1 - trust_score) * 0.15)
        + (stake_gap * 0.10)
        + (order_value_risk * 0.05)
    )

    if economic_risk >= 0.75:
        recommended_consensus = 5
        recommended_execution_mode = "foundation_consensus"
        allow_execution = False
        reason = "economic_risk_too_high"
    elif economic_risk >= 0.50:
        recommended_consensus = 4
        recommended_execution_mode = "foundation_consensus"
        allow_execution = True
        reason = "high_risk_requires_strong_consensus"
    elif economic_risk >= 0.25:
        recommended_consensus = 3
        recommended_execution_mode = "foundation_consensus"
        allow_execution = True
        reason = "moderate_risk_requires_consensus"
    else:
        recommended_consensus = 2
        recommended_execution_mode = order.get("execution_mode") or "foundation_supplier_pipeline"
        allow_execution = True
        reason = "low_risk_standard_execution"

    recommended_stake_required = round(
        max(stake_required, price * (0.10 + economic_risk)),
        6,
    )

    recommended_max_exposure = round(
        max(1.0, (1 - economic_risk) * 100.0),
        6,
    )

    recommended_max_price = round(
        max(price, price * (1 + economic_risk * 0.25)),
        6,
    )

    return {
        "status": "ok",
        "engine": "iat_economic_governor_v1",
        "allow_execution": allow_execution,
        "reason": reason,
        "economic_risk": round(economic_risk, 6),
        "recommended_consensus": recommended_consensus,
        "recommended_execution_mode": recommended_execution_mode,
        "recommended_stake_required": recommended_stake_required,
        "recommended_max_exposure": recommended_max_exposure,
        "recommended_max_price": recommended_max_price,
        "inputs": {
            "price": price,
            "reputation": reputation,
            "risk_score": risk_score,
            "runtime_health": runtime_health,
            "trust_score": trust_score,
            "stake_amount": stake_amount,
            "stake_required": stake_required,
        },
        "policy": {
            "foundation_controls_execution": True,
            "seller_cannot_override_economic_decision": True,
            "buyer_cannot_override_economic_decision": True,
            "recommendation_only": True,
        },
    }
