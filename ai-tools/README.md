# ai-tools/ — In-Container AI Tool Configuration

This directory stores configuration, skills, agents, and prompts for the AI
tools that run **inside the LoomAI Docker containers** (OpenCode, Aider, Claude
Code CLI, Crush, Deep Agents). It is the single source of truth for all
in-container AI assets.

> **Not for development-time tooling.**  The `.claude/commands/` directory at
> the project root is for the Claude Code instance used by developers to build
> LoomAI itself.  This directory is for the AI tools that *end users* interact
> with through the LoomAI web UI.

## Directory Structure

```
ai-tools/
  shared/                 Shared context, skills, and agents for ALL AI tools
    FABRIC_AI.md          Master FABRIC instructions (becomes AGENTS.md in workspace)
    skills/               Skill definitions (*.md) — available to all tools
    agents/               Agent persona prompts (*.md) — available to all tools
  aider/                  Aider-specific configuration
  claude-code/            Claude Code CLI configuration
    CLAUDE.md             In-container project instructions for Claude Code
  crush/                  Crush-specific configuration
  deepagents/             Deep Agents (LangChain) configuration
    AGENTS.md             Project instructions for Deep Agents
```

## How These Files Reach the Container

At build time, the `ai-tools/` directory is copied into the Docker image. At
runtime, `ai_terminal.py` seeds the user workspace from these files:

- `shared/FABRIC_AI.md` is copied to the workspace as `AGENTS.md`
- `shared/skills/` are seeded into the tool's skill directory
- `shared/agents/` are seeded into the tool's agent directory
- `claude-code/CLAUDE.md` is placed where Claude Code CLI discovers it

## Adding New Skills or Agents

**Skill:** Create `shared/skills/<skill-name>.md` with YAML frontmatter.
The file name (minus `.md`) becomes the slash command (`/skill-name`).

**Agent:** Create `shared/agents/<agent-name>.md` with a system prompt.
The file name (minus `.md`) becomes the agent identity.

**Claude Code:** Edit `claude-code/CLAUDE.md` to add project instructions that
Claude Code CLI will auto-discover.

## Evaluation and Updates

When updating skills or agents:
1. Edit the files in this directory (not in `backend/app/` or the container)
2. Rebuild the container (`/rebuild`)
3. Start a new AI terminal session to pick up the changes
