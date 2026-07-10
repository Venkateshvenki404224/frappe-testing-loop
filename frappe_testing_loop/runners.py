from __future__ import annotations

import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

from .models import Timing


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
