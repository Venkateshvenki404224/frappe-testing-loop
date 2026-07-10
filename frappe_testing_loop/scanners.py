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

def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _is_frappe_whitelist(dec: ast.AST) -> bool:
    return _call_name(dec).startswith("frappe.whitelist")


def _whitelist_has_methods(dec: ast.AST) -> bool:
    return isinstance(dec, ast.Call) and any(kw.arg == "methods" for kw in dec.keywords)


def _mutable_default_name(default: ast.AST) -> str | None:
    if isinstance(default, ast.List):
        return "list"
    if isinstance(default, ast.Dict):
        return "dict"
    if isinstance(default, ast.Set):
        return "set"
    return None


def _is_db_call_name(name: str) -> bool:
    return name.startswith((
        "frappe.db.get_value",
        "frappe.db.get_all",
        "frappe.db.get_list",
        "frappe.db.sql",
        "frappe.get_doc",
        "frappe.get_all",
        "frappe.get_list",
    ))


def scan_official_standards(app_path: Path, include_tests: bool = False) -> list[Finding]:
    """Static checks derived from frappe/skills code-style and frappe-app-dev guidance."""
    findings: list[Finding] = []
    for path in iter_files(app_path, (".py",)):
        if not include_tests and is_test_path(path, app_path):
            continue
        rel = str(path.relative_to(app_path))
        try:
            tree = ast.parse(path.read_text(errors="ignore"))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                positional_args = list(node.args.posonlyargs) + list(node.args.args)
                defaults = [None] * (len(positional_args) - len(node.args.defaults)) + list(node.args.defaults)
                for arg, default in zip(positional_args, defaults):
                    if default is None:
                        continue
                    mutable_type = _mutable_default_name(default)
                    if mutable_type:
                        findings.append(Finding("warn", "python", rel, node.lineno, f"Mutable default argument '{arg.arg}' uses {mutable_type}; use None plus an in-function default"))
                for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
                    if default is None:
                        continue
                    mutable_type = _mutable_default_name(default)
                    if mutable_type:
                        findings.append(Finding("warn", "python", rel, node.lineno, f"Mutable default argument '{arg.arg}' uses {mutable_type}; use None plus an in-function default"))

                whitelist_decorators = [dec for dec in node.decorator_list if _is_frappe_whitelist(dec)]
                if whitelist_decorators:
                    if not any(_whitelist_has_methods(dec) for dec in whitelist_decorators):
                        findings.append(Finding("warn", "api", rel, node.lineno, "Whitelisted method should declare allowed HTTP methods, e.g. @frappe.whitelist(methods=['GET']) or ['POST']"))
                    for arg in positional_args + list(node.args.kwonlyargs):
                        if arg.arg in {"self", "cls"}:
                            continue
                        if arg.annotation is None:
                            findings.append(Finding("warn", "api", rel, node.lineno, f"Whitelisted method parameter '{arg.arg}' should have a type hint so Frappe can validate/cast inputs"))
                    if node.args.vararg:
                        findings.append(Finding("warn", "api", rel, node.lineno, "Whitelisted method should avoid *args; explicit typed parameters are safer"))
                    if node.args.kwarg:
                        findings.append(Finding("warn", "api", rel, node.lineno, "Whitelisted method should avoid **kwargs; explicit typed parameters are safer"))

            if isinstance(node, ast.Call):
                name = _call_name(node)
                if name == "frappe.db.sql" and node.args:
                    first = node.args[0]
                    if isinstance(first, ast.JoinedStr):
                        findings.append(Finding("high", "security", rel, node.lineno, "String-formatted SQL uses an f-string; use parameter substitution or frappe.qb"))
                    elif isinstance(first, ast.BinOp) and isinstance(first.op, (ast.Mod, ast.Add)):
                        findings.append(Finding("high", "security", rel, node.lineno, "String-built SQL uses interpolation/concatenation; use parameter substitution or frappe.qb"))
                    elif isinstance(first, ast.Call) and _call_name(first.func) in {"str.format", "format"}:
                        findings.append(Finding("high", "security", rel, node.lineno, "String-formatted SQL uses format(); use parameter substitution or frappe.qb"))

            if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                for child in ast.walk(node):
                    if isinstance(child, ast.Call) and _is_db_call_name(_call_name(child)):
                        findings.append(Finding("warn", "performance", rel, child.lineno, "DB call inside loop can create N+1 queries; batch-fetch or move the query outside the loop"))
    return findings


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
                    if allow_guest:
                        findings.append(Finding("warn", "api", rel, node.lineno, "Guest API: verify this whitelisted method must be public and has safe permission/data handling"))
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
