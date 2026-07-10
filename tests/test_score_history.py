import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from frappe_testing_loop.audit import compute_score, Finding, Timing, append_results_history


class ScoreHistoryTests(unittest.TestCase):
    def test_compute_score_weights_hard_failures_warnings_and_ponytail(self):
        report = {
            "summary": {"guest_apis": 2},
            "findings": [
                {"severity": "high", "category": "syntax", "file": "api.py", "line": 1, "message": "bad"},
                {"severity": "warn", "category": "static", "file": "api.py", "line": 2, "message": "raw sql"},
                {"severity": "info", "category": "ponytail", "file": "api.py", "line": 3, "message": "simplify"},
            ],
            "timings": [
                {"target": "route:/app", "ok": False, "status_code": 500, "elapsed_ms": 10.0, "error": "boom"},
            ],
            "bench_results": [
                {"cmd": "bench test", "ok": False, "returncode": 1},
            ],
        }

        score = compute_score(report)

        self.assertEqual(score["high"], 1)
        self.assertEqual(score["warn"], 1)
        self.assertEqual(score["ponytail"], 1)
        self.assertEqual(score["guest_apis"], 2)
        self.assertEqual(score["runtime_failures"], 1)
        self.assertEqual(score["bench_failures"], 1)
        self.assertEqual(score["total"], 2255)
        self.assertEqual(score["status"], "fail")

    def test_compute_score_marks_review_when_only_warnings_or_ponytail_exist(self):
        report = {
            "summary": {"guest_apis": 0},
            "findings": [
                {"severity": "warn", "category": "static", "file": "api.py", "line": 2, "message": "raw sql"},
                {"severity": "info", "category": "ponytail_debt", "file": "api.py", "line": 3, "message": "simplify"},
            ],
            "timings": [],
            "bench_results": [],
        }

        score = compute_score(report)

        self.assertEqual(score["total"], 55)
        self.assertEqual(score["status"], "review")

    def test_compute_score_marks_pass_when_no_findings_or_failures_exist(self):
        report = {"summary": {"guest_apis": 0}, "findings": [], "timings": [], "bench_results": []}

        score = compute_score(report)

        self.assertEqual(score["total"], 0)
        self.assertEqual(score["status"], "pass")

    def test_append_results_history_writes_header_and_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports_dir = Path(tmp)
            report = {
                "app": "sample_app",
                "generated_at": "2026-07-10T08:00:00",
                "report_dir": str(reports_dir / "run-1"),
                "score": {
                    "total": 55,
                    "status": "review",
                    "high": 0,
                    "warn": 1,
                    "ponytail": 1,
                    "guest_apis": 0,
                    "runtime_failures": 0,
                    "bench_failures": 0,
                },
            }

            append_results_history(report, reports_dir)
            append_results_history(report, reports_dir)

            lines = (reports_dir / "results.tsv").read_text().splitlines()
            self.assertEqual(len(lines), 3)
            self.assertEqual(lines[0], "timestamp\tapp\trun_dir\tscore\tstatus\thigh\twarn\tponytail\tguest_apis\truntime_failures\tbench_failures")
            self.assertIn("sample_app", lines[1])
            self.assertIn("\treview\t", lines[1])

    def test_cli_auto_report_writes_score_and_results_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bench = root / "bench"
            app_dir = bench / "apps" / "sample_app" / "sample_app"
            app_dir.mkdir(parents=True)
            (app_dir / "api.py").write_text(
                "import frappe\n\n@frappe.whitelist()\ndef ping():\n    return 'pong'\n"
            )
            reports_dir = root / "reports"

            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "frappe_testing_loop.audit",
                    "--bench",
                    str(bench),
                    "--app",
                    "sample_app",
                    "--no-ponytail",
                    "--reports-dir",
                    str(reports_dir),
                ],
                cwd=Path(__file__).resolve().parents[1],
                check=True,
                text=True,
                capture_output=True,
            )

            run_dirs = [p for p in reports_dir.iterdir() if p.is_dir()]
            self.assertEqual(len(run_dirs), 1)
            report = json.loads((run_dirs[0] / "audit.json").read_text())
            self.assertIn("score", report)
            self.assertEqual(report["score"]["status"], "pass")
            self.assertTrue((reports_dir / "results.tsv").exists())


if __name__ == "__main__":
    unittest.main()
