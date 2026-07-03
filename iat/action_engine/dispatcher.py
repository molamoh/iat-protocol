from typing import Any, Dict

from iat.action_engine.context import normalize_action_context, validate_action_context


def dispatch_action(action_context: Dict[str, Any]) -> Dict[str, Any]:
    validation = validate_action_context(action_context)

    if not validation.get("valid"):
        return {
            "status": "dispatch_rejected",
            "reason": validation.get("reason"),
            "validation": validation,
            "dispatch_target": None,
        }

    ctx = normalize_action_context(validation.get("context"))
    metadata = ctx.get("metadata") or {}

    requested_target = metadata.get("dispatch_target")

    if requested_target:
        dispatch_target = requested_target
        dispatch_mode = "explicit_target"
    else:
        dispatch_target = "local_action_engine"
        dispatch_mode = "default_local"

    return {
        "status": "dispatched",
        "reason": "action_dispatch_target_resolved",
        "action_id": ctx.get("action_id"),
        "action_type": ctx.get("action_type"),
        "dispatch_target": dispatch_target,
        "dispatch_mode": dispatch_mode,
        "execution_node": "local",
    }
