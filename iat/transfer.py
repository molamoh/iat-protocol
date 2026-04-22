import json
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from spl.token.instructions import transfer_checked, TransferCheckedParams, get_associated_token_address
from spl.token.constants import TOKEN_PROGRAM_ID

RPC = "https://api.mainnet-beta.solana.com"
IAT_MINT = "3vRGo1VpGbZH67Ur2UG7VNUqSqQyApLQEcCxgnqK4f4Z"

def send_iat(from_keypair_path, to_address, amount):
    client = Client(RPC)
    with open(from_keypair_path) as f:
        keypair = Keypair.from_bytes(bytes(json.load(f)))
    mint = Pubkey.from_string(IAT_MINT)
    source = get_associated_token_address(keypair.pubkey(), mint)
    dest = get_associated_token_address(Pubkey.from_string(to_address), mint)
    amount_raw = int(amount * 10**8)
    ix = transfer_checked(TransferCheckedParams(program_id=TOKEN_PROGRAM_ID, source=source, mint=mint, dest=dest, owner=keypair.pubkey(), amount=amount_raw, decimals=8, signers=[]))
    blockhash = client.get_latest_blockhash().value.blockhash
    from solders.message import Message
    msg = Message([ix], keypair.pubkey())
    from solders.transaction import Transaction
    tx = Transaction([keypair], msg, blockhash)
    resp = client.send_raw_transaction(bytes(tx))
    return str(resp.value)
