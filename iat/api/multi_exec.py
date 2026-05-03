import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


def compute_agent_market_score(agent):
    """
    Market pre-selection score.
    Same wallet is NOT penalized here.
    We rank agents by reliability, history, price, and availability.
    """
    if not bool(agent.get("available", True)):
        return -999999

    reputation = float(agent.get("reputation", 0.5) or 0.5)
    price = float(agent.get("price", 1.0) or 1.0)
    successes = int(agent.get("success_count", 0) or 0)
    failures = int(agent.get("failure_count", 0) or 0)
    call_count = int(agent.get("call_count", 0) or 0)
    win_count = int(agent.get("win_count", 0) or 0)
    latency_total = float(agent.get("latency_total", 0) or 0)

    avg_latency = (latency_total / call_count) if call_count > 0 else None

    # Anti-gaming:
    # Win rate only becomes meaningful after enough calls.
    raw_win_rate = (win_count / call_count) if call_count > 0 else 0

    confidence = min(call_count / 10, 1.0)
    adjusted_win_rate = raw_win_rate * confidence

    success_bonus = min(successes * 0.03, 0.30)
    failure_penalty = failures * 0.25
    win_rate_bonus = adjusted_win_rate * 0.35

    price_score = 1 / (price + 0.001)

    # Stability: reward low average latency over time.
    stability_bonus = 0
    if avg_latency is not None:
        stability_bonus = min(1 / (avg_latency + 0.1), 1.0) * 0.15

    score = (
        reputation * 1.5
        + success_bonus
        + win_rate_bonus
        + stability_bonus
        + price_score * 0.25
        - failure_penalty
    )

    return round(score, 6)


def select_top_agents(agents, limit=3):
    """
    Select best available agents before execution.
    This reduces cost and avoids calling disabled/bad agents.
    """
    available_agents = [
        a for a in agents
        if bool(a.get("available", True))
    ]

    ranked = sorted(
        available_agents,
        key=compute_agent_market_score,
        reverse=True,
    )

    return ranked[:limit]



def call_agent(agent, order):
    start = time.monotonic()

    try:
        r = requests.post(
            f"{agent['url']}/execute",
            json={
                "order_id": order.get("order_id", "test"),
                "tx_signature": order.get("tx_signature"),
                "query": order.get("query"),
            },
            timeout=15,
        )

        latency = max(time.monotonic() - start, 0)

        if r.status_code == 200:
            return {
                "agent_id": agent.get("agent_id"),
                "wallet": agent.get("wallet"),  # ✅ AJOUT
                "success": True,
                "latency": round(latency, 6),
                "reputation": agent.get("reputation", 0.5),
                "success_count": agent.get("success_count", 0),
                "failure_count": agent.get("failure_count", 0),
                "call_count": agent.get("call_count", 0),
                "win_count": agent.get("win_count", 0),
                "latency_total": agent.get("latency_total", 0),
                "data": r.json(),
            }

        return {
            "agent_id": agent.get("agent_id"),
            "success": False,
            "latency": round(latency, 6),
            "reputation": agent.get("reputation", 0.5),
            "success_count": agent.get("success_count", 0),
            "failure_count": agent.get("failure_count", 0),
            "call_count": agent.get("call_count", 0),
            "win_count": agent.get("win_count", 0),
            "latency_total": agent.get("latency_total", 0),
            "error": r.text,
        }

    except Exception as e:
        latency = max(time.monotonic() - start, 0)
    return {
        "agent_id": agent.get("agent_id"),
        "success": False,
        "latency": round(latency, 6),
        "reputation": agent.get("reputation", 0.5),
        "success_count": agent.get("success_count", 0),
        "failure_count": agent.get("failure_count", 0),
        "call_count": agent.get("call_count", 0),
        "win_count": agent.get("win_count", 0),
        "latency_total": agent.get("latency_total", 0),
        "error": str(e),
    }


def multi_call(agents, order, max_workers=5):
    results = []

    # Do not call disabled / killed agents
    agents = [
        a for a in agents
        if bool(a.get("available", True))
    ]

    if not agents:
        return results

    workers = min(max_workers, len(agents))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(call_agent, agent, order)
            for agent in agents
            if agent.get("url")
        ]

        for future in as_completed(futures):
            results.append(future.result())

    return results


def compute_quality(result):


    data = result.get("data", {}).get("data", {})
    results = data.get("results", [])

    quality = len(results)

    if results:
        first = results[0]
        if first.get("title"):
            quality += 1
        if first.get("snippet"):
            quality += 1
        if first.get("link"):
            quality += 1

    latency = result.get("latency", 1)
    latency_score = 1 / (latency + 0.001)

    return quality * 2 + latency_score


def select_best_result(results):
    valid = [r for r in results if r.get("success")]

    if not valid:
        return None

    return max(valid, key=compute_quality)

def compute_consensus(results):
    valid = [r for r in results if r.get("success")]

    if not valid:
        return {
            "status": "failed",
            "score": 0,
            "valid_agents": 0,
            "reason": "no_successful_results",
            "suspicious_agents": [],
            "collusion_flags": [],
        }

    agent_sets = []

    # --- BUILD AGENTS ---
    for r in valid:
        data = r.get("data", {}).get("data", {})
        items = data.get("results", [])

        links = set()
        for item in items[:5]:
            link = item.get("link")
            if link:
                links.add(link.strip().lower())

        rep = float(r.get("reputation", 0.5))
        successes = int(r.get("success_count", 0) or 0)
        failures = int(r.get("failure_count", 0) or 0)

        success_factor = 1 + min(successes * 0.02, 0.20)
        failure_factor = 1 / (1 + failures)

        base_weight = rep * success_factor * failure_factor

        agent_sets.append({
            "agent_id": r.get("agent_id"),
            "wallet": r.get("wallet"),
            "links": links,
            "base_weight": base_weight,
            "weight": base_weight,
        })

    # --- WALLET DIAGNOSTIC ONLY ---
    wallet_weights = {}
    for agent in agent_sets:
        w = agent.get("wallet") or "UNKNOWN"
        wallet_weights.setdefault(w, 0)
        wallet_weights[w] += agent["weight"]

    # --- CALCULATE OVERLAPS ---
    for agent in agent_sets:
        links = agent["links"]

        if not links:
            agent["overlap"] = 0
            continue

        other_links = set()
        for other in agent_sets:
            if other["agent_id"] != agent["agent_id"]:
                other_links.update(other["links"])

        overlap = len(links.intersection(other_links)) / len(links)
        agent["overlap"] = round(overlap, 4)

    # --- DYNAMIC WEIGHT BY BEHAVIOR ---
    for agent in agent_sets:
        overlap = float(agent.get("overlap", 0))
        agent["weight"] = agent["weight"] * (0.2 + 0.8 * overlap)

    total_weight = sum(a["weight"] for a in agent_sets)

    weighted_score = 0
    for agent in agent_sets:
        weighted_score += agent["overlap"] * agent["weight"]

    score = weighted_score / total_weight if total_weight > 0 else 0
    status = "passed" if score >= 0.60 else "suspicious"

    suspicious_agents = [
        agent["agent_id"]
        for agent in agent_sets
        if agent["overlap"] < 0.5
    ]

    # --- WALLET COLLUSION DIAGNOSTIC ---
    wallet_groups = {}
    for agent in agent_sets:
        wallet = agent.get("wallet") or "UNKNOWN"
        wallet_groups.setdefault(wallet, []).append(agent)

    collusion_flags = []

    def overlap_between(a, b):
        links_a = a.get("links", set())
        links_b = b.get("links", set())

        if not links_a or not links_b:
            return 0

        return len(links_a.intersection(links_b)) / max(len(links_a), 1)

    for wallet, group in wallet_groups.items():
        if len(group) < 2:
            continue

        other_agents = [
            a for a in agent_sets
            if (a.get("wallet") or "UNKNOWN") != wallet
        ]

        if not other_agents:
            continue

        internal_scores = []
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                internal_scores.append(overlap_between(a, b))

        external_scores = []
        for a in group:
            for b in other_agents:
                external_scores.append(overlap_between(a, b))

        internal_avg = sum(internal_scores) / len(internal_scores) if internal_scores else 0
        external_avg = sum(external_scores) / len(external_scores) if external_scores else 0

        if internal_avg >= 0.8 and external_avg <= 0.3:
            for agent in group:
                collusion_flags.append({
                    "agent_id": agent.get("agent_id"),
                    "wallet": wallet,
                    "internal_overlap": round(internal_avg, 4),
                    "external_overlap": round(external_avg, 4),
                    "reason": "same_wallet_cluster_low_external_agreement",
                })

    collusion_agent_ids = set(flag["agent_id"] for flag in collusion_flags)
    suspicious_agents = list(set(suspicious_agents).union(collusion_agent_ids))

    return {
        "status": status,
        "score": round(score, 4),
        "total_weight": round(total_weight, 4),
        "weighted_overlap": round(weighted_score, 4),
        "valid_agents": len(valid),
        "agent_overlaps": [
            {
                "agent_id": a["agent_id"],
                "overlap": a["overlap"],
                "base_weight": round(a["base_weight"], 4),
                "weight": round(a["weight"], 4),
            }
            for a in agent_sets
        ],
        "wallet_weights": {
            wallet: round(weight, 4)
            for wallet, weight in wallet_weights.items()
        },
        "suspicious_agents": suspicious_agents,
        "collusion_flags": collusion_flags,
    }

