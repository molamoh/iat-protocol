import time
from typing import Any, Dict, Optional


def now_ts() -> int:
    return int(time.time())


def build_action_request(
    action_type: str,
    action_scope: str,
    payload: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "action_type": action_type,
        "action_scope": action_scope,
        "payload": payload or {},
        "metadata": metadata or {},
        "created_at": now_ts(),
    }


def build_action_result(
    status: str,
    action_type: str,
    action_scope: str,
    result: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "status": status,
        "action_type": action_type,
        "action_scope": action_scope,
        "result": result or {},
        "reason": reason,
        "error": error,
        "executed_at": now_ts(),
    }
