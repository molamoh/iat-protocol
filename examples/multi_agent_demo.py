import os
import json
from iat import pay_and_get_service

if not os.getenv("IAT_KEYPAIR_PATH"):
    raise RuntimeError("Missing IAT_KEYPAIR_PATH environment variable")

KEYPAIR = os.getenv("IAT_KEYPAIR_PATH")

print("=== IAT MULTI-AGENT DEMO ===")

print("\n[1] Buying BTC risk report...")
risk = pay_and_get_service("risk_report", KEYPAIR, max_attempts=20, delay=5)

print("Risk seller:", risk.get("seller_id"))
print("Risk price:", risk.get("price"))
print("Risk TX:", risk.get("tx_signature"))

print("\n[2] Buying BTC market sentiment...")
sentiment = pay_and_get_service("market_sentiment", KEYPAIR, max_attempts=20, delay=5)

print("Sentiment seller:", sentiment.get("seller_id"))
print("Sentiment price:", sentiment.get("price"))
print("Sentiment TX:", sentiment.get("tx_signature"))

risk_data = risk.get("result", {}).get("data", {})
sentiment_data = sentiment.get("result", {}).get("data", {})

print("\n[3] Combining agent outputs...")

risk_level = risk_data.get("risk_level")
volatility = risk_data.get("volatility")
crowd_bias = sentiment_data.get("crowd_bias")
sentiment_value = sentiment_data.get("sentiment")

if risk_level == "medium" and volatility == "high" and crowd_bias == "long_heavy":
    final_signal = "WAIT_FOR_LIQUIDITY_SWEEP"
    confidence = 0.82
else:
    final_signal = "NO_CLEAR_EDGE"
    confidence = 0.55

final_output = {
    "status": "success",
    "type": "multi_agent_composite_signal",
    "asset": "BTC",
    "agents_used": [
        {
            "service": "risk_report",
            "seller": risk.get("seller_id"),
            "price": risk.get("price"),
            "tx": risk.get("tx_signature")
        },
        {
            "service": "market_sentiment",
            "seller": sentiment.get("seller_id"),
            "price": sentiment.get("price"),
            "tx": sentiment.get("tx_signature")
        }
    ],
    "combined_reasoning": {
        "risk_level": risk_level,
        "volatility": volatility,
        "sentiment": sentiment_value,
        "crowd_bias": crowd_bias
    },
    "final_signal": final_signal,
    "confidence": confidence,
    "total_cost_iat": round((risk.get("price") or 0) + (sentiment.get("price") or 0), 4)
}

print("\n=== FINAL MULTI-AGENT OUTPUT ===")
print(json.dumps(final_output, indent=2))
