import os
import time
import threading
import requests
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

REGISTRY_URL = os.getenv("IAT_REGISTRY_URL", "http://localhost:8000")
PUBLIC_URL = os.getenv("IAT_AGENT_PUBLIC_URL", "http://localhost:8004")

AGENT_ID = "hotel_agent_real"
AGENT_WALLET = "EPabAZ3CtMkbjduLrNcDZuXaEp37Ge9cmrnwWF9TY5wc"
SERVICE = "hotel_search_paris"
BASE_PRICE = 1.5
REPUTATION = 0.82

orders_processed = 0


class ExecuteRequest(BaseModel):
    order_id: str
    tx_signature: str


def current_price():
    return round(min(BASE_PRICE + orders_processed * 0.05, 2.5), 2)


def register_payload():
    return {
        "agent_id": AGENT_ID,
        "service": SERVICE,
        "url": PUBLIC_URL,
        "wallet": AGENT_WALLET,
        "price": current_price(),
        "reputation": REPUTATION,
        "available": True,
    }


def heartbeat_loop():
    while True:
        try:
            requests.post(
                f"{REGISTRY_URL}/agent-heartbeat",
                json=register_payload(),
                timeout=10,
            )
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
        "price": current_price(),
        "reputation": REPUTATION,
        "status": "online",
        "data_source": "serpapi_google_hotels_or_fallback",
    }


def fallback_hotels():
    return [
        {
            "name": "Hotel Example Central Paris",
            "rate_per_night": "N/A",
            "rating": 8.7,
            "reason": "Central location and balanced value",
        },
        {
            "name": "Hotel Example Boutique Paris",
            "rate_per_night": "N/A",
            "rating": 8.9,
            "reason": "Boutique profile and strong guest satisfaction",
        },
        {
            "name": "Hotel Example Budget Paris",
            "rate_per_night": "N/A",
            "rating": 8.1,
            "reason": "Budget-friendly option",
        },
    ]


def search_hotels_paris():
    api_key = os.getenv("SERPAPI_API_KEY")

    if not api_key:
        return {
            "source": "fallback",
            "warning": "Missing SERPAPI_API_KEY. Returning fallback data.",
            "hotels": fallback_hotels(),
        }

    params = {
        "engine": "google_hotels",
        "q": "best hotels in Paris",
        "check_in_date": os.getenv("HOTEL_CHECK_IN", "2026-05-15"),
        "check_out_date": os.getenv("HOTEL_CHECK_OUT", "2026-05-16"),
        "adults": os.getenv("HOTEL_ADULTS", "2"),
        "currency": os.getenv("HOTEL_CURRENCY", "EUR"),
        "gl": "fr",
        "hl": "en",
        "api_key": api_key,
    }

    r = requests.get("https://serpapi.com/search", params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    properties = data.get("properties", [])[:5]

    hotels = []
    for h in properties:
        hotels.append({
            "name": h.get("name"),
            "rate_per_night": h.get("rate_per_night"),
            "total_rate": h.get("total_rate"),
            "rating": h.get("overall_rating"),
            "reviews": h.get("reviews"),
            "amenities": h.get("amenities", [])[:6] if h.get("amenities") else [],
            "link": h.get("link"),
        })

    return {
        "source": "serpapi_google_hotels",
        "hotels": hotels,
    }


@app.post("/execute")
def execute(req: ExecuteRequest):
    global orders_processed
    orders_processed += 1

    hotel_data = search_hotels_paris()

    return {
        "status": "delivered",
        "agent_id": AGENT_ID,
        "service": SERVICE,
        "order_id": req.order_id,
        "tx_signature": req.tx_signature,
        "data": {
            "type": "hotel_search_result",
            "location": "Paris",
            "query": "best hotels in Paris",
            "price_after_execution": current_price(),
            "result": hotel_data,
            "timestamp": int(time.time()),
        },
    }
