import base64
import json
import hmac
import hashlib

import pytest
from fastapi import HTTPException

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
