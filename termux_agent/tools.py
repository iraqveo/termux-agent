"""High-signal tools exposed to the local agent and MCP client."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .permissions import Policy, bounded_text, safe_path


@dataclass
class ToolRuntime:
    root: Path
    policy: Policy

    def __post_init__(self) -> None:
        self.root = self.root.expanduser().resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(self.root)

    def read_file(self, path: str, max_bytes: int = 64_000) -> dict:
        target = safe_path(self.root, path)
        if not target.is_file():
            raise FileNotFoundError(path)
        data = target.read_bytes()[: max(1, min(max_bytes, self.policy.max_output_bytes * 2))]
        return {"path": str(target.relative_to(self.root)), "content": data.decode("utf-8", errors="replace")}

    def search_text(self, pattern: str, path: str = ".", max_results: int = 100) -> list[dict]:
        if not pattern or len(pattern) > 200:
            raise ValueError("pattern must contain 1-200 characters")
        base = safe_path(self.root, path)
        if not base.exists():
            raise FileNotFoundError(path)
        try:
            matcher = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"invalid regular expression: {exc}") from exc
        candidates = [base] if base.is_file() else [item for item in base.rglob("*") if item.is_file()]
        ignored = {".git", ".venv", "node_modules", "__pycache__"}
        matches: list[dict] = []
        for candidate in candidates:
            if any(part in ignored for part in candidate.parts):
                continue
            try:
                lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for number, line in enumerate(lines, start=1):
                if matcher.search(line):
                    matches.append({"path": str(candidate.relative_to(self.root)), "line": number, "text": line[:500]})
                    if len(matches) >= max(1, min(max_results, 500)):
                        return matches
        return matches

    def write_file(self, path: str, content: str) -> dict:
        self.policy.require("write")
        target = safe_path(self.root, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"path": str(target.relative_to(self.root)), "bytes": target.stat().st_size}

    def run_command(self, command: str, timeout: int = 60) -> dict:
        argv = self.policy.check_command(command)
        timeout = max(1, min(timeout, 300))
        completed = subprocess.run(
            argv,
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "TERMUX_AGENT_ROOT": str(self.root)},
            check=False,
        )
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": bounded_text(completed.stdout, self.policy.max_output_bytes),
            "stderr": bounded_text(completed.stderr, self.policy.max_output_bytes),
        }

    def notify(self, title: str, content: str) -> dict:
        executable = "termux-notification"
        if not shutil_which(executable):
            return {"sent": False, "reason": f"{executable} is not installed"}
        completed = subprocess.run(
            [executable, "--title", title[:120], "--content", content[:500]],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return {"sent": completed.returncode == 0, "returncode": completed.returncode, "stderr": completed.stderr[:500]}


def shutil_which(executable: str) -> str | None:
    """Small wrapper kept injectable for tests."""
    import shutil

    return shutil.which(executable)
