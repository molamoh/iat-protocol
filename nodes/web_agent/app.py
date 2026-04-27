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


class ExecuteRequest(BaseModel):
    order_id: str
    tx_signature: str
    query: str | None = None


# -------- REGISTRATION --------

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
            requests.post(f"{REGISTRY_URL}/agent-heartbeat", json=payload(), timeout=5)
        except Exception:
            pass
        time.sleep(10)


@app.on_event("startup")
def startup():
    threading.Thread(target=heartbeat_loop, daemon=True).start()


# -------- WEB SEARCH --------

def simple_search(query):
    try:
        url = f"https://html.duckduckgo.com/html/?q={query}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")

        results = []
        for result in soup.select(".result")[:5]:
            title = result.select_one(".result__title")
            snippet = result.select_one(".result__snippet")
            link = result.select_one("a")

            if title and link:
                results.append({
                    "title": title.get_text(strip=True),
                    "snippet": snippet.get_text(strip=True) if snippet else "",
                    "link": link.get("href")
                })

        
        if not results:
            return [{
                "title": "No results found",
                "snippet": "Search engine returned no data. Possible block or HTML change.",
                "link": ""
            }]
        return results


    except Exception as e:
        return [{"error": str(e)}]


# -------- EXECUTE --------

@app.post("/execute")
def execute(req: ExecuteRequest):
    query = req.query if req.query else "general search"

    results = simple_search(query)

    return {
        "status": "delivered",
        "agent_id": AGENT_ID,
        "service": SERVICE,
        "data": {
            "type": "web_research",
            "query": query,
            "results": results,
            "timestamp": int(time.time())
        }
    }
