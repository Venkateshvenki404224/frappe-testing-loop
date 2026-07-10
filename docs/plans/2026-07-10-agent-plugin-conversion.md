# Frappe Testing Loop Agent Plugin Conversion Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Convert Frappe Testing Loop from a standalone repository/CLI into an installable, reusable agent workflow for Claude Code, Codex, and other AI coding agents.

**Architecture:** Keep the existing Python CLI as the execution engine. Add agent-facing wrappers around it: an Agent Skills compatible `SKILL.md`, Claude Code project/plugin metadata, Codex plugin metadata, and generic repository instructions (`AGENTS.md`) so agents can discover and run the loop without re-learning commands.

**Tech Stack:** Python stdlib CLI, Agent Skills open standard (`SKILL.md`), Claude Code skills/plugins (`.claude/skills`, `.claude-plugin/plugin.json`), Codex skills/plugins (`.agents/skills`, `.codex-plugin/plugin.json`), Markdown docs.

---

## Research summary

Verified official sources:

1. **Claude Code skills**
   - Official docs: `https://docs.anthropic.com/en/docs/claude-code/skills.md`
   - Claude Code loads project skills from `.claude/skills/<skill-name>/SKILL.md`.
   - Claude Code skills follow the Agent Skills open standard and can be invoked directly with `/skill-name`.
   - Claude Code plugins can package skills, agents, hooks, MCP servers, and more.

2. **Claude Code plugins**
   - Official docs: `https://docs.anthropic.com/en/docs/claude-code/plugins-reference.md`
   - A plugin can include `skills/<skill>/SKILL.md` and a `.claude-plugin/plugin.json` manifest.
   - Skills-directory plugins can also live under `.claude/skills/<plugin>/.claude-plugin/plugin.json`.

3. **Codex skills**
   - Official docs: `https://developers.openai.com/codex/build-skills.md`
   - Codex skills use the Agent Skills open standard.
   - A skill is a directory with `SKILL.md`, optional `scripts/`, `references/`, `assets/`, and `agents/`.
   - Codex scans repository skills from `.agents/skills`.

4. **Codex plugins**
   - Official docs: `https://developers.openai.com/codex/build-plugins.md`
   - A Codex plugin uses `.codex-plugin/plugin.json`.
   - A plugin can package one or more skills under `skills/`.

5. **MCP**
   - Official docs: `https://modelcontextprotocol.io/docs/getting-started/intro.md`
   - MCP is the cross-agent standard for connecting AI applications to external tools/workflows.
   - MCP should be a later phase because this repo can first expose a portable skill that shells out to the existing CLI.

## Compatibility decision

**Phase 1: Agent Skills + plugin metadata**

Use a skill-first packaging strategy because both Claude Code and Codex officially support Agent Skills. This is the smallest useful conversion and keeps the current CLI untouched.

**Phase 2: MCP server**

Add a stdio MCP server only after Phase 1 is validated. MCP is useful for ChatGPT desktop, Claude Desktop/Code, and other MCP clients, but it adds protocol surface area and dependency/runtime questions.

## Implementation tasks

### Task 1: Add canonical Agent Skill

**Objective:** Create `skills/frappe-testing-loop/SKILL.md` with exact instructions for agents to run audit → inspect → fix → rerun.

**Files:**
- Create: `skills/frappe-testing-loop/SKILL.md`
- Create: `skills/frappe-testing-loop/references/report-interpretation.md`

**Verification:**
- `python3 - <<'PY'` parse YAML-like frontmatter and confirm `name` and `description` exist.

### Task 2: Add Claude Code and Codex repository discovery files

**Objective:** Make the skill available when agents open this repository directly.

**Files:**
- Create: `.claude/skills/frappe-testing-loop/SKILL.md`
- Create: `.agents/skills/frappe-testing-loop/SKILL.md`
- Create: `CLAUDE.md`
- Create: `AGENTS.md`

**Verification:**
- Confirm all four files exist.
- Confirm `.claude/skills/...` and `.agents/skills/...` contain the same frontmatter as the canonical skill.

### Task 3: Add plugin manifests

**Objective:** Make the repository usable as a plugin package for Claude Code and Codex.

**Files:**
- Create: `.codex-plugin/plugin.json`
- Create: `.claude-plugin/plugin.json`
- Create: `plugins/frappe-testing-loop/.codex-plugin/plugin.json`
- Create: `plugins/frappe-testing-loop/.claude-plugin/plugin.json`
- Create: `plugins/frappe-testing-loop/skills/frappe-testing-loop/SKILL.md`

**Verification:**
- `python3 -m json.tool` validates all JSON manifests.

### Task 4: Add install/use documentation

**Objective:** Document how humans and agents should install/use the skill/plugin.

**Files:**
- Create: `docs/agent-integrations.md`
- Modify: `README.md`

**Verification:**
- Confirm docs mention Claude, Codex, Agent Skills, and future MCP.

### Task 5: Validate Python package still works

**Objective:** Ensure plugin conversion does not break the existing CLI.

**Commands:**
```bash
python3 -m compileall frappe_testing_loop
python3 -m frappe_testing_loop.audit --help
python3 -m json.tool .codex-plugin/plugin.json
python3 -m json.tool .claude-plugin/plugin.json
```

**Expected:** All commands pass.

## Future Phase 2 plan: MCP server

Add `frappe_testing_loop/mcp_server.py` exposing tools like:

- `frappe_testing_loop.audit_static`
- `frappe_testing_loop.audit_runtime`
- `frappe_testing_loop.generate_report`
- `frappe_testing_loop.explain_findings`

Use stdio transport first. Keep MCP optional so the CLI remains dependency-light.
