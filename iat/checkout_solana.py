"""Build deterministic Anchor instruction plans without holding buyer keys."""

from __future__ import annotations

import base64
import hashlib
import struct
from typing import Any, Mapping

from solders.pubkey import Pubkey

from iat.config import IAT_TOKEN_ADDRESS


SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")
SPL_TOKEN_PROGRAM_ID = Pubkey.from_string(
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
)
TOKEN_2022_PROGRAM_ID = Pubkey.from_string(
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
)
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string(
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
)
ALLOWED_TOKEN_PROGRAMS = {SPL_TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID}


class SolanaPlanError(ValueError):
    pass


def _pubkey(value: Any, field: str) -> Pubkey:
    try:
        return Pubkey.from_string(str(value or "").strip())
    except Exception as exc:
        raise SolanaPlanError(f"invalid_{field}") from exc


def _pda(program_id: Pubkey, *seeds: bytes) -> Pubkey:
    return Pubkey.find_program_address(list(seeds), program_id)[0]


def _meta(address: Pubkey, *, signer: bool = False, writable: bool = False) -> dict[str, Any]:
    return {
        "address": str(address),
        "signer": signer,
        "writable": writable,
    }


def _discriminator(name: str) -> bytes:
    return hashlib.sha256(f"global:{name}".encode()).digest()[:8]


def build_set_paused_plan(
    *,
    program_id: str,
    authority: str,
    paused: bool,
) -> dict[str, Any]:
    """Build the deterministic admin pause instruction without signing it."""
    program = _pubkey(program_id, "program_id")
    admin = _pubkey(authority, "authority")
    config = _pda(program, b"config")
    data = _discriminator("set_paused") + struct.pack("<?", bool(paused))
    return {
        "program_id": str(program),
        "network": "solana-devnet",
        "fee_payer": str(admin),
        "signature_required": True,
        "simulation_required": True,
        "funds_transfer": False,
        "instruction": {
            "program_id": str(program),
            "accounts": [
                _meta(config, writable=True),
                _meta(admin, signer=True),
            ],
            "data_base64": base64.b64encode(data).decode(),
        },
        "display": {
            "action": "set_paused",
            "paused": bool(paused),
            "config": str(config),
            "authority": str(admin),
        },
    }


def build_update_asset_plan(
    *,
    program_id: str,
    authority: str,
    input_mint: str,
    ratio_numerator: int,
    ratio_denominator: int,
    max_order_iat: int,
    valid_until: int,
    enabled: bool,
) -> dict[str, Any]:
    """Build a deterministic admin asset-policy instruction without signing."""
    program = _pubkey(program_id, "program_id")
    admin = _pubkey(authority, "authority")
    mint = _pubkey(input_mint, "input_mint")
    if min(
        int(ratio_numerator),
        int(ratio_denominator),
        int(max_order_iat),
        int(valid_until),
    ) <= 0:
        raise SolanaPlanError("invalid_asset_policy")
    config = _pda(program, b"config")
    asset = _pda(program, b"asset", bytes(config), bytes(mint))
    data = _discriminator("update_asset") + struct.pack(
        "<QQQq?",
        int(ratio_numerator),
        int(ratio_denominator),
        int(max_order_iat),
        int(valid_until),
        bool(enabled),
    )
    return {
        "program_id": str(program),
        "network": "solana-devnet",
        "fee_payer": str(admin),
        "signature_required": True,
        "simulation_required": True,
        "funds_transfer": False,
        "instruction": {
            "program_id": str(program),
            "accounts": [
                _meta(config),
                _meta(admin, signer=True),
                _meta(asset, writable=True),
            ],
            "data_base64": base64.b64encode(data).decode(),
        },
        "display": {
            "action": "update_asset",
            "config": str(config),
            "asset": str(asset),
            "input_mint": str(mint),
            "ratio_numerator": int(ratio_numerator),
            "ratio_denominator": int(ratio_denominator),
            "max_order_iat": int(max_order_iat),
            "valid_until": int(valid_until),
            "enabled": bool(enabled),
            "authority": str(admin),
        },
    }


def build_treasury_instruction_plan(
    *,
    quote: Mapping[str, Any],
    order_id: str,
    program_id: str,
    quote_authority: str,
    treasury_iat_vault: str,
    settlement_escrow: str,
    treasury_input_vault: str,
    buyer_input_account: str,
    input_token_program: str,
    iat_token_program: str,
) -> dict[str, Any]:
    """Build Anchor instruction bytes and canonical accounts for wallet clients."""

    if quote.get("route") != "treasury":
        raise SolanaPlanError("treasury_route_required")
    buyer = _pubkey(quote.get("buyer_wallet"), "buyer_wallet")
    program = _pubkey(program_id, "program_id")
    protocol_quote_authority = _pubkey(quote_authority, "quote_authority")
    input_mint = _pubkey(quote.get("input", {}).get("mint"), "input_mint")
    iat_mint = _pubkey(
        quote.get("output", {}).get("mint") or IAT_TOKEN_ADDRESS,
        "iat_mint",
    )
    buyer_input = _pubkey(buyer_input_account, "buyer_input_account")
    input_vault = _pubkey(treasury_input_vault, "treasury_input_vault")
    iat_vault = _pubkey(treasury_iat_vault, "treasury_iat_vault")
    escrow = _pubkey(settlement_escrow, "settlement_escrow")
    input_program = _pubkey(input_token_program, "input_token_program")
    iat_program = _pubkey(iat_token_program, "iat_token_program")
    if input_program not in ALLOWED_TOKEN_PROGRAMS or iat_program not in ALLOWED_TOKEN_PROGRAMS:
        raise SolanaPlanError("unsupported_token_program")
    if input_mint == iat_mint:
        raise SolanaPlanError("input_mint_is_iat")

    try:
        input_amount = int(quote["input"]["amount_minor"])
        iat_amount = int(quote["output"]["amount_minor"])
        expires_at = int(quote["expires_at"])
        quote_hash = bytes.fromhex(str(quote["intent_hash"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise SolanaPlanError("invalid_quote_contract") from exc
    if input_amount <= 0 or iat_amount <= 0 or len(quote_hash) != 32:
        raise SolanaPlanError("invalid_quote_contract")

    order_hash = hashlib.sha256(order_id.encode()).digest()
    nonce = int.from_bytes(
        hashlib.sha256(b"iat-checkout-nonce:" + quote_hash).digest()[:8],
        "little",
    )
    config = _pda(program, b"config")
    vault_authority = _pda(program, b"vault-authority", bytes(config))
    asset = _pda(program, b"asset", bytes(config), bytes(input_mint))
    wallet_usage = _pda(program, b"wallet-usage", bytes(config), bytes(buyer))
    payment_intent = _pda(
        program,
        b"payment",
        bytes(config),
        order_hash,
        bytes(buyer),
        nonce.to_bytes(8, "little"),
    )

    execute_data = (
        _discriminator("execute_treasury_checkout")
        + order_hash
        + quote_hash
        + struct.pack("<QQQq", nonce, input_amount, iat_amount, expires_at)
    )
    execute_accounts = [
        _meta(buyer, signer=True, writable=True),
        _meta(protocol_quote_authority, signer=True),
        _meta(config, writable=True),
        _meta(asset),
        _meta(wallet_usage, writable=True),
        _meta(payment_intent, writable=True),
        _meta(input_mint),
        _meta(iat_mint),
        _meta(buyer_input, writable=True),
        _meta(input_vault, writable=True),
        _meta(iat_vault, writable=True),
        _meta(escrow, writable=True),
        _meta(vault_authority),
        _meta(input_program),
        _meta(iat_program),
        _meta(SYSTEM_PROGRAM_ID),
    ]
    initialize_usage_data = _discriminator("initialize_wallet_usage")
    initialize_usage_accounts = [
        _meta(config),
        _meta(buyer, signer=True, writable=True),
        _meta(wallet_usage, writable=True),
        _meta(SYSTEM_PROGRAM_ID),
    ]
    return {
        "program_id": str(program),
        "network": "solana",
        "fee_payer": str(buyer),
        "buyer_signature_required": True,
        "protocol_authorization_signature_required": True,
        "quote_authority": str(protocol_quote_authority),
        "server_holds_quote_authority_key": False,
        "simulation_required": True,
        "derived_accounts": {
            "config": str(config),
            "asset": str(asset),
            "wallet_usage": str(wallet_usage),
            "payment_intent": str(payment_intent),
            "vault_authority": str(vault_authority),
        },
        "wallet_usage_prerequisite": {
            "query_account": str(wallet_usage),
            "include_only_when_account_is_missing": True,
            "program_id": str(program),
            "accounts": initialize_usage_accounts,
            "data_base64": base64.b64encode(initialize_usage_data).decode(),
        },
        "execute": {
            "program_id": str(program),
            "accounts": execute_accounts,
            "data_base64": base64.b64encode(execute_data).decode(),
        },
        "display": {
            "order_id": order_id,
            "route": "treasury",
            "input_asset": quote["input"]["asset"],
            "input_amount": quote["input"]["amount"],
            "input_destination": str(input_vault),
            "iat_amount": quote["output"]["amount"],
            "iat_destination": str(escrow),
            "expires_at": expires_at,
        },
        "anti_replay": {
            "order_hash_hex": order_hash.hex(),
            "quote_hash_hex": quote_hash.hex(),
            "nonce": nonce,
            "payment_intent": str(payment_intent),
        },
    }


def build_direct_usdc_purchase_plan(
    *,
    quote: Mapping[str, Any],
    order_id: str,
    program_id: str,
    treasury_iat_vault: str,
    treasury_input_vault: str,
    buyer_input_account: str,
    buyer_iat_account: str,
    input_token_program: str,
    iat_token_program: str,
) -> dict[str, Any]:
    """Build a buyer-only USDC → IAT purchase delivered to the buyer token account."""

    if quote.get("route") != "treasury":
        raise SolanaPlanError("treasury_route_required")
    if str(quote.get("input", {}).get("asset") or "").upper() != "USDC":
        raise SolanaPlanError("usdc_input_required")
    buyer = _pubkey(quote.get("buyer_wallet"), "buyer_wallet")
    program = _pubkey(program_id, "program_id")
    input_mint = _pubkey(quote.get("input", {}).get("mint"), "input_mint")
    iat_mint = _pubkey(
        quote.get("output", {}).get("mint") or IAT_TOKEN_ADDRESS,
        "iat_mint",
    )
    buyer_input = _pubkey(buyer_input_account, "buyer_input_account")
    buyer_iat = _pubkey(buyer_iat_account, "buyer_iat_account")
    input_vault = _pubkey(treasury_input_vault, "treasury_input_vault")
    iat_vault = _pubkey(treasury_iat_vault, "treasury_iat_vault")
    input_program = _pubkey(input_token_program, "input_token_program")
    iat_program = _pubkey(iat_token_program, "iat_token_program")
    if input_program not in ALLOWED_TOKEN_PROGRAMS or iat_program not in ALLOWED_TOKEN_PROGRAMS:
        raise SolanaPlanError("unsupported_token_program")
    if input_mint == iat_mint:
        raise SolanaPlanError("input_mint_is_iat")

    try:
        input_amount = int(quote["input"]["amount_minor"])
        iat_amount = int(quote["output"]["amount_minor"])
        expires_at = int(quote["expires_at"])
        quote_hash = bytes.fromhex(str(quote["intent_hash"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise SolanaPlanError("invalid_quote_contract") from exc
    if input_amount <= 0 or iat_amount <= 0 or len(quote_hash) != 32:
        raise SolanaPlanError("invalid_quote_contract")

    order_hash = hashlib.sha256(order_id.encode()).digest()
    nonce = int.from_bytes(
        hashlib.sha256(b"iat-checkout-nonce:" + quote_hash).digest()[:8],
        "little",
    )
    config = _pda(program, b"config")
    vault_authority = _pda(program, b"vault-authority", bytes(config))
    asset = _pda(program, b"asset", bytes(config), bytes(input_mint))
    wallet_usage = _pda(program, b"wallet-usage", bytes(config), bytes(buyer))
    payment_intent = _pda(
        program,
        b"payment",
        bytes(config),
        order_hash,
        bytes(buyer),
        nonce.to_bytes(8, "little"),
    )

    execute_data = (
        _discriminator("purchase_iat_with_usdc")
        + order_hash
        + quote_hash
        + struct.pack("<QQQq", nonce, input_amount, iat_amount, expires_at)
    )
    execute_accounts = [
        _meta(buyer, signer=True, writable=True),
        _meta(config, writable=True),
        _meta(asset),
        _meta(wallet_usage, writable=True),
        _meta(payment_intent, writable=True),
        _meta(input_mint),
        _meta(iat_mint),
        _meta(buyer_input, writable=True),
        _meta(input_vault, writable=True),
        _meta(iat_vault, writable=True),
        _meta(buyer_iat, writable=True),
        _meta(vault_authority),
        _meta(input_program),
        _meta(iat_program),
        _meta(SYSTEM_PROGRAM_ID),
    ]
    initialize_usage_accounts = [
        _meta(config),
        _meta(buyer, signer=True, writable=True),
        _meta(wallet_usage, writable=True),
        _meta(SYSTEM_PROGRAM_ID),
    ]
    return {
        "program_id": str(program),
        "network": "solana",
        "fee_payer": str(buyer),
        "buyer_signature_required": True,
        "protocol_authorization_signature_required": False,
        "server_holds_quote_authority_key": False,
        "simulation_required": True,
        "delivery_mode": "direct_to_buyer",
        "derived_accounts": {
            "config": str(config),
            "asset": str(asset),
            "wallet_usage": str(wallet_usage),
            "payment_intent": str(payment_intent),
            "vault_authority": str(vault_authority),
        },
        "wallet_usage_prerequisite": {
            "query_account": str(wallet_usage),
            "include_only_when_account_is_missing": True,
            "program_id": str(program),
            "accounts": initialize_usage_accounts,
            "data_base64": base64.b64encode(
                _discriminator("initialize_wallet_usage")
            ).decode(),
        },
        "buyer_iat_account_prerequisite": {
            "query_account": str(buyer_iat),
            "include_only_when_account_is_missing": True,
            "program_id": str(ASSOCIATED_TOKEN_PROGRAM_ID),
            "accounts": [
                _meta(buyer, signer=True, writable=True),
                _meta(buyer_iat, writable=True),
                _meta(buyer),
                _meta(iat_mint),
                _meta(SYSTEM_PROGRAM_ID),
                _meta(iat_program),
            ],
            "data_base64": "",
        },
        "execute": {
            "program_id": str(program),
            "accounts": execute_accounts,
            "data_base64": base64.b64encode(execute_data).decode(),
        },
        "display": {
            "order_id": order_id,
            "route": "treasury",
            "input_asset": "USDC",
            "input_amount": quote["input"]["amount"],
            "input_destination": str(input_vault),
            "iat_amount": quote["output"]["amount"],
            "iat_destination": str(buyer_iat),
            "iat_recipient_owner": str(buyer),
            "expires_at": expires_at,
        },
        "anti_replay": {
            "order_hash_hex": order_hash.hex(),
            "quote_hash_hex": quote_hash.hex(),
            "nonce": nonce,
            "payment_intent": str(payment_intent),
        },
    }
