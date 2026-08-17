import asyncio

import httpx
from fastapi import FastAPI
from solders.keypair import Keypair

from iat.api import db
from iat.api import protocol_evidence
from iat.attested_wallet_signer import build_evidence_message


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
    return app


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
