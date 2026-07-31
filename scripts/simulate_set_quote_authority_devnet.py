"""Simulate the GN2d devnet quote-authority rotation; never sign or send."""

from __future__ import annotations

import base64
import json
import sys

from solana.rpc.api import Client
from solana.rpc.commitment import Confirmed
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

from iat.checkout_devnet_verify import Rpc, verify
from iat.checkout_solana import build_set_quote_authority_plan


PROGRAM_ID = "GN2d9tgQvwWqFaGuVomqBxcngW8c3CPWe4JRG6bP4rD"
AUTHORITY = "EPabAZ3CtMkbjduLrNcDZuXaEp37Ge9cmrnwWF9TY5wc"
NEW_QUOTE_AUTHORITY = "3eg5d45QKsWL6ZNQ7Lp7ZJdJiQ1tzDce96SAZyb3zyyq"


def main() -> int:
    rpc = Rpc()
    state = verify()
    if not state["config"]["paused"]:
        raise RuntimeError("protocol_must_be_paused")
    if state["config"]["authority"] != AUTHORITY:
        raise RuntimeError("configured_authority_mismatch")
    if state["config"]["quote_authority"] == NEW_QUOTE_AUTHORITY:
        print(json.dumps({"status": "already_configured", "sent": False}))
        return 0

    plan = build_set_quote_authority_plan(
        program_id=PROGRAM_ID,
        authority=AUTHORITY,
        quote_authority=NEW_QUOTE_AUTHORITY,
    )
    raw = plan["instruction"]
    instruction = Instruction(
        Pubkey.from_string(raw["program_id"]),
        base64.b64decode(raw["data_base64"], validate=True),
        [
            AccountMeta(
                Pubkey.from_string(item["address"]),
                item["signer"],
                item["writable"],
            )
            for item in raw["accounts"]
        ],
    )
    transaction = Transaction.new_unsigned(
        Message.new_with_blockhash(
            [instruction],
            Pubkey.from_string(AUTHORITY),
            Hash.default(),
        )
    )
    simulation = Client(rpc.url, commitment=Confirmed).simulate_transaction(
        transaction,
        sig_verify=False,
        replace_recent_blockhash=True,
        commitment=Confirmed,
    ).value
    result = {
        "status": "simulation_succeeded" if simulation.err is None else "simulation_failed",
        "cluster": "devnet",
        "program_id": PROGRAM_ID,
        "config": state["config"]["address"],
        "authority": AUTHORITY,
        "current_quote_authority": state["config"]["quote_authority"],
        "new_quote_authority": NEW_QUOTE_AUTHORITY,
        "fee_payer": AUTHORITY,
        "funds_transfer": False,
        "signed": False,
        "sent": False,
        "simulation_error": simulation.err,
        "units_consumed": simulation.units_consumed,
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if simulation.err is None else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
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
        raise SystemExit(1)
