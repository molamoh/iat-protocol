from typing import Any, Dict

from iat.action_engine.queue import dequeue_next_action
from iat.action_engine.scheduler import compute_action_schedule
from iat.action_engine.dispatcher import dispatch_action
from iat.action_engine.router import route_action


def process_next_action() -> Dict[str, Any]:
    dequeue_result = dequeue_next_action()

    if dequeue_result.get("status") == "empty":
        return {
            "status": "no_action",
            "reason": "queue_empty",
            "dequeue": dequeue_result,
            "executed": False,
        }

    item = dequeue_result.get("item") or {}
    action_context = item.get("context") or {}

    schedule = compute_action_schedule(action_context)

    if not schedule.get("ready_to_execute"):
        return {
            "status": "action_not_ready",
            "reason": schedule.get("reason"),
            "dequeue": dequeue_result,
            "schedule": schedule,
            "action_context": action_context,
            "executed": False,
        }

    dispatch = dispatch_action(action_context)

    if dispatch.get("status") != "dispatched":
        return {
            "status": "action_dispatch_failed",
            "reason": dispatch.get("reason"),
            "dequeue": dequeue_result,
            "schedule": schedule,
            "dispatch": dispatch,
            "action_context": action_context,
            "executed": False,
        }

    result = route_action(action_context)
    result["dequeue"] = dequeue_result
    result["schedule"] = schedule
    result["dispatch"] = dispatch
    result["action_context"] = action_context
    result["executed"] = result.get("status") not in (
        "action_rejected",
        "unsupported_adapter",
    )

    return result
