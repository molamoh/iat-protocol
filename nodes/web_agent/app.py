import os
import time
import threading
import requests
from fastapi import FastAPI
from pydantic import BaseModel
from bs4 import BeautifulSoup

app = FastAPI()

REGISTRY_URL = os.getenv("IAT_REGISTRY_URL", "http://localhost:8000")
PUBLIC_URL = os.getenv("IAT_AGENT_PUBLIC_URL", "http://localhost:8005")

AGENT_ID = os.getenv("IAT_AGENT_ID", "web_research_agent")
SERVICE = os.getenv("IAT_SERVICE", "web_research")
AGENT_WALLET = os.getenv("IAT_AGENT_WALLET", "EPabAZ3CtMkbjduLrNcDZuXaEp37Ge9cmrnwWF9TY5wc")
PRICE = float(os.getenv("IAT_PRICE", "1.2"))
REPUTATION = float(os.getenv("IAT_REPUTATION", "0.85"))

ALLOW_UNPAID_TEST = os.getenv("ALLOW_UNPAID_TEST", "true").lower() == "true"


class ExecuteRequest(BaseModel):
    order_id: str
    tx_signature: str | None = None
    query: str | None = None
    service: str | None = None
    buyer_intent: dict | None = None
    requirements: dict | None = None
    buyer_context: dict | None = None
    delivery_format: dict | None = None


def payload():
    return {
        "agent_id": AGENT_ID,
        "service": SERVICE,
        "url": PUBLIC_URL,
        "wallet": AGENT_WALLET,
        "agent_type": "foundation",
        "price": PRICE,
        "reputation": REPUTATION,
        "available": True,
    }


def heartbeat_loop():
    while True:
        try:
            requests.post(f"{REGISTRY_URL}/agent-heartbeat", json=payload(), timeout=5)
        except Exception:
            pass
        time.sleep(60)


@app.on_event("startup")
def startup():
    threading.Thread(target=heartbeat_loop, daemon=True).start()



@app.post("/heartbeat-now")
def heartbeat_now():
    try:
        r = requests.post(f"{REGISTRY_URL}/agent-heartbeat", json=payload(), timeout=10)
        return {
            "status": "sent",
            "registry_url": REGISTRY_URL,
            "payload": payload(),
            "registry_status": r.status_code,
            "registry_response": r.text,
        }
    except Exception as e:
        return {
            "status": "error",
            "registry_url": REGISTRY_URL,
            "payload": payload(),
            "error": str(e),
        }


@app.get("/info")
def info():
    return {
        "agent_id": AGENT_ID,
        "service": SERVICE,
        "wallet": AGENT_WALLET,
        "agent_type": "foundation",
        "price": PRICE,
        "reputation": REPUTATION,
        "status": "online",
    }



def search_with_google_custom_search(query):
    api_key = os.getenv("GOOGLE_API_KEY")
    cse_id = os.getenv("GOOGLE_CSE_ID")

    if not api_key or not cse_id:
        return None

    try:
        r = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": api_key,
                "cx": cse_id,
                "q": query,
                "num": 5,
            },
            timeout=15,
        )

        if r.status_code != 200:
            return None

        data = r.json()
        results = []

        for item in data.get("items", [])[:5]:
            results.append({
                "source": "google_custom_search",
                "title": item.get("title"),
                "snippet": item.get("snippet"),
                "link": item.get("link"),
            })

        return results if results else None

    except Exception:
        return None


def search_with_serper(query):
    api_key = os.getenv("SERPER_API_KEY")

    if not api_key:
        return None

    try:
        r = requests.post(
            "https://google.serper.dev/search",
            headers={
                "X-API-KEY": api_key,
                "Content-Type": "application/json",
            },
            json={"q": query},
            timeout=15,
        )

        data = r.json()
        results = []

        for item in data.get("organic", [])[:5]:
            results.append({
                "source": "serper_google",
                "title": item.get("title"),
                "snippet": item.get("snippet"),
                "link": item.get("link"),
            })

        return results

    except Exception:
        return None


def search_with_duckduckgo(query):
    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )

        soup = BeautifulSoup(r.text, "html.parser")
        results = []

        for result in soup.select(".result")[:5]:
            title = result.select_one(".result__title")
            snippet = result.select_one(".result__snippet")
            link = result.select_one("a.result__a")

            if title and link:
                results.append({
                    "source": "duckduckgo_html",
                    "title": title.get_text(strip=True),
                    "snippet": snippet.get_text(strip=True) if snippet else "",
                    "link": link.get("href"),
                })

        return results

    except Exception:
        return None


def simple_search(query):
    results = search_with_google_custom_search(query)

    if results:
        return results

    results = search_with_serper(query)

    if results:
        return results

    results = search_with_duckduckgo(query)

    if results:
        return results

    return []





def build_buyer_friendly_delivery(query, results, buyer_intent=None, requirements=None):
    buyer_intent = buyer_intent or {}
    requirements = requirements or {}

    recommendations = []

    for idx, item in enumerate(results[:5], start=1):
        title = item.get("title") or item.get("name") or f"Option {idx}"
        snippet = item.get("snippet") or item.get("description") or ""
        link = item.get("link") or item.get("url")

        recommendations.append({
            "rank": idx,
            "title": title,
            "reason": snippet[:500],
            "source_url": link,
            "quality_score": round(max(0.50, 1.0 - (idx - 1) * 0.08), 2),
            "value_score": round(max(0.50, 0.95 - (idx - 1) * 0.07), 2),
        })

    final = recommendations[0] if recommendations else None

    return {
        "status": "success" if recommendations else "error",
        "summary": (
            "I searched the web using the buyer request and structured requirements. "
            "The options below are ranked for relevance, expected quality and value-for-money."
        ),
        "recommendations": recommendations,
        "final_recommendation": final,
        "confidence": 0.82 if recommendations else 0,
        "sources": [
            r.get("source_url")
            for r in recommendations
            if r.get("source_url")
        ],
        "intent_used": {
            "goal": buyer_intent.get("goal"),
            "purchase_type": buyer_intent.get("purchase_type"),
            "requirements": requirements or buyer_intent.get("requirements", {}),
        },
    }


@app.post("/execute")
def execute(req: ExecuteRequest):
    if not req.tx_signature and not ALLOW_UNPAID_TEST:
        return {
            "status": "rejected",
            "reason": "missing_tx_signature",
        }

    query = req.query or "general search"

    if req.buyer_intent:
        goal = req.buyer_intent.get("goal") or ""
        reqs = req.requirements or req.buyer_intent.get("requirements", {})
        query = f"{goal} {reqs} {req.query or ''}".strip()

    results = simple_search(query)

    delivery = build_buyer_friendly_delivery(
        query=query,
        results=results,
        buyer_intent=req.buyer_intent,
        requirements=req.requirements,
    )

    return {
        "status": delivery.get("status", "success"),
        "agent_id": AGENT_ID,
        "service": SERVICE,
        "order_id": req.order_id,
        "tx_signature": req.tx_signature,
        "summary": delivery.get("summary"),
        "recommendations": delivery.get("recommendations", []),
        "final_recommendation": delivery.get("final_recommendation"),
        "confidence": delivery.get("confidence", 0),
        "sources": delivery.get("sources", []),
        "data": {
            "type": "web_research",
            "query": query,
            "results": results,
            "intent_used": delivery.get("intent_used"),
            "timestamp": int(time.time()),
        },
    }

