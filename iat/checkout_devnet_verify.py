"""Reusable read-only devnet verification for the IAT checkout deployment."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import sys
import time

import requests
from solders.pubkey import Pubkey


PROGRAM_ID = Pubkey.from_string("GN2d9tgQvwWqFaGuVomqBxcngW8c3CPWe4JRG6bP4rD")
USDC_DEVNET_MINT = Pubkey.from_string(
    "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"
)
CLASSIC_TOKEN_PROGRAM = Pubkey.from_string(
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
)
UPGRADEABLE_LOADER = "BPFLoaderUpgradeab1e11111111111111111111111"


class VerificationError(RuntimeError):
    pass


def _discriminator(name: str) -> bytes:
    return hashlib.sha256(f"account:{name}".encode()).digest()[:8]


def _pubkey(data: bytes, offset: int) -> Pubkey:
    return Pubkey.from_bytes(data[offset : offset + 32])


def parse_protocol_config(data: bytes) -> dict:
    if len(data) != 243:
        raise VerificationError("invalid_protocol_config_length")
    if data[:8] != _discriminator("ProtocolConfig"):
        raise VerificationError("invalid_protocol_config_discriminator")
    return {
        "authority": str(_pubkey(data, 8)),
        "pending_authority": str(_pubkey(data, 40)),
        "quote_authority": str(_pubkey(data, 72)),
        "iat_mint": str(_pubkey(data, 104)),
        "treasury_iat_vault": str(_pubkey(data, 136)),
        "settlement_escrow": str(_pubkey(data, 168)),
        "max_order_iat": struct.unpack_from("<Q", data, 200)[0],
        "wallet_daily_iat_cap": struct.unpack_from("<Q", data, 208)[0],
        "treasury_daily_iat_cap": struct.unpack_from("<Q", data, 216)[0],
        "treasury_usage_day": struct.unpack_from("<q", data, 224)[0],
        "treasury_usage_iat": struct.unpack_from("<Q", data, 232)[0],
        "paused": bool(data[240]),
        "bump": data[241],
        "vault_authority_bump": data[242],
    }


def parse_asset_config(data: bytes) -> dict:
    if len(data) != 170:
        raise VerificationError("invalid_asset_config_length")
    if data[:8] != _discriminator("AssetConfig"):
        raise VerificationError("invalid_asset_config_discriminator")
    return {
        "config": str(_pubkey(data, 8)),
        "input_mint": str(_pubkey(data, 40)),
        "treasury_input_vault": str(_pubkey(data, 72)),
        "token_program": str(_pubkey(data, 104)),
        "ratio_numerator": struct.unpack_from("<Q", data, 136)[0],
        "ratio_denominator": struct.unpack_from("<Q", data, 144)[0],
        "max_order_iat": struct.unpack_from("<Q", data, 152)[0],
        "valid_until": struct.unpack_from("<q", data, 160)[0],
        "enabled": bool(data[168]),
        "bump": data[169],
    }


class Rpc:
    def __init__(self) -> None:
        self.url = os.getenv(
            "IAT_CHECKOUT_RPC_URL",
            "https://api.devnet.solana.com",
        ).strip()
        self.timeout = max(
            3,
            min(int(os.getenv("IAT_CHECKOUT_RPC_TIMEOUT_SECONDS", "15")), 30),
        )
        if not self.url.startswith("https://"):
            raise VerificationError("https_rpc_required")

    def account(self, address: Pubkey) -> dict:
        response = requests.post(
            self.url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [
                    str(address),
                    {"encoding": "base64", "commitment": "confirmed"},
                ],
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        value = payload.get("result", {}).get("value")
        if not isinstance(value, dict):
            raise VerificationError(f"account_not_found:{address}")
        encoded = value.get("data")
        if (
            not isinstance(encoded, list)
            or len(encoded) != 2
            or encoded[1] != "base64"
        ):
            raise VerificationError(f"invalid_account_encoding:{address}")
        value["decoded"] = base64.b64decode(encoded[0], validate=True)
        return value


def _require_owner(account: dict, owner: Pubkey | str, label: str) -> None:
    if account.get("owner") != str(owner):
        raise VerificationError(f"{label}_owner_mismatch")


def _parse_token_account(account: dict, label: str) -> dict:
    _require_owner(account, CLASSIC_TOKEN_PROGRAM, label)
    data = account["decoded"]
    if len(data) != 165:
        raise VerificationError(f"{label}_invalid_length")
    return {
        "mint": str(_pubkey(data, 0)),
        "authority": str(_pubkey(data, 32)),
        "amount": struct.unpack_from("<Q", data, 64)[0],
    }


def verify() -> dict:
    rpc = Rpc()
    program = rpc.account(PROGRAM_ID)
    _require_owner(program, UPGRADEABLE_LOADER, "program")
    if program.get("executable") is not True:
        raise VerificationError("program_not_executable")

    config_address, config_bump = Pubkey.find_program_address(
        [b"config"],
        PROGRAM_ID,
    )
    config_account = rpc.account(config_address)
    _require_owner(config_account, PROGRAM_ID, "config")
    config = parse_protocol_config(config_account["decoded"])
    if config["bump"] != config_bump:
        raise VerificationError("config_bump_mismatch")

    vault_authority, vault_bump = Pubkey.find_program_address(
        [b"vault-authority", bytes(config_address)],
        PROGRAM_ID,
    )
    if config["vault_authority_bump"] != vault_bump:
        raise VerificationError("vault_authority_bump_mismatch")

    iat_mint = Pubkey.from_string(config["iat_mint"])
    for label, mint in (("iat_mint", iat_mint), ("usdc_mint", USDC_DEVNET_MINT)):
        account = rpc.account(mint)
        _require_owner(account, CLASSIC_TOKEN_PROGRAM, label)
        if len(account["decoded"]) != 82:
            raise VerificationError(f"{label}_invalid_length")

    treasury_iat = _parse_token_account(
        rpc.account(Pubkey.from_string(config["treasury_iat_vault"])),
        "treasury_iat_vault",
    )
    if treasury_iat["mint"] != str(iat_mint):
        raise VerificationError("treasury_iat_vault_mint_mismatch")
    if treasury_iat["authority"] != str(vault_authority):
        raise VerificationError("treasury_iat_vault_authority_mismatch")

    settlement = _parse_token_account(
        rpc.account(Pubkey.from_string(config["settlement_escrow"])),
        "settlement_escrow",
    )
    if settlement["mint"] != str(iat_mint):
        raise VerificationError("settlement_escrow_mint_mismatch")

    asset_address, asset_bump = Pubkey.find_program_address(
        [b"asset", bytes(config_address), bytes(USDC_DEVNET_MINT)],
        PROGRAM_ID,
    )
    asset_account = rpc.account(asset_address)
    _require_owner(asset_account, PROGRAM_ID, "usdc_asset")
    asset = parse_asset_config(asset_account["decoded"])
    if asset["bump"] != asset_bump:
        raise VerificationError("usdc_asset_bump_mismatch")
    if asset["config"] != str(config_address):
        raise VerificationError("usdc_asset_config_mismatch")
    if asset["input_mint"] != str(USDC_DEVNET_MINT):
        raise VerificationError("usdc_asset_mint_mismatch")
    if asset["token_program"] != str(CLASSIC_TOKEN_PROGRAM):
        raise VerificationError("usdc_asset_token_program_mismatch")

    treasury_usdc = _parse_token_account(
        rpc.account(Pubkey.from_string(asset["treasury_input_vault"])),
        "treasury_usdc_vault",
    )
    if treasury_usdc["mint"] != str(USDC_DEVNET_MINT):
        raise VerificationError("treasury_usdc_vault_mint_mismatch")
    if treasury_usdc["authority"] != str(vault_authority):
        raise VerificationError("treasury_usdc_vault_authority_mismatch")

    now = int(time.time())
    warnings = []
    if not config["paused"]:
        warnings.append("protocol_unpaused_before_upgrade")
    if asset["valid_until"] <= now:
        warnings.append("usdc_asset_policy_stale")
    return {
        "status": "verified",
        "upgrade_ready": config["paused"],
        "warnings": warnings,
        "cluster": "devnet",
        "program_id": str(PROGRAM_ID),
        "program_executable": True,
        "config": {
            "address": str(config_address),
            "authority": config["authority"],
            "quote_authority": config["quote_authority"],
            "paused": config["paused"],
        },
        "mints": {
            "iat": str(iat_mint),
            "usdc": str(USDC_DEVNET_MINT),
            "token_program": str(CLASSIC_TOKEN_PROGRAM),
        },
        "vaults": {
            "authority": str(vault_authority),
            "iat_inventory": treasury_iat["amount"],
            "usdc_inventory": treasury_usdc["amount"],
        },
        "usdc_asset": {
            "address": str(asset_address),
            "enabled": asset["enabled"],
            "ratio_numerator": asset["ratio_numerator"],
            "ratio_denominator": asset["ratio_denominator"],
            "valid_until": asset["valid_until"],
            "policy_fresh": asset["valid_until"] > now,
        },
        "read_only": True,
    }


def main() -> int:
    try:
        print(json.dumps(verify(), sort_keys=True))
        return 0
    except (VerificationError, requests.RequestException, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_code": type(exc).__name__,
                    "reason": str(exc)[:160],
                    "read_only": True,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
