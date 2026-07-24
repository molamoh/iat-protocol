"""Explainable, simulation-only competitive intelligence for IAT sellers."""

from __future__ import annotations

import math
import statistics
from typing import Any, Iterable, Mapping

from iat.intelligence.decision_core import DecisionPolicy, evaluate_candidates


class SellerIntelligenceError(ValueError):
    pass


def _number(value: Any, name: str, *, minimum: float = 0, maximum: float = 1e9) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SellerIntelligenceError(f"invalid_{name}") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise SellerIntelligenceError(f"{name}_out_of_range")
    return number


def _normalize_offer(raw: Mapping[str, Any]) -> dict[str, Any]:
    offer_id = str(raw.get("offer_id") or "").strip()
    if not offer_id:
        raise SellerIntelligenceError("offer_id_required")
    return {
        "offer_id": offer_id,
        "price": _number(raw.get("price"), "price"),
        "quality": _number(raw.get("quality"), "quality", maximum=100),
        "trust": _number(raw.get("trust"), "trust", maximum=100),
        "reliability": _number(raw.get("reliability"), "reliability", maximum=100),
        "latency_score": _number(raw.get("latency_score"), "latency_score", maximum=100),
        "capabilities": sorted(set(str(item) for item in raw.get("capabilities", []))),
    }


def analyze_seller_offer(
    seller_offer: Mapping[str, Any],
    market_offers: Iterable[Mapping[str, Any]],
    *,
    monthly_orders: int = 0,
    variable_cost_per_order: float = 0,
    commission_rate: float = .10,
    price_elasticity: float = 1.0,
) -> dict[str, Any]:
    seller = _normalize_offer(seller_offer)
    market = [_normalize_offer(item) for item in market_offers]
    if not 2 <= len(market) <= 100:
        raise SellerIntelligenceError("market_requires_2_to_100_offers")
    all_ids = [seller["offer_id"], *(item["offer_id"] for item in market)]
    if len(set(all_ids)) != len(all_ids):
        raise SellerIntelligenceError("duplicate_offer_id")
    orders = int(monthly_orders)
    if isinstance(monthly_orders, bool) or orders != monthly_orders or not 0 <= orders <= 10_000_000:
        raise SellerIntelligenceError("monthly_orders_out_of_range")
    cost = _number(variable_cost_per_order, "variable_cost_per_order")
    commission = _number(commission_rate, "commission_rate", maximum=.5)
    elasticity = _number(price_elasticity, "price_elasticity", maximum=5)

    prices = [item["price"] for item in market]
    market_median = statistics.median(prices)
    maximum_price = max([seller["price"], *prices, .000001])
    decision = evaluate_candidates(
        [
            {
                "candidate_id": item["offer_id"],
                "price": item["price"],
                "quality": item["quality"],
                "trust": item["trust"],
                "reliability": item["reliability"],
                "latency_score": item["latency_score"],
                "capabilities": item["capabilities"],
            }
            for item in [seller, *market]
        ],
        policy=DecisionPolicy(strategy="balanced", maximum_price=maximum_price),
        decision_type="seller_market_position",
        context={"seller_offer_id": seller["offer_id"], "benchmark_count": len(market)},
    )
    ranked_ids = [item["candidate_id"] for item in decision["ranked_candidates"]]
    rank = ranked_ids.index(seller["offer_id"]) + 1
    total = len(ranked_ids)
    percentile = round(100 * (total - rank) / max(1, total - 1), 2)

    top_count = max(1, math.ceil(len(market) * .25))
    top_market = [
        item for item in decision["ranked_candidates"]
        if item["candidate_id"] != seller["offer_id"]
    ][:top_count]
    market_by_id = {item["offer_id"]: item for item in market}
    top_capabilities = sorted({
        capability
        for ranked in top_market
        for capability in market_by_id[ranked["candidate_id"]]["capabilities"]
    })
    capability_gaps = sorted(set(top_capabilities) - set(seller["capabilities"]))

    break_even_price = cost / max(.000001, 1 - commission)
    candidate_prices = {
        "current": seller["price"],
        "market_median": market_median,
        "price_minus_10_percent": seller["price"] * .9,
        "price_plus_10_percent": seller["price"] * 1.1,
    }
    scenarios = []
    for scenario, price in candidate_prices.items():
        price = max(0.0, price)
        price_change = (price / seller["price"] - 1) if seller["price"] else 0
        demand_multiplier = max(.1, min(3.0, 1 - elasticity * price_change))
        projected_orders = round(orders * demand_multiplier)
        contribution = (price * (1 - commission) - cost) * projected_orders
        scenarios.append({
            "scenario": scenario,
            "unit_price": round(price, 6),
            "estimated_order_multiplier": round(demand_multiplier, 6),
            "estimated_monthly_orders": projected_orders,
            "estimated_monthly_contribution": round(contribution, 6),
            "economically_positive": price >= break_even_price,
        })
    best_viable = max(
        (item for item in scenarios if item["economically_positive"]),
        key=lambda item: item["estimated_monthly_contribution"],
        default=None,
    )
    recommendations = []
    if capability_gaps:
        recommendations.append({
            "type": "capability_gap",
            "priority": "high",
            "suggested_capabilities": capability_gaps[:10],
            "reason": "capabilities_present_among_top_quartile_competitors",
        })
    if seller["price"] > market_median:
        recommendations.append({
            "type": "price_position",
            "priority": "medium",
            "reason": "price_above_market_median",
            "market_median": round(market_median, 6),
        })
    if best_viable:
        recommendations.append({
            "type": "pricing_scenario",
            "priority": "informational",
            "scenario": best_viable["scenario"],
            "reason": "highest_simulated_contribution_under_declared_assumptions",
        })

    return {
        "status": "ok",
        "analysis_type": "seller_competitive_intelligence",
        "seller_offer_id": seller["offer_id"],
        "market": {
            "benchmark_count": len(market),
            "median_price": round(market_median, 6),
            "seller_rank": rank,
            "total_ranked": total,
            "competitive_percentile": percentile,
        },
        "decision_snapshot": {
            "decision_hash": decision["decision_hash"],
            "seller_score": next(
                item["score"] for item in decision["ranked_candidates"]
                if item["candidate_id"] == seller["offer_id"]
            ),
            "policy_version": decision["policy_version"],
        },
        "capability_gaps": capability_gaps,
        "break_even_unit_price": round(break_even_price, 6),
        "scenarios": scenarios,
        "recommendations": recommendations,
        "assumptions": {
            "price_elasticity": elasticity,
            "commission_rate": commission,
            "monthly_orders_baseline": orders,
            "benchmarks_are_caller_supplied": True,
        },
        "governance": {
            "simulation_only": True,
            "production_side_effects": False,
            "automatic_price_change_allowed": False,
            "automatic_catalog_change_allowed": False,
            "seller_approval_required": True,
        },
    }
