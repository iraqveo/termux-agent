from __future__ import annotations

import json
from pathlib import Path

import pytest

from termux_agent.mcp_server import handle
from termux_agent.permissions import PermissionError, Policy, safe_path
from termux_agent.session import SessionStore
from termux_agent.tools import ToolRuntime


def test_plan_mode_blocks_write_and_execution(tmp_path: Path) -> None:
    runtime = ToolRuntime(tmp_path, Policy(mode="plan"))
    with pytest.raises(PermissionError):
        runtime.write_file("note.txt", "hello")
    with pytest.raises(PermissionError):
        runtime.run_command("python -c 'print(1)'")


def test_build_mode_allows_safe_write_and_allowlisted_command(tmp_path: Path) -> None:
    runtime = ToolRuntime(tmp_path, Policy(mode="build"))
    assert runtime.write_file("src/note.txt", "hello")['bytes'] == 5
    result = runtime.run_command("python -c 'print(1)'")
    assert result["returncode"] == 0
    assert result["stdout"].strip() == "1"


def test_path_traversal_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(PermissionError):
        safe_path(tmp_path, "../outside.txt")


def test_search_is_bounded_and_ignores_git(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("TODO: fix\npass\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "hidden.txt").write_text("TODO: hidden\n", encoding="utf-8")
    matches = ToolRuntime(tmp_path, Policy()).search_text("TODO")
    assert matches == [{"path": "src/app.py", "line": 1, "text": "TODO: fix"}]


def test_session_round_trip(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create("Test")
    store.add_message(session_id, "user", "hello")
    store.add_message(session_id, "assistant", "world")
    record = store.get(session_id)
    assert record is not None
    assert [item["content"] for item in record["messages"]] == ["hello", "world"]


def test_mcp_tool_list_and_call(tmp_path: Path) -> None:
    runtime = ToolRuntime(tmp_path, Policy(mode="plan"))
    listed = handle(runtime, {"id": 1, "method": "tools/list", "params": {}})
    assert listed and any(tool["name"] == "search_text" for tool in listed["result"]["tools"])
    (tmp_path / "readme.txt").write_text("MCP works", encoding="utf-8")
    called = handle(runtime, {"id": 2, "method": "tools/call", "params": {"name": "read_file", "arguments": {"path": "readme.txt"}}})
    assert called and called["result"]["structuredContent"]["content"] == "MCP works"
    encoded = json.dumps(called, ensure_ascii=False)
    assert "MCP works" in encoded
