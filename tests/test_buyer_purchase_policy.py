from pathlib import Path

import pytest
from solders.keypair import Keypair

from iat import buyer_identity
from iat.api import db


@pytest.fixture()
def buyer_policy_database(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "buyer-policy.sqlite")
    monkeypatch.setattr(db, "USE_POSTGRES", False)
    buyer_identity.init_wallet_identity_db()
    return str(Keypair().pubkey())


def test_autonomous_spend_requires_explicit_enabled_policy(buyer_policy_database):
    with pytest.raises(buyer_identity.WalletIdentityError, match="autonomous_purchase_policy_required"):
        buyer_identity.authorize_buyer_spend(
            buyer_policy_database,
            quote_id="quote_missing_policy",
            input_asset="USDC",
            amount_minor=100,
            service="web_research",
            expires_at=200,
            now=100,
        )


def test_policy_enforces_service_order_and_daily_limits(buyer_policy_database):
    wallet = buyer_policy_database
    policy = buyer_identity.save_buyer_purchase_policy(
        wallet,
        enabled=True,
        input_asset="USDC",
        max_per_order_minor=600,
        daily_limit_minor=1_000,
        allowed_services=["web_research"],
        now=100,
    )
    assert policy["enabled"] is True
    assert policy["allowed_services"] == ["web_research"]

    first = buyer_identity.authorize_buyer_spend(
        wallet,
        quote_id="quote_1",
        input_asset="USDC",
        amount_minor=600,
        service="web_research",
        expires_at=300,
        now=120,
    )
    replay = buyer_identity.authorize_buyer_spend(
        wallet,
        quote_id="quote_1",
        input_asset="USDC",
        amount_minor=600,
        service="web_research",
        expires_at=300,
        now=121,
    )
    assert first["status"] == "reserved"
    assert replay["status"] == "already_reserved"

    with pytest.raises(buyer_identity.WalletIdentityError, match="purchase_policy_order_limit_exceeded"):
        buyer_identity.authorize_buyer_spend(
            wallet,
            quote_id="quote_too_large",
            input_asset="USDC",
            amount_minor=601,
            service="web_research",
            expires_at=300,
            now=122,
        )
    with pytest.raises(buyer_identity.WalletIdentityError, match="purchase_policy_service_blocked"):
        buyer_identity.authorize_buyer_spend(
            wallet,
            quote_id="quote_wrong_service",
            input_asset="USDC",
            amount_minor=100,
            service="code_execution",
            expires_at=300,
            now=123,
        )
    with pytest.raises(buyer_identity.WalletIdentityError, match="purchase_policy_daily_limit_exceeded"):
        buyer_identity.authorize_buyer_spend(
            wallet,
            quote_id="quote_daily_limit",
            input_asset="USDC",
            amount_minor=500,
            service="web_research",
            expires_at=300,
            now=124,
        )


def test_expired_reservation_releases_daily_budget(buyer_policy_database):
    wallet = buyer_policy_database
    buyer_identity.save_buyer_purchase_policy(
        wallet,
        enabled=True,
        input_asset="USDC",
        max_per_order_minor=700,
        daily_limit_minor=700,
        now=100,
    )
    buyer_identity.authorize_buyer_spend(
        wallet,
        quote_id="quote_expiring",
        input_asset="USDC",
        amount_minor=700,
        expires_at=150,
        now=120,
    )
    replacement = buyer_identity.authorize_buyer_spend(
        wallet,
        quote_id="quote_replacement",
        input_asset="USDC",
        amount_minor=700,
        expires_at=300,
        now=151,
    )
    assert replacement["daily_reserved_minor"] == 700


def test_submitted_spend_remains_in_daily_budget_after_quote_expiry(buyer_policy_database):
    wallet = buyer_policy_database
    buyer_identity.save_buyer_purchase_policy(
        wallet,
        enabled=True,
        input_asset="USDC",
        max_per_order_minor=700,
        daily_limit_minor=700,
        now=100,
    )
    buyer_identity.authorize_buyer_spend(
        wallet,
        quote_id="quote_paid",
        input_asset="USDC",
        amount_minor=700,
        expires_at=150,
        now=120,
    )
    assert buyer_identity.update_buyer_spend_reservation("quote_paid", "confirmed", now=130)
    with pytest.raises(buyer_identity.WalletIdentityError, match="purchase_policy_daily_limit_exceeded"):
        buyer_identity.authorize_buyer_spend(
            wallet,
            quote_id="quote_after_payment",
            input_asset="USDC",
            amount_minor=1,
            expires_at=300,
            now=151,
        )


def test_intent_decision_is_wallet_bound_idempotent_and_tamper_evident(buyer_policy_database):
    wallet = buyer_policy_database
    request = {
        "service": "web_research",
        "goal": "Produce a cited market report",
        "maximum_price": 3,
        "strategy": "safest",
        "required_capabilities": ["source_verification"],
    }
    selection = {"status": "selected", "selected": {"candidate_id": "sa_1"}}
    selected = {
        "seller_agent_id": "sa_1",
        "agent_id": "agent_1",
        "catalog_item_id": "catalog_1",
        "unit_price": 2,
        "currency": "IAT",
    }
    created = buyer_identity.save_buyer_intent_decision(
        wallet,
        idempotency_key="intent-key-0001",
        request_payload=request,
        selection=selection,
        selected_record=selected,
        now=100,
    )
    replay = buyer_identity.save_buyer_intent_decision(
        wallet,
        idempotency_key="intent-key-0001",
        request_payload=request,
        selection={"status": "selected", "selected": {"candidate_id": "attacker"}},
        selected_record={**selected, "seller_agent_id": "attacker"},
        now=101,
    )
    assert created["intent_decision_id"] == replay["intent_decision_id"]
    assert replay["selection"] == selection
    assert replay["selected_seller_agent_id"] == "sa_1"
    assert replay["idempotent_replay"] is True
    assert created["expires_at"] == 220

    with pytest.raises(buyer_identity.WalletIdentityError, match="intent_idempotency_conflict"):
        buyer_identity.save_buyer_intent_decision(
            wallet,
            idempotency_key="intent-key-0001",
            request_payload={**request, "maximum_price": 30},
            selection=selection,
            selected_record=selected,
            now=102,
        )


def test_same_intent_key_is_isolated_between_wallets(buyer_policy_database):
    request = {"service": "web_research", "goal": "A sufficiently long goal"}
    first = buyer_identity.save_buyer_intent_decision(
        buyer_policy_database,
        idempotency_key="shared-intent-key",
        request_payload=request,
        selection={"status": "no_eligible_candidate"},
        selected_record=None,
        now=100,
    )
    second = buyer_identity.save_buyer_intent_decision(
        str(Keypair().pubkey()),
        idempotency_key="shared-intent-key",
        request_payload=request,
        selection={"status": "no_eligible_candidate"},
        selected_record=None,
        now=100,
    )
    assert first["intent_decision_id"] != second["intent_decision_id"]


def test_intent_decision_claim_is_single_use_and_order_replay_is_idempotent(buyer_policy_database):
    wallet = buyer_policy_database
    created = buyer_identity.save_buyer_intent_decision(
        wallet,
        idempotency_key="claim-intent-key",
        request_payload={"service": "web_research", "goal": "A sufficiently long goal"},
        selection={"status": "selected"},
        selected_record={
            "seller_agent_id": "sa_1",
            "agent_id": "agent_1",
            "catalog_item_id": "catalog_1",
            "unit_price": 2,
            "currency": "IAT",
        },
        now=100,
    )
    claimed = buyer_identity.claim_buyer_intent_decision(
        wallet, created["intent_decision_id"], now=110
    )
    assert claimed["selected_agent_id"] == "agent_1"
    with pytest.raises(buyer_identity.WalletIdentityError, match="intent_decision_commit_in_progress"):
        buyer_identity.claim_buyer_intent_decision(
            wallet, created["intent_decision_id"], now=111
        )
    assert buyer_identity.finalize_buyer_intent_decision(
        wallet, created["intent_decision_id"], "order_1"
    )
    replay = buyer_identity.claim_buyer_intent_decision(
        wallet, created["intent_decision_id"], now=112
    )
    assert replay["order_id"] == "order_1"
    assert replay["idempotent_replay"] is True


def test_expired_or_foreign_intent_decision_cannot_be_claimed(buyer_policy_database):
    wallet = buyer_policy_database
    created = buyer_identity.save_buyer_intent_decision(
        wallet,
        idempotency_key="expiry-intent-key",
        request_payload={"service": "web_research", "goal": "A sufficiently long goal"},
        selection={"status": "selected"},
        selected_record=None,
        now=100,
        ttl_seconds=30,
    )
    with pytest.raises(buyer_identity.WalletIdentityError, match="intent_decision_not_found"):
        buyer_identity.claim_buyer_intent_decision(
            str(Keypair().pubkey()), created["intent_decision_id"], now=110
        )
    with pytest.raises(buyer_identity.WalletIdentityError, match="intent_decision_expired"):
        buyer_identity.claim_buyer_intent_decision(
            wallet, created["intent_decision_id"], now=130
        )


def test_committed_intent_decision_remains_readable_without_mutation(buyer_policy_database):
    wallet = buyer_policy_database
    created = buyer_identity.save_buyer_intent_decision(
        wallet,
        idempotency_key="read-committed-intent",
        request_payload={"service": "web_research", "goal": "A sufficiently long goal"},
        selection={"status": "selected"},
        selected_record=None,
        now=100,
        ttl_seconds=30,
    )
    buyer_identity.claim_buyer_intent_decision(wallet, created["intent_decision_id"], now=110)
    assert buyer_identity.finalize_buyer_intent_decision(
        wallet, created["intent_decision_id"], "order_1"
    )

    decision = buyer_identity.get_buyer_intent_decision(
        wallet, created["intent_decision_id"], now=200
    )
    replay = buyer_identity.get_buyer_intent_decision(
        wallet, created["intent_decision_id"], now=201
    )
    assert decision["order_id"] == "order_1"
    assert decision["request"]["service"] == "web_research"
    assert replay["consumed_at"] == decision["consumed_at"]
    with pytest.raises(buyer_identity.WalletIdentityError, match="intent_decision_not_found"):
        buyer_identity.get_buyer_intent_decision(
            str(Keypair().pubkey()), created["intent_decision_id"], now=200
        )


def test_uncommitted_expired_intent_decision_cannot_be_read(buyer_policy_database):
    created = buyer_identity.save_buyer_intent_decision(
        buyer_policy_database,
        idempotency_key="read-expired-intent",
        request_payload={"service": "web_research", "goal": "A sufficiently long goal"},
        selection={"status": "selected"},
        selected_record=None,
        now=100,
        ttl_seconds=30,
    )
    with pytest.raises(buyer_identity.WalletIdentityError, match="intent_decision_expired"):
        buyer_identity.get_buyer_intent_decision(
            buyer_policy_database, created["intent_decision_id"], now=130
        )
