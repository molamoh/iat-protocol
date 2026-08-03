from iat.api import agent_b_api


def test_root_exposes_build_version(monkeypatch):
    monkeypatch.setenv("IAT_BUILD_VERSION", "commit-123")

    assert agent_b_api.root() == {
        "status": "ok",
        "message": "IAT Protocol API is running",
        "build_version": "commit-123",
    }


def test_health_is_cheap_and_identifies_image(monkeypatch):
    monkeypatch.setenv("IAT_BUILD_VERSION", "commit-456")

    assert agent_b_api.health() == {
        "status": "ok",
        "service": "iat-protocol",
        "build_version": "commit-456",
    }
