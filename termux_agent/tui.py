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
        self.draft = ""
        self.input_active = False
        self.exit_requested = False
        if self.session_id is None:
            sessions = self.store.list(limit=1)
            self.session_id = sessions[0]["id"] if sessions else self.store.create("Chat session")
        self._metadata = self._load_metadata()

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
        record = self.selected_record()
        lines: list[str] = []
        messages = record.get("messages") or []
        if messages:
            lines.extend(self._wrap(str(messages[-1].get("content", "")), max(4, width - 2))[:4])
            lines.append("")
        prompt = self.draft if self.draft else "Ask your question..."
        if self.input_active:
            prompt += "▌"
        lines.extend([
            "─" * min(width, 72),
            f"❯ {prompt}",
            "─" * min(width, 72),
            self._metadata_line(width),
        ])
        return lines

    def _load_metadata(self) -> dict[str, Any]:
        usage = self.store.get_usage(self.session_id)
        return {
            "model": os.getenv("TERMUX_AGENT_MODEL", str(usage.get("model", "Not connected"))),
            "repository": os.getenv("TERMUX_AGENT_REPOSITORY", "") or str(usage.get("repository", "")) or self.root.name,
            "used": int(usage.get("total_tokens", 0)),
        }

    def _metadata_line(self, width: int) -> str:
        return self._clip(
            f"Model: {self._metadata['model']}  |  Repo: {self._metadata['repository']}  |  "
            f"Used: {self._metadata['used']:,}",
            max(1, width),
        )

    def add_message(self, content: str) -> None:
        content = content.strip()
        if not content:
            self.message = "Please type a message first"
            return
        self.store.add_message(self.session_id, "user", content)
        self.store.add_evidence(self.session_id, EvidenceKind.UNKNOWN.value, "tui.message", content)
        self.draft = ""
        self.input_active = False
        self.message = "Saved locally"
        self._metadata = self._load_metadata()

    def _draw_question_bar(
        self,
        screen: Any,
        width: int,
        top: int,
        draft: str | None = None,
        active: bool = False,
    ) -> None:
        rule = "─" * max(1, width - 2)
        screen.addstr(top, 1, rule[: max(1, width - 2)], curses.A_DIM)
        text = draft if draft else "Ask your question..."
        caret = "▌" if active else ""
        prompt = self._clip(f"❯ {text}{caret}", max(1, width - 2))
        screen.attron(curses.color_pair(1) | curses.A_BOLD)
        screen.addstr(top + 1, 1, prompt)
        screen.attroff(curses.color_pair(1) | curses.A_BOLD)
        screen.addstr(top + 2, 1, rule[: max(1, width - 2)], curses.A_DIM)

    def _draw_last_message(self, screen: Any, width: int, height: int) -> None:
        """Show only the most recently sent message above the input bar."""
        record = self.selected_record()
        messages = record.get("messages") or []
        if not messages:
            return
        content = str(messages[-1].get("content", ""))
        max_rows = max(1, height - 6)
        for row, line in enumerate(self._wrap(content, max(4, width - 4))[-max_rows:], start=1):
            screen.addstr(row, 2, self._clip(line, max(1, width - 4)))

    def _draw_input_bar(self, screen: Any, width: int, height: int) -> None:
        """Redraw only the four bottom rows; typing never clears the whole screen."""
        top = height - 4
        for row in range(top, height):
            screen.move(row, 0)
            screen.clrtoeol()
        self._draw_question_bar(screen, width, top, self.draft, self.input_active)
        screen.addstr(height - 1, 1, self._metadata_line(width - 2), curses.A_DIM)
        screen.refresh()

    def read_draft(self, screen: Any) -> str:
        """Read one draft interactively with partial redraw and cached token encoding."""
        buffer: list[str] = []
        self.draft = ""
        self.input_active = True
        curses.curs_set(0)
        try:
            while True:
                self.draft = "".join(buffer)
                height, width = screen.getmaxyx()
                self._draw_input_bar(screen, width, height)
                key = screen.get_wch()
                if key in ("\n", "\r"):
                    return self.draft.strip()
                if key == "\x1b":
                    self.draft = ""
                    self.input_active = False
                    self._draw_input_bar(screen, *screen.getmaxyx()[::-1])
                    return ""
                if key == "q" and not buffer:
                    self.exit_requested = True
                    self.input_active = False
                    return ""
                if key in (curses.KEY_BACKSPACE, "\b", "\x7f"):
                    if buffer:
                        buffer.pop()
                elif isinstance(key, str) and key.isprintable():
                    buffer.append(key)
        finally:
            self.input_active = False
            curses.curs_set(0)



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


    def draw(self, screen: Any) -> None:
        screen.erase()
        height, width = screen.getmaxyx()
        if height < 7 or width < 40:
            screen.addstr(0, 0, "Resize Termux to at least 40x7 · q to quit")
            screen.refresh()
            return
        self._draw_last_message(screen, width, height)
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
            self.input_active = True
            message = self.read_draft(screen)
            if self.exit_requested:
                return
            self.add_message(message)


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
