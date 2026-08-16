from iat.buyer_discovery import build_buyer_intent_preview


def record(agent_id, price, *, trust=90, reputation=.8, health=95, capabilities=None):
    return {
        "seller_agent_id": agent_id,
        "seller_id": f"private-{agent_id}",
        "agent_id": f"registry-{agent_id}",
        "service": "web_research",
        "service_type": "web_research",
        "catalog_item_id": f"catalog-{agent_id}",
        "title": f"Research {agent_id}",
        "unit_price": price,
        "currency": "IAT",
        "capabilities": capabilities or '["source_verification"]',
        "specialties": "[]",
        "reputation": reputation,
        "successful_orders": 8,
        "failed_orders": 2,
        "runtime_health_score": health,
        "runtime_validation_status": "active",
        "catalog_verification_status": "foundation_verified",
        "seller_trust_score": trust,
        "seller_risk_score": 1,
        "capacity_per_day": 10,
        "capacity_per_order": 1,
        "url": "https://private-runtime.example",
        "wallet": "private-wallet",
    }


def test_preview_selects_policy_compliant_candidate_without_private_fields():
    result = build_buyer_intent_preview(
        [record("safe", 2, trust=95), record("cheap", 1, trust=40)],
        wallet="buyer-wallet",
        service="web_research",
        goal="Research current protocol developments with cited sources",
        maximum_price=3,
        strategy="safest",
        required_capabilities=["source_verification"],
        now=100,
    )
    assert result["status"] == "selected"
    assert result["selected"]["candidate_id"] == "safe"
    facts = result["selected"]["facts"]
    assert facts["catalog_item_id"] == "catalog-safe"
    assert "wallet" not in facts
    assert "url" not in facts
    assert result["funds_reserved"] is False
    assert result["selection_is_quote"] is False


def test_preview_rejects_price_and_missing_capability_constraints():
    result = build_buyer_intent_preview(
        [
            record("expensive", 5),
            record("missing", 1, capabilities='["summarization"]'),
        ],
        wallet="buyer-wallet",
        service="web_research",
        goal="Research current protocol developments with cited sources",
        maximum_price=2,
        strategy="balanced",
        required_capabilities=["source_verification"],
        now=100,
    )
    assert result["status"] == "no_eligible_candidate"
    rejected = {item["candidate_id"]: item["reasons"] for item in result["rejected_candidates"]}
    assert "price_above_maximum" in rejected["expensive"]
    assert "required_capabilities_missing" in rejected["missing"]
    assert result["next_action"] == "refine_intent"

