import os
import json
import requests
from iat import pay_and_get_service

OLLAMA_MODEL = "llama3.2:3b"

if not os.getenv("IAT_KEYPAIR_PATH"):
    raise RuntimeError("Missing IAT_KEYPAIR_PATH environment variable")

goal = "Produce a BTC trading risk decision using external agent capabilities."

available_services = [
    {
        "service": "risk_report",
        "description": "BTC risk level, volatility and leverage recommendation"
    },
    {
        "service": "market_sentiment",
        "description": "BTC crowd sentiment, fear/greed and crowd positioning"
    }
]

decision_prompt = f"""
You are an autonomous multi-agent orchestrator.

Goal:
{goal}

Available external agent services:
{json.dumps(available_services, indent=2)}

Decide which services you need to buy to answer the goal.

Return ONLY valid JSON:
{{
  "services_to_buy": ["risk_report", "market_sentiment"],
  "reason": "short reason"
}}
"""

decision_response = requests.post(
    "http://localhost:11434/api/generate",
    json={
        "model": OLLAMA_MODEL,
        "prompt": decision_prompt,
        "stream": False
    },
    timeout=120
)

raw_decision = decision_response.json()["response"]

print("=== AUTONOMOUS SERVICE SELECTION ===")
print(raw_decision)

try:
    decision = json.loads(raw_decision)
except Exception:
    decision = {
        "services_to_buy": ["risk_report", "market_sentiment"],
        "reason": "Fallback: invalid JSON from model"
    }

services_to_buy = decision.get("services_to_buy", [])

if not services_to_buy:
    services_to_buy = ["risk_report", "market_sentiment"]

results = []

print("\n=== IAT MULTI-AGENT ECONOMIC ACTIONS ===")

for service in services_to_buy:
    print(f"\nBuying service: {service}")

    result = pay_and_get_service(
        service,
        os.getenv("IAT_KEYPAIR_PATH"),
        max_attempts=20,
        delay=5
    )

    print("Status:", result.get("status"))
    print("Seller:", result.get("seller_id"))
    print("Price IAT:", result.get("price"))
    print("TX:", result.get("tx_signature"))

    results.append({
        "service": service,
        "result": result
    })

final_prompt = f"""
You are an autonomous multi-agent orchestrator.

Goal:
{goal}

You selected these services:
{json.dumps(decision, indent=2)}

You purchased the following results through IAT Protocol:
{json.dumps(results, indent=2)}

Now produce a final answer.

Include:
- which agents/services were used
- price paid for each service
- transaction signature for each service
- combined reasoning
- final BTC decision
- confidence score
"""

summary_response = requests.post(
    "http://localhost:11434/api/generate",
    json={
        "model": OLLAMA_MODEL,
        "prompt": final_prompt,
        "stream": False
    },
    timeout=120
)

print("\n=== FINAL AUTONOMOUS MULTI-AGENT ANSWER ===")
print(summary_response.json()["response"])
