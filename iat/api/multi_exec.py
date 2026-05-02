import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


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
                "data": r.json(),
            }

        return {
            "agent_id": agent.get("agent_id"),
            "success": False,
            "latency": round(latency, 6),
            "reputation": agent.get("reputation", 0.5),
            "error": r.text,
        }

    except Exception as e:
        latency = max(time.monotonic() - start, 0)
    return {
        "agent_id": agent.get("agent_id"),
        "success": False,
        "latency": round(latency, 6),
        "reputation": agent.get("reputation", 0.5),
        "error": str(e),
    }


def multi_call(agents, order, max_workers=5):
    results = []

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
        }

    agent_sets = []
    total_weight = 0

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

        agent_sets.append({
            "agent_id": r.get("agent_id"),
            "wallet": r.get("wallet"),
            "links": links,
            "weight": rep,
        })

        total_weight += rep

    # --- GROUP BY WALLET ---
    wallet_weights = {}

    for agent in agent_sets:
        w = agent.get("wallet")
        wallet_weights.setdefault(w, 0)
        wallet_weights[w] += agent["weight"]

    # --- CAP WALLET DOMINANCE ---
    MAX_WALLET_WEIGHT = 3.0

    for agent in agent_sets:
        w = agent.get("wallet")
        total_w = wallet_weights.get(w, 0)

        if total_w > MAX_WALLET_WEIGHT:
            reduction_factor = MAX_WALLET_WEIGHT / total_w
            agent["weight"] *= reduction_factor

    #  RECOMPUTE TOTAL WEIGHT
    total_weight = sum(a["weight"] for a in agent_sets)

    # --- CALCULATE OVERLAPS FIRST ---
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

    # garder trace du poids initial (debug utile)
        agent["base_weight"] = agent["weight"]

    # 🔥 pénalité forte si overlap faible
        agent["weight"] = agent["weight"] * (0.2 + 0.8 * overlap)

    # recalcul total_weight après modification
        total_weight = sum(a["weight"] for a in agent_sets)

    # --- FINAL SCORE ---
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

    return {
        "status": status,
        "score": round(score, 4),
        "total_weight": round(total_weight, 4),
        "weighted_overlap": round(weighted_score, 4),
        "valid_agents": len(valid),
        "agent_overlaps": [
            {
                "agent_id": agent["agent_id"],
                "overlap": agent["overlap"],
                "weight": agent["weight"],
            }
            for agent in agent_sets
        ],
        "suspicious_agents": suspicious_agents,
    }
