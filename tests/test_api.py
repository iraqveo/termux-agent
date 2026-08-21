from __future__ import annotations

import io
import json

import pytest

from termux_agent import api
from termux_agent.api import APIConfigurationError, APIRequestError, OpenAICompatibleClient


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def test_missing_api_key_is_rejected(monkeypatch):
    monkeypatch.delenv("TERMUX_AGENT_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(APIConfigurationError):
        OpenAICompatibleClient()


def test_client_sends_key_and_parses_usage(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode())
        return FakeResponse({
            "model": "gpt-test",
            "choices": [{"message": {"content": "TERMUX_AGENT_API_OK"}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 3},
        })

    monkeypatch.setattr(api, "urlopen", fake_urlopen)
    client = OpenAICompatibleClient(api_key="secret-key", model="gpt-test")
    response = client.complete("ping")
    assert response.text == "TERMUX_AGENT_API_OK"
    assert response.total_tokens == 7
    assert captured["headers"]["Authorization"] == "Bearer secret-key"
    assert captured["body"]["messages"][-1] == {"role": "user", "content": "ping"}


def test_provider_errors_redact_key(monkeypatch):
    def fake_urlopen(*_args, **_kwargs):
        raise api.HTTPError("https://example.test", 401, "bad", {}, io.BytesIO(b"secret-key"))

    monkeypatch.setattr(api, "urlopen", fake_urlopen)
    client = OpenAICompatibleClient(api_key="secret-key", base_url="https://example.test")
    with pytest.raises(APIRequestError) as error:
        client.complete("ping")
    assert "secret-key" not in str(error.value)
    assert "[redacted]" in str(error.value)


def test_client_sends_multi_turn_history(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode())
        return FakeResponse({
            "model": "gpt-chat",
            "choices": [{"message": {"content": "second answer"}}],
            "usage": {"prompt_tokens": 9, "completion_tokens": 4},
        })

    monkeypatch.setattr(api, "urlopen", fake_urlopen)
    client = OpenAICompatibleClient(api_key="secret-key", model="gpt-chat")
    response = client.complete_messages([
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second question"},
    ])
    assert response.text == "second answer"
    assert captured["body"]["messages"][-2:] == [
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second question"},
    ]


def test_client_rejects_conversation_without_user_turn(monkeypatch):
    monkeypatch.setattr(api, "urlopen", lambda *_args, **_kwargs: pytest.fail("request should not be sent"))
    client = OpenAICompatibleClient(api_key="secret-key")
    with pytest.raises(ValueError, match="last chat message"):
        client.complete_messages([{"role": "assistant", "content": "not a prompt"}])


def test_client_lists_provider_models(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return FakeResponse({"data": [{"id": "model-a"}, {"id": "model-b"}]})

    monkeypatch.setattr(api, "urlopen", fake_urlopen)
    client = OpenAICompatibleClient(api_key="secret-key", base_url="https://provider.example/v1")
    assert client.list_models() == ["model-a", "model-b"]
    assert captured["url"] == "https://provider.example/v1/models"
