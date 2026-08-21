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


def test_tui_renders_session_state_and_audit_sections(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create("visual session")
    runtime = ToolRuntime(tmp_path, Policy(mode="build"), session_store=store, session_id=session_id)
    runtime.approve_execution()
    store.record_usage(session_id, "gpt-test", "termux-agent", input_tokens=12, output_tokens=8)
    app = TUIApp(tmp_path, tmp_path / "sessions.db", session_id)
    rendered = "\n".join(app.render_lines(width=100))
    assert "❯ Ask your question..." in rendered
    assert "Conversation" not in rendered
    assert "TERMUX AGENT" not in rendered
    assert "Hello" not in rendered
    assert "governance" not in rendered.lower()
    assert "evidence" not in rendered.lower()
    assert "Model: gpt-test" in rendered
    assert "Repo: termux-agent" in rendered
    assert "Draft: 0 tokens" in rendered
    assert "Used: 20" in rendered
