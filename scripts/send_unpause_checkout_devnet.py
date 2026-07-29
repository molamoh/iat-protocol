"""Send the explicitly approved GN2d devnet unpause transaction."""

from __future__ import annotations

import base64
import json
import os

from solana.rpc.api import Client
from solana.rpc.commitment import Finalized
from solana.rpc.types import TxOpts
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

from iat.checkout_devnet_verify import verify
from iat.checkout_solana import build_set_paused_plan


PROGRAM_ID = "GN2d9tgQvwWqFaGuVomqBxcngW8c3CPWe4JRG6bP4rD"
AUTHORITY = "EPabAZ3CtMkbjduLrNcDZuXaEp37Ge9cmrnwWF9TY5wc"


def main() -> int:
    before = verify()
    if not before["config"]["paused"]:
        print(json.dumps({"status": "already_unpaused", "sent": False}, sort_keys=True))
        return 0
    if before["config"]["authority"] != AUTHORITY:
        raise RuntimeError("configured_authority_mismatch")
    if not before["usdc_asset"]["policy_fresh"]:
        raise RuntimeError("usdc_asset_policy_must_be_fresh")

    plan = build_set_paused_plan(
        program_id=PROGRAM_ID,
        authority=AUTHORITY,
        paused=False,
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

    keypair_path = os.getenv(
        "IAT_CHECKOUT_AUTHORITY_KEYPAIR",
        "/home/ilias/pool-wallet.json",
    )
    with open(keypair_path, encoding="utf-8") as keypair_file:
        signer = Keypair.from_bytes(bytes(json.load(keypair_file)))
    authority = Pubkey.from_string(AUTHORITY)
    if signer.pubkey() != authority:
        raise RuntimeError("signer_authority_mismatch")

    rpc_url = os.getenv(
        "IAT_CHECKOUT_RPC_URL",
        "https://api.devnet.solana.com",
    ).strip()
    if not rpc_url.startswith("https://"):
        raise RuntimeError("https_rpc_required")
    client = Client(rpc_url, commitment=Finalized)
    latest = client.get_latest_blockhash(commitment=Finalized).value
    message = Message.new_with_blockhash(
        [instruction],
        authority,
        latest.blockhash,
    )
    transaction = Transaction([signer], message, latest.blockhash)

    simulation = client.simulate_transaction(
        transaction,
        sig_verify=True,
        commitment=Finalized,
    ).value
    if simulation.err is not None:
        raise RuntimeError(f"signed_simulation_failed:{simulation.err}")
    print(
        json.dumps(
            {
                "status": "signed_simulation_succeeded",
                "cluster": "devnet",
                "action": "set_paused_false",
                "funds_transfer": False,
                "units_consumed": simulation.units_consumed,
            },
            sort_keys=True,
        ),
        flush=True,
    )

    response = client.send_transaction(
        transaction,
        opts=TxOpts(
            skip_preflight=False,
            preflight_commitment=Finalized,
            max_retries=5,
        ),
    )
    signature = response.value
    print(
        json.dumps(
            {
                "status": "submitted",
                "signature": str(signature),
                "automatic_resubmission": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )

    confirmation_warning = None
    try:
        confirmation = client.confirm_transaction(
            signature,
            commitment=Finalized,
            last_valid_block_height=latest.last_valid_block_height,
        )
        status = confirmation.value[0]
        if status is None or status.err is not None:
            confirmation_warning = f"unpause_not_finalized:{status}"
    except Exception as exc:
        confirmation_warning = f"confirmation_rpc_error:{type(exc).__name__}"

    after = verify()
    if after["config"]["paused"]:
        raise RuntimeError(confirmation_warning or "unpause_state_not_observed")
    print(
        json.dumps(
            {
                "status": (
                    "finalized"
                    if confirmation_warning is None
                    else "finalized_state_observed"
                ),
                "cluster": "devnet",
                "action": "set_paused_false",
                "signature": str(signature),
                "paused": False,
                "policy_fresh": after["usdc_asset"]["policy_fresh"],
                "funds_transfer": False,
                "confirmation_warning": confirmation_warning,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
