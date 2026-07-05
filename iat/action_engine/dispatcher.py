from typing import Any, Dict

from iat.action_engine.context import normalize_action_context, validate_action_context
from iat.api.db import get_action_circuit_breaker_db


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
    service_name = (
        ctx.get("action_scope")
        or ctx.get("action_type")
        or "default"
    )

    breaker = get_action_circuit_breaker_db(service_name).get("breaker")

    if breaker and breaker.get("state") == "OPEN":
        return {
            "status": "blocked_by_circuit_breaker",
            "reason": "service_circuit_open",
            "service_name": service_name,
            "breaker": breaker,
            "dispatch_target": None,
        }

    if breaker and breaker.get("state") == "HALF_OPEN":
        metadata["circuit_breaker_probe"] = True


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
