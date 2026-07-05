from typing import Dict, Any


def compute_runtime_trust(
    seller_agent: Dict[str, Any],
) -> Dict[str, Any]:

    success_rate = float(seller_agent.get("success_rate", 0.5))
    reputation = float(seller_agent.get("reputation", 0.5))
    governance = float(seller_agent.get("governance_score", 50))
    health = float(seller_agent.get("runtime_health_score", 50))

    trust = (
        success_rate * 40 +
        reputation * 20 +
        governance * 0.20 +
        health * 0.20
    )

    risk = max(0.0, 100.0 - trust)

    return {
        "trust_score": round(trust, 2),
        "risk_score": round(risk, 2),
    }
