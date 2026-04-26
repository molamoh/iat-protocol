import os
from iat import pay_and_get_service

KEYPAIR_PATH = os.getenv("IAT_KEYPAIR_PATH")

if not KEYPAIR_PATH:
    raise RuntimeError("Missing IAT_KEYPAIR_PATH environment variable")

result = pay_and_get_service(
    "risk_report",
    KEYPAIR_PATH,
    max_attempts=20,
    delay=5
)

print("=== IAT PROTOCOL DEMO ===")
print("Service:", result.get("result", {}).get("service"))
print("Status:", result.get("status"))
print("Seller:", result.get("seller_id"))
print("Price IAT:", result.get("price"))
print("TX:", result.get("tx_signature"))
print("Delivered data:")
print(result.get("result", {}).get("data"))
