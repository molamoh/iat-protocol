from typing import Any, Dict


DEFAULT_RUNTIME_POLICY = {
    "max_retries": 3,
    "claim_lease_seconds": 60,
    "worker_stale_seconds": 120,
    "send_to_dlq_on_max_retry": True,
    "allow_requeue_after_expired_claim": True,
    "allow_governance_escalation": False,

    "worker_score_capability_weight": 20,
    "worker_score_load_max": 30,
    "worker_score_failure_penalty": 10,
    "worker_score_reliability_max": 30,
    "worker_score_heartbeat_max": 20,
    "worker_score_heartbeat_divisor": 50000,
}


def get_runtime_policy() -> Dict[str, Any]:
    return {
        "status": "ok",
        "runtime_policy_engine": "iat_action_runtime_policy_engine_v1",
        "policy": dict(DEFAULT_RUNTIME_POLICY),
    }


def evaluate_recovery_policy(plan: Dict[str, Any], retry_decision: Dict[str, Any] = None) -> Dict[str, Any]:
    plan = plan or {}
    retry_decision = retry_decision or {}
    policy = dict(DEFAULT_RUNTIME_POLICY)

    decision = plan.get("decision")
    retry_status = retry_decision.get("status")

    if decision == "no_recovery_needed":
        return {
            "status": "no_action",
            "reason": "policy_no_recovery_needed",
            "policy": policy,
            "plan": plan,
            "retry_decision": retry_decision,
        }

    if decision != "requeue_action":
        return {
            "status": "unsupported",
            "reason": "policy_unsupported_recovery_decision",
            "policy": policy,
            "plan": plan,
            "retry_decision": retry_decision,
        }

    if retry_status == "max_retry_reached":
        if policy.get("send_to_dlq_on_max_retry"):
            return {
                "status": "send_to_dlq",
                "reason": "policy_max_retry_requires_dlq",
                "policy": policy,
                "plan": plan,
                "retry_decision": retry_decision,
            }

        return {
            "status": "escalate_governance",
            "reason": "policy_max_retry_requires_governance",
            "policy": policy,
            "plan": plan,
            "retry_decision": retry_decision,
        }

    if retry_status == "retry_allowed" and policy.get("allow_requeue_after_expired_claim"):
        return {
            "status": "requeue_allowed",
            "reason": "policy_allows_requeue_after_expired_claim",
            "policy": policy,
            "plan": plan,
            "retry_decision": retry_decision,
        }

    return {
        "status": "hold",
        "reason": "policy_holds_recovery_action",
        "policy": policy,
        "plan": plan,
        "retry_decision": retry_decision,
    }






def compute_worker_score(worker, required_capabilities=None):
    worker = worker or {}
    required_capabilities = required_capabilities or []

    capabilities = worker.get("capabilities") or {}
    policy = dict(DEFAULT_RUNTIME_POLICY)

    capability_score = 0
    missing_capabilities = []

    for capability in required_capabilities:
        if capabilities.get(capability):
            capability_score += int(policy.get("worker_score_capability_weight") or 20)
        else:
            missing_capabilities.append(capability)

    if missing_capabilities:
        return {
            "status": "ineligible",
            "score": 0,
            "reason": "worker_missing_required_capabilities",
            "missing_capabilities": missing_capabilities,
        }

    processed_actions = int(worker.get("processed_actions") or 0)
    failed_actions = int(worker.get("failed_actions") or 0)
    last_heartbeat = int(worker.get("last_heartbeat") or 0)

    load_score = max(
        0,
        int(policy.get("worker_score_load_max") or 30) - processed_actions,
    )

    reliability_score = max(
        0,
        int(policy.get("worker_score_reliability_max") or 30)
        - (failed_actions * int(policy.get("worker_score_failure_penalty") or 10)),
    )

    heartbeat_score = min(
        int(policy.get("worker_score_heartbeat_max") or 20),
        max(0, last_heartbeat % 1000000)
        / int(policy.get("worker_score_heartbeat_divisor") or 50000),
    )

    final_score = round(
        capability_score +
        load_score +
        reliability_score +
        heartbeat_score,
        6,
    )

    return {
        "status": "eligible",
        "score": final_score,
        "reason": "worker_score_computed",
        "components": {
            "capability_score": capability_score,
            "load_score": load_score,
            "reliability_score": reliability_score,
            "heartbeat_score": heartbeat_score,
        },
        "missing_capabilities": [],
    }



def evaluate_worker_policy(
    workers,
    required_capabilities=None,
):
    workers = workers or []
    required_capabilities = required_capabilities or []

    candidates = []

    for worker in workers:

        if str(worker.get("worker_status") or "").lower() != "idle":
            continue

        score = compute_worker_score(
            worker,
            required_capabilities=required_capabilities,
        )

        if score.get("status") != "eligible":
            continue

        candidates.append({
            "worker": worker,
            "score": score,
            "final_score": score.get("score", 0),
        })

    if not candidates:
        return {
            "status": "no_worker_available",
            "reason": "worker_policy_no_matching_worker",
            "selected_worker": None,
            "candidate_count": 0,
        }

    candidates.sort(
        key=lambda item: item.get("final_score", 0),
        reverse=True,
    )

    selected = candidates[0]

    return {
        "status": "worker_selected",
        "reason": "runtime_worker_policy_score_selected",
        "selected_worker": selected.get("worker"),
        "selected_score": selected.get("score"),
        "candidate_count": len(candidates),
        "candidates": [
            {
                "worker_id": item.get("worker", {}).get("worker_id"),
                "score": item.get("final_score"),
                "score_components": item.get("score", {}).get("components"),
            }
            for item in candidates
        ],
    }




def evaluate_runtime_policy(domain: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
    domain = str(domain or "").lower()
    context = context or {}

    if domain == "worker":
        return evaluate_worker_policy(
            context.get("workers") or [],
            required_capabilities=context.get("required_capabilities") or [],
        )

    if domain == "recovery":
        return evaluate_recovery_policy(
            context.get("plan") or {},
            retry_decision=context.get("retry_decision") or {},
        )

    return {
        "status": "unsupported_policy_domain",
        "reason": "runtime_policy_domain_not_supported",
        "domain": domain,
        "supported_domains": [
            "worker",
            "recovery",
        ],
    }



def inspect_runtime_policy_engine() -> Dict[str, Any]:
    return {
        "status": "ok",
        "runtime_policy_engine": "iat_action_runtime_policy_engine_v1",
        "policy": dict(DEFAULT_RUNTIME_POLICY),
        "capabilities": {
            "evaluate_recovery_policy": True,
            "dlq_policy": True,
            "requeue_policy": True,
            "governance_escalation_policy": False,
            "database_backed_policy": False,
        },
    }
