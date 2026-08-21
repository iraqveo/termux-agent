"""Command-line interface for Termux Agent and its governance lifecycle."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .permissions import EvidenceKind, GovernanceError, PermissionError, Policy
from .session import SessionStore
from .tools import ToolRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="termux-agent")
    parser.add_argument("--root", default=".", help="workspace root")
    parser.add_argument("--db", default=None, help="SQLite database path")
    parser.add_argument("--session-id", default=None, help="existing session id")
    sub = parser.add_subparsers(dest="mode", required=True)

    for mode in ("plan", "build"):
        command = sub.add_parser(mode, help=f"run a {mode} operation")
        command.add_argument("--task", help="describe the task")
        command.add_argument("--command", dest="run_command", help="run one exact allow-listed command")
        command.add_argument("--read", metavar="PATH", help="read one file")
        command.add_argument("--search", metavar="REGEX", help="search text")
        command.add_argument("--path", default=".", help="path for search")
        command.add_argument("--yes", action="store_true", help="confirm a build operation after review")

    governance = sub.add_parser("governance", help="inspect or change governance state")
    governance_sub = governance.add_subparsers(dest="governance_command", required=True)
    governance_sub.add_parser("status")
    governance_sub.add_parser("approve")
    halt = governance_sub.add_parser("halt")
    halt.add_argument("--reason", required=True)
    evidence = governance_sub.add_parser("evidence")
    evidence.add_argument("--kind", choices=("OBSERVED", "INFERRED", "UNKNOWN"), required=True)
    evidence.add_argument("--source", required=True)
    evidence.add_argument("--content", required=True)

    sub.add_parser("tui", help="open the local interactive terminal interface")

    api = sub.add_parser("api", help="test an external OpenAI-compatible API")
    api_sub = api.add_subparsers(dest="api_command", required=True)
    api_test = api_sub.add_parser("test", help="send one real request using the environment API key")
    api_test.add_argument("--prompt", default="Reply with exactly: TERMUX_AGENT_API_OK")

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


def get_store_and_session(args: argparse.Namespace) -> tuple[SessionStore, str]:
    store = SessionStore(database_path(args))
    session_id = args.session_id
    if session_id is None:
        session_id = store.create("Termux Agent session")
    elif store.get(session_id) is None:
        raise ValueError(f"session not found: {session_id}")
    return store, session_id


def get_runtime(args: argparse.Namespace, mode: str = "plan") -> tuple[ToolRuntime, SessionStore, str]:
    store, session_id = get_store_and_session(args)
    runtime = ToolRuntime(Path(args.root), Policy.from_environment(mode=mode), session_store=store, session_id=session_id)
    return runtime, store, session_id


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.mode == "tui":
            from .tui import run_tui

            run_tui(Path(args.root), database_path(args), args.session_id)
            return 0

        if args.mode == "api":
            from .api import OpenAICompatibleClient

            client = OpenAICompatibleClient()
            store, session_id = get_store_and_session(args)
            response = client.complete(args.prompt)
            repository = os.getenv("TERMUX_AGENT_REPOSITORY", Path(args.root).expanduser().resolve().name)
            store.add_message(session_id, "user", args.prompt)
            store.add_message(session_id, "assistant", response.text)
            store.record_usage(
                session_id,
                response.model,
                repository,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
            )
            emit({
                "session_id": session_id,
                "ok": True,
                "model": response.model,
                "text": response.text,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "total_tokens": response.total_tokens,
            })
            return 0

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

        if args.mode == "governance":
            runtime, store, session_id = get_runtime(args)
            if args.governance_command == "status":
                emit({"session_id": session_id, **runtime.status()})
            elif args.governance_command == "approve":
                emit({"session_id": session_id, "state": runtime.approve_execution()})
            elif args.governance_command == "halt":
                emit({"session_id": session_id, "state": runtime.halt(args.reason)})
            else:
                evidence_id = store.add_evidence(session_id, args.kind, args.source, args.content)
                emit({"session_id": session_id, "evidence_id": evidence_id, "kind": args.kind})
            return 0

        runtime, _store, session_id = get_runtime(args, mode=args.mode)
        if args.task:
            runtime._evidence(EvidenceKind.UNKNOWN, "cli.task", args.task)
        if args.read:
            emit(runtime.read_file(args.read))
        if args.search:
            emit(runtime.search_text(args.search, args.path))
        if args.run_command:
            if args.mode != "build" or not args.yes:
                print("command execution requires build mode and --yes", file=sys.stderr)
                return 2
            runtime.approve_execution("explicit --yes approval")
            emit(runtime.run_command(args.run_command))
        emit({"session_id": session_id, **runtime.status()})
        return 0
    except (PermissionError, GovernanceError, FileNotFoundError, ValueError, NotADirectoryError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
