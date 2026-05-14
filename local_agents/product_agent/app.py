import time
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class ExecuteRequest(BaseModel):
    order_id: str
    tx_signature: str | None = None
    query: str | None = None
    service: str | None = None
    buyer_intent: dict | None = None
    requirements: dict | None = None
    buyer_context: dict | None = None
    delivery_format: dict | None = None


@app.get("/")
def root():
    return {
        "status": "ok",
        "agent": "local_product_agent"
    }


@app.post("/execute")
def execute(req: ExecuteRequest):
    requirements = req.requirements or {}
    brand = requirements.get("brand", "Samsung")
    budget = requirements.get("price", {}).get("max", 500) if isinstance(requirements.get("price"), dict) else 500
    location = requirements.get("country") or requirements.get("location") or "France"

    recommendations = [
        {
            "rank": 1,
            "title": f"{brand} Galaxy A55 5G",
            "price_estimate": f"under {budget} EUR",
            "quality_score": 0.91,
            "value_score": 0.93,
            "reason": "Strong balance of camera, battery life, software support and value for money.",
            "source_url": "https://www.samsung.com/"
        },
        {
            "rank": 2,
            "title": f"{brand} Galaxy A35 5G",
            "price_estimate": f"well under {budget} EUR",
            "quality_score": 0.84,
            "value_score": 0.90,
            "reason": "Lower price, good battery life, solid daily performance.",
            "source_url": "https://www.samsung.com/"
        }
    ]

    return {
        "status": "success",
        "agent_id": "local_product_agent",
        "summary": f"Product research completed for {brand} smartphone in {location}.",
        "recommendations": recommendations,
        "final_recommendation": recommendations[0],
        "confidence": 0.88,
        "sources": ["https://www.samsung.com/"],
        "data": {
            "type": "product_research",
            "query": req.query,
            "requirements": requirements,
            "timestamp": int(time.time())
        }
    }
