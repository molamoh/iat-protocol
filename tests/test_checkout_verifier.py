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
    DIRECT_USDC_PURCHASE_DISCRIMINATOR,
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


def transaction(
    *,
    buyer,
    program,
    payment=None,
    quote_authority=None,
    iat_destination=None,
    direct=False,
):
    if direct:
        if payment is None or iat_destination is None or quote_authority is None:
            raise ValueError(
                "direct transaction requires payment, destination and quote authority"
            )
        addresses = [
            buyer,
            quote_authority,
            Pubkey.new_unique(),
            Pubkey.new_unique(),
            Pubkey.new_unique(),
            payment,
            Pubkey.new_unique(),
            Pubkey.new_unique(),
            Pubkey.new_unique(),
            Pubkey.new_unique(),
            Pubkey.new_unique(),
            iat_destination,
            Pubkey.new_unique(),
            Pubkey.new_unique(),
            Pubkey.new_unique(),
            Pubkey.new_unique(),
        ]
        accounts = [
            AccountMeta(
                address,
                index in {0, 1},
                index in {0, 2, 4, 5, 8, 9, 10, 11},
            )
            for index, address in enumerate(addresses)
        ]
        data = DIRECT_USDC_PURCHASE_DISCRIMINATOR + b"proof"
    else:
        accounts = [AccountMeta(program, False, False)]
        if quote_authority:
            accounts.append(AccountMeta(quote_authority, True, False))
        if payment:
            accounts.append(AccountMeta(payment, False, True))
        if iat_destination:
            accounts.append(AccountMeta(iat_destination, False, True))
        data = b"proof"
    message = Message.new_with_blockhash(
        [Instruction(program, data, accounts)],
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


def test_finalized_signatures_for_address_is_bounded_and_filters_failures():
    valid = str(Signature.default())
    session = Session(
        [
            {
                "jsonrpc": "2.0",
                "result": [
                    {"signature": valid, "err": None},
                    {"signature": str(Signature.new_unique()), "err": {"InstructionError": [0, "Custom"]}},
                    {"signature": "invalid", "err": None},
                    {"signature": valid, "err": None},
                ],
            }
        ]
    )
    verifier = SolanaCheckoutVerifier("https://rpc.example", session=session)

    assert verifier.finalized_signatures_for_address(str(Pubkey.new_unique()), limit=99) == [valid]
    params = session.calls[0][1]["json"]["params"]
    assert params[1] == {"commitment": "finalized", "limit": 10}


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


def test_direct_purchase_requires_buyer_destination_and_quote_authority():
    buyer = Pubkey.new_unique()
    program, payment = Pubkey.new_unique(), Pubkey.new_unique()
    quote_authority = Pubkey.new_unique()
    iat_destination = Pubkey.new_unique()
    config, input_mint = Pubkey.new_unique(), Pubkey.new_unique()
    order_hash = hashlib.sha256(b"direct-order").digest()
    quote_hash = hashlib.sha256(b"direct-quote").digest()
    data = payment_intent_data(
        config=config,
        order_hash=order_hash,
        quote_hash=quote_hash,
        buyer=buyer,
        input_mint=input_mint,
        input_amount=1_507_500,
        iat_amount=150_000_000,
        nonce=77,
    )
    _, encoded = transaction(
        buyer=buyer,
        program=program,
        payment=payment,
        quote_authority=quote_authority,
        iat_destination=iat_destination,
        direct=True,
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
            "delivery_mode": "direct_to_buyer",
            "iat_destination": str(iat_destination),
            "payment_intent": str(payment),
            "order_hash_hex": order_hash.hex(),
            "quote_hash_hex": quote_hash.hex(),
            "input_mint": str(input_mint),
            "input_amount": 1_507_500,
            "iat_amount": 150_000_000,
            "nonce": 77,
        },
    )
    assert result["status"] == "confirmed"


def test_direct_purchase_rejects_missing_buyer_iat_destination():
    buyer = Pubkey.new_unique()
    program, payment = Pubkey.new_unique(), Pubkey.new_unique()
    _, encoded = transaction(buyer=buyer, program=program, payment=payment)
    verifier = SolanaCheckoutVerifier(
        "https://rpc.example",
        session=Session(finalized(encoded)),
    )

    with pytest.raises(
        CheckoutVerificationError,
        match="direct_purchase_instruction_missing",
    ):
        verifier.verify(
            signature=str(Signature.default()),
            route="treasury",
            evidence={
                "buyer_wallet": str(buyer),
                "program_id": str(program),
                "quote_authority": str(buyer),
                "delivery_mode": "direct_to_buyer",
                "iat_destination": str(Pubkey.new_unique()),
                "payment_intent": str(payment),
            },
        )


def test_direct_purchase_rejects_unapproved_quote_signer():
    buyer = Pubkey.new_unique()
    actual_signer = Pubkey.new_unique()
    expected_signer = Pubkey.new_unique()
    program, payment = Pubkey.new_unique(), Pubkey.new_unique()
    iat_destination = Pubkey.new_unique()
    _, encoded = transaction(
        buyer=buyer,
        program=program,
        payment=payment,
        quote_authority=actual_signer,
        iat_destination=iat_destination,
        direct=True,
    )
    verifier = SolanaCheckoutVerifier(
        "https://rpc.example",
        session=Session(finalized(encoded)),
    )

    with pytest.raises(
        CheckoutVerificationError,
        match="treasury_accounts_missing_from_transaction",
    ):
        verifier.verify(
            signature=str(Signature.default()),
            route="treasury",
            evidence={
                "buyer_wallet": str(buyer),
                "program_id": str(program),
                "quote_authority": str(expected_signer),
                "delivery_mode": "direct_to_buyer",
                "iat_destination": str(iat_destination),
                "payment_intent": str(payment),
            },
        )
