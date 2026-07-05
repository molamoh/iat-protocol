from typing import Dict, Any


def execute_adapter(
    adapter: str,
    seller_agent: Dict[str, Any],
    execution_context: Dict[str, Any],
):

    if adapter == "internal":
        return {
            "status": "ok",
            "execution_mode": "iat_internal",
            "adapter": "internal",
            "result": {
                "task": execution_context.get("task"),
                "scope": execution_context.get("scope"),
                "requested_format": execution_context.get("required_format"),
                "seller_capabilities": seller_agent.get("capabilities", []),
                "seller_specialties": seller_agent.get("specialties", []),
            },
        }

    return {
        "status": "unsupported_adapter",
        "adapter": adapter,
    }
