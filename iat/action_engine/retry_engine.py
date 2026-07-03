from typing import Any, Dict


def evaluate_retry_policy(action_context: Dict[str, Any], failure_result: Dict[str, Any] = None) -> Dict[str, Any]:
    action_context = action_context or {}
    failure_result = failure_result or {}

    retry_policy = action_context.get("retry_policy") or {}
    retry_count = int(retry_policy.get("retry_count") or 0)
    max_retries = int(retry_policy.get("max_retries") or 3)

    if retry_count < max_retries:
        return {
            "status": "retry_allowed",
            "reason": "retry_count_below_max_retries",
            "action_id": action_context.get("action_id"),
            "retry_count": retry_count,
            "max_retries": max_retries,
            "next_retry_count": retry_count + 1,
            "failure_status": failure_result.get("status"),
        }

    return {
        "status": "max_retry_reached",
        "reason": "retry_count_reached_max_retries",
        "action_id": action_context.get("action_id"),
        "retry_count": retry_count,
        "max_retries": max_retries,
        "failure_status": failure_result.get("status"),
    }


def increment_retry_policy(action_context: Dict[str, Any], reason: str = "retry_scheduled") -> Dict[str, Any]:
    action_context = dict(action_context or {})
    retry_policy = dict(action_context.get("retry_policy") or {})

    retry_count = int(retry_policy.get("retry_count") or 0)
    max_retries = int(retry_policy.get("max_retries") or 3)

    retry_policy["retry_count"] = retry_count + 1
    retry_policy["max_retries"] = max_retries
    retry_policy["last_retry_reason"] = reason

    action_context["retry_policy"] = retry_policy

    return {
        "status": "retry_policy_incremented",
        "reason": reason,
        "action_id": action_context.get("action_id"),
        "retry_policy": retry_policy,
        "action_context": action_context,
    }


def inspect_retry_engine() -> Dict[str, Any]:
    return {
        "status": "ok",
        "retry_engine": "iat_action_retry_engine_v1",
        "capabilities": {
            "evaluate_retry_policy": True,
            "increment_retry_policy": True,
            "dead_letter_queue": False,
            "automatic_requeue": False,
        },
    }
