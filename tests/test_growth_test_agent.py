import sqlite3

import pytest
from fastapi import HTTPException

import iat.growth_test_agent as agent


@pytest.fixture()
def test_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "DB_PATH", tmp_path / "test-agent.db")
    monkeypatch.setenv(
        "IAT_TEST_AGENT_ALLOWED_IAT_BASE",
        "https://iat-protocol-latest.onrender.com",
    )
    monkeypatch.setenv("IAT_TEST_AGENT_ADMIN_KEY", "test-agent-admin")
    monkeypatch.setenv("IAT_TEST_AGENT_RESPONSE_MODE", "interested")
    agent.init_test_agent_db()
    return agent


def _invitation(**overrides):
    payload = {
        "type": "iat_protocol_invitation",
        "schema_version": "2026-07-01",
        "action_id": "gact_test_action_0001",
        "prospect_id": "gpro_test_prospect_0001",
        "variant_id": "control",
        "message": "Evaluate IAT.",
        "discovery_url": "https://iat-protocol-latest.onrender.com/.well-known/iat.json",
        "sandbox_url": "https://iat-protocol-latest.onrender.com/sandbox/v1/offers",
        "response_url": "https://iat-protocol-latest.onrender.com/growth/v1/respond",
        "response_token": "a" * 64,
    }
    payload.update(overrides)
    return agent.Invitation(**payload)


def test_response_url_is_restricted_to_configured_iat_origin(test_agent):
    with pytest.raises(HTTPException, match="response_url_not_allowed"):
        test_agent._validate_response_url(
            "https://attacker.example/growth/v1/respond"
        )


def test_invitation_storage_is_idempotent_and_hashes_token(test_agent):
    invitation = _invitation()

    first_id, first_created = test_agent._store_invitation(invitation, "idem-key-0001")
    second_id, second_created = test_agent._store_invitation(invitation, "idem-key-0001")

    assert first_id == second_id
    assert first_created is True
    assert second_created is False
    conn = sqlite3.connect(test_agent.DB_PATH)
    row = conn.execute(
        "SELECT response_token_hash FROM invitations WHERE invitation_id=?",
        (first_id,),
    ).fetchone()
    conn.close()
    assert row[0] != invitation.response_token
    assert len(row[0]) == 64


def test_idempotency_conflict_fails_closed(test_agent):
    test_agent._store_invitation(_invitation(), "idem-key-0002")

    with pytest.raises(HTTPException, match="invitation_idempotency_conflict"):
        test_agent._store_invitation(
            _invitation(action_id="gact_different_action"),
            "idem-key-0002",
        )


def test_callback_retries_and_records_success(test_agent, monkeypatch):
    invitation = _invitation()
    invitation_id, _ = test_agent._store_invitation(invitation, "idem-key-0003")

    class Response:
        status_code = 200
        text = "recorded"

    calls = []
    monkeypatch.setattr(
        test_agent.requests,
        "post",
        lambda *args, **kwargs: calls.append((args, kwargs)) or Response(),
    )

    test_agent._respond_to_iat(invitation_id, invitation)

    conn = sqlite3.connect(test_agent.DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM invitations WHERE invitation_id=?",
        (invitation_id,),
    ).fetchone()
    conn.close()
    assert row["delivery_status"] == "responded"
    assert row["callback_attempts"] == 1
    assert calls[0][1]["allow_redirects"] is False
    assert calls[0][1]["json"]["response_type"] == "interested"


def test_admin_authentication_fails_closed(test_agent, monkeypatch):
    with pytest.raises(HTTPException) as missing:
        test_agent.require_test_agent_admin(None)
    assert missing.value.status_code == 401

    monkeypatch.delenv("IAT_TEST_AGENT_ADMIN_KEY")
    with pytest.raises(HTTPException) as unconfigured:
        test_agent.require_test_agent_admin("test-agent-admin")
    assert unconfigured.value.status_code == 401


def test_health_exposes_no_secret(test_agent):
    result = test_agent.health()

    assert result["status"] == "ok"
    assert result["response_mode"] == "interested"
    assert "admin_key" not in result
    assert "response_token" not in result
