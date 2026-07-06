from typing import Dict, Any


def compute_runtime_score(agent: Dict[str, Any]) -> float:
    success = float(agent.get("success_rate", 0.0))
    reputation = float(agent.get("reputation", 0.0))
    trust = float(agent.get("trust_score", 50.0)) / 100.0
    health = float(agent.get("runtime_health_score", 50.0)) / 100.0

    score = (
        success * 0.35 +
        reputation * 0.25 +
        trust * 0.20 +
        health * 0.20
    )

    return round(score, 6)
