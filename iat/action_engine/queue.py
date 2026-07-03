import time
from typing import Any, Dict, List, Optional

from iat.action_engine.context import normalize_action_context, validate_action_context


_ACTION_QUEUE: List[Dict[str, Any]] = []


def now_ts() -> int:
    return int(time.time())


def enqueue_action(action_context: Dict[str, Any]) -> Dict[str, Any]:
    validation = validate_action_context(action_context)

    if not validation.get("valid"):
        return {
            "status": "enqueue_rejected",
            "reason": validation.get("reason"),
            "validation": validation,
            "queued": False,
        }

    ctx = normalize_action_context(validation.get("context"))

    queue_item = {
        "queue_status": "queued",
        "action_id": ctx.get("action_id"),
        "action_type": ctx.get("action_type"),
        "priority": ctx.get("priority"),
        "created_at": ctx.get("created_at"),
        "queued_at": now_ts(),
        "attempts": 0,
        "context": ctx,
    }

    _ACTION_QUEUE.append(queue_item)

    return {
        "status": "queued",
        "reason": "action_enqueued",
        "action_id": ctx.get("action_id"),
        "queue_size": len(_ACTION_QUEUE),
        "queued": True,
    }


def list_queued_actions() -> Dict[str, Any]:
    return {
        "status": "ok",
        "queue_size": len(_ACTION_QUEUE),
        "actions": [
            {
                "queue_status": item.get("queue_status"),
                "action_id": item.get("action_id"),
                "action_type": item.get("action_type"),
                "priority": item.get("priority"),
                "queued_at": item.get("queued_at"),
                "attempts": item.get("attempts"),
            }
            for item in _ACTION_QUEUE
        ],
    }


def dequeue_next_action() -> Dict[str, Any]:
    if not _ACTION_QUEUE:
        return {
            "status": "empty",
            "reason": "action_queue_empty",
            "item": None,
        }

    priority_rank = {
        "low": 10,
        "normal": 50,
        "high": 80,
        "critical": 100,
    }

    best_index = 0
    best_score = -1

    for index, item in enumerate(_ACTION_QUEUE):
        priority = item.get("priority") or "normal"
        score = priority_rank.get(priority, priority_rank["normal"])

        if score > best_score:
            best_score = score
            best_index = index

    item = _ACTION_QUEUE.pop(best_index)
    item["queue_status"] = "dequeued"
    item["dequeued_at"] = now_ts()
    item["attempts"] = int(item.get("attempts") or 0) + 1

    return {
        "status": "dequeued",
        "reason": "action_dequeued",
        "item": item,
        "queue_size": len(_ACTION_QUEUE),
    }


def clear_action_queue() -> Dict[str, Any]:
    count = len(_ACTION_QUEUE)
    _ACTION_QUEUE.clear()

    return {
        "status": "cleared",
        "reason": "action_queue_cleared",
        "cleared_count": count,
        "queue_size": 0,
    }


def get_queue_size() -> int:
    return len(_ACTION_QUEUE)
