from solders.keypair import Keypair

from iat.api import agent_b_api, db


def _risk_policy(*, score):
    return agent_b_api.compute_release_policy(
        verdict="foundation_verified_with_evidence",
        financial_risk={
            "release_risk_score": score,
            "release_risk_level": "low",
        },
        decision_confidence=0.75,
        verification_confidence=0.8,
        financial_release_confidence_raw=0.86,
        verified_count=5,
        rejected_count=0,
        uncertain_count=0,
    )


def test_zero_risk_is_not_replaced_by_default_high_risk():
    policy = _risk_policy(score=0)
    authority = agent_b_api.authorize_release_from_risk(
        verdict="foundation_verified_with_evidence",
        financial_release_confidence=policy["financial_release_confidence"],
        verified_count=5,
        rejected_count=0,
        risk_result={"release_risk_score": 0},
        release_policy=policy,
    )

    assert policy["release_policy_mode"] == "automatic"
    assert "verified_evidence_low_risk" in policy["policy_reasons"]
    assert authority["release_authorized"] is True
    assert "release_risk_score_high" not in authority["release_block_reasons"]


def test_missing_risk_still_fails_closed():
    policy = _risk_policy(score=None)

    assert policy["release_policy_mode"] == "manual_review"
    assert policy["max_payout_mode"] == "none"


def _configure_recovery(monkeypatch, authorization):
    winner_wallet = str(Keypair().pubkey())
    treasury_wallet = str(Keypair().pubkey())
    monkeypatch.setenv("IAT_PROTOCOL_TREASURY_WALLET", treasury_wallet)
    monkeypatch.setattr(
        db,
        "get_settlement_by_id_db",
        lambda _settlement_id: {"order_id": "order-canary"},
    )
    monkeypatch.setattr(
        agent_b_api,
        "get_order_db",
        lambda _order_id: {"delivery_result": {}},
    )
    monkeypatch.setattr(
        agent_b_api,
        "resolve_settlement_candidate",
        lambda _order, _delivery: {
            "status": "resolved",
            "source": "test",
            "best": {"agent_id": "seller", "wallet": "logical_wallet"},
        },
    )
    monkeypatch.setattr(
        agent_b_api,
        "resolve_payment_wallet",
        lambda _wallet, agent=None: {
            "valid": True,
            "resolved_wallet": winner_wallet,
        },
    )
    monkeypatch.setattr(
        agent_b_api,
        "authorize_settlement_release",
        lambda _order_id: authorization,
    )
    return winner_wallet, treasury_wallet


def test_manual_review_recovery_cannot_bypass_authorization(monkeypatch):
    winner_wallet, treasury_wallet = _configure_recovery(
        monkeypatch,
        {
            "release_authorized": False,
            "authorization_mode": "manual_review",
            "authorization_reason": "release_policy_manual_review_required",
        },
    )
    captured = {}

    def recover(**kwargs):
        captured.update(kwargs)
        return {"status": "settlement_recovered_manual_review_required"}

    monkeypatch.setattr(db, "recover_settlement_wallet_configuration_db", recover)

    result = agent_b_api.admin_recover_settlement_wallets("settlement", _admin=True)

    assert result["status"] == "settlement_recovered_manual_review_required"
    assert captured["winner_wallet"] == winner_wallet
    assert captured["treasury_wallet"] == treasury_wallet
    assert captured["next_status"] == "manual_review"


def test_blocked_release_policy_cannot_recover_or_authorize(monkeypatch):
    _configure_recovery(
        monkeypatch,
        {
            "release_authorized": False,
            "authorization_mode": "blocked",
            "authorization_reason": "release_policy_blocked",
        },
    )
    called = False

    def recover(**_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(db, "recover_settlement_wallet_configuration_db", recover)

    result = agent_b_api.admin_recover_settlement_wallets("settlement", _admin=True)

    assert result["status"] == "recovery_blocked"
    assert result["reason"] == "release_policy_blocked"
    assert called is False


def test_db_recovery_rejects_unapproved_target_state():
    result = db.recover_settlement_wallet_configuration_db(
        settlement_id="settlement",
        winner_id="seller",
        winner_wallet=str(Keypair().pubkey()),
        treasury_wallet=str(Keypair().pubkey()),
        next_status="ready_for_release",
    )

    assert result["status"] == "error"
    assert result["reason"] == "invalid_wallet_recovery_next_status"
