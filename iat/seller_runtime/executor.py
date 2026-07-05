from typing import Dict, Any

from iat.seller_runtime.adapters import execute_adapter


def execute_seller_agent(
    seller_agent: Dict[str, Any],
    execution_context: Dict[str, Any],
):
    adapter = (
        seller_agent.get("runtime_adapter")
        or seller_agent.get("adapter")
        or "internal"
    )

    return execute_adapter(
        adapter,
        seller_agent,
        execution_context,
    )
