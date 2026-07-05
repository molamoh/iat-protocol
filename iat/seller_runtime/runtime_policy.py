from typing import Dict, Any


def evaluate_seller_runtime_policy(
    seller_agent: Dict[str, Any],
    execution_context: Dict[str, Any],
):
    adapter = str(seller_agent.get("runtime_adapter") or "").lower()

    if not adapter:
        return {
            "allowed": False,
            "reason": "runtime_adapter_missing",
        }

    if adapter == "http":
        endpoint = seller_agent.get("endpoint") or seller_agent.get("url")
        if not endpoint:
            return {
                "allowed": False,
                "reason": "http_endpoint_missing",
            }

    if execution_context.get("buyer_data_stripped") is False:
        return {
            "allowed": False,
            "reason": "buyer_data_not_stripped",
        }

    if execution_context.get("foundation_mediated") is False:
        return {
            "allowed": False,
            "reason": "execution_not_foundation_mediated",
        }

    return {
        "allowed": True,
        "reason": "runtime_policy_allowed",
    }
