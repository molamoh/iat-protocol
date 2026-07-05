"""
IAT Settlement Decision Engine v1.

Purpose:
- Provide a standard decision contract for settlement evaluators.
- Aggregate independent evaluator reports into one final settlement decision.
- Keep workflow orchestration separate from financial/governance decision logic.
"""

from __future__ import annotations

from typing import Any, Dict, List

from iat.action_engine.unified_trust_engine import compute_unified_trust_score


VALID_ENGINE_DECISIONS = {
    "approve",
    "manual_review",
    "block",
    "abstain",
}


FINAL_DECISIONS = {
    "authorized",
    "manual_review",
    "blocked",
}


def normalize_decision_report(
    engine: str,
    decision: str = "abstain",
    confidence: float = 0.0,
    risk_score: float = 50.0,
    weight: float = 1.0,
    reasons: List[str] | None = None,
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    decision = str(decision or "abstain")

    if decision not in VALID_ENGINE_DECISIONS:
        decision = "abstain"

    try:
        confidence = float(confidence or 0.0)
    except Exception:
        confidence = 0.0

    try:
        risk_score = float(risk_score or 50.0)
    except Exception:
        risk_score = 50.0

    try:
        weight = float(weight or 1.0)
    except Exception:
        weight = 1.0

    confidence = max(0.0, min(confidence, 1.0))
    risk_score = max(0.0, min(risk_score, 100.0))
    weight = max(0.0, weight)

    return {
        "engine": str(engine or "unknown"),
        "decision": decision,
        "confidence": round(confidence, 4),
        "risk_score": round(risk_score, 4),
        "weight": round(weight, 4),
        "reasons": reasons if isinstance(reasons, list) else [],
        "metadata": metadata if isinstance(metadata, dict) else {},
    }


def aggregate_settlement_decisions(
    reports: List[Dict[str, Any]],
) -> Dict[str, Any]:
    normalized = []

    for report in reports or []:
        if not isinstance(report, dict):
            continue

        normalized.append(
            normalize_decision_report(
                engine=report.get("engine"),
                decision=report.get("decision"),
                confidence=report.get("confidence"),
                risk_score=report.get("risk_score"),
                weight=report.get("weight"),
                reasons=report.get("reasons"),
                metadata=report.get("metadata"),
            )
        )

    if not normalized:
        return {
            "decision_engine": "settlement_decision_engine_v1",
            "final_decision": "manual_review",
            "confidence": 0.0,
            "consensus": 0.0,
            "risk_score": 50.0,
            "reasons": ["no_evaluator_reports"],
            "engine_reports": [],
            "audit": {
                "approve_weight": 0.0,
                "manual_review_weight": 0.0,
                "block_weight": 0.0,
                "total_weight": 0.0,
            },
        }

    approve_weight = 0.0
    manual_review_weight = 0.0
    block_weight = 0.0
    total_weight = 0.0

    weighted_confidence = 0.0
    weighted_risk = 0.0
    reasons = []

    for report in normalized:
        weight = float(report.get("weight", 0.0) or 0.0)
        decision = report.get("decision")

        total_weight += weight
        weighted_confidence += float(report.get("confidence", 0.0) or 0.0) * weight
        weighted_risk += float(report.get("risk_score", 50.0) or 50.0) * weight

        if decision == "approve":
            approve_weight += weight
        elif decision == "manual_review":
            manual_review_weight += weight
        elif decision == "block":
            block_weight += weight

        for reason in report.get("reasons") or []:
            if reason not in reasons:
                reasons.append(reason)

    if total_weight <= 0:
        final_decision = "manual_review"
        confidence = 0.0
        consensus = 0.0
        risk_score = 50.0
        reasons.append("zero_total_weight")
    else:
        confidence = weighted_confidence / total_weight
        risk_score = weighted_risk / total_weight

        strongest_weight = max(
            approve_weight,
            manual_review_weight,
            block_weight,
        )
        consensus = strongest_weight / total_weight

        mandatory_manual_review = any(
            report.get("decision") == "manual_review"
            and report.get("engine") in {
                "foundation_evaluator_v1",
                "risk_evaluator_v1",
                "policy_evaluator_v1",
            }
            for report in normalized
        )

        if block_weight > 0:
            final_decision = "blocked"
            reasons.append("one_or_more_engines_blocked")
        elif mandatory_manual_review:
            final_decision = "manual_review"
            reasons.append("mandatory_evaluator_requires_manual_review")
        elif manual_review_weight > approve_weight:
            final_decision = "manual_review"
            reasons.append("manual_review_weight_exceeds_approve_weight")
        elif approve_weight > 0 and confidence >= 0.70 and risk_score <= 45:
            final_decision = "authorized"
            reasons.append("approval_consensus_above_threshold")
        else:
            final_decision = "manual_review"
            reasons.append("approval_threshold_not_met")

    return {
        "decision_engine": "settlement_decision_engine_v1",
        "final_decision": final_decision,
        "confidence": round(float(confidence), 4),
        "consensus": round(float(consensus), 4),
        "risk_score": round(float(risk_score), 4),
        "reasons": reasons,
        "engine_reports": normalized,
        "audit": {
            "approve_weight": round(approve_weight, 4),
            "manual_review_weight": round(manual_review_weight, 4),
            "block_weight": round(block_weight, 4),
            "total_weight": round(total_weight, 4),
        },
    }


def evaluate_foundation_review_v1(
    settlement: Dict[str, Any],
) -> Dict[str, Any]:
    payload = settlement.get("settlement_payload")

    if not isinstance(payload, dict):
        payload = {}

    foundation_review = payload.get("foundation_review")

    if not isinstance(foundation_review, dict):
        return normalize_decision_report(
            engine="foundation_evaluator_v1",
            decision="manual_review",
            confidence=0.40,
            risk_score=60.0,
            weight=1.0,
            reasons=["foundation_review_missing"],
            metadata={
                "settlement_id": settlement.get("settlement_id"),
                "settlement_status": settlement.get("settlement_status"),
            },
        )

    verdict = foundation_review.get("verdict")
    decision_ready = foundation_review.get("foundation_decision_ready") is True
    evidence_status = foundation_review.get("foundation_evidence_status")
    confidence = float(foundation_review.get("decision_confidence", 0.5) or 0.5)
    reason = foundation_review.get("reason")

    reasons = []
    if reason:
        reasons.append(str(reason))

    if evidence_status:
        reasons.append(f"foundation_evidence_status:{evidence_status}")

    if verdict in ("blocked", "rejected", "foundation_rejected"):
        return normalize_decision_report(
            engine="foundation_evaluator_v1",
            decision="block",
            confidence=max(confidence, 0.70),
            risk_score=85.0,
            weight=1.0,
            reasons=reasons + ["foundation_verdict_blocks_settlement"],
            metadata=foundation_review,
        )

    if decision_ready and verdict in (
        "approve",
        "approved",
        "foundation_verified_with_evidence",
        "foundation_verified",
    ):
        return normalize_decision_report(
            engine="foundation_evaluator_v1",
            decision="approve",
            confidence=confidence,
            risk_score=25.0,
            weight=1.0,
            reasons=reasons + ["foundation_review_decision_ready"],
            metadata=foundation_review,
        )

    return normalize_decision_report(
        engine="foundation_evaluator_v1",
        decision="manual_review",
        confidence=confidence,
        risk_score=55.0,
        weight=1.0,
        reasons=reasons + ["foundation_review_not_ready_for_approval"],
        metadata=foundation_review,
    )



def evaluate_risk_review_v1(
    settlement: Dict[str, Any],
) -> Dict[str, Any]:
    payload = settlement.get("settlement_payload")

    if not isinstance(payload, dict):
        payload = {}

    risk_review = payload.get("risk_review")

    if not isinstance(risk_review, dict):
        return normalize_decision_report(
            engine="risk_evaluator_v1",
            decision="manual_review",
            confidence=0.40,
            risk_score=65.0,
            weight=1.0,
            reasons=["risk_review_missing"],
            metadata={
                "settlement_id": settlement.get("settlement_id"),
                "settlement_status": settlement.get("settlement_status"),
            },
        )

    risk_decision = risk_review.get("risk_decision")
    risk_score = float(risk_review.get("risk_score", 50.0) or 50.0)
    confidence = float(risk_review.get("confidence", 0.5) or 0.5)
    risk_level = risk_review.get("risk_level")
    reason = risk_review.get("reason")

    reasons = []

    if reason:
        reasons.append(str(reason))

    if risk_level:
        reasons.append(f"risk_level:{risk_level}")

    if risk_decision in ("blocked", "block"):
        return normalize_decision_report(
            engine="risk_evaluator_v1",
            decision="block",
            confidence=max(confidence, 0.70),
            risk_score=max(risk_score, 80.0),
            weight=1.0,
            reasons=reasons + ["risk_review_blocks_settlement"],
            metadata=risk_review,
        )

    if risk_decision in ("approve", "approved") and risk_score <= 45:
        return normalize_decision_report(
            engine="risk_evaluator_v1",
            decision="approve",
            confidence=confidence,
            risk_score=risk_score,
            weight=1.0,
            reasons=reasons + ["risk_review_accepts_settlement"],
            metadata=risk_review,
        )

    return normalize_decision_report(
        engine="risk_evaluator_v1",
        decision="manual_review",
        confidence=confidence,
        risk_score=risk_score,
        weight=1.0,
        reasons=reasons + ["risk_review_requires_manual_review"],
        metadata=risk_review,
    )



def evaluate_policy_review_v1(
    settlement: Dict[str, Any],
) -> Dict[str, Any]:
    payload = settlement.get("settlement_payload")

    if not isinstance(payload, dict):
        payload = {}

    policy_review = payload.get("policy_review")

    if not isinstance(policy_review, dict):
        return normalize_decision_report(
            engine="policy_evaluator_v1",
            decision="manual_review",
            confidence=0.40,
            risk_score=60.0,
            weight=1.0,
            reasons=["policy_review_missing"],
            metadata={
                "settlement_id": settlement.get("settlement_id"),
                "settlement_status": settlement.get("settlement_status"),
            },
        )

    policy_decision = policy_review.get("policy_decision")
    release_policy_mode = policy_review.get("release_policy_mode")
    confidence = float(policy_review.get("confidence", 0.5) or 0.5)
    reason = policy_review.get("reason")

    reasons = []

    if reason:
        reasons.append(str(reason))

    if release_policy_mode:
        reasons.append(f"release_policy_mode:{release_policy_mode}")

    if policy_decision in ("blocked", "block"):
        return normalize_decision_report(
            engine="policy_evaluator_v1",
            decision="block",
            confidence=max(confidence, 0.70),
            risk_score=85.0,
            weight=1.0,
            reasons=reasons + ["policy_review_blocks_settlement"],
            metadata=policy_review,
        )

    if policy_decision in ("approve", "approved", "authorized") and release_policy_mode in (
        "automatic",
        "approved",
        "authorized",
    ):
        return normalize_decision_report(
            engine="policy_evaluator_v1",
            decision="approve",
            confidence=confidence,
            risk_score=30.0,
            weight=1.0,
            reasons=reasons + ["policy_review_accepts_settlement"],
            metadata=policy_review,
        )

    return normalize_decision_report(
        engine="policy_evaluator_v1",
        decision="manual_review",
        confidence=confidence,
        risk_score=55.0,
        weight=1.0,
        reasons=reasons + ["policy_review_requires_manual_review"],
        metadata=policy_review,
    )




def evaluate_unified_trust_review_v1(
    settlement: Dict[str, Any],
) -> Dict[str, Any]:
    payload = settlement.get("settlement_payload")

    if not isinstance(payload, dict):
        payload = {}

    entity = payload.get("unified_trust_entity")

    if not isinstance(entity, dict):
        entity = {
            "entity_id": settlement.get("seller_agent_id") or settlement.get("seller_id") or settlement.get("settlement_id"),
            "entity_type": payload.get("entity_type") or "settlement_subject",
            "reputation": payload.get("reputation", 50),
            "trust_score": payload.get("trust_score", 50),
            "risk_score": payload.get("risk_score", 50),
            "reliability_score": payload.get("reliability_score", 50),
            "runtime_health_score": payload.get("runtime_health_score", 50),
            "governance_score": payload.get("governance_score", 50),
        }

    trust = (
        entity.get("trust_snapshot")
        or entity.get("unified_trust")
    )

    if trust is None:
        trust = compute_unified_trust_score(entity)

    score = float(trust.get("score", 50) or 50)
    tier = trust.get("tier")

    reasons = [
        f"unified_trust_tier:{tier}",
        f"unified_trust_score:{round(score, 4)}",
    ]

    if score >= 75:
        return normalize_decision_report(
            engine="unified_trust_evaluator_v1",
            decision="approve",
            confidence=0.80,
            risk_score=max(0.0, 100.0 - score),
            weight=1.0,
            reasons=reasons + ["unified_trust_accepts_settlement"],
            metadata=trust,
        )

    if score <= 30:
        return normalize_decision_report(
            engine="unified_trust_evaluator_v1",
            decision="block",
            confidence=0.85,
            risk_score=max(70.0, 100.0 - score),
            weight=1.0,
            reasons=reasons + ["unified_trust_blocks_settlement"],
            metadata=trust,
        )

    return normalize_decision_report(
        engine="unified_trust_evaluator_v1",
        decision="manual_review",
        confidence=0.60,
        risk_score=100.0 - score,
        weight=1.0,
        reasons=reasons + ["unified_trust_requires_manual_review"],
        metadata=trust,
    )


SETTLEMENT_EVALUATORS = [
    evaluate_foundation_review_v1,
    evaluate_risk_review_v1,
    evaluate_policy_review_v1,
    evaluate_unified_trust_review_v1,
]



def evaluate_settlement_decision_v1(
    settlement: Dict[str, Any],
    context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Minimal v1 evaluator set.

    This is intentionally conservative:
    - No automatic authorization without real evaluator inputs.
    - Current version returns manual_review until Foundation/Risk/Policy engines
      are connected.
    """
    context = context if isinstance(context, dict) else {}


    payload = settlement.get("settlement_payload") or {}

    foundation_decision = payload.get("foundation_decision") or {}

    decision_info = foundation_decision.get("decision") or {}

    stored_hash = payload.get("foundation_decision_hash")
    current_hash = decision_info.get("decision_hash")

    if stored_hash and current_hash and stored_hash != current_hash:
        return {
            "decision_engine": "settlement_decision_engine_v1",
            "final_decision": "blocked",
            "reason": "foundation_decision_hash_mismatch",
            "status": "rejected",
            "context": context,
        }

    reports = []

    for evaluator in SETTLEMENT_EVALUATORS:
        reports.append(evaluator(settlement))

    decision = aggregate_settlement_decisions(reports)

    decision["context"] = context
    return decision
