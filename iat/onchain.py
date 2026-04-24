import time
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from solders.signature import Signature
from solana.rpc.types import TokenAccountOpts

RPC = "https://blue-white-thunder.solana-mainnet.quiknode.pro/2777cfcf546a9704abe0d5c7b4b3bce2b7c31586/"
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


def extract_transfer_checked_info(tx_details):
    try:
        instructions = tx_details.transaction.transaction.message.instructions

        for inst in instructions:
            inst_str = str(inst)

            if "transferChecked" in inst_str:
                raw = inst_str

                def extract_between(text, start, end):
                    if start in text and end in text.split(start, 1)[1]:
                        return text.split(start, 1)[1].split(end, 1)[0]
                    return None

                return {
                    "authority": extract_between(raw, '"authority": String("', '")'),
                    "destination": extract_between(raw, '"destination": String("', '")'),
                    "mint": extract_between(raw, '"mint": String("', '")'),
                    "source": extract_between(raw, '"source": String("', '")'),
                    "ui_amount": extract_between(raw, '"uiAmount": Number(', ')'),
                    "ui_amount_string": extract_between(raw, '"uiAmountString": String("', '")'),
                }

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
