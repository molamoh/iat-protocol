from solders.keypair import Keypair

from iat.api import agent_b_api
from iat.api import db


def test_seller_registration_rejects_non_solana_wallet(monkeypatch):
    monkeypatch.setattr(agent_b_api, "init_db", lambda: None)

    result = agent_b_api.seller_register(agent_b_api.SellerRegisterRequest(
        seller_name="Invalid wallet seller",
        wallet="wallet_metadata_test_001",
        email="seller@example.com",
    ))

    assert result == {"status": "error", "message": "seller_wallet_invalid"}


def test_seller_approval_requires_verified_email_and_wallet(monkeypatch):
    monkeypatch.setattr(db, "get_seller_db", lambda _seller_id: {
        "seller_id": "seller_unverified",
        "seller_status": "pending",
        "wallet": str(Keypair().pubkey()),
        "email_verified": 0,
        "wallet_verified": 0,
    })

    result = db.approve_seller_db("seller_unverified", override_terminal=True)

    assert result["status"] == "error"
    assert result["message"] == "seller_identity_verification_required"
    assert result["email_verified"] is False
    assert result["wallet_verified"] is False
    assert result["wallet_valid"] is True


def test_create_order_rejects_unresolved_seller_payment_wallet(monkeypatch):
    monkeypatch.setattr(agent_b_api, "get_order_db", lambda _order_id: None)
    monkeypatch.setattr(agent_b_api, "is_buyer_banned_db", lambda _wallet: False)
    monkeypatch.setattr(agent_b_api, "select_best_seller", lambda *_args, **_kwargs: {
        "seller_id": "seller_with_logical_wallet",
        "seller_wallet": "wallet_metadata_test_001",
        "price": 2.0,
        "reputation": 0.9,
        "available": True,
        "url": "",
        "source": "test",
    })
    monkeypatch.delenv("IAT_WALLET_METADATA_TEST_001_PAYMENT_WALLET", raising=False)

    result = agent_b_api.create_order(
        agent_b_api.OrderRequest(
            service="web_research",
            query="Bounded cited report",
            buyer_wallet=str(Keypair().pubkey()),
            locked_agent_id="seller_with_logical_wallet",
            locked_unit_price="2.0",
            locked_order_id="bio_invalid_wallet_test",
        ),
        internal_call=True,
    )

    assert result["status"] == "rejected"
    assert result["reason"] == "seller_payment_wallet_unresolved"
    assert result["wallet_resolution_reason"] == "logical_wallet_mapping_not_configured"


def test_create_order_freezes_resolved_seller_payment_wallet(monkeypatch):
    logical_wallet = "seller_runtime_wallet"
    payment_wallet = str(Keypair().pubkey())
    captured = {}
    monkeypatch.setattr(agent_b_api, "get_order_db", lambda _order_id: None)
    monkeypatch.setattr(agent_b_api, "is_buyer_banned_db", lambda _wallet: False)
    monkeypatch.setattr(agent_b_api, "select_best_seller", lambda *_args, **_kwargs: {
        "seller_id": "seller_with_mapping",
        "seller_wallet": logical_wallet,
        "price": 2.0,
        "reputation": 0.9,
        "available": True,
        "url": "",
        "source": "test",
    })
    monkeypatch.setenv("IAT_SELLER_RUNTIME_PAYMENT_WALLET", payment_wallet)
    monkeypatch.setattr(
        agent_b_api,
        "create_order_db",
        lambda order_id, order: captured.update(order_id=order_id, order=order),
    )

    result = agent_b_api.create_order(
        agent_b_api.OrderRequest(
            service="web_research",
            query="Bounded cited report",
            buyer_wallet=str(Keypair().pubkey()),
            locked_agent_id="seller_with_mapping",
            locked_unit_price="2.0",
            locked_order_id="bio_resolved_wallet_test",
        ),
        internal_call=True,
    )

    assert result["actual_agent_wallet"] == payment_wallet
    assert captured["order"]["actual_agent_wallet"] == payment_wallet
