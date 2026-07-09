#!/usr/bin/env python3
"""
Starter Frappe app audit script.

Runs static Frappe-specific checks and optional HTTP health checks.
It is intentionally dependency-light: only Python stdlib plus optional requests.

Example:
  python frappe_app_audit.py --bench /home/frappe/frappe-bench --app my_app \
    --site site.localhost --base-url http://localhost:8000 \
    --username Administrator --password admin \
    --endpoint my_app.api.health --route /app --json report.json
"""
from __future__ import annotations

import argparse
import ast
import html as html_lib
import json
import os
import re
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

RISK_PATTERNS = {
    "guest_api": re.compile(r"@frappe\.whitelist\([^\n)]*allow_guest\s*=\s*True", re.I),
    "ignore_permissions": re.compile(r"ignore_permissions\s*=\s*True"),
    "ignore_mandatory": re.compile(r"ignore_mandatory\s*=\s*True"),
    "manual_commit": re.compile(r"frappe\.db\.commit\s*\("),
    "raw_sql": re.compile(r"frappe\.db\.sql\s*\("),
    "eval_exec": re.compile(r"\b(eval|exec)\s*\("),
    "enqueue": re.compile(r"frappe\.enqueue\s*\("),
    "get_all": re.compile(r"frappe\.get_all\s*\(|frappe\.db\.get_all\s*\("),
}

# Ponytail-inspired checks: not correctness checks, only "can this be smaller/reused?" prompts.
# Keep these as review findings, not hard failures.
PONYTAIL_PATTERNS = {
    "abstract_one_impl": re.compile(r"\b(ABC|Protocol|abstractmethod)\b"),
    "custom_cache": re.compile(r"\b(cache|memoize|ttl)\b", re.I),
    "custom_retry": re.compile(r"\b(retry|backoff|exponential)\b", re.I),
    "manual_json_http": re.compile(r"json\.dumps|json\.loads|requests\.", re.I),
    "ponytail_debt": re.compile(r"(#|//)\s*ponytail:\s*(.+)", re.I),
}

STANDARD_FRAPPE_API_HINTS = {
    "get": "frappe.client.get / /api/resource can often replace simple get_* wrappers",
    "get_list": "frappe.client.get_list / /api/resource can often replace simple list wrappers",
    "list": "frappe.client.get_list / /api/resource can often replace simple list wrappers",
    "create": "frappe.client.insert / POST /api/resource can often replace simple create_* wrappers",
    "insert": "frappe.client.insert / POST /api/resource can often replace simple insert wrappers",
    "update": "frappe.client.save / PUT /api/resource can often replace simple update_* wrappers",
    "save": "frappe.client.save / PUT /api/resource can often replace simple save wrappers",
    "delete": "frappe.client.delete / DELETE /api/resource can often replace simple delete wrappers",
}

@dataclass
class Finding:
    severity: str
    category: str
    file: str
    line: int
    message: str

@dataclass
class Timing:
    target: str
    ok: bool
    status_code: int | None
    elapsed_ms: float
    error: str | None = None


def iter_files(root: Path, suffixes: tuple[str, ...]):
    skip = {".git", "node_modules", "__pycache__", ".venv", "env"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fn in filenames:
            if fn.endswith(suffixes):
                yield Path(dirpath) / fn


def is_test_path(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    parts = set(rel.parts)
    return "tests" in parts or path.name.startswith("test_")


def line_no(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def scan_patterns(app_path: Path, include_tests: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_files(app_path, (".py",)):
        if not include_tests and is_test_path(path, app_path):
            continue
        text = path.read_text(errors="ignore")
        rel = str(path.relative_to(app_path))
        for name, pattern in RISK_PATTERNS.items():
            for m in pattern.finditer(text):
                sev = "warn"
                msg = f"Review Frappe-specific risky pattern: {name}"
                if name in {"guest_api", "eval_exec"}:
                    sev = "high"
                if name == "raw_sql":
                    msg = "Review raw SQL for parameterization, permission behavior, and EXPLAIN plan"
                findings.append(Finding(sev, "static", rel, line_no(text, m.start()), msg))
    return findings


def whitelist_functions(app_path: Path, include_tests: bool = False) -> tuple[list[dict[str, Any]], list[Finding]]:
    apis: list[dict[str, Any]] = []
    findings: list[Finding] = []
    by_name: dict[str, list[str]] = {}
    by_dotted: dict[str, list[str]] = {}
    for path in iter_files(app_path, (".py",)):
        if not include_tests and is_test_path(path, app_path):
            continue
        rel = str(path.relative_to(app_path))
        try:
            tree = ast.parse(path.read_text(errors="ignore"))
        except SyntaxError as e:
            findings.append(Finding("high", "syntax", rel, e.lineno or 0, f"Python syntax error: {e.msg}"))
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                is_whitelisted = False
                allow_guest = False
                for dec in node.decorator_list:
                    src = ast.unparse(dec) if hasattr(ast, "unparse") else ""
                    if "frappe.whitelist" in src:
                        is_whitelisted = True
                        if "allow_guest=True" in src.replace(" ", ""):
                            allow_guest = True
                if is_whitelisted:
                    dotted = f"{rel[:-3].replace('/', '.')}.{node.name}"
                    api = {"file": rel, "line": node.lineno, "name": node.name, "endpoint_suffix": dotted, "allow_guest": allow_guest}
                    apis.append(api)
                    by_name.setdefault(node.name, []).append(f"{rel}:{node.lineno}")
                    by_dotted.setdefault(dotted, []).append(f"{rel}:{node.lineno}")
                    lower_name = node.name.lower()
                    verb = lower_name.split("_", 1)[0]
                    if verb in STANDARD_FRAPPE_API_HINTS:
                        findings.append(Finding("info", "ponytail", rel, node.lineno, f"Check if this API can reuse standard Frappe CRUD before custom code: {STANDARD_FRAPPE_API_HINTS[verb]}"))
                    if allow_guest:
                        findings.append(Finding("warn", "ponytail", rel, node.lineno, "Guest API: Ponytail does not simplify security; verify this must be public"))
    for name, locs in by_name.items():
        if len(locs) > 1:
            findings.append(Finding("warn", "api", locs[0].split(":")[0], int(locs[0].split(":")[1]), f"Duplicate whitelisted function name '{name}' at {', '.join(locs)}"))
    for dotted, locs in by_dotted.items():
        if len(locs) > 1:
            findings.append(Finding("high", "api", locs[0].split(":")[0], int(locs[0].split(":")[1]), f"Duplicate whitelisted dotted API '{dotted}' at {', '.join(locs)}"))
    return apis, findings


def scan_doctypes(app_path: Path) -> tuple[list[dict[str, Any]], list[Finding]]:
    doctypes: list[dict[str, Any]] = []
    findings: list[Finding] = []
    for path in iter_files(app_path, (".json",)):
        if "/doctype/" not in str(path).replace(os.sep, "/"):
            continue
        rel = str(path.relative_to(app_path))
        try:
            data = json.loads(path.read_text(errors="ignore"))
        except json.JSONDecodeError as e:
            findings.append(Finding("high", "doctype", rel, e.lineno, f"Invalid DocType JSON: {e.msg}"))
            continue
        if data.get("doctype") == "DocType" or "fields" in data:
            name = data.get("name") or path.stem
            fields = data.get("fields") or []
            perms = data.get("permissions") or []
            doctypes.append({
                "name": name,
                "file": rel,
                "field_count": len(fields),
                "permission_count": len(perms),
                "is_submittable": bool(data.get("is_submittable")),
                "autoname": data.get("autoname"),
            })
            if not perms and not data.get("istable"):
                findings.append(Finding("warn", "doctype", rel, 1, f"DocType '{name}' has no permissions in JSON"))
            mandatory = [f.get("fieldname") for f in fields if f.get("reqd")]
            if data.get("is_submittable") and not mandatory:
                findings.append(Finding("info", "doctype", rel, 1, f"Submittable DocType '{name}' has no mandatory fields; verify this is intended"))
    return doctypes, findings


def scan_hooks(app_path: Path) -> tuple[dict[str, bool], list[Finding]]:
    hooks_path = app_path / "hooks.py"
    result = {"exists": hooks_path.exists(), "doc_events": False, "scheduler_events": False, "override_whitelisted_methods": False, "override_doctype_class": False, "fixtures": False}
    findings: list[Finding] = []
    if not hooks_path.exists():
        findings.append(Finding("info", "hooks", "hooks.py", 0, "No hooks.py found at app root"))
        return result, findings
    text = hooks_path.read_text(errors="ignore")
    for key in list(result.keys()):
        if key != "exists":
            result[key] = re.search(rf"^\s*{key}\s*=", text, re.M) is not None
    if result["scheduler_events"]:
        findings.append(Finding("info", "hooks", "hooks.py", 1, "Scheduler events present; test manually with bench execute and worker logs"))
    if result["override_whitelisted_methods"]:
        findings.append(Finding("warn", "hooks", "hooks.py", 1, "Whitelisted method overrides present; verify compatibility with upstream APIs"))
    return result, findings


def scan_ponytail(app_path: Path, include_tests: bool = False) -> list[Finding]:
    """Ponytail layer: find likely over-engineering/debt; never blocks the run."""
    findings: list[Finding] = []
    for path in iter_files(app_path, (".py", ".js", ".ts", ".vue", ".json", ".md")):
        if not include_tests and is_test_path(path, app_path):
            continue
        rel = str(path.relative_to(app_path))
        text = path.read_text(errors="ignore")
        if path.suffix == ".py":
            for name, pattern in PONYTAIL_PATTERNS.items():
                for match in pattern.finditer(text):
                    if name == "ponytail_debt":
                        note = match.group(2).strip()
                        missing_trigger = not re.search(r"\b(when|until|if|after|trigger|upgrade)\b", note, re.I)
                        msg = f"Ponytail debt marker: {note}"
                        if missing_trigger:
                            msg += " | add a revisit trigger so it does not rot"
                        findings.append(Finding("info", "ponytail_debt", rel, line_no(text, match.start()), msg))
                    elif name == "abstract_one_impl":
                        findings.append(Finding("info", "ponytail", rel, line_no(text, match.start()), "Review abstraction: keep only if there is more than one real implementation/caller"))
                    elif name == "custom_cache":
                        findings.append(Finding("info", "ponytail", rel, line_no(text, match.start()), "Review custom cache: stdlib functools.lru_cache or Frappe cache may be enough"))
                    elif name == "custom_retry":
                        findings.append(Finding("info", "ponytail", rel, line_no(text, match.start()), "Review custom retry/backoff: keep only if failure mode is proven and tested"))
                    elif name == "manual_json_http":
                        findings.append(Finding("info", "ponytail", rel, line_no(text, match.start()), "Review manual JSON/HTTP helper: Frappe client/resource APIs or requests built-ins may already cover it"))
        if path.suffix == ".py" and text.count("\n") > 500:
            findings.append(Finding("info", "ponytail", rel, 1, "Large Python file >500 lines; check if dead/speculative code can be deleted before adding more"))
    return findings


def run_bench(bench: Path, site: str, commands: list[list[str]]) -> list[dict[str, Any]]:
    results = []
    for cmd in commands:
        full = ["bench", "--site", site] + cmd
        start = time.perf_counter()
        try:
            p = subprocess.run(full, cwd=bench, text=True, capture_output=True, timeout=600)
            elapsed = (time.perf_counter() - start) * 1000
            results.append({"cmd": " ".join(full), "ok": p.returncode == 0, "returncode": p.returncode, "elapsed_ms": elapsed, "stdout_tail": p.stdout[-2000:], "stderr_tail": p.stderr[-2000:]})
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            results.append({"cmd": " ".join(full), "ok": False, "elapsed_ms": elapsed, "error": str(e)})
    return results


def http_checks(base_url: str, username: str | None, password: str | None, endpoints: list[str], routes: list[str], repeat: int) -> list[Timing]:
    try:
        import requests
    except ImportError:
        return [Timing("requests", False, None, 0, "Install requests to run HTTP checks")]
    s = requests.Session()
    base_url = base_url.rstrip("/")
    timings: list[Timing] = []
    if username and password:
        try:
            r = s.post(f"{base_url}/api/method/login", data={"usr": username, "pwd": password}, timeout=15)
            timings.append(Timing("login", r.ok, r.status_code, r.elapsed.total_seconds() * 1000, None if r.ok else r.text[:300]))
        except Exception as e:
            timings.append(Timing("login", False, None, 0, str(e)))
    targets = [(f"api:{e}", f"{base_url}/api/method/{e}") for e in endpoints]
    targets += [(f"route:{r}", f"{base_url}/{r.lstrip('/')}") for r in routes]
    for label, url in targets:
        samples = []
        status = None
        err = None
        ok = True
        for _ in range(max(1, repeat)):
            try:
                start = time.perf_counter()
                resp = s.get(url, timeout=30)
                elapsed = (time.perf_counter() - start) * 1000
                samples.append(elapsed)
                status = resp.status_code
                ok = ok and resp.ok
            except Exception as e:
                ok = False
                err = str(e)
        timings.append(Timing(label, ok, status, statistics.mean(samples) if samples else 0, err))
    return timings


def write_markdown_report(report: dict[str, Any], path: Path) -> None:
    findings = report.get("findings", [])
    timings = report.get("timings", [])
    apis = report.get("whitelisted_apis", [])
    doctypes = report.get("doctypes", [])

    def section(title: str) -> list[str]:
        return ["", f"## {title}", ""]

    lines: list[str] = [
        f"# Frappe Audit Report: `{report.get('app')}`",
        "",
        f"App path: `{report.get('app_path')}`",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(report.get("summary", {}), indent=2),
        "```",
    ]

    lines += section("Runtime timings")
    if timings:
        lines += ["| Target | OK | Status | Avg ms | Error |", "|---|---:|---:|---:|---|"]
        for t in timings:
            lines.append(f"| `{t.get('target')}` | {t.get('ok')} | {t.get('status_code')} | {float(t.get('elapsed_ms') or 0):.1f} | {t.get('error') or ''} |")
    else:
        lines.append("No runtime timings collected in this run.")

    lines += section("High findings - fix first")
    high = [f for f in findings if f.get("severity") == "high"]
    if high:
        for f in high:
            lines.append(f"- `{f.get('file')}:{f.get('line')}` **{f.get('category')}** — {f.get('message')}")
    else:
        lines.append("None.")

    lines += section("Warnings - review before production clean")
    warn = [f for f in findings if f.get("severity") == "warn"]
    if warn:
        by_file: dict[str, list[dict[str, Any]]] = {}
        for f in warn:
            by_file.setdefault(f.get("file", ""), []).append(f)
        for file, rows in sorted(by_file.items()):
            lines += ["", f"### `{file}`", ""]
            for f in rows:
                lines.append(f"- L{f.get('line')}: **{f.get('category')}** — {f.get('message')}")
    else:
        lines.append("None.")

    lines += section("Ponytail findings - simplify/reuse/delete opportunities")
    ponytail = [f for f in findings if str(f.get("category", "")).startswith("ponytail")]
    if ponytail:
        by_file = {}
        for f in ponytail:
            by_file.setdefault(f.get("file", ""), []).append(f)
        for file, rows in sorted(by_file.items()):
            lines += ["", f"### `{file}`", ""]
            for f in rows:
                lines.append(f"- L{f.get('line')}: {f.get('message')}")
    else:
        lines.append("None.")

    lines += section("Info findings")
    info = [f for f in findings if f.get("severity") == "info" and not str(f.get("category", "")).startswith("ponytail")]
    if info:
        for f in info:
            lines.append(f"- `{f.get('file')}:{f.get('line')}` **{f.get('category')}** — {f.get('message')}")
    else:
        lines.append("None.")

    lines += section("Whitelisted APIs")
    if apis:
        lines += ["| API | File | Line | Guest |", "|---|---|---:|---:|"]
        for a in apis:
            lines.append(f"| `{a.get('endpoint_suffix')}` | `{a.get('file')}` | {a.get('line')} | {a.get('allow_guest')} |")
    else:
        lines.append("No whitelisted APIs discovered.")

    lines += section("DocTypes")
    if doctypes:
        lines += ["| DocType | File | Fields | Permissions | Submittable |", "|---|---|---:|---:|---:|"]
        for d in doctypes:
            lines.append(f"| `{d.get('name')}` | `{d.get('file')}` | {d.get('field_count')} | {d.get('permission_count')} | {d.get('is_submittable')} |")
    else:
        lines.append("No DocTypes discovered.")

    lines += section("AI remediation instructions")
    lines += [
        "1. Fix `High findings` first; they are blockers.",
        "2. For each warning, inspect the exact file and line before changing anything.",
        "3. For Ponytail findings, do not blindly delete code. First check whether Frappe, stdlib, or existing app code already covers the use case.",
        "4. After changes, rerun this audit, runtime checks, and `bench --site <site> run-tests --app <app> --failfast`.",
    ]

    path.write_text("\n".join(lines) + "\n")


def write_html_report(report: dict[str, Any], path: Path) -> None:
    def esc(value: Any) -> str:
        return html_lib.escape("" if value is None else str(value))

    summary = report.get("summary", {})
    findings = report.get("findings", [])
    timings = report.get("timings", [])
    apis = report.get("whitelisted_apis", [])
    doctypes = report.get("doctypes", [])

    by_severity = {level: [f for f in findings if f.get("severity") == level] for level in ["high", "warn", "info"]}
    ponytail = [f for f in findings if str(f.get("category", "")).startswith("ponytail")]

    def grouped_findings(rows: list[dict[str, Any]], title: str, css_class: str) -> str:
        if not rows:
            return f"<section><h2>{esc(title)}</h2><p class='empty'>None.</p></section>"
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            groups.setdefault(row.get("file", ""), []).append(row)
        parts = [f"<section><h2>{esc(title)} <span class='count'>{len(rows)}</span></h2>"]
        for file, file_rows in sorted(groups.items()):
            parts.append(f"<details open><summary><code>{esc(file)}</code> <span class='count'>{len(file_rows)}</span></summary>")
            parts.append("<table><thead><tr><th>Line</th><th>Severity</th><th>Category</th><th>Message</th></tr></thead><tbody>")
            for f in sorted(file_rows, key=lambda x: int(x.get("line") or 0)):
                parts.append(
                    "<tr class='{css}'><td class='line'>L{line}</td><td>{sev}</td><td>{cat}</td><td>{msg}</td></tr>".format(
                        css=esc(css_class), line=esc(f.get("line")), sev=esc(f.get("severity")), cat=esc(f.get("category")), msg=esc(f.get("message"))
                    )
                )
            parts.append("</tbody></table></details>")
        parts.append("</section>")
        return "\n".join(parts)

    cards = "\n".join(
        f"<div class='card {esc(key)}'><div class='label'>{esc(key.replace('_', ' ').title())}</div><div class='num'>{esc(value)}</div></div>"
        for key, value in summary.items()
    )

    timing_rows = "".join(
        f"<tr><td><code>{esc(t.get('target'))}</code></td><td>{esc(t.get('ok'))}</td><td>{esc(t.get('status_code'))}</td><td>{float(t.get('elapsed_ms') or 0):.1f}</td><td>{esc(t.get('error') or '')}</td></tr>"
        for t in timings
    ) or "<tr><td colspan='5' class='empty'>No runtime timings collected.</td></tr>"

    api_rows = "".join(
        f"<tr><td><code>{esc(a.get('endpoint_suffix'))}</code></td><td><code>{esc(a.get('file'))}</code></td><td>{esc(a.get('line'))}</td><td>{esc(a.get('allow_guest'))}</td></tr>"
        for a in apis
    ) or "<tr><td colspan='4' class='empty'>No whitelisted APIs discovered.</td></tr>"

    doctype_rows = "".join(
        f"<tr><td><code>{esc(d.get('name'))}</code></td><td><code>{esc(d.get('file'))}</code></td><td>{esc(d.get('field_count'))}</td><td>{esc(d.get('permission_count'))}</td><td>{esc(d.get('is_submittable'))}</td></tr>"
        for d in doctypes
    ) or "<tr><td colspan='5' class='empty'>No DocTypes discovered.</td></tr>"

    raw_json = esc(json.dumps(report, indent=2, default=str))
    app = esc(report.get("app"))
    app_path = esc(report.get("app_path"))

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Frappe Audit Report - {app}</title>
<style>
:root {{ --bg:#0b1020; --panel:#121a2f; --muted:#94a3b8; --text:#e5e7eb; --line:#24314f; --high:#ef4444; --warn:#f59e0b; --info:#38bdf8; --ok:#22c55e; --pony:#a78bfa; }}
* {{ box-sizing:border-box; }} body {{ margin:0; background:linear-gradient(135deg,#08111f,#111827 55%,#1e1b4b); color:var(--text); font:14px/1.5 Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; }}
header {{ padding:32px 40px 18px; border-bottom:1px solid var(--line); background:rgba(11,16,32,.82); position:sticky; top:0; z-index:2; backdrop-filter:blur(10px); }}
h1 {{ margin:0 0 6px; font-size:28px; }} .sub {{ color:var(--muted); }} main {{ padding:24px 40px 60px; max-width:1400px; margin:auto; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:18px 0 28px; }} .card {{ background:var(--panel); border:1px solid var(--line); border-radius:16px; padding:16px; box-shadow:0 10px 30px rgba(0,0,0,.18); }}
.card .label {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.08em; }} .card .num {{ font-size:28px; font-weight:800; margin-top:4px; }} .card.high .num {{ color:var(--high); }} .card.warn .num {{ color:var(--warn); }} .card.ponytail .num {{ color:var(--pony); }} .card.guest_apis .num {{ color:var(--ok); }}
section {{ background:rgba(18,26,47,.86); border:1px solid var(--line); border-radius:18px; padding:18px; margin:18px 0; }} h2 {{ margin:0 0 14px; font-size:20px; }} .count {{ color:var(--muted); font-size:12px; font-weight:600; }}
details {{ border:1px solid var(--line); border-radius:12px; margin:10px 0; overflow:hidden; background:#0e172a; }} summary {{ cursor:pointer; padding:12px 14px; color:#f8fafc; }}
table {{ width:100%; border-collapse:collapse; overflow:hidden; }} th,td {{ padding:9px 10px; border-top:1px solid var(--line); text-align:left; vertical-align:top; }} th {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.06em; background:#111c33; }}
code {{ color:#c4b5fd; background:#0b1222; padding:2px 5px; border-radius:6px; }} .line {{ white-space:nowrap; color:#93c5fd; }} .high td:first-child {{ border-left:4px solid var(--high); }} .warn td:first-child {{ border-left:4px solid var(--warn); }} .info td:first-child {{ border-left:4px solid var(--info); }} .pony td:first-child {{ border-left:4px solid var(--pony); }} .empty {{ color:var(--muted); }}
.toolbar {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:14px; }} button {{ border:1px solid var(--line); background:#17223a; color:var(--text); border-radius:10px; padding:8px 12px; cursor:pointer; }} button:hover {{ background:#1f2d4a; }}
pre {{ max-height:460px; overflow:auto; background:#020617; border:1px solid var(--line); border-radius:12px; padding:14px; color:#cbd5e1; }}
</style>
<script>
function openAll() {{ document.querySelectorAll('details').forEach(d => d.open = true); }}
function closeAll() {{ document.querySelectorAll('details').forEach(d => d.open = false); }}
function copyPrompt() {{
  const text = `Use this Frappe audit report to fix issues. Prioritize High findings, then runtime failures, then warnings, then Ponytail simplification findings. Inspect exact file/line before editing. After changes rerun audit + bench tests.`;
  navigator.clipboard.writeText(text);
}}
</script>
</head>
<body>
<header>
  <h1>Frappe Audit Report: <code>{app}</code></h1>
  <div class="sub">App path: <code>{app_path}</code></div>
  <div class="toolbar"><button onclick="openAll()">Open all</button><button onclick="closeAll()">Close all</button><button onclick="copyPrompt()">Copy AI remediation prompt</button></div>
</header>
<main>
  <div class="cards">{cards}</div>

  <section><h2>Runtime timings</h2><table><thead><tr><th>Target</th><th>OK</th><th>Status</th><th>Avg ms</th><th>Error</th></tr></thead><tbody>{timing_rows}</tbody></table></section>

  {grouped_findings(by_severity['high'], 'High findings - fix first', 'high')}
  {grouped_findings(by_severity['warn'], 'Warnings - review before production clean', 'warn')}
  {grouped_findings(ponytail, 'Ponytail findings - simplify/reuse/delete opportunities', 'pony')}
  {grouped_findings([f for f in by_severity['info'] if not str(f.get('category','')).startswith('ponytail')], 'Info findings', 'info')}

  <section><h2>Whitelisted APIs <span class="count">{len(apis)}</span></h2><table><thead><tr><th>API</th><th>File</th><th>Line</th><th>Guest</th></tr></thead><tbody>{api_rows}</tbody></table></section>
  <section><h2>DocTypes <span class="count">{len(doctypes)}</span></h2><table><thead><tr><th>DocType</th><th>File</th><th>Fields</th><th>Permissions</th><th>Submittable</th></tr></thead><tbody>{doctype_rows}</tbody></table></section>

  <section><h2>AI remediation instructions</h2><ol><li>Fix High findings first; they are blockers.</li><li>For each warning, inspect exact file and line before changing anything.</li><li>For Ponytail findings, do not blindly delete code. Check whether Frappe, stdlib, or existing app code already covers the use case.</li><li>After changes, rerun audit, runtime checks, and <code>bench --site &lt;site&gt; run-tests --app &lt;app&gt; --failfast</code>.</li></ol></section>

  <section><details><summary>Raw JSON report</summary><pre>{raw_json}</pre></details></section>
</main>
</body>
</html>
"""
    path.write_text(html)


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
    args = ap.parse_args()

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

    findings = []
    findings += scan_patterns(app_path, include_tests=args.include_tests)
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
    }

    print(json.dumps(report["summary"], indent=2))
    for item in findings[:50]:
        print(f"[{item.severity}] {item.category} {item.file}:{item.line} - {item.message}")
    if len(findings) > 50:
        print(f"... {len(findings)-50} more findings")
    for t in timings:
        print(f"[http] {t.target} ok={t.ok} status={t.status_code} avg_ms={t.elapsed_ms:.1f} error={t.error or ''}")

    if args.json:
        args.json.write_text(json.dumps(report, indent=2, default=str))
        print(f"Wrote {args.json}")
    if args.md:
        write_markdown_report(report, args.md)
        print(f"Wrote {args.md}")
    if args.html:
        write_html_report(report, args.html)
        print(f"Wrote {args.html}")

    return 1 if report["summary"]["high"] else 0

if __name__ == "__main__":
    raise SystemExit(main())
