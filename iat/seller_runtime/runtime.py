from typing import Dict, Any

from iat.seller_runtime.executor import execute_seller_agent
from iat.seller_runtime.service_registry import resolve_service


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

    seller_agent.setdefault(
        "runtime_adapter",
        resolved["preferred_adapter"],
    )

    if not seller_agent.get("capabilities"):
        seller_agent["capabilities"] = [
            resolved["default_capability"]
        ]

    return execute_seller_agent(
        seller_agent,
        execution_context,
    )
