import sqlite3
import json

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature

import iat.checkout_receipt as receipt


@pytest.fixture()
def receipt_db(tmp_path, monkeypatch):
    database = tmp_path / "receipts.sqlite"

    def connect():
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(receipt, "get_conn", connect)
    monkeypatch.setattr(receipt, "release_conn", lambda conn: conn.close())
    monkeypatch.setattr(receipt, "qmark", lambda: "?")
    monkeypatch.setattr(receipt.database, "USE_POSTGRES", False)
    receipt.init_delivery_receipt_db()


def test_api_pull_receipt_is_sealed_and_buyer_acceptance_is_idempotent(receipt_db):
    configured = receipt.configure_delivery_receipt(
        quote_id="uq_accept",
        order_id="ord_accept",
        channel="api_pull",
        destination=None,
        now=100,
    )
    delivered = receipt.publish_delivery_payload(
        quote_id="uq_accept",
        order_id="ord_accept",
        payload={"status": "success", "result": "verified report"},
        now=110,
    )
    accepted = receipt.acknowledge_delivery(
        quote_id="uq_accept", decision="accepted", now=120
    )
    duplicate = receipt.acknowledge_delivery(
        quote_id="uq_accept", decision="accepted", now=130
    )

    assert configured["state"] == "configured"
    assert delivered["state"] == "delivered"
    assert len(delivered["payload_digest"]) == 64
    assert accepted["state"] == "accepted"
    assert receipt.settlement_release_receipt_gate("ord_accept")["release_allowed"] is True
    assert duplicate["idempotent"] is True
    assert [event["event_type"] for event in receipt.delivery_receipt_events("uq_accept")] == [
        "delivery_destination_configured",
        "delivery_payload_sealed",
        "delivery_accepted",
    ]
    with pytest.raises(receipt.DeliveryReceiptError, match="already_final"):
        receipt.acknowledge_delivery(
            quote_id="uq_accept",
            decision="disputed",
            dispute_code="incorrect",
            message="This result is demonstrably incorrect.",
        )


def test_email_destination_is_masked_and_waits_for_dispatch(receipt_db):
    configured = receipt.configure_delivery_receipt(
        quote_id="uq_email",
        order_id="ord_email",
        channel="email",
        destination="buyer@example.com",
        now=100,
    )
    ready = receipt.publish_delivery_payload(
        quote_id="uq_email",
        order_id="ord_email",
        payload={"status": "success"},
        now=110,
    )

    assert configured["destination"] == "b***@example.com"
    assert ready["state"] == "pending_dispatch"
    with pytest.raises(receipt.DeliveryReceiptError, match="not_yet_dispatched"):
        receipt.acknowledge_delivery(
            quote_id="uq_email", decision="accepted", now=120
        )


def test_configured_receipt_rebinds_to_replacement_quote(receipt_db):
    first = receipt.configure_delivery_receipt(
        quote_id="uq_expired",
        order_id="ord_requoted",
        channel="email",
        destination="buyer@example.com",
        now=100,
    )

    replacement = receipt.configure_delivery_receipt(
        quote_id="uq_replacement",
        order_id="ord_requoted",
        channel="email",
        destination="delivery@example.com",
        now=200,
    )

    assert receipt.get_delivery_receipt("uq_expired") is None
    assert replacement["receipt_token"] == first["receipt_token"]
    assert replacement["destination"] == "d***@example.com"
    assert [
        event["event_type"]
        for event in receipt.delivery_receipt_events("uq_replacement")
    ] == ["delivery_quote_rebound"]


def test_sealed_receipt_cannot_rebind_to_replacement_quote(receipt_db):
    receipt.configure_delivery_receipt(
        quote_id="uq_paid",
        order_id="ord_paid",
        channel="api_pull",
        destination=None,
        now=100,
    )
    receipt.publish_delivery_payload(
        quote_id="uq_paid",
        order_id="ord_paid",
        payload={"status": "success"},
        now=110,
    )

    with pytest.raises(
        receipt.DeliveryReceiptError, match="delivery_order_already_bound"
    ):
        receipt.configure_delivery_receipt(
            quote_id="uq_impossible_replacement",
            order_id="ord_paid",
            channel="email",
            destination="buyer@example.com",
            now=200,
        )


def test_dispute_requires_reason_and_preserves_payload_digest(receipt_db):
    first = receipt.publish_delivery_payload(
        quote_id="uq_dispute",
        order_id="ord_dispute",
        payload={"answer": 1},
        now=100,
    )
    with pytest.raises(receipt.DeliveryReceiptError, match="explanation_required"):
        receipt.acknowledge_delivery(
            quote_id="uq_dispute",
            decision="disputed",
            dispute_code="incorrect",
            message="too short",
        )
    disputed = receipt.acknowledge_delivery(
        quote_id="uq_dispute",
        decision="disputed",
        dispute_code="incorrect",
        message="The returned value does not match the requested evidence.",
        now=120,
    )
    assert disputed["state"] == "disputed"
    gate = receipt.settlement_release_receipt_gate("ord_dispute")
    assert gate["release_allowed"] is False
    assert gate["reason"] == "buyer_delivery_dispute_open"
    assert disputed["compensation_state"] == "review_request_pending"
    assert disputed["payload_digest"] == first["payload_digest"]

    with pytest.raises(receipt.DeliveryReceiptError, match="digest_conflict"):
        receipt.publish_delivery_payload(
            quote_id="uq_dispute",
            order_id="ord_dispute",
            payload={"answer": 2},
            now=130,
        )


@pytest.mark.parametrize(
    ("channel", "destination"),
    [
        ("email", "not-an-email"),
        ("webhook", "http://agent.example/deliver"),
        ("webhook", "https://user:password@agent.example/deliver"),
        ("api_pull", "https://unexpected.example"),
    ],
)
def test_invalid_delivery_destinations_fail_closed(receipt_db, channel, destination):
    with pytest.raises(receipt.DeliveryReceiptError):
        receipt.configure_delivery_receipt(
            quote_id=f"uq_{channel}",
            order_id=f"ord_{channel}",
            channel=channel,
            destination=destination,
        )


def test_legacy_order_without_receipt_keeps_existing_release_governance(receipt_db):
    gate = receipt.settlement_release_receipt_gate("legacy-order")

    assert gate["release_allowed"] is True
    assert gate["legacy_compatibility"] is True


def _ready_webhook(tmp_path, monkeypatch):
    keypair = Keypair()
    keyfile = tmp_path / "delivery-keypair.json"
    keyfile.write_text(json.dumps(list(bytes(keypair))), encoding="utf-8")
    monkeypatch.setenv("IAT_DELIVERY_SIGNING_KEYPAIR_PATH", str(keyfile))
    monkeypatch.setattr(
        receipt,
        "validate_public_runtime_url",
        lambda url: {"public": True, "hostname": "buyer.example"},
    )
    receipt.configure_delivery_receipt(
        quote_id="uq_webhook",
        order_id="ord_webhook",
        channel="webhook",
        destination="https://buyer.example/iat-delivery",
        now=100,
    )
    payload = {"status": "success", "result": "verified report"}
    receipt.publish_delivery_payload(
        quote_id="uq_webhook",
        order_id="ord_webhook",
        payload=payload,
        now=110,
    )
    monkeypatch.setattr(
        "iat.checkout_delivery.get_delivery",
        lambda quote_id: {"result": payload},
    )
    return keypair


def test_signed_webhook_marks_delivery_only_after_2xx(receipt_db, tmp_path, monkeypatch):
    keypair = _ready_webhook(tmp_path, monkeypatch)
    observed = {}

    class Response:
        status_code = 202

    def post(url, **kwargs):
        observed["url"] = url
        observed.update(kwargs)
        return Response()

    result = receipt.dispatch_webhook("uq_webhook", now=120, post=post)

    assert result["state"] == "delivered"
    assert result["dispatch_response_code"] == 202
    assert result["dispatch_attempt_count"] == 1
    assert observed["allow_redirects"] is False
    assert observed["headers"]["Idempotency-Key"].startswith("cdr_")
    assert Signature.from_string(
        observed["headers"]["X-IAT-Delivery-Signature"]
    ).verify(Pubkey.from_string(str(keypair.pubkey())), observed["data"])


def test_webhook_failure_is_retried_with_same_receipt_id(receipt_db, tmp_path, monkeypatch):
    _ready_webhook(tmp_path, monkeypatch)
    attempts = []

    class Response:
        status_code = 503

    def post(url, **kwargs):
        attempts.append(
            (kwargs["headers"]["Idempotency-Key"], kwargs["data"])
        )
        return Response()

    first = receipt.dispatch_webhook("uq_webhook", now=120, post=post)
    waiting = receipt.dispatch_webhook("uq_webhook", now=121, post=post)
    second = receipt.dispatch_webhook("uq_webhook", now=150, post=post)

    assert first["state"] == "pending_dispatch"
    assert first["dispatch_next_attempt_at"] == 150
    assert waiting["retry_wait"] is True
    assert second["dispatch_attempt_count"] == 2
    assert attempts[0] == attempts[1]


def _ready_email(tmp_path, monkeypatch):
    keypair = Keypair()
    keyfile = tmp_path / "delivery-email-keypair.json"
    keyfile.write_text(json.dumps(list(bytes(keypair))), encoding="utf-8")
    monkeypatch.setenv("IAT_DELIVERY_SIGNING_KEYPAIR_PATH", str(keyfile))
    monkeypatch.setenv("IAT_DELIVERY_EMAIL_FROM", "IAT Delivery <delivery@iat.example>")
    monkeypatch.setenv("IAT_PUBLIC_SITE_URL", "https://iat.example")
    receipt.configure_delivery_receipt(
        quote_id="uq_email_dispatch",
        order_id="ord_email_dispatch",
        channel="email",
        destination="buyer@example.com",
        now=100,
    )
    payload = {"status": "success", "summary": "A sealed delivery"}
    receipt.publish_delivery_payload(
        quote_id="uq_email_dispatch",
        order_id="ord_email_dispatch",
        payload=payload,
        now=110,
    )
    monkeypatch.setattr(
        "iat.checkout_delivery.get_delivery",
        lambda quote_id: {"result": payload},
    )
    return keypair, payload


def test_signed_email_contains_stable_receipt_and_explicit_decision_link(
    receipt_db, tmp_path, monkeypatch
):
    keypair, payload = _ready_email(tmp_path, monkeypatch)
    messages = []

    result = receipt.dispatch_email(
        "uq_email_dispatch", now=120, send=messages.append
    )

    message = messages[0]
    signature = Signature.from_string(message["X-IAT-Delivery-Signature"])
    canonical = receipt._canonical_payload(payload).encode()
    assert result["state"] == "dispatched"
    assert message["To"] == "buyer@example.com"
    assert signature.verify(keypair.pubkey(), canonical)
    assert "https://iat.example/delivery/#receipt=cdr_" in message.get_content()
    assert "Opening this link does not accept" in message.get_content()
    token = message["X-IAT-Receipt-ID"]
    assert message["X-Mailjet-Campaign"] == token
    assert receipt.get_delivery_receipt_by_token(token)["quote_id"] == "uq_email_dispatch"


def test_mailjet_sent_event_confirms_dispatched_email(receipt_db, tmp_path, monkeypatch):
    _ready_email(tmp_path, monkeypatch)
    messages = []
    dispatched = receipt.dispatch_email(
        "uq_email_dispatch", now=120, send=messages.append
    )

    confirmed = receipt.record_email_provider_event(
        receipt_token=messages[0]["X-IAT-Receipt-ID"],
        recipient="buyer@example.com",
        event="sent",
        event_at=130,
        provider_message_id="mj-123",
    )

    assert dispatched["state"] == "dispatched"
    assert confirmed["state"] == "delivered"
    assert confirmed["provider_status"] == "sent"
    assert receipt.get_delivery_receipt("uq_email_dispatch")["provider_message_id"] == "mj-123"
    assert confirmed["buyer_confirmation_required"] is True


def test_mailjet_event_rejects_recipient_mismatch(receipt_db, tmp_path, monkeypatch):
    _ready_email(tmp_path, monkeypatch)
    messages = []
    receipt.dispatch_email("uq_email_dispatch", now=120, send=messages.append)

    with pytest.raises(
        receipt.DeliveryReceiptError, match="email_provider_recipient_mismatch"
    ):
        receipt.record_email_provider_event(
            receipt_token=messages[0]["X-IAT-Receipt-ID"],
            recipient="attacker@example.com",
            event="sent",
            event_at=130,
        )


def test_mailjet_bounce_fails_dispatched_email(receipt_db, tmp_path, monkeypatch):
    _ready_email(tmp_path, monkeypatch)
    messages = []
    receipt.dispatch_email("uq_email_dispatch", now=120, send=messages.append)

    failed = receipt.record_email_provider_event(
        receipt_token=messages[0]["X-IAT-Receipt-ID"],
        recipient="buyer@example.com",
        event="bounce",
        event_at=130,
        reason="recipient user unknown",
    )

    assert failed["state"] == "dispatch_failed"
    assert failed["provider_status"] == "bounce"
    assert failed["dispatch_last_error"].startswith("email_provider_bounce")


def test_email_failure_retries_with_stable_message_id(receipt_db, tmp_path, monkeypatch):
    _ready_email(tmp_path, monkeypatch)
    message_ids = []

    def fail(message):
        message_ids.append(message["Message-ID"])
        raise receipt.DeliveryReceiptError("delivery_smtp_temporary_failure")

    first = receipt.dispatch_email("uq_email_dispatch", now=120, send=fail)
    second = receipt.dispatch_email("uq_email_dispatch", now=150, send=fail)

    assert first["state"] == "pending_dispatch"
    assert first["dispatch_next_attempt_at"] == 150
    assert second["dispatch_attempt_count"] == 2
    assert message_ids[0] == message_ids[1]
