from unittest.mock import Mock

import pytest
import requests
from pydantic import ValidationError

from iat.api.public import (
    SandboxPreviewRequest,
    public_openapi_schema,
    sandbox_purchase,
)
from iat.buyer import IATAPIError, IATClient, IATTransportError, RetryPolicy
from iat.discovery import build_discovery_manifest
from iat.sandbox import (
    BuyerSandbox,
    SandboxConflictError,
    SandboxNotFoundError,
    SandboxValidationError,
)


@pytest.fixture()
def sandbox():
    return BuyerSandbox(signing_key=b"test-signing-key", max_records=20)


def _request(**overrides):
    payload = {
        "service": "web_research",
        "goal": "Compare agent payment protocols",
        "max_price": "2.00",
        "strategy": "quality",
        "required_capabilities": ["source_verification"],
    }
    payload.update(overrides)
    return payload


def test_discovery_manifest_is_defensively_copied():
    first = build_discovery_manifest()
    first["protocol"]["name"] = "mutated"

    second = build_discovery_manifest()

    assert second["protocol"]["name"] == "IAT Protocol"
    assert second["sandbox"]["funds_required"] is False
    assert second["intelligence"]["simulate_decision"] == "/intelligence/v1/decisions/simulate"


def test_sandbox_preview_enforces_budget_and_capabilities(sandbox):
    preview = sandbox.preview(**_request())

    assert preview["status"] == "offer_selected"
    assert preview["selected_offer"]["offer_id"] == "sandbox-research-deep"
    assert float(preview["selected_offer"]["price"]) <= 2.0
    assert "source_verification" in preview["selected_offer"]["capabilities"]


def test_sandbox_purchase_is_idempotent_and_moves_no_funds(sandbox):
    first = sandbox.purchase(**_request(), idempotency_key="purchase-key-0001")
    second = sandbox.purchase(**_request(), idempotency_key="purchase-key-0001")

    assert first["order_id"] == second["order_id"]
    assert first["status"] == "completed"
    assert first["sandbox"] is True
    assert first["production_side_effects"] is False
    assert first["funds_moved"] is False
    assert first["receipt"]["scope"] == "sandbox_only"


def test_sandbox_rejects_conflicting_idempotency_key(sandbox):
    sandbox.purchase(**_request(), idempotency_key="purchase-key-0002")

    with pytest.raises(SandboxConflictError):
        sandbox.purchase(
            **_request(goal="A different request"),
            idempotency_key="purchase-key-0002",
        )


@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity", "1000001"])
def test_sandbox_rejects_unsafe_budgets(sandbox, value):
    with pytest.raises(SandboxValidationError):
        sandbox.preview(**_request(max_price=value))


def test_sandbox_returns_no_offer_instead_of_ignoring_constraints(sandbox):
    preview = sandbox.preview(
        **_request(max_price="0.10", required_capabilities=["source_verification"])
    )

    assert preview["status"] == "no_eligible_offer"
    assert preview["selected_offer"] is None


def test_sandbox_feedback_is_idempotent_and_learning_is_bounded(sandbox):
    order = sandbox.purchase(**_request(), idempotency_key="purchase-key-0003")

    first = sandbox.record_feedback(
        order["order_id"],
        outcome="negative",
        feedback_key="feedback-key-0001",
    )
    duplicate = sandbox.record_feedback(
        order["order_id"],
        outcome="negative",
        feedback_key="feedback-key-0001",
    )
    for index in range(30):
        result = sandbox.record_feedback(
            order["order_id"],
            outcome="negative",
            feedback_key=f"feedback-key-{index + 1000}",
        )

    assert first["status"] == "recorded"
    assert duplicate["status"] == "already_recorded"
    assert result["adaptation"]["score_adjustment"] == -5.0
    assert result["adaptation"]["production_effect"] is False
    assert result["adaptation"]["policy_mutation_allowed"] is False


def test_sandbox_feedback_volume_is_bounded(sandbox):
    order = sandbox.purchase(**_request(), idempotency_key="purchase-key-0004")
    for index in range(64):
        sandbox.record_feedback(
            order["order_id"],
            outcome="positive",
            feedback_key=f"bounded-feedback-{index:04d}",
        )

    with pytest.raises(SandboxValidationError, match="feedback_limit_reached"):
        sandbox.record_feedback(
            order["order_id"],
            outcome="positive",
            feedback_key="bounded-feedback-overflow",
        )


def test_sandbox_unknown_order_fails_closed(sandbox):
    with pytest.raises(SandboxNotFoundError):
        sandbox.get_order("sandbox_ord_unknown")


def test_public_openapi_advertises_discovery_and_required_idempotency():
    schema = public_openapi_schema()
    purchase = schema["paths"]["/sandbox/v1/purchase"]["post"]
    idempotency = next(
        parameter
        for parameter in purchase["parameters"]
        if parameter["name"] == "Idempotency-Key"
    )

    assert "/.well-known/iat.json" in schema["paths"]
    assert idempotency["required"] is True


def test_public_sandbox_rejects_extra_fields():
    with pytest.raises(ValidationError):
        SandboxPreviewRequest(**{**_request(), "production_override": True})


def test_public_sandbox_purchase_end_to_end():
    response = sandbox_purchase(
        SandboxPreviewRequest(**_request()),
        idempotency_key="api-purchase-key-0001",
    )

    assert response["funds_moved"] is False


def test_client_discovery_uses_machine_manifest():
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"protocol": {"name": "IAT Protocol"}}
    session = Mock()
    session.request.return_value = response
    client = IATClient("https://iat.test", session=session)

    result = client.discover()

    assert result["protocol"]["name"] == "IAT Protocol"
    assert session.request.call_args.args[:2] == ("GET", "https://iat.test/.well-known/iat.json")


def test_client_can_request_explainable_decision_simulation():
    response = Mock(status_code=200)
    response.json.return_value = {"status": "selected", "production_side_effects": False}
    session = Mock()
    session.request.return_value = response
    client = IATClient("https://iat.test", session=session)

    result = client.simulate_decision(
        [{
            "candidate_id": "seller-a",
            "price": 2,
            "quality": 90,
            "trust": 95,
            "reliability": 94,
            "latency_score": 80,
            "capabilities": ["search"],
        }],
        policy={"strategy": "safest", "maximum_price": 5},
    )

    assert result["production_side_effects"] is False
    assert session.request.call_args.args[:2] == (
        "POST",
        "https://iat.test/intelligence/v1/decisions/simulate",
    )


def test_client_retries_idempotent_sandbox_purchase():
    unavailable = Mock(status_code=503)
    unavailable.json.return_value = {"detail": "unavailable"}
    completed = Mock(status_code=200)
    completed.json.return_value = {"status": "completed", "funds_moved": False}
    session = Mock()
    session.request.side_effect = [unavailable, completed]
    client = IATClient(
        "https://iat.test",
        session=session,
        retry_policy=RetryPolicy(attempts=2, initial_delay=0, maximum_delay=0),
    )

    result = client.sandbox_buy(
        "risk_report",
        goal="Assess BTC risk",
        max_price="2.00",
        idempotency_key="client-key-0001",
    )

    assert result["status"] == "completed"
    assert session.request.call_count == 2


def test_client_does_not_retry_non_idempotent_production_order():
    session = Mock()
    session.request.side_effect = requests.ConnectionError("offline")
    client = IATClient(
        "https://iat.test",
        session=session,
        retry_policy=RetryPolicy(attempts=3, initial_delay=0, maximum_delay=0),
    )

    with pytest.raises(IATTransportError):
        client.create_order("risk_report")

    assert session.request.call_count == 1


def test_client_exposes_machine_readable_api_errors():
    response = Mock(status_code=409)
    response.json.return_value = {"detail": "idempotency_conflict"}
    session = Mock()
    session.request.return_value = response
    client = IATClient("https://iat.test", session=session)

    with pytest.raises(IATAPIError) as error:
        client.sandbox_buy(
            "risk_report",
            goal="Assess BTC risk",
            max_price="2.00",
            idempotency_key="client-key-0002",
        )

    assert error.value.status_code == 409
    assert error.value.as_dict()["code"] == "api_request_failed"
