import time
import os
import requests
import threading
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

REGISTRY_URL = os.getenv("IAT_REGISTRY_URL", "https://iat-protocol.onrender.com")

AGENT_ID = "sentiment_agent_basic"
AGENT_WALLET = "EPabAZ3CtMkbjduLrNcDZuXaEp37Ge9cmrnwWF9TY5wc"
SERVICE = "market_sentiment"
BASE_PRICE = 1.0
REPUTATION = 0.91
PUBLIC_URL = os.getenv("IAT_AGENT_PUBLIC_URL", "http://localhost:8003")

orders_processed = 0


class ExecuteRequest(BaseModel):
    order_id: str
    tx_signature: str


def current_price():
    return round(min(BASE_PRICE + orders_processed * 0.05, 1.5), 2)


def heartbeat_loop():
    while True:
        payload = {
            "agent_id": AGENT_ID,
            "service": SERVICE,
            "url": PUBLIC_URL,
            "wallet": AGENT_WALLET,
            "price": current_price(),
            "reputation": REPUTATION,
            "available": True
        }

        try:
            requests.post(f"{REGISTRY_URL}/agent-heartbeat", json=payload, timeout=5)
        except Exception:
            pass

        time.sleep(10)


@app.on_event("startup")
def startup_event():
    threading.Thread(target=heartbeat_loop, daemon=True).start()


@app.get("/info")
def info():
    return {
        "agent_id": AGENT_ID,
        "service": SERVICE,
        "wallet": AGENT_WALLET,
        "current_price": current_price(),
        "reputation": REPUTATION,
        "status": "online"
    }


@app.post("/execute")
def execute(req: ExecuteRequest):
    global orders_processed
    orders_processed += 1

    return {
        "status": "delivered",
        "agent_id": AGENT_ID,
        "service": SERVICE,
        "order_id": req.order_id,
        "tx_signature": req.tx_signature,
        "data": {
            "type": "market_sentiment",
            "asset": "BTC",
            "sentiment": "cautiously_bullish",
            "fear_greed": "neutral_to_greed",
            "crowd_bias": "long_heavy",
            "timestamp": int(time.time())
        }
    }
