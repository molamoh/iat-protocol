from typing import Any, Dict

from iat.api.db import (
    expire_stale_action_claims_db,
    list_action_claims_db,
    list_action_queue_db,
)


def inspect_claim_recovery(limit: int = 50) -> Dict[str, Any]:
    return {
        "status": "ok",
        "claim_recovery": "iat_action_claim_recovery_v1",
        "expired_or_released_claims": list_action_claims_db(limit=limit),
        "queue": list_action_queue_db(limit=limit),
        "capabilities": {
            "detect_expired_claims": True,
            "recover_expired_claims": False,
            "requeue_actions": False,
        },
    }


def run_claim_recovery_cycle(limit: int = 50) -> Dict[str, Any]:
    expired = expire_stale_action_claims_db()
    claims = list_action_claims_db(limit=limit)

    expired_claims = [
        claim for claim in claims.get("claims", [])
        if str(claim.get("claim_status") or "").lower() == "expired"
    ]

    return {
        "status": "claim_recovery_cycle_completed",
        "claim_recovery": "iat_action_claim_recovery_v1",
        "expired": expired,
        "expired_claims_count": len(expired_claims),
        "expired_claims": expired_claims,
        "capabilities": {
            "detect_expired_claims": True,
            "recover_expired_claims": False,
            "requeue_actions": False,
        },
    }
