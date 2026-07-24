import pytest

from iat.intelligence.decision_core import (
    DecisionPolicy,
    DecisionValidationError,
    evaluate_candidates,
)
from iat.api.public import (
    DecisionCandidateRequest,
    DecisionPolicyRequest,
    DecisionSimulationRequest,
    simulate_decision,
)


def _candidates():
    return [
        {"candidate_id": "cheap", "price": 2, "quality": 70, "trust": 75, "reliability": 80, "latency_score": 60, "capabilities": ["search"]},
        {"candidate_id": "trusted", "price": 7, "quality": 90, "trust": 98, "reliability": 97, "latency_score": 80, "capabilities": ["search", "citations"]},
    ]


def test_decision_is_explainable_and_deterministic():
    policy = DecisionPolicy(strategy="safest", maximum_price=10, required_capabilities=("search",))
    first = evaluate_candidates(_candidates(), policy=policy, now=100)
    second = evaluate_candidates(_candidates(), policy=policy, now=100)

    assert first["selected"]["candidate_id"] == "trusted"
    assert first["decision_hash"] == second["decision_hash"]
    assert first["decision_id"] != second["decision_id"]
    assert first["production_side_effects"] is False
    assert first["selected"]["contributions"]["trust"] > 0


def test_constraints_reject_ineligible_candidates_with_reasons():
    decision = evaluate_candidates(
        _candidates(),
        policy=DecisionPolicy(maximum_price=5, required_capabilities=("citations",)),
    )

    assert decision["status"] == "no_eligible_candidate"
    reasons = {reason for item in decision["rejected_candidates"] for reason in item["reasons"]}
    assert {"price_above_maximum", "required_capabilities_missing"} <= reasons


def test_invalid_metrics_fail_closed():
    candidate = _candidates()[0] | {"trust": 101}

    with pytest.raises(DecisionValidationError, match="trust_out_of_range"):
        evaluate_candidates([candidate])


def test_single_candidate_confidence_is_capped_and_risk_is_visible():
    result = evaluate_candidates([_candidates()[0]])

    assert result["confidence"] == 0.65
    assert "single_eligible_candidate" in result["risks"]


def test_duplicate_candidate_identity_fails_closed():
    with pytest.raises(DecisionValidationError, match="duplicate_candidate_id"):
        evaluate_candidates([_candidates()[0], _candidates()[0]])


def test_public_simulation_contract_has_no_side_effects():
    request = DecisionSimulationRequest(
        candidates=[DecisionCandidateRequest(**item) for item in _candidates()],
        policy=DecisionPolicyRequest(strategy="balanced", maximum_price=10),
        context={"buyer_intent_id": "intent_test"},
    )

    result = simulate_decision(request)

    assert result["status"] == "selected"
    assert result["simulation"] is True
    assert result["production_side_effects"] is False
    assert result["context"]["buyer_intent_id"] == "intent_test"
