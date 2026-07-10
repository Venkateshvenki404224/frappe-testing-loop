# Agent Instructions for Frappe Testing Loop

This repository is both:

1. a Python CLI for auditing Frappe/ERPNext apps, and
2. an Agent Skills compatible package for AI coding agents.

## Required operating loop

For coding/product work in this repo, follow:

```text
Research → Plan → Implement → Validate → Report verified evidence
```

Do not jump directly into edits without first checking the current repo state and relevant docs.

## Main command

```bash
python3 -m frappe_testing_loop.audit --help
```

Example audit:

```bash
python3 -m frappe_testing_loop.audit \
  --bench /path/to/frappe-bench \
  --app <app_name> \
  --site <site_name> \
  --html reports/<app_name>-audit.html \
  --json reports/<app_name>-audit.json
```

## Agent skill

The canonical skill is:

```text
skills/frappe-testing-loop/SKILL.md
```

Codex repository skill mirror:

```text
.agents/skills/frappe-testing-loop/SKILL.md
```

Claude Code project skill mirror:

```text
.claude/skills/frappe-testing-loop/SKILL.md
```

Load/use that skill when auditing Frappe/ERPNext apps.

## Validation before completion

Run at minimum:

```bash
python3 -m compileall frappe_testing_loop
python3 -m frappe_testing_loop.audit --help
```

If plugin metadata changes, validate JSON:

```bash
python3 -m json.tool .codex-plugin/plugin.json
python3 -m json.tool .claude-plugin/plugin.json
```

If auditing a real Frappe app, also run native Frappe tests where possible:

```bash
bench --site <site_name> run-tests --app <app_name> --failfast
```

## Reporting style

Always report:

- what was researched
- what was changed
- exact commands run
- exact report paths
- what passed/failed
- what remains unverified
