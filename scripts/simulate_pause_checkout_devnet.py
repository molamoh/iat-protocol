"""Simulate the unsigned GN2d devnet pause transaction; never send it."""

from __future__ import annotations

import base64
import json
import os
import sys

import requests
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

from iat.checkout_solana import build_set_paused_plan


PROGRAM_ID = "GN2d9tgQvwWqFaGuVomqBxcngW8c3CPWe4JRG6bP4rD"
AUTHORITY = "EPabAZ3CtMkbjduLrNcDZuXaEp37Ge9cmrnwWF9TY5wc"


def simulate() -> dict:
    plan = build_set_paused_plan(
        program_id=PROGRAM_ID,
        authority=AUTHORITY,
        paused=True,
    )
    instruction_plan = plan["instruction"]
    instruction = Instruction(
        Pubkey.from_string(instruction_plan["program_id"]),
        base64.b64decode(instruction_plan["data_base64"], validate=True),
        [
            AccountMeta(
                Pubkey.from_string(item["address"]),
                item["signer"],
                item["writable"],
            )
            for item in instruction_plan["accounts"]
        ],
    )
    fee_payer = Pubkey.from_string(plan["fee_payer"])
    message = Message.new_with_blockhash(
        [instruction],
        fee_payer,
        Hash.default(),
    )
    unsigned_transaction = Transaction.new_unsigned(message)
    if any(bytes(signature) != bytes(64) for signature in unsigned_transaction.signatures):
        raise RuntimeError("simulation_transaction_must_remain_unsigned")

    rpc_url = os.getenv(
        "IAT_CHECKOUT_RPC_URL",
        "https://api.devnet.solana.com",
    ).strip()
    if not rpc_url.startswith("https://"):
        raise RuntimeError("https_rpc_required")
    response = requests.post(
        rpc_url,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "simulateTransaction",
            "params": [
                base64.b64encode(bytes(unsigned_transaction)).decode(),
                {
                    "encoding": "base64",
                    "commitment": "confirmed",
                    "sigVerify": False,
                    "replaceRecentBlockhash": True,
                },
            ],
        },
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    value = payload.get("result", {}).get("value")
    if not isinstance(value, dict):
        raise RuntimeError("invalid_simulation_response")
    return {
        "status": "simulation_succeeded" if value.get("err") is None else "simulation_failed",
        "cluster": "devnet",
        "action": "set_paused_true",
        "program_id": PROGRAM_ID,
        "config": plan["display"]["config"],
        "authority": AUTHORITY,
        "fee_payer": AUTHORITY,
        "funds_transfer": False,
        "signed": False,
        "sent": False,
        "simulation_error": value.get("err"),
        "units_consumed": value.get("unitsConsumed"),
    }


def main() -> int:
    try:
        result = simulate()
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "simulation_succeeded" else 1
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "simulation_failed",
                    "reason": str(exc)[:160],
                    "signed": False,
                    "sent": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
