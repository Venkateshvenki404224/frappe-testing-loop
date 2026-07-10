# Agent integrations

Frappe Testing Loop can now be used in four ways:

1. Python CLI
2. Agent Skills compatible skill
3. Claude Code skill/plugin
4. Codex skill/plugin

## 1. Python CLI

From the repository root:

```bash
python3 -m frappe_testing_loop.audit --help
```

Optional editable install:

```bash
pip install -e .
frappe-testing-loop --help
```

## 2. Agent Skills compatible package

Canonical skill:

```text
skills/frappe-testing-loop/SKILL.md
```

The skill tells agents how to run:

```text
audit → inspect → fix → native tests → rerun audit → report verified evidence
```

## 3. Claude Code

Claude Code project skill:

```text
.claude/skills/frappe-testing-loop/SKILL.md
```

Claude Code can invoke it as:

```text
/frappe-testing-loop
```

Claude plugin manifest:

```text
.claude-plugin/plugin.json
```

Packaged plugin folder:

```text
plugins/frappe-testing-loop/
```

A Claude Code plugin can package skills under `skills/<skill-name>/SKILL.md`; this repo follows that structure.

## 4. Codex

Codex repository skill:

```text
.agents/skills/frappe-testing-loop/SKILL.md
```

Codex plugin manifest:

```text
.codex-plugin/plugin.json
```

Packaged plugin folder:

```text
plugins/frappe-testing-loop/
```

Codex plugin docs expect:

```text
<plugin>/.codex-plugin/plugin.json
<plugin>/skills/<skill-name>/SKILL.md
```

This repo provides both root-level plugin metadata and a `plugins/frappe-testing-loop/` distributable folder.

## 5. Generic AI coding agents

Agents that do not support skills/plugins should read:

```text
AGENTS.md
```

Claude-specific sessions should also read:

```text
CLAUDE.md
```

## 6. Future MCP support

MCP is the best long-term cross-agent tool protocol. Recommended future tools:

- `audit_static`
- `audit_runtime`
- `generate_report`
- `explain_findings`

MCP should remain optional so the core CLI stays dependency-light.

## Verification commands

```bash
python3 -m compileall frappe_testing_loop
python3 -m frappe_testing_loop.audit --help
python3 -m json.tool .codex-plugin/plugin.json
python3 -m json.tool .claude-plugin/plugin.json
python3 -m json.tool plugins/frappe-testing-loop/.codex-plugin/plugin.json
python3 -m json.tool plugins/frappe-testing-loop/.claude-plugin/plugin.json
```
