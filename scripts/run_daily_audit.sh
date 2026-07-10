#!/usr/bin/env bash
# Frappe Testing Loop daily cron runner template.
#
# Copy this file into your bench/server, edit the CONFIG section, then add it to cron.
# It writes audit.html, audit.json, review.md, results.tsv, index.html, and issue.md
# for fail/review runs. Optional GitHub issue publishing uses the gh CLI.

set -euo pipefail

# -----------------------------
# CONFIG - edit these values
# -----------------------------
BENCH_PATH="${BENCH_PATH:-/home/frappe/frappe-bench}"
APP_NAME="${APP_NAME:-my_app}"
SITE_NAME="${SITE_NAME:-}"                    # Example: mysite.localhost. Required for --run-bench.
BASE_URL="${BASE_URL:-}"                 # Example: http://localhost:8000. Leave empty for static-only scans.
REPORTS_DIR="${REPORTS_DIR:-$PWD/skills/frappe-testing-loop/reports}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Runtime checks. Space-separated routes/endpoints. Keep empty if site is not running.
ROUTES="${ROUTES:-/ /app}"
ENDPOINTS="${ENDPOINTS:-}"
REPEAT="${REPEAT:-3}"

# Native bench tests. Set RUN_BENCH=1 only when this runner can safely run migrate/tests.
RUN_BENCH="${RUN_BENCH:-0}"

# GitHub issue publishing. Requires authenticated gh CLI.
GITHUB_ISSUE="${GITHUB_ISSUE:-0}"
GITHUB_REPO="${GITHUB_REPO:-}"           # Example: owner/repo
GITHUB_LABEL="${GITHUB_LABEL:-frappe-testing-loop,audit}"

# Optional log file for cron stdout/stderr.
LOG_DIR="${LOG_DIR:-$REPORTS_DIR/logs}"
mkdir -p "$LOG_DIR" "$REPORTS_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y%m%d-%H%M%S)-$APP_NAME.log"

CMD=("$PYTHON_BIN" -m frappe_testing_loop.audit --bench "$BENCH_PATH" --app "$APP_NAME" --reports-dir "$REPORTS_DIR")

if [[ -n "$SITE_NAME" ]]; then
  CMD+=(--site "$SITE_NAME")
fi

if [[ -n "$BASE_URL" ]]; then
  CMD+=(--base-url "$BASE_URL" --repeat "$REPEAT")
  for route in $ROUTES; do
    CMD+=(--route "$route")
  done
  for endpoint in $ENDPOINTS; do
    CMD+=(--endpoint "$endpoint")
  done
fi

if [[ "$RUN_BENCH" == "1" ]]; then
  CMD+=(--run-bench)
fi

if [[ "$GITHUB_ISSUE" == "1" ]]; then
  CMD+=(--github-issue)
  if [[ -n "$GITHUB_REPO" ]]; then
    CMD+=(--github-repo "$GITHUB_REPO")
  fi
  if [[ -n "$GITHUB_LABEL" ]]; then
    CMD+=(--github-label "$GITHUB_LABEL")
  fi
fi

{
  echo "[$(date -Is)] Starting Frappe Testing Loop audit"
  echo "Bench:   $BENCH_PATH"
  echo "App:     $APP_NAME"
  echo "Site:    $SITE_NAME"
  echo "Base URL:${BASE_URL:- static-only}"
  echo "Reports: $REPORTS_DIR"
  echo "Command: ${CMD[*]}"
  "${CMD[@]}"
  echo "[$(date -Is)] Completed. Index: $REPORTS_DIR/index.html"
} 2>&1 | tee -a "$LOG_FILE"
