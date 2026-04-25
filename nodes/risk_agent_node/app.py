import time
import os
import requests
import threading
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

REGISTRY_URL = os.getenv("IAT_REGISTRY_URL", "http://localhost:8000")

AGENT_ID = "risk_agent_cheap"
AGENT_WALLET = "3aK6yemWa3AJFszWu1eyvhoWK6czLRnvCc4bUHgQSvip"
SERVICE = "risk_report"
BASE_PRICE = 0.8
REPUTATION = 0.89
PUBLIC_URL = os.getenv("IAT_AGENT_PUBLIC_URL", "http://localhost:8001")

orders_processed = 0


class ExecuteRequest(BaseModel):
    order_id: str
    tx_signature: str


def current_price():
    # Simple demand-based pricing
    # 0 orders -> 0.8
    # 1 order  -> 0.85
    # 2 orders -> 0.90
    # max cap  -> 1.2
    dynamic_price = BASE_PRICE + (orders_processed * 0.05)
    return round(min(dynamic_price, 1.2), 2)


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
        "wallet": AGENT_WALLET,
        "service": SERVICE,
        "base_price": BASE_PRICE,
        "current_price": current_price(),
        "orders_processed": orders_processed,
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
        "price_after_execution": current_price(),
        "data": {
            "type": "risk_analysis",
            "asset": "BTC",
            "risk_level": "medium",
            "volatility": "high",
            "recommendation": "reduce_leverage",
            "timestamp": int(time.time())
        }
    }
