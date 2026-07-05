from typing import Any, Dict
from iat.action_engine.runtime_event_registry import get_runtime_event_definition
from iat.api.db import set_action_runtime_state_db, get_action_runtime_state_db, update_action_worker_status_db, get_action_circuit_breaker_db, upsert_action_circuit_breaker_db




def metrics_hook(event: Dict[str, Any]) -> Dict[str, Any]:
    event_type = event.get("event_type")

    definition = get_runtime_event_definition(event_type)

    return {
        "status": "processed",
        "hook": "metrics",
        "event_type": event_type,
        "category": definition.get("category"),
        "severity": definition.get("severity"),
        "consumers": definition.get("consumers", []),
    }





def governance_hook(event: Dict[str, Any]) -> Dict[str, Any]:
    definition = get_runtime_event_definition(event.get("event_type"))

    if "governance" not in definition.get("consumers", []):
        return {
            "status":"ignored",
            "hook":"governance",
            "reason":"event_not_routed_to_governance",
        }

    runtime_state = get_action_runtime_state_db("runtime.risk.score")

    risk_score = 0
    state = runtime_state.get("state")

    if state:
        try:
            risk_score = int(state.get("state_value") or 0)
        except Exception:
            pass

    if risk_score >= 100:
        decision = "disable_worker"
    elif risk_score >= 50:
        decision = "limit_worker"
    elif risk_score >= 20:
        decision = "monitor"
    else:
        decision = "none"

    governance_action = None

    worker_id = (
        event.get("worker_id")
        or event.get("payload", {}).get("worker_id")
    )

    if decision == "disable_worker" and worker_id:
        governance_action = update_action_worker_status_db(
            worker_id=worker_id,
            worker_status="disabled",
        )

    return {
        "status":"processed",
        "hook":"governance",
        "runtime_risk_score":risk_score,
        "decision":decision,
        "governance_action":governance_action,
    }


def risk_hook(event: Dict[str, Any]) -> Dict[str, Any]:
    definition = get_runtime_event_definition(event.get("event_type"))

    if "risk" not in definition.get("consumers", []):
        return {
            "status": "ignored",
            "hook": "risk",
            "reason": "event_not_routed_to_risk",
        }

    severity = definition.get("severity", "info")

    risk_delta = {
        "info": 0,
        "warning": 10,
        "critical": 25,
    }.get(severity, 0)

    current = get_action_runtime_state_db("runtime.risk.score")

    score = 0

    state = current.get("state")
    if state:
        try:
            score = int(state.get("state_value") or 0)
        except Exception:
            score = 0

    score += risk_delta

    set_action_runtime_state_db(
        "runtime.risk.score",
        score,
    )

    return {
        "status": "processed",
        "hook": "risk",
        "severity": severity,
        "risk_delta": risk_delta,
        "runtime_risk_score": score,
    }


def autoscaling_hook(event: Dict[str, Any]) -> Dict[str, Any]:
    definition = get_runtime_event_definition(event.get("event_type"))

    if event.get("event_type") != "WorkerBusy":
        return {
            "status": "ignored",
            "hook": "autoscaling",
            "reason": "event_not_relevant_for_autoscaling",
        }

    return {
        "status": "processed",
        "hook": "autoscaling",
        "decision": "observe_runtime_load",
        "recommended_workers": 0,
    }




def circuit_breaker_hook(event: Dict[str, Any]) -> Dict[str, Any]:

    service = (
        event.get("service_name")
        or event.get("payload", {}).get("service_name")
        or "default"
    )

    breaker = get_action_circuit_breaker_db(service).get("breaker")

    if breaker:
        failure_count = int(breaker.get("failure_count") or 0)
        success_count = int(breaker.get("success_count") or 0)
    else:
        failure_count = 0
        success_count = 0

    if event.get("event_type") == "WorkerExecutionFailed":
        failure_count += 1

    if event.get("event_type") == "WorkerExecutionCompleted":
        success_count += 1
        failure_count = max(0, failure_count - 1)

    state = "CLOSED"

    if failure_count >= 5:
        state = "OPEN"

    import time

    upsert_action_circuit_breaker_db(
        service_name=service,
        state=state,
        failure_count=failure_count,
        success_count=success_count,
        opened_at=int(time.time()) if state == "OPEN" else None,
        last_failure_at=int(time.time()),
    )

    return {
        "status":"processed",
        "hook":"circuit_breaker",
        "service":service,
        "failure_count":failure_count,
        "state":state,
    }


def dispatch_runtime_hooks(event: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": "ok",
        "runtime_hooks": "iat_runtime_hooks_v1",
        "hooks": {
            "metrics": metrics_hook(event),
            "governance": governance_hook(event),
            "risk": risk_hook(event),
            "autoscaling": autoscaling_hook(event),
            "circuit_breaker": circuit_breaker_hook(event),
        },
    }
