import pytest
from fastapi import HTTPException

from iat.api.agent_b_api import require_admin


def test_admin_authentication_fails_closed(monkeypatch):
    monkeypatch.delenv("IAT_ADMIN_API_KEY", raising=False)

    with pytest.raises(HTTPException) as error:
        require_admin(None)

    assert error.value.status_code == 401


def test_admin_authentication_accepts_matching_key(monkeypatch):
    monkeypatch.setenv("IAT_ADMIN_API_KEY", "test-admin-key")

    assert require_admin("test-admin-key") is True
