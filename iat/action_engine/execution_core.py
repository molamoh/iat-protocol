from typing import Any, Dict

from iat.action_engine.context import build_action_context, validate_action_context
from iat.api.db import (
    enqueue_action_db,
    dequeue_next_action_db,
    list_action_queue_db,
    complete_action_queue_item_db,
    record_action_execution_history_db,
    summarize_action_execution_result,
)
from iat.action_engine.pipeline_executor import execute_pipeline
from iat.action_engine.protocol_runtime import execute_protocol_order


def submit_action_to_core(
    action_type,
    action_scope,
    payload=None,
    metadata=None,
    requested_by="iat_protocol",
    priority="normal",
    timeout_seconds=300,
    retry_policy=None,
    orchestration=None,
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
        orchestration=orchestration,
    )

    validation = validate_action_context(action_context)

    if not validation.get("valid"):
        return {
            "status": "action_context_invalid",
            "reason": validation.get("reason"),
            "validation": validation,
            "queued": False,
        }

    enqueue_result = enqueue_action_db(validation.get("context"))

    return {
        "status": "submitted",
        "reason": "action_submitted_to_execution_core",
        "action_id": validation.get("context", {}).get("action_id"),
        "enqueue_result": enqueue_result,
        "action_context": validation.get("context"),
        "queued": enqueue_result.get("queued", False),
    }


def process_next_core_action() -> Dict[str, Any]:
    dequeue_result = dequeue_next_action_db()

    if dequeue_result.get("status") == "empty":
        return {
            "status": "no_action",
            "reason": "execution_core_queue_empty",
            "dequeue": dequeue_result,
            "executed": False,
        }

    item = dequeue_result.get("item") or {}
    action_context = item.get("action_context") or item.get("context") or {}

    payload = action_context.get("payload") or {}

    if action_context.get("action_type") == "protocol_order":
        result = execute_protocol_order(
            payload.get("order") or {},
            payload.get("tx_signature"),
        )
    else:
        result = execute_pipeline(action_context)

    result["dequeue"] = dequeue_result

    success_statuses = {
        "ok",
        "success",
        "completed",
        "pipeline_completed",
        "foundation_supplier_pipeline_completed",
        "consensus_delivered",
    }

    result["executed"] = bool(
        result.get("executed")
        or str(result.get("status") or "").lower() in success_statuses
    )

    action_id = action_context.get("action_id")

    history = record_action_execution_history_db(action_context, result)
    result_summary = summarize_action_execution_result(result)

    completion = complete_action_queue_item_db(action_id, result_summary)

    result["execution_history"] = history
    result["queue_completion"] = completion

    return result


def inspect_execution_core() -> Dict[str, Any]:
    queue_state = list_action_queue_db()

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
            "persistent_queue": True,
            "distributed_workers": False,
        },
    }
