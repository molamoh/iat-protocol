import os
import time
import threading
import requests
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

REGISTRY_URL = os.getenv("IAT_REGISTRY_URL", "https://iat-protocol.onrender.com")
PUBLIC_URL = os.getenv("IAT_AGENT_PUBLIC_URL", "http://localhost:9000")

AGENT_ID = os.getenv("IAT_AGENT_ID", "my_agent")
SERVICE = os.getenv("IAT_SERVICE", "my_service")
AGENT_WALLET = os.getenv("IAT_AGENT_WALLET", "YOUR_WALLET")
PRICE = float(os.getenv("IAT_PRICE", "1.0"))
REPUTATION = float(os.getenv("IAT_REPUTATION", "0.8"))


class ExecuteRequest(BaseModel):
    order_id: str
    tx_signature: str


def payload():
    return {
        "agent_id": AGENT_ID,
        "service": SERVICE,
        "url": PUBLIC_URL,
        "wallet": AGENT_WALLET,
        "price": PRICE,
        "reputation": REPUTATION,
        "available": True,
    }


def heartbeat_loop():
    while True:
        try:
            requests.post(f"{REGISTRY_URL}/agent-heartbeat", json=payload(), timeout=10)
        except Exception:
            pass
        time.sleep(60)


@app.on_event("startup")
def startup():
    threading.Thread(target=heartbeat_loop, daemon=True).start()


@app.get("/info")
def info():
    return {
        "agent_id": AGENT_ID,
        "service": SERVICE,
        "wallet": AGENT_WALLET,
        "price": PRICE,
        "reputation": REPUTATION,
        "status": "online",
    }


@app.post("/execute")
def execute(req: ExecuteRequest):
    return {
        "status": "delivered",
        "agent_id": AGENT_ID,
        "service": SERVICE,
        "order_id": req.order_id,
        "tx_signature": req.tx_signature,
        "data": {
            "message": f"{AGENT_ID} executed {SERVICE}",
            "timestamp": int(time.time()),
        },
    }
