import asyncio
import json

import httpx
from fastapi import FastAPI
from solders.keypair import Keypair

from iat.api import db
from iat.api import protocol_evidence
from iat.api.checkout_api import init_checkout_db
from iat.attested_wallet_signer import build_evidence_message
from iat.buyer_identity import init_wallet_identity_db
from iat.checkout_receipt import (
    configure_delivery_receipt,
    open_delivery_inbox,
    publish_delivery_payload,
)


NOW = 1_800_000_000


def call(app, method, path, **kwargs):
    async def request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://iat") as api:
            return await api.request(method, path, **kwargs)

    return asyncio.run(request())


def signed_payload(keypair, *, evidence_id="bid_1", digest="a" * 64, observed_at=NOW):
    wallet = str(keypair.pubkey())
    payload = {
        "evidence_type": "buyer_job_journal",
        "evidence_id": evidence_id,
        "evidence_sha256": digest,
        "observed_at": observed_at,
        "wallet_address": wallet,
    }
    message = build_evidence_message(wallet, **{
        key: payload[key]
        for key in ("evidence_type", "evidence_id", "evidence_sha256", "observed_at")
    })
    payload["signature"] = str(keypair.sign_message(message))
    return payload


def evidence_app(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "protocol.sqlite3")
    monkeypatch.setattr(db, "USE_POSTGRES", False)
    monkeypatch.setattr(db, "pool", None)
    monkeypatch.setattr(protocol_evidence, "_now", lambda: NOW)
    protocol_evidence.init_protocol_evidence_db()
    app = FastAPI()
    app.include_router(protocol_evidence.router)
    app.include_router(protocol_evidence.validation_router)
    app.include_router(protocol_evidence.quality_router)
    return app


def completed_journey(payload, *, acceptance_criteria=None, result=None):
    init_wallet_identity_db()
    init_checkout_db()
    connection = db.get_conn()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """INSERT INTO buyer_intent_decisions (
                intent_decision_id, wallet, idempotency_key, request_hash,
                request_json, selection_json, created_at, expires_at, consumed_at,
                order_id
            ) VALUES (?, ?, ?, ?, ?, '{}', ?, ?, ?, ?)""",
            (
                payload["evidence_id"], payload["wallet_address"], "idem_12345678",
                "request_hash",
                json.dumps({"acceptance_criteria": acceptance_criteria}),
                NOW - 100, NOW + 100, NOW - 90, "order_1",
            ),
        )
        cursor.execute(
            """INSERT INTO universal_checkout_quotes (
                quote_id, order_id, buyer_wallet, input_asset, route, required_iat,
                state, intent_hash, request_hash, idempotency_key, quote_payload,
                created_at, expires_at, updated_at, tx_signature
            ) VALUES (?, ?, ?, 'USDC', 'direct', '1', 'confirmed', 'intent',
                      'request', 'quote_idem_1', '{}', ?, ?, ?, ?)""",
            (
                "quote_1", "order_1", payload["wallet_address"], NOW - 80,
                NOW + 100, NOW - 70, "3" * 88,
            ),
        )
        cursor.execute(
            """INSERT INTO universal_checkout_deliveries (
                quote_id, order_id, tx_signature, state, attempt_count,
                next_attempt_at, settlement_state, created_at, updated_at,
                completed_at
            ) VALUES (?, ?, ?, 'completed', 1, ?, 'completed', ?, ?, ?)""",
            ("quote_1", "order_1", "3" * 88, NOW - 70, NOW - 70, NOW - 60, NOW - 60),
        )
        connection.commit()
    finally:
        db.release_conn(connection)
    configured = configure_delivery_receipt(
        quote_id="quote_1", order_id="order_1", channel="api_pull",
        destination=None, now=NOW - 60,
    )
    publish_delivery_payload(
        quote_id="quote_1", order_id="order_1",
        payload=result or {"status": "delivered"},
        now=NOW - 50,
    )
    return configured["receipt_token"]


def test_signed_evidence_is_public_and_idempotent(tmp_path, monkeypatch):
    app = evidence_app(tmp_path, monkeypatch)
    payload = signed_payload(Keypair())
    first = call(app, "POST", "/protocol/v1/evidence", json=payload)
    repeated = call(app, "POST", "/protocol/v1/evidence", json=payload)
    public = call(
        app,
        "GET",
        f"/protocol/v1/evidence/bid_1?wallet_address={payload['wallet_address']}",
    )
    assert first.status_code == repeated.status_code == public.status_code == 200
    assert first.json() == repeated.json() == public.json()
    assert first.json()["effect"] == "evidence_only"
    assert first.json()["receipt_id"].startswith("per_")
    assert len(first.json()["receipt_sha256"]) == 64


def test_invalid_signature_and_stale_evidence_are_rejected(tmp_path, monkeypatch):
    app = evidence_app(tmp_path, monkeypatch)
    payload = signed_payload(Keypair())
    payload["signature"] = signed_payload(Keypair())["signature"]
    invalid = call(app, "POST", "/protocol/v1/evidence", json=payload)
    stale = call(
        app,
        "POST",
        "/protocol/v1/evidence",
        json=signed_payload(Keypair(), evidence_id="bid_old", observed_at=NOW - 86_401),
    )
    assert invalid.status_code == 403
    assert invalid.json()["detail"] == "protocol_evidence_signature_invalid"
    assert stale.status_code == 422
    assert stale.json()["detail"] == "protocol_evidence_expired"


def test_existing_identity_cannot_be_rewritten_with_another_digest(tmp_path, monkeypatch):
    app = evidence_app(tmp_path, monkeypatch)
    keypair = Keypair()
    first = call(app, "POST", "/protocol/v1/evidence", json=signed_payload(keypair))
    conflict = call(
        app,
        "POST",
        "/protocol/v1/evidence",
        json=signed_payload(keypair, digest="b" * 64),
    )
    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "protocol_evidence_conflict"


def test_unknown_evidence_is_not_disclosed_as_present(tmp_path, monkeypatch):
    app = evidence_app(tmp_path, monkeypatch)
    wallet = str(Keypair().pubkey())
    response = call(
        app,
        "GET",
        f"/protocol/v1/evidence/missing?wallet_address={wallet}",
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "protocol_evidence_not_found"


def test_delivery_binding_requires_opening_then_becomes_public(tmp_path, monkeypatch):
    app = evidence_app(tmp_path, monkeypatch)
    payload = signed_payload(Keypair())
    evidence = call(app, "POST", "/protocol/v1/evidence", json=payload).json()
    receipt_token = completed_journey(payload)
    pending = call(
        app, "POST", f"/protocol/v1/delivery-validations/{evidence['receipt_id']}"
    )
    assert pending.status_code == 409
    assert pending.json()["detail"] == "delivery_validation_inbox_not_opened"
    open_delivery_inbox(receipt_token, now=NOW - 40)
    validated = call(
        app, "POST", f"/protocol/v1/delivery-validations/{evidence['receipt_id']}"
    )
    public = call(
        app, "GET", f"/protocol/v1/delivery-validations/{evidence['receipt_id']}"
    )
    assert validated.status_code == public.status_code == 200
    assert validated.json() == public.json()
    assert validated.json()["decision"] == "verified_delivery_binding"
    assert validated.json()["quality_verified"] is False
    assert validated.json()["effect"] == "evidence_only"
    assert len(validated.json()["validation_sha256"]) == 64


def test_changed_sealed_delivery_is_rejected_and_recorded(tmp_path, monkeypatch):
    app = evidence_app(tmp_path, monkeypatch)
    payload = signed_payload(Keypair())
    evidence = call(app, "POST", "/protocol/v1/evidence", json=payload).json()
    receipt_token = completed_journey(payload)
    open_delivery_inbox(receipt_token, now=NOW - 40)
    connection = db.get_conn()
    try:
        connection.cursor().execute(
            "UPDATE universal_checkout_delivery_receipts SET sealed_payload='tampered' WHERE quote_id='quote_1'"
        )
        connection.commit()
    finally:
        db.release_conn(connection)
    rejected = call(
        app, "POST", f"/protocol/v1/delivery-validations/{evidence['receipt_id']}"
    )
    assert rejected.status_code == 200
    assert rejected.json()["decision"] == "rejected_delivery_binding"
    assert rejected.json()["reason"] == "delivery_payload_digest_invalid"


def test_explicit_quality_criteria_are_evaluated_without_content_disclosure(
    tmp_path, monkeypatch
):
    app = evidence_app(tmp_path, monkeypatch)
    payload = signed_payload(Keypair())
    evidence = call(app, "POST", "/protocol/v1/evidence", json=payload).json()
    receipt_token = completed_journey(
        payload,
        acceptance_criteria={"required_result_fields": ["summary", "sources"], "min_sources": 2},
        result={"status": "delivered", "summary": "private analysis", "sources": ["a", "b"]},
    )
    open_delivery_inbox(receipt_token, now=NOW - 40)
    delivery = call(
        app, "POST", f"/protocol/v1/delivery-validations/{evidence['receipt_id']}"
    ).json()
    quality = call(
        app, "POST", f"/protocol/v1/quality-validations/{delivery['validation_id']}"
    )
    public = call(
        app, "GET", f"/protocol/v1/quality-validations/{delivery['validation_id']}"
    )
    assert quality.status_code == public.status_code == 200
    assert quality.json() == public.json()
    assert quality.json()["decision"] == "accepted_by_explicit_criteria"
    assert quality.json()["content_disclosed"] is False
    assert "private analysis" not in str(quality.json())


def test_quality_validation_requires_predeclared_criteria(tmp_path, monkeypatch):
    app = evidence_app(tmp_path, monkeypatch)
    payload = signed_payload(Keypair())
    evidence = call(app, "POST", "/protocol/v1/evidence", json=payload).json()
    receipt_token = completed_journey(payload)
    open_delivery_inbox(receipt_token, now=NOW - 40)
    delivery = call(
        app, "POST", f"/protocol/v1/delivery-validations/{evidence['receipt_id']}"
    ).json()
    quality = call(
        app, "POST", f"/protocol/v1/quality-validations/{delivery['validation_id']}"
    )
    assert quality.status_code == 409
    assert quality.json()["detail"] == "acceptance_criteria_not_declared"
