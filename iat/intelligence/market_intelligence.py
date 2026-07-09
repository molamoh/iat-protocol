from collections import Counter, defaultdict
from typing import Any, Dict, List


def _as_list(value):
    import json

    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _safe_float(value, default=0.0):
    try:
        return float(value if value is not None else default)
    except Exception:
        return default


def build_market_intelligence() -> Dict[str, Any]:
    from iat.api.db import (
        list_orders_db,
        list_agents_db,
        get_stats_db,
        get_network_status_db,
    )

    orders = list_orders_db()
    agents = list_agents_db()
    stats = get_stats_db()
    network = get_network_status_db()

    service_demand = Counter()
    capability_demand = Counter()
    specialty_demand = Counter()
    service_supply = Counter()
    capability_supply = Counter()
    specialty_supply = Counter()

    pending_by_service = Counter()
    delivered_by_service = Counter()

    for order in orders.values():
        service = str(order.get("service") or "unknown")
        service_demand[service] += 1

        if str(order.get("status") or "").lower() == "delivered":
            delivered_by_service[service] += 1
        else:
            pending_by_service[service] += 1

        buyer_intent = order.get("buyer_intent") or {}
        if isinstance(buyer_intent, dict):
            for cap in buyer_intent.get("required_capabilities") or []:
                capability_demand[str(cap).strip().lower()] += 1

            for spec in buyer_intent.get("preferred_specialties") or []:
                specialty_demand[str(spec).strip().lower()] += 1

    for agent in agents:
        if not agent.get("available"):
            continue

        service = str(agent.get("service") or "unknown")
        service_supply[service] += 1

        for cap in _as_list(agent.get("capabilities")):
            capability_supply[str(cap).strip().lower()] += 1

        for spec in _as_list(agent.get("specialties")):
            specialty_supply[str(spec).strip().lower()] += 1

    service_gaps = []
    for service, demand_count in service_demand.items():
        supply_count = service_supply.get(service, 0)
        pending_count = pending_by_service.get(service, 0)

        gap_score = max(0, demand_count - supply_count) + pending_count

        if gap_score > 0:
            service_gaps.append({
                "service": service,
                "demand_count": demand_count,
                "supply_count": supply_count,
                "pending_count": pending_count,
                "delivered_count": delivered_by_service.get(service, 0),
                "gap_score": gap_score,
            })

    capability_gaps = []
    for cap, demand_count in capability_demand.items():
        supply_count = capability_supply.get(cap, 0)
        gap_score = max(0, demand_count - supply_count)

        if gap_score > 0:
            capability_gaps.append({
                "capability": cap,
                "demand_count": demand_count,
                "supply_count": supply_count,
                "gap_score": gap_score,
            })

    specialty_gaps = []
    for spec, demand_count in specialty_demand.items():
        supply_count = specialty_supply.get(spec, 0)
        gap_score = max(0, demand_count - supply_count)

        if gap_score > 0:
            specialty_gaps.append({
                "specialty": spec,
                "demand_count": demand_count,
                "supply_count": supply_count,
                "gap_score": gap_score,
            })

    service_gaps.sort(key=lambda x: x["gap_score"], reverse=True)
    capability_gaps.sort(key=lambda x: x["gap_score"], reverse=True)
    specialty_gaps.sort(key=lambda x: x["gap_score"], reverse=True)

    recommendations = []

    for gap in service_gaps[:10]:
        if gap["supply_count"] == 0:
            recommendations.append({
                "type": "market_supply",
                "action": "create_or_recruit_supply",
                "target": gap["service"],
                "reason": "service_has_demand_but_no_available_supply",
                "priority": "high",
                "safe_mode": "recommendation_only",
            })
        elif gap["pending_count"] > gap["supply_count"]:
            recommendations.append({
                "type": "capacity",
                "action": "increase_capacity_or_add_suppliers",
                "target": gap["service"],
                "reason": "pending_orders_exceed_available_supply",
                "priority": "medium",
                "safe_mode": "recommendation_only",
            })

    for gap in capability_gaps[:10]:
        recommendations.append({
            "type": "capability_gap",
            "action": "add_foundation_or_supplier_capability",
            "target": gap["capability"],
            "reason": "buyer_demand_capability_under_supplied",
            "priority": "high" if gap["supply_count"] == 0 else "medium",
            "safe_mode": "recommendation_only",
        })

    for gap in specialty_gaps[:10]:
        recommendations.append({
            "type": "specialty_gap",
            "action": "add_specialized_agent_or_factory_request",
            "target": gap["specialty"],
            "reason": "buyer_preferred_specialty_under_supplied",
            "priority": "high" if gap["supply_count"] == 0 else "medium",
            "safe_mode": "recommendation_only",
        })

    total_orders = int(stats.get("total_orders", 0) or 0)
    delivered_orders = int(stats.get("delivered_orders", 0) or 0)
    success_rate = _safe_float(stats.get("success_rate_percent"), 0.0)

    market_health_score = 100.0
    if total_orders > 0:
        pending_ratio = max(0.0, min(1.0, (total_orders - delivered_orders) / max(total_orders, 1)))
        market_health_score -= pending_ratio * 35

    if service_gaps:
        market_health_score -= min(len(service_gaps) * 5, 25)

    if capability_gaps:
        market_health_score -= min(len(capability_gaps) * 3, 20)

    if success_rate > 0:
        market_health_score = (market_health_score * 0.7) + (success_rate * 0.3)

    market_health_score = round(max(0.0, min(100.0, market_health_score)), 4)

    forecast_service_growth = {}
    capacity_shortage_probability = {}
    recommended_new_foundation_agents = []
    recommended_new_seller_agents = []
    recommended_factory_requests = []

    for gap in service_gaps[:10]:
        demand_count = gap.get("demand_count", 0)
        supply_count = gap.get("supply_count", 0)
        pending_count = gap.get("pending_count", 0)

        growth_pressure = min(1.0, demand_count / max(total_orders, 1))
        shortage_pressure = min(1.0, pending_count / max(supply_count, 1))

        forecast_service_growth[gap["service"]] = round(growth_pressure, 6)
        capacity_shortage_probability[gap["service"]] = round(shortage_pressure, 6)

        if shortage_pressure >= 0.75:
            recommended_new_seller_agents.append({
                "service": gap["service"],
                "recommended_count": max(1, min(5, int(shortage_pressure * 3))),
                "reason": "high_pending_pressure_vs_supply",
                "creation_mode": "recommendation_only",
            })

    for gap in capability_gaps[:10]:
        demand_count = gap.get("demand_count", 0)
        supply_count = gap.get("supply_count", 0)
        gap_score = gap.get("gap_score", 0)

        pressure = min(1.0, gap_score / max(demand_count, 1))

        if pressure >= 0.50:
            recommended_new_foundation_agents.append({
                "capability": gap["capability"],
                "recommended_count": 1 if pressure < 0.80 else 2,
                "reason": "foundation_capability_gap_detected",
                "creation_mode": "recommendation_only",
            })

        if supply_count <= 1 and demand_count >= 3:
            recommended_factory_requests.append({
                "target_capability": gap["capability"],
                "recommended_supplier_count": min(5, max(1, int(gap_score / 3))),
                "reason": "supplier_capability_under_supply",
                "creation_mode": "recommendation_only",
            })

    predicted_market_health = market_health_score

    if service_gaps:
        predicted_market_health -= min(len(service_gaps) * 2.5, 10)

    if capability_gaps:
        predicted_market_health -= min(len(capability_gaps) * 1.5, 10)

    if recommended_new_seller_agents or recommended_new_foundation_agents:
        predicted_market_health += 5

    predicted_market_health = round(max(0.0, min(100.0, predicted_market_health)), 4)

    forecast_confidence = 0.35
    if total_orders >= 10:
        forecast_confidence += 0.20
    if total_orders >= 50:
        forecast_confidence += 0.20
    if service_gaps or capability_gaps:
        forecast_confidence += 0.10

    forecast_confidence = round(max(0.0, min(0.85, forecast_confidence)), 4)

    forecast = {
        "forecast_type": "market_intelligence_forecast",
        "forecast_horizon": "short_term",
        "expected_service_growth": forecast_service_growth,
        "capacity_shortage_probability": capacity_shortage_probability,
        "recommended_new_foundation_agents": recommended_new_foundation_agents[:10],
        "recommended_new_seller_agents": recommended_new_seller_agents[:10],
        "recommended_factory_requests": recommended_factory_requests[:10],
        "predicted_market_health_score": predicted_market_health,
        "confidence": forecast_confidence,
        "execution_policy": {
            "forecast_does_not_create_agents": True,
            "forecast_does_not_trigger_factory": True,
            "foundation_approval_required": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }

    action_plan = {
        "priority_1": [],
        "priority_2": [],
        "priority_3": [],
        "foundation_approval_required": True,
        "execution_mode": "recommendation_only",
        "policy": {
            "action_plan_does_not_execute": True,
            "foundation_approval_required": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }

    for rec in recommendations:
        if rec.get("type") == "capacity":
            action_plan["priority_1"].append({
                "action": "increase_capacity",
                "target": rec["target"],
                "reason": rec["reason"],
            })

    for rec in forecast.get("recommended_factory_requests", []):
        action_plan["priority_2"].append({
            "action": "factory_request",
            "target": rec["target_capability"],
            "recommended_supplier_count": rec["recommended_supplier_count"],
            "reason": rec["reason"],
        })

    for rec in forecast.get("recommended_new_foundation_agents", []):
        action_plan["priority_3"].append({
            "action": "new_foundation_capability",
            "target": rec["capability"],
            "recommended_count": rec["recommended_count"],
            "reason": rec["reason"],
        })


    return {
        "status": "ok",
        "engine": "iat_market_intelligence_v2",
        "mode": "observation_and_recommendation_only",
        "market_health_score": market_health_score,
        "stats": stats,
        "network_summary": network.get("network", {}),
        "demand": {
            "services": dict(service_demand),
            "capabilities": dict(capability_demand),
            "specialties": dict(specialty_demand),
        },
        "supply": {
            "services": dict(service_supply),
            "capabilities": dict(capability_supply),
            "specialties": dict(specialty_supply),
        },
        "gaps": {
            "services": service_gaps[:20],
            "capabilities": capability_gaps[:20],
            "specialties": specialty_gaps[:20],
        },
        "forecast": forecast,
        "action_plan": action_plan,
        "recommendations": recommendations[:30],
        "policy": {
            "does_not_create_agents": True,
            "does_not_modify_capacity": True,
            "does_not_override_foundation": True,
            "seller_cannot_trigger_auto_generation": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }
