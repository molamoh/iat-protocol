from typing import Any, Callable, Dict

from iat.action_engine.scheduler import compute_action_schedule
from iat.action_engine.dispatcher import dispatch_action
from iat.action_engine.router import route_action


def run_scheduler_stage(action_context: Dict[str, Any]) -> Dict[str, Any]:
    schedule = compute_action_schedule(action_context)

    return {
        "stage": "scheduler",
        "status": "completed" if schedule.get("ready_to_execute") else "blocked",
        "result": schedule,
        "continue_pipeline": bool(schedule.get("ready_to_execute")),
        "reason": schedule.get("reason"),
    }


def run_dispatcher_stage(action_context: Dict[str, Any]) -> Dict[str, Any]:
    dispatch = dispatch_action(action_context)

    return {
        "stage": "dispatcher",
        "status": "completed" if dispatch.get("status") == "dispatched" else "failed",
        "result": dispatch,
        "continue_pipeline": dispatch.get("status") == "dispatched",
        "reason": dispatch.get("reason"),
    }


def run_router_stage(action_context: Dict[str, Any]) -> Dict[str, Any]:
    routed = route_action(action_context)

    return {
        "stage": "router",
        "status": "completed"
        if routed.get("status") not in ("action_rejected", "unsupported_adapter")
        else "failed",
        "result": routed,
        "continue_pipeline": routed.get("status") not in ("action_rejected", "unsupported_adapter"),
        "reason": routed.get("reason"),
    }


PIPELINE_STAGE_REGISTRY: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "scheduler": run_scheduler_stage,
    "dispatcher": run_dispatcher_stage,
    "router": run_router_stage,
}


def get_pipeline_stage(stage_name: str):
    return PIPELINE_STAGE_REGISTRY.get(str(stage_name or ""))
