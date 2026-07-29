import base64
import hashlib

import pytest
from solders.pubkey import Pubkey

from iat.checkout_solana import (
    build_set_paused_plan,
    SPL_TOKEN_PROGRAM_ID,
    SolanaPlanError,
    build_direct_usdc_purchase_plan,
    build_treasury_instruction_plan,
)
from iat.config import IAT_TOKEN_ADDRESS


def key():
    return str(Pubkey.new_unique())


def quote(**overrides):
    value = {
        "route": "treasury",
        "buyer_wallet": key(),
        "input": {
            "asset": "USDC",
            "mint": key(),
            "amount": "2.500000",
            "amount_minor": 2_500_000,
        },
        "output": {
            "asset": "IAT",
            "mint": IAT_TOKEN_ADDRESS,
            "amount": "10",
            "amount_minor": 1_000_000_000,
        },
        "expires_at": 2_000_000_060,
        "intent_hash": hashlib.sha256(b"quote").hexdigest(),
    }
    value.update(overrides)
    return value


def build(value=None, **overrides):
    values = {
        "quote": value or quote(),
        "order_id": "ord-123",
        "program_id": key(),
        "quote_authority": key(),
        "treasury_iat_vault": key(),
        "settlement_escrow": key(),
        "treasury_input_vault": key(),
        "buyer_input_account": key(),
        "input_token_program": str(SPL_TOKEN_PROGRAM_ID),
        "iat_token_program": str(SPL_TOKEN_PROGRAM_ID),
    }
    values.update(overrides)
    return build_treasury_instruction_plan(**values)


def test_plan_is_deterministic_unsigned_and_human_reviewable():
    value = quote()
    inputs = {
        "quote": value,
        "program_id": key(),
        "quote_authority": key(),
        "treasury_iat_vault": key(),
        "settlement_escrow": key(),
        "treasury_input_vault": key(),
        "buyer_input_account": key(),
    }
    first = build(**inputs)
    second = build(**inputs)

    assert first == second
    assert first["buyer_signature_required"] is True
    assert first["protocol_authorization_signature_required"] is True
    assert first["server_holds_quote_authority_key"] is False
    assert first["simulation_required"] is True
    assert first["display"]["input_amount"] == "2.500000"
    assert first["display"]["iat_amount"] == "10"
    assert len(base64.b64decode(first["execute"]["data_base64"])) == 104


def test_payment_pda_changes_with_order_buyer_and_quote():
    first = build()
    second = build(quote(intent_hash=hashlib.sha256(b"other").hexdigest()))

    assert (
        first["derived_accounts"]["payment_intent"]
        != second["derived_accounts"]["payment_intent"]
    )


def test_wallet_usage_initialization_is_explicit_not_init_if_needed():
    plan = build()
    prerequisite = plan["wallet_usage_prerequisite"]

    assert prerequisite["include_only_when_account_is_missing"] is True
    assert prerequisite["query_account"] == plan["derived_accounts"]["wallet_usage"]
    assert len(base64.b64decode(prerequisite["data_base64"])) == 8


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("program_id", "invalid", "invalid_program_id"),
        ("input_token_program", "11111111111111111111111111111111", "unsupported_token_program"),
    ],
)
def test_plan_rejects_invalid_programs(field, value, reason):
    with pytest.raises(SolanaPlanError, match=reason):
        build(**{field: value})


def test_raydium_quote_cannot_enter_treasury_program():
    with pytest.raises(SolanaPlanError, match="treasury_route_required"):
        build(quote(route="raydium"))


def test_direct_usdc_purchase_needs_only_buyer_and_delivers_to_buyer_account():
    value = quote()
    buyer_iat = key()
    plan = build_direct_usdc_purchase_plan(
        quote=value,
        order_id="ord-direct",
        program_id=key(),
        treasury_iat_vault=key(),
        treasury_input_vault=key(),
        buyer_input_account=key(),
        buyer_iat_account=buyer_iat,
        input_token_program=str(SPL_TOKEN_PROGRAM_ID),
        iat_token_program=str(SPL_TOKEN_PROGRAM_ID),
    )

    assert plan["buyer_signature_required"] is True
    assert plan["protocol_authorization_signature_required"] is False
    assert plan["delivery_mode"] == "direct_to_buyer"
    assert plan["display"]["iat_destination"] == buyer_iat
    assert plan["display"]["iat_recipient_owner"] == value["buyer_wallet"]
    prerequisite = plan["buyer_iat_account_prerequisite"]
    assert prerequisite["query_account"] == buyer_iat
    assert prerequisite["include_only_when_account_is_missing"] is True
    assert prerequisite["data_base64"] == ""
    assert len(plan["execute"]["accounts"]) == 15
    assert [item for item in plan["execute"]["accounts"] if item["signer"]] == [
        {
            "address": value["buyer_wallet"],
            "signer": True,
            "writable": True,
        }
    ]
    assert len(base64.b64decode(plan["execute"]["data_base64"])) == 104


def test_direct_purchase_rejects_non_usdc_input():
    value = quote()
    value["input"]["asset"] = "SOL"
    with pytest.raises(SolanaPlanError, match="usdc_input_required"):
        build_direct_usdc_purchase_plan(
            quote=value,
            order_id="ord-direct",
            program_id=key(),
            treasury_iat_vault=key(),
            treasury_input_vault=key(),
            buyer_input_account=key(),
            buyer_iat_account=key(),
            input_token_program=str(SPL_TOKEN_PROGRAM_ID),
            iat_token_program=str(SPL_TOKEN_PROGRAM_ID),
        )


def test_pause_plan_is_unsigned_deterministic_and_transfers_no_funds():
    program = key()
    authority = key()

    plan = build_set_paused_plan(
        program_id=program,
        authority=authority,
        paused=True,
    )

    assert plan["signature_required"] is True
    assert plan["simulation_required"] is True
    assert plan["funds_transfer"] is False
    assert plan["display"]["paused"] is True
    assert plan["instruction"]["accounts"][1] == {
        "address": authority,
        "signer": True,
        "writable": False,
    }
    data = base64.b64decode(plan["instruction"]["data_base64"])
    assert data[:8] == hashlib.sha256(b"global:set_paused").digest()[:8]
    assert data[8:] == b"\x01"
