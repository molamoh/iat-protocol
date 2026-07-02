from iat.action_engine.models import build_action_result


def execute_dry_run_action(action_request):
    action_request = action_request or {}

    return build_action_result(
        status="dry_run_executed",
        action_type=action_request.get("action_type", "unknown"),
        action_scope=action_request.get("action_scope", "unknown"),
        result={
            "dry_run": True,
            "input_payload": action_request.get("payload") or {},
        },
        reason="action_engine_dry_run_adapter",
    )
