"""High-signal tools exposed to the local agent and MCP client."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .permissions import EvidenceKind, GovernanceController, Policy, bounded_text, safe_path


@dataclass
class ToolRuntime:
    root: Path
    policy: Policy
    governance: GovernanceController | None = None
    session_store: Any | None = None
    session_id: str | None = None

    def __post_init__(self) -> None:
        self.root = self.root.expanduser().resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(self.root)
        if self.governance is None:
            snapshot = self.session_store.get_governance_snapshot(self.session_id) if self.session_store and self.session_id else None
            self.governance = GovernanceController.from_snapshot(snapshot, audit_sink=self._audit)
        elif self.governance.audit_sink is None:
            self.governance.audit_sink = self._audit

    def _audit(self, event: dict[str, Any]) -> None:
        if self.session_store is not None:
            self.session_store.add_governance_event(self.session_id, event)
            if self.governance is not None:
                self.session_store.save_governance_snapshot(self.session_id, self.governance.snapshot())

    def _evidence(self, kind: EvidenceKind, source: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        if self.session_store is not None:
            self.session_store.add_evidence(self.session_id, kind.value, source, content, metadata)

    def approve_execution(self, reason: str = "explicit user approval") -> str:
        """Move through PREVIEWING and SELF_REVIEW before enabling execution."""
        assert self.governance is not None
        self.governance.begin_preview("preview generated")
        self.governance.begin_self_review("self-review completed")
        self.governance.approve_execution(reason)
        return self.governance.state.value

    def halt(self, reason: str) -> str:
        assert self.governance is not None
        return self.governance.halt(reason).value

    def status(self) -> dict[str, Any]:
        assert self.governance is not None
        return {
            "state": self.governance.state.value,
            "consecutive_executions": self.governance.consecutive_executions,
            "max_consecutive_executions": self.governance.max_consecutive_executions,
        }

    def read_file(self, path: str, max_bytes: int = 64_000) -> dict:
        target = safe_path(self.root, path)
        if not target.is_file():
            raise FileNotFoundError(path)
        data = target.read_bytes()[: max(1, min(max_bytes, self.policy.max_output_bytes * 2))]
        content = data.decode("utf-8", errors="replace")
        self._evidence(EvidenceKind.OBSERVED, "read_file", f"read {len(data)} bytes from {path}")
        return {"path": str(target.relative_to(self.root)), "content": content}

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
                        self._evidence(EvidenceKind.OBSERVED, "search_text", f"found {len(matches)} matches for {pattern}")
                        return matches
        self._evidence(EvidenceKind.OBSERVED, "search_text", f"found {len(matches)} matches for {pattern}")
        return matches

    def _require_execution(self) -> None:
        assert self.governance is not None
        self.governance.require_execution()

    def write_file(self, path: str, content: str) -> dict:
        self.policy.require("write")
        self._require_execution()
        target = safe_path(self.root, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        result = {"path": str(target.relative_to(self.root)), "bytes": target.stat().st_size}
        self._evidence(EvidenceKind.OBSERVED, "write_file", f"wrote {result['bytes']} bytes to {path}")
        self.governance.record_execution(True)  # type: ignore[union-attr]
        return result

    def run_command(self, command: str, timeout: int = 60) -> dict:
        argv = self.policy.check_command(command)
        self._require_execution()
        timeout = max(1, min(timeout, 300))
        try:
            completed = subprocess.run(
                argv,
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "TERMUX_AGENT_ROOT": str(self.root)},
                check=False,
            )
            result = {
                "command": command,
                "returncode": completed.returncode,
                "stdout": bounded_text(completed.stdout, self.policy.max_output_bytes),
                "stderr": bounded_text(completed.stderr, self.policy.max_output_bytes),
            }
        except subprocess.TimeoutExpired as exc:
            result = {"command": command, "returncode": 124, "stdout": "", "stderr": f"timeout after {timeout}s: {exc}"}
        success = result["returncode"] == 0
        self._evidence(EvidenceKind.OBSERVED, "run_command", f"{command} returned {result['returncode']}", {"returncode": result["returncode"]})
        self.governance.record_execution(success, result["stderr"] or f"return code {result['returncode']}")  # type: ignore[union-attr]
        return result

    def notify(self, title: str, content: str) -> dict:
        executable = "termux-notification"
        if not shutil_which(executable):
            self._evidence(EvidenceKind.UNKNOWN, "notify", f"{executable} is not installed")
            return {"sent": False, "reason": f"{executable} is not installed"}
        completed = subprocess.run(
            [executable, "--title", title[:120], "--content", content[:500]],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self._evidence(EvidenceKind.OBSERVED, "notify", f"notification returned {completed.returncode}")
        return {"sent": completed.returncode == 0, "returncode": completed.returncode, "stderr": completed.stderr[:500]}


def shutil_which(executable: str) -> str | None:
    """Small wrapper kept injectable for tests."""
    import shutil

    return shutil.which(executable)
