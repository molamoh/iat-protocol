"""Run against a local IAT API; no wallet or funds are required."""

from iat import IATClient


client = IATClient.from_env()

manifest = client.discover()
print("Protocol:", manifest["protocol"]["name"], manifest["protocol"]["version"])

preview = client.sandbox_preview(
    "web_research",
    goal="Compare autonomous agent payment protocols",
    max_price="2.00",
    strategy="quality",
    required_capabilities=["source_verification"],
)
print("Selected:", preview["selected_offer"]["offer_id"])

order = client.sandbox_buy(
    "web_research",
    goal="Compare autonomous agent payment protocols",
    max_price="2.00",
    strategy="quality",
    required_capabilities=["source_verification"],
    idempotency_key="quickstart-research-001",
)
print("Order:", order["order_id"])
print("Funds moved:", order["funds_moved"])
print("Result:", order["result"]["summary"])
