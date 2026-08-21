"""Clean, chat-first local TUI for Termux Agent."""

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
        self.message = "جاهز"
        if self.session_id is None:
            sessions = self.store.list(limit=1)
            self.session_id = sessions[0]["id"] if sessions else self.store.create("جلسة محادثة")

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
        lines = ["TERMUX AGENT", "", "Conversation"]
        messages = record.get("messages") or []
        if not messages:
            lines.extend(["", "مرحباً.", "اكتب رسالتك في الأسفل للبدء."])
        else:
            for item in messages[-8:]:
                role = "أنت" if item.get("role") == "user" else "وكيل"
                lines.append(f"{role}: {self._clip(item.get('content', ''), max(20, width - 8))}")
        lines.extend(["", self.message, "↑ إرسال"])
        return lines

    def add_message(self, content: str) -> None:
        content = content.strip()
        if not content:
            self.message = "اكتب رسالة أولاً"
            return
        self.store.add_message(self.session_id, "user", content)
        self.store.add_evidence(self.session_id, EvidenceKind.UNKNOWN.value, "tui.message", content)
        self.message = "تم الحفظ محلياً"

    def _prompt(self, screen: Any) -> str:
        height, width = screen.getmaxyx()
        prompt = "اكتب رسالتك: "
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

    def _draw_header(self, screen: Any, width: int) -> None:
        title = "TERMUX AGENT"
        x = max(1, (width - len(title)) // 2)
        screen.attron(curses.color_pair(1) | curses.A_BOLD)
        screen.addstr(0, x, title)
        screen.attroff(curses.color_pair(1) | curses.A_BOLD)
        screen.addstr(1, 1, "─" * max(1, width - 2), curses.A_DIM)

    def _draw_messages(self, screen: Any, width: int, height: int) -> None:
        record = self.selected_record()
        messages = record.get("messages") or []
        top = 3
        bottom = height - 5
        if not messages:
            screen.attron(curses.color_pair(1) | curses.A_BOLD)
            screen.addstr(top, 2, self._clip("مرحباً، كيف أساعدك؟", width - 4))
            screen.attroff(curses.color_pair(1) | curses.A_BOLD)
            screen.addstr(top + 2, 2, self._clip("اكتب طلبك في الأسفل ثم اضغط Enter.", width - 4), curses.A_DIM)
            return

        row = top
        for item in messages[-10:]:
            if row >= bottom:
                break
            is_user = item.get("role") == "user"
            label = "أنت" if is_user else "الوكيل"
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

    def _draw_composer(self, screen: Any, width: int, height: int) -> None:
        """Draw exactly two compact bottom rows with a centered send arrow."""
        left = 1
        inner = max(8, width - 2)
        top = height - 4
        line_one = "╭" + "─" * (inner - 2) + "╮"
        line_two = "│" + " " * (inner - 2) + "│"
        screen.addstr(top, left, line_one[: width - 1])
        screen.addstr(top + 1, left, line_two[: width - 1])
        arrow = "↑"
        send = " إرسال "
        center = max(left + 2, (width - len(arrow + send)) // 2)
        screen.attron(curses.color_pair(1) | curses.A_BOLD)
        screen.addstr(top + 1, center, f"{arrow}{send}")
        screen.attroff(curses.color_pair(1) | curses.A_BOLD)
        screen.addstr(height - 1, 1, self._clip("Enter كتابة رسالة   q خروج", width - 2), curses.A_DIM)

    def draw(self, screen: Any) -> None:
        screen.erase()
        height, width = screen.getmaxyx()
        if height < 10 or width < 40:
            screen.addstr(0, 0, "كبّر نافذة Termux إلى 40x10 على الأقل · q للخروج")
            screen.refresh()
            return
        self._draw_header(screen, width)
        self._draw_messages(screen, width, height)
        screen.addstr(height - 5, 1, self._clip(self.message, width - 2), curses.A_DIM)
        self._draw_composer(screen, width, height)
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
                self.message = "تم التحديث"
            elif key == ord("?"):
                self.message = "Enter كتابة رسالة · q خروج"


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
