import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from frappe_testing_loop.audit import compute_score, Finding, Timing, append_results_history, build_issue_body, write_reports_index
from frappe_testing_loop.scanners import whitelist_functions


class ScoreHistoryTests(unittest.TestCase):
    def test_whitelisted_crud_style_names_are_not_ponytail_by_name_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_path = Path(tmp) / "sample_app"
            app_path.mkdir()
            (app_path / "api.py").write_text(
                "import frappe\n\n"
                "@frappe.whitelist()\n"
                "def get_lab_templates():\n"
                "    return []\n\n"
                "@frappe.whitelist()\n"
                "def create_lab():\n"
                "    return {}\n"
            )

            apis, findings = whitelist_functions(app_path)

            self.assertEqual({api["name"] for api in apis}, {"get_lab_templates", "create_lab"})
            self.assertFalse([f for f in findings if f.category == "ponytail"])

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
                "import frappe\n\n@frappe.whitelist(methods=['GET'])\ndef ping() -> str:\n    return 'pong'\n"
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

    def test_build_issue_body_includes_score_and_file_lines(self):
        report = {
            "app": "sample_app",
            "app_path": "/tmp/bench/apps/sample_app",
            "generated_at": "2026-07-10T08:00:00",
            "report_dir": "/tmp/reports/run-1",
            "summary": {"findings": 1, "high": 0, "warn": 1, "guest_apis": 0},
            "score": {"total": 50, "status": "review", "high": 0, "warn": 1, "guest_apis": 0, "runtime_failures": 0, "bench_failures": 0},
            "findings": [{"severity": "warn", "category": "static", "file": "api.py", "line": 7, "message": "Review raw SQL"}],
            "timings": [],
            "bench_results": [],
        }

        body = build_issue_body(report)

        self.assertIn("Frappe Testing Loop alert", body)
        self.assertIn("Status: `review`", body)
        self.assertIn("`api.py:7`", body)

    def test_cli_auto_report_writes_issue_md_for_review_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bench = root / "bench"
            app_dir = bench / "apps" / "sample_app" / "sample_app"
            app_dir.mkdir(parents=True)
            (app_dir / "api.py").write_text(
                "import frappe\n\n@frappe.whitelist()\ndef ping():\n    frappe.db.sql('select 1')\n    return 'pong'\n"
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
            issue_md = run_dirs[0] / "issue.md"
            self.assertTrue(issue_md.exists())
            self.assertIn("Status: `review`", issue_md.read_text())

    def test_cli_github_issue_dry_run_embeds_payload_in_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bench = root / "bench"
            app_dir = bench / "apps" / "sample_app" / "sample_app"
            app_dir.mkdir(parents=True)
            (app_dir / "api.py").write_text(
                "import frappe\n\n@frappe.whitelist()\ndef ping():\n    frappe.db.sql('select 1')\n    return 'pong'\n"
            )
            out_json = root / "audit.json"

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
                    "--no-default-reports",
                    "--json",
                    str(out_json),
                    "--github-issue",
                    "--github-dry-run",
                ],
                cwd=Path(__file__).resolve().parents[1],
                check=True,
                text=True,
                capture_output=True,
            )

            report = json.loads(out_json.read_text())
            self.assertTrue(report["github_issue"]["ok"])
            self.assertTrue(report["github_issue"]["dry_run"])
            self.assertIn("requires attention", report["github_issue"]["title"])

    def test_write_reports_index_builds_dashboard_from_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports_dir = Path(tmp)
            run_dir = reports_dir / "20260710-080000-sample_app-abcd1234"
            run_dir.mkdir()
            (run_dir / "audit.html").write_text("<html>audit</html>")
            report = {
                "app": "sample_app",
                "generated_at": "2026-07-10T08:00:00",
                "report_dir": str(run_dir),
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

            index_path = write_reports_index(reports_dir)
            html = index_path.read_text()

            self.assertTrue(index_path.exists())
            self.assertIn("Frappe Testing Loop Report Index", html)
            self.assertIn("sample_app", html)
            self.assertIn("status-review", html)
            self.assertIn("audit.html", html)

    def test_cli_auto_report_updates_index_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bench = root / "bench"
            app_dir = bench / "apps" / "sample_app" / "sample_app"
            app_dir.mkdir(parents=True)
            (app_dir / "api.py").write_text(
                "import frappe\n\n@frappe.whitelist(methods=['GET'])\ndef ping() -> str:\n    return 'pong'\n"
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

            index_path = reports_dir / "index.html"
            self.assertTrue(index_path.exists())
            self.assertIn("sample_app", index_path.read_text())


if __name__ == "__main__":
    unittest.main()
