"""
IAT Protocol — Decision Intelligence Adapter

Transforms structured protocol decisions into existing runtime and long-term
intelligence signals.

Architectural rules:
- no new database table;
- no duplicated memory engine;
- no duplicated event engine;
- telemetry failures must never alter the original authorization decision;
- long-term memory is selective to preserve scalability.
"""

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Optional


def _decision_to_dict(decision: Any) -> Dict[str, Any]:
    if is_dataclass(decision):
        payload = asdict(decision)
    elif isinstance(decision, dict):
        payload = dict(decision)
    else:
        payload = {
            "allowed": bool(getattr(decision, "allowed", False)),
            "authority": getattr(decision, "authority", None),
            "reason": getattr(decision, "reason", None),
            "policy_version": getattr(decision, "policy_version", None),
            "fail_closed": bool(getattr(decision, "fail_closed", False)),
        }

    return {
        "allowed": bool(payload.get("allowed", False)),
        "authority": str(payload.get("authority") or "unknown"),
        "reason": str(payload.get("reason") or "unspecified"),
        "policy_version": str(payload.get("policy_version") or "unknown"),
        "fail_closed": bool(payload.get("fail_closed", False)),
    }


def _decision_severity(decision: Dict[str, Any]) -> str:
    if decision["fail_closed"]:
        return "critical"

    if not decision["allowed"]:
        return "warning"

    return "info"


def _decision_event_type(decision: Dict[str, Any]) -> str:
    authority = decision["authority"].strip().lower() or "unknown"
    authority_name = "".join(
        part.capitalize()
        for part in authority.replace("-", "_").split("_")
        if part
    ) or "Unknown"

    outcome = "Allowed" if decision["allowed"] else "Denied"
    return f"{authority_name}Authority{outcome}"


def integrate_protocol_decision(
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
    Feed an existing structured decision into IAT intelligence engines.

    Strategy:
    - every decision -> runtime event;
    - denied/fail-closed decision -> runtime memory;
    - denied/fail-closed decision -> protocol long-term memory;
    - allowed decisions remain lightweight unless persist_allowed_memory=True.

    This function is best-effort by design. Intelligence recording failures
    are returned but never replace or modify the original decision.
    """

    normalized = _decision_to_dict(decision)
    severity = _decision_severity(normalized)
    event_type = _decision_event_type(normalized)

    payload = {
        **normalized,
        "principal_id": principal_id,
        "principal_type": principal_type,
        "resource": resource,
        "source_type": source_type,
        "source_id": source_id,
        "context": context or {},
    }

    result: Dict[str, Any] = {
        "status": "decision_integration_completed",
        "decision": normalized,
        "event_type": event_type,
        "severity": severity,
        "runtime_event": None,
        "runtime_memory": None,
        "protocol_memory": None,
        "errors": [],
    }

    try:
        from iat.action_engine.runtime_event_bus import publish_runtime_event

        result["runtime_event"] = publish_runtime_event(
            event_type=event_type,
            severity=severity,
            payload=payload,
            action_id=action_id,
        )
    except Exception as exc:
        result["errors"].append({
            "engine": "runtime_event_bus",
            "error": type(exc).__name__,
            "message": str(exc),
        })

    should_persist_memory = (
        not normalized["allowed"]
        or normalized["fail_closed"]
        or persist_allowed_memory
    )

    if should_persist_memory:
        try:
            from iat.api.db import record_action_runtime_memory_db

            result["runtime_memory"] = record_action_runtime_memory_db(
                memory_type="protocol_decision",
                subject_type=principal_type,
                subject_id=principal_id,
                event_type=event_type,
                severity=severity,
                summary=(
                    f"{normalized['authority']} authority decision: "
                    f"{normalized['reason']}"
                ),
                memory_payload=payload,
            )
        except Exception as exc:
            result["errors"].append({
                "engine": "runtime_memory",
                "error": type(exc).__name__,
                "message": str(exc),
            })

        try:
            from iat.api.db import store_protocol_memory_db

            confidence = 1.0 if normalized["fail_closed"] else 0.9
            importance = 1.0 if normalized["fail_closed"] else 0.8

            result["protocol_memory"] = store_protocol_memory_db(
                memory_type="authority_decision_memory",
                scope="security",
                subject_id=principal_id or normalized["authority"],
                source_type=source_type,
                source_id=source_id or principal_id or normalized["authority"],
                confidence=confidence,
                importance_score=importance,
                memory_payload=payload,
                tags=[
                    "security",
                    "authority",
                    normalized["authority"],
                    "allowed" if normalized["allowed"] else "denied",
                    normalized["reason"],
                ],
                metadata={
                    "policy_version": normalized["policy_version"],
                    "fail_closed": normalized["fail_closed"],
                    "protocol_core_sovereignty_reserved": True,
                    "decision_adapter": "iat_decision_intelligence_adapter_v1",
                },
                min_confidence=0.35,
            )
        except Exception as exc:
            result["errors"].append({
                "engine": "protocol_memory",
                "error": type(exc).__name__,
                "message": str(exc),
            })

    if result["errors"]:
        result["status"] = "decision_integration_partially_completed"

    return result
