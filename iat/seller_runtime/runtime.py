from typing import Dict, Any

from iat.seller_runtime.executor import execute_seller_agent
from iat.seller_runtime.service_registry import resolve_service
from iat.seller_runtime.adapter_registry import resolve_adapter
from iat.seller_runtime.runtime_policy import evaluate_seller_runtime_policy


def run_seller_runtime(
    seller_agent: Dict[str, Any],
    execution_context: Dict[str, Any],
):
    seller_agent = dict(seller_agent or {})
    execution_context = dict(execution_context or {})

    service = (
        execution_context.get("service")
        or seller_agent.get("service")
    )

    resolved = resolve_service(service)

    adapter = resolve_adapter(
        seller_agent.get("runtime_adapter")
        or resolved["preferred_adapter"]
    )

    seller_agent["runtime_adapter"] = adapter["adapter"]

    if not seller_agent.get("capabilities"):
        seller_agent["capabilities"] = [
            resolved["default_capability"]
        ]

    policy = evaluate_seller_runtime_policy(
        seller_agent,
        execution_context,
    )

    if not policy.get("allowed"):
        return {
            "status": "runtime_policy_blocked",
            "adapter": seller_agent.get("runtime_adapter"),
            "policy": policy,
        }

    result = execute_seller_agent(
        seller_agent,
        execution_context,
    )

    if isinstance(result, dict):
        result["runtime_policy"] = policy

    return result
