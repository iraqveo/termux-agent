"""Clean, English, chat-first local TUI for Termux Agent."""

from __future__ import annotations

import argparse
import curses
import os
import textwrap
from pathlib import Path
from typing import Any

from .permissions import EvidenceKind
from .session import SessionStore


class TUIApp:
    """Minimal mobile chat surface; persistence and governance stay behind the UI."""

    def __init__(self, root: Path, database: Path, session_id: str | None = None):
        self.root = root.expanduser().resolve()
        self.store = SessionStore(database.expanduser())
        self.session_id = session_id
        self.message = "Ready"
        if self.session_id is None:
            sessions = self.store.list(limit=1)
            self.session_id = sessions[0]["id"] if sessions else self.store.create("Chat session")

    @staticmethod
    def _clip(value: object, width: int) -> str:
        text = str(value).replace("\n", " ")
        if width <= 1:
            return ""
        return text if len(text) <= width else text[: width - 1] + "…"

    @staticmethod
    def _wrap(value: object, width: int) -> list[str]:
        return textwrap.wrap(str(value), width=max(4, width), break_long_words=False) or [""]

    def selected_record(self) -> dict[str, Any]:
        return self.store.get(self.session_id) or {"messages": []}

    def render_lines(self, width: int = 100) -> list[str]:
        """Accessible text fallback used by tests and small terminals."""
        return [
            "─" * min(width, 72),
            "❯ Ask your question...",
            "─" * min(width, 72),
        ]

    def add_message(self, content: str) -> None:
        content = content.strip()
        if not content:
            self.message = "Please type a message first"
            return
        self.store.add_message(self.session_id, "user", content)
        self.store.add_evidence(self.session_id, EvidenceKind.UNKNOWN.value, "tui.message", content)
        self.message = "Saved locally"

    def _prompt(self, screen: Any) -> str:
        height, width = screen.getmaxyx()
        prompt = "Message: "
        screen.move(height - 1, 1)
        screen.clrtoeol()
        screen.addstr(height - 1, 1, self._clip(prompt, width - 2))
        screen.refresh()
        curses.echo()
        try:
            value = screen.getstr(height - 1, min(width - 2, len(prompt) + 2), max(1, width - len(prompt) - 3))
            return value.decode("utf-8", errors="replace").strip()
        finally:
            curses.noecho()

    def _draw_question_bar(self, screen: Any, width: int, top: int) -> None:
        rule = "─" * max(1, width - 2)
        screen.addstr(top, 1, rule[: max(1, width - 2)], curses.A_DIM)
        screen.attron(curses.color_pair(1) | curses.A_BOLD)
        screen.addstr(top + 1, 1, self._clip("❯ Ask your question...", max(1, width - 2)))
        screen.attroff(curses.color_pair(1) | curses.A_BOLD)
        screen.addstr(top + 2, 1, rule[: max(1, width - 2)], curses.A_DIM)

    def _draw_header(self, screen: Any, width: int) -> None:
        title = "TERMUX AGENT"
        x = max(1, (width - len(title)) // 2)
        screen.attron(curses.color_pair(1) | curses.A_BOLD)
        screen.addstr(3, x, title)
        screen.attroff(curses.color_pair(1) | curses.A_BOLD)
        screen.addstr(4, 1, "─" * max(1, width - 2), curses.A_DIM)

    def _draw_messages(self, screen: Any, width: int, height: int) -> None:
        record = self.selected_record()
        messages = record.get("messages") or []
        top = 3
        bottom = height - 5
        if not messages:
            screen.attron(curses.color_pair(1) | curses.A_BOLD)
            screen.addstr(top, 2, self._clip("Hello, how can I help?", width - 4))
            screen.attroff(curses.color_pair(1) | curses.A_BOLD)
            screen.addstr(top + 2, 2, self._clip("Type your request below and press Enter.", width - 4), curses.A_DIM)
            return

        row = top
        for item in messages[-10:]:
            if row >= bottom:
                break
            is_user = item.get("role") == "user"
            label = "You" if is_user else "Agent"
            color = 2 if is_user else 1
            screen.attron(curses.color_pair(color) | curses.A_BOLD)
            screen.addstr(row, 2, label)
            screen.attroff(curses.color_pair(color) | curses.A_BOLD)
            row += 1
            for wrapped in self._wrap(item.get("content", ""), width - 6)[:3]:
                if row >= bottom:
                    break
                screen.addstr(row, 3, self._clip(wrapped, width - 5))
                row += 1
            row += 1

    def _draw_input_bar(self, screen: Any, width: int, height: int) -> None:
        """Draw the only visible surface at the bottom of the screen."""
        self._draw_question_bar(screen, width, height - 4)

    def draw(self, screen: Any) -> None:
        screen.erase()
        height, width = screen.getmaxyx()
        if height < 7 or width < 40:
            screen.addstr(0, 0, "Resize Termux to at least 40x7 · q to quit")
            screen.refresh()
            return
        self._draw_input_bar(screen, width, height)
        screen.refresh()

    def run(self, screen: Any) -> None:
        curses.curs_set(0)
        screen.keypad(True)
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_YELLOW, -1)
        while True:
            self.draw(screen)
            key = screen.getch()
            if key in (ord("q"), 27):
                return
            if key in (10, 13, ord("i")):
                self.add_message(self._prompt(screen))
            elif key == ord("r"):
                self.message = "Refreshed"
            elif key == ord("?"):
                self.message = "Enter  Type message     q  Quit"


def run_tui(root: Path, database: Path, session_id: str | None = None) -> None:
    curses.wrapper(TUIApp(root, database, session_id).run)


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
