from __future__ import annotations

from pathlib import Path

import curses

from termux_agent.permissions import GovernanceState, Policy
from termux_agent.session import SessionStore
from termux_agent.tools import ToolRuntime
from termux_agent.tui import TUIApp


class FakeScreen:
    def __init__(self, keys: list[object]):
        self.keys = iter(keys)

    def getmaxyx(self):
        return (24, 80)

    def get_wch(self):
        return next(self.keys)

    def erase(self):
        return None

    def move(self, *_args):
        return None

    def clrtoeol(self):
        return None

    def addstr(self, *_args):
        return None

    def attron(self, *_args):
        return None

    def attroff(self, *_args):
        return None

    def refresh(self):
        return None


def test_governance_snapshot_survives_new_runtime(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create("persistent governance")
    first = ToolRuntime(tmp_path, Policy(mode="build"), session_store=store, session_id=session_id)
    assert first.approve_execution() == GovernanceState.EXECUTING.value

    second = ToolRuntime(tmp_path, Policy(mode="build"), session_store=store, session_id=session_id)
    assert second.status()["state"] == GovernanceState.EXECUTING.value
    assert second.status()["consecutive_executions"] == 0


def test_last_sent_message_is_rendered_with_you_prefix_without_panels(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create("message display")
    app = TUIApp(tmp_path, tmp_path / "sessions.db", session_id)
    app.add_message("iraq")
    rendered = "\n".join(app.render_lines(width=100))
    assert "You > iraq" in rendered
    assert "agent iraq" not in rendered
    assert "TERMUX AGENT" not in rendered
    assert "Conversation" not in rendered
    assert "❯ Ask your question..." in rendered


def test_read_draft_accepts_text_and_enter(tmp_path: Path, monkeypatch) -> None:
    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create("interactive input")
    app = TUIApp(tmp_path, tmp_path / "sessions.db", session_id)
    monkeypatch.setattr(curses, "curs_set", lambda _value: None)
    monkeypatch.setattr(curses, "color_pair", lambda _value: 0)
    screen = FakeScreen(["i", "r", "a", "q", "\n"])
    assert app.read_draft(screen) == "iraq"
    assert app.input_active is False


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


class FakeChatClient:
    def __init__(self):
        self.calls = []

    def complete_messages(self, messages):
        from termux_agent.api import APIResponse

        self.calls.append(messages)
        return APIResponse("real assistant reply", "gpt-chat", 7, 5)


def test_tui_sends_history_and_persists_assistant_reply(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create("api chat")
    client = FakeChatClient()
    app = TUIApp(tmp_path, tmp_path / "sessions.db", session_id, client=client)

    app.add_message("hello agent")

    record = app.selected_record()
    assert [(item["role"], item["content"]) for item in record["messages"]] == [
        ("user", "hello agent"),
        ("assistant", "real assistant reply"),
    ]
    assert client.calls[-1][-1] == {"role": "user", "content": "hello agent"}
    assert app._metadata["used"] == 12
    assert "Agent > real assistant reply" in "\n".join(app.render_lines())


def test_tui_keeps_user_message_when_provider_fails(tmp_path: Path):
    class FailingClient:
        def complete_messages(self, _messages):
            from termux_agent.api import APIRequestError

            raise APIRequestError("provider returned HTTP 402: insufficient credits")

    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create("failed api chat")
    app = TUIApp(tmp_path, tmp_path / "sessions.db", session_id, client=FailingClient())
    app.add_message("please answer")

    record = app.selected_record()
    assert len(record["messages"]) == 1
    assert record["messages"][0]["role"] == "user"
    assert "402" in app.message
