from typing import Any, Dict

from iat.action_engine.context import build_action_context, validate_action_context
from iat.action_engine.queue import enqueue_action, dequeue_next_action, list_queued_actions
from iat.action_engine.pipeline_executor import execute_pipeline


def submit_action_to_core(
    action_type,
    action_scope,
    payload=None,
    metadata=None,
    requested_by="iat_protocol",
    priority="normal",
    timeout_seconds=300,
    retry_policy=None,
) -> Dict[str, Any]:
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
            "queued": False,
        }

    enqueue_result = enqueue_action(validation.get("context"))

    return {
        "status": "submitted",
        "reason": "action_submitted_to_execution_core",
        "action_id": validation.get("context", {}).get("action_id"),
        "enqueue_result": enqueue_result,
        "action_context": validation.get("context"),
        "queued": enqueue_result.get("queued", False),
    }


def process_next_core_action() -> Dict[str, Any]:
    dequeue_result = dequeue_next_action()

    if dequeue_result.get("status") == "empty":
        return {
            "status": "no_action",
            "reason": "execution_core_queue_empty",
            "dequeue": dequeue_result,
            "executed": False,
        }

    item = dequeue_result.get("item") or {}
    action_context = item.get("context") or {}

    result = execute_pipeline(action_context)
    result["dequeue"] = dequeue_result
    return result


def inspect_execution_core() -> Dict[str, Any]:
    queue_state = list_queued_actions()

    return {
        "status": "ok",
        "execution_core": "iat_action_execution_core_v1",
        "queue": queue_state,
        "capabilities": {
            "queue": True,
            "scheduler": True,
            "dispatcher": True,
            "router": True,
            "worker": True,
            "persistent_queue": False,
            "distributed_workers": False,
        },
    }
