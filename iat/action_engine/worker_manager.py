from typing import Any, Dict, Optional

from iat.api.db import (
    heartbeat_action_worker_db,
    list_action_workers_db,
    mark_action_worker_result_db,
)
from iat.action_engine.execution_core import process_next_core_action


def select_available_worker() -> Dict[str, Any]:
    workers_result = list_action_workers_db(limit=100)
    workers = workers_result.get("workers") or []

    idle_workers = [
        worker for worker in workers
        if str(worker.get("worker_status") or "").lower() == "idle"
    ]

    if not idle_workers:
        return {
            "status": "no_available_worker",
            "reason": "no_idle_action_worker_available",
            "worker": None,
            "workers_count": len(workers),
        }

    idle_workers.sort(
        key=lambda worker: (
            int(worker.get("processed_actions") or 0),
            int(worker.get("last_heartbeat") or 0),
        )
    )

    worker = idle_workers[0]

    return {
        "status": "worker_selected",
        "reason": "idle_action_worker_selected",
        "worker": worker,
        "workers_count": len(workers),
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

    success = bool(result.get("executed"))

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
