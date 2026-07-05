import time
from iat.action_engine.unified_trust_engine import compute_unified_trust_score


def compute_agent_score(agent, now=None):
    now = now or int(time.time())

    price = float(agent.get("price_iat") or 999999)
    reputation = float(agent.get("reputation") or 0)
    updated_at = int(agent.get("updated_at") or 0)

    latency = float(agent.get("latency") or 1)
    success_rate = float(agent.get("success_rate") or 1)

    age_seconds = max(now - updated_at, 0)

    freshness_score = max(0.1, 1 - (age_seconds / 120))
    price_score = 1 / price if price > 0 else 0
    latency_score = 1 / latency if latency > 0 else 0

    local_score = (
        reputation * 0.45 +
        price_score * 0.25 +
        freshness_score * 0.10 +
        latency_score * 0.10 +
        success_rate * 0.10
    )

    unified = agent.get("unified_trust")

    if unified is None:
        unified = compute_unified_trust_score({
            "entity_id": agent.get("agent_id") or agent.get("seller_agent_id") or agent.get("id"),
            "entity_type": agent.get("agent_type") or "execution_agent",
            "reputation": reputation * 100 if reputation <= 1 else reputation,
            "trust_score": agent.get("trust_score", agent.get("trust", 50)),
            "risk_score": agent.get("risk_score", agent.get("risk", 50)),
            "reliability_score": success_rate * 100 if success_rate <= 1 else success_rate,
            "runtime_health_score": agent.get("runtime_health_score", freshness_score * 100),
            "governance_score": agent.get("governance_score", 50),
        })

    local_score_100 = max(0, min(100, local_score * 100))

    final_score = round(
        (local_score_100 * 0.50) + (unified.get("score", 50) * 0.50),
        6,
    )

    return final_score


def rank_agents(agents):
    now = int(time.time())

    ranked = []
    for agent in agents:
        item = dict(agent)

        unified = compute_unified_trust_score({
            "entity_id": item.get("agent_id"),
            "entity_type": item.get("agent_type","seller_agent"),
            "reputation": float(item.get("reputation",0))*100,
            "trust_score": float(item.get("trust_score",50)),
            "risk_score": float(item.get("risk_score",50)),
            "reliability_score": float(item.get("success_rate",0))*100,
            "runtime_health_score": float(item.get("runtime_health_score",50)),
            "governance_score": float(item.get("governance_score",50)),
        })

        item["unified_trust"] = unified
        item["score"] = compute_agent_score(item, now=now)

        ranked.append(item)

    ranked.sort(key=lambda a: a["score"], reverse=True)
    return ranked


def select_best_agent(agents):
    ranked = rank_agents(agents)

    if not ranked:
        return None

    return ranked[0]
