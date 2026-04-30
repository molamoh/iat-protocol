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
        }

    weights = {}
    total_weight = 0

    for r in valid:
        data = r.get("data", {}).get("data", {})
        items = data.get("results", [])

        links = []
        for item in items[:5]:
            link = item.get("link")
            if link:
                links.append(link.strip().lower())

        signature = tuple(sorted(links))

        rep = r.get("reputation", 0.5)

        weights[signature] = weights.get(signature, 0) + rep
        total_weight += rep

    best_weight = max(weights.values()) if weights else 0
    score = best_weight / total_weight if total_weight > 0 else 0

    return {
        "status": "passed" if score >= 0.66 else "suspicious",
        "score": round(score, 4),
        "total_weight": round(total_weight, 4),
        "winning_weight": round(best_weight, 4),
    }
