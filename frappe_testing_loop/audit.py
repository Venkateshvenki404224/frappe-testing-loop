#!/usr/bin/env python3
"""Backward-compatible CLI wrapper for Frappe Testing Loop audits.

Implementation is split across focused modules:
- models.py: shared dataclasses
- scanners.py: static Frappe/Ponytail scanners
- runners.py: bench and HTTP checks
- scoring.py: score/history
- reports.py: Markdown/HTML reports
- alerts.py: issue.md and GitHub issue publishing
- cli.py: argument parsing and orchestration
"""
from __future__ import annotations

from .alerts import *
from .cli import main
from .models import *
from .reports import *
from .runners import *
from .scanners import *
from .scoring import *
from .utils import *


if __name__ == "__main__":
    raise SystemExit(main())
