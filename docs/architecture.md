# Frappe Testing Loop Architecture

Frappe Testing Loop turns a Frappe app audit into a repeatable loop:

```text
static scan → Ponytail review → runtime smoke checks → native Frappe tests → HTML report → fix → rerun
```

## Layers

### 1. Static scanner

Runs without a live site. It scans app files for:

- `@frappe.whitelist()` APIs
- `allow_guest=True`
- duplicate API names/paths
- risky Frappe patterns such as `ignore_permissions=True`, `frappe.db.commit()`, raw SQL, broad exceptions, enqueue usage, and heavy `get_all` usage
- DocType JSON metadata
- hooks such as `doc_events` and `scheduler_events`

### 2. Ponytail layer

Inspired by Dietrich Gebert's Ponytail discipline: before writing more code, check whether the code should exist at all.

It flags review points like:

- concrete over-engineering signals such as custom cache/retry/HTTP/JSON helpers
- large files that might need splitting
- whitelisted API inventory so humans can separately decide whether a method duplicates Frappe's standard REST/resource APIs
- vague `ponytail:` debt comments without revisit triggers

Ponytail findings are not automatic failures. They are simplification prompts.

The static audit also applies first-pass official standards derived from [`frappe/skills`](https://github.com/frappe/skills), including typed whitelisted parameters, explicit whitelisted HTTP methods, mutable default arguments, string-built SQL, and DB calls inside loops.

### 3. Runtime smoke checks

When a Frappe site is running, the loop can time routes and whitelisted API methods:

- `/`
- `/app`
- `/api/method/<dotted.path>`

It records status code, average milliseconds, and request errors.

### 4. Native Frappe tests

This tool does not replace Frappe's own tests. Use it alongside:

```bash
bench --site <site> set-config allow_tests true
bench --site <site> run-tests --app <app> --failfast
bench --site <site> migrate
```

### 5. Human/AI HTML report

The generated HTML report contains:

- summary cards
- runtime timings
- high findings
- warnings grouped by file
- Ponytail findings grouped by file
- info findings
- whitelisted API table
- DocType table
- raw JSON payload for AI agents
- remediation instructions

## Severity meaning

| Severity | Meaning | Action |
|---|---|---|
| `high` | Blocker or likely broken state | Stop and fix first |
| `warn` | Risky or review-worthy pattern | Inspect exact file/line |
| `info` | Useful context | Read if relevant |
| `ponytail` | Simplification/reuse opportunity | Verify before adding code |

## AI remediation loop

Give the generated HTML or JSON report to an AI coding agent and instruct it:

1. Fix `high` findings first.
2. Inspect each warning at exact file/line before editing.
3. For Ponytail findings, check Frappe built-ins and existing app code before writing new code.
4. Make minimal changes.
5. Rerun the audit, runtime checks, and `bench run-tests`.

