# Agents & AI Tools

Two distinct agent systems operate in this project: **Claude Code slash commands** (development-time) and **in-container AI tool agents** (runtime).

## Claude Code Slash Commands

13 slash commands available for development work. These are defined as skills in `ai-tools/claude-code/skills/`.

| Command | Role | Key Files |
|---------|------|-----------|
| `/lead <goal>` | Team lead — breaks goals into tasks, delegates to specialists | `docs/TEAM_STATUS.md` |
| `/design <task>` | **UI design authority** — all visual/UX decisions, patterns, consistency | `frontend/src/styles/global.css`, `frontend/src/styles/toolbar.css` |
| `/cli-design <task>` | **CLI design authority** — all CLI output, formatting, interaction decisions | `backend/cli/loomai_cli/output.py`, `backend/cli/loomai_cli/shell.py` |
| `/backend <task>` | Backend specialist — FastAPI, FABlib, Python, CLI (implements `/cli-design` decisions) | `backend/app/`, `backend/cli/` |
| `/frontend <task>` | Frontend specialist — React, TypeScript, CSS (implements `/design` decisions) | `frontend/src/` |
| `/graph <task>` | Graph/visualization — Cytoscape.js, Leaflet, graph_builder | `backend/app/graph_builder.py`, `frontend/src/components/CytoscapeGraph.tsx` |
| `/libraries <task>` | Artifacts — templates, recipes, seeding | `backend/app/routes/templates.py`, `backend/app/routes/artifacts.py` |
| `/artifacts <task>` | FABRIC Artifact Manager — browse, search, get, publish | `backend/app/routes/artifacts.py` |
| `/infra <task>` | Infrastructure — Docker, builds, deployment, nginx | `Dockerfile`, `docker-compose*.yml`, `build/` |
| `/ai-eval [mode] [target]` | In-container AI tool optimization | `backend/ai-tools/` |
| `/test [target]` | Run backend/frontend tests | `backend/tests/`, `frontend/e2e/` |
| `/test-guide <question>` | Test suite specialist — write, debug, extend tests | `backend/tests/`, `frontend/e2e/` |
| `/update_skills` | Review and optimize Claude Code skills | `ai-tools/claude-code/skills/` |

### Agent Coordination

Agents share state through `docs/TEAM_STATUS.md`, which tracks:
- **Current Goal**: The active objective being worked on
- **Active Work**: Tasks currently in progress
- **Completed**: Finished work items with details
- **Blockers**: Issues preventing progress

## In-Container AI Tool Agents

8 agent personas defined in `backend/ai-tools/shared/agents/`. These are available to the in-container AI tools (LoomAI, Aider, OpenCode, Crush, Deep Agents) for FABRIC-specific expertise.

| Agent | File | Expertise |
|-------|------|-----------|
| Fabric Manager | `fabric-manager.md` | Slice lifecycle, resource management, FABlib operations |
| Network Architect | `network-architect.md` | L2/L3 networks, VLANs, facility ports, inter-site connectivity |
| Template Builder | `template-builder.md` | Weave creation, VM templates, boot configs, `weave.json` |
| DevOps Engineer | `devops-engineer.md` | Deployment, monitoring, infrastructure setup on VMs |
| Troubleshooter | `troubleshooter.md` | Debugging slice failures, connectivity issues, SSH problems |
| Data Analyst | `data-analyst.md` | FABRIC Reports API queries, usage analytics, visualization |
| Experiment Designer | `experiment-designer.md` | Experiment topology design, resource selection, methodology |
| AI Tools Evaluator | `ai-tools-evaluator.md` | Assess and optimize AI tool configurations |

## In-Container AI Tool Skills

29 skills defined in `backend/ai-tools/shared/skills/`. These provide step-by-step instructions for common FABRIC operations.

| Skill | File | Purpose |
|-------|------|---------|
| `create-slice` | `create-slice.md` | Build a new slice topology |
| `deploy-slice` | `deploy-slice.md` | Submit and provision a slice |
| `modify-slice` | `modify-slice.md` | Add/remove nodes and components |
| `delete-slice` | `delete-slice.md` | Delete a running slice |
| `renew-slice` | `renew-slice.md` | Extend slice lease |
| `clone-export` | `clone-export.md` | Clone or export a slice |
| `common-tasks` | `common-tasks.md` | Step-by-step recipes for frequent FABRIC operations |
| `interact-slice` | `interact-slice.md` | SSH and execute on VMs |
| `monitor` | `monitor.md` | Enable monitoring, view metrics |
| `create-weave` | `create-weave.md` | Build orchestrated weave artifacts |
| `create-vm-template` | `create-vm-template.md` | Create VM template artifacts |
| `create-recipe` | `create-recipe.md` | Create recipe artifacts |
| `create-tutorial` | `create-tutorial.md` | Create tutorial notebooks |
| `publish-artifact` | `publish-artifact.md` | Publish to FABRIC Artifact Manager |
| `network` | `network.md` | Configure networks and connectivity |
| `sites` | `sites.md` | Query site availability and resources |
| `config` | `config.md` | FABRIC configuration and credentials |
| `ssh-config` | `ssh-config.md` | SSH key and bastion setup |
| `init-project` | `init-project.md` | Initialize a FABRIC project |
| `getting-started` | `getting-started.md` | New user onboarding |
| `fablib` | `fablib.md` | FABlib Python API reference |
| `query-fabric` | `query-fabric.md` | Query FABRIC infrastructure |
| `reports` | `reports.md` | FABRIC Reports API queries |
| `install-software` | `install-software.md` | Install packages on VMs |
| `debug` | `debug.md` | Troubleshoot common issues |
| `benchmark` | `benchmark.md` | Run performance benchmarks |
| `web-tunnel` | `web-tunnel.md` | Set up web app tunnels to VMs |
| `jupyter` | `jupyter.md` | JupyterLab integration |
| `eval-ai-tools` | `eval-ai-tools.md` | Evaluate AI tool configurations |

## Agent & Skill File Locations

All shared FABRIC context for in-container AI tools lives under `backend/ai-tools/shared/`:

| Directory | Contents |
|-----------|----------|
| `backend/ai-tools/shared/skills/` | 29 skill files (`.md`) — step-by-step instructions and recipes |
| `backend/ai-tools/shared/agents/` | 8 agent persona files (`.md`) — role definitions with expertise areas |

### Per-Tool Workspace Seeding

When a tool session starts, `_setup_*_workspace()` functions in `backend/app/routes/ai_terminal.py` copy shared skills and agents into each tool's expected locations:

| Tool | Skills destination | Agents destination |
|------|-------------------|-------------------|
| Crush | `.crush/skills/` | `.crush/agents/` |
| Deep Agents | `.deepagents/skills/` | `.deepagents/agents/` |
| Claude Code | `.claude/commands/<name>.md` (as slash commands) | `AGENTS.md` (workspace root) |
| Aider / OpenCode | Available via `FABRIC_AI.md` context file | Available via `FABRIC_AI.md` context file |

### Background Model Discovery

On startup, the backend discovers the first healthy LLM and persists it as the shared default:

1. **Startup task**: `_model_discovery()` in `app/main.py` lifespan calls `discover_and_persist_default_model()` from `ai_terminal.py`
2. **Probe order**: FABRIC AI server (`ai.fabric-testbed.net`) first, then NRP (`ellm.nrp-nautilus.io`) as fallback, then any custom providers
3. **Persistence**: The first healthy model is saved as `ai.default_model` and `ai.default_model_source` in `settings.json` via `settings_manager.py`
4. **Shared usage**: All AI tools read this default — the model proxy rewrites unknown model names to it, CLI (`loomai`) and chat panel both use the same config
5. **Re-validation**: If a saved default model exists on startup, it is health-checked before being kept; if unhealthy, discovery runs fresh

## How to Add New Skills or Agents

1. **Create a `.md` file** in the appropriate directory:
   - Skills: `backend/ai-tools/shared/skills/<name>.md`
   - Agents: `backend/ai-tools/shared/agents/<name>.md`
2. **Follow the format**: Skills use frontmatter (`name:` and `description:`) followed by markdown body with instructions. Agents are persona definitions with expertise areas and behavioral guidelines.
3. **Rebuild or restart** the container so that `_setup_*_workspace()` functions pick up the new files on next tool session start.
4. **Review with `/update_skills`** — this Claude Code slash command audits all skills for quality, token efficiency, and consistency.
