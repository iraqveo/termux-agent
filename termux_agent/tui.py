"""Small local TUI for Termux Agent using Python's standard curses module."""

from __future__ import annotations

import argparse
import curses
import os
import textwrap
from pathlib import Path
from typing import Any

from .permissions import GovernanceError, Policy
from .session import SessionStore
from .tools import ToolRuntime


STATE_COLORS = {
    "ANALYZING": 1,
    "PREVIEWING": 2,
    "SELF_REVIEW": 3,
    "EXECUTING": 4,
    "HALTED": 5,
}


class TUIApp:
    def __init__(self, root: Path, database: Path, session_id: str | None = None):
        self.root = root.expanduser().resolve()
        self.store = SessionStore(database.expanduser())
        self.session_id = session_id
        self.sessions: list[dict[str, Any]] = []
        self.selected = 0
        self.message = "Press ? for help"
        self.show_help = False
        self.refresh_sessions()
        if self.session_id:
            for index, session in enumerate(self.sessions):
                if session["id"] == self.session_id:
                    self.selected = index
                    break
        elif self.sessions:
            self.session_id = self.sessions[0]["id"]
        else:
            self.session_id = self.store.create("TUI session")
            self.refresh_sessions()

    def refresh_sessions(self) -> None:
        self.sessions = self.store.list(limit=100)
        if self.sessions:
            self.selected = min(self.selected, len(self.sessions) - 1)
            if self.session_id not in {item["id"] for item in self.sessions}:
                self.session_id = self.sessions[self.selected]["id"]

    def selected_record(self) -> dict[str, Any] | None:
        return self.store.get(self.session_id) if self.session_id else None

    def selected_state(self, record: dict[str, Any] | None) -> str:
        return str((record or {}).get("governance", {}).get("state", "ANALYZING"))

    def render_lines(self, width: int = 100) -> list[str]:
        record = self.selected_record()
        state = self.selected_state(record)
        governance = (record or {}).get("governance") or {}
        events = (record or {}).get("governance_events") or []
        evidence = (record or {}).get("evidence") or []
        session = (record or {}).get("session") or {}
        lines = [
            "TERMUX AGENT | local governance console",
            f"Session: {session.get('title', 'none')}  [{str(self.session_id or '')[:12]}]",
            f"State: {state}    Steps: {governance.get('consecutive_executions', 0)}/3    Root: {self.root}",
            "",
            "Lifecycle: ANALYZING -> PREVIEWING -> SELF_REVIEW -> EXECUTING -> HALTED",
            "",
            "Recent audit events:",
        ]
        if events:
            for event in events[-6:]:
                transition = f"{event.get('from_state', '?')} -> {event.get('to_state', '?')}"
                lines.append(f"  {event.get('event', '?')}: {transition} | {event.get('reason', '')[:width - 42]}")
        else:
            lines.append("  No audit events yet.")
        lines.append("")
        lines.append("Recent evidence:")
        if evidence:
            for item in evidence[-5:]:
                lines.append(f"  [{item.get('kind', 'UNKNOWN')}] {item.get('source', '?')}: {item.get('content', '')[:width - 30]}")
        else:
            lines.append("  No evidence yet.")
        lines.append("")
        lines.append(f"Message: {self.message}")
        return lines

    def prompt(self, screen: Any, label: str) -> str:
        height, width = screen.getmaxyx()
        screen.addstr(height - 2, 0, (label + " ")[: width - 1])
        screen.refresh()
        curses.echo()
        try:
            value = screen.getstr(height - 1, 0, max(1, width - 1)).decode("utf-8", errors="replace")
        finally:
            curses.noecho()
        return value.strip()

    def approve(self) -> None:
        if not self.session_id:
            return
        runtime = ToolRuntime(self.root, Policy(mode="build"), session_store=self.store, session_id=self.session_id)
        try:
            runtime.approve_execution("approved from TUI")
            self.message = "Approved: PREVIEWING -> SELF_REVIEW -> EXECUTING"
        except GovernanceError as exc:
            self.message = f"Approval blocked: {exc}"

    def halt(self) -> None:
        if not self.session_id:
            return
        runtime = ToolRuntime(self.root, Policy(mode="plan"), session_store=self.store, session_id=self.session_id)
        reason = self.message if self.message != "Press ? for help" else "manual halt from TUI"
        try:
            runtime.halt(reason)
            self.message = "Session halted"
        except GovernanceError as exc:
            self.message = f"Halt blocked: {exc}"

    def new_session(self, screen: Any) -> None:
        title = self.prompt(screen, "New session title:") or "TUI session"
        self.session_id = self.store.create(title)
        self.refresh_sessions()
        self.selected = next((i for i, item in enumerate(self.sessions) if item["id"] == self.session_id), 0)
        self.message = f"Created session: {title}"

    def draw(self, screen: Any) -> None:
        screen.erase()
        height, width = screen.getmaxyx()
        if height < 12 or width < 60:
            screen.addstr(0, 0, "Terminal too small; resize to at least 60x12. Press q to quit.")
            screen.refresh()
            return
        screen.attron(curses.color_pair(1))
        screen.addstr(0, 0, " TERMUX AGENT ".center(width)[:width - 1])
        screen.attroff(curses.color_pair(1))
        left_width = max(24, min(34, width // 3))
        screen.vline(1, left_width, curses.ACS_VLINE, height - 3)
        screen.addstr(1, 1, "SESSIONS"[: left_width - 2], curses.A_BOLD)
        for index, session in enumerate(self.sessions[: height - 5]):
            marker = ">" if index == self.selected else " "
            title = str(session.get("title", ""))[: left_width - 8]
            line = f"{marker} {index + 1:02d} {title}"
            attr = curses.A_REVERSE if index == self.selected else curses.A_NORMAL
            screen.addstr(2 + index, 1, line.ljust(left_width - 2)[: left_width - 2], attr)
        screen.addstr(height - 2, 1, "n new  a approve  h halt  r refresh"[: left_width - 2])
        screen.addstr(height - 1, 1, "j/k select  e evidence  ? help  q quit"[: left_width - 2])

        record = self.selected_record()
        state = self.selected_state(record)
        screen.attron(curses.color_pair(STATE_COLORS.get(state, 1)) | curses.A_BOLD)
        screen.addstr(1, left_width + 2, f" {state} ")
        screen.attroff(curses.color_pair(STATE_COLORS.get(state, 1)) | curses.A_BOLD)
        available = width - left_width - 4
        lines = self.render_lines(available)
        for row, line in enumerate(lines[: height - 3], start=2):
            clipped = line.replace("\n", " ")[:available]
            screen.addstr(row, left_width + 2, clipped)
        screen.refresh()

    def run(self, screen: Any) -> None:
        curses.curs_set(0)
        screen.keypad(True)
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_YELLOW, -1)
        curses.init_pair(3, curses.COLOR_MAGENTA, -1)
        curses.init_pair(4, curses.COLOR_GREEN, -1)
        curses.init_pair(5, curses.COLOR_RED, -1)
        while True:
            self.draw(screen)
            key = screen.getch()
            if key in (ord("q"), 27):
                return
            if key in (curses.KEY_DOWN, ord("j")) and self.sessions:
                self.selected = min(self.selected + 1, len(self.sessions) - 1)
                self.session_id = self.sessions[self.selected]["id"]
            elif key in (curses.KEY_UP, ord("k")) and self.sessions:
                self.selected = max(self.selected - 1, 0)
                self.session_id = self.sessions[self.selected]["id"]
            elif key == ord("n"):
                self.new_session(screen)
            elif key == ord("a"):
                self.approve()
            elif key == ord("h"):
                self.halt()
            elif key == ord("r"):
                self.refresh_sessions()
                self.message = "Refreshed"
            elif key == ord("e"):
                record = self.selected_record() or {}
                self.message = f"Evidence records: {len(record.get('evidence', []))}; audit events: {len(record.get('governance_events', []))}"
            elif key == ord("?"):
                self.message = "Keys: n=new, a=approve, h=halt, r=refresh, e=counts, j/k=select, q=quit"


def run_tui(root: Path, database: Path, session_id: str | None = None) -> None:
    app = TUIApp(root, database, session_id)
    curses.wrapper(app.run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="termux-agent-tui")
    parser.add_argument("--root", default=".")
    parser.add_argument("--db", default=os.getenv("TERMUX_AGENT_DB", str(Path.home() / ".termux-agent" / "sessions.db")))
    parser.add_argument("--session-id", default=None)
    args = parser.parse_args(argv)
    run_tui(Path(args.root), Path(args.db), args.session_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
