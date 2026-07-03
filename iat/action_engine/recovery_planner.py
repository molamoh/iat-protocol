from typing import Any, Dict

from iat.api.db import list_action_claims_db, list_action_queue_db, list_action_workers_db


def inspect_recovery_planner(limit: int = 50) -> Dict[str, Any]:
    return {
        "status": "ok",
        "recovery_planner": "iat_action_recovery_planner_v1",
        "claims": list_action_claims_db(limit=limit),
        "queue": list_action_queue_db(limit=limit),
        "workers": list_action_workers_db(limit=limit),
        "capabilities": {
            "detect_expired_claims": True,
            "plan_requeue": True,
            "execute_requeue": False,
            "escalate_governance": False,
        },
    }


def plan_recovery_actions(limit: int = 50) -> Dict[str, Any]:
    claims = list_action_claims_db(limit=limit)
    queue = list_action_queue_db(limit=limit)
    workers = list_action_workers_db(limit=limit)

    queue_by_action_id = {
        item.get("action_id"): item
        for item in queue.get("actions", [])
    }

    plans = []

    for claim in claims.get("claims", []):
        claim_status = str(claim.get("claim_status") or "").lower()
        action_id = claim.get("action_id")
        queue_item = queue_by_action_id.get(action_id) or {}
        queue_status = str(queue_item.get("queue_status") or "").lower()

        if claim_status == "expired":
            if queue_status in ("completed", "failed"):
                decision = "no_recovery_needed"
                reason = "queue_item_already_terminal"
            else:
                decision = "requeue_action"
                reason = "expired_claim_action_should_be_requeued"

            plans.append({
                "action_id": action_id,
                "claim_id": claim.get("claim_id"),
                "worker_id": claim.get("worker_id"),
                "claim_status": claim_status,
                "queue_status": queue_status,
                "decision": decision,
                "reason": reason,
            })

    return {
        "status": "planned",
        "recovery_planner": "iat_action_recovery_planner_v1",
        "plans_count": len(plans),
        "plans": plans,
        "workers_count": workers.get("count", 0),
    }
