from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sys

from .alerts import publish_github_issue, report_needs_attention, write_attention_file
from .models import Finding
from .reports import write_html_report, write_markdown_report, write_reports_index
from .runners import http_checks, run_bench
from .scanners import scan_doctypes, scan_hooks, scan_official_standards, scan_patterns, scan_ponytail, whitelist_functions
from .scoring import append_results_history, compute_score
from .utils import create_report_run_dir, ensure_parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", type=Path, help="Path to frappe-bench")
    ap.add_argument("--app", required=True, help="App name")
    ap.add_argument("--site", help="Frappe site name")
    ap.add_argument("--base-url", help="Base URL, e.g. http://localhost:8000")
    ap.add_argument("--username")
    ap.add_argument("--password")
    ap.add_argument("--endpoint", action="append", default=[], help="Dotted whitelisted method to time; repeatable")
    ap.add_argument("--route", action="append", default=[], help="Route to time; repeatable")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--run-bench", action="store_true", help="Run bench tests/migrate commands")
    ap.add_argument("--include-tests", action="store_true", help="Include test files in static/Ponytail scans")
    ap.add_argument("--no-ponytail", action="store_true", help="Disable Ponytail over-engineering/debt audit layer")
    ap.add_argument("--json", type=Path, help="Write JSON report")
    ap.add_argument("--md", type=Path, help="Write human/AI-readable Markdown report")
    ap.add_argument("--html", type=Path, help="Write standalone human-readable HTML report")
    ap.add_argument("--reports-dir", type=Path, help="Base directory for automatic per-run report folders. Defaults to skills/frappe-testing-loop/reports")
    ap.add_argument("--no-default-reports", action="store_true", help="Do not auto-write reports when --json/--md/--html are omitted")
    ap.add_argument("--no-index", action="store_true", help="Do not update reports/index.html for automatic report runs")
    ap.add_argument("--attention-file", type=Path, help="Write GitHub-ready issue Markdown when audit status is fail/review")
    ap.add_argument("--no-auto-attention-file", action="store_true", help="Do not auto-write issue.md inside automatic report folders")
    ap.add_argument("--github-issue", action="store_true", help="Create a GitHub issue or comment on the existing open audit issue when status is fail/review")
    ap.add_argument("--github-repo", help="GitHub repo for --github-issue, e.g. owner/repo. Defaults to gh current repo")
    ap.add_argument("--github-label", help="Comma-separated labels to apply when creating a new GitHub issue")
    ap.add_argument("--github-dry-run", action="store_true", help="Build GitHub issue payload without calling gh; useful for tests")
    args = ap.parse_args()

    should_auto_write_reports = not args.no_default_reports and not (args.json or args.md or args.html)
    auto_report_dir: Path | None = None

    bench = args.bench or Path.cwd()
    app_path = bench / "apps" / args.app
    if not app_path.exists():
        # Also allow direct app path as --bench parent/current path during local planning.
        direct = Path.cwd() / args.app
        if direct.exists():
            app_path = direct
        else:
            print(f"ERROR: app path not found: {app_path}", file=sys.stderr)
            return 2

    if should_auto_write_reports:
        auto_report_dir = create_report_run_dir(args.app, args.reports_dir)
        args.json = auto_report_dir / "audit.json"
        args.md = auto_report_dir / "review.md"
        args.html = auto_report_dir / "audit.html"

    findings = []
    findings += scan_patterns(app_path, include_tests=args.include_tests)
    findings += scan_official_standards(app_path, include_tests=args.include_tests)
    apis, f = whitelist_functions(app_path, include_tests=args.include_tests); findings += f
    doctypes, f = scan_doctypes(app_path); findings += f
    hooks, f = scan_hooks(app_path); findings += f
    if not args.no_ponytail:
        findings += scan_ponytail(app_path, include_tests=args.include_tests)

    bench_results = []
    if args.run_bench:
        if not args.site:
            findings.append(Finding("high", "bench", "", 0, "--run-bench requires --site"))
        else:
            bench_results = run_bench(bench, args.site, [["migrate"], ["run-tests", "--app", args.app]])

    timings = []
    if args.base_url:
        timings = http_checks(args.base_url, args.username, args.password, args.endpoint, args.route, args.repeat)

    report = {
        "app": args.app,
        "app_path": str(app_path),
        "summary": {
            "findings": len(findings),
            "high": sum(1 for x in findings if x.severity == "high"),
            "warn": sum(1 for x in findings if x.severity == "warn"),
            "info": sum(1 for x in findings if x.severity == "info"),
            "ponytail": sum(1 for x in findings if x.category.startswith("ponytail")),
            "whitelisted_apis": len(apis),
            "guest_apis": sum(1 for x in apis if x.get("allow_guest")),
            "doctypes": len(doctypes),
        },
        "findings": [asdict(x) for x in findings],
        "whitelisted_apis": apis,
        "doctypes": doctypes,
        "hooks": hooks,
        "bench_results": bench_results,
        "timings": [asdict(x) for x in timings],
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "report_dir": str(auto_report_dir) if auto_report_dir else None,
    }
    report["score"] = compute_score(report)

    if auto_report_dir and not args.no_auto_attention_file and report_needs_attention(report):
        args.attention_file = args.attention_file or (auto_report_dir / "issue.md")

    if args.attention_file and report_needs_attention(report):
        report["attention_file"] = str(args.attention_file)

    if args.github_issue and report_needs_attention(report):
        github_result = publish_github_issue(report, args.github_repo, args.github_label, dry_run=args.github_dry_run)
        report["github_issue"] = github_result
        if not github_result.get("ok"):
            print(f"GitHub issue publish failed: {github_result.get('error')}", file=sys.stderr)

    print(json.dumps(report["summary"], indent=2))
    print("Score:", json.dumps(report["score"], sort_keys=True))
    for item in findings[:50]:
        print(f"[{item.severity}] {item.category} {item.file}:{item.line} - {item.message}")
    if len(findings) > 50:
        print(f"... {len(findings)-50} more findings")
    for t in timings:
        print(f"[http] {t.target} ok={t.ok} status={t.status_code} avg_ms={t.elapsed_ms:.1f} error={t.error or ''}")

    if args.json:
        ensure_parent(args.json)
        args.json.write_text(json.dumps(report, indent=2, default=str))
        print(f"Wrote {args.json}")
    if args.md:
        ensure_parent(args.md)
        write_markdown_report(report, args.md)
        print(f"Wrote {args.md}")
    if args.html:
        ensure_parent(args.html)
        write_html_report(report, args.html)
        print(f"Wrote {args.html}")
    if args.attention_file and report_needs_attention(report):
        write_attention_file(report, args.attention_file)
        print(f"Wrote {args.attention_file}")
    if auto_report_dir:
        reports_base = auto_report_dir.parent
        history_path = append_results_history(report, reports_base)
        print(f"Updated {history_path}")
        if not args.no_index:
            index_path = write_reports_index(reports_base)
            print(f"Updated {index_path}")

    return 1 if report["summary"]["high"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
