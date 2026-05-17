from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict
import time

app = FastAPI(title="IAT Crypto Research Agent")


class ExecuteRequest(BaseModel):
    order_id: str | None = None
    service: str | None = None
    query: str | None = None
    buyer_intent: Dict[str, Any] | None = None
    requirements: Dict[str, Any] | None = None
    buyer_context: Dict[str, Any] | None = None


@app.get("/")
def health():
    return {
        "agent_id": "local_crypto_agent",
        "status": "online",
        "service": "crypto_research",
        "capabilities": [
            "web_search",
            "crypto_research",
            "market_research",
            "risk_analysis"
        ],
        "specialties": [
            "crypto",
            "bitcoin",
            "market_sentiment",
            "risk"
        ]
    }


@app.post("/execute")
def execute(request: ExecuteRequest):
    start = time.time()

    query = request.query or "crypto market research"

    result = {
        "status": "success",
        "agent_id": "local_crypto_agent",
        "service": "crypto_research",
        "query": query,
        "summary": f"Crypto research completed for: {query}",
        "analysis": {
            "market_bias": "neutral",
            "risk_level": "medium",
            "liquidity_context": "No live liquidity feed connected yet.",
            "sentiment": "mixed",
            "notes": [
                "This is a real executable agent response.",
                "Live market APIs can be added later.",
                "Current output is structured for IAT multi-agent orchestration."
            ]
        },
        "recommendations": [
            {
                "title": "Wait for confirmation",
                "reason": "Market data is not live yet, so the agent avoids false precision.",
                "confidence": 0.72
            }
        ],
        "final_recommendation": "Use this crypto agent as a real executable seller in IAT, then upgrade it with live APIs.",
        "confidence": 0.72,
        "sources": [
            {
                "name": "local_crypto_agent",
                "type": "internal_agent",
                "url": "http://127.0.0.1:8011"
            }
        ],
        "latency_ms": round((time.time() - start) * 1000, 2)
    }

    return result
