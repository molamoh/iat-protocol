import json

from iat.api import buyer_intent
from iat.api.groq_config import (
    DEFAULT_GROQ_MODEL,
    effective_groq_model,
    groq_json_request,
    groq_model_status,
)


class _GroqResponse:
    status_code = 200
    text = ""

    def __init__(self, content):
        self._content = content

    def json(self):
        return {"choices": [{"message": {"content": json.dumps(self._content)}}]}


def test_groq_uses_gpt_oss_20b_by_default(monkeypatch):
    monkeypatch.delenv("GROQ_MODEL", raising=False)

    assert effective_groq_model() == DEFAULT_GROQ_MODEL
    payload = groq_json_request([], temperature=0.1)
    assert payload["model"] == "openai/gpt-oss-20b"
    assert payload["reasoning_effort"] == "low"
    assert payload["reasoning_format"] == "hidden"


def test_deprecated_render_override_is_automatically_migrated(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "llama-3.1-8b-instant")

    status = groq_model_status()
    assert status["configured_model"] == "llama-3.1-8b-instant"
    assert status["effective_model"] == "openai/gpt-oss-20b"
    assert status["automatically_migrated"] is True


def test_supported_custom_model_remains_configurable(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "custom/provider-model")

    payload = groq_json_request([], temperature=0.2)
    assert payload["model"] == "custom/provider-model"
    assert "reasoning_effort" not in payload
    assert "reasoning_format" not in payload


def test_invalid_gpt_oss_reasoning_effort_fails_safe(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-20b")
    monkeypatch.setenv("GROQ_REASONING_EFFORT", "unsupported")

    assert groq_json_request([], temperature=0.1)["reasoning_effort"] == "low"


def test_buyer_intent_sends_migrated_model_to_groq(monkeypatch):
    captured = {}
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_MODEL", "llama-3.1-8b-instant")

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return _GroqResponse(
            {
                "provider": "groq",
                "purchase_type": "research",
                "goal": "compare products",
                "requirements": {},
            }
        )

    monkeypatch.setattr(buyer_intent.requests, "post", fake_post)

    result = buyer_intent.normalize_buyer_intent("compare products")

    assert result["provider"] == "groq"
    assert captured["url"].endswith("/chat/completions")
    assert captured["json"]["model"] == "openai/gpt-oss-20b"
    assert captured["json"]["reasoning_format"] == "hidden"
