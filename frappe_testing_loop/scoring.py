from __future__ import annotations

from pathlib import Path
from typing import Any


def compute_score(report: dict[str, Any]) -> dict[str, Any]:
    """Compute a deterministic quality score for comparing audit runs.

    Lower is better. Hard failures dominate the score; Ponytail findings are
    intentionally low weight because they are review prompts, not blockers.
    """
    findings = report.get("findings", []) or []
    timings = report.get("timings", []) or []
    bench_results = report.get("bench_results", []) or []
    summary = report.get("summary", {}) or {}

    high = sum(1 for f in findings if f.get("severity") == "high")
    warn = sum(1 for f in findings if f.get("severity") == "warn")
    ponytail = sum(1 for f in findings if str(f.get("category", "")).startswith("ponytail"))
    guest_apis = int(summary.get("guest_apis") or 0)
    runtime_failures = sum(1 for t in timings if not t.get("ok", True))
    bench_failures = sum(1 for r in bench_results if not r.get("ok", True))
    slow_routes = sum(1 for t in timings if float(t.get("elapsed_ms") or 0) > 1000)

    total = (
        high * 1000
        + bench_failures * 500
        + runtime_failures * 500
        + guest_apis * 100
        + warn * 50
        + ponytail * 5
        + slow_routes * 20
    )

    if high or bench_failures or runtime_failures:
        status = "fail"
    elif warn or ponytail or guest_apis or slow_routes:
        status = "review"
    else:
        status = "pass"

    return {
        "total": total,
        "status": status,
        "high": high,
        "warn": warn,
        "ponytail": ponytail,
        "guest_apis": guest_apis,
        "runtime_failures": runtime_failures,
        "bench_failures": bench_failures,
        "slow_routes": slow_routes,
    }

RESULTS_HEADER = [
    "timestamp",
    "app",
    "run_dir",
    "score",
    "status",
    "high",
    "warn",
    "ponytail",
    "guest_apis",
    "runtime_failures",
    "bench_failures",
]


def append_results_history(report: dict[str, Any], reports_dir: Path) -> Path:
    """Append one run summary row to reports/results.tsv."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / "results.tsv"
    score = report.get("score", {}) or {}
    if not path.exists():
        path.write_text("\t".join(RESULTS_HEADER) + "\n")
    row = [
        report.get("generated_at") or "",
        report.get("app") or "",
        report.get("report_dir") or "",
        str(score.get("total", 0)),
        score.get("status") or "",
        str(score.get("high", 0)),
        str(score.get("warn", 0)),
        str(score.get("ponytail", 0)),
        str(score.get("guest_apis", 0)),
        str(score.get("runtime_failures", 0)),
        str(score.get("bench_failures", 0)),
    ]
    with path.open("a") as f:
        f.write("\t".join(str(x).replace("\t", " ").replace("\n", " ") for x in row) + "\n")
    return path
