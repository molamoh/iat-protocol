from unittest.mock import Mock

import pytest

from iat.api.public import public_openapi_schema
from iat.security.network import UnsafeNetworkTarget, validate_public_runtime_url
from iat.seller import IATSellerClient
from iat.seller_growth import (
    SellerGrowthValidationError,
    build_commission_policy,
    build_integration_contract,
    build_seller_discovery,
    estimate_seller_economics,
    evaluate_seller_readiness,
)


def _ready_profile():
    return {
        "seller_name": "Autonomous Research Supplier",
        "wallet": "wallet-public-key",
        "support_email": "support@example.test",
        "service": "web_research",
        "unit_price": "2.00",
        "currency": "IAT",
        "refund_policy": "Refund when no verified result is delivered.",
        "runtime_adapter": "http",
        "runtime_url": "https://supplier.example.test/execute",
        "health_endpoint": "https://supplier.example.test/health",
        "capabilities": ["web_search", "source_verification"],
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "timeout_seconds": 60,
        "capacity_per_day": 1_000,
        "idempotency_supported": True,
        "data_policy": "No training and deletion after execution.",
        "secret_handling": "Secrets are never logged.",
        "incident_contact": "security@example.test",
        "evidence_types": ["source_citations", "execution_digest"],
    }


def test_seller_discovery_exposes_complete_journey_and_commission(monkeypatch):
    monkeypatch.setenv("IAT_PROTOCOL_COMMISSION_RATE", "0.075")

    discovery = build_seller_discovery()

    assert [step["step"] for step in discovery["journey"]] == [
        "evaluate",
        "register",
        "connect_runtime",
        "publish",
        "operate",
    ]
    assert discovery["commercial_policy"]["production_rate"] == "0.075000"
    assert "atomic_commission_and_seller_payout" in discovery["differentiators"]


def test_commission_policy_clamps_misconfiguration(monkeypatch):
    monkeypatch.setenv("IAT_PROTOCOL_COMMISSION_RATE", "4.2")

    policy = build_commission_policy()

    assert policy["production_rate"] == "0.500000"
    assert policy["charged_on_failed_orders"] is False


def test_economics_estimator_is_transparent_and_exact(monkeypatch):
    monkeypatch.setenv("IAT_PROTOCOL_COMMISSION_RATE", "0.10")

    result = estimate_seller_economics(
        unit_price="2.00",
        monthly_completed_orders=100,
        refund_rate="0.05",
        variable_cost_per_order="0.25",
    )

    projection = result["monthly_projection"]
    assert projection["listed_gross"] == "200.000000"
    assert projection["refunds"] == "10.000000"
    assert projection["protocol_commission"] == "19.000000"
    assert projection["seller_payout"] == "171.000000"
    assert projection["seller_contribution_after_commission"] == "146.000000"
    assert result["simulation_only"] is True


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("unit_price", "NaN", "unit_price_out_of_range"),
        ("monthly_completed_orders", 1.5, "monthly_completed_orders_must_be_integer"),
        ("refund_rate", "1.1", "refund_rate_out_of_range"),
    ],
)
def test_economics_estimator_rejects_invalid_inputs(field, value, error):
    payload = {
        "unit_price": "1",
        "monthly_completed_orders": 10,
        "refund_rate": "0",
    }
    payload[field] = value

    with pytest.raises(SellerGrowthValidationError, match=error):
        estimate_seller_economics(**payload)


def test_readiness_returns_actionable_machine_plan():
    profile = _ready_profile()
    profile["runtime_url"] = "http://127.0.0.1/internal"
    profile["wallet"] = None

    result = evaluate_seller_readiness(profile)

    readiness = result["readiness"]
    assert readiness["level"] == "not_ready"
    assert "wallet_required" in readiness["blockers"]
    assert "https_runtime_required" in readiness["blockers"]
    assert readiness["can_become_buyer_routable"] is False
    assert result["policy"]["assessment_creates_account"] is False


def test_complete_profile_is_integration_ready():
    result = evaluate_seller_readiness(_ready_profile())

    assert result["readiness"]["level"] == "integration_ready"
    assert result["readiness"]["score"] == 100
    assert result["next_actions"] == [{"priority": "next", "action": "register_seller"}]


def test_integration_contract_enforces_seller_isolation():
    contract = build_integration_contract("http")

    assert "no_direct_buyer_contact" in contract["required_invariants"]
    assert contract["security"]["buyer_data_minimized"] is True
    assert contract["security"]["https_required_in_production"] is True


def test_public_openapi_contains_seller_evaluation_routes():
    schema = public_openapi_schema()

    assert "/seller/v1/discovery" in schema["paths"]
    assert "/seller/v1/readiness" in schema["paths"]
    assert "/seller/v1/economics/estimate" in schema["paths"]
    assert "/seller/v1/integration-contract" in schema["paths"]


def test_seller_client_uses_dedicated_header_for_authenticated_routes():
    response = Mock(status_code=200)
    response.json.return_value = {"status": "ok"}
    session = Mock()
    session.request.return_value = response
    client = IATSellerClient(
        "https://iat.test",
        seller_api_key="seller-secret",
        session=session,
    )

    result = client.dashboard()

    assert result["status"] == "ok"
    headers = session.request.call_args.kwargs["headers"]
    assert headers["x-seller-api-key"] == "seller-secret"
    assert "x-api-key" not in headers


def test_seller_client_never_puts_key_in_register_agent_body():
    response = Mock(status_code=200)
    response.json.return_value = {"status": "ok"}
    session = Mock()
    session.request.return_value = response
    client = IATSellerClient(
        "https://iat.test",
        seller_api_key="seller-secret",
        session=session,
    )

    client.register_agent(
        agent_id="research-agent",
        service="web_research",
        runtime_adapter="python",
        python_plugin="research",
    )

    assert "api_key" not in session.request.call_args.kwargs["json"]
    assert session.request.call_args.kwargs["headers"]["x-seller-api-key"] == "seller-secret"


def test_network_target_rejects_credentials_and_private_addresses(monkeypatch):
    with pytest.raises(UnsafeNetworkTarget, match="credentials"):
        validate_public_runtime_url("https://user:password@example.test/runtime")

    monkeypatch.setattr(
        "iat.security.network.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("10.0.0.8", 443))],
    )
    with pytest.raises(UnsafeNetworkTarget, match="must_be_public"):
        validate_public_runtime_url("https://supplier.example.test/runtime")


def test_network_target_accepts_only_globally_routable_resolution(monkeypatch):
    monkeypatch.setattr(
        "iat.security.network.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )

    result = validate_public_runtime_url("https://supplier.example.test/runtime")

    assert result["public"] is True
    assert result["resolved_addresses"] == ["8.8.8.8"]
