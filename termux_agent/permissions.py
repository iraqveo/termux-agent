"""Permission and path-safety primitives for the Termux agent."""

from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class PermissionError(RuntimeError):
    """Raised when an operation is not allowed in the current mode."""


@dataclass(frozen=True)
class Policy:
    mode: str = "plan"
    allowed_commands: tuple[str, ...] = (
        "python",
        "pytest",
        "git",
        "npm",
        "node",
        "ruff",
        "mypy",
    )
    max_output_bytes: int = 32_000

    @classmethod
    def from_environment(cls, mode: str = "plan") -> "Policy":
        raw = os.getenv("TERMUX_AGENT_ALLOWED_COMMANDS")
        if not raw:
            return cls(mode=mode)
        try:
            values = tuple(str(item) for item in json.loads(raw))
        except (TypeError, ValueError) as exc:
            raise ValueError("TERMUX_AGENT_ALLOWED_COMMANDS must be a JSON array") from exc
        return cls(mode=mode, allowed_commands=values)

    def require(self, capability: str) -> None:
        if capability == "write" and self.mode != "build":
            raise PermissionError("write operations require build mode")
        if capability == "execute" and self.mode != "build":
            raise PermissionError("command execution requires build mode")

    def check_command(self, command: str) -> list[str]:
        self.require("execute")
        parts = shlex.split(command)
        if not parts:
            raise PermissionError("empty command")
        executable = Path(parts[0]).name
        if executable not in self.allowed_commands:
            allowed = ", ".join(self.allowed_commands)
            raise PermissionError(f"command '{executable}' is not allowed; allowed: {allowed}")
        forbidden = {"rm", "sudo", "su", "curl", "wget", "chmod", "chown", "dd", "mkfs"}
        if any(Path(token).name in forbidden for token in parts):
            raise PermissionError("destructive or network-sensitive command rejected")
        return parts


def safe_path(root: Path, relative: str | Path) -> Path:
    """Resolve a workspace-relative path and reject traversal/symlink escapes."""

    root = root.expanduser().resolve()
    candidate = (root / relative).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"path escapes workspace: {relative}") from exc
    existing = candidate
    while existing != root and not existing.exists():
        existing = existing.parent
    if existing.is_symlink():
        raise PermissionError(f"symlink path rejected: {relative}")
    return candidate


def bounded_text(value: str, limit: int) -> str:
    if len(value.encode("utf-8")) <= limit:
        return value
    encoded = value.encode("utf-8")[:limit]
    return encoded.decode("utf-8", errors="ignore") + "\n...[truncated]"


def normalize_patterns(patterns: Iterable[str]) -> tuple[str, ...]:
    return tuple(pattern for pattern in patterns if pattern and len(pattern) <= 200)
