from typing import Any, Dict

from iat.api.db import (
    list_action_queue_db,
    list_action_claims_db,
    list_action_workers_db,
    list_action_execution_history_db,
    list_action_dead_letter_queue_db,
)


def compute_runtime_metrics(limit: int = 200) -> Dict[str, Any]:
    queue = list_action_queue_db(limit=limit)
    claims = list_action_claims_db(limit=limit)
    workers = list_action_workers_db(limit=limit)
    history = list_action_execution_history_db(limit=limit)
    dlq = list_action_dead_letter_queue_db(limit=limit)

    queue_items = queue.get("actions") or []
    claim_items = claims.get("claims") or []
    worker_items = workers.get("workers") or []
    history_items = history.get("history") or []
    dlq_items = dlq.get("items") or []

    queue_by_status = {}
    for item in queue_items:
        status = str(item.get("queue_status") or "unknown")
        queue_by_status[status] = queue_by_status.get(status, 0) + 1

    claims_by_status = {}
    for item in claim_items:
        status = str(item.get("claim_status") or "unknown")
        claims_by_status[status] = claims_by_status.get(status, 0) + 1

    workers_by_status = {}
    for item in worker_items:
        status = str(item.get("worker_status") or "unknown")
        workers_by_status[status] = workers_by_status.get(status, 0) + 1

    executions_by_status = {}
    success_count = 0
    failed_count = 0

    for item in history_items:
        status = str(item.get("execution_status") or "unknown")
        executions_by_status[status] = executions_by_status.get(status, 0) + 1

        if item.get("executed") in (1, True):
            success_count += 1
        else:
            failed_count += 1

    total_executions = len(history_items)
    success_rate = round((success_count / total_executions) * 100, 4) if total_executions else 0

    return {
        "status": "ok",
        "runtime_metrics": "iat_action_runtime_metrics_v1",
        "queue": {
            "total": len(queue_items),
            "by_status": queue_by_status,
        },
        "claims": {
            "total": len(claim_items),
            "by_status": claims_by_status,
        },
        "workers": {
            "total": len(worker_items),
            "by_status": workers_by_status,
        },
        "executions": {
            "total": total_executions,
            "success_count": success_count,
            "failed_count": failed_count,
            "success_rate_percent": success_rate,
            "by_status": executions_by_status,
        },
        "dead_letter_queue": {
            "total": len(dlq_items),
        },
    }


def inspect_runtime_metrics(limit: int = 200) -> Dict[str, Any]:
    return {
        "status": "ok",
        "runtime_metrics_engine": "iat_action_runtime_metrics_v1",
        "metrics": compute_runtime_metrics(limit=limit),
        "capabilities": {
            "queue_metrics": True,
            "claim_metrics": True,
            "worker_metrics": True,
            "execution_metrics": True,
            "dead_letter_queue_metrics": True,
            "time_series_metrics": False,
        },
    }
