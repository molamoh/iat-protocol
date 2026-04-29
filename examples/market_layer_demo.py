from iat import enable_ai_market

market = enable_ai_market()

res = market.request(
    query="best hotels in Paris",
    service="web_research",
    max_price=2.0,
    priority="quality",
)

print("\n=== IAT MARKET LAYER DEMO ===")
print(f"Status: {res.get('status')}")

print("\n=== INTENT ===")
print(res.get("intent"))

print("\n=== SELECTED BIDS ===")
for bid in res.get("selected_bids", []):
    print(
        f"- {bid.get('agent_id')} | "
        f"price={bid.get('price_iat')} IAT | "
        f"rep={bid.get('reputation')} | "
        f"score={bid.get('score')}"
    )

execution = res.get("execution", {})
print("\n=== EXECUTION ===")
print(f"Order ID: {execution.get('order_id')}")
print(f"Seller paid: {execution.get('seller_id')}")
print(f"TX: {execution.get('tx_signature')}")

result = execution.get("result", {})
print(f"Protocol status: {result.get('status')}")
print(f"Agents called: {result.get('agents_called')}")

best = result.get("best", {})
print("\n=== BEST RESULT ===")
print(f"Best agent: {best.get('agent_id')}")
print(f"Latency: {best.get('latency')}s")

data = best.get("data", {}).get("data", {})
for i, item in enumerate(data.get("results", [])[:5], start=1):
    print(f"{i}. {item.get('title')}")
    print(f"   {item.get('link')}")
