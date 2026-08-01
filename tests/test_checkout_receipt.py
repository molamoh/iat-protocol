import sqlite3

import pytest

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
