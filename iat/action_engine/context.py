import time
import uuid
from typing import Any, Dict, Optional


def now_ts() -> int:
    return int(time.time())


def build_action_context(
    action_type: str,
    action_scope: str,
    payload: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    requested_by: str = "iat_protocol",
    priority: str = "normal",
    timeout_seconds: int = 300,
    retry_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    action_id = str(uuid.uuid4())

    return {
        "action_id": action_id,
        "action_type": action_type,
        "action_scope": action_scope,
        "requested_by": requested_by,
        "priority": priority,
        "timeout_seconds": int(timeout_seconds or 300),
        "retry_policy": retry_policy or {
            "retry_count": 0,
            "max_retries": 3,
        },
        "payload": payload or {},
        "metadata": metadata or {},
        "created_at": now_ts(),
        "context_version": "action_context_v1",
    }


def normalize_action_context(action_context: Dict[str, Any]) -> Dict[str, Any]:
    action_context = action_context or {}

    return {
        "action_id": action_context.get("action_id") or str(uuid.uuid4()),
        "action_type": action_context.get("action_type"),
        "action_scope": action_context.get("action_scope"),
        "requested_by": action_context.get("requested_by") or "iat_protocol",
        "priority": action_context.get("priority") or "normal",
        "timeout_seconds": int(action_context.get("timeout_seconds") or 300),
        "retry_policy": action_context.get("retry_policy") or {
            "retry_count": 0,
            "max_retries": 3,
        },
        "payload": action_context.get("payload") or {},
        "metadata": action_context.get("metadata") or {},
        "created_at": int(action_context.get("created_at") or now_ts()),
        "context_version": action_context.get("context_version") or "action_context_v1",
    }


def validate_action_context(action_context: Dict[str, Any]) -> Dict[str, Any]:
    ctx = normalize_action_context(action_context)

    missing = []
    for field in ["action_id", "action_type", "action_scope", "requested_by"]:
        if not ctx.get(field):
            missing.append(field)

    if missing:
        return {
            "valid": False,
            "reason": "missing_required_context_fields",
            "missing_fields": missing,
            "context": ctx,
        }

    return {
        "valid": True,
        "reason": "action_context_valid",
        "context": ctx,
    }
