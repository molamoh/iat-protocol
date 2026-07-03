from iat.action_engine.context import build_action_context, validate_action_context
from iat.action_engine.router import route_action
from iat.action_engine.scheduler import compute_action_schedule


def execute_action(
    action_type,
    action_scope,
    payload=None,
    metadata=None,
    requested_by="iat_protocol",
    priority="normal",
    timeout_seconds=300,
    retry_policy=None,
):
    action_context = build_action_context(
        action_type=action_type,
        action_scope=action_scope,
        payload=payload or {},
        metadata=metadata or {},
        requested_by=requested_by,
        priority=priority,
        timeout_seconds=timeout_seconds,
        retry_policy=retry_policy,
    )

    validation = validate_action_context(action_context)

    if not validation.get("valid"):
        return {
            "status": "action_context_invalid",
            "reason": validation.get("reason"),
            "validation": validation,
        }

    schedule = compute_action_schedule(validation.get("context"))

    if not schedule.get("ready_to_execute"):
        return {
            "status": "action_not_ready",
            "reason": schedule.get("reason"),
            "schedule": schedule,
            "action_context": validation.get("context"),
        }

    result = route_action(validation.get("context"))
    result["action_context"] = validation.get("context")
    result["schedule"] = schedule
    return result
