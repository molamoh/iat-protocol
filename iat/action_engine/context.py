import time
import uuid
from typing import Any, Dict, List, Optional


ACTION_CONTEXT_VERSION = "action_context_v2"
ORCHESTRATION_VERSION = "iat_orchestration_context_v1"


def now_ts() -> int:
    return int(time.time())


def _normalize_string_list(value: Any) -> List[str]:
    if value is None:
        return []

    if isinstance(value, str):
        value = [value]

    if not isinstance(value, (list, tuple, set)):
        return []

    normalized = []
    seen = set()

    for item in value:
        item = str(item or "").strip()

        if not item or item in seen:
            continue

        normalized.append(item)
        seen.add(item)

    return normalized


def _normalize_optional_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _normalize_optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_action_context(
    action_type: str,
    action_scope: str,
    payload: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    requested_by: str = "iat_protocol",
    priority: str = "normal",
    timeout_seconds: int = 300,
    retry_policy: Optional[Dict[str, Any]] = None,
    orchestration: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    action_id = str(uuid.uuid4())
    orchestration = orchestration or {}

    return normalize_action_context({
        "action_id": action_id,
        "action_type": action_type,
        "action_scope": action_scope,
        "requested_by": requested_by,
        "priority": priority,
        "timeout_seconds": timeout_seconds,
        "retry_policy": retry_policy,
        "payload": payload or {},
        "metadata": metadata or {},
        "created_at": now_ts(),
        "context_version": ACTION_CONTEXT_VERSION,
        "orchestration": orchestration,
    })


def normalize_action_context(
    action_context: Dict[str, Any],
) -> Dict[str, Any]:
    action_context = action_context or {}

    orchestration = _normalize_optional_dict(
        action_context.get("orchestration")
    )

    action_id = (
        str(action_context.get("action_id") or uuid.uuid4()).strip()
    )

    depends_on = _normalize_string_list(
        orchestration.get(
            "depends_on",
            action_context.get("depends_on"),
        )
    )

    required_capabilities = _normalize_string_list(
        orchestration.get(
            "required_capabilities",
            action_context.get("required_capabilities"),
        )
    )

    normalized_orchestration = {
        "orchestration_version": (
            orchestration.get("orchestration_version")
            or ORCHESTRATION_VERSION
        ),
        "plan_id": (
            orchestration.get("plan_id")
            or action_context.get("plan_id")
        ),
        "parent_action_id": (
            orchestration.get("parent_action_id")
            or action_context.get("parent_action_id")
        ),
        "depends_on": depends_on,
        "execution_group": (
            orchestration.get("execution_group")
            or action_context.get("execution_group")
        ),
        "parallel_group": (
            orchestration.get("parallel_group")
            or action_context.get("parallel_group")
        ),
        "step_position": _normalize_optional_int(
            orchestration.get(
                "step_position",
                action_context.get("step_position"),
            )
        ),
        "rollback_action": _normalize_optional_dict(
            orchestration.get(
                "rollback_action",
                action_context.get("rollback_action"),
            )
        ),
        "compensation_action": _normalize_optional_dict(
            orchestration.get(
                "compensation_action",
                action_context.get("compensation_action"),
            )
        ),
        "expected_inputs": _normalize_optional_dict(
            orchestration.get(
                "expected_inputs",
                action_context.get("expected_inputs"),
            )
        ),
        "produced_outputs": _normalize_optional_dict(
            orchestration.get(
                "produced_outputs",
                action_context.get("produced_outputs"),
            )
        ),
        "execution_constraints": _normalize_optional_dict(
            orchestration.get(
                "execution_constraints",
                action_context.get("execution_constraints"),
            )
        ),
        "deadline": _normalize_optional_int(
            orchestration.get(
                "deadline",
                action_context.get("deadline"),
            )
        ),
        "cost_budget": _normalize_optional_float(
            orchestration.get(
                "cost_budget",
                action_context.get("cost_budget"),
            )
        ),
        "required_capabilities": required_capabilities,
    }

    return {
        "action_id": action_id,
        "action_type": action_context.get("action_type"),
        "action_scope": action_context.get("action_scope"),
        "requested_by": (
            action_context.get("requested_by")
            or "iat_protocol"
        ),
        "priority": action_context.get("priority") or "normal",
        "timeout_seconds": int(
            action_context.get("timeout_seconds") or 300
        ),
        "retry_policy": (
            action_context.get("retry_policy")
            if isinstance(action_context.get("retry_policy"), dict)
            else {
                "retry_count": 0,
                "max_retries": 3,
            }
        ),
        "payload": _normalize_optional_dict(
            action_context.get("payload")
        ),
        "metadata": _normalize_optional_dict(
            action_context.get("metadata")
        ),
        "orchestration": normalized_orchestration,
        "created_at": int(
            action_context.get("created_at") or now_ts()
        ),
        "context_version": (
            action_context.get("context_version")
            or ACTION_CONTEXT_VERSION
        ),
    }


def validate_action_context(
    action_context: Dict[str, Any],
) -> Dict[str, Any]:
    ctx = normalize_action_context(action_context)

    missing = []

    for field in (
        "action_id",
        "action_type",
        "action_scope",
        "requested_by",
    ):
        if not ctx.get(field):
            missing.append(field)

    if missing:
        return {
            "valid": False,
            "reason": "missing_required_context_fields",
            "missing_fields": missing,
            "context": ctx,
        }

    orchestration = ctx.get("orchestration") or {}
    action_id = ctx.get("action_id")
    dependencies = orchestration.get("depends_on") or []

    if action_id in dependencies:
        return {
            "valid": False,
            "reason": "action_cannot_depend_on_itself",
            "context": ctx,
        }

    parent_action_id = orchestration.get("parent_action_id")

    if parent_action_id and parent_action_id == action_id:
        return {
            "valid": False,
            "reason": "action_cannot_be_its_own_parent",
            "context": ctx,
        }

    deadline = orchestration.get("deadline")

    if deadline is not None and deadline <= 0:
        return {
            "valid": False,
            "reason": "invalid_orchestration_deadline",
            "context": ctx,
        }

    cost_budget = orchestration.get("cost_budget")

    if cost_budget is not None and cost_budget < 0:
        return {
            "valid": False,
            "reason": "invalid_orchestration_cost_budget",
            "context": ctx,
        }

    return {
        "valid": True,
        "reason": "action_context_valid",
        "context": ctx,
        "orchestration_enabled": bool(
            orchestration.get("plan_id")
            or orchestration.get("parent_action_id")
            or dependencies
            or orchestration.get("execution_group")
            or orchestration.get("parallel_group")
        ),
    }
