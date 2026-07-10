from typing import Any, Dict, List


def _safe_float(value, default=0.0):
    try:
        return float(value if value is not None else default)
    except Exception:
        return default


def build_foundation_execution_plan(decision_id: str) -> Dict[str, Any]:
    from iat.api.db import (
        get_foundation_decision_db,
        resolve_sellers_for_service_db,
        compute_seller_dynamic_agent_capacity_db,
    )

    decision = get_foundation_decision_db(decision_id)

    if not decision:
        return {
            "status": "error",
            "message": "foundation_decision_not_found",
            "decision_id": decision_id,
        }

    decision_status = str(
        decision.get("status") or ""
    ).lower()

    if decision_status != "approved":
        return {
            "status": "blocked",
            "message": "foundation_decision_not_approved",
            "decision_id": decision_id,
            "current_status": decision_status,
            "required_status": "approved",
        }

    target = str(decision.get("target") or "").strip()
    execution_order = decision.get("execution_order") or []
    source_payload = decision.get("source_payload") or {}

    plan_steps: List[Dict[str, Any]] = []
    governance_checks: List[Dict[str, Any]] = []
    rollback_plan: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []

    governance_checks.append({
        "check": "decision_is_approved",
        "passed": True,
    })

    governance_checks.append({
        "check": "foundation_authority_present",
        "passed": (
            str(decision.get("protocol_authority") or "")
            == "iat_foundation"
        ),
    })

    governance_checks.append({
        "check": "execution_order_present",
        "passed": bool(execution_order),
    })

    for position, action in enumerate(execution_order, start=1):
        if action == "increase_capacity":
            resolution = resolve_sellers_for_service_db(
                service=target,
                limit=20,
            )

            sellers = resolution.get("sellers", [])
            seller_plans = []

            for seller in sellers:
                seller_id = seller.get("seller_id")

                capacity_preview = (
                    compute_seller_dynamic_agent_capacity_db(
                        seller_id=seller_id,
                    )
                )

                seller_plans.append({
                    "seller_id": seller_id,
                    "service": target,
                    "selection_signals": {
                        "available_agent_count": seller.get(
                            "available_agent_count"
                        ),
                        "runtime_health_score": seller.get(
                            "max_runtime_health_score"
                        ),
                        "reputation": seller.get(
                            "max_reputation"
                        ),
                        "risk_score": seller.get(
                            "min_risk_score"
                        ),
                    },
                    "capacity_preview": capacity_preview,
                    "foundation_selection_required": True,
                    "selected": False,
                })

                if capacity_preview.get("status") == "ok":
                    rollback_plan.append({
                        "action": "restore_seller_capacity",
                        "seller_id": seller_id,
                        "restore_max_agents_allowed": (
                            capacity_preview.get(
                                "old_max_agents_allowed"
                            )
                        ),
                        "trigger": "execution_failure_or_governance_rollback",
                    })

            plan_steps.append({
                "position": position,
                "action": action,
                "target": target,
                "dispatcher": "seller_dynamic_capacity_engine",
                "existing_function": (
                    "recompute_seller_dynamic_agent_capacity_db"
                ),
                "seller_resolution": resolution,
                "seller_execution_candidates": seller_plans,
                "execution_ready": bool(seller_plans),
                "foundation_selection_required": True,
            })

            if not seller_plans:
                conflicts.append({
                    "type": "missing_execution_target",
                    "action": action,
                    "target": target,
                    "reason": "no_eligible_seller_resolved",
                })

        elif action == "factory_request":
            source_actions = source_payload.get(
                "source_actions"
            ) or []

            matching = next(
                (
                    item
                    for item in source_actions
                    if item.get("action") == "factory_request"
                ),
                {},
            )

            plan_steps.append({
                "position": position,
                "action": action,
                "target": target,
                "dispatcher": "seller_agent_factory",
                "existing_function": (
                    "create_seller_agent_factory_request_db"
                ),
                "recommended_supplier_count": matching.get(
                    "recommended_supplier_count"
                ),
                "execution_ready": False,
                "reason": "seller_identity_and_factory_payload_required",
                "foundation_selection_required": True,
            })

        elif action == "new_foundation_capability":
            source_actions = source_payload.get(
                "source_actions"
            ) or []

            matching = next(
                (
                    item
                    for item in source_actions
                    if item.get("action")
                    == "new_foundation_capability"
                ),
                {},
            )

            plan_steps.append({
                "position": position,
                "action": action,
                "target": target,
                "dispatcher": "foundation_governance",
                "existing_function": None,
                "recommended_count": matching.get(
                    "recommended_count"
                ),
                "execution_ready": False,
                "reason": "foundation_capability_governance_required",
                "foundation_selection_required": True,
            })

        else:
            plan_steps.append({
                "position": position,
                "action": action,
                "target": target,
                "execution_ready": False,
                "reason": "unsupported_execution_action",
            })

            conflicts.append({
                "type": "unsupported_action",
                "action": action,
                "target": target,
            })

    ready_steps = [
        step for step in plan_steps
        if step.get("execution_ready")
    ]

    blocked_steps = [
        step for step in plan_steps
        if not step.get("execution_ready")
    ]

    decision_score = _safe_float(
        decision.get("decision_score"),
        0.0,
    )

    risk_score = max(
        [
            _safe_float(
                seller.get("selection_signals", {}).get(
                    "risk_score"
                ),
                0.0,
            )
            for step in plan_steps
            for seller in step.get(
                "seller_execution_candidates", []
            )
        ]
        or [0.0]
    )

    impact_score = round(
        max(
            0.0,
            min(
                100.0,
                decision_score * (1.0 - min(risk_score, 1.0)),
            ),
        ),
        4,
    )

    execution_ready = (
        bool(plan_steps)
        and not conflicts
        and len(ready_steps) == len(plan_steps)
        and all(
            check.get("passed")
            for check in governance_checks
        )
    )

    return {
        "status": "execution_plan_built",
        "engine": "foundation_execution_planner_v1",
        "decision_id": decision_id,
        "decision_status": decision_status,
        "target": target,
        "decision_score": decision_score,
        "estimated_impact_score": impact_score,
        "execution_ready": execution_ready,
        "ready_step_count": len(ready_steps),
        "blocked_step_count": len(blocked_steps),
        "plan_steps": plan_steps,
        "governance_checks": governance_checks,
        "conflicts": conflicts,
        "rollback_plan": rollback_plan,
        "execution_triggered": False,
        "policy": {
            "planning_only": True,
            "does_not_modify_capacity": True,
            "does_not_create_factory_requests": True,
            "does_not_create_foundation_agents": True,
            "foundation_selection_required": True,
            "foundation_final_authority": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }
