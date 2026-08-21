#!/usr/bin/env python3
"""Run a non-destructive integration test on a real Termux device."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def check(condition: bool, message: str, details: str = "") -> dict[str, str]:
    status = "PASS" if condition else "FAIL"
    result = {"status": status, "check": message}
    if details:
        result["details"] = details
    print(f"[{status}] {message}{': ' + details if details else ''}")
    if not condition:
        raise RuntimeError(message)
    return result


def optional_check(message: str, available: bool, details: str) -> dict[str, str]:
    status = "PASS" if available else "WARN"
    print(f"[{status}] {message}: {details}")
    return {"status": status, "check": message, "details": details}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from termux_agent.mcp_server import handle
    from termux_agent.permissions import GovernanceError, GovernanceState, Policy
    from termux_agent.session import SessionStore
    from termux_agent.tools import ToolRuntime

    results: list[dict[str, str]] = []
    print("Termux Agent device smoke test")
    print(f"Root: {root}")
    results.append(optional_check("Running inside Termux", bool(os.environ.get("PREFIX")), os.environ.get("PREFIX", "not detected; simulation mode")))
    results.append(check((root / "pyproject.toml").is_file(), "Repository root is valid"))
    results.append(check(shutil.which("python") is not None, "Python is available", sys.executable))
    results.append(check(shutil.which("git") is not None, "Git is available", shutil.which("git") or "missing"))
    results.append(optional_check("ripgrep is available", shutil.which("rg") is not None, shutil.which("rg") or "not installed; Python search remains available"))
    results.append(optional_check("proot-distro is available", shutil.which("proot-distro") is not None, shutil.which("proot-distro") or "not installed; optional build sandbox"))
    results.append(optional_check("Termux:API notification command is available", shutil.which("termux-notification") is not None, shutil.which("termux-notification") or "not installed; notifications disabled"))
    storage = Path.home() / "storage" / "shared"
    results.append(optional_check("Shared storage is exposed", storage.is_dir(), str(storage)))

    with tempfile.TemporaryDirectory(prefix="termux-agent-device-") as temporary:
        workspace = Path(temporary)
        database = workspace / "sessions.db"
        store = SessionStore(database)
        session_id = store.create("real-device-smoke-test")
        policy = Policy(mode="build", allowed_commands=(("python", "-c", "print('device_ok')"),))
        runtime = ToolRuntime(workspace, policy, session_store=store, session_id=session_id)

        try:
            runtime.run_command("python -c \"print('device_ok')\"")
            raise AssertionError("execution unexpectedly passed before approval")
        except GovernanceError:
            results.append(check(True, "Execution is blocked before explicit approval"))

        results.append(check(runtime.approve_execution() == GovernanceState.EXECUTING.value, "Approval enters EXECUTING state"))
        output = runtime.run_command("python -c \"print('device_ok')\"")
        results.append(check(output["returncode"] == 0 and "device_ok" in output["stdout"], "Exact argv command executes", output["stdout"].strip()))
        results.append(check(runtime.write_file("device-proof.txt", "written-by-approved-agent\n")["bytes"] > 0, "Approved file write executes"))
        runtime.run_command("python -c \"print('device_ok')\"")
        results.append(check(runtime.status()["state"] == GovernanceState.HALTED.value, "Three-step execution budget forces HALT"))

        record = store.get(session_id)
        results.append(check(record is not None, "SQLite session is readable"))
        results.append(check(len(record["governance_events"]) >= 4, "Governance audit events are persisted"))
        results.append(check(len(record["evidence"]) >= 3, "Typed evidence records are persisted"))

        mcp_runtime = ToolRuntime(workspace, Policy(mode="build"))
        blocked = handle(mcp_runtime, {"id": 1, "method": "tools/call", "params": {"name": "run_command", "arguments": {"command": "pytest"}}})
        results.append(check(blocked is not None and "error" in blocked, "MCP blocks execution before approval"))
        approved = handle(mcp_runtime, {"id": 2, "method": "tools/call", "params": {"name": "approve_execution", "arguments": {}}})
        results.append(check(approved is not None and approved["result"]["structuredContent"]["state"] == "EXECUTING", "MCP approval gate works"))

    if os.environ.get("TERMUX_AGENT_SEND_NOTIFICATION") == "1" and shutil.which("termux-notification"):
        subprocess.run(["termux-notification", "--title", "Termux Agent", "--content", "Device smoke test passed"], check=False)
        print("[PASS] Test notification sent")
    else:
        print("[INFO] Notification not sent; set TERMUX_AGENT_SEND_NOTIFICATION=1 to enable it")

    summary = {"passed_or_warned": len(results), "root": str(root), "termux": bool(os.environ.get("PREFIX"))}
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, RuntimeError, KeyError, OSError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
