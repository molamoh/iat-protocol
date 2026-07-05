from typing import Dict, Any

from iat.seller_runtime.executor import execute_seller_agent


def run_seller_runtime(
    seller_agent: Dict[str, Any],
    execution_context: Dict[str, Any],
):
    return execute_seller_agent(
        seller_agent,
        execution_context,
    )
