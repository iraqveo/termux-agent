"""Permission, governance, and path-safety primitives for the Termux agent."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable


class PermissionError(RuntimeError):
    """Raised when an operation is not allowed by policy or governance."""


class GovernanceError(RuntimeError):
    """Raised when a state transition or execution budget is invalid."""


class EvidenceKind(str, Enum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


class GovernanceState(str, Enum):
    ANALYZING = "ANALYZING"
    PREVIEWING = "PREVIEWING"
    SELF_REVIEW = "SELF_REVIEW"
    EXECUTING = "EXECUTING"
    HALTED = "HALTED"


_ALLOWED_TRANSITIONS: dict[GovernanceState, set[GovernanceState]] = {
    GovernanceState.ANALYZING: {GovernanceState.PREVIEWING, GovernanceState.HALTED},
    GovernanceState.PREVIEWING: {GovernanceState.SELF_REVIEW, GovernanceState.HALTED},
    GovernanceState.SELF_REVIEW: {GovernanceState.EXECUTING, GovernanceState.HALTED},
    GovernanceState.EXECUTING: {GovernanceState.ANALYZING, GovernanceState.HALTED},
    GovernanceState.HALTED: set(),
}


DEFAULT_ALLOWED_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("pytest",),
    ("python", "-m", "pytest"),
    ("npm", "test"),
    ("npm", "run", "build"),
    ("git", "diff"),
    ("git", "diff", "--check"),
    ("git", "status"),
    ("git", "status", "--short"),
    ("ruff", "check"),
    ("mypy",),
)

# This is deliberately a second line of defense. It is checked even if a
# future maintainer accidentally adds a broad command to the allowlist.
DENY_EXECUTABLES = frozenset({
    "rm", "sudo", "su", "curl", "wget", "chmod", "chown", "dd", "mkfs",
    "sh", "bash", "zsh", "fish", "busybox", "env", "nohup",
})
DENY_COMMAND_PATTERNS = (
    re.compile(r"\bgit\s+push\b", re.IGNORECASE),
    re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE),
    re.compile(r"\bnpm\s+publish\b", re.IGNORECASE),
)
SHELL_OPERATOR_PATTERN = re.compile(r"(?:&&|\|\||[;&|<>`]|\$\(|\r|\n)")


@dataclass
class GovernanceController:
    """Enforce explicit review stages, execution limits, and repeated-failure HALT."""

    state: GovernanceState = GovernanceState.ANALYZING
    max_consecutive_executions: int = 3
    audit_sink: Callable[[dict[str, Any]], None] | None = None
    consecutive_executions: int = 0
    _last_failure_digest: str | None = field(default=None, init=False)
    _last_failure_count: int = field(default=0, init=False)

    @classmethod
    def from_snapshot(
        cls,
        snapshot: dict[str, Any] | None,
        audit_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> "GovernanceController":
        if not snapshot:
            return cls(audit_sink=audit_sink)
        controller = cls(
            state=GovernanceState(str(snapshot.get("state", GovernanceState.ANALYZING.value))),
            audit_sink=audit_sink,
            consecutive_executions=int(snapshot.get("consecutive_executions", 0)),
        )
        controller._last_failure_digest = snapshot.get("last_failure_digest")
        controller._last_failure_count = int(snapshot.get("last_failure_count", 0))
        return controller

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "consecutive_executions": self.consecutive_executions,
            "last_failure_digest": self._last_failure_digest,
            "last_failure_count": self._last_failure_count,
        }

    def _audit(self, event: dict[str, Any]) -> None:
        if self.audit_sink is not None:
            self.audit_sink(event)

    def transition(
        self,
        next_state: GovernanceState,
        reason: str,
        evidence_kind: EvidenceKind = EvidenceKind.UNKNOWN,
        payload: dict[str, Any] | None = None,
    ) -> GovernanceState:
        if self.state == GovernanceState.HALTED:
            raise GovernanceError("governance is halted and requires a new session")
        if next_state not in _ALLOWED_TRANSITIONS[self.state]:
            raise GovernanceError(f"invalid transition {self.state.value} -> {next_state.value}")
        previous = self.state
        self.state = next_state
        self._audit({
            "event": "state_transition",
            "from_state": previous.value,
            "to_state": next_state.value,
            "reason": reason,
            "evidence_kind": evidence_kind.value,
            "payload": payload or {},
        })
        return self.state

    def begin_preview(self, reason: str = "task is ready for preview") -> GovernanceState:
        return self.transition(GovernanceState.PREVIEWING, reason, EvidenceKind.INFERRED)

    def begin_self_review(self, reason: str = "preview is complete") -> GovernanceState:
        return self.transition(GovernanceState.SELF_REVIEW, reason, EvidenceKind.OBSERVED)

    def approve_execution(self, reason: str = "self-review approved") -> GovernanceState:
        return self.transition(GovernanceState.EXECUTING, reason, EvidenceKind.OBSERVED)

    def require_execution(self) -> None:
        if self.state != GovernanceState.EXECUTING:
            raise GovernanceError(f"execution requires EXECUTING state, current state is {self.state.value}")
        if self.consecutive_executions >= self.max_consecutive_executions:
            self.halt("maximum consecutive execution steps reached")
            raise GovernanceError("execution budget exhausted; HALT required")

    def record_execution(self, success: bool, failure_reason: str | None = None) -> GovernanceState:
        if self.state != GovernanceState.EXECUTING:
            raise GovernanceError("cannot record execution outside EXECUTING state")
        self.consecutive_executions += 1
        if success:
            self._last_failure_digest = None
            self._last_failure_count = 0
            self._audit({
                "event": "execution_result",
                "from_state": self.state.value,
                "to_state": self.state.value,
                "reason": "execution completed",
                "evidence_kind": EvidenceKind.OBSERVED.value,
                "payload": {"success": True, "step": self.consecutive_executions},
            })
            if self.consecutive_executions >= self.max_consecutive_executions:
                return self.halt("maximum consecutive execution steps reached")
            return self.state

        reason = (failure_reason or "unknown execution failure").strip()[:500]
        digest = hashlib.sha256(reason.encode("utf-8")).hexdigest()
        self._last_failure_count = self._last_failure_count + 1 if digest == self._last_failure_digest else 1
        self._last_failure_digest = digest
        repeated = self._last_failure_count >= 2
        exhausted = self.consecutive_executions >= self.max_consecutive_executions
        if repeated or exhausted:
            why = "same failure observed twice" if repeated else "maximum consecutive execution steps reached"
            return self.halt(why, EvidenceKind.OBSERVED, {"failure_digest": digest, "failure_reason": reason})
        self._audit({
            "event": "execution_result",
            "from_state": self.state.value,
            "to_state": GovernanceState.ANALYZING.value,
            "reason": "execution failed; re-analysis required",
            "evidence_kind": EvidenceKind.OBSERVED.value,
            "payload": {"failure_reason": reason, "failure_digest": digest},
        })
        return self.transition(GovernanceState.ANALYZING, "execution failed; re-analysis required", EvidenceKind.OBSERVED, {"failure_reason": reason})

    def halt(
        self,
        reason: str,
        evidence_kind: EvidenceKind = EvidenceKind.OBSERVED,
        payload: dict[str, Any] | None = None,
    ) -> GovernanceState:
        if self.state == GovernanceState.HALTED:
            return self.state
        previous = self.state
        self.state = GovernanceState.HALTED
        self._audit({
            "event": "halt",
            "from_state": previous.value,
            "to_state": GovernanceState.HALTED.value,
            "reason": reason,
            "evidence_kind": evidence_kind.value,
            "payload": payload or {},
        })
        return self.state


@dataclass(frozen=True)
class Policy:
    """Defense-in-depth policy: legacy mode plus exact argv and governance checks."""

    mode: str = "plan"
    allowed_commands: tuple[tuple[str, ...], ...] = DEFAULT_ALLOWED_COMMANDS
    max_output_bytes: int = 32_000
    deny_executables: frozenset[str] = DENY_EXECUTABLES
    deny_patterns: tuple[re.Pattern[str], ...] = DENY_COMMAND_PATTERNS

    @classmethod
    def from_environment(cls, mode: str = "plan") -> "Policy":
        raw = os.getenv("TERMUX_AGENT_ALLOWED_COMMANDS")
        if not raw:
            return cls(mode=mode)
        try:
            configured = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("TERMUX_AGENT_ALLOWED_COMMANDS must be a JSON array") from exc
        if not isinstance(configured, list):
            raise ValueError("TERMUX_AGENT_ALLOWED_COMMANDS must be a JSON array")
        commands: list[tuple[str, ...]] = []
        for item in configured:
            if isinstance(item, str):
                argv = tuple(shlex.split(item))
            elif isinstance(item, list) and all(isinstance(part, str) for part in item):
                argv = tuple(item)
            else:
                raise ValueError("each allowlist entry must be a command string or argv array")
            if not argv:
                raise ValueError("allowlist entries cannot be empty")
            commands.append(argv)
        return cls(mode=mode, allowed_commands=tuple(commands))

    def require(self, capability: str) -> None:
        if capability == "write" and self.mode != "build":
            raise PermissionError("write operations require build mode")
        if capability == "execute" and self.mode != "build":
            raise PermissionError("command execution requires build mode")

    def check_command(self, command: str) -> list[str]:
        """Parse once and require exact argv equality; never use substring matching."""
        self.require("execute")
        if not command.strip():
            raise PermissionError("empty command")
        if SHELL_OPERATOR_PATTERN.search(command):
            raise PermissionError("shell operators and command chaining are rejected")
        try:
            parts = tuple(shlex.split(command))
        except ValueError as exc:
            raise PermissionError(f"invalid command syntax: {exc}") from exc
        if not parts:
            raise PermissionError("empty command")
        if parts not in self.allowed_commands:
            allowed = ", ".join(" ".join(argv) for argv in self.allowed_commands)
            raise PermissionError(f"command must exactly match an allowlist entry; allowed: {allowed}")
        if any(Path(token).name in self.deny_executables for token in parts):
            raise PermissionError("destructive, privilege-changing, or shell-wrapper command rejected")
        normalized = " ".join(parts)
        if any(pattern.search(normalized) for pattern in self.deny_patterns):
            raise PermissionError("defensive denylist rejected the command")
        return list(parts)


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
