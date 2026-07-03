import time
from typing import Any, Dict

from iat.action_engine.context import normalize_action_context, validate_action_context


PRIORITY_RANK = {
    "low": 10,
    "normal": 50,
    "high": 80,
    "critical": 100,
}


def now_ts() -> int:
    return int(time.time())


def compute_action_schedule(action_context: Dict[str, Any]) -> Dict[str, Any]:
    validation = validate_action_context(action_context)

    if not validation.get("valid"):
        return {
            "status": "schedule_rejected",
            "reason": validation.get("reason"),
            "validation": validation,
            "ready_to_execute": False,
        }

    ctx = normalize_action_context(validation.get("context"))
    metadata = ctx.get("metadata") or {}

    priority = str(ctx.get("priority") or "normal")
    priority_rank = PRIORITY_RANK.get(priority, PRIORITY_RANK["normal"])

    scheduled_for = int(metadata.get("scheduled_for") or ctx.get("created_at") or now_ts())
    current_time = now_ts()

    if metadata.get("blocked") is True:
        return {
            "status": "blocked",
            "reason": metadata.get("blocked_reason") or "action_blocked_by_metadata",
            "action_id": ctx.get("action_id"),
            "action_type": ctx.get("action_type"),
            "priority": priority,
            "priority_rank": priority_rank,
            "scheduled_for": scheduled_for,
            "ready_to_execute": False,
        }

    if scheduled_for > current_time:
        return {
            "status": "scheduled",
            "reason": "action_scheduled_for_future",
            "action_id": ctx.get("action_id"),
            "action_type": ctx.get("action_type"),
            "priority": priority,
            "priority_rank": priority_rank,
            "scheduled_for": scheduled_for,
            "now": current_time,
            "ready_to_execute": False,
        }

    return {
        "status": "ready",
        "reason": "action_ready_to_execute",
        "action_id": ctx.get("action_id"),
        "action_type": ctx.get("action_type"),
        "priority": priority,
        "priority_rank": priority_rank,
        "scheduled_for": scheduled_for,
        "now": current_time,
        "ready_to_execute": True,
    }


def should_execute_now(action_context: Dict[str, Any]) -> bool:
    schedule = compute_action_schedule(action_context)
    return bool(schedule.get("ready_to_execute"))
