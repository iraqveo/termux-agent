from __future__ import annotations

from termux_agent.tokenizer import count_tokens, encoding_for_model


def test_tokenizer_is_cached_and_graceful() -> None:
    first = encoding_for_model("gpt-4o-mini")
    second = encoding_for_model("gpt-4o-mini")
    assert first is second
    result = count_tokens("hello world", "gpt-4o-mini")
    assert result is None or result == 2


def test_tui_metadata_contains_draft_and_used_counts(tmp_path) -> None:
    from termux_agent.session import SessionStore
    from termux_agent.tui import TUIApp

    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create("token view")
    store.record_usage(session_id, "gpt-4o-mini", "termux-agent", input_tokens=4, output_tokens=6)
    app = TUIApp(tmp_path, tmp_path / "sessions.db", session_id)
    app.draft_tokens = 3
    metadata = app._metadata_line(200)
    assert "Model: gpt-4o-mini" in metadata
    assert "Repo: termux-agent" in metadata
    assert "Draft: 3 tokens" in metadata
    assert "Used: 10" in metadata
