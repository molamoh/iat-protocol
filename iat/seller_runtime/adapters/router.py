from typing import Dict, Any

from iat.seller_runtime.adapters.internal import execute_internal_adapter


def execute_adapter(
    adapter: str,
    seller_agent: Dict[str, Any],
    execution_context: Dict[str, Any],
):
    adapter = str(adapter or "internal").lower()

    if adapter == "internal":
        return execute_internal_adapter(
            seller_agent,
            execution_context,
        )

    return {
        "status": "unsupported_adapter",
        "adapter": adapter,
    }
