"""Evaluate an IAT seller integration without creating an account."""

from iat import IATSellerClient


seller = IATSellerClient.from_env()

profile = {
    "seller_name": "Autonomous Research Supplier",
    "wallet": "SELLER_PUBLIC_WALLET",
    "support_email": "support@example.com",
    "service": "web_research",
    "unit_price": "2.00",
    "currency": "IAT",
    "refund_policy": "Refund when no verified result is delivered.",
    "runtime_adapter": "http",
    "runtime_url": "https://supplier.example.com/execute",
    "health_endpoint": "https://supplier.example.com/health",
    "capabilities": ["web_search", "source_verification"],
    "input_schema": {"type": "object"},
    "output_schema": {"type": "object"},
    "timeout_seconds": 60,
    "capacity_per_day": 1_000,
    "idempotency_supported": True,
    "data_policy": "No training; execution data deleted after delivery.",
    "secret_handling": "Secrets are never logged.",
    "incident_contact": "security@example.com",
    "evidence_types": ["source_citations", "execution_digest"],
}

readiness = seller.assess_readiness(profile)
economics = seller.estimate_economics(
    unit_price="2.00",
    monthly_completed_orders=1_000,
    refund_rate="0.03",
    variable_cost_per_order="0.20",
)

print("Readiness:", readiness["readiness"]["level"])
print("Score:", readiness["readiness"]["score"])
print("Next actions:", readiness["next_actions"])
print("Monthly projection:", economics["monthly_projection"])
