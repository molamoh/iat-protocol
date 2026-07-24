"""Deterministic, explainable multi-objective decision intelligence."""

from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


POLICY_VERSION = "iat_decision_policy_v2"
ENGINE_VERSION = "iat_decision_core_v2"
OBJECTIVES = ("price", "quality", "trust", "reliability", "latency")
STRATEGY_WEIGHTS = {
    "balanced": {"price": .25, "quality": .25, "trust": .20, "reliability": .20, "latency": .10},
    "cheapest": {"price": .65, "quality": .10, "trust": .10, "reliability": .10, "latency": .05},
    "fastest": {"price": .10, "quality": .10, "trust": .10, "reliability": .15, "latency": .55},
    "safest": {"price": .10, "quality": .15, "trust": .35, "reliability": .35, "latency": .05},
    "quality": {"price": .10, "quality": .55, "trust": .15, "reliability": .15, "latency": .05},
}


class DecisionValidationError(ValueError):
    pass


def _bounded(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DecisionValidationError(f"invalid_{name}") from exc
    if not math.isfinite(number) or not 0 <= number <= 100:
        raise DecisionValidationError(f"{name}_out_of_range")
    return number


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True)
class DecisionPolicy:
    strategy: str = "balanced"
    maximum_price: float | None = None
    required_capabilities: tuple[str, ...] = ()
    minimum_trust: float = 0
    minimum_reliability: float = 0

    def normalized(self) -> dict[str, Any]:
        if self.strategy not in STRATEGY_WEIGHTS:
            raise DecisionValidationError("unsupported_strategy")
        maximum = None if self.maximum_price is None else float(self.maximum_price)
        if maximum is not None and (not math.isfinite(maximum) or maximum <= 0):
            raise DecisionValidationError("invalid_maximum_price")
        return {
            "strategy": self.strategy,
            "weights": STRATEGY_WEIGHTS[self.strategy],
            "maximum_price": maximum,
            "required_capabilities": sorted(set(self.required_capabilities)),
            "minimum_trust": _bounded(self.minimum_trust, "minimum_trust"),
            "minimum_reliability": _bounded(self.minimum_reliability, "minimum_reliability"),
        }


def evaluate_candidates(
    candidates: Iterable[Mapping[str, Any]],
    *,
    policy: DecisionPolicy | None = None,
    decision_type: str = "select_offer",
    context: Mapping[str, Any] | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    normalized_policy = (policy or DecisionPolicy()).normalized()
    maximum = normalized_policy["maximum_price"]
    required = set(normalized_policy["required_capabilities"])
    eligible, rejected = [], []
    seen_ids: set[str] = set()

    for raw in list(candidates):
        candidate_id = str(raw.get("candidate_id") or raw.get("offer_id") or "").strip()
        if not candidate_id:
            raise DecisionValidationError("candidate_id_required")
        if candidate_id in seen_ids:
            raise DecisionValidationError("duplicate_candidate_id")
        seen_ids.add(candidate_id)
        capabilities = set(str(item) for item in raw.get("capabilities", []))
        try:
            price = float(raw.get("price", 0))
        except (TypeError, ValueError) as exc:
            raise DecisionValidationError("invalid_price") from exc
        if not math.isfinite(price) or price < 0:
            raise DecisionValidationError("invalid_price")
        reasons = []
        if maximum is not None and price > maximum:
            reasons.append("price_above_maximum")
        if not required.issubset(capabilities):
            reasons.append("required_capabilities_missing")
        trust = _bounded(raw.get("trust", 0), "trust")
        reliability = _bounded(raw.get("reliability", 0), "reliability")
        if trust < normalized_policy["minimum_trust"]:
            reasons.append("trust_below_minimum")
        if reliability < normalized_policy["minimum_reliability"]:
            reasons.append("reliability_below_minimum")
        if reasons:
            rejected.append({"candidate_id": candidate_id, "reasons": reasons})
            continue
        price_score = 100.0
        if maximum is not None:
            price_score = max(0.0, min(100.0, (1 - price / maximum) * 100))
        metrics = {
            "price": price_score,
            "quality": _bounded(raw.get("quality", 0), "quality"),
            "trust": trust,
            "reliability": reliability,
            "latency": _bounded(raw.get("latency_score", 0), "latency"),
        }
        contributions = {
            key: round(metrics[key] * normalized_policy["weights"][key], 6)
            for key in OBJECTIVES
        }
        score = round(sum(contributions.values()), 6)
        eligible.append({
            "candidate_id": candidate_id,
            "score": score,
            "metrics": metrics,
            "contributions": contributions,
            "facts": {
                "price": price,
                "capabilities": sorted(capabilities),
                **dict(raw.get("facts") or {}),
            },
        })

    eligible.sort(key=lambda item: (-item["score"], item["candidate_id"]))
    selected = eligible[0] if eligible else None
    margin = selected["score"] - eligible[1]["score"] if len(eligible) > 1 else 0
    confidence = (
        round(min(.99, max(.5, .5 + margin / 100)), 6)
        if len(eligible) > 1
        else (.65 if selected else 0.0)
    )
    risks = []
    if len(eligible) == 1:
        risks.append("single_eligible_candidate")
    if len(eligible) > 1 and margin < 5:
        risks.append("narrow_winning_margin")
    if selected and selected["metrics"]["trust"] < 60:
        risks.append("selected_candidate_low_trust")
    timestamp = int(now or time.time())
    stable = {
        "decision_type": decision_type,
        "selected_candidate_id": selected["candidate_id"] if selected else None,
        "ranked_candidates": eligible,
        "rejected_candidates": rejected,
        "policy": normalized_policy,
        "context": dict(context or {}),
        "policy_version": POLICY_VERSION,
        "engine_version": ENGINE_VERSION,
    }
    return {
        "decision_id": f"idec_{uuid.uuid4().hex}",
        "status": "selected" if selected else "no_eligible_candidate",
        "decision": decision_type,
        "selected": selected,
        "alternatives": eligible[1:4],
        "ranked_candidates": eligible,
        "rejected_candidates": rejected,
        "confidence": confidence,
        "expected_utility": round((selected["score"] / 100), 6) if selected else 0.0,
        "constraints_satisfied": bool(selected),
        "risks": risks,
        "explanation": {
            "reason": "highest_policy_compliant_multi_objective_score" if selected else "no_candidate_satisfied_policy",
            "winning_margin": round(margin, 6),
            "objectives": list(OBJECTIVES),
            "confidence_basis": (
                "score_margin_between_top_candidates"
                if len(eligible) > 1
                else "single_candidate_confidence_cap"
            ),
        },
        "policy": normalized_policy,
        "context": dict(context or {}),
        "policy_version": POLICY_VERSION,
        "engine_version": ENGINE_VERSION,
        "simulation": True,
        "production_side_effects": False,
        "created_at": timestamp,
        "decision_hash": _canonical_hash(stable),
    }
