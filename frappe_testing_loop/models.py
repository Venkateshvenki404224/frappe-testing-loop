from __future__ import annotations

from dataclasses import dataclass


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
