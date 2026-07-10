from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import Any

from .models import Finding
from .utils import iter_files, is_test_path, line_no


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
