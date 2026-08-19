# ai-tools/ — In-Container AI Tool Configuration

This directory stores configuration, skills, agents, prompts, and retrieval
examples for the AI tools that run **inside the LoomAI Docker containers**:
LoomAI Assistant, Antigravity, Codex, Aider, OpenCode, Crush, Pi, Deep Agents,
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

At build time, the `ai-tools/` directory is copied into the Docker image.
`app.harness_config` renders merge-preserving external harness defaults during
image build and backend startup, and `ai_terminal.py` also seeds the user
workspace from these files:

- `shared/FABRIC_AI.md` is copied to the workspace as `AGENTS.md`
- `shared/skills/` are seeded into native skill directories where supported
- `shared/agents/` are seeded into native agent directories where supported
- `shared/corpus/` is indexed directly by LoomAI RAG with metadata
- `claude-code/CLAUDE.md` is placed where Claude Code CLI discovers it
- Aider receives `AGENTS.md` plus a generated read-only `AI_ASSETS.md` index
- Antigravity and Codex receive `AGENTS.md`, `AI_ASSETS.md`, and parallel
  skill/agent directories
- Jupyter AI receives a patched prompt plus copied reference skills/agents
- `opencode.json`, `.opencode/`, `.aider.conf.yml`, `CONVENTIONS.md`,
  `.crush.json`, `.config/goose/config.yaml`, `~/.codex/config.toml`, and
  per-harness context files are generated as defaults under `/home/fabric/work`
  and `/home/fabric`
- Pi receives `pi/AGENTS.md`, `pi/agent/models.json`,
  `pi/agent/settings.json`, `pi/agent/extensions/loomai-surface-guard.ts`,
  `pi/README.md`, and the `pi/pi-fabric` wrapper. Pi 0.80.3 is
  direct-provider only; it does not have built-in MCP support.

Runtime harness files are defaults, not the source of truth. User-specific
overrides belong in `/home/fabric/work` or `/home/fabric`; the sync process
preserves unowned keys and user files. Re-run it with `loomai tools sync`
(`loomai ai tools sync` also works). The generated mapping and override guide
is `/home/fabric/work/.loomai/harness-defaults/MAPPING.md`.

The WebUI Settings > AI Tools > Harnesses section exposes the same generator
per harness. It shows configured, user-modified, or stale status for OpenCode,
Goose, Pi, Aider, Crush, Codex, and Claude Code, and provides per-harness
Configure/Sync, Reset, Uninstall, and Docs actions. Reset overwrites that
harness's expected generated config files with canonical defaults. Uninstall
removes installed packages and LoomAI-owned runtime state; it preserves config
by default and only removes expected generated config files when the user
selects "Also remove harness configuration". Uninstall refuses to run while the
harness has an active terminal or web process.

After an owner-approved rebuild, run the post-deploy lifecycle parity verifier
from inside the container to exercise install, reset, default uninstall,
remove-config uninstall, and reinstall outcomes for all managed harnesses:

```bash
python3 /app/scripts/verify_harness_lifecycle.py --execute
```

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
5. Run `loomai tools sync` or start a new AI terminal session to pick up the
   changes in an already-running container
6. After deployment, run
   `python3 /app/scripts/verify_harness_lifecycle.py --execute` to verify
   harness install/reset/uninstall/reinstall parity

## Feature Propagation

When adding new features to LoomAI that AI tools should know about, follow the process documented in `docs/FEATURE_PROPAGATION.md`.

Key steps:
1. Update `FABRIC_AI.md` with the new feature documentation
2. Add skills in `shared/skills/` if needed
3. Rebuild the container
4. Re-seed active sessions via `POST /api/ai/tools/sync` or
   `loomai tools sync`; use `POST /api/ai/propagate-config` only for provider
   settings propagation
