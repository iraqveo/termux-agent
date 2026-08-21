"""Safe OpenAI-compatible API integration for real device tests."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class APIConfigurationError(ValueError):
    """Raised when the API integration is not configured safely."""


class APIRequestError(RuntimeError):
    """Raised for a provider request failure without exposing the API key."""


@dataclass(frozen=True)
class APIResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class OpenAICompatibleClient:
    """Small stdlib-only client for OpenAI-compatible chat-completions APIs."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = (api_key or os.getenv("TERMUX_AGENT_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
        self.base_url = (base_url or os.getenv("TERMUX_AGENT_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.model = model or os.getenv("TERMUX_AGENT_MODEL") or "gpt-4o-mini"
        self.timeout = timeout
        if not self.api_key:
            raise APIConfigurationError(
                "No API key configured. Set TERMUX_AGENT_API_KEY in Termux; the key is never stored in SQLite."
            )
        if not self.base_url.startswith(("https://", "http://")):
            raise APIConfigurationError("TERMUX_AGENT_BASE_URL must use http:// or https://")

    def complete(self, prompt: str, system: str | None = None) -> APIResponse:
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("prompt cannot be empty")
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = json.dumps({"model": self.model, "messages": messages, "temperature": 0.2}).encode("utf-8")
        request = Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "termux-agent/0.2",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500]
            raise APIRequestError(self._safe_error(f"provider returned HTTP {exc.code}: {body}")) from None
        except URLError as exc:
            raise APIRequestError(self._safe_error(f"network error: {exc.reason}")) from None
        except TimeoutError:
            raise APIRequestError("provider request timed out") from None

        try:
            data = json.loads(raw)
            text = str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise APIRequestError("provider returned an invalid chat-completion response") from exc
        usage = data.get("usage") or {}
        return APIResponse(
            text=text,
            model=str(data.get("model") or self.model),
            input_tokens=int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0),
            output_tokens=int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0),
        )

    def _safe_error(self, message: str) -> str:
        if self.api_key:
            return message.replace(self.api_key, "[redacted]")
        return message


def configured() -> bool:
    return bool((os.getenv("TERMUX_AGENT_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip())


__all__ = [
    "APIConfigurationError",
    "APIRequestError",
    "APIResponse",
    "OpenAICompatibleClient",
    "configured",
]


if __name__ == "__main__":
    client = OpenAICompatibleClient()
    response = client.complete("Reply with exactly: OK")
    print(response.text)
    print(f"model={response.model} tokens={response.total_tokens}")
