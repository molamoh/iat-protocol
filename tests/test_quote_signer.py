import base64
import hashlib
import hmac
import json
import time

import httpx
import pytest
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction

from iat.checkout_solana import SPL_TOKEN_PROGRAM_ID, build_direct_usdc_purchase_plan
from iat.config import IAT_TOKEN_ADDRESS
from iat.quote_signer import (
    LocalDevnetQuoteSigner,
    QuoteSigningRejected,
    verify_quote_authorization,
)
from iat.quote_signer_service import app


NOW = 2_000_000_000


def key():
    return str(Pubkey.new_unique())


def plan(*, buyer, quote_authority):
    return build_direct_usdc_purchase_plan(
        quote={
            "route": "treasury",
            "buyer_wallet": str(buyer),
            "input": {
                "asset": "USDC",
                "mint": key(),
                "amount": "1.005000",
                "amount_minor": 1_005_000,
            },
            "output": {
                "asset": "IAT",
                "mint": IAT_TOKEN_ADDRESS,
                "amount": "1",
                "amount_minor": 100_000_000,
            },
            "expires_at": NOW + 60,
            "intent_hash": hashlib.sha256(b"authorized quote").hexdigest(),
        },
        order_id="ord-signer",
        program_id=key(),
        quote_authority=str(quote_authority),
        treasury_iat_vault=key(),
        treasury_input_vault=key(),
        buyer_input_account=key(),
        buyer_iat_account=key(),
        input_token_program=str(SPL_TOKEN_PROGRAM_ID),
        iat_token_program=str(SPL_TOKEN_PROGRAM_ID),
    )


def instruction(value):
    return Instruction(
        Pubkey.from_string(value["program_id"]),
        base64.b64decode(value["data_base64"]),
        [
            AccountMeta(
                Pubkey.from_string(item["address"]),
                item["signer"],
                item["writable"],
            )
            for item in value["accounts"]
        ],
    )


def encoded_transaction(value, *, extra=None):
    instructions = []
    if extra is not None:
        instructions.append(extra)
    instructions.append(instruction(value["execute"]))
    message = Message.new_with_blockhash(
        instructions,
        Pubkey.from_string(value["fee_payer"]),
        Hash.from_string("11111111111111111111111111111112"),
    )
    signatures = [Signature.default()] * message.header.num_required_signatures
    return base64.b64encode(
        bytes(VersionedTransaction.populate(message, signatures))
    ).decode()


def test_signer_adds_only_the_quote_authority_signature():
    buyer = Keypair()
    authority = Keypair()
    value = plan(buyer=buyer.pubkey(), quote_authority=authority.pubkey())
    signer = LocalDevnetQuoteSigner(authority, cluster="devnet")

    result = signer.sign(
        transaction_base64=encoded_transaction(value),
        instruction_plan=value,
        expires_at=NOW + 60,
        now=NOW,
    )

    transaction = VersionedTransaction.from_bytes(
        base64.b64decode(result.transaction_base64)
    )
    signers = list(transaction.message.account_keys)[
        : transaction.message.header.num_required_signatures
    ]
    authority_index = signers.index(authority.pubkey())
    buyer_index = signers.index(buyer.pubkey())
    assert transaction.signatures[authority_index].verify(
        authority.pubkey(),
        bytes(transaction.message),
    )
    assert transaction.signatures[buyer_index] == Signature.default()
    assert result.quote_authority == str(authority.pubkey())
    assert verify_quote_authorization(
        original_transaction_base64=encoded_transaction(value),
        authorized_transaction_base64=result.transaction_base64,
        quote_authority=str(authority.pubkey()),
    ) == result.message_hash


def test_signer_rejects_any_unapproved_instruction():
    buyer = Keypair()
    authority = Keypair()
    value = plan(buyer=buyer.pubkey(), quote_authority=authority.pubkey())
    extra = transfer(
        TransferParams(
            from_pubkey=buyer.pubkey(),
            to_pubkey=Pubkey.new_unique(),
            lamports=1,
        )
    )

    with pytest.raises(QuoteSigningRejected, match="unapproved_instruction"):
        LocalDevnetQuoteSigner(authority, cluster="devnet").sign(
            transaction_base64=encoded_transaction(value, extra=extra),
            instruction_plan=value,
            expires_at=NOW + 60,
            now=NOW,
        )


def test_signer_rejects_wrong_authority_and_expired_quote():
    buyer = Keypair()
    authority = Keypair()
    value = plan(buyer=buyer.pubkey(), quote_authority=authority.pubkey())
    encoded = encoded_transaction(value)

    with pytest.raises(QuoteSigningRejected, match="quote_authority_signer_mismatch"):
        LocalDevnetQuoteSigner(Keypair(), cluster="devnet").sign(
            transaction_base64=encoded,
            instruction_plan=value,
            expires_at=NOW + 60,
            now=NOW,
        )
    with pytest.raises(QuoteSigningRejected, match="quote_expired"):
        LocalDevnetQuoteSigner(authority, cluster="devnet").sign(
            transaction_base64=encoded,
            instruction_plan=value,
            expires_at=NOW,
            now=NOW,
        )


def test_local_backend_is_forbidden_outside_devnet():
    with pytest.raises(QuoteSigningRejected, match="devnet_only"):
        LocalDevnetQuoteSigner(Keypair(), cluster="mainnet-beta")


@pytest.mark.anyio
async def test_private_service_authenticates_and_is_idempotent(
    tmp_path,
    monkeypatch,
):
    buyer = Keypair()
    authority = Keypair()
    value = plan(buyer=buyer.pubkey(), quote_authority=authority.pubkey())
    keypair_path = tmp_path / "quote-authority.json"
    keypair_path.write_text(json.dumps(list(bytes(authority))), encoding="utf-8")
    secret = "s" * 32
    monkeypatch.setenv("IAT_QUOTE_SIGNER_ENABLED", "true")
    monkeypatch.setenv("IAT_QUOTE_SIGNER_ALLOW_LOCAL_KEYPAIR", "true")
    monkeypatch.setenv("IAT_QUOTE_SIGNER_CLUSTER", "devnet")
    monkeypatch.setenv("IAT_QUOTE_SIGNER_KEYPAIR_PATH", str(keypair_path))
    monkeypatch.setenv("IAT_QUOTE_SIGNER_SHARED_SECRET", secret)
    monkeypatch.setattr("iat.quote_signer_service._now", lambda: NOW)
    payload = {
        "request_id": "request_1234567890",
        "quote_id": "uq_" + "a" * 32,
        "expires_at": NOW + 60,
        "transaction_base64": encoded_transaction(value),
        "instruction_plan": value,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = str(NOW)
    signature = hmac.new(
        secret.encode(),
        timestamp.encode() + b"." + raw,
        hashlib.sha256,
    ).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-IAT-Signer-Timestamp": timestamp,
        "X-IAT-Signer-Signature": signature,
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        first = await client.post("/v1/sign", content=raw, headers=headers)
        second = await client.post("/v1/sign", content=raw, headers=headers)

    assert first.status_code == 200
    assert first.json()["status"] == "signed"
    assert first.json()["idempotent"] is False
    assert second.status_code == 200
    assert second.json()["idempotent"] is True


@pytest.mark.anyio
async def test_private_service_logs_only_sanitized_rejection_reason(
    monkeypatch, caplog
):
    monkeypatch.setenv("IAT_QUOTE_SIGNER_SHARED_SECRET", "s" * 32)
    monkeypatch.setattr("iat.quote_signer_service._now", lambda: NOW)
    payload = {
        "request_id": "request_1234567890",
        "quote_id": "uq_" + "a" * 32,
        "expires_at": NOW + 60,
        "transaction_base64": "A" * 64,
        "instruction_plan": {},
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()

    with caplog.at_level("WARNING", logger="iat.quote_signer"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/sign",
                content=raw,
                headers={
                    "X-IAT-Signer-Timestamp": str(NOW),
                    "X-IAT-Signer-Signature": "0" * 64,
                },
            )

    assert response.status_code == 403
    assert "quote_signer_rejected reason=invalid_auth_signature" in caplog.text
    assert raw.decode() not in caplog.text


@pytest.mark.anyio
async def test_private_service_rejects_invalid_hmac(monkeypatch):
    monkeypatch.setenv("IAT_QUOTE_SIGNER_SHARED_SECRET", "s" * 32)
    timestamp = str(int(time.time()))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/v1/sign",
            content=b"{}",
            headers={
                "Content-Type": "application/json",
                "X-IAT-Signer-Timestamp": timestamp,
                "X-IAT-Signer-Signature": "0" * 64,
            },
        )
    assert response.status_code == 403
    assert response.json()["detail"] == "invalid_auth_signature"
