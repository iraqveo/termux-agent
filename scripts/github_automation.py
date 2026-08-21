#!/usr/bin/env python3
"""Safe, deterministic GitHub maintenance helpers used by Actions.

The scripts intentionally do not execute issue or pull-request content. They only
inspect repository text and publish bounded, reviewable metadata through `gh`.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


IGNORED = {".git", ".venv", "node_modules", "__pycache__", "dist", "build"}


def gh(*args: str, input_text: str | None = None) -> str:
    result = subprocess.run(["gh", *args], text=True, input=input_text, capture_output=True, check=True)
    return result.stdout


def repo_name() -> str:
    return os.environ["GITHUB_REPOSITORY"]


def todos(root: Path) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in IGNORED for part in path.parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, start=1):
            if "TODO" in line or "FIXME" in line:
                found.append({"path": str(path.relative_to(root)), "line": number, "text": line.strip()[:240]})
    return found[:200]


def open_issues() -> list[dict]:
    raw = gh("issue", "list", "--repo", repo_name(), "--state", "open", "--limit", "100", "--json", "number,title")
    return json.loads(raw or "[]")


def scan_todos(root: Path) -> int:
    items = todos(root)
    if not items:
        print("No TODO or FIXME markers found.")
        return 0
    title = "Maintenance: tracked TODO/FIXME markers"
    existing = {item["title"] for item in open_issues()}
    if title in existing:
        print("A matching maintenance issue is already open.")
        return 0
    body = "## Findings\n\nThe scheduled scan found the following markers:\n\n"
    body += "\n".join(f"- `{item['path']}:{item['line']}` — `{item['text']}`" for item in items)
    body += "\n\nThis issue was created by a deterministic repository scan; no source code was executed."
    gh("issue", "create", "--repo", repo_name(), "--title", title, "--label", "maintenance", "--body", body[:12_000])
    print(f"Created issue for {len(items)} markers.")
    return 0


def triage_issue() -> int:
    payload = json.loads(os.environ.get("ISSUE_PAYLOAD", "{}"))
    issue = payload.get("issue", {})
    number = str(issue.get("number", ""))
    text = f"{issue.get('title', '')} {issue.get('body', '')}".lower()
    if not number:
        print("No issue payload supplied.")
        return 1
    label = "bug" if any(word in text for word in ("error", "bug", "fail", "crash")) else "discussion"
    try:
        gh("label", "create", label, "--repo", repo_name(), "--color", "D4C5F9", "--force")
    except subprocess.CalledProcessError:
        pass
    gh("issue", "edit", number, "--repo", repo_name(), "--add-label", label)
    gh("issue", "comment", number, "--repo", repo_name(), "--body", f"Automated triage: marked this issue as **{label}** based on its text. A maintainer should review the classification.")
    return 0


def review_pr() -> int:
    event = json.loads(os.environ.get("PR_PAYLOAD", "{}"))
    number = str(event.get("number", ""))
    if not number:
        print("No pull-request payload supplied.")
        return 1
    diff_check = subprocess.run(["git", "diff", "--check", "HEAD^", "HEAD"], text=True, capture_output=True, check=False)
    if diff_check.returncode == 0:
        body = "Automated review: `git diff --check` passed. The repository test workflow is the source of truth for behavior."
    else:
        body = "Automated review found whitespace errors:\n\n```text\n" + diff_check.stdout[:6_000] + "\n```"
    gh("pr", "comment", number, "--repo", repo_name(), "--body", body)
    return 0 if diff_check.returncode == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan-todos")
    scan.add_argument("--root", default=".")
    sub.add_parser("triage-issue")
    sub.add_parser("review-pr")
    args = parser.parse_args()
    if args.command == "scan-todos":
        return scan_todos(Path(args.root).resolve())
    if args.command == "triage-issue":
        return triage_issue()
    return review_pr()


if __name__ == "__main__":
    raise SystemExit(main())
