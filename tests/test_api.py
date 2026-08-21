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
