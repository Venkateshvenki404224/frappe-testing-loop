# Autoresearch-style Frappe Testing Loop Hardening Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make Frappe Testing Loop more robust by borrowing the safe parts of Karpathy's `autoresearch` loop: baseline, bounded experiments, metric-based keep/discard, append-only results, and simple program instructions for agents.

**Architecture:** Keep `frappe_testing_loop.audit` as the deterministic scanner. Add an optional loop runner that repeatedly runs audit/test commands, records metrics in TSV/JSONL, and only keeps code changes that improve a clear score. Do not let the runner blindly edit production apps without git isolation and explicit commands.

**Tech Stack:** Python stdlib, git, existing `frappe_testing_loop.audit`, native Frappe `bench` tests when available.

---

## Verified source idea

Official repo checked: `karpathy/autoresearch`.

Useful patterns from `program.md` and README:

- Start from a fresh branch/tag for each run.
- Establish a baseline first.
- Keep the scope small and explicit.
- Use a fixed budget per experiment.
- Log every run to `results.tsv`.
- Commit before running an experiment.
- If the metric improves, keep the commit.
- If the metric is worse/equal or crashes, reset/discard.
- Keep the evaluation harness read-only.
- Prefer simpler changes when results are equal.

For Frappe Testing Loop, the equivalent is:

```text
baseline audit + tests → agent proposes one small fix → run audit/tests again → score → keep/discard → log → repeat
```

---

## Scoring model for Frappe apps

Karpathy uses `val_bpb` where lower is better. For Frappe apps, use a deterministic quality score where lower is better.

Suggested score:

```text
score =
  high_findings * 1000 +
  runtime_failures * 500 +
  bench_failures * 500 +
  warn_findings * 50 +
  guest_apis * 100 +
  ponytail_findings * 5 +
  slow_routes * 20
```

Rules:

- Any syntax error, duplicate API, failed bench test, or broken runtime route is a hard blocker.
- Ponytail findings are low-weight review prompts, not automatic failures.
- If score is equal, prefer smaller diff / fewer lines / simpler code.
- Never keep a change that improves the score by removing security checks or tests.

---

## Task 1: Add score computation to audit report

**Objective:** Make each report comparable across runs.

**Files:**
- Modify: `frappe_testing_loop/audit.py`
- Test: `tests/test_scoring.py` or a small stdlib test file if no test framework exists yet

**Steps:**

1. Add a `compute_score(report)` function.
2. Count:
   - high findings
   - warn findings
   - ponytail findings
   - guest APIs
   - failed timings
   - failed bench commands
   - slow timings above threshold if threshold exists
3. Store this in the report as:

```json
"score": {
  "total": 1234,
  "high": 1,
  "warn": 4,
  "runtime_failures": 0,
  "bench_failures": 0,
  "guest_apis": 0,
  "ponytail": 3
}
```

4. Show the score card in HTML.
5. Verify:

```bash
python3 -m compileall frappe_testing_loop
python3 -m frappe_testing_loop.audit --help
python3 -m frappe_testing_loop.audit --bench /tmp/ftl-test-bench --app sample_app --no-ponytail --reports-dir /tmp/ftl-reports
python3 -m json.tool /tmp/ftl-reports/*/audit.json
```

---

## Task 2: Add append-only run history

**Objective:** Make it easy to compare multiple runs without opening every folder.

**Files:**
- Modify: `frappe_testing_loop/audit.py`
- Create/update automatically: `skills/frappe-testing-loop/reports/results.tsv`

**Steps:**

1. When automatic reports are enabled, append one row to `results.tsv`.
2. Columns:

```text
timestamp	app	run_dir	score	high	warn	ponytail	guest_apis	runtime_failures	bench_failures	status	description
```

3. Status should be:
   - `pass` if no high findings and no bench/runtime failures
   - `review` if warnings/ponytail exist
   - `fail` if high findings or hard failures exist
4. Keep `results.tsv` ignored by git.
5. Verify two audit runs append two rows.

---

## Task 3: Add a `program.md` for agents

**Objective:** Give Claude/Codex a simple operating contract like Karpathy's `program.md`.

**Files:**
- Create: `program.md`
- Mirror if useful: `plugins/frappe-testing-loop/program.md`

**Content should define:**

- Setup checklist.
- What files the agent can modify.
- What files are read-only.
- Baseline-first rule.
- Audit/test command.
- Results logging.
- Keep/discard rule.
- Stop conditions.

**Important safety difference from autoresearch:** Frappe app code may be real product code, so the loop should not run forever by default. Use a bounded repeat count unless the user explicitly asks for overnight/autonomous mode.

---

## Task 4: Add optional loop runner CLI

**Objective:** Provide an actual bounded loop command.

**Files:**
- Create: `frappe_testing_loop/loop.py`
- Modify: `pyproject.toml` to expose `frappe-testing-loop-run` if desired

**Command shape:**

```bash
python3 -m frappe_testing_loop.loop \
  --bench /path/to/frappe-bench \
  --app benchpress \
  --site frontend \
  --max-runs 5 \
  --audit-command "python3 -m frappe_testing_loop.audit --bench /path/to/frappe-bench --app benchpress --site frontend" \
  --test-command "bench --site frontend run-tests --app benchpress --failfast"
```

**Behavior:**

1. Verify git repo is clean.
2. Create/run on branch `frappe-loop/<timestamp>-<app>`.
3. Run baseline audit.
4. For each run:
   - record current commit
   - let the user/agent make exactly one small change outside the runner
   - run audit/tests
   - compare score to best score
   - keep if improved
   - reset if worse/equal and not simpler
   - append results row
5. Never auto-push.

Because the runner cannot safely create code changes by itself, it should start as an orchestrator around agent/user edits, not a self-editing bot.

---

## Task 5: Improve HTML comparison view

**Objective:** Make reports useful after multiple runs.

**Files:**
- Modify: `frappe_testing_loop/audit.py`
- Optional create: `frappe_testing_loop/report_index.py`

**Features:**

- Add score card.
- Add previous run comparison if `results.tsv` exists.
- Generate `index.html` inside `reports/` listing all runs.
- Show trend:
  - score now vs previous
  - high/warn count delta
  - new guest APIs
  - fixed high findings

---

## Task 6: Add stronger Frappe checks

**Objective:** Improve signal quality beyond static regex.

**Add checks:**

1. Detect broad `except Exception` and bare `except`.
2. Detect unbounded `frappe.get_all` / `frappe.db.get_all` without `limit`.
3. Detect direct `frappe.db.set_value` in controllers without permission discussion.
4. Detect `ignore_permissions=True` near request/user-controlled input.
5. Detect whitelisted methods without obvious permission checks.
6. Detect route/API HTTP 200 with JSON fields `exc`, `exception`, or `_server_messages`.

**Verification:** Run on BenchPress/VPN Management and inspect noise. If noisy, downgrade to `info` or Ponytail instead of `warn/high`.

---

## Task 7: Add tests and fixtures

**Objective:** Stop future changes from breaking scanner behavior.

**Files:**
- Create: `tests/fixtures/sample_frappe_app/...`
- Create: `tests/test_audit_static.py`
- Create: `tests/test_reports.py`
- Create: `tests/test_scoring.py`

**Test cases:**

- whitelisted API discovery
- guest API detection
- duplicate API detection
- DocType JSON parsing
- default report folder creation
- invalid app path does not create report folder
- score calculation
- TSV append

---

## Suggested implementation order

1. Task 1: score computation.
2. Task 2: results.tsv history.
3. Task 5: report index/comparison.
4. Task 7: tests/fixtures.
5. Task 3: `program.md` agent contract.
6. Task 6: stronger Frappe checks.
7. Task 4: optional loop runner.

This order keeps the useful parts first without jumping too fast into an autonomous self-editing runner.

---

## What not to copy directly

Do not copy Karpathy's `LOOP FOREVER` behavior as the default. It makes sense for isolated ML experiments, but Frappe apps may touch product/business logic. Default should be bounded and reviewable.

Do not make the evaluation harness editable by the agent. The audit/scoring code must stay stable during a run, otherwise scores become meaningless.

Do not treat Ponytail findings as hard failures. They should guide simplification, not block deploys by themselves.
