from typing import Any, Dict, List

from iat.action_engine.recovery_planner import plan_recovery_actions
from iat.action_engine.retry_engine import evaluate_retry_policy
from iat.action_engine.runtime_policy_engine import evaluate_runtime_policy
from iat.api.db import (
    list_action_queue_db,
    move_action_to_dead_letter_queue_db,
    reactivate_action_queue_item_db,
)


def execute_recovery_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    plan = plan or {}
    decision = plan.get("decision")
    action_id = plan.get("action_id")

    if decision == "no_recovery_needed":
        return {
            "status": "skipped",
            "reason": "recovery_not_needed",
            "action_id": action_id,
            "plan": plan,
            "recovered": False,
        }

    if decision != "requeue_action":
        return {
            "status": "unsupported_recovery_decision",
            "reason": "recovery_decision_not_supported_yet",
            "action_id": action_id,
            "plan": plan,
            "recovered": False,
        }

    queue = list_action_queue_db(limit=100)
    queue_item = next(
        (item for item in queue.get("actions", []) if item.get("action_id") == action_id),
        {},
    )
    action_context = queue_item.get("action_context") or {}
    retry_decision = evaluate_retry_policy(
        action_context,
        failure_result={"status": "claim_expired", "reason": "expired_claim_recovery"},
    )

    policy_decision = evaluate_runtime_policy(
        domain="recovery",
        context={
            "plan": plan,
            "retry_decision": retry_decision,
        },
    )

    if policy_decision.get("status") == "send_to_dlq":
        dlq = move_action_to_dead_letter_queue_db(
            action_context,
            failure_result={"status": "claim_expired", "reason": "expired_claim_recovery"},
            reason="max_retry_reached_during_recovery",
        )

        return {
            "status": "sent_to_dead_letter_queue",
            "reason": "max_retry_reached_during_recovery",
            "action_id": action_id,
            "plan": plan,
            "recovered": False,
            "retry_decision": retry_decision,
            "policy_decision": policy_decision,
            "dead_letter_queue": dlq,
        }

    if policy_decision.get("status") == "requeue_allowed":
        reactivation = reactivate_action_queue_item_db(
            action_id=action_id,
            reason="expired_claim_recovery_requeue_allowed",
        )

        return {
            "status": "recovery_executed",
            "reason": "action_reactivated_after_expired_claim",
            "action_id": action_id,
            "plan": plan,
            "recovered": bool(reactivation.get("reactivated")),
            "retry_decision": retry_decision,
            "policy_decision": policy_decision,
            "queue_reactivation": reactivation,
        }

    return {
        "status": "recovery_held",
        "reason": "policy_did_not_allow_requeue",
        "action_id": action_id,
        "plan": plan,
        "recovered": False,
        "retry_decision": retry_decision,
        "policy_decision": policy_decision,
    }


def execute_recovery_cycle(limit: int = 50) -> Dict[str, Any]:
    planning = plan_recovery_actions(limit=limit)
    plans: List[Dict[str, Any]] = planning.get("plans") or []

    results = [
        execute_recovery_plan(plan)
        for plan in plans
    ]

    return {
        "status": "recovery_execution_cycle_completed",
        "recovery_executor": "iat_action_recovery_executor_v1",
        "planning": planning,
        "executed_plans_count": len(results),
        "results": results,
        "queue": list_action_queue_db(limit=limit),
        "capabilities": {
            "execute_recovery_plans": True,
            "queue_reactivation": True,
            "retry_policy_enforced": True,
            "dead_letter_queue": True,
        },
    }


def inspect_recovery_executor(limit: int = 50) -> Dict[str, Any]:
    return {
        "status": "ok",
        "recovery_executor": "iat_action_recovery_executor_v1",
        "planning": plan_recovery_actions(limit=limit),
        "queue": list_action_queue_db(limit=limit),
        "capabilities": {
            "execute_recovery_plans": True,
            "queue_reactivation": True,
            "retry_policy_enforced": True,
            "dead_letter_queue": True,
        },
    }
