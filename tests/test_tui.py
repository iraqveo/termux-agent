from __future__ import annotations

from pathlib import Path

from termux_agent.permissions import GovernanceState, Policy
from termux_agent.session import SessionStore
from termux_agent.tools import ToolRuntime
from termux_agent.tui import TUIApp


def test_governance_snapshot_survives_new_runtime(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create("persistent governance")
    first = ToolRuntime(tmp_path, Policy(mode="build"), session_store=store, session_id=session_id)
    assert first.approve_execution() == GovernanceState.EXECUTING.value

    second = ToolRuntime(tmp_path, Policy(mode="build"), session_store=store, session_id=session_id)
    assert second.status()["state"] == GovernanceState.EXECUTING.value
    assert second.status()["consecutive_executions"] == 0


def test_last_sent_message_is_rendered_without_panels(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create("message display")
    app = TUIApp(tmp_path, tmp_path / "sessions.db", session_id)
    app.add_message("hello from Termux")
    rendered = "\n".join(app.render_lines(width=100))
    assert "agent hello from Termux" in rendered
    assert "TERMUX AGENT" not in rendered
    assert "Conversation" not in rendered
    assert "❯ Ask your question..." in rendered


def test_tui_metadata_is_cached_during_typing(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create("latency")
    store.record_usage(session_id, "gpt-test", "termux-agent", input_tokens=1, output_tokens=2)
    app = TUIApp(tmp_path, tmp_path / "sessions.db", session_id)
    app.store.get_usage = lambda _session_id: (_ for _ in ()).throw(AssertionError("SQLite read during typing"))
    assert "Used: 3" in app._metadata_line(200)
    assert "Used: 3" in app._metadata_line(200)


def test_input_caret_is_visible_without_token_counting(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create("caret")
    app = TUIApp(tmp_path, tmp_path / "sessions.db", session_id)
    app.draft = "hello"
    app.input_active = True
    rendered = "\n".join(app.render_lines(width=100))
    assert "hello▌" in rendered
    assert "Draft:" not in rendered


def test_tui_metadata_shows_model_repo_and_used_tokens(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create("visual session")
    store.record_usage(session_id, "gpt-test", "termux-agent", input_tokens=12, output_tokens=8)
    app = TUIApp(tmp_path, tmp_path / "sessions.db", session_id)
    rendered = "\n".join(app.render_lines(width=100))
    assert "❯ Ask your question..." in rendered
    assert "Conversation" not in rendered
    assert "TERMUX AGENT" not in rendered
    assert "Model: gpt-test" in rendered
    assert "Repo: termux-agent" in rendered
    assert "Draft:" not in rendered
    assert "Used: 20" in rendered
