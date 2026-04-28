from iat import enable_ai_market

QUERY = "best hotels in Paris"

market = enable_ai_market()
res = market.buy("web_research", query=QUERY)

print("\n=== IAT PAID MULTI-CALL DEMO ===")
print(f"Status: {res.get('status')}")
print(f"Order ID: {res.get('order_id')}")
print(f"Seller paid: {res.get('seller_id')}")
print(f"Price IAT: {res.get('price')}")
print(f"TX: {res.get('tx_signature')}")

result = res.get("result", {})
print("\n=== MULTI-CALL RESULT ===")
print(f"Protocol status: {result.get('status')}")
print(f"Agents called: {result.get('agents_called')}")
print(f"Query: {result.get('query')}")

best = result.get("best", {})
print("\n=== BEST AGENT ===")
print(f"Agent: {best.get('agent_id')}")
print(f"Latency: {best.get('latency')}s")

data = best.get("data", {}).get("data", {})
results = data.get("results", [])

print("\n=== TOP RESULTS ===")
for i, item in enumerate(results[:5], start=1):
    print(f"{i}. {item.get('title')}")
    print(f"   {item.get('snippet')}")
    print(f"   {item.get('link')}")
