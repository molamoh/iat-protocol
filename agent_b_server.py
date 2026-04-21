from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from shared_protocol import WalletStore, VerifAI, IATProtocol

app = FastAPI(title="IAT Agent B Server")

store = WalletStore()
verifier = VerifAI()

try:
    seller_wallet = store.get_wallet("agent_b_seller")
except KeyError:
    seller_wallet = store.create_wallet("agent_b_seller")
    verifier.certify(seller_wallet, "llm-seller-v1")
    store.upsert_wallet(seller_wallet)

seller_wallet.certified = True
store.upsert_wallet(seller_wallet)

PRICE = 2.5


class OrderRequest(BaseModel):
    tx_id: str
    buyer_agent_id: str
    item: str = "btc_signal"


@app.get("/info")
def info():
    return {
        "agent": "agent_b_seller",
        "address": seller_wallet.address,
        "price": PRICE,
        "certified": seller_wallet.certified,
    }


@app.post("/buy-signal")
def buy_signal(order: OrderRequest):
    # Recharge le ledger à chaque requête pour voir les nouvelles transactions
    protocol = IATProtocol()

    tx = next((t for t in protocol.transactions if t.tx_id == order.tx_id), None)

    if not tx:
        raise HTTPException(status_code=404, detail="Transaction introuvable")

    if tx.receiver != seller_wallet.address:
        raise HTTPException(status_code=400, detail="Transaction non destinée au vendeur")

    if tx.amount < PRICE:
        raise HTTPException(status_code=400, detail="Paiement insuffisant")

    return {
        "status": "delivered",
        "item": order.item,
        "payload": {
            "signal": "BUY_ON_PULLBACK",
            "confidence": 0.72,
            "timeframe": "4h",
        },
        "paid_tx": tx.tx_id,
    }