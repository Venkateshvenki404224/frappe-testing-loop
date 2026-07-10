---
name: frappe-testing-loop
description: Run Frappe Testing Loop on Frappe/ERPNext apps to generate HTML/JSON audit reports, inspect risky Frappe patterns, guide fixes, and repeat the audit → fix → verify loop.
---

# Frappe Testing Loop

Use this skill when working on a Frappe or ERPNext app and the user asks to audit, test, validate, debug, review APIs, inspect risky Frappe patterns, or generate an AI-readable HTML report.

## What this skill does

Frappe Testing Loop is an agent workflow around the `frappe-testing-loop` Python CLI. It helps agents avoid blindly editing Frappe apps by producing a grounded report first.

The loop is:

```text
research context → run audit → inspect report → fix smallest useful issue → run native tests → rerun audit → summarize verified results
```

## When to use

Use this skill for:

- Frappe/ERPNext app audits
- BenchPress or VPN Management app validation
- Whitelisted API discovery and review
- Guest API/security review
- risky Frappe patterns such as `ignore_permissions=True`, raw SQL, manual commits, broad exceptions, and custom APIs that may duplicate standard Frappe REST/resource APIs
- generating an HTML report for humans and AI agents
- validating agent-written code before declaring it done

Do **not** use this as a replacement for native Frappe tests. Use both.

## Prerequisites to discover first

Before running commands, identify:

1. Frappe bench path, usually `/home/frappe/frappe-bench`.
2. App name, for example `benchpress` or `vpn_management`.
3. Site name, for example `frontend`, `site.localhost`, or the configured bench site.
4. Whether a Frappe server/container is running.
5. Optional base URL for runtime checks, for example `http://localhost:8000` or `http://benchpress_frontend:8080`.
6. Whether authenticated endpoint checks require username/password or API keys.

If any value is not obvious from the repo/docker compose/bench config, ask or run safe discovery commands before assuming.

## Install/check the CLI

From a clone of this repository:

```bash
python3 -m frappe_testing_loop.audit --help
```

Optional editable install:

```bash
pip install -e .
frappe-testing-loop --help
```

The current CLI is dependency-light and uses Python stdlib.

## Standard local bench audit

```bash
python3 -m frappe_testing_loop.audit \
  --bench /path/to/frappe-bench \
  --app <app_name> \
  --site <site_name> \
  --base-url http://localhost:8000 \
  --route / \
  --route /app
```

If no `--json`, `--md`, or `--html` path is passed, the CLI automatically creates a unique ignored run folder:

```text
skills/frappe-testing-loop/reports/<YYYYMMDD-HHMMSS>-<app_name>-<id>/
├── audit.html
├── audit.json
├── review.md
└── issue.md      # only when status is fail/review
```

Each `audit.json` includes a deterministic `score` block. Lower is better. Hard failures dominate the score, while Ponytail findings are low-weight review prompts. The parent `reports/` folder also gets ignored `results.tsv` and `index.html` files so multiple runs can be compared from one browser dashboard without opening every report.

The static scanner includes first-pass official `frappe/skills` checks for AI-written Frappe code: typed whitelisted parameters, explicit whitelisted HTTP methods, mutable default arguments, string-built SQL, and DB calls inside loops. These checks are deterministic prompts; validate exact file/line context before editing production code.

For scheduled loops, failed/review runs can also produce GitHub-ready alerts. Use `--attention-file <path>` to write an issue body to a specific file, or `--github-issue --github-repo <owner/repo>` to create/update one stable open GitHub issue. Existing open issues with the title `[Frappe Testing Loop] <app> audit requires attention` are commented on instead of creating duplicate daily issues.

For cron automation, use `scripts/run_daily_audit.sh` and `examples/crontab.example`. The runner accepts `BENCH_PATH`, `APP_NAME`, `SITE_NAME`, `BASE_URL`, `ROUTES`, `ENDPOINTS`, `RUN_BENCH`, `REPORTS_DIR`, `GITHUB_ISSUE`, `GITHUB_REPO`, and `GITHUB_LABEL` as environment variables.

Use `--reports-dir <path>` to override the base folder, `--no-index` to skip dashboard updates, or `--no-default-reports` to disable automatic report writing. If no server is running, omit `--base-url`, `--route`, and `--endpoint` and run a static audit first.

## Docker/container workflow

When the app exists inside a backend container, copy the audit script into the container and run it there:

```bash
docker cp frappe_testing_loop/audit.py <backend-container>:/tmp/frappe_app_audit.py

docker exec <backend-container> bash -lc '
python3 /tmp/frappe_app_audit.py \
  --bench /home/frappe/frappe-bench \
  --app <app_name> \
  --site <site_name> \
  --base-url <container-visible-base-url> \
  --route / \
  --route /app \
  --json /tmp/<app_name>-audit.json \
  --html /tmp/<app_name>-audit.html
'

docker cp <backend-container>:/tmp/<app_name>-audit.html ./reports/<app_name>-audit.html
docker cp <backend-container>:/tmp/<app_name>-audit.json ./reports/<app_name>-audit.json
```

## Authenticated API smoke checks

Pass whitelisted method names with repeated `--endpoint` flags:

```bash
python3 -m frappe_testing_loop.audit \
  --bench /path/to/frappe-bench \
  --app <app_name> \
  --site <site_name> \
  --base-url http://localhost:8000 \
  --username Administrator \
  --password '<password>' \
  --endpoint <app_name>.api.some_method \
  --repeat 3
```

Never print or commit passwords, API keys, cookies, or generated reports containing secrets.

## Native Frappe tests to run after fixes

```bash
bench --site <site_name> set-config allow_tests true
bench --site <site_name> run-tests --app <app_name> --failfast
bench --site <site_name> migrate
```

For Docker:

```bash
docker exec <backend-container> bash -lc '
cd /home/frappe/frappe-bench
bench --site <site_name> set-config allow_tests true
bench --site <site_name> run-tests --app <app_name> --failfast
bench --site <site_name> migrate
'
```

## How to interpret reports

Prioritize in this order:

1. `high` findings: syntax errors, duplicate APIs, guest/eval risk. Fix or justify first.
2. `warn` findings: risky Frappe patterns needing review.
3. runtime failures: routes or API endpoints failing or slow.
4. Ponytail findings: simplification opportunities; not automatic failures.
5. `info` findings: inventory/context.

For every fix:

- cite exact file and line from the report
- make the smallest useful change
- rerun the audit
- run native Frappe tests when available
- report what was verified and what remains unverified

## Agent output format

When reporting to the user, include:

```markdown
## Verified
- CLI/report generated: <path>
- Native tests: <command/result>
- Audit rerun: <summary counts>

## Fixed
- <file:line> — <what changed and why>

## Remaining
- <finding or blocker>

## Report
- HTML: <path>
- JSON: <path if generated>
```

Prefer attaching or linking the HTML report when the platform supports it.
