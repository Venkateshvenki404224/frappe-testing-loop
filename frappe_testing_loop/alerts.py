from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .utils import ensure_parent


def report_needs_attention(report: dict[str, Any]) -> bool:
    score = report.get("score", {}) or {}
    return score.get("status") in {"fail", "review"} or int(score.get("total") or 0) > 0


def build_issue_body(report: dict[str, Any]) -> str:
    """Build a compact GitHub/file alert body for non-pass audit runs."""
    score = report.get("score", {}) or {}
    summary = report.get("summary", {}) or {}
    findings = report.get("findings", []) or []
    timings = report.get("timings", []) or []
    bench_results = report.get("bench_results", []) or []

    high = [f for f in findings if f.get("severity") == "high"][:20]
    warn = [f for f in findings if f.get("severity") == "warn"][:20]
    failed_timings = [t for t in timings if not t.get("ok", True)][:20]
    failed_bench = [b for b in bench_results if not b.get("ok", True)][:10]

    lines = [
        f"# Frappe Testing Loop alert: `{report.get('app')}`",
        "",
        "The scheduled/manual Frappe Testing Loop audit found issues that need attention.",
        "",
        "## Score",
        "",
        f"- Status: `{score.get('status')}`",
        f"- Total: `{score.get('total')}`",
        f"- High: `{score.get('high', 0)}`",
        f"- Warnings: `{score.get('warn', 0)}`",
        f"- Guest APIs: `{score.get('guest_apis', 0)}`",
        f"- Runtime failures: `{score.get('runtime_failures', 0)}`",
        f"- Bench failures: `{score.get('bench_failures', 0)}`",
        "",
        "## Report links / paths",
        "",
        f"- Generated at: `{report.get('generated_at')}`",
        f"- App path: `{report.get('app_path')}`",
        f"- Report directory: `{report.get('report_dir') or ''}`",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(summary, indent=2),
        "```",
    ]

    if high:
        lines += ["", "## High findings - fix first", ""]
        for f in high:
            lines.append(f"- `{f.get('file')}:{f.get('line')}` **{f.get('category')}** — {f.get('message')}")

    if failed_bench:
        lines += ["", "## Bench failures", ""]
        for b in failed_bench:
            lines.append(f"- `{b.get('cmd')}` returncode={b.get('returncode')} error={b.get('error') or ''}")

    if failed_timings:
        lines += ["", "## Runtime failures", ""]
        for t in failed_timings:
            lines.append(f"- `{t.get('target')}` status={t.get('status_code')} error={t.get('error') or ''}")

    if warn:
        lines += ["", "## Warnings - review", ""]
        for f in warn:
            lines.append(f"- `{f.get('file')}:{f.get('line')}` **{f.get('category')}** — {f.get('message')}")

    lines += [
        "",
        "## AI remediation instructions",
        "",
        "1. Inspect the exact file and line before editing.",
        "2. Fix high/runtime/bench failures first.",
        "3. Review guest APIs and warnings; do not blindly delete Ponytail findings.",
        "4. Rerun Frappe Testing Loop and native Frappe tests after changes.",
    ]
    return "\n".join(lines) + "\n"


def write_attention_file(report: dict[str, Any], path: Path) -> None:
    ensure_parent(path)
    path.write_text(build_issue_body(report))


class tempfile_body:
    def __init__(self, body: str):
        self.body = body
        self.path: Path | None = None

    def __enter__(self) -> Path:
        import tempfile
        fd, name = tempfile.mkstemp(prefix="frappe-testing-loop-issue-", suffix=".md")
        os.close(fd)
        self.path = Path(name)
        self.path.write_text(self.body)
        return self.path

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.path and self.path.exists():
            self.path.unlink()


def publish_github_issue(report: dict[str, Any], repo: str | None, labels: str | None, dry_run: bool = False) -> dict[str, Any]:
    """Create a GitHub issue or comment on the existing open alert issue.

    Requires the GitHub CLI (`gh`) to be authenticated. The issue title is stable
    by app name so daily cron runs update one open issue instead of spamming.
    """
    title = f"[Frappe Testing Loop] {report.get('app')} audit requires attention"
    body = build_issue_body(report)
    repo_args = ["--repo", repo] if repo else []

    if dry_run:
        return {"ok": True, "dry_run": True, "title": title, "body": body}

    search_cmd = [
        "gh", "issue", "list", *repo_args,
        "--state", "open",
        "--search", title,
        "--json", "number,title,url",
        "--jq", ".[] | select(.title == " + json.dumps(title) + ") | [.number,.url] | @tsv",
    ]
    found = subprocess.run(search_cmd, text=True, capture_output=True)
    if found.returncode != 0:
        return {"ok": False, "error": found.stderr.strip() or found.stdout.strip(), "cmd": " ".join(search_cmd)}

    first = found.stdout.strip().splitlines()[0] if found.stdout.strip() else ""
    if first:
        number, url = first.split("\t", 1)
        with tempfile_body(body) as body_file:
            comment = subprocess.run(["gh", "issue", "comment", number, *repo_args, "--body-file", str(body_file)], text=True, capture_output=True)
        return {"ok": comment.returncode == 0, "action": "comment", "number": number, "url": url, "error": comment.stderr.strip() or comment.stdout.strip()}

    create_cmd = ["gh", "issue", "create", *repo_args, "--title", title]
    if labels:
        create_cmd += ["--label", labels]
    with tempfile_body(body) as body_file:
        create_cmd += ["--body-file", str(body_file)]
        created = subprocess.run(create_cmd, text=True, capture_output=True)
    out = created.stdout.strip()
    return {"ok": created.returncode == 0, "action": "create", "url": out, "error": created.stderr.strip() if created.returncode else ""}
