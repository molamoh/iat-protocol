from iat.action_engine.adapters.dry_run import execute_dry_run_action
from iat.action_engine.adapters.settlement_atomic import execute_settlement_atomic_action
from iat.action_engine.registry import resolve_adapter_for_action


def route_action(action_request):
    action_request = action_request or {}

    adapter_resolution = resolve_adapter_for_action(action_request)

    if adapter_resolution.get("status") != "adapter_resolved":
        return {
            "status": "action_rejected",
            "action_type": action_request.get("action_type", "unknown"),
            "action_scope": action_request.get("action_scope", "unknown"),
            "reason": adapter_resolution.get("reason"),
            "adapter_resolution": adapter_resolution,
        }

    adapter = adapter_resolution.get("adapter")

    if adapter == "dry_run":
        result = execute_dry_run_action(action_request)
        result["adapter_resolution"] = adapter_resolution
        return result

    if adapter == "settlement_atomic":
        result = execute_settlement_atomic_action(action_request)
        result["adapter_resolution"] = adapter_resolution
        return result

    return {
        "status": "unsupported_adapter",
        "action_type": action_request.get("action_type", "unknown"),
        "action_scope": action_request.get("action_scope", "unknown"),
        "reason": "adapter_not_supported_yet",
        "adapter": adapter,
        "adapter_resolution": adapter_resolution,
    }
