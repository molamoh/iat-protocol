from typing import Dict, Any


def execute_http_adapter(
    seller_agent: Dict[str, Any],
    execution_context: Dict[str, Any],
):
    return {
        "status": "unsupported_adapter",
        "adapter": "http",
        "reason": "http_adapter_not_enabled_yet",
    }
