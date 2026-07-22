"""
IAT Protocol — Runtime Decision Dispatcher.

Single entry point for distributing structured protocol decisions toward
existing intelligence engines.

The dispatcher does not authorize, reject or modify decisions.
It only observes and forwards them on a best-effort basis.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from iat.intelligence.decision_adapter import integrate_protocol_decision


DISPATCHER_VERSION = "iat_runtime_decision_dispatcher_v1"


def dispatch_protocol_decision(
    decision: Any,
    *,
    principal_id: Optional[str] = None,
    principal_type: str = "protocol_identity",
    resource: Optional[str] = None,
    source_type: str = "decision_engine",
    source_id: Optional[str] = None,
    action_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    persist_allowed_memory: bool = False,
) -> Dict[str, Any]:
    """
    Dispatch a structured decision to the protocol intelligence layer.

    Guarantees:
    - never changes the original decision;
    - never raises because an intelligence engine failed;
    - centralizes future intelligence integrations;
    - avoids direct coupling between security and persistence engines.
    """

    dispatcher_context = {
        **(context or {}),
        "dispatcher_version": DISPATCHER_VERSION,
    }

    try:
        integration = integrate_protocol_decision(
            decision=decision,
            principal_id=principal_id,
            principal_type=principal_type,
            resource=resource,
            source_type=source_type,
            source_id=source_id,
            action_id=action_id,
            context=dispatcher_context,
            persist_allowed_memory=persist_allowed_memory,
        )

        return {
            "status": "decision_dispatched",
            "dispatcher_version": DISPATCHER_VERSION,
            "integration": integration,
        }

    except Exception as exc:
        return {
            "status": "decision_dispatch_failed",
            "dispatcher_version": DISPATCHER_VERSION,
            "integration": None,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }
