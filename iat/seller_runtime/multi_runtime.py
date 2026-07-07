from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

from iat.seller_runtime.runtime import run_seller_runtime
from iat.seller_runtime.runtime_resolver import resolve_seller_runtime_agent


def run_multi_seller_runtime(
    service: str,
    execution_context: Dict[str, Any],
    candidate_agents: List[Dict[str, Any]],
    max_workers: int = 3,
) -> Dict[str, Any]:
    candidate_agents = candidate_agents or []
    max_workers = max(1, min(int(max_workers or 3), len(candidate_agents) or 1))

    if not candidate_agents:
        return {
            "status": "error",
            "message": "no_candidate_seller_runtime_agents",
            "results": [],
        }

    selected = []

    for agent in candidate_agents:
        resolution = resolve_seller_runtime_agent(
            service=service,
            execution_context=execution_context,
            candidate_agents=[agent],
        )
        resolved = resolution.get("agent") or {}
        if resolved:
            selected.append({
                "resolution": resolution,
                "agent": resolved,
            })

    if not selected:
        return {
            "status": "error",
            "message": "no_resolved_seller_runtime_agents",
            "results": [],
        }

    results = []

    def execute(item):
        agent = item["agent"]
        resolution = item["resolution"]

        runtime_result = run_seller_runtime(
            agent,
            execution_context,
        )

        success = runtime_result.get("status") == "ok"

        result_payload = runtime_result.get("result") or {}

        return {
            "success": success,
            "agent_id": agent.get("agent_id"),
            "seller_agent_id": agent.get("seller_agent_id"),
            "seller_id": agent.get("seller_id"),
            "service": service,
            "adapter": runtime_result.get("adapter"),
            "execution_mode": runtime_result.get("execution_mode"),
            "runtime_score": agent.get("runtime_score"),
            "reputation": agent.get("reputation", 0.5),
            "risk_score": float(agent.get("risk_score", 0) or 0),
            "latency": float(agent.get("latency", 1) or 1),
            "data": {
                "summary": result_payload.get("summary"),
                "confidence": result_payload.get("confidence", 0.5),
                "claims": result_payload.get("analysis_points", []),
                "entities": [
                    result_payload.get("scope", {}).get("asset"),
                    result_payload.get("scope", {}).get("service"),
                ],
                "structured_signals": {
                    "runtime_adapter": runtime_result.get("adapter"),
                    "execution_mode": runtime_result.get("execution_mode"),
                },
                "metrics": {
                    "confidence": result_payload.get("confidence", 0.5),
                    "runtime_score": agent.get("runtime_score"),
                },
                "raw": runtime_result,
            },
            "runtime": runtime_result,
            "runtime_resolution": resolution,
        }

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(execute, item) for item in selected]
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({
                    "success": False,
                    "error": str(exc),
                    "failure_type": "runtime_exception",
                })

    return {
        "status": "ok",
        "results": results,
        "agents_count": len(selected),
    }
