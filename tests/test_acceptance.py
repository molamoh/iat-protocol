import pytest
from pydantic import ValidationError

from iat.acceptance import AcceptanceCriteria, evaluate_acceptance


def test_explicit_acceptance_contract_passes_without_disclosing_content():
    criteria = AcceptanceCriteria(
        required_result_fields=["summary", "sources"],
        min_sources=2,
        minimum_confidence=0.8,
        min_verified_claim_count=1,
    )
    result = evaluate_acceptance(
        criteria,
        {
            "summary": "private result",
            "sources": ["one", "two"],
            "confidence": 87,
            "verified_claim_count": 2,
        },
        inbox_signature_status="not_configured",
    )
    assert result["decision"] == "accepted_by_explicit_criteria"
    assert result["failed_count"] == 0
    assert "private result" not in str(result)


def test_acceptance_contract_rejects_missing_requirements():
    criteria = AcceptanceCriteria(min_sources=3, require_signed_delivery=True)
    result = evaluate_acceptance(
        criteria,
        {"sources": ["one"]},
        inbox_signature_status="not_configured",
    )
    assert result["decision"] == "rejected_by_explicit_criteria"
    assert result["failed_count"] == 2


def test_empty_or_unknown_acceptance_contract_is_invalid():
    with pytest.raises(ValidationError):
        AcceptanceCriteria()
    with pytest.raises(ValidationError):
        AcceptanceCriteria(required_result_fields=["private_prompt"])
