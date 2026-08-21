"""Optional, model-aware token counting for the live TUI draft counter."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

try:
    import tiktoken  # type: ignore
except ImportError:  # pragma: no cover - exercised on minimal Termux installs
    tiktoken = None


@lru_cache(maxsize=8)
def encoding_for_model(model: str) -> Any | None:
    """Return a cached tiktoken encoding, or None when the extra is unavailable."""
    if tiktoken is None:
        return None
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        try:
            return tiktoken.get_encoding("o200k_base")
        except Exception:
            return None


def count_tokens(text: str, model: str = "gpt-4o-mini") -> int | None:
    """Count tokens for text using the selected model's encoding.

    None means tiktoken is not installed or no usable encoding is available;
    callers should display an explicit unavailable marker rather than inventing
    an exact-looking number.
    """
    encoding = encoding_for_model(model)
    if encoding is None:
        return None
    try:
        return len(encoding.encode(text, disallowed_special=()))
    except Exception:
        return None
