import json
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.instruction import Instruction
from spl.token.instructions import transfer_checked, TransferCheckedParams, get_associated_token_address, create_associated_token_account
from spl.token.constants import TOKEN_PROGRAM_ID

import os

RPC = (
    os.getenv("IAT_SOLANA_RPC_URL")
    or os.getenv("SOLANA_RPC_URL")
    or "https://api.mainnet-beta.solana.com"
)
IAT_MINT = "3vRGo1VpGbZH67Ur2UG7VNUqSqQyApLQEcCxgnqK4f4Z"

# Memo program
MEMO_PROGRAM_ID = Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr")



def load_keypair(keypair_input):
    from solders.keypair import Keypair

    if isinstance(keypair_input, str) and keypair_input.strip().startswith("["):
        return Keypair.from_bytes(bytes(json.loads(keypair_input)))

    with open(keypair_input, "r") as f:
        return Keypair.from_bytes(bytes(json.load(f)))


def send_iat(from_keypair_path, to_address, amount, order_id=None, memo_text=None):
    client = Client(RPC)

    keypair = load_keypair(from_keypair_path)

    mint = Pubkey.from_string(IAT_MINT)

    source = get_associated_token_address(keypair.pubkey(), mint)
    dest = get_associated_token_address(Pubkey.from_string(to_address), mint)

    amount_raw = int(amount * 10**8)

    # Token transfer instruction
    ix_transfer = transfer_checked(
        TransferCheckedParams(
            program_id=TOKEN_PROGRAM_ID,
            source=source,
            mint=mint,
            dest=dest,
            owner=keypair.pubkey(),
            amount=amount_raw,
            decimals=8,
            signers=[]
        )
    )

    instructions = []

    # Create recipient associated token account if it does not exist
    dest_info = client.get_account_info(dest)
    if dest_info.value is None:
        ix_create_ata = create_associated_token_account(
            payer=keypair.pubkey(),
            owner=Pubkey.from_string(to_address),
            mint=mint
        )
        instructions.append(ix_create_ata)

    instructions.append(ix_transfer)

    # Add memo if provided
    if memo_text is not None:
        memo_data = str(memo_text).encode("utf-8")
    elif order_id is not None:
        memo_data = f"ORDER:{order_id}".encode("utf-8")
    else:
        memo_data = None

    if memo_data is not None:

        memo_ix = Instruction(
            program_id=MEMO_PROGRAM_ID,
            accounts=[],
            data=memo_data
        )

        instructions.append(memo_ix)

    blockhash = client.get_latest_blockhash().value.blockhash

    from solders.message import Message
    msg = Message(instructions, keypair.pubkey())

    from solders.transaction import Transaction
    tx = Transaction([keypair], msg, blockhash)

    resp = client.send_raw_transaction(bytes(tx))
    return str(resp.value)


def send_iat_split_atomic(
    from_keypair_path,
    treasury_address,
    winner_address,
    commission_amount,
    seller_payout_amount,
    memo_text=None,
):
    """
    Execute the protocol commission and seller payout in one atomic
    Solana transaction.

    Either every instruction succeeds or the complete transaction fails.
    """
    client = Client(RPC)
    keypair = load_keypair(from_keypair_path)

    mint = Pubkey.from_string(IAT_MINT)
    treasury_owner = Pubkey.from_string(str(treasury_address))
    winner_owner = Pubkey.from_string(str(winner_address))

    source_ata = get_associated_token_address(keypair.pubkey(), mint)
    treasury_ata = get_associated_token_address(treasury_owner, mint)
    winner_ata = get_associated_token_address(winner_owner, mint)

    commission_raw = int(round(float(commission_amount or 0) * 10**8))
    seller_payout_raw = int(round(float(seller_payout_amount or 0) * 10**8))

    if commission_raw < 0 or seller_payout_raw < 0:
        raise ValueError("Atomic split amounts cannot be negative")

    if commission_raw + seller_payout_raw <= 0:
        raise ValueError("Atomic split total amount must be positive")

    instructions = []

    treasury_info = client.get_account_info(treasury_ata)
    if treasury_info.value is None:
        instructions.append(
            create_associated_token_account(
                payer=keypair.pubkey(),
                owner=treasury_owner,
                mint=mint,
            )
        )

    winner_info = client.get_account_info(winner_ata)
    if winner_info.value is None:
        instructions.append(
            create_associated_token_account(
                payer=keypair.pubkey(),
                owner=winner_owner,
                mint=mint,
            )
        )

    if commission_raw > 0:
        instructions.append(
            transfer_checked(
                TransferCheckedParams(
                    program_id=TOKEN_PROGRAM_ID,
                    source=source_ata,
                    mint=mint,
                    dest=treasury_ata,
                    owner=keypair.pubkey(),
                    amount=commission_raw,
                    decimals=8,
                    signers=[],
                )
            )
        )

    if seller_payout_raw > 0:
        instructions.append(
            transfer_checked(
                TransferCheckedParams(
                    program_id=TOKEN_PROGRAM_ID,
                    source=source_ata,
                    mint=mint,
                    dest=winner_ata,
                    owner=keypair.pubkey(),
                    amount=seller_payout_raw,
                    decimals=8,
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

    blockhash = client.get_latest_blockhash().value.blockhash

    from solders.message import Message
    from solders.transaction import Transaction

    message = Message(instructions, keypair.pubkey())
    transaction = Transaction([keypair], message, blockhash)

    response = client.send_raw_transaction(bytes(transaction))
    return str(response.value)

