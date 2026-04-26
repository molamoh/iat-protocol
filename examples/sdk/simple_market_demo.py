from iat import enable_ai_market

market = enable_ai_market()

result = market.buy("risk_report")

print("=== IAT AI MARKET DEMO ===")
print("Status:", result.get("status"))
print("Seller:", result.get("seller_id"))
print("Price IAT:", result.get("price"))
print("TX:", result.get("tx_signature"))
print("Data:", result.get("result", {}).get("data"))
