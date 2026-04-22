import json, urllib.request
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from solana.rpc.types import TokenAccountOpts

RPC = "https://api.mainnet-beta.solana.com"
IAT_MINT = "3vRGo1VpGbZH67Ur2UG7VNUqSqQyApLQEcCxgnqK4f4Z"

def get_iat_balance(wallet_address: str) -> float:
    client = Client(RPC)
    mint = Pubkey.from_string(IAT_MINT)
    owner = Pubkey.from_string(wallet_address)
    opts = TokenAccountOpts(mint=mint, encoding="jsonParsed")
    resp = client.get_token_accounts_by_owner_json_parsed(owner, opts)
    if resp.value:
        amount = resp.value[0].account.data.parsed["info"]["tokenAmount"]["uiAmount"]
        return float(amount or 0)
    return 0.0
