from __future__ import annotations

import json
from pathlib import Path

import pytest

from termux_agent.mcp_server import handle
from termux_agent.permissions import (
    EvidenceKind,
    GovernanceError,
    GovernanceState,
    PermissionError,
    Policy,
    safe_path,
)
from termux_agent.session import SessionStore
from termux_agent.tools import ToolRuntime


def approved_runtime(tmp_path: Path, **kwargs) -> ToolRuntime:
    runtime = ToolRuntime(tmp_path, Policy(mode="build", **kwargs))
    assert runtime.approve_execution() == GovernanceState.EXECUTING.value
    return runtime


def test_plan_mode_blocks_write_and_execution(tmp_path: Path) -> None:
    runtime = ToolRuntime(tmp_path, Policy(mode="plan"))
    with pytest.raises(PermissionError):
        runtime.write_file("note.txt", "hello")
    with pytest.raises(PermissionError):
        runtime.run_command("pytest")


def test_exact_argv_rejects_substrings_and_shell_chaining(tmp_path: Path) -> None:
    runtime = approved_runtime(tmp_path)
    with pytest.raises(PermissionError, match="exactly match"):
        runtime.run_command("pytest --maxfail=1")
    with pytest.raises(PermissionError, match="operators"):
        runtime.run_command("pytest && git push origin main")


def test_denylist_is_second_line_of_defense(tmp_path: Path) -> None:
    runtime = ToolRuntime(
        tmp_path,
        Policy(mode="build", allowed_commands=(("sh", "-c", "echo unsafe"), ("git", "push", "origin", "main"))),
    )
    runtime.approve_execution()
    with pytest.raises(PermissionError, match="shell-wrapper"):
        runtime.run_command("sh -c 'echo unsafe'")
    with pytest.raises(PermissionError, match="denylist"):
        runtime.run_command("git push origin main")


def test_build_mode_requires_explicit_governance_approval(tmp_path: Path) -> None:
    runtime = ToolRuntime(tmp_path, Policy(mode="build"))
    with pytest.raises(GovernanceError, match="EXECUTING"):
        runtime.run_command("pytest")
    assert runtime.approve_execution() == GovernanceState.EXECUTING.value
    result = runtime.run_command("python -m pytest")
    assert result["returncode"] == 5  # pytest has no tests in the temporary workspace


def test_three_successful_steps_force_halt(tmp_path: Path) -> None:
    runtime = ToolRuntime(
        tmp_path,
        Policy(mode="build", allowed_commands=(("python", "-c", "print(1)"),)),
    )
    runtime.approve_execution()
    assert runtime.write_file("one.txt", "1")["bytes"] == 1
    assert runtime.run_command('python -c "print(1)"')["returncode"] == 0
    assert runtime.run_command('python -c "print(1)"')["returncode"] == 0
    assert runtime.status()["state"] == GovernanceState.HALTED.value
    with pytest.raises(GovernanceError, match="HALTED"):
        runtime.run_command('python -c "print(1)"')


def test_repeated_failure_forces_halt(tmp_path: Path) -> None:
    runtime = ToolRuntime(tmp_path, Policy(mode="build", allowed_commands=(("python", "-m", "pytest"),)))
    runtime.approve_execution()
    first = runtime.run_command("python -m pytest")
    assert first["returncode"] != 0
    assert runtime.status()["state"] == GovernanceState.ANALYZING.value
    runtime.approve_execution("re-review after failure")
    runtime.run_command("python -m pytest")
    assert runtime.status()["state"] == GovernanceState.HALTED.value


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


def test_session_round_trip_includes_audit_and_evidence(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create("Test")
    store.add_message(session_id, "user", "hello")
    store.add_evidence(session_id, "OBSERVED", "test", "observed output")
    store.add_governance_event(session_id, {"event": "halt", "reason": "test", "evidence_kind": "OBSERVED"})
    record = store.get(session_id)
    assert record is not None
    assert [item["content"] for item in record["messages"]] == ["hello"]
    assert record["evidence"][0]["kind"] == EvidenceKind.OBSERVED.value
    assert record["governance_events"][0]["event"] == "halt"


def test_mcp_requires_approval_for_execution_and_exposes_status(tmp_path: Path) -> None:
    runtime = ToolRuntime(tmp_path, Policy(mode="build"))
    listed = handle(runtime, {"id": 1, "method": "tools/list", "params": {}})
    assert listed and any(tool["name"] == "approve_execution" for tool in listed["result"]["tools"])
    blocked = handle(runtime, {"id": 2, "method": "tools/call", "params": {"name": "run_command", "arguments": {"command": "pytest"}}})
    assert blocked and "error" in blocked
    approved = handle(runtime, {"id": 3, "method": "tools/call", "params": {"name": "approve_execution", "arguments": {}}})
    assert approved and approved["result"]["structuredContent"]["state"] == "EXECUTING"
    status = handle(runtime, {"id": 4, "method": "tools/call", "params": {"name": "status", "arguments": {}}})
    assert status and status["result"]["structuredContent"]["state"] == "EXECUTING"
    encoded = json.dumps(status, ensure_ascii=False)
    assert "consecutive_executions" in encoded
