"""Unsigned, non-broadcast Solana simulation for authorized IAT settlements."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any, Callable

import requests
from solders.hash import Hash
from solders.instruction import Instruction
from solders.message import Message
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.instructions import (
    TransferCheckedParams,
    create_associated_token_account,
    get_associated_token_address,
    transfer_checked,
)

from iat.config import IAT_DECIMALS, IAT_TOKEN_ADDRESS


MEMO_PROGRAM_ID = Pubkey.from_string(
    "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
)
ALLOWED_CLUSTERS = {"solana-devnet", "solana-localnet"}
SOLANA_DEVNET_GENESIS_HASH = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1"


class SettlementSimulationError(ValueError):
    pass


def _pubkey(value: Any, field: str) -> Pubkey:
    try:
        return Pubkey.from_string(str(value or "").strip())
    except Exception as exc:
        raise SettlementSimulationError(f"invalid_{field}") from exc


def configured_simulation_context() -> dict[str, str]:
    cluster = os.getenv("IAT_SETTLEMENT_SIMULATION_CLUSTER", "solana-devnet").strip()
    if cluster not in ALLOWED_CLUSTERS:
        raise SettlementSimulationError("settlement_simulation_cluster_not_allowed")
    rpc_url = (
        os.getenv("IAT_SETTLEMENT_SIMULATION_RPC_URL")
        or os.getenv("IAT_SOLANA_RPC_URL")
        or (
            "http://127.0.0.1:8899"
            if cluster == "solana-localnet"
            else "https://api.devnet.solana.com"
        )
    ).strip()
    if not rpc_url:
        raise SettlementSimulationError("settlement_simulation_rpc_not_configured")
    if "mainnet" in rpc_url.lower():
        raise SettlementSimulationError("mainnet_settlement_simulation_not_allowed")
    return {
        "cluster": cluster,
        "rpc_url": rpc_url,
        "escrow_authority": os.getenv("IAT_ESCROW_WALLET", "").strip(),
        "mint": os.getenv("IAT_TOKEN_ADDRESS", IAT_TOKEN_ADDRESS).strip(),
    }


def rpc_call(rpc_url: str, method: str, params: list[Any]) -> Any:
    try:
        response = requests.post(
            rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=min(
                max(float(os.getenv("IAT_SETTLEMENT_SIMULATION_TIMEOUT_SECONDS", "10")), 2),
                20,
            ),
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise SettlementSimulationError("settlement_simulation_rpc_unavailable") from exc
    if not isinstance(payload, dict) or payload.get("error") or "result" not in payload:
        raise SettlementSimulationError("settlement_simulation_rpc_invalid_response")
    return payload["result"]


def _parsed_account(
    call: Callable[[str, list[Any]], Any],
    address: Pubkey,
) -> dict[str, Any] | None:
    result = call(
        "getAccountInfo",
        [str(address), {"encoding": "jsonParsed", "commitment": "confirmed"}],
    )
    if not isinstance(result, dict):
        raise SettlementSimulationError("solana_account_response_invalid")
    value = result.get("value")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SettlementSimulationError("solana_account_response_invalid")
    return value


def _parsed_info(account: dict[str, Any], field: str) -> dict[str, Any]:
    if account.get("owner") != str(TOKEN_PROGRAM_ID):
        raise SettlementSimulationError(f"{field}_owner_invalid")
    try:
        info = account["data"]["parsed"]["info"]
    except (KeyError, TypeError) as exc:
        raise SettlementSimulationError(f"{field}_data_invalid") from exc
    if not isinstance(info, dict):
        raise SettlementSimulationError(f"{field}_data_invalid")
    return info


def simulate_authorized_settlement(
    *,
    authorization_id: str,
    settlement_id: str,
    order_id: str,
    winner_wallet: str,
    treasury_wallet: str,
    gross_amount_minor: int,
    commission_amount_minor: int,
    seller_payout_amount_minor: int,
    context: dict[str, str] | None = None,
    rpc: Callable[[str, list[Any]], Any] | None = None,
) -> dict[str, Any]:
    """Simulate an unsigned atomic split and return only public safe metadata."""
    settings = context or configured_simulation_context()
    cluster = str(settings.get("cluster") or "")
    if cluster not in ALLOWED_CLUSTERS:
        raise SettlementSimulationError("settlement_simulation_cluster_not_allowed")
    rpc_url = str(settings.get("rpc_url") or "")
    if not rpc_url:
        raise SettlementSimulationError("settlement_simulation_rpc_not_configured")
    if "mainnet" in rpc_url.lower():
        raise SettlementSimulationError("mainnet_settlement_simulation_not_allowed")
    call = rpc or (lambda method, params: rpc_call(rpc_url, method, params))

    genesis_hash = str(call("getGenesisHash", []))
    if cluster == "solana-devnet" and genesis_hash != SOLANA_DEVNET_GENESIS_HASH:
        raise SettlementSimulationError("settlement_simulation_cluster_identity_invalid")
    if not genesis_hash:
        raise SettlementSimulationError("settlement_simulation_cluster_identity_invalid")

    escrow = _pubkey(settings.get("escrow_authority"), "escrow_authority")
    mint = _pubkey(settings.get("mint"), "iat_mint")
    winner = _pubkey(winner_wallet, "winner_wallet")
    treasury = _pubkey(treasury_wallet, "treasury_wallet")
    amounts = (gross_amount_minor, commission_amount_minor, seller_payout_amount_minor)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in amounts):
        raise SettlementSimulationError("settlement_amount_invalid")
    if gross_amount_minor <= 0:
        raise SettlementSimulationError("settlement_gross_must_be_positive")
    if commission_amount_minor + seller_payout_amount_minor != gross_amount_minor:
        raise SettlementSimulationError("settlement_amount_conservation_failed")

    mint_account = _parsed_account(call, mint)
    if mint_account is None:
        raise SettlementSimulationError("iat_mint_account_missing")
    mint_info = _parsed_info(mint_account, "iat_mint")
    if int(mint_info.get("decimals", -1)) != IAT_DECIMALS:
        raise SettlementSimulationError("iat_mint_decimals_invalid")

    source = get_associated_token_address(escrow, mint)
    treasury_ata = get_associated_token_address(treasury, mint)
    winner_ata = get_associated_token_address(winner, mint)
    source_account = _parsed_account(call, source)
    if source_account is None:
        raise SettlementSimulationError("escrow_token_account_missing")
    source_info = _parsed_info(source_account, "escrow_token_account")
    if source_info.get("mint") != str(mint) or source_info.get("owner") != str(escrow):
        raise SettlementSimulationError("escrow_token_account_binding_invalid")
    try:
        source_balance = int(source_info["tokenAmount"]["amount"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SettlementSimulationError("escrow_token_balance_invalid") from exc
    if source_balance < gross_amount_minor:
        raise SettlementSimulationError("escrow_token_balance_insufficient")

    instructions: list[Instruction] = []
    for owner, ata, field in (
        (treasury, treasury_ata, "treasury_token_account"),
        (winner, winner_ata, "winner_token_account"),
    ):
        account = _parsed_account(call, ata)
        if account is None:
            instructions.append(create_associated_token_account(escrow, owner, mint))
            continue
        info = _parsed_info(account, field)
        if info.get("mint") != str(mint) or info.get("owner") != str(owner):
            raise SettlementSimulationError(f"{field}_binding_invalid")

    for destination, amount in (
        (treasury_ata, commission_amount_minor),
        (winner_ata, seller_payout_amount_minor),
    ):
        if amount <= 0:
            continue
        instructions.append(
            transfer_checked(
                TransferCheckedParams(
                    program_id=TOKEN_PROGRAM_ID,
                    source=source,
                    mint=mint,
                    dest=destination,
                    owner=escrow,
                    amount=amount,
                    decimals=IAT_DECIMALS,
                    signers=[],
                )
            )
        )
    memo = f"IAT_SETTLEMENT_SIMULATION:{settlement_id}:{order_id}"
    instructions.append(Instruction(MEMO_PROGRAM_ID, memo.encode(), []))

    latest = call("getLatestBlockhash", [{"commitment": "confirmed"}])
    try:
        blockhash = Hash.from_string(str(latest["value"]["blockhash"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise SettlementSimulationError("solana_blockhash_invalid") from exc
    message = Message.new_with_blockhash(instructions, escrow, blockhash)
    unsigned = VersionedTransaction.populate(
        message,
        [Signature.default()] * int(message.header.num_required_signatures),
    )
    raw = bytes(unsigned)
    transaction_base64 = base64.b64encode(raw).decode()
    simulated = call(
        "simulateTransaction",
        [
            transaction_base64,
            {
                "encoding": "base64",
                "commitment": "confirmed",
                "sigVerify": False,
                "replaceRecentBlockhash": False,
            },
        ],
    )
    if not isinstance(simulated, dict) or not isinstance(simulated.get("value"), dict):
        raise SettlementSimulationError("settlement_simulation_response_invalid")
    value = simulated["value"]
    if value.get("err") is not None:
        raise SettlementSimulationError("settlement_simulation_failed")
    logs = value.get("logs") or []
    logs_sha256 = hashlib.sha256(
        json.dumps(logs, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()
    context_slot = (simulated.get("context") or {}).get("slot")
    return {
        "simulation_status": "succeeded",
        "authorization_id": authorization_id,
        "cluster": cluster,
        "genesis_hash": genesis_hash,
        "commitment": "confirmed",
        "token_program": str(TOKEN_PROGRAM_ID),
        "mint": str(mint),
        "mint_decimals": IAT_DECIMALS,
        "fee_payer": str(escrow),
        "escrow_authority": str(escrow),
        "source_token_account": str(source),
        "treasury_token_account": str(treasury_ata),
        "winner_token_account": str(winner_ata),
        "gross_amount_minor": gross_amount_minor,
        "protocol_commission_amount_minor": commission_amount_minor,
        "seller_payout_amount_minor": seller_payout_amount_minor,
        "instruction_count": len(instructions),
        "required_signature_count": int(message.header.num_required_signatures),
        "unsigned_transaction_sha256": hashlib.sha256(raw).hexdigest(),
        "simulation_logs_sha256": logs_sha256,
        "units_consumed": value.get("unitsConsumed"),
        "context_slot": context_slot,
        "serialized_transaction_disclosed": False,
    }
