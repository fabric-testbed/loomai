# ai-tools/ — In-Container AI Tool Configuration

This directory stores configuration, skills, agents, prompts, and retrieval
examples for the AI tools that run **inside the LoomAI Docker containers**:
LoomAI Assistant, Antigravity, Codex, Aider, OpenCode, Crush, Deep Agents,
Claude Code CLI, and Jupyter AI. It is the single source of truth for
in-container end-user AI assets.

> **Not for development-time tooling.**  The `.claude/commands/` directory at
> the project root is for the Claude Code instance used by developers to build
> LoomAI itself.  This directory is for the AI tools that *end users* interact
> with through the LoomAI web UI.

## Directory Structure

```
ai-tools/
  shared/                 Shared source context, skills, and agents
    FABRIC_AI.md          Master FABRIC instructions (becomes AGENTS.md in workspace)
    skills/               Skill definitions (*.md) — adapted where supported
    agents/               Agent persona prompts (*.md) — adapted where supported
    corpus/               Curated RAG source maps (*.md)
    evals/                Static assistant quality eval cases (*.md)
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
- `shared/skills/` are seeded into native skill directories where supported
- `shared/agents/` are seeded into native agent directories where supported
- `shared/corpus/` is indexed directly by LoomAI RAG with metadata
- `claude-code/CLAUDE.md` is placed where Claude Code CLI discovers it
- Aider receives `AGENTS.md` plus a generated read-only `AI_ASSETS.md` index
- Antigravity and Codex receive `AGENTS.md`, `AI_ASSETS.md`, and parallel
  skill/agent directories
- Jupyter AI receives a patched prompt plus copied reference skills/agents

## Adding New Skills or Agents

**Skill:** Create `shared/skills/<skill-name>.md` with canonical Markdown
frontmatter. The file name (minus `.md`) becomes the slash command
(`/skill-name`). See `docs/AI_ASSET_FORMAT.md` for the schema.

**Agent:** Create `shared/agents/<agent-name>.md` with canonical Markdown
frontmatter and a system prompt body. The file name (minus `.md`) becomes the
agent identity.

**Claude Code:** Edit `claude-code/CLAUDE.md` to add project instructions that
Claude Code CLI will auto-discover.

## Evaluation and Updates

When updating skills, agents, corpus maps, or evals:
1. Edit the files in this directory (not in `backend/app/` or the container)
2. Keep top-level `ai-tools/` and `backend/ai-tools/` mirrored
3. Run the focused backend AI tests
4. Rebuild the container (`/rebuild`) when runtime assets must update
5. Start a new AI terminal session to pick up the changes

## Feature Propagation

When adding new features to LoomAI that AI tools should know about, follow the process documented in `docs/FEATURE_PROPAGATION.md`.

Key steps:
1. Update `FABRIC_AI.md` with the new feature documentation
2. Add skills in `shared/skills/` if needed
3. Rebuild the container
4. Re-seed active sessions via `POST /api/ai/propagate-config`
