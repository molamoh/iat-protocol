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
    app.include_router(protocol_evidence.settlement_eligibility_router)
    app.include_router(protocol_evidence.settlement_execution_plan_router)
    app.include_router(protocol_evidence.settlement_authorization_router)
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


def test_accepted_quality_creates_release_eligibility_without_moving_funds(
    tmp_path, monkeypatch
):
    app = evidence_app(tmp_path, monkeypatch)
    payload = signed_payload(Keypair())
    evidence = call(app, "POST", "/protocol/v1/evidence", json=payload).json()
    receipt_token = completed_journey(
        payload,
        acceptance_criteria={"min_sources": 1},
        result={"status": "delivered", "sources": ["source"]},
    )
    open_delivery_inbox(receipt_token, now=NOW - 40)
    delivery = call(
        app, "POST", f"/protocol/v1/delivery-validations/{evidence['receipt_id']}"
    ).json()
    quality = call(
        app, "POST", f"/protocol/v1/quality-validations/{delivery['validation_id']}"
    ).json()
    monkeypatch.setattr(
        db,
        "get_settlement_by_order_id_db",
        lambda order_id: {"settlement_id": "settlement_1", "order_id": order_id},
    )
    eligible = call(
        app, "POST", f"/protocol/v1/settlement-eligibility/{quality['quality_validation_id']}"
    )
    public = call(
        app, "GET", f"/protocol/v1/settlement-eligibility/{quality['quality_validation_id']}"
    )
    assert eligible.status_code == public.status_code == 200
    assert eligible.json() == public.json()
    assert eligible.json()["decision"] == "eligible_for_governed_release"
    assert eligible.json()["settlement_id"] == "settlement_1"
    assert eligible.json()["funds_moved"] is False
    assert eligible.json()["transaction_signed"] is False
    assert eligible.json()["transaction_broadcast"] is False


def test_rejected_quality_creates_compensation_review_eligibility(
    tmp_path, monkeypatch
):
    app = evidence_app(tmp_path, monkeypatch)
    payload = signed_payload(Keypair())
    evidence = call(app, "POST", "/protocol/v1/evidence", json=payload).json()
    receipt_token = completed_journey(
        payload,
        acceptance_criteria={"min_sources": 3},
        result={"status": "delivered", "sources": ["only-one"]},
    )
    open_delivery_inbox(receipt_token, now=NOW - 40)
    delivery = call(
        app, "POST", f"/protocol/v1/delivery-validations/{evidence['receipt_id']}"
    ).json()
    quality = call(
        app, "POST", f"/protocol/v1/quality-validations/{delivery['validation_id']}"
    ).json()
    monkeypatch.setattr(db, "get_settlement_by_order_id_db", lambda _order_id: None)
    eligible = call(
        app, "POST", f"/protocol/v1/settlement-eligibility/{quality['quality_validation_id']}"
    )
    assert eligible.status_code == 200
    assert eligible.json()["decision"] == "eligible_for_compensation_review"
    assert eligible.json()["effect"] == "eligibility_only"
    assert eligible.json()["funds_moved"] is False


def test_release_eligibility_creates_read_only_execution_plan(
    tmp_path, monkeypatch
):
    app = evidence_app(tmp_path, monkeypatch)
    payload = signed_payload(Keypair())
    evidence = call(app, "POST", "/protocol/v1/evidence", json=payload).json()
    receipt_token = completed_journey(
        payload,
        acceptance_criteria={"min_sources": 1},
        result={"status": "delivered", "sources": ["source"]},
    )
    open_delivery_inbox(receipt_token, now=NOW - 40)
    delivery = call(
        app, "POST", f"/protocol/v1/delivery-validations/{evidence['receipt_id']}"
    ).json()
    quality = call(
        app, "POST", f"/protocol/v1/quality-validations/{delivery['validation_id']}"
    ).json()
    settlement = {
        "settlement_id": "settlement_1",
        "order_id": "order_1",
        "winner_wallet": str(Keypair().pubkey()),
        "treasury_wallet": str(Keypair().pubkey()),
        "gross_amount_minor": 1_000_000,
        "protocol_commission_amount_minor": 100_000,
        "seller_payout_amount_minor": 900_000,
    }
    monkeypatch.setattr(
        db, "get_settlement_by_order_id_db", lambda _order_id: settlement
    )
    eligibility = call(
        app,
        "POST",
        f"/protocol/v1/settlement-eligibility/{quality['quality_validation_id']}",
    ).json()

    planned = call(
        app,
        "POST",
        f"/protocol/v1/settlement-execution-plans/{eligibility['eligibility_id']}",
    )
    public = call(
        app,
        "GET",
        f"/protocol/v1/settlement-execution-plans/{eligibility['eligibility_id']}",
    )

    assert planned.status_code == public.status_code == 200
    assert planned.json() == public.json()
    plan = planned.json()
    assert plan["decision"] == "awaiting_governance_authorization"
    assert "foundation_release_authorization_not_evaluated" in plan["blockers"]
    assert "buyer_delivery_confirmation_pending" in plan["blockers"]
    assert plan["gross_amount_minor"] == 1_000_000
    assert plan["protocol_commission_amount_minor"] == 100_000
    assert plan["seller_payout_amount_minor"] == 900_000
    assert len(plan["plan_sha256"]) == 64
    assert plan["effect"] == "planning_only"
    assert plan["execution_enabled"] is False
    assert plan["transaction_built"] is False
    assert plan["simulation_performed"] is False
    assert plan["transaction_signed"] is False
    assert plan["transaction_broadcast"] is False
    assert plan["funds_moved"] is False
    assert "serialized_transaction" not in plan


def test_compensation_eligibility_cannot_create_release_plan(tmp_path, monkeypatch):
    app = evidence_app(tmp_path, monkeypatch)
    connection = db.get_conn()
    try:
        connection.cursor().execute(
            """INSERT INTO protocol_settlement_eligibility (
                eligibility_id, quality_validation_id, delivery_validation_id,
                evidence_receipt_id, evidence_id, order_id, quote_id,
                settlement_id, decision, reason, policy_version,
                eligibility_sha256, evaluated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "pse_compensation", "pqv_compensation", "pdv_1", "per_1",
                "bid_1", "order_1", "quote_1", None,
                "eligible_for_compensation_review", "quality_failed",
                "settlement_eligibility_v1", "f" * 64, NOW,
            ),
        )
        connection.commit()
    finally:
        db.release_conn(connection)
    response = call(
        app, "POST", "/protocol/v1/settlement-execution-plans/pse_compensation"
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "settlement_execution_plan_not_applicable"


def insert_execution_plan(*, blockers=None):
    connection = db.get_conn()
    try:
        connection.cursor().execute(
            """INSERT INTO protocol_settlement_execution_plans (
                plan_id, eligibility_id, quality_validation_id, order_id,
                settlement_id, winner_wallet, treasury_wallet,
                gross_amount_minor, protocol_commission_amount_minor,
                seller_payout_amount_minor, decision, blockers_json,
                receipt_gate_json, policy_version, plan_sha256, evaluated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "psp_authorize", "pse_authorize", "pqv_authorize", "order_1",
                "settlement_1", str(Keypair().pubkey()), str(Keypair().pubkey()),
                1_000_000, 100_000, 900_000,
                "awaiting_governance_authorization",
                json.dumps(blockers or ["foundation_release_authorization_not_evaluated"]),
                json.dumps({"release_allowed": False}),
                "settlement_execution_plan_v1", "e" * 64, NOW,
            ),
        )
        connection.commit()
    finally:
        db.release_conn(connection)


def test_foundation_authorization_is_public_idempotent_and_does_not_execute(
    tmp_path, monkeypatch
):
    app = evidence_app(tmp_path, monkeypatch)
    insert_execution_plan()
    monkeypatch.setattr(
        protocol_evidence,
        "_evaluate_foundation_release",
        lambda order_id: {
            "release_authorized": True,
            "authorized_by": "foundation",
            "authorization_mode": "authorized",
            "authorization_reason": "release_policy_automatic_authorized",
            "financial_release_confidence": 0.93,
            "financial_risk": {"risk_score": 8},
            "final_delivery_receipt": {
                "release_allowed": True,
                "reason": "buyer_accepted_sealed_delivery",
                "receipt_state": "accepted",
                "payload_digest": "d" * 64,
            },
            "order_id": order_id,
        },
    )
    authorized = call(
        app, "POST", "/protocol/v1/settlement-authorizations/psp_authorize"
    )
    public = call(
        app, "GET", "/protocol/v1/settlement-authorizations/psp_authorize"
    )
    repeated = call(
        app, "POST", "/protocol/v1/settlement-authorizations/psp_authorize"
    )
    assert authorized.status_code == public.status_code == repeated.status_code == 200
    assert authorized.json() == public.json() == repeated.json()
    record = authorized.json()
    assert record["release_authorized"] is True
    assert record["authorized_by"] == "foundation"
    assert record["effect"] == "authorization_only"
    assert record["execution_enabled"] is False
    assert record["transaction_built"] is False
    assert record["simulation_performed"] is False
    assert record["transaction_signed"] is False
    assert record["transaction_broadcast"] is False
    assert record["funds_moved"] is False
    assert len(record["authorization_sha256"]) == 64
    assert "foundation_decision" not in record


def test_blocked_foundation_authorization_can_be_retried(tmp_path, monkeypatch):
    app = evidence_app(tmp_path, monkeypatch)
    insert_execution_plan()
    monkeypatch.setattr(
        protocol_evidence,
        "_evaluate_foundation_release",
        lambda _order_id: {
            "release_authorized": False,
            "authorized_by": None,
            "authorization_mode": "blocked",
            "authorization_reason": "buyer_delivery_confirmation_pending",
            "release_block_reasons": ["buyer_delivery_confirmation_pending"],
        },
    )
    blocked = call(
        app, "POST", "/protocol/v1/settlement-authorizations/psp_authorize"
    )
    missing = call(
        app, "GET", "/protocol/v1/settlement-authorizations/psp_authorize"
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "foundation_release_not_authorized"
    assert missing.status_code == 404


def test_structurally_invalid_plan_never_reaches_foundation(tmp_path, monkeypatch):
    app = evidence_app(tmp_path, monkeypatch)
    insert_execution_plan(blockers=["settlement_amount_conservation_failed"])
    called = False

    def evaluate(_order_id):
        nonlocal called
        called = True
        return {"release_authorized": True}

    monkeypatch.setattr(protocol_evidence, "_evaluate_foundation_release", evaluate)
    blocked = call(
        app, "POST", "/protocol/v1/settlement-authorizations/psp_authorize"
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == (
        "settlement_execution_plan_structurally_blocked"
    )
    assert called is False
