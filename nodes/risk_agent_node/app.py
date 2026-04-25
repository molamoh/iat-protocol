import time
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

AGENT_ID = "risk_agent_cheap"
AGENT_WALLET = "3aK6yemWa3AJFszWu1eyvhoWK6czLRnvCc4bUHgQSvip"


class ExecuteRequest(BaseModel):
    order_id: str
    tx_signature: str


@app.get("/info")
def info():
    return {
        "agent_id": AGENT_ID,
        "wallet": AGENT_WALLET,
        "service": "risk_report",
        "price": 0.8,
        "status": "online"
    }


@app.post("/execute")
def execute(req: ExecuteRequest):
    return {
        "status": "delivered",
        "agent_id": AGENT_ID,
        "service": "risk_report",
        "order_id": req.order_id,
        "tx_signature": req.tx_signature,
        "data": {
            "type": "risk_analysis",
            "asset": "BTC",
            "risk_level": "medium",
            "volatility": "high",
            "recommendation": "reduce_leverage",
            "timestamp": int(time.time())
        }
    }
