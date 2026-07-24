import pytest

from iat.intelligence.seller_intelligence import (
    SellerIntelligenceError,
    analyze_seller_offer,
)


def _offer(offer_id, price, **overrides):
    item = {
        "offer_id": offer_id,
        "price": price,
        "quality": 80,
        "trust": 80,
        "reliability": 80,
        "latency_score": 80,
        "capabilities": ["search"],
    }
    item.update(overrides)
    return item


def test_seller_analysis_is_explainable_and_never_mutates_offer():
    seller = _offer("seller", 8)
    original = dict(seller)
    result = analyze_seller_offer(
        seller,
        [
            _offer("market-a", 5, capabilities=["search", "citations"]),
            _offer("market-b", 6, quality=95, capabilities=["search", "citations"]),
        ],
        monthly_orders=100,
        variable_cost_per_order=2,
        commission_rate=.1,
    )

    assert seller == original
    assert result["market"]["median_price"] == 5.5
    assert result["capability_gaps"] == ["citations"]
    assert result["governance"]["automatic_price_change_allowed"] is False
    assert result["decision_snapshot"]["decision_hash"]


def test_scenarios_never_label_below_break_even_as_positive():
    result = analyze_seller_offer(
        _offer("seller", 1),
        [_offer("a", 1), _offer("b", 2)],
        monthly_orders=100,
        variable_cost_per_order=2,
        commission_rate=.1,
    )

    assert result["break_even_unit_price"] > 2
    assert not any(item["economically_positive"] for item in result["scenarios"])


def test_benchmark_set_and_identity_fail_closed():
    with pytest.raises(SellerIntelligenceError, match="2_to_100"):
        analyze_seller_offer(_offer("seller", 2), [_offer("only", 2)])

    with pytest.raises(SellerIntelligenceError, match="duplicate_offer_id"):
        analyze_seller_offer(
            _offer("seller", 2),
            [_offer("seller", 2), _offer("other", 2)],
        )
