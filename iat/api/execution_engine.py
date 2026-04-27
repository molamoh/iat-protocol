import time


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

    final_score = (
        reputation * 0.45 +
        price_score * 0.25 +
        freshness_score * 0.10 +
        latency_score * 0.10 +
        success_rate * 0.10
    )

    return round(final_score, 6)


def rank_agents(agents):
    now = int(time.time())

    ranked = []
    for agent in agents:
        item = dict(agent)
        item["score"] = compute_agent_score(agent, now=now)
        ranked.append(item)

    ranked.sort(key=lambda a: a["score"], reverse=True)
    return ranked


def select_best_agent(agents):
    ranked = rank_agents(agents)

    if not ranked:
        return None

    return ranked[0]
