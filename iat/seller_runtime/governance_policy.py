from typing import Dict, Any


MIN_TRUST_SCORE = 20
MAX_RISK_SCORE = 80


def evaluate_governance_policy(
    seller_agent: Dict[str, Any],
) -> Dict[str, Any]:

    trust = float(seller_agent.get("trust_score", 50))
    risk = float(seller_agent.get("risk_score", 0))

    if trust < MIN_TRUST_SCORE:
        return {
            "allowed": False,
            "reason": "trust_score_too_low",
            "trust_score": trust,
        }

    if risk > MAX_RISK_SCORE:
        return {
            "allowed": False,
            "reason": "risk_score_too_high",
            "risk_score": risk,
        }

    return {
        "allowed": True,
        "reason": "governance_policy_allowed",
        "trust_score": trust,
        "risk_score": risk,
    }
