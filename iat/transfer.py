import json
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.instruction import Instruction
from spl.token.instructions import transfer_checked, TransferCheckedParams, get_associated_token_address, create_associated_token_account
from spl.token.constants import TOKEN_PROGRAM_ID

RPC = "https://blue-white-thunder.solana-mainnet.quiknode.pro/2777cfcf546a9704abe0d5c7b4b3bce2b7c31586/"
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
