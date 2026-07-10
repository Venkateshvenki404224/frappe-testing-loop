# Claude Code Instructions

This repository packages Frappe Testing Loop as a CLI plus Claude/Codex-compatible agent skill.

## Always follow

Research → Plan → Implement → Validate → Report verified evidence.

## Claude skill

Project skill path:

```text
.claude/skills/frappe-testing-loop/SKILL.md
```

Canonical skill path:

```text
skills/frappe-testing-loop/SKILL.md
```

Use `/frappe-testing-loop` when auditing or fixing Frappe/ERPNext apps.

## CLI checks

```bash
python3 -m frappe_testing_loop.audit --help
python3 -m compileall frappe_testing_loop
```

## Plugin metadata

Claude plugin manifest:

```text
.claude-plugin/plugin.json
```

Packaged plugin folder:

```text
plugins/frappe-testing-loop/
```
