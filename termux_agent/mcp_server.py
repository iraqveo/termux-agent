"""Minimal MCP-style stdio server with bounded, local-only tools."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .permissions import PermissionError, Policy
from .tools import ToolRuntime

TOOLS = [
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file inside the workspace.",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    {
        "name": "search_text",
        "description": "Search a regular expression in workspace text files.",
        "inputSchema": {
            "type": "object",
            "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}},
            "required": ["pattern"],
        },
    },
    {
        "name": "write_file",
        "description": "Write a text file; available only in build mode.",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
    },
    {
        "name": "run_command",
        "description": "Run one allow-listed command; available only in build mode.",
        "inputSchema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
    },
    {
        "name": "notify",
        "description": "Send a Termux notification when Termux:API is available.",
        "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}, "content": {"type": "string"}}, "required": ["title", "content"]},
    },
]


def response(request_id: Any, result: Any = None, error: str | None = None) -> dict:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error is None:
        payload["result"] = result
    else:
        payload["error"] = {"code": -32000, "message": error}
    return payload


def handle(runtime: ToolRuntime, request: dict) -> dict | None:
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}
    if method == "initialize":
        return response(request_id, {"protocolVersion": "2024-11-05", "serverInfo": {"name": "termux-agent", "version": "0.1.0"}, "capabilities": {"tools": {}}})
    if method in {"notifications/initialized", "notifications/cancelled"}:
        return None
    if method == "tools/list":
        return response(request_id, {"tools": TOOLS})
    if method != "tools/call":
        return response(request_id, error=f"unsupported method: {method}")

    name = params.get("name")
    arguments = params.get("arguments") or {}
    try:
        if name == "read_file":
            result = runtime.read_file(str(arguments["path"]))
        elif name == "search_text":
            result = runtime.search_text(str(arguments["pattern"]), str(arguments.get("path", ".")))
        elif name == "write_file":
            result = runtime.write_file(str(arguments["path"]), str(arguments["content"]))
        elif name == "run_command":
            result = runtime.run_command(str(arguments["command"]))
        elif name == "notify":
            result = runtime.notify(str(arguments["title"]), str(arguments["content"]))
        else:
            return response(request_id, error=f"unknown tool: {name}")
        return response(request_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}], "structuredContent": result})
    except (KeyError, PermissionError, FileNotFoundError, ValueError, NotADirectoryError) as exc:
        return response(request_id, error=str(exc))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="termux-agent-mcp")
    parser.add_argument("--root", default=".")
    parser.add_argument("--mode", choices=("plan", "build"), default="plan")
    args = parser.parse_args(argv)
    runtime = ToolRuntime(Path(args.root), Policy.from_environment(args.mode))
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            result = handle(runtime, request)
        except json.JSONDecodeError as exc:
            result = response(None, error=f"invalid JSON: {exc.msg}")
        if result is not None:
            sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
