from iat.action_engine.adapters.dry_run import execute_dry_run_action


def route_action(action_request):
    action_request = action_request or {}
    metadata = action_request.get("metadata") or {}

    execution_mode = metadata.get("execution_mode", "dry_run")

    if execution_mode == "dry_run":
        return execute_dry_run_action(action_request)

    return {
        "status": "unsupported_execution_mode",
        "action_type": action_request.get("action_type", "unknown"),
        "action_scope": action_request.get("action_scope", "unknown"),
        "reason": "execution_mode_not_supported_yet",
        "execution_mode": execution_mode,
    }
