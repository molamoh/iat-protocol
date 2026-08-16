import base64
import json
import hmac
import hashlib

import pytest
from fastapi import HTTPException, Response
from solders.keypair import Keypair
from solders.hash import Hash
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from iat.api import checkout_api, db
from iat import checkout_compensation, checkout_delivery, checkout_receipt
from iat.checkout import RaydiumSnapshot


NOW = 2_000_000_000
BUYER = "Buyer111111111111111111111111111111111"
SECRET = "buyer-secret-long-enough-123"


@pytest.fixture()
def checkout_database(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "checkout.sqlite")
    monkeypatch.setattr(db, "USE_POSTGRES", False)
    monkeypatch.setattr(checkout_api.time, "time", lambda: NOW)
    monkeypatch.setenv("IAT_TREASURY_CHECKOUT_ENABLED", "true")
    monkeypatch.setenv("IAT_RAYDIUM_CHECKOUT_ENABLED", "true")
    monkeypatch.setenv("IAT_TREASURY_INVENTORY_IAT", "500")
    monkeypatch.setenv("IAT_REFERENCE_PRICE_USD", "0.25")
    monkeypatch.setenv(
        "IAT_TREASURY_PROGRAM_ID",
        "IATCheckout11111111111111111111111111111",
    )
    monkeypatch.setenv(
        "IAT_TREASURY_IAT_VAULT",
        "Treasury1111111111111111111111111111111",
    )
    monkeypatch.setenv(
        "IAT_CHECKOUT_ASSETS_JSON",
        json.dumps(
            {
                "USDC": {
                    "mint": "USDC1111111111111111111111111111111111",
                    "decimals": 6,
                    "usd_price": "1",
                    "oracle": "pyth",
                    "observed_at": NOW - 2,
                }
            }
        ),
    )
    db.init_db()
    checkout_api.init_checkout_db()
    db.create_order_db(
        "ord-api",
        {
            "service": "research",
            "price": 10,
            "seller_id": "seller-1",
            "seller_wallet": "seller-wallet",
            "buyer_secret": SECRET,
            "buyer_wallet": BUYER,
            "created_at": NOW - 10,
            "updated_at": NOW - 10,
            "status": "created",
        },
    )


def request(**overrides):
    values = {
        "order_id": "ord-api",
        "buyer_wallet": BUYER,
        "buyer_secret": SECRET,
        "input_asset": "USDC",
    }
    values.update(overrides)
    return checkout_api.UniversalQuoteRequest(**values)


def _create_inbox_order(order_id: str, wallet: str, secret: str):
    db.create_order_db(
        order_id,
        {
            "service": "research",
            "price": 1,
            "seller_id": "seller-1",
            "seller_wallet": "seller-wallet",
            "buyer_secret": secret,
            "buyer_wallet": wallet,
            "created_at": NOW - 10,
            "updated_at": NOW - 10,
            "status": "created",
        },
    )


def test_buyer_inbox_is_isolated_paginated_and_excludes_canaries(
    checkout_database, monkeypatch
):
    monkeypatch.setenv("IAT_PUBLIC_SITE_URL", "https://iatprotocol.com")
    first_quote = checkout_api.create_universal_quote(
        request(), idempotency_key="inbox-list-first-0001"
    )
    checkout_receipt.configure_delivery_receipt(
        quote_id=first_quote["quote_id"],
        order_id="ord-api",
        channel="api_pull",
        destination=None,
        now=100,
    )
    _create_inbox_order("ord-inbox-second", BUYER, SECRET)
    second_quote = checkout_api.create_universal_quote(
        request(order_id="ord-inbox-second"),
        idempotency_key="inbox-list-second-0001",
    )
    checkout_receipt.configure_delivery_receipt(
        quote_id=second_quote["quote_id"],
        order_id="ord-inbox-second",
        channel="api_pull",
        destination=None,
        now=200,
    )
    checkout_receipt.publish_delivery_payload(
        quote_id=second_quote["quote_id"],
        order_id="ord-inbox-second",
        payload={"status": "success", "summary": "Agent-native result"},
        now=201,
    )
    other_wallet = "Other111111111111111111111111111111111"
    other_secret = "other-secret-long-enough-456"
    _create_inbox_order("ord-inbox-other", other_wallet, other_secret)
    other_quote = checkout_api.create_universal_quote(
        request(
            order_id="ord-inbox-other",
            buyer_wallet=other_wallet,
            buyer_secret=other_secret,
        ),
        idempotency_key="inbox-list-other-0001",
    )
    checkout_receipt.configure_delivery_receipt(
        quote_id=other_quote["quote_id"],
        order_id="ord-inbox-other",
        channel="api_pull",
        destination=None,
        now=300,
    )
    checkout_receipt.create_native_inbox_canary(now=400)

    first_page = checkout_api.get_buyer_delivery_inbox(
        Response(), buyer_wallet=BUYER, buyer_secret=SECRET, limit=1
    )
    second_page = checkout_api.get_buyer_delivery_inbox(
        Response(),
        buyer_wallet=BUYER,
        buyer_secret=SECRET,
        cursor=first_page["next_cursor"],
        limit=1,
    )

    assert first_page["count"] == 1
    assert first_page["items"][0]["order_id"] == "ord-inbox-second"
    assert first_page["items"][0]["delivery_url"].startswith(
        "https://iatprotocol.com/delivery/#receipt=cdr_"
    )
    assert first_page["next_cursor"]
    assert second_page["count"] == 1
    assert second_page["items"][0]["order_id"] == "ord-api"
    assert second_page["next_cursor"] is None
    assert all("other" not in item["order_id"] for item in first_page["items"] + second_page["items"])
    assert all("canary" not in item["order_id"] for item in first_page["items"] + second_page["items"])

    opened = checkout_api.get_authenticated_buyer_inbox_item(
        second_quote["quote_id"],
        Response(),
        buyer_wallet=BUYER,
        buyer_secret=SECRET,
    )
    assert opened["inbox"]["result"]["summary"] == "Agent-native result"
    assert "receipt_id" not in opened["inbox"]
    assert "receipt_token" not in opened["final_receipt"]

    with pytest.raises(HTTPException) as rejected:
        checkout_api.get_buyer_delivery_inbox(
            Response(), buyer_wallet=BUYER, buyer_secret="wrong-secret-long-enough"
        )
    assert rejected.value.status_code == 403


def test_buyer_inbox_rejects_invalid_cursor(checkout_database):
    with pytest.raises(HTTPException) as rejected:
        checkout_api.get_buyer_delivery_inbox(
            Response(),
            buyer_wallet=BUYER,
            buyer_secret=SECRET,
            cursor="not-base64!",
        )
    assert rejected.value.status_code == 422


def test_wallet_signature_session_opens_all_wallet_receipts_without_order_secret(
    checkout_database, monkeypatch
):
    keypair = Keypair()
    wallet = str(keypair.pubkey())
    _create_inbox_order("ord-wallet-session", wallet, "unknown-to-client-secret")
    quote = checkout_api.create_universal_quote(
        request(
            order_id="ord-wallet-session",
            buyer_wallet=wallet,
            buyer_secret="unknown-to-client-secret",
        ),
        idempotency_key="wallet-session-inbox-0001",
    )
    checkout_receipt.configure_delivery_receipt(
        quote_id=quote["quote_id"],
        order_id="ord-wallet-session",
        channel="api_pull",
        destination=None,
        now=100,
    )
    checkout_receipt.publish_delivery_payload(
        quote_id=quote["quote_id"],
        order_id="ord-wallet-session",
        payload={"status": "success", "summary": "Wallet-owned result"},
        now=101,
    )

    challenge = checkout_api.issue_wallet_auth_challenge(
        checkout_api.WalletChallengeRequest(wallet=wallet), Response()
    )
    signature = str(keypair.sign_message(challenge["message"].encode()))
    session = checkout_api.create_wallet_auth_session(
        checkout_api.WalletSessionRequest(
            challenge_id=challenge["challenge_id"], signature=signature
        ),
        Response(),
    )
    authorization = f"Bearer {session['access_token']}"
    listing = checkout_api.get_wallet_delivery_inbox(
        Response(), authorization=authorization
    )
    opened = checkout_api.get_wallet_inbox_item(
        quote["quote_id"], Response(), authorization=authorization
    )

    assert listing["wallet"] == wallet
    assert [item["order_id"] for item in listing["items"]] == ["ord-wallet-session"]
    assert opened["inbox"]["result"]["summary"] == "Wallet-owned result"

    checkout_api.delete_wallet_auth_session(Response(), authorization=authorization)
    with pytest.raises(HTTPException) as rejected:
        checkout_api.get_wallet_delivery_inbox(
            Response(), authorization=authorization
        )
    assert rejected.value.status_code == 401


def test_wallet_session_cannot_open_another_wallet_receipt(checkout_database):
    keypair = Keypair()
    challenge = checkout_api.issue_wallet_auth_challenge(
        checkout_api.WalletChallengeRequest(wallet=str(keypair.pubkey())), Response()
    )
    session = checkout_api.create_wallet_auth_session(
        checkout_api.WalletSessionRequest(
            challenge_id=challenge["challenge_id"],
            signature=str(keypair.sign_message(challenge["message"].encode())),
        ),
        Response(),
    )
    quote = checkout_api.create_universal_quote(
        request(), idempotency_key="wallet-isolation-0001"
    )
    checkout_receipt.configure_delivery_receipt(
        quote_id=quote["quote_id"],
        order_id="ord-api",
        channel="api_pull",
        destination=None,
        now=100,
    )

    with pytest.raises(HTTPException) as rejected:
        checkout_api.get_wallet_inbox_item(
            quote["quote_id"],
            Response(),
            authorization=f"Bearer {session['access_token']}",
        )
    assert rejected.value.status_code == 404


def test_wallet_checkout_builds_authorized_transaction_and_requires_simulation(monkeypatch):
    fee_payer = Keypair().pubkey()
    program = Keypair().pubkey()
    observed = {}

    def rpc(method, params):
        if method == "getLatestBlockhash":
            return {"value": {"blockhash": str(Hash.default())}}
        observed["simulation"] = params
        return {"value": {"err": None, "unitsConsumed": 4321}}

    def authorize(**kwargs):
        observed["authorized"] = kwargs
        return {
            "transaction_base64": kwargs["transaction_base64"],
            "message_hash": "message-hash",
            "quote_authority": "authority",
        }

    monkeypatch.setattr(checkout_api, "_rpc_call", rpc)
    monkeypatch.setattr(checkout_api, "_authorize_with_quote_signer", authorize)
    prepared = {
        "expires_at": NOW + 120,
        "solana_instruction_plan": {
            "fee_payer": str(fee_payer),
            "execute": {
                "program_id": str(program),
                "data_base64": base64.b64encode(b"checkout").decode(),
                "accounts": [
                    {"address": str(fee_payer), "signer": True, "writable": True}
                ],
            },
        },
    }

    result = checkout_api._build_authorized_wallet_transaction("uq_wallet", prepared)

    decoded = VersionedTransaction.from_bytes(base64.b64decode(result["transaction_base64"]))
    assert str(decoded.message.account_keys[0]) == str(fee_payer)
    assert result["simulation"] == {"status": "succeeded", "units_consumed": 4321}
    assert observed["simulation"][1]["sigVerify"] is False


def test_wallet_checkout_fails_closed_when_simulation_fails(monkeypatch):
    fee_payer = Keypair().pubkey()
    monkeypatch.setattr(
        checkout_api,
        "_rpc_call",
        lambda method, params: (
            {"value": {"blockhash": str(Hash.default())}}
            if method == "getLatestBlockhash"
            else {"value": {"err": {"InstructionError": [0, "Custom"]}}}
        ),
    )
    monkeypatch.setattr(
        checkout_api,
        "_authorize_with_quote_signer",
        lambda **kwargs: {
            "transaction_base64": kwargs["transaction_base64"],
            "message_hash": "hash",
            "quote_authority": "authority",
        },
    )
    prepared = {
        "expires_at": NOW + 120,
        "solana_instruction_plan": {
            "fee_payer": str(fee_payer),
            "execute": {
                "program_id": str(Keypair().pubkey()),
                "data_base64": base64.b64encode(b"checkout").decode(),
                "accounts": [
                    {"address": str(fee_payer), "signer": True, "writable": True}
                ],
            },
        },
    }

    with pytest.raises(HTTPException) as rejected:
        checkout_api._build_authorized_wallet_transaction("uq_wallet", prepared)
    assert rejected.value.status_code == 409
    assert rejected.value.detail == "transaction_simulation_failed"


def test_wallet_checkout_reuses_matching_prepared_quote(monkeypatch):
    active = {
        "quote_id": "uq_existing",
        "order_id": "ord-api",
        "buyer_wallet": BUYER,
        "input_asset": "USDC",
        "state": "prepared",
    }
    prepared = {"solana_instruction_plan": {"program_id": "program"}}
    authorized = {"transaction_base64": "transaction", "simulation": {"status": "succeeded"}}

    monkeypatch.setattr(checkout_api, "_session_wallet", lambda authorization: (BUYER, {}))
    monkeypatch.setattr(
        checkout_api,
        "_wallet_owned_order",
        lambda order_id, wallet: {"buyer_secret": SECRET},
    )
    monkeypatch.setattr(
        checkout_api,
        "create_universal_quote",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            HTTPException(
                status_code=409,
                detail={
                    "code": "order_has_active_checkout_quote",
                    "quote_id": "uq_existing",
                },
            )
        ),
    )
    monkeypatch.setattr(checkout_api, "_get_quote", lambda quote_id: active)
    monkeypatch.setattr(
        checkout_api,
        "_public_quote",
        lambda row: {
            "quote_id": row["quote_id"],
            "expires_at": NOW + 120,
            "input": {"asset": "USDC"},
            "output": {"asset": "IAT"},
        },
    )
    monkeypatch.setattr(checkout_api, "prepare_universal_checkout", lambda *args: prepared)
    monkeypatch.setattr(
        checkout_api, "_build_authorized_wallet_transaction", lambda *args: authorized
    )

    result = checkout_api.prepare_wallet_checkout(
        "ord-api",
        checkout_api.WalletCheckoutRequest(input_asset="USDC"),
        Response(),
        authorization="Bearer session",
    )

    assert result["quote_id"] == "uq_existing"
    assert result["transaction_base64"] == "transaction"


def test_authenticated_intent_commit_locks_selected_agent_and_price(monkeypatch):
    from iat.api import agent_b_api

    decision = {
        "intent_decision_id": "bid_test_decision",
        "request": {
            "service": "web_research",
            "goal": "Produce a cited market report",
            "maximum_price": 3,
            "strategy": "safest",
            "required_capabilities": ["source_verification"],
        },
        "selected_agent_id": "agent_1",
        "selected_seller_agent_id": "sa_1",
        "selected_catalog_item_id": "catalog_1",
        "selected_unit_price": "2",
        "selected_currency": "IAT",
        "order_id": None,
    }
    candidate = {
        "agent_id": "agent_1",
        "seller_agent_id": "sa_1",
        "catalog_item_id": "catalog_1",
        "unit_price": "2",
        "registry_price": "2",
        "currency": "IAT",
    }
    observed = {}
    monkeypatch.setattr(checkout_api, "_session_wallet", lambda authorization: (BUYER, "token"))
    monkeypatch.setattr(checkout_api, "claim_buyer_intent_decision", lambda *args: decision)
    monkeypatch.setattr(checkout_api, "list_verified_marketplace_candidates_db", lambda *args, **kwargs: [candidate])
    monkeypatch.setattr(checkout_api, "finalize_buyer_intent_decision", lambda *args: True)

    def create(req, **kwargs):
        observed["request"] = req
        return {"order_id": "order_1", "seller_id": "agent_1", "price": 2}

    monkeypatch.setattr(agent_b_api, "create_order", create)
    result = checkout_api.commit_buyer_intent(
        checkout_api.BuyerIntentCommitRequest(intent_decision_id="bid_test_decision"),
        Response(),
        authorization="Bearer session",
    )
    assert result["order_id"] == "order_1"
    assert result["funds_reserved"] is False
    assert observed["request"].locked_agent_id == "agent_1"
    assert observed["request"].locked_unit_price == "2"
    assert observed["request"].locked_order_id.startswith("bio_")


def test_intent_checkout_prepare_enforces_autonomous_policy_and_never_submits(monkeypatch):
    observed = {}
    monkeypatch.setattr(checkout_api, "_session_wallet", lambda authorization: (BUYER, "token"))
    monkeypatch.setattr(
        checkout_api,
        "get_buyer_intent_decision",
        lambda wallet, decision_id: {"order_id": "order_1", "wallet": wallet},
    )

    def prepare(order_id, req, response, authorization=None):
        observed.update(
            order_id=order_id,
            autonomous=req.autonomous,
            input_asset=req.input_asset,
            authorization=authorization,
        )
        return {
            "status": "autonomous_checkout_policy_authorized",
            "order_id": order_id,
            "quote_id": "uq_1",
            "transaction_base64": "unsigned-for-buyer",
        }

    monkeypatch.setattr(checkout_api, "prepare_wallet_checkout", prepare)
    result = checkout_api.prepare_buyer_intent_checkout(
        checkout_api.BuyerIntentCheckoutPrepareRequest(
            intent_decision_id="bid_test_decision", input_asset="USDC"
        ),
        Response(),
        authorization="Bearer session",
    )

    assert observed == {
        "order_id": "order_1",
        "autonomous": True,
        "input_asset": "USDC",
        "authorization": "Bearer session",
    }
    assert result["policy_enforced"] is True
    assert result["buyer_signature_required"] is True
    assert result["transaction_submitted"] is False
    assert result["funds_moved"] is False


def test_intent_checkout_prepare_requires_committed_wallet_decision(monkeypatch):
    monkeypatch.setattr(checkout_api, "_session_wallet", lambda authorization: (BUYER, "token"))
    monkeypatch.setattr(
        checkout_api,
        "get_buyer_intent_decision",
        lambda wallet, decision_id: {"order_id": None, "wallet": wallet},
    )
    with pytest.raises(HTTPException) as rejected:
        checkout_api.prepare_buyer_intent_checkout(
            checkout_api.BuyerIntentCheckoutPrepareRequest(
                intent_decision_id="bid_test_decision"
            ),
            Response(),
            authorization="Bearer session",
        )
    assert rejected.value.status_code == 409
    assert rejected.value.detail == "intent_decision_not_committed"


def test_intent_checkout_submit_binds_quote_to_committed_order(monkeypatch):
    signature = str(Signature.default())
    observed = {}
    monkeypatch.setattr(checkout_api, "_session_wallet", lambda authorization: (BUYER, "token"))
    monkeypatch.setattr(
        checkout_api,
        "get_buyer_intent_decision",
        lambda wallet, decision_id: {"order_id": "order_1", "wallet": wallet},
    )
    monkeypatch.setattr(
        checkout_api,
        "_wallet_owned_quote",
        lambda quote_id, wallet: ({"quote_id": quote_id, "order_id": "order_1"}, {}),
    )

    def submit(quote_id, req, response, authorization=None):
        observed.update(quote_id=quote_id, signature=req.tx_signature, authorization=authorization)
        return {"status": "submitted", "quote_id": quote_id, "tx_signature": req.tx_signature}

    monkeypatch.setattr(checkout_api, "submit_wallet_checkout", submit)
    result = checkout_api.submit_buyer_intent_checkout(
        checkout_api.BuyerIntentCheckoutSubmitRequest(
            intent_decision_id="bid_test_decision",
            quote_id="uq_1",
            tx_signature=signature,
        ),
        Response(),
        authorization="Bearer session",
    )
    assert observed == {
        "quote_id": "uq_1",
        "signature": signature,
        "authorization": "Bearer session",
    }
    assert result["order_id"] == "order_1"
    assert result["buyer_signature_reported"] is True
    assert result["broadcast_performed_by_iat"] is False
    assert result["iat_custodied_buyer_key"] is False


def test_intent_checkout_submit_rejects_quote_substitution(monkeypatch):
    monkeypatch.setattr(checkout_api, "_session_wallet", lambda authorization: (BUYER, "token"))
    monkeypatch.setattr(
        checkout_api,
        "get_buyer_intent_decision",
        lambda wallet, decision_id: {"order_id": "order_1", "wallet": wallet},
    )
    monkeypatch.setattr(
        checkout_api,
        "_wallet_owned_quote",
        lambda quote_id, wallet: ({"quote_id": quote_id, "order_id": "order_2"}, {}),
    )
    with pytest.raises(HTTPException) as rejected:
        checkout_api.submit_buyer_intent_checkout(
            checkout_api.BuyerIntentCheckoutSubmitRequest(
                intent_decision_id="bid_test_decision",
                quote_id="uq_other",
                tx_signature=str(Signature.default()),
            ),
            Response(),
            authorization="Bearer session",
        )
    assert rejected.value.status_code == 409
    assert rejected.value.detail == "intent_quote_mismatch"


@pytest.mark.parametrize(
    ("confirmation", "expected_status", "verified"),
    [
        ({"status": "pending", "reason": "transaction_not_finalized"}, "buyer_intent_payment_pending", False),
        (
            {"status": "confirmed", "payment_verified": True, "delivery": {"state": "queued"}},
            "buyer_intent_payment_confirmed",
            True,
        ),
    ],
)
def test_intent_checkout_confirm_reports_only_verified_chain_state(
    monkeypatch, confirmation, expected_status, verified
):
    monkeypatch.setattr(checkout_api, "_session_wallet", lambda authorization: (BUYER, "token"))
    monkeypatch.setattr(
        checkout_api,
        "get_buyer_intent_decision",
        lambda wallet, decision_id: {"order_id": "order_1", "wallet": wallet},
    )
    monkeypatch.setattr(
        checkout_api,
        "_wallet_owned_quote",
        lambda quote_id, wallet: ({"quote_id": quote_id, "order_id": "order_1"}, {}),
    )
    monkeypatch.setattr(checkout_api, "confirm_wallet_checkout", lambda *args, **kwargs: confirmation)

    result = checkout_api.confirm_buyer_intent_checkout(
        checkout_api.BuyerIntentCheckoutConfirmRequest(
            intent_decision_id="bid_test_decision", quote_id="uq_1"
        ),
        Response(),
        authorization="Bearer session",
    )
    assert result["status"] == expected_status
    assert result["payment_verified"] is verified
    assert result["delivery_triggered"] is verified
    assert result["retryable"] is (not verified)


def test_intent_checkout_confirm_rejects_quote_from_another_order(monkeypatch):
    monkeypatch.setattr(checkout_api, "_session_wallet", lambda authorization: (BUYER, "token"))
    monkeypatch.setattr(
        checkout_api,
        "get_buyer_intent_decision",
        lambda wallet, decision_id: {"order_id": "order_1", "wallet": wallet},
    )
    monkeypatch.setattr(
        checkout_api,
        "_wallet_owned_quote",
        lambda quote_id, wallet: ({"quote_id": quote_id, "order_id": "order_2"}, {}),
    )
    with pytest.raises(HTTPException) as rejected:
        checkout_api.confirm_buyer_intent_checkout(
            checkout_api.BuyerIntentCheckoutConfirmRequest(
                intent_decision_id="bid_test_decision", quote_id="uq_other"
            ),
            Response(),
            authorization="Bearer session",
        )
    assert rejected.value.status_code == 409
    assert rejected.value.detail == "intent_quote_mismatch"


def test_intent_commit_rejects_changed_market_and_releases_claim(monkeypatch):
    released = []
    monkeypatch.setattr(checkout_api, "_session_wallet", lambda authorization: (BUYER, "token"))
    monkeypatch.setattr(checkout_api, "claim_buyer_intent_decision", lambda *args: {
        "request": {"service": "web_research", "goal": "Produce a cited report"},
        "selected_agent_id": "agent_1",
        "selected_seller_agent_id": "sa_1",
        "selected_catalog_item_id": "catalog_1",
        "selected_unit_price": "2",
        "selected_currency": "IAT",
        "order_id": None,
    })
    monkeypatch.setattr(checkout_api, "list_verified_marketplace_candidates_db", lambda *args, **kwargs: [{
        "agent_id": "agent_1", "seller_agent_id": "sa_1", "catalog_item_id": "catalog_1",
        "unit_price": "3", "registry_price": "3", "currency": "IAT",
    }])
    monkeypatch.setattr(checkout_api, "release_buyer_intent_decision_claim", lambda *args: released.append(args) or True)
    with pytest.raises(HTTPException) as rejected:
        checkout_api.commit_buyer_intent(
            checkout_api.BuyerIntentCommitRequest(intent_decision_id="bid_test_decision"),
            Response(),
            authorization="Bearer session",
        )
    assert rejected.value.status_code == 409
    assert rejected.value.detail == "intent_decision_market_changed"
    assert released


def test_wallet_checkout_does_not_reuse_submitted_quote(monkeypatch):
    monkeypatch.setattr(checkout_api, "_session_wallet", lambda authorization: (BUYER, {}))
    monkeypatch.setattr(
        checkout_api,
        "_wallet_owned_order",
        lambda order_id, wallet: {"buyer_secret": SECRET},
    )
    rejection = HTTPException(
        status_code=409,
        detail={
            "code": "order_has_active_checkout_quote",
            "quote_id": "uq_submitted",
        },
    )
    monkeypatch.setattr(
        checkout_api,
        "create_universal_quote",
        lambda *args, **kwargs: (_ for _ in ()).throw(rejection),
    )
    monkeypatch.setattr(
        checkout_api,
        "_get_quote",
        lambda quote_id: {
            "quote_id": quote_id,
            "order_id": "ord-api",
            "buyer_wallet": BUYER,
            "input_asset": "USDC",
            "state": "submitted",
        },
    )

    with pytest.raises(HTTPException) as rejected:
        checkout_api.prepare_wallet_checkout(
            "ord-api",
            checkout_api.WalletCheckoutRequest(input_asset="USDC"),
            Response(),
            authorization="Bearer session",
        )

    assert rejected.value is rejection


def test_wallet_recovery_confirms_only_session_wallet_submissions(monkeypatch):
    observed = {}
    monkeypatch.setattr(
        checkout_api, "_session_wallet", lambda authorization: (BUYER, {})
    )
    monkeypatch.setattr(
        checkout_api,
        "_submitted_quotes_for_wallet",
        lambda wallet: observed.setdefault("wallet", wallet) and [
            {"quote_id": "uq_submitted", "order_id": "ord-api"}
        ],
    )
    monkeypatch.setattr(
        checkout_api,
        "get_order_db",
        lambda order_id: {"buyer_wallet": BUYER, "buyer_secret": SECRET},
    )

    def confirm(quote_id, request):
        observed.update(
            {
                "quote_id": quote_id,
                "buyer_wallet": request.buyer_wallet,
                "buyer_secret": request.buyer_secret,
            }
        )
        return {"status": "confirmed"}

    monkeypatch.setattr(checkout_api, "confirm_universal_checkout", confirm)

    result = checkout_api.recover_submitted_wallet_checkouts(
        Response(), authorization="Bearer session"
    )

    assert observed == {
        "wallet": BUYER,
        "quote_id": "uq_submitted",
        "buyer_wallet": BUYER,
        "buyer_secret": SECRET,
    }
    assert result == {
        "status": "wallet_checkout_recovery_complete",
        "recovered": [{"quote_id": "uq_submitted", "status": "confirmed"}],
        "pending": [],
        "rejected": [],
    }


def test_wallet_recovery_never_confirms_mismatched_order_wallet(monkeypatch):
    monkeypatch.setattr(
        checkout_api, "_session_wallet", lambda authorization: (BUYER, {})
    )
    monkeypatch.setattr(
        checkout_api,
        "_submitted_quotes_for_wallet",
        lambda wallet: [{"quote_id": "uq_foreign", "order_id": "ord-foreign"}],
    )
    monkeypatch.setattr(
        checkout_api,
        "get_order_db",
        lambda order_id: {"buyer_wallet": "AnotherWallet", "buyer_secret": SECRET},
    )
    monkeypatch.setattr(
        checkout_api,
        "confirm_universal_checkout",
        lambda *args: pytest.fail("foreign order must not be confirmed"),
    )

    result = checkout_api.recover_submitted_wallet_checkouts(
        Response(), authorization="Bearer session"
    )

    assert result["recovered"] == []
    assert result["rejected"] == [
        {"quote_id": "uq_foreign", "reason": "order_unavailable"}
    ]


def test_reconciliation_discovers_and_confirms_exact_payment_intent(monkeypatch):
    proof = {"payment_intent": str(Keypair().pubkey())}
    row = {
        "quote_id": "uq_reconcile",
        "order_id": "ord-api",
        "buyer_wallet": BUYER,
        "state": "prepared",
        "execution_evidence": json.dumps({"proof": proof}),
    }
    observed = {}

    class Verifier:
        def finalized_signatures_for_address(self, address, limit):
            observed.update({"address": address, "limit": limit})
            return [str(checkout_api.Signature.default())]

        def verify(self, **kwargs):
            observed["verify"] = kwargs
            return {"status": "confirmed"}

    monkeypatch.setattr(checkout_api, "_checkout_verifier", Verifier)
    monkeypatch.setattr(checkout_api, "_reconcilable_treasury_quotes", lambda limit: [row])
    monkeypatch.setattr(
        checkout_api,
        "get_order_db",
        lambda order_id: {"buyer_wallet": BUYER, "buyer_secret": SECRET},
    )
    monkeypatch.setattr(checkout_api, "_attach_reconciled_signature", lambda *args: True)
    monkeypatch.setattr(
        checkout_api,
        "confirm_universal_checkout",
        lambda quote_id, request: {"status": "confirmed"},
    )

    result = checkout_api.run_checkout_reconciliation_sweep(limit=7)

    assert result == {"selected": 1, "recovered": 1, "pending": 0, "rejected": 0}
    assert observed["address"] == proof["payment_intent"]
    assert observed["limit"] == 5
    assert observed["verify"]["route"] == "treasury"
    assert observed["verify"]["evidence"] == proof


def test_reconciliation_ignores_nonmatching_candidate(monkeypatch):
    row = {
        "quote_id": "uq_reconcile",
        "order_id": "ord-api",
        "buyer_wallet": BUYER,
        "state": "prepared",
        "execution_evidence": json.dumps(
            {"proof": {"payment_intent": str(Keypair().pubkey())}}
        ),
    }

    class Verifier:
        def finalized_signatures_for_address(self, address, limit):
            return [str(checkout_api.Signature.default())]

        def verify(self, **kwargs):
            raise checkout_api.CheckoutVerificationError("evidence_mismatch")

    monkeypatch.setattr(checkout_api, "_checkout_verifier", Verifier)
    monkeypatch.setattr(checkout_api, "_reconcilable_treasury_quotes", lambda limit: [row])
    monkeypatch.setattr(
        checkout_api,
        "get_order_db",
        lambda order_id: {"buyer_wallet": BUYER, "buyer_secret": SECRET},
    )
    monkeypatch.setattr(
        checkout_api,
        "_attach_reconciled_signature",
        lambda *args: pytest.fail("unverified signature must never be attached"),
    )

    assert checkout_api.run_checkout_reconciliation_sweep() == {
        "selected": 1,
        "recovered": 0,
        "pending": 1,
        "rejected": 0,
    }


def test_reconciliation_confirms_after_another_worker_attaches_signature(monkeypatch):
    row = {
        "quote_id": "uq_reconcile_race",
        "order_id": "ord-api",
        "buyer_wallet": BUYER,
        "state": "prepared",
        "execution_evidence": json.dumps(
            {"proof": {"payment_intent": str(Keypair().pubkey())}}
        ),
    }

    class Verifier:
        def finalized_signatures_for_address(self, address, limit):
            return [str(checkout_api.Signature.default())]

        def verify(self, **kwargs):
            return {"status": "confirmed"}

    monkeypatch.setattr(checkout_api, "_checkout_verifier", Verifier)
    monkeypatch.setattr(checkout_api, "_reconcilable_treasury_quotes", lambda limit: [row])
    monkeypatch.setattr(
        checkout_api,
        "get_order_db",
        lambda order_id: {"buyer_wallet": BUYER, "buyer_secret": SECRET},
    )
    monkeypatch.setattr(checkout_api, "_attach_reconciled_signature", lambda *args: False)
    monkeypatch.setattr(
        checkout_api,
        "confirm_universal_checkout",
        lambda quote_id, request: {"status": "confirmed"},
    )

    assert checkout_api.run_checkout_reconciliation_sweep() == {
        "selected": 1,
        "recovered": 1,
        "pending": 0,
        "rejected": 0,
    }


def _basic(username: str, password: str) -> str:
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {encoded}"


def test_mailjet_event_endpoint_requires_configured_basic_auth(monkeypatch):
    monkeypatch.setenv("IAT_MAILJET_EVENT_USERNAME", "iat-mailjet")
    monkeypatch.setenv("IAT_MAILJET_EVENT_SECRET", "provider-secret")

    with pytest.raises(HTTPException) as rejected:
        checkout_api.receive_mailjet_delivery_event(
            {"event": "sent"}, authorization=_basic("iat-mailjet", "wrong")
        )

    assert rejected.value.status_code == 401


def test_mailjet_event_endpoint_records_correlated_event(monkeypatch):
    monkeypatch.setenv("IAT_MAILJET_EVENT_USERNAME", "iat-mailjet")
    monkeypatch.setenv("IAT_MAILJET_EVENT_SECRET", "provider-secret")
    observed = {}

    def record(**kwargs):
        observed.update(kwargs)
        return {"state": "delivered"}

    monkeypatch.setattr(checkout_api, "record_email_provider_event", record)
    result = checkout_api.receive_mailjet_delivery_event(
        {
            "event": "sent",
            "time": 123,
            "email": "buyer@example.com",
            "customcampaign": "cdr_receipt",
            "mj_campaign_id": "456",
        },
        authorization=_basic("iat-mailjet", "provider-secret"),
    )

    assert result == {
        "status": "mailjet_events_processed",
        "recorded": 1,
        "ignored": 0,
    }
    assert observed == {
        "receipt_token": "cdr_receipt",
        "recipient": "buyer@example.com",
        "event": "sent",
        "event_at": 123,
        "provider_message_id": "456",
        "reason": "",
    }


def test_mailjet_event_endpoint_acknowledges_transport_canary(monkeypatch):
    monkeypatch.setenv("IAT_MAILJET_EVENT_USERNAME", "iat-mailjet")
    monkeypatch.setenv("IAT_MAILJET_EVENT_SECRET", "provider-secret")

    result = checkout_api.receive_mailjet_delivery_event(
        {
            "event": "sent",
            "time": 123,
            "email": "owner@example.com",
            "customcampaign": "iat_transport_canary_123",
        },
        authorization=_basic("iat-mailjet", "provider-secret"),
    )

    assert result == {
        "status": "mailjet_events_processed",
        "recorded": 0,
        "ignored": 1,
    }


@pytest.mark.parametrize(
    "encoded",
    [
        '{"USDC":{"mint":"mint"}}',
        '"{\\"USDC\\":{\\"mint\\":\\"mint\\"}}"',
        """'{"USDC":{"mint":"mint"}}'""",
    ],
)
def test_json_env_accepts_render_safe_object_encodings(monkeypatch, encoded):
    monkeypatch.setenv("IAT_CHECKOUT_ASSETS_JSON", encoded)

    assert checkout_api._json_env("IAT_CHECKOUT_ASSETS_JSON") == {
        "USDC": {"mint": "mint"}
    }


def test_quote_signer_client_uses_authenticated_canonical_request(monkeypatch):
    secret = "q" * 32
    monkeypatch.setenv("IAT_QUOTE_SIGNER_CLIENT_ENABLED", "true")
    monkeypatch.setenv("IAT_QUOTE_SIGNER_URL", "https://signer.example")
    monkeypatch.setenv("IAT_QUOTE_SIGNER_SHARED_SECRET", secret)
    monkeypatch.setattr(checkout_api.time, "time", lambda: NOW)
    monkeypatch.setattr(
        checkout_api,
        "verify_quote_authorization",
        lambda **kwargs: "01" * 32,
    )
    observed = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": "signed",
                "quote_id": "uq_" + "a" * 32,
                "transaction_base64": "signed-transaction",
                "message_hash": "01" * 32,
                "quote_authority": "quote-authority",
                "expires_at": NOW + 60,
                "idempotent": False,
            }

    def post(url, **kwargs):
        observed["url"] = url
        observed.update(kwargs)
        return Response()

    monkeypatch.setattr(checkout_api.requests, "post", post)
    result = checkout_api._authorize_with_quote_signer(
        quote_id="uq_" + "a" * 32,
        transaction_base64="unsigned-transaction",
        instruction_plan={
            "quote_authority": "quote-authority",
            "protocol_authorization_signature_required": True,
        },
        expires_at=NOW + 60,
    )

    timestamp = observed["headers"]["X-IAT-Signer-Timestamp"]
    expected = hmac.new(
        secret.encode(),
        timestamp.encode() + b"." + observed["data"],
        hashlib.sha256,
    ).hexdigest()
    assert observed["url"] == "https://signer.example/v1/sign"
    assert "content" not in observed
    assert observed["headers"]["X-IAT-Signer-Signature"] == expected
    assert json.loads(observed["data"])["instruction_plan"]["quote_authority"] == (
        "quote-authority"
    )
    assert result["transaction_base64"] == "signed-transaction"


def test_quote_signer_client_caps_render_quote_ttl(monkeypatch):
    monkeypatch.setenv("IAT_CHECKOUT_QUOTE_TTL_SECONDS", "300")
    policy = checkout_api.load_checkout_policy()

    monkeypatch.setenv("IAT_QUOTE_SIGNER_CLIENT_ENABLED", "true")
    compatible = checkout_api._quote_signer_compatible_policy(policy)

    assert policy.quote_ttl_seconds == 300
    assert compatible.quote_ttl_seconds == 120


@pytest.mark.parametrize("encoded", ["[]", '"[]"', "not-json"])
def test_json_env_rejects_non_object_values(monkeypatch, encoded):
    monkeypatch.setenv("IAT_CHECKOUT_ASSETS_JSON", encoded)

    with pytest.raises(checkout_api.CheckoutRejected):
        checkout_api._json_env("IAT_CHECKOUT_ASSETS_JSON")


def test_devnet_fixed_usdc_refreshes_only_the_expected_circle_asset(monkeypatch):
    monkeypatch.setattr(checkout_api.time, "time", lambda: NOW)
    monkeypatch.setenv("IAT_CHECKOUT_DEVNET_FIXED_USDC_ENABLED", "true")
    monkeypatch.setenv(
        "IAT_CHECKOUT_ASSETS_JSON",
        json.dumps(
            {
                "USDC": {
                    "mint": checkout_api.DEVNET_CIRCLE_USDC_MINT,
                    "decimals": 6,
                    "usd_price": "1",
                    "oracle": checkout_api.DEVNET_FIXED_USDC_ORACLE,
                    "observed_at": 1,
                }
            }
        ),
    )

    snapshot = checkout_api._asset_snapshot("usdc")

    assert snapshot.observed_at == NOW
    assert snapshot.usd_price == 1


def test_devnet_fixed_usdc_does_not_refresh_an_unexpected_oracle(monkeypatch):
    monkeypatch.setattr(checkout_api.time, "time", lambda: NOW)
    monkeypatch.setenv("IAT_CHECKOUT_DEVNET_FIXED_USDC_ENABLED", "true")
    monkeypatch.setenv(
        "IAT_CHECKOUT_ASSETS_JSON",
        json.dumps(
            {
                "USDC": {
                    "mint": checkout_api.DEVNET_CIRCLE_USDC_MINT,
                    "decimals": 6,
                    "usd_price": "1",
                    "oracle": "untrusted",
                    "observed_at": 1,
                }
            }
        ),
    )

    assert checkout_api._asset_snapshot("USDC").observed_at == 1


def test_quote_is_persisted_idempotently_and_secret_is_not_stored(checkout_database):
    first = checkout_api.create_universal_quote(
        request(), idempotency_key="checkout-idempotency-0001"
    )
    second = checkout_api.create_universal_quote(
        request(), idempotency_key="checkout-idempotency-0001"
    )

    assert first["quote_id"] == second["quote_id"]
    assert first["route"] == "treasury"
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM universal_checkout_quotes").fetchone()
    db.release_conn(conn)
    assert SECRET not in json.dumps(dict(row))
    assert len(first["intent_hash"]) == 64


def test_idempotency_key_cannot_be_reused_for_another_request(checkout_database):
    checkout_api.create_universal_quote(
        request(), idempotency_key="checkout-idempotency-0002"
    )

    with pytest.raises(HTTPException) as rejected:
        checkout_api.create_universal_quote(
            request(input_asset="USDT"),
            idempotency_key="checkout-idempotency-0002",
        )

    assert rejected.value.status_code == 409


def test_one_order_cannot_reserve_multiple_active_quotes(checkout_database):
    first = checkout_api.create_universal_quote(
        request(), idempotency_key="checkout-active-order-0001"
    )
    with pytest.raises(HTTPException) as rejected:
        checkout_api.create_universal_quote(
            request(),
            idempotency_key="checkout-active-order-0002",
        )
    assert rejected.value.status_code == 409
    assert rejected.value.detail["code"] == "order_has_active_checkout_quote"
    assert rejected.value.detail["quote_id"] == first["quote_id"]


def test_order_secret_and_wallet_are_both_required(checkout_database):
    with pytest.raises(HTTPException) as rejected:
        checkout_api.create_universal_quote(
            request(buyer_secret="wrong-secret-long-enough"),
            idempotency_key="checkout-idempotency-0003",
        )

    assert rejected.value.status_code == 403


def test_prepare_returns_contract_but_never_signs_for_buyer(checkout_database):
    quote = checkout_api.create_universal_quote(
        request(), idempotency_key="checkout-idempotency-0004"
    )
    prepared = checkout_api.prepare_universal_checkout(
        quote["quote_id"],
        checkout_api.UniversalPrepareRequest(
            buyer_wallet=BUYER,
            buyer_secret=SECRET,
        ),
    )

    assert prepared["status"] == "prepared"
    assert prepared["transaction_contract"]["buyer_signer"] == BUYER
    assert prepared["transaction_contract"]["atomic_execution_required"] is True
    assert prepared["readiness"]["server_custody"] is False
    assert prepared["readiness"]["serialized_transaction"] == (
        "buyer_wallet_must_add_blockhash_and_sign"
    )
    assert prepared["readiness"]["instruction_plan"].startswith(
        "configuration_error:"
    )


def test_status_credentials_are_headers_not_query_contract(checkout_database):
    quote = checkout_api.create_universal_quote(
        request(), idempotency_key="checkout-idempotency-0005"
    )
    status = checkout_api.get_universal_quote(
        quote["quote_id"],
        buyer_wallet=BUYER,
        buyer_secret=SECRET,
    )
    assert status["quote_id"] == quote["quote_id"]

    with pytest.raises(HTTPException) as rejected:
        checkout_api.get_universal_quote(
            quote["quote_id"],
            buyer_wallet=None,
            buyer_secret=None,
        )
    assert rejected.value.status_code == 403


def test_live_raydium_payload_is_private_and_builds_escrow_transaction(
    checkout_database,
    monkeypatch,
):
    monkeypatch.setenv("IAT_TREASURY_CHECKOUT_ENABLED", "false")
    monkeypatch.setenv("IAT_RAYDIUM_LIVE_ENABLED", "true")
    monkeypatch.setenv("IAT_RAYDIUM_ALLOWED_POOLS", "pool-approved")
    monkeypatch.setenv("IAT_RAYDIUM_QUOTES_JSON", "{}")
    provider_payload = {
        "provider": "raydium_trade_api_v2",
        "quote_response": {"success": True, "data": {"opaque": True}},
        "maximum_input_minor": 3_000_000,
    }
    monkeypatch.setattr(
        checkout_api,
        "_live_raydium_quote",
        lambda **_: (
            RaydiumSnapshot(
                input_amount=checkout_api.Decimal("2.5"),
                output_iat=checkout_api.Decimal("10"),
                price_impact_bps=50,
                pool_liquidity_usd=checkout_api.Decimal("25000"),
                pool_id="pool-approved",
                observed_at=NOW,
            ),
            provider_payload,
        ),
    )
    monkeypatch.setattr(
        checkout_api,
        "_raydium_transaction_plan",
        lambda payload: {
            "provider": payload["_provider_payload"]["provider"],
            "transaction_base64": "mock-transaction",
            "output_to_buyer_wallet": False,
            "simulation_required": True,
        },
    )
    monkeypatch.setattr(
        checkout_api,
        "message_hash_from_transaction_base64",
        lambda _: "ab" * 32,
    )

    created = checkout_api.create_universal_quote(
        request(),
        idempotency_key="checkout-idempotency-raydium",
    )
    assert created["route"] == "raydium"
    assert "_provider_payload" not in created
    assert created["expires_at"] - created["created_at"] == 25
    assert created["input"]["amount_semantics"] == "maximum"

    status = checkout_api.get_universal_quote(
        created["quote_id"],
        buyer_wallet=BUYER,
        buyer_secret=SECRET,
    )
    assert "_provider_payload" not in status

    prepared = checkout_api.prepare_universal_checkout(
        created["quote_id"],
        checkout_api.UniversalPrepareRequest(
            buyer_wallet=BUYER,
            buyer_secret=SECRET,
        ),
    )
    assert prepared["readiness"]["instruction_plan"] == "ready"
    assert prepared["raydium_transaction"]["output_to_buyer_wallet"] is False


def test_submit_confirm_and_global_replay_protection(
    checkout_database,
    monkeypatch,
):
    monkeypatch.setattr(
        checkout_api,
        "_treasury_instruction_plan",
        lambda payload, order_id: {
            "program_id": "program",
            "quote_authority": "quote-authority",
            "anti_replay": {
                "payment_intent": "payment-intent",
                "order_hash_hex": "01" * 32,
                "quote_hash_hex": "02" * 32,
                "nonce": 7,
            },
        },
    )
    quote = checkout_api.create_universal_quote(
        request(),
        idempotency_key="checkout-confirmation-0001",
    )
    checkout_api.prepare_universal_checkout(
        quote["quote_id"],
        checkout_api.UniversalPrepareRequest(
            buyer_wallet=BUYER,
            buyer_secret=SECRET,
        ),
    )
    signature = str(checkout_api.Signature.default())
    submitted = checkout_api.submit_universal_checkout(
        quote["quote_id"],
        checkout_api.UniversalSubmitRequest(
            buyer_wallet=BUYER,
            buyer_secret=SECRET,
            tx_signature=signature,
        ),
    )
    assert submitted["status"] == "submitted"

    class Verifier:
        def verify(self, **kwargs):
            assert kwargs["signature"] == signature
            return {
                "status": "confirmed",
                "route": "treasury",
                "signature": signature,
                "finalized": True,
            }

    monkeypatch.setattr(checkout_api, "_checkout_verifier", lambda: Verifier())
    confirmed = checkout_api.confirm_universal_checkout(
        quote["quote_id"],
        checkout_api.UniversalPrepareRequest(
            buyer_wallet=BUYER,
            buyer_secret=SECRET,
        ),
    )
    duplicate = checkout_api.confirm_universal_checkout(
        quote["quote_id"],
        checkout_api.UniversalPrepareRequest(
            buyer_wallet=BUYER,
            buyer_secret=SECRET,
        ),
    )
    assert confirmed["payment_verified"] is True
    assert duplicate["idempotent"] is True
    assert confirmed["delivery"]["state"] == "completed"
    assert db.get_order_db("ord-api")["status"] == "delivered"
    assert db.is_tx_processed_db(signature) is True


def test_late_signature_registration_allows_onchain_recovery(
    checkout_database,
    monkeypatch,
):
    monkeypatch.setattr(
        checkout_api,
        "_treasury_instruction_plan",
        lambda payload, order_id: {
            "program_id": "program",
            "quote_authority": "quote-authority",
            "anti_replay": {
                "payment_intent": "payment-intent",
                "order_hash_hex": "01" * 32,
                "quote_hash_hex": "02" * 32,
                "nonce": 7,
            },
        },
    )
    quote = checkout_api.create_universal_quote(
        request(),
        idempotency_key="checkout-late-signature-0001",
    )
    checkout_api.prepare_universal_checkout(
        quote["quote_id"],
        checkout_api.UniversalPrepareRequest(
            buyer_wallet=BUYER,
            buyer_secret=SECRET,
        ),
    )
    conn = db.get_conn()
    try:
        conn.execute(
            "UPDATE universal_checkout_quotes SET expires_at = ? WHERE quote_id = ?",
            (NOW - 1, quote["quote_id"]),
        )
        conn.commit()
    finally:
        db.release_conn(conn)

    submitted = checkout_api.submit_universal_checkout(
        quote["quote_id"],
        checkout_api.UniversalSubmitRequest(
            buyer_wallet=BUYER,
            buyer_secret=SECRET,
            tx_signature=str(checkout_api.Signature.default()),
        ),
    )

    assert submitted["status"] == "submitted"


def _enqueue_test_delivery(state="paid"):
    conn = db.get_conn()
    try:
        conn.execute(
            "UPDATE orders SET status = ?, tx_signature = ? WHERE order_id = ?",
            (state, "tx-delivery", "ord-api"),
        )
        checkout_delivery.enqueue_delivery_tx(
            conn.cursor(),
            quote_id="quote-delivery",
            order_id="ord-api",
            tx_signature="tx-delivery",
            now=NOW,
        )
        conn.commit()
    finally:
        db.release_conn(conn)


def test_delivery_failure_is_retryable_and_payment_remains_paid(
    checkout_database,
    monkeypatch,
):
    _enqueue_test_delivery()
    monkeypatch.setenv("IAT_CHECKOUT_DELIVERY_RETRY_BASE_SECONDS", "30")

    delivery = checkout_delivery.run_checkout_delivery(
        "quote-delivery",
        now=NOW,
        executor=lambda order, signature: {"error": "provider_unreachable"},
    )

    assert delivery["state"] == "retryable_failure"
    assert delivery["next_attempt_at"] == NOW + 30
    assert delivery["last_error_code"] == "provider_unreachable"
    order = db.get_order_db("ord-api")
    assert order["status"] == "paid"
    assert order["used"] is False
    assert order["tx_signature"] == "tx-delivery"


def test_delivery_retry_wait_is_enforced(checkout_database):
    _enqueue_test_delivery()
    calls = []
    first = checkout_delivery.run_checkout_delivery(
        "quote-delivery",
        now=NOW,
        executor=lambda order, signature: {"error": "temporary"},
    )
    second = checkout_delivery.run_checkout_delivery(
        "quote-delivery",
        now=NOW + 1,
        executor=lambda order, signature: calls.append(signature),
    )

    assert first["state"] == "retryable_failure"
    assert second["claimed"] is False
    assert calls == []


def test_delivery_review_state_retries_autonomously_and_preserves_payment(
    checkout_database,
    monkeypatch,
):
    _enqueue_test_delivery()
    monkeypatch.setenv("IAT_CHECKOUT_DELIVERY_RETRY_BASE_SECONDS", "30")
    delivery = checkout_delivery.run_checkout_delivery(
        "quote-delivery",
        now=NOW,
        executor=lambda order, signature: {
            "status": "foundation_review_required",
            "delivery_authorized": False,
        },
    )

    assert delivery["state"] == "retryable_failure"
    assert delivery["next_attempt_at"] == NOW + 30
    assert delivery["last_error_code"] == "foundation_decision_not_ready_for_delivery"
    order = db.get_order_db("ord-api")
    assert order["status"] == "paid"
    assert order["used"] is False


def test_delivery_review_exhaustion_requests_terminal_recovery(
    checkout_database,
    monkeypatch,
):
    _enqueue_test_delivery()
    monkeypatch.setenv("IAT_CHECKOUT_DELIVERY_MAX_ATTEMPTS", "1")

    delivery = checkout_delivery.run_checkout_delivery(
        "quote-delivery",
        now=NOW,
        executor=lambda order, signature: {
            "status": "foundation_review_required",
            "delivery_authorized": False,
        },
    )

    assert delivery["state"] == "exhausted"
    assert db.get_order_db("ord-api")["status"] == "foundation_review_required"


def test_legacy_review_can_be_resumed_without_resetting_attempts(checkout_database):
    _enqueue_test_delivery()
    checkout_delivery.run_checkout_delivery(
        "quote-delivery",
        now=NOW,
        executor=lambda order, signature: {"status": "success"},
    )
    conn = db.get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE universal_checkout_deliveries SET state = ?, attempt_count = ? WHERE quote_id = ?",
            ("review_required", 3, "quote-delivery"),
        )
        conn.commit()
    finally:
        db.release_conn(conn)

    resumed = checkout_delivery.resume_review_required_delivery(
        "quote-delivery", now=NOW + 10
    )

    assert resumed["state"] == "retryable_failure"
    stored = checkout_delivery.get_delivery("quote-delivery")
    assert stored["attempt_count"] == 3
    assert stored["next_attempt_at"] == NOW + 10


def test_foundation_retry_can_be_accelerated_after_repair_cooldown(
    checkout_database,
    monkeypatch,
):
    _enqueue_test_delivery()
    monkeypatch.setenv("IAT_CHECKOUT_DELIVERY_RETRY_BASE_SECONDS", "300")
    checkout_delivery.run_checkout_delivery(
        "quote-delivery",
        now=NOW,
        executor=lambda order, signature: {
            "status": "foundation_review_required",
            "delivery_authorized": False,
        },
    )

    accelerated = checkout_delivery.accelerate_foundation_retry(
        "quote-delivery", now=NOW + 30
    )

    assert accelerated["status"] == "foundation_retry_accelerated"
    stored = checkout_delivery.get_delivery("quote-delivery")
    assert stored["attempt_count"] == 1
    assert stored["next_attempt_at"] == NOW + 30


def test_foundation_retry_acceleration_enforces_cooldown(checkout_database):
    _enqueue_test_delivery()
    checkout_delivery.run_checkout_delivery(
        "quote-delivery",
        now=NOW,
        executor=lambda order, signature: {
            "status": "foundation_review_required",
            "delivery_authorized": False,
        },
    )

    result = checkout_delivery.accelerate_foundation_retry(
        "quote-delivery", now=NOW + 5
    )

    assert result["status"] == "repair_acceleration_not_required"
    assert checkout_delivery.get_delivery("quote-delivery")["next_attempt_at"] == NOW + 30


def test_delivery_is_idempotent_after_completion(checkout_database):
    _enqueue_test_delivery()
    calls = []

    def executor(order, signature):
        calls.append((order["order_id"], signature))
        return {"status": "success", "result": "delivered"}

    first = checkout_delivery.run_checkout_delivery(
        "quote-delivery", now=NOW, executor=executor
    )
    second = checkout_delivery.run_checkout_delivery(
        "quote-delivery", now=NOW + 100, executor=executor
    )

    assert first["state"] == "completed"
    assert second["state"] == "completed"
    assert second["claimed"] is False
    assert calls == [("ord-api", "tx-delivery")]
    assert db.get_order_db("ord-api")["used"] is True


def test_exhausted_delivery_can_only_be_redriven_with_audited_reason(
    checkout_database,
    monkeypatch,
):
    _enqueue_test_delivery()
    monkeypatch.setenv("IAT_CHECKOUT_DELIVERY_MAX_ATTEMPTS", "1")
    failed = checkout_delivery.run_checkout_delivery(
        "quote-delivery",
        now=NOW,
        executor=lambda order, signature: {"error": "provider_offline"},
    )
    assert failed["state"] == "exhausted"

    with pytest.raises(ValueError, match="redrive_reason_length_invalid"):
        checkout_delivery.redrive_exhausted_delivery(
            "quote-delivery", reason="retry", now=NOW + 10
        )

    redriven = checkout_delivery.redrive_exhausted_delivery(
        "quote-delivery",
        reason="Provider health was manually verified before redrive.",
        now=NOW + 10,
    )
    assert redriven["state"] == "pending"
    events = checkout_delivery.delivery_events("quote-delivery")
    assert events[0]["event_type"] == "admin_redrive"
    assert events[0]["from_state"] == "exhausted"
    assert events[0]["to_state"] == "pending"
    assert events[0]["reason"].startswith("Provider health")


def test_delivery_dashboard_excludes_result_and_credentials(checkout_database):
    _enqueue_test_delivery()
    dashboard = checkout_delivery.delivery_dashboard(limit=10)

    assert dashboard["state_counts"] == {"pending": 1}
    assert dashboard["total"] == 1
    item = dashboard["items"][0]
    assert "result_payload" not in item
    assert "buyer_secret" not in item
    assert "tx_signature" not in item


def _confirmed_quote_with_delivery():
    quote = checkout_api.create_universal_quote(
        request(), idempotency_key="checkout-compensation-0001"
    )
    conn = db.get_conn()
    try:
        conn.execute(
            "UPDATE universal_checkout_quotes SET state = ? WHERE quote_id = ?",
            ("confirmed", quote["quote_id"]),
        )
        conn.execute(
            "UPDATE orders SET status = ?, tx_signature = ? WHERE order_id = ?",
            ("paid", "tx-compensation", "ord-api"),
        )
        checkout_delivery.enqueue_delivery_tx(
            conn.cursor(),
            quote_id=quote["quote_id"],
            order_id="ord-api",
            tx_signature="tx-compensation",
            now=NOW,
        )
        conn.commit()
    finally:
        db.release_conn(conn)
    return quote


def test_exhausted_delivery_automatically_opens_treasury_compensation(
    checkout_database,
    monkeypatch,
):
    quote = _confirmed_quote_with_delivery()
    monkeypatch.setenv("IAT_CHECKOUT_DELIVERY_MAX_ATTEMPTS", "1")
    checkout_delivery.run_checkout_delivery(
        quote["quote_id"],
        now=NOW,
        executor=lambda order, signature: {"error": "provider_offline"},
    )

    compensation = checkout_compensation.get_compensation(quote["quote_id"])
    assert compensation["state"] == "pending_review"
    assert compensation["refund_asset"] == "USDC"
    assert compensation["refund_mint"] == "USDC1111111111111111111111111111111111"
    assert compensation["refund_amount_minor"] == "2512500"
    assert compensation["eligibility_reason"] == "delivery_attempts_exhausted"


def test_compensation_decision_is_governed_and_idempotent(
    checkout_database,
    monkeypatch,
):
    quote = _confirmed_quote_with_delivery()
    monkeypatch.setenv("IAT_CHECKOUT_DELIVERY_MAX_ATTEMPTS", "1")
    checkout_delivery.run_checkout_delivery(
        quote["quote_id"],
        now=NOW,
        executor=lambda order, signature: {"error": "provider_offline"},
    )

    approved = checkout_compensation.decide_compensation(
        quote["quote_id"],
        approve=True,
        reason="Verified terminal non-delivery and refund destination.",
        now=NOW + 1,
    )
    duplicate = checkout_compensation.decide_compensation(
        quote["quote_id"],
        approve=True,
        reason="Verified terminal non-delivery and refund destination.",
        now=NOW + 2,
    )

    assert approved["state"] == "approved"
    assert approved["payout_signature"] is None
    assert duplicate["idempotent"] is True


def test_compensation_is_rejected_before_terminal_non_delivery(checkout_database):
    quote = _confirmed_quote_with_delivery()
    with pytest.raises(ValueError, match="compensation_not_eligible"):
        checkout_compensation.request_compensation(
            quote["quote_id"],
            requested_by="authenticated_buyer",
            now=NOW,
        )


def test_buyer_dispute_blocks_release_and_opens_compensation_review(checkout_database):
    quote = _confirmed_quote_with_delivery()
    checkout_delivery.run_checkout_delivery(
        quote["quote_id"],
        now=NOW,
        executor=lambda order, signature: {
            "status": "success",
            "summary": "Delivered but disputed result",
        },
    )

    receipt = checkout_receipt.acknowledge_delivery(
        quote_id=quote["quote_id"],
        decision="disputed",
        dispute_code="incorrect",
        message="The delivered result does not answer the paid request.",
        now=NOW + 1,
    )
    compensation = checkout_compensation.get_compensation(quote["quote_id"])
    gate = checkout_receipt.settlement_release_receipt_gate("ord-api")

    assert receipt["state"] == "disputed"
    assert receipt["compensation_state"] == "pending_review"
    assert compensation["eligibility_reason"] == "buyer_disputed_sealed_delivery"
    assert gate["release_allowed"] is False


def test_public_delivery_never_exposes_internal_order_credentials():
    public = checkout_delivery._public_delivery(
        {
            "state": "review_required",
            "result": {
                "status": "review_required",
                "delivery_authorized": False,
                "foundation_verdict": "foundation_evidence_not_ready",
                "foundation_decision_ready": False,
                "foundation_evidence_status": "verification_failed",
                "verification_valid_agents": 2,
                "execution_mode": "foundation_supplier_pipeline",
                "foundation_decision": {
                    "order": {
                        "buyer_secret": SECRET,
                        "buyer_wallet": BUYER,
                    }
                },
            },
        }
    )

    assert public["result"] == {
        "status": "review_required",
        "delivery_authorized": False,
        "foundation_verdict": "foundation_evidence_not_ready",
        "foundation_decision_ready": False,
        "foundation_evidence_status": "verification_failed",
        "verification_valid_agents": 2,
        "execution_mode": "foundation_supplier_pipeline",
    }
    assert SECRET not in json.dumps(public)
