from typing import Any, Dict, Optional

from iat.api.db import (
    heartbeat_action_worker_db,
    heartbeat_action_claim_db,
    expire_stale_action_claims_db,
    list_action_workers_db,
    list_action_claims_db,
)


def heartbeat_worker_runtime(
    worker_id: str,
    worker_status: str = "idle",
    current_action_id: Optional[str] = None,
) -> Dict[str, Any]:
    return heartbeat_action_worker_db(
        worker_id=worker_id,
        worker_status=worker_status,
        current_action_id=current_action_id,
    )


def heartbeat_claim_runtime(
    claim_id: str,
    worker_id: Optional[str] = None,
    extend_seconds: int = 60,
) -> Dict[str, Any]:
    return heartbeat_action_claim_db(
        claim_id=claim_id,
        worker_id=worker_id,
        extend_seconds=extend_seconds,
    )


def run_runtime_heartbeat_cycle(
    worker_id: Optional[str] = None,
    worker_status: str = "idle",
    current_action_id: Optional[str] = None,
    claim_id: Optional[str] = None,
    extend_seconds: int = 60,
) -> Dict[str, Any]:
    worker_heartbeat = None
    claim_heartbeat = None

    if worker_id:
        worker_heartbeat = heartbeat_worker_runtime(
            worker_id=worker_id,
            worker_status=worker_status,
            current_action_id=current_action_id,
        )

    if claim_id:
        claim_heartbeat = heartbeat_claim_runtime(
            claim_id=claim_id,
            worker_id=worker_id,
            extend_seconds=extend_seconds,
        )

    expired_claims = expire_stale_action_claims_db()

    return {
        "status": "heartbeat_cycle_completed",
        "reason": "runtime_heartbeat_cycle_completed",
        "worker_heartbeat": worker_heartbeat,
        "claim_heartbeat": claim_heartbeat,
        "expired_claims": expired_claims,
    }


def inspect_runtime_health(limit: int = 50) -> Dict[str, Any]:
    workers = list_action_workers_db(limit=limit)
    claims = list_action_claims_db(limit=limit)

    return {
        "status": "ok",
        "runtime_health_engine": "iat_action_heartbeat_engine_v1",
        "workers": workers,
        "claims": claims,
    }
