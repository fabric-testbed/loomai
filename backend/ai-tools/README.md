# ai-tools/ — In-Container AI Tool Configuration

This directory stores configuration, skills, agents, and prompts for the AI
tools that run **inside the fabviz Docker containers** (Aider, OpenCode, Claude
Code CLI).  It is the single source of truth for all in-container AI assets.

> **Not for development-time tooling.**  The `.claude/commands/` directory at
> the project root is for the Claude Code instance used by developers to build
> fabviz itself.  This directory is for the AI tools that *end users* interact
> with through the fabviz web UI.

## Directory Structure

```
ai-tools/
  shared/                 Shared context available to all AI tools
    FABRIC_AI.md          Master FABRIC instructions (becomes AGENTS.md in workspace)
  opencode/               OpenCode-specific configuration
    agents/               Agent persona prompts (*.md)
    skills/               Skill definitions (*.md)
  aider/                  Aider-specific configuration
    .aider.conf.yml       Aider settings and conventions
  claude-code/            Claude Code CLI configuration
    CLAUDE.md             In-container project instructions for Claude Code
```

## How These Files Reach the Container

At build time, the `ai-tools/` directory is copied into the Docker image.  At
runtime, `ai_terminal.py` seeds the user workspace from these files:

- `shared/FABRIC_AI.md` is copied to the workspace as `AGENTS.md`
- `opencode/skills/` are written to `.opencode/skills/<name>/SKILL.md`
- `opencode/agents/` are written to `.opencode/agent-prompts/<name>.md`
- `aider/.aider.conf.yml` is copied to the workspace root
- `claude-code/CLAUDE.md` is placed where Claude Code CLI discovers it

## Adding New Skills or Agents

**OpenCode skill:** Create `opencode/skills/<skill-name>.md` with YAML
frontmatter.  The file name (minus `.md`) becomes the slash command
(`/skill-name`).

**OpenCode agent:** Create `opencode/agents/<agent-name>.md` with a system
prompt.  The file name (minus `.md`) becomes the agent identity.

**Aider conventions:** Edit `aider/.aider.conf.yml` to add model settings,
conventions, or lint commands.

**Claude Code:** Edit `claude-code/CLAUDE.md` to add project instructions that
Claude Code CLI will auto-discover.

## Evaluation and Updates

When updating skills or agents:
1. Edit the files in this directory (not in `backend/app/` or the container)
2. Rebuild the container (`/rebuild`)
3. Start a new AI terminal session to pick up the changes
