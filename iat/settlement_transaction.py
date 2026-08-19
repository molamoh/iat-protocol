"""Canonical Solana instruction builder for IAT atomic settlements."""

from __future__ import annotations

from solders.instruction import Instruction
from solders.pubkey import Pubkey
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.instructions import (
    TransferCheckedParams,
    create_associated_token_account,
    get_associated_token_address,
    transfer_checked,
)

from iat.config import IAT_DECIMALS


MEMO_PROGRAM_ID = Pubkey.from_string(
    "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
)
SOLANA_DEVNET_GENESIS_HASH = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1"


def build_atomic_settlement_instructions(
    *,
    escrow_authority: Pubkey,
    mint: Pubkey,
    treasury_owner: Pubkey,
    winner_owner: Pubkey,
    commission_amount_minor: int,
    seller_payout_amount_minor: int,
    create_treasury_account: bool,
    create_winner_account: bool,
    memo_text: str | None = None,
) -> tuple[list[Instruction], dict[str, Pubkey]]:
    """Build the one canonical instruction sequence used by every phase."""
    amounts = (commission_amount_minor, seller_payout_amount_minor)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in amounts):
        raise ValueError("settlement_amount_invalid")
    if min(amounts) < 0:
        raise ValueError("settlement_amount_negative")
    if sum(amounts) <= 0:
        raise ValueError("settlement_total_amount_must_be_positive")

    source = get_associated_token_address(escrow_authority, mint)
    treasury_ata = get_associated_token_address(treasury_owner, mint)
    winner_ata = get_associated_token_address(winner_owner, mint)
    instructions: list[Instruction] = []

    if create_treasury_account:
        instructions.append(
            create_associated_token_account(
                payer=escrow_authority,
                owner=treasury_owner,
                mint=mint,
            )
        )
    if create_winner_account:
        instructions.append(
            create_associated_token_account(
                payer=escrow_authority,
                owner=winner_owner,
                mint=mint,
            )
        )

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
                    owner=escrow_authority,
                    amount=amount,
                    decimals=IAT_DECIMALS,
                    signers=[],
                )
            )
        )

    if memo_text:
        instructions.append(
            Instruction(
                program_id=MEMO_PROGRAM_ID,
                accounts=[],
                data=str(memo_text).encode("utf-8"),
            )
        )

    return instructions, {
        "source_token_account": source,
        "treasury_token_account": treasury_ata,
        "winner_token_account": winner_ata,
    }
