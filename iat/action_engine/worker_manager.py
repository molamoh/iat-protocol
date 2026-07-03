from typing import Any, Dict, Optional

from iat.api.db import (
    heartbeat_action_worker_db,
    list_action_workers_db,
    mark_action_worker_result_db,
    claim_action_db,
    release_action_claim_db,
    expire_stale_action_claims_db,
)
from iat.action_engine.execution_core import process_next_core_action
from iat.action_engine.runtime_policy_engine import evaluate_runtime_policy



def select_available_worker(
    required_capabilities=None,
) -> Dict[str, Any]:

    workers_result = list_action_workers_db(limit=100)
    workers = workers_result.get("workers") or []

    decision = evaluate_runtime_policy(
        domain="worker",
        context={
            "workers": workers,
            "required_capabilities": required_capabilities,
        },
    )

    if decision.get("status") != "worker_selected":
        return {
            "status": "no_available_worker",
            "reason": decision.get("reason"),
            "worker": None,
            "workers_count": len(workers),
            "policy_decision": decision,
        }

    return {
        "status": "worker_selected",
        "reason": "runtime_policy_selected_worker",
        "worker": decision.get("selected_worker"),
        "workers_count": len(workers),
        "policy_decision": decision,
    }


def process_next_action_with_worker(worker_id: Optional[str] = None) -> Dict[str, Any]:
    selected = None

    if worker_id:
        workers_result = list_action_workers_db(limit=100)
        workers = workers_result.get("workers") or []
        selected = next(
            (worker for worker in workers if worker.get("worker_id") == worker_id),
            None,
        )

        if not selected:
            return {
                "status": "worker_not_found",
                "reason": "requested_worker_not_registered",
                "worker_id": worker_id,
                "executed": False,
            }

        if str(selected.get("worker_status") or "").lower() != "idle":
            return {
                "status": "worker_not_available",
                "reason": "requested_worker_not_idle",
                "worker_id": worker_id,
                "worker_status": selected.get("worker_status"),
                "executed": False,
            }
    else:
        selection = select_available_worker()
        if selection.get("status") != "worker_selected":
            return {
                "status": "worker_unavailable",
                "reason": selection.get("reason"),
                "selection": selection,
                "executed": False,
            }
        selected = selection.get("worker")

    worker_id = selected.get("worker_id")

    expire_stale_action_claims_db()

    heartbeat_action_worker_db(
        worker_id=worker_id,
        worker_status="busy",
        current_action_id=None,
    )

    result = process_next_core_action()

    action_id = (
        result.get("action_context", {}).get("action_id")
        or result.get("dequeue", {}).get("item", {}).get("action_id")
    )

    claim = None
    claim_release = None

    if action_id:
        claim = claim_action_db(
            action_id=action_id,
            worker_id=worker_id,
            lease_seconds=60,
        )

        if not claim.get("claimed"):
            mark_action_worker_result_db(
                worker_id=worker_id,
                success=False,
                current_action_id=action_id,
            )

            return {
                "status": "action_claim_failed",
                "reason": claim.get("reason"),
                "worker_id": worker_id,
                "action_id": action_id,
                "claim": claim,
                "execution_result": result,
                "executed": False,
            }

    success = bool(result.get("executed"))

    if claim and claim.get("claim_id"):
        claim_release = release_action_claim_db(
            claim_id=claim.get("claim_id"),
            worker_id=worker_id,
            release_reason="worker_execution_completed" if success else "worker_execution_failed",
        )

    worker_result = mark_action_worker_result_db(
        worker_id=worker_id,
        success=success,
        current_action_id=action_id,
    )

    return {
        "status": "worker_processed_action",
        "reason": "worker_manager_processed_next_action",
        "worker_id": worker_id,
        "action_id": action_id,
        "executed": success,
        "claim": claim,
        "claim_release": claim_release,
        "execution_result": result,
        "worker_result": worker_result,
    }


def inspect_worker_manager() -> Dict[str, Any]:
    workers = list_action_workers_db(limit=100)

    idle_count = 0
    busy_count = 0

    for worker in workers.get("workers") or []:
        status = str(worker.get("worker_status") or "").lower()
        if status == "idle":
            idle_count += 1
        elif status == "busy":
            busy_count += 1

    return {
        "status": "ok",
        "worker_manager": "iat_action_worker_manager_v1",
        "workers": workers,
        "idle_workers": idle_count,
        "busy_workers": busy_count,
    }
