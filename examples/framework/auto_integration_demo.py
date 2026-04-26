from iat import enable_iat_economy

tool = enable_iat_economy()

result = tool.run("risk_report")

print("=== IAT AUTO INTEGRATION DEMO ===")
print("Status:", result.get("status"))
print("Seller:", result.get("seller_id"))
print("Price IAT:", result.get("price"))
print("TX:", result.get("tx_signature"))
print("Data:", result.get("result", {}).get("data"))
