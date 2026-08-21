"""Command-line interface for Termux Agent."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .permissions import PermissionError, Policy
from .session import SessionStore
from .tools import ToolRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="termux-agent")
    parser.add_argument("--root", default=".", help="workspace root")
    parser.add_argument("--db", default=None, help="SQLite database path")
    sub = parser.add_subparsers(dest="mode", required=True)

    for mode in ("plan", "build"):
        command = sub.add_parser(mode, help=f"run a {mode} operation")
        command.add_argument("--task", help="describe the task")
        command.add_argument("--command", dest="run_command", help="run a single allow-listed command")
        command.add_argument("--read", metavar="PATH", help="read one file")
        command.add_argument("--search", metavar="REGEX", help="search text")
        command.add_argument("--path", default=".", help="path for search")
        command.add_argument("--yes", action="store_true", help="confirm a build command")

    session = sub.add_parser("session", help="manage local sessions")
    session_sub = session.add_subparsers(dest="session_command", required=True)
    new = session_sub.add_parser("new")
    new.add_argument("--title", default="Untitled session")
    show = session_sub.add_parser("show")
    show.add_argument("session_id")
    session_sub.add_parser("list")
    return parser


def database_path(args: argparse.Namespace) -> Path:
    if args.db:
        return Path(args.db)
    return Path(os.getenv("TERMUX_AGENT_DB", Path.home() / ".termux-agent" / "sessions.db"))


def emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "session":
        store = SessionStore(database_path(args))
        if args.session_command == "new":
            session_id = store.create(args.title)
            emit({"session_id": session_id, "title": args.title})
        elif args.session_command == "show":
            record = store.get(args.session_id)
            if record is None:
                print(f"session not found: {args.session_id}", file=sys.stderr)
                return 1
            emit(record)
        else:
            emit(store.list())
        return 0

    policy = Policy.from_environment(mode=args.mode)
    runtime = ToolRuntime(Path(args.root), policy)
    try:
        if args.task:
            emit({"mode": args.mode, "task": args.task, "next": "inspect, plan, then execute"})
        if args.read:
            emit(runtime.read_file(args.read))
        if args.search:
            emit(runtime.search_text(args.search, args.path))
        if args.run_command:
            if args.mode == "build" and not args.yes:
                print("build command requires --yes after review", file=sys.stderr)
                return 2
            emit(runtime.run_command(args.run_command))
        return 0
    except (PermissionError, FileNotFoundError, ValueError, NotADirectoryError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
