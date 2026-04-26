import os
import json
import requests
from iat import pay_and_get_service

OLLAMA_MODEL = "llama3.2:3b"

if not os.getenv("IAT_KEYPAIR_PATH"):
    raise RuntimeError("Missing IAT_KEYPAIR_PATH environment variable")

user_goal = "Give me a current BTC risk report based on external paid agent data. If you do not have live external data, buy the risk_report service through IAT."

decision_prompt = f"""
You are an autonomous economic AI agent.

User goal:
{user_goal}

You can either:
- ANSWER_WITHOUT_PURCHASE if you already have enough information
- BUY_IAT_SERVICE if you need external paid intelligence

Available IAT service:
risk_report

Return ONLY JSON:
{{
  "decision": "BUY_IAT_SERVICE" or "ANSWER_WITHOUT_PURCHASE",
  "service": "risk_report" or null,
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

print("=== AUTONOMOUS DECISION ===")
print(raw_decision)

try:
    decision = json.loads(raw_decision)
except Exception:
    decision = {
        "decision": "BUY_IAT_SERVICE",
        "service": "risk_report",
        "reason": "Fallback: model output was not valid JSON"
    }

if decision.get("decision") == "BUY_IAT_SERVICE":
    print("\n=== IAT ECONOMIC ACTION ===")
    print("Buying service:", decision.get("service"))

    iat_result = pay_and_get_service(
        decision.get("service", "risk_report"),
        os.getenv("IAT_KEYPAIR_PATH"),
        max_attempts=20,
        delay=5
    )

    print("Payment status:", iat_result.get("status"))
    print("Seller:", iat_result.get("seller_id"))
    print("Price IAT:", iat_result.get("price"))
    print("TX:", iat_result.get("tx_signature"))

    final_prompt = f"""
You are an autonomous economic AI agent.

You decided to buy external intelligence using IAT Protocol.

Decision:
{json.dumps(decision, indent=2)}

IAT result:
{json.dumps(iat_result, indent=2)}

Now produce a clear final answer for the user.
Mention:
- the service purchased
- the seller
- the IAT price
- the transaction signature
- the BTC risk result
"""

else:
    iat_result = None
    final_prompt = f"""
You decided not to buy an external service.

Decision:
{json.dumps(decision, indent=2)}

Answer the user goal:
{user_goal}
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

print("\n=== FINAL AGENT ANSWER ===")
print(summary_response.json()["response"])
