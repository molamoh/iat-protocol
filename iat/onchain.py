import time
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.keypair import Keypair
from solana.rpc.types import TokenAccountOpts

import json
import os

RPC = (
    os.getenv("IAT_SOLANA_RPC_URL")
    or os.getenv("SOLANA_RPC_URL")
    or "https://api.mainnet-beta.solana.com"
)
IAT_MINT = "3vRGo1VpGbZH67Ur2UG7VNUqSqQyApLQEcCxgnqK4f4Z"

client = Client(RPC)


def get_iat_balance(wallet_address: str):
    mint = Pubkey.from_string(IAT_MINT)
    owner = Pubkey.from_string(wallet_address)
    opts = TokenAccountOpts(mint=mint, encoding="jsonParsed")

    for _ in range(5):
        try:
            resp = client.get_token_accounts_by_owner_json_parsed(owner, opts)
            if resp.value:
                amount = resp.value[0].account.data.parsed["info"]["tokenAmount"]["uiAmount"]
                return float(amount or 0)
            return 0.0
        except Exception:
            time.sleep(2)

    return None


def verify_tx_signature(tx_signature: str) -> bool:
    try:
        sig = Signature.from_string(tx_signature)
        resp = client.get_transaction(sig, encoding="jsonParsed", max_supported_transaction_version=0)
        return resp.value is not None
    except Exception:
        return False


def get_tx_details(tx_signature: str):
    try:
        sig = Signature.from_string(tx_signature)
        resp = client.get_transaction(sig, encoding="jsonParsed", max_supported_transaction_version=0)
        return resp.value
    except Exception:
        return None


def get_escrow_public_key():
    """
    Resolve the public key of the protocol escrow keypair.

    The private key never leaves the local process. Only the public key is
    returned and used to inspect recent Solana transactions.
    """
    keypair_path = (
        os.getenv("IAT_ESCROW_KEYPAIR_JSON")
        or os.getenv("IAT_ESCROW_KEYPAIR_PATH")
    )

    if not keypair_path:
        return None

    try:
        with open(keypair_path, "r", encoding="utf-8") as handle:
            raw_keypair = json.load(handle)

        if not isinstance(raw_keypair, list):
            return None

        keypair = Keypair.from_bytes(bytes(raw_keypair))
        return keypair.pubkey()

    except Exception:
        return None


def find_settlement_transaction_signature(
    settlement_id: str,
    order_id: str,
    claimed_at: int | None = None,
    limit: int = 100,
):
    """
    Reconcile an ambiguous settlement broadcast.

    Search recent transactions involving the escrow wallet and identify the
    exact atomic settlement transaction through its unique memo:

        IAT_SETTLEMENT:<settlement_id>:<order_id>

    Safety:
    - Never returns an errored transaction.
    - Never guesses from amount or recipient alone.
    - Requires the exact settlement memo.
    - Restricts the search to transactions close to the execution claim.
    """
    if not settlement_id or not order_id:
        return {
            "status": "invalid_request",
            "found": False,
            "reason": "settlement_id_and_order_id_required",
        }

    escrow_pubkey = get_escrow_public_key()

    if escrow_pubkey is None:
        return {
            "status": "unavailable",
            "found": False,
            "reason": "escrow_public_key_unavailable",
        }

    expected_memo = f"IAT_SETTLEMENT:{settlement_id}:{order_id}"

    try:
        response = client.get_signatures_for_address(
            escrow_pubkey,
            limit=max(1, min(int(limit or 100), 1000)),
        )

        entries = response.value or []

        for entry in entries:
            signature_text = str(entry.signature)
            block_time = getattr(entry, "block_time", None)
            transaction_error = getattr(entry, "err", None)

            if transaction_error is not None:
                continue

            if (
                claimed_at
                and block_time
                and int(block_time) < int(claimed_at) - 180
            ):
                continue

            tx_details = get_tx_details(signature_text)

            if tx_details is None:
                continue

            tx_text = str(tx_details)

            if expected_memo not in tx_text:
                continue

            return {
                "status": "found",
                "found": True,
                "reason": "exact_settlement_memo_found_onchain",
                "settlement_id": settlement_id,
                "order_id": order_id,
                "expected_memo": expected_memo,
                "atomic_tx_signature": signature_text,
                "block_time": block_time,
                "escrow_wallet": str(escrow_pubkey),
            }

        return {
            "status": "not_found",
            "found": False,
            "reason": "exact_settlement_memo_not_found_in_recent_transactions",
            "settlement_id": settlement_id,
            "order_id": order_id,
            "expected_memo": expected_memo,
            "searched_count": len(entries),
            "escrow_wallet": str(escrow_pubkey),
        }

    except Exception as exc:
        return {
            "status": "rpc_error",
            "found": False,
            "reason": "settlement_transaction_reconciliation_rpc_error",
            "settlement_id": settlement_id,
            "order_id": order_id,
            "expected_memo": expected_memo,
            "error": str(exc),
        }



def extract_transfer_checked_info(tx_details):
    """
    Extract SPL token transfer info from parsed Solana transaction.

    Supports:
    - transferChecked
    - transfer

    Phantom and wallets may use either instruction type.
    """
    try:
        instructions = tx_details.transaction.transaction.message.instructions

        for inst in instructions:
            inst_str = str(inst)

            is_transfer_checked = "transferChecked" in inst_str
            is_transfer = '"type": String("transfer")' in inst_str or "'type': 'transfer'" in inst_str

            if is_transfer_checked or is_transfer:
                raw = inst_str

                def extract_between(text, start, end):
                    if start in text and end in text.split(start, 1)[1]:
                        return text.split(start, 1)[1].split(end, 1)[0]
                    return None

                info = {
                    "authority": extract_between(raw, '"authority": String("', '")'),
                    "destination": extract_between(raw, '"destination": String("', '")'),
                    "mint": extract_between(raw, '"mint": String("', '")'),
                    "source": extract_between(raw, '"source": String("', '")'),
                    "ui_amount": extract_between(raw, '"uiAmount": Number(', ')'),
                    "ui_amount_string": extract_between(raw, '"uiAmountString": String("', '")'),
                    "amount": extract_between(raw, '"amount": String("', '")'),
                    "instruction_type": "transferChecked" if is_transfer_checked else "transfer",
                }

                return info

        return None
    except Exception:
        return None


def extract_memo(tx_details):
    try:
        instructions = tx_details.transaction.transaction.message.instructions

        for inst in instructions:
            inst_str = str(inst)

            if "Memo" in inst_str or "memo" in inst_str:
                return inst_str

        return None
    except Exception:
        return None
