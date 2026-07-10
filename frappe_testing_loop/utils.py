from __future__ import annotations

from datetime import datetime
import os
import re
import uuid
from pathlib import Path


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


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-._")
    return slug or "app"


def default_reports_base() -> Path:
    """Return the default skill-local reports directory.

    Prefer the path used by this repository/plugin so agents get stable, ignored
    report history without passing --html/--json every run. Fall back to CWD for
    editable/script copies where the repository layout is not present.
    """
    repo_root = Path(__file__).resolve().parents[1]
    repo_skill_reports = repo_root / "skills" / "frappe-testing-loop" / "reports"
    cwd_skill_reports = Path.cwd() / "skills" / "frappe-testing-loop" / "reports"
    if cwd_skill_reports.parent.exists():
        return cwd_skill_reports
    if repo_skill_reports.parent.exists():
        return repo_skill_reports
    return cwd_skill_reports


def create_report_run_dir(app: str, reports_dir: Path | None = None) -> Path:
    base = reports_dir or default_reports_base()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    unique = uuid.uuid4().hex[:8]
    run_dir = base / f"{stamp}-{slugify(app)}-{unique}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
