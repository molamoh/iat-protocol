"""Explicit, deterministic acceptance contracts for autonomous deliveries."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


PUBLIC_RESULT_FIELDS = {
    "confidence",
    "final_recommendation",
    "foundation_decision_ready",
    "foundation_verdict",
    "message",
    "recommendations",
    "sources",
    "status",
    "summary",
    "verified_claim_count",
}


class AcceptanceCriteria(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_result_fields: list[str] = Field(default_factory=list, max_length=20)
    min_sources: int = Field(default=0, ge=0, le=100)
    minimum_confidence: float | None = Field(default=None, ge=0, le=1)
    min_verified_claim_count: int = Field(default=0, ge=0, le=10_000)
    require_foundation_decision: bool = False
    require_signed_delivery: bool = False

    @model_validator(mode="after")
    def validate_contract(self):
        normalized = sorted({str(item).strip() for item in self.required_result_fields})
        if any(item not in PUBLIC_RESULT_FIELDS for item in normalized):
            raise ValueError("acceptance_result_field_not_allowed")
        self.required_result_fields = normalized
        if not (
            normalized
            or self.min_sources
            or self.minimum_confidence is not None
            or self.min_verified_claim_count
            or self.require_foundation_decision
            or self.require_signed_delivery
        ):
            raise ValueError("acceptance_criteria_empty")
        return self


def evaluate_acceptance(
    criteria: AcceptanceCriteria,
    result: dict[str, Any],
    *,
    inbox_signature_status: str,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    for field in criteria.required_result_fields:
        present = field in result and result[field] not in (None, "", [], {})
        checks.append({"code": f"required_field:{field}", "passed": present})

    if criteria.min_sources:
        source_count = len(result.get("sources")) if isinstance(result.get("sources"), list) else 0
        checks.append({
            "code": "minimum_sources",
            "passed": source_count >= criteria.min_sources,
            "actual": source_count,
            "required": criteria.min_sources,
        })

    if criteria.minimum_confidence is not None:
        try:
            confidence = float(result.get("confidence"))
            if confidence > 1:
                confidence /= 100
        except (TypeError, ValueError):
            confidence = -1
        checks.append({
            "code": "minimum_confidence",
            "passed": confidence >= criteria.minimum_confidence,
            "actual": max(0, confidence),
            "required": criteria.minimum_confidence,
        })

    if criteria.min_verified_claim_count:
        try:
            claim_count = max(0, int(result.get("verified_claim_count") or 0))
        except (TypeError, ValueError):
            claim_count = 0
        checks.append({
            "code": "minimum_verified_claims",
            "passed": claim_count >= criteria.min_verified_claim_count,
            "actual": claim_count,
            "required": criteria.min_verified_claim_count,
        })

    if criteria.require_foundation_decision:
        passed = result.get("foundation_decision_ready") is True and bool(
            result.get("foundation_verdict") or result.get("final_recommendation")
        )
        checks.append({"code": "foundation_decision_required", "passed": passed})

    if criteria.require_signed_delivery:
        checks.append({
            "code": "signed_delivery_required",
            "passed": inbox_signature_status == "verified",
        })

    return {
        "decision": (
            "accepted_by_explicit_criteria"
            if checks and all(check["passed"] for check in checks)
            else "rejected_by_explicit_criteria"
        ),
        "checks": checks,
        "passed_count": sum(bool(check["passed"]) for check in checks),
        "failed_count": sum(not bool(check["passed"]) for check in checks),
    }
