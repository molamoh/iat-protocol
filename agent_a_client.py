import requests

from shared_protocol import WalletStore, VerifAI, IATProtocol

store = WalletStore()
verifier = VerifAI()
protocol = IATProtocol()

try:
    buyer_wallet = store.get_wallet("agent_a_buyer")
except KeyError:
    buyer_wallet = store.create_wallet("agent_a_buyer")
    verifier.certify(buyer_wallet, "gpt-buyer-v1")
    protocol.faucet(buyer_wallet, 10.0, "bootstrap funds")
    store.upsert_wallet(buyer_wallet)

buyer_wallet.certified = True
store.upsert_wallet(buyer_wallet)

seller_info = requests.get("http://127.0.0.1:8000/info", timeout=10).json()

try:
    seller_wallet = store.get_wallet("agent_b_seller")
except KeyError:
    seller_wallet = store.create_wallet("agent_b_seller")

seller_wallet.address = seller_info["address"]
seller_wallet.certified = seller_info["certified"]
store.upsert_wallet(seller_wallet)

tx = protocol.transfer(
    sender=buyer_wallet,
    receiver=seller_wallet,
    amount=2.5,
    memo="buy:btc_signal"
)

store.upsert_wallet(buyer_wallet)
store.upsert_wallet(seller_wallet)

response = requests.post(
    "http://127.0.0.1:8000/buy-signal",
    json={
        "tx_id": tx.tx_id,
        "buyer_agent_id": buyer_wallet.agent_id,
        "item": "btc_signal"
    },
    timeout=10
)

print("\n=== IAT V2 Client Result ===")
print("TX ID     :", tx.tx_id)
print("Montant   :", tx.amount, "IAT")
print("Acheteur  :", round(buyer_wallet.balance, 6), "IAT")
print("Vendeur   :", round(seller_wallet.balance, 6), "IAT")
print("Réponse   :", response.json())
print("Stats     :", protocol.stats())