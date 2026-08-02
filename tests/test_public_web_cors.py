from iat.api import agent_b_api


def test_public_web_cors_supports_wallet_session_contract():
    assert "GET" in agent_b_api.PUBLIC_WEB_ALLOW_METHODS
    assert "POST" in agent_b_api.PUBLIC_WEB_ALLOW_METHODS
    assert "DELETE" in agent_b_api.PUBLIC_WEB_ALLOW_METHODS
    assert "Authorization" in agent_b_api.PUBLIC_WEB_ALLOW_HEADERS
    assert "Content-Type" in agent_b_api.PUBLIC_WEB_ALLOW_HEADERS
