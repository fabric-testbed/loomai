# Feature Propagation Process

How to update AI tool context when new LoomAI features are added.

## Architecture

### Source of Truth
- `ai-tools/shared/FABRIC_AI.md` — Master instructions used by tool-specific adapters (~1000 lines)
- `ai-tools/shared/skills/*.md` — Shared skills (slash commands, auto-discovered by tools)
- `ai-tools/shared/agents/*.md` — Shared agent personas
- `ai-tools/shared/evals/*.md` — Static assistant quality eval cases
- `backend/app/routes/ai_terminal.py` -> `_TOOL_PREAMBLES` — Per-tool execution method preambles

### How Instructions Reach Each Tool

| Tool | Instructions | Config | How Updated |
|------|-------------|--------|-------------|
| LoomAI Assistant | In-memory prompt + RAG + selectable agents | settings/default model | Always fresh per request |
| OpenCode | AGENTS.md + .opencode/skills/ + .opencode/agent-prompts/ | opencode.json + MCP scripts | Workspace seeding on launch |
| Aider | AGENTS.md + AI_ASSETS.md (read-only refs) | .aider.conf.yml | Workspace seeding on launch |
| Claude Code | AGENTS.md + CLAUDE.md + .claude/commands/ | user auth/config | Workspace seeding on launch |
| Crush | AGENTS.md + .crush/skills/ + .crush/agents/ | .crush.json | Workspace seeding on launch |
| Deep Agents | AGENTS.md + .deepagents/skills/ + .deepagents/agents/ | .deepagents/config.json | Workspace seeding on launch |
| Antigravity | AGENTS.md + AI_ASSETS.md + .antigravity/skills/ + .antigravity/agents/ | user auth/config | Workspace seeding on launch |
| Codex | AGENTS.md + AI_ASSETS.md + .codex/skills/ + .codex/agents/ | optional ~/.codex/config.toml custom provider | Workspace seeding on launch |
| Jupyter AI | patched Jupyternaut prompt + copied reference context | Jupyter AI provider config | JupyterLab startup |

### AGENTS.md Assembly
`_write_agents_md(cwd, tool_name)` in `ai_terminal.py`:
1. Reads `_TOOL_PREAMBLES[tool_name]` — tool-specific execution method header
2. Reads `ai-tools/shared/FABRIC_AI.md` — shared master instructions
3. Concatenates: preamble + FABRIC_AI.md -> writes `{cwd}/AGENTS.md`

### Propagation Triggers
- **Container build**: `ai-tools/` copied into Docker image
- **Container start**: `seed_ai_tool_defaults()` runs workspace seeding for supported tool workspaces
- **Settings save**: `propagate_ai_configs()` re-runs workspace seeding (background task)
- **New terminal session**: Tool-specific setup re-runs for that tool

## Checklist: Adding a New Feature

When you add a feature that AI tools should know about:

1. **Update `ai-tools/shared/FABRIC_AI.md`**
   - New API endpoint -> "Backend REST API" section
   - New tool call -> "FABRIC Tools" section
   - New CLI command -> reference in relevant section
   - New concept -> add subsection

2. **Add or update skills** (if the feature warrants a slash command):
   - Create `ai-tools/shared/skills/<feature>.md` with canonical Markdown
     frontmatter (see `AI_ASSET_FORMAT.md`)
   - Skills are adapted into each supported tool's native directory or
     generated context index

3. **Add or update evals** when the feature should be protected by assistant
   behavior checks:
   - Create or update `ai-tools/shared/evals/<case>.md`
   - Include expected retrieval domains, tool names, prompt terms, and any
     intent-router expectations

4. **Update preambles** (only if execution methods differ per tool):
   - Edit `_TOOL_PREAMBLES` in `ai_terminal.py`
   - Usually not needed — most features use the same methods across tools

5. **Rebuild container**: `/rebuild` or `docker compose build`
   - This copies updated `ai-tools/` into the image

6. **Re-seed active sessions**:
   - `POST /api/ai/propagate-config` forces supported tool workspaces to re-read configs
   - Or: start a new terminal session for the specific tool

7. **Verify**: Launch each tool and check it knows about the feature

## Per-Tool Execution Methods

| Tool | Primary | Fallback | Tool Calling |
|------|---------|----------|--------------|
| LoomAI Assistant | Function calls (list_slices, ssh_execute, etc.) | `loomai` CLI suggestions for unsupported models | Yes (native) |
| OpenCode | `loomai` CLI | curl, FABlib Python | Yes (MCP servers) |
| Aider | `loomai` CLI | Python scripts | No |
| Claude Code | `loomai` CLI | FABlib Python | No native LoomAI tool calls |
| Crush | `loomai` CLI | FABlib Python | No |
| Deep Agents | `loomai` CLI | FABlib Python | No native LoomAI tool calls |
| Antigravity | `loomai` CLI via `AGENTS.md` guidance | FABlib Python | No native LoomAI tool calls |
| Codex | `loomai` CLI via `AGENTS.md` guidance | FABlib Python | No native LoomAI tool calls |
| Jupyter AI | FABlib notebooks and `loomai` CLI guidance | copied examples/reference context | No native LoomAI tool calls |

## Common Mistakes

- **Editing files in `backend/app/` instead of `ai-tools/`**: The container copies from `ai-tools/` at build time. Changes to runtime copies are ephemeral.
- **Forgetting to rebuild**: Changes to `ai-tools/` only take effect after a container rebuild.
- **Editing AGENTS.md directly**: This file is auto-generated from preamble + FABRIC_AI.md. Edit the sources instead.
- **Updating only one tool**: Use shared files so all supported adapters get the update. Only use per-tool preambles for execution-method differences.
