from typing import Any, Dict, Optional

from iat.action_engine.heartbeat_engine import run_runtime_heartbeat_cycle, inspect_runtime_health
from iat.api.db import expire_stale_action_claims_db
from iat.action_engine.claim_recovery import run_claim_recovery_cycle, inspect_claim_recovery
from iat.action_engine.recovery_planner import inspect_recovery_planner, plan_recovery_actions


def run_runtime_supervisor_cycle(
    worker_id: Optional[str] = None,
    worker_status: str = "idle",
    current_action_id: Optional[str] = None,
    claim_id: Optional[str] = None,
) -> Dict[str, Any]:
    heartbeat = run_runtime_heartbeat_cycle(
        worker_id=worker_id,
        worker_status=worker_status,
        current_action_id=current_action_id,
        claim_id=claim_id,
        extend_seconds=60,
    )

    expired_claims = expire_stale_action_claims_db()
    claim_recovery = run_claim_recovery_cycle(limit=50)
    recovery_plan = plan_recovery_actions(limit=50)
    health = inspect_runtime_health(limit=50)

    return {
        "status": "runtime_supervisor_cycle_completed",
        "runtime_supervisor": "iat_action_runtime_supervisor_v1",
        "heartbeat": heartbeat,
        "expired_claims": expired_claims,
        "claim_recovery": claim_recovery,
        "recovery_plan": recovery_plan,
        "health": health,
    }


def inspect_runtime_supervisor() -> Dict[str, Any]:
    return {
        "status": "ok",
        "runtime_supervisor": "iat_action_runtime_supervisor_v1",
        "health": inspect_runtime_health(limit=50),
        "claim_recovery": inspect_claim_recovery(limit=50),
        "recovery_planner": inspect_recovery_planner(limit=50),
        "capabilities": {
            "heartbeat_cycle": True,
            "claim_expiration": True,
            "claim_recovery": True,
            "recovery_planner": True,
            "retry_engine": False,
            "distributed_worker_pool": False,
        },
    }
