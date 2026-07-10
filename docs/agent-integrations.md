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

### Install as a Claude Code plugin

This repository includes a Claude marketplace catalog at:

```text
.claude-plugin/marketplace.json
```

Inside Claude Code, add the marketplace and install the plugin:

```text
/plugin marketplace add Venkateshvenki404224/frappe-testing-loop
/plugin install frappe-testing-loop@frappe-testing-loop
```

Then invoke the plugin skill:

```text
/frappe-testing-loop:frappe-testing-loop
```

If Claude Code cannot access the repository, authenticate GitHub first:

```bash
gh auth login
# or expose a token before starting Claude Code
export GITHUB_TOKEN=<token>
```

### Project-local skill fallback

If you are already inside this repository, Claude Code can also discover the project skill directly:

```text
.claude/skills/frappe-testing-loop/SKILL.md
```

Invoke the project skill as:

```text
/frappe-testing-loop
```

### Packaged plugin layout

```text
plugins/frappe-testing-loop/
├── .claude-plugin/plugin.json
└── skills/frappe-testing-loop/SKILL.md
```

A Claude Code plugin packages skills under `skills/<skill-name>/SKILL.md`; this repo follows that structure.

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
