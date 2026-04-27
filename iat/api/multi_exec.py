import time
import requests


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
            timeout=10,
        )

        latency = max(time.monotonic() - start, 0)

        if r.status_code == 200:
            return {
                "agent_id": agent["agent_id"],
                "success": True,
                "latency": round(latency, 6),
                "data": r.json(),
            }

        return {
            "agent_id": agent["agent_id"],
            "success": False,
            "latency": round(latency, 6),
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


def multi_call(agents, order):
    return [call_agent(agent, order) for agent in agents]


def select_best_result(results):
    valid = [r for r in results if r.get("success")]

    if not valid:
        return None

    return min(valid, key=lambda r: r["latency"])
