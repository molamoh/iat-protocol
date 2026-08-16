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
