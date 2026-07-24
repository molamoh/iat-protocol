import base64
import hashlib
import struct

import pytest
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.message import Message
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from iat.checkout_verifier import (
    PAYMENT_INTENT_DISCRIMINATOR,
    CheckoutVerificationError,
    SolanaCheckoutVerifier,
    decode_payment_intent,
    message_hash_from_transaction_base64,
)


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response(self.responses.pop(0))


def transaction(*, buyer, program, payment=None, quote_authority=None):
    accounts = [AccountMeta(program, False, False)]
    if quote_authority:
        accounts.append(AccountMeta(quote_authority, True, False))
    if payment:
        accounts.append(AccountMeta(payment, False, True))
    message = Message.new_with_blockhash(
        [Instruction(program, b"proof", accounts)],
        buyer,
        Hash.default(),
    )
    signatures = [Signature.default()] * (2 if quote_authority else 1)
    tx = VersionedTransaction.populate(message, signatures)
    return tx, base64.b64encode(bytes(tx)).decode()


def finalized(encoded, account=None):
    responses = [
        {
            "jsonrpc": "2.0",
            "result": {
                "value": [
                    {
                        "err": None,
                        "confirmationStatus": "finalized",
                    }
                ]
            },
        },
        {
            "jsonrpc": "2.0",
            "result": {
                "blockTime": 2_000_000_000,
                "transaction": [encoded, "base64"],
            },
        },
    ]
    if account is not None:
        responses.append(
            {"jsonrpc": "2.0", "result": {"value": account}}
        )
    return responses


def payment_intent_data(
    *,
    config,
    order_hash,
    quote_hash,
    buyer,
    input_mint,
    input_amount,
    iat_amount,
    nonce,
    executed_at=2_000_000_000,
    bump=255,
):
    return b"".join(
        [
            PAYMENT_INTENT_DISCRIMINATOR,
            bytes(config),
            order_hash,
            quote_hash,
            bytes(buyer),
            bytes(input_mint),
            struct.pack("<QQQqB", input_amount, iat_amount, nonce, executed_at, bump),
        ]
    )


def test_raydium_confirmation_requires_exact_prepared_message():
    buyer, program = Pubkey.new_unique(), Pubkey.new_unique()
    tx, encoded = transaction(buyer=buyer, program=program)
    verifier = SolanaCheckoutVerifier(
        "https://rpc.example",
        session=Session(finalized(encoded)),
    )
    result = verifier.verify(
        signature=str(Signature.default()),
        route="raydium",
        evidence={
            "buyer_wallet": str(buyer),
            "message_hash": hashlib.sha256(bytes(tx.message)).hexdigest(),
        },
    )

    assert result["status"] == "confirmed"
    assert result["finalized"] is True
    assert result["message_hash"] == message_hash_from_transaction_base64(encoded)


def test_raydium_modified_transaction_is_rejected():
    buyer, program = Pubkey.new_unique(), Pubkey.new_unique()
    _, encoded = transaction(buyer=buyer, program=program)
    verifier = SolanaCheckoutVerifier(
        "https://rpc.example",
        session=Session(finalized(encoded)),
    )
    with pytest.raises(
        CheckoutVerificationError,
        match="raydium_message_hash_mismatch",
    ):
        verifier.verify(
            signature=str(Signature.default()),
            route="raydium",
            evidence={"buyer_wallet": str(buyer), "message_hash": "00" * 32},
        )


def test_unfinalized_transaction_is_retryable_not_accepted():
    verifier = SolanaCheckoutVerifier(
        "https://rpc.example",
        session=Session(
            [
                {
                    "jsonrpc": "2.0",
                    "result": {
                        "value": [
                            {
                                "err": None,
                                "confirmationStatus": "confirmed",
                            }
                        ]
                    },
                }
            ]
        ),
    )
    with pytest.raises(CheckoutVerificationError) as pending:
        verifier.verify(
            signature=str(Signature.default()),
            route="raydium",
            evidence={"buyer_wallet": str(Pubkey.new_unique())},
        )
    assert pending.value.code == "transaction_not_finalized"
    assert pending.value.retryable is True


def test_treasury_confirmation_decodes_exact_anchor_payment_intent():
    buyer = Pubkey.new_unique()
    program, payment = Pubkey.new_unique(), Pubkey.new_unique()
    quote_authority = Pubkey.new_unique()
    config, input_mint = Pubkey.new_unique(), Pubkey.new_unique()
    order_hash = hashlib.sha256(b"order").digest()
    quote_hash = hashlib.sha256(b"quote").digest()
    data = payment_intent_data(
        config=config,
        order_hash=order_hash,
        quote_hash=quote_hash,
        buyer=buyer,
        input_mint=input_mint,
        input_amount=2_500_000,
        iat_amount=1_000_000_000,
        nonce=42,
    )
    proof = decode_payment_intent(data)
    assert proof.buyer == str(buyer)
    tx, encoded = transaction(
        buyer=buyer,
        program=program,
        payment=payment,
        quote_authority=quote_authority,
    )
    verifier = SolanaCheckoutVerifier(
        "https://rpc.example",
        session=Session(
            finalized(
                encoded,
                {
                    "owner": str(program),
                    "executable": False,
                    "data": [base64.b64encode(data).decode(), "base64"],
                },
            )
        ),
    )
    result = verifier.verify(
        signature=str(Signature.default()),
        route="treasury",
        evidence={
            "buyer_wallet": str(buyer),
            "program_id": str(program),
            "quote_authority": str(quote_authority),
            "payment_intent": str(payment),
            "order_hash_hex": order_hash.hex(),
            "quote_hash_hex": quote_hash.hex(),
            "input_mint": str(input_mint),
            "input_amount": 2_500_000,
            "iat_amount": 1_000_000_000,
            "nonce": 42,
        },
    )
    assert result["status"] == "confirmed"


def test_treasury_tampered_payment_intent_is_rejected():
    buyer = Pubkey.new_unique()
    program, payment = Pubkey.new_unique(), Pubkey.new_unique()
    quote_authority = Pubkey.new_unique()
    config, input_mint = Pubkey.new_unique(), Pubkey.new_unique()
    data = payment_intent_data(
        config=config,
        order_hash=hashlib.sha256(b"order").digest(),
        quote_hash=hashlib.sha256(b"quote").digest(),
        buyer=buyer,
        input_mint=input_mint,
        input_amount=1,
        iat_amount=2,
        nonce=3,
    )
    _, encoded = transaction(
        buyer=buyer,
        program=program,
        payment=payment,
        quote_authority=quote_authority,
    )
    verifier = SolanaCheckoutVerifier(
        "https://rpc.example",
        session=Session(
            finalized(
                encoded,
                {
                    "owner": str(program),
                    "executable": False,
                    "data": [base64.b64encode(data).decode(), "base64"],
                },
            )
        ),
    )
    with pytest.raises(
        CheckoutVerificationError,
        match="payment_intent_evidence_mismatch",
    ):
        verifier.verify(
            signature=str(Signature.default()),
            route="treasury",
            evidence={
                "buyer_wallet": str(buyer),
                "program_id": str(program),
                "quote_authority": str(quote_authority),
                "payment_intent": str(payment),
                "order_hash_hex": hashlib.sha256(b"other-order").hexdigest(),
                "quote_hash_hex": hashlib.sha256(b"quote").hexdigest(),
                "input_mint": str(input_mint),
                "input_amount": 1,
                "iat_amount": 2,
                "nonce": 3,
            },
        )
