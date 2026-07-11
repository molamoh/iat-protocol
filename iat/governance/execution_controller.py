import hashlib
import json
import time
from typing import Any, Dict, List

from iat.governance.execution_planner import (
    build_foundation_execution_plan,
)


def _stable_hash(payload: Dict[str, Any]) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def simulate_foundation_execution_controller(
    decision_id: str,
    selected_seller_ids: List[str] | None = None,
) -> Dict[str, Any]:
    """
    Simulation-only Foundation Execution Controller.

    Performs:
    - pre-flight validation
    - explicit Seller selection validation
    - logical execution lock simulation
    - action simulation
    - outcome verification simulation
    - rollback readiness verification
    - audit report generation

    Does not modify protocol state.
    """
    selected_seller_ids = list(
        dict.fromkeys(selected_seller_ids or [])
    )

    execution_plan = build_foundation_execution_plan(
        decision_id=decision_id,
    )

    if execution_plan.get("status") != "execution_plan_built":
        return {
            "status": "blocked",
            "engine": "foundation_execution_controller_v1",
            "decision_id": decision_id,
            "message": "execution_plan_unavailable",
            "execution_plan": execution_plan,
            "execution_triggered": False,
        }

    preflight_checks = [
        {
            "check": "decision_approved",
            "passed": (
                execution_plan.get("decision_status")
                == "approved"
            ),
        },
        {
            "check": "execution_plan_ready",
            "passed": bool(
                execution_plan.get("execution_ready")
            ),
        },
        {
            "check": "no_plan_conflicts",
            "passed": not bool(
                execution_plan.get("conflicts")
            ),
        },
        {
            "check": "rollback_plan_present",
            "passed": bool(
                execution_plan.get("rollback_plan")
            ),
        },
        {
            "check": "execution_not_already_triggered",
            "passed": not bool(
                execution_plan.get("execution_triggered")
            ),
        },
    ]

    candidate_seller_ids = []

    for step in execution_plan.get("plan_steps", []):
        for candidate in step.get(
            "seller_execution_candidates",
            [],
        ):
            seller_id = candidate.get("seller_id")
            if (
                seller_id
                and seller_id not in candidate_seller_ids
            ):
                candidate_seller_ids.append(seller_id)

    unknown_selected_sellers = [
        seller_id
        for seller_id in selected_seller_ids
        if seller_id not in candidate_seller_ids
    ]

    seller_selection_required = any(
        step.get("foundation_selection_required")
        for step in execution_plan.get("plan_steps", [])
    )

    if seller_selection_required:
        selection_passed = (
            bool(selected_seller_ids)
            and not unknown_selected_sellers
        )
    else:
        selection_passed = True

    preflight_checks.append({
        "check": "foundation_seller_selection_valid",
        "passed": selection_passed,
        "candidate_seller_ids": candidate_seller_ids,
        "selected_seller_ids": selected_seller_ids,
        "unknown_selected_sellers": (
            unknown_selected_sellers
        ),
    })

    preflight_passed = all(
        check.get("passed")
        for check in preflight_checks
    )

    controller_input = {
        "decision_id": decision_id,
        "selected_seller_ids": selected_seller_ids,
        "execution_plan_engine": execution_plan.get(
            "engine"
        ),
        "target": execution_plan.get("target"),
        "plan_steps": execution_plan.get(
            "plan_steps",
            [],
        ),
    }

    execution_lock = {
        "lock_id": _stable_hash({
            **controller_input,
            "lock_scope": "simulation",
        }),
        "lock_scope": "simulation_only",
        "resource": f"foundation_decision:{decision_id}",
        "acquired": preflight_passed,
        "exclusive": True,
        "persistent": False,
        "created_at": int(time.time()),
    }

    simulated_steps = []

    if preflight_passed:
        for step in execution_plan.get("plan_steps", []):
            action = step.get("action")

            if action == "increase_capacity":
                selected_candidates = [
                    candidate
                    for candidate in step.get(
                        "seller_execution_candidates",
                        [],
                    )
                    if candidate.get("seller_id")
                    in selected_seller_ids
                ]

                for candidate in selected_candidates:
                    preview = (
                        candidate.get("capacity_preview")
                        or {}
                    )

                    simulated_steps.append({
                        "position": step.get("position"),
                        "action": action,
                        "seller_id": candidate.get(
                            "seller_id"
                        ),
                        "status": "simulation_completed",
                        "would_call": (
                            "recompute_seller_dynamic_agent_capacity_db"
                        ),
                        "old_capacity": preview.get(
                            "old_max_agents_allowed"
                        ),
                        "new_capacity": preview.get(
                            "new_max_agents_allowed"
                        ),
                        "capacity_direction": preview.get(
                            "capacity_direction"
                        ),
                        "decision_reason": preview.get(
                            "decision_reason"
                        ),
                        "state_modified": False,
                    })

            elif action == "factory_request":
                simulated_steps.append({
                    "position": step.get("position"),
                    "action": action,
                    "target": step.get("target"),
                    "status": "simulation_blocked",
                    "reason": (
                        "factory_payload_and_seller_selection_required"
                    ),
                    "state_modified": False,
                })

            elif action == "new_foundation_capability":
                simulated_steps.append({
                    "position": step.get("position"),
                    "action": action,
                    "target": step.get("target"),
                    "status": "simulation_blocked",
                    "reason": (
                        "foundation_capability_governance_required"
                    ),
                    "state_modified": False,
                })

            else:
                simulated_steps.append({
                    "position": step.get("position"),
                    "action": action,
                    "status": "unsupported_action",
                    "state_modified": False,
                })

    verification_checks = [
        {
            "check": "no_protocol_state_modified",
            "passed": all(
                not step.get("state_modified")
                for step in simulated_steps
            ),
        },
        {
            "check": "simulation_lock_non_persistent",
            "passed": not execution_lock.get("persistent"),
        },
        {
            "check": "rollback_plan_available",
            "passed": bool(
                execution_plan.get("rollback_plan")
            ),
        },
        {
            "check": "selected_sellers_are_candidates",
            "passed": not unknown_selected_sellers,
        },
    ]

    verification_passed = (
        bool(simulated_steps)
        and all(
            check.get("passed")
            for check in verification_checks
        )
    )

    controller_status = (
        "simulation_completed"
        if preflight_passed and verification_passed
        else "simulation_blocked"
    )

    audit_payload = {
        "decision_id": decision_id,
        "status": controller_status,
        "selected_seller_ids": selected_seller_ids,
        "preflight_checks": preflight_checks,
        "execution_lock": execution_lock,
        "simulated_steps": simulated_steps,
        "verification_checks": verification_checks,
        "rollback_plan": execution_plan.get(
            "rollback_plan",
            [],
        ),
    }

    audit_record = {
        "audit_id": _stable_hash(audit_payload),
        "event_type": (
            "foundation_execution_simulation"
        ),
        "controller_engine": (
            "foundation_execution_controller_v1"
        ),
        "decision_id": decision_id,
        "created_at": int(time.time()),
        "payload_hash": _stable_hash(audit_payload),
        "persistent": False,
    }

    return {
        "status": controller_status,
        "engine": "foundation_execution_controller_v1",
        "mode": "simulation_only",
        "decision_id": decision_id,
        "target": execution_plan.get("target"),
        "preflight_passed": preflight_passed,
        "preflight_checks": preflight_checks,
        "execution_lock": execution_lock,
        "simulated_steps": simulated_steps,
        "verification_passed": verification_passed,
        "verification_checks": verification_checks,
        "rollback_plan": execution_plan.get(
            "rollback_plan",
            [],
        ),
        "audit_record": audit_record,
        "execution_triggered": False,
        "state_modified": False,
        "policy": {
            "foundation_is_only_execution_authority": True,
            "approved_decision_required": True,
            "explicit_seller_selection_required": True,
            "simulation_only": True,
            "persistent_lock_not_created": True,
            "database_not_modified": True,
            "rollback_required_before_real_execution": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }
