from __future__ import annotations

import html as html_lib
import json
from pathlib import Path
from typing import Any


def write_markdown_report(report: dict[str, Any], path: Path) -> None:
    findings = report.get("findings", [])
    timings = report.get("timings", [])
    apis = report.get("whitelisted_apis", [])
    doctypes = report.get("doctypes", [])
    score = report.get("score", {})

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
        "",
        "## Score",
        "",
        "```json",
        json.dumps(score, indent=2),
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
    score = report.get("score", {})
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
    score_cards = "\n".join(
        f"<div class='card score-{esc(key)}'><div class='label'>Score {esc(key.replace('_', ' ').title())}</div><div class='num'>{esc(value)}</div></div>"
        for key, value in score.items()
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
  <section><h2>Quality score</h2><div class="cards">{score_cards}</div><p class="sub">Lower is better. Hard failures dominate; Ponytail findings are low-weight review prompts.</p></section>

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
