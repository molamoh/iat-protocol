from typing import Any, Dict, Optional

from iat.api.db import record_action_runtime_event_db, list_action_runtime_events_db
from iat.action_engine.runtime_hooks import dispatch_runtime_hooks


def publish_runtime_event(
    event_type: str,
    severity: str = "info",
    payload: Optional[Dict[str, Any]] = None,
    action_id: Optional[str] = None,
    worker_id: Optional[str] = None,
    claim_id: Optional[str] = None,
) -> Dict[str, Any]:
    return record_action_runtime_event_db(
        event_type=event_type,
        action_id=action_id,
        worker_id=worker_id,
        claim_id=claim_id,
        severity=severity,
        event_payload=payload or {},
    )


def publish_action_event(
    event_type: str,
    action_id: str,
    payload: Optional[Dict[str, Any]] = None,
    severity: str = "info",
) -> Dict[str, Any]:
    return publish_runtime_event(
        event_type=event_type,
        action_id=action_id,
        severity=severity,
        payload=payload or {},
    )


def publish_worker_event(
    event_type: str,
    worker_id: str,
    payload: Optional[Dict[str, Any]] = None,
    severity: str = "info",
) -> Dict[str, Any]:
    return publish_runtime_event(
        event_type=event_type,
        worker_id=worker_id,
        severity=severity,
        payload=payload or {},
    )


def publish_claim_event(
    event_type: str,
    claim_id: str,
    action_id: Optional[str] = None,
    worker_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    severity: str = "info",
) -> Dict[str, Any]:
    return publish_runtime_event(
        event_type=event_type,
        claim_id=claim_id,
        action_id=action_id,
        worker_id=worker_id,
        severity=severity,
        payload=payload or {},
    )




def dispatch_runtime_event(
    event_type: str,
    severity: str = "info",
    payload: Optional[Dict[str, Any]] = None,
    action_id: Optional[str] = None,
    worker_id: Optional[str] = None,
    claim_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Public Runtime Event API.

    Today:
        dispatch -> publish -> DB

    Future:
        dispatch -> publish
                 -> governance hooks
                 -> risk hooks
                 -> autoscaling hooks
                 -> metrics hooks
                 -> AI hooks
    """

    event = publish_runtime_event(
        event_type=event_type,
        severity=severity,
        payload=payload,
        action_id=action_id,
        worker_id=worker_id,
        claim_id=claim_id,
    )

    dispatch_runtime_hooks({
        "event_type": event_type,
        "severity": severity,
        "payload": payload or {},
        "action_id": action_id,
        "worker_id": worker_id,
        "claim_id": claim_id,
    })

    return event



def inspect_runtime_event_bus(limit: int = 20) -> Dict[str, Any]:
    return {
        "status": "ok",
        "runtime_event_bus": "iat_action_runtime_event_bus_v1",
        "recent_events": list_action_runtime_events_db(limit=limit),
        "capabilities": {
            "publish_runtime_event": True,
            "publish_action_event": True,
            "publish_worker_event": True,
            "publish_claim_event": True,
            "dedicated_event_table": False,
            "uses_action_runtime_events": True,
        },
    }
