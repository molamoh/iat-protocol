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

print("\n=== MARKET CANDIDATES ===")
for bid in res.get("selected_bids", []):
    print(
        f"- {bid.get('agent_id')} | "
        f"price={bid.get('price_iat')} IAT | "
        f"rep={bid.get('reputation')} | "
        f"score={bid.get('score')}"
    )

execution = res.get("execution", {})
execution = res.get("execution", {})
result = execution.get("result", {})
best = result.get("best", {})
consensus = result.get("consensus", {})
settlement = result.get("settlement", {})

print("\n=== EXECUTION ===")
print(f"Order ID: {execution.get('order_id')}")
print(f"Initial candidate: {execution.get('seller_id')}")
print(f"TX: {execution.get('tx_signature')}")
print(f"Buyer secret: {execution.get('buyer_secret')}")
print(f"Protocol status: {result.get('status')}")
print(f"Agents called: {result.get('agents_called')}")

print("\n=== CONSENSUS ===")
print(f"Consensus status: {consensus.get('status')}")
print(f"Consensus score: {consensus.get('score')}")
print(f"Suspicious agents: {consensus.get('suspicious_agents')}")

print("\n=== FINAL WINNER ===")
print(f"Winner agent: {best.get('agent_id')}")
print(f"Selection score: {best.get('selection_score')}")
print(f"Latency: {best.get('latency')}s")
print(f"Score details: {best.get('selection_score_details')}")

print("\n=== PAYOUT ===")
print(f"Winner payment status: {settlement.get('winner_payment_status')}")
print(f"Payout to agent: {settlement.get('payout_to_agent')}")
print(f"Payout tx: {settlement.get('payout_tx')}")

print("\n=== BEST RESULT ===")
data = best.get("data", {}).get("data", {})
for i, item in enumerate(data.get("results", [])[:5], start=1):
    print(f"{i}. {item.get('title')}")
    print(f"   {item.get('link')}")
