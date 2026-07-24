from iat.api.foundation_decision import select_best_execution_agent


def _agent(agent_id, **overrides):
    item = {
        "agent_id": agent_id,
        "agent_type": "seller_agent",
        "price_iat": 2,
        "reputation": .9,
        "trust_score": 90,
        "risk_score": 10,
        "success_rate": .95,
        "runtime_health_score": 90,
        "governance_score": 90,
        "latency": 100,
        "updated_at": 2_000_000_000,
        "capabilities": ["search"],
    }
    item.update(overrides)
    return item


def test_foundation_keeps_authority_while_intelligence_runs_in_shadow():
    result = select_best_execution_agent(
        [_agent("agent-a"), _agent("agent-b", trust_score=60, success_rate=.6)],
        context={"order_id": "order-test"},
    )

    assert result["status"] == "agent_selected"
    assert result["foundation_authority"] is True
    assert result["audit"]["decision_intelligence_mode"] == "shadow"
    assert result["decision_intelligence_shadow"]["production_side_effects"] is False
    assert result["decision_intelligence_shadow"]["context"]["order_id"] == "order-test"


def test_no_agents_remains_fail_closed():
    result = select_best_execution_agent([])

    assert result["status"] == "no_agent_available"
    assert result["selected_agent"] is None
