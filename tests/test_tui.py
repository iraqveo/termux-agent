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
    app = TUIApp(tmp_path, tmp_path / "sessions.db", session_id)
    rendered = "\n".join(app.render_lines(width=100))
    assert "Conversation" in rendered
    assert "❯ Ask your question..." in rendered
    assert "↑ Send" in rendered
    assert "Hello" in rendered
    assert "governance" not in rendered.lower()
    assert "evidence" not in rendered.lower()
