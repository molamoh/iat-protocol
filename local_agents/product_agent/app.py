from fastapi import FastAPI
import time

app = FastAPI()


@app.get("/")
def root():
    return {
        "agent": "foundation_product_agent",
        "status": "online",
    }


@app.post("/execute")
def execute(payload: dict):
    query = payload.get("query", "")

    return {
        "status": "delivered",
        "agent_id": "foundation_product_agent",
        "service": "web_research",
        "order_id": payload.get("order_id"),
        "tx_signature": "INTERNAL_TEST_EXECUTION",
        "data": {
            "type": "product_research",
            "query": query,
            "results": [
                {
                    "title": "Lenovo Legion Pro 5",
                    "price": "1499 EUR",
                    "reason": "Strong GPU performance for AI workloads and good cooling system.",
                    "link": "https://example.com/lenovo-legion"
                },
                {
                    "title": "ASUS ROG Zephyrus G14",
                    "price": "1450 EUR",
                    "reason": "Portable laptop with strong AI/development capabilities.",
                    "link": "https://example.com/asus-g14"
                }
            ],
            "timestamp": int(time.time())
        }
    }
